"""FastAPI server: multi-backend A2UI agent.

Routes:
    POST /api/chat        -- send user message, get A2UI response
    POST /api/chat/stream -- SSE streaming variant
    POST /api/action      -- send UI action event, get updated A2UI response
    GET  /api/config      -- get current provider/model
    POST /api/config      -- switch provider/model
"""

import logging
import os
import re
import uuid

import orjson
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from a2ui_pipeline import build_retry_prompt, get_system_prompt, parse_and_validate
from providers.base import DEFAULT_MAX_TOKENS, get_provider, LLMProvider
from session import SessionStore

# Allowed characters in action names: alphanumeric, underscores, hyphens, dots, spaces
_ACTION_NAME_RE = re.compile(r"^[\w\s.\-]{1,100}$")

_ERROR_TEXT = "Sorry, I had trouble generating the interface. Please try again."

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="A2UI Local Agent", default_response_class=ORJSONResponse)

# Configurable CORS -- restrict in production via CORS_ORIGINS env var
_cors_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions = SessionStore()
_provider: LLMProvider = get_provider()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ActionRequest(BaseModel):
    session_id: str
    action: dict


class ConfigRequest(BaseModel):
    provider: str | None = None
    model: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(session_id: str, text: str = "", a2ui_messages: list | None = None) -> dict:
    return {"text": text, "a2ui_messages": a2ui_messages or [], "session_id": session_id}


async def _try_generate_and_validate(
    provider: LLMProvider,
    session,
    session_id: str,
) -> dict:
    """Single attempt: call LLM, parse, validate. Returns result dict or raises."""
    llm_output = await provider.generate(
        system_prompt=get_system_prompt(),
        messages=session.messages,
        max_tokens=DEFAULT_MAX_TOKENS,
    )
    sessions.add_message(session_id, "assistant", llm_output)

    text, a2ui_messages = parse_and_validate(llm_output)
    return _make_result(session_id, text, a2ui_messages)


# ---------------------------------------------------------------------------
# Core generate-and-validate loop (non-streaming)
# ---------------------------------------------------------------------------

async def _generate_a2ui(
    provider: LLMProvider,
    session_id: str,
    user_text: str,
) -> dict:
    """Run the generate -> parse -> validate -> (retry) loop."""
    session = sessions.get_or_create(session_id)
    sessions.add_message(session_id, "user", user_text)

    max_attempts = 2
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        logger.info(f"Attempt {attempt}/{max_attempts} for session {session_id}")

        if attempt > 1:
            # Remove the failed assistant response before retrying
            if session.messages and session.messages[-1]["role"] == "assistant":
                session.messages.pop()
            retry_query = build_retry_prompt(user_text, last_error)
            sessions.add_message(session_id, "user", retry_query)

        try:
            return await _try_generate_and_validate(provider, session, session_id)
        except Exception as e:
            last_error = f"Validation failed: {e}"
            logger.warning(f"Attempt {attempt} error: {e}")
            if attempt < max_attempts:
                continue

    logger.error("Max retries exhausted")
    return _make_result(session_id, _ERROR_TEXT)


# ---------------------------------------------------------------------------
# SSE streaming generator
# ---------------------------------------------------------------------------

async def _stream_a2ui(provider: LLMProvider, session_id: str, user_text: str):
    """SSE generator: stream text chunks, then emit final parsed A2UI messages."""
    session = sessions.get_or_create(session_id)
    sessions.add_message(session_id, "user", user_text)

    chunks: list[str] = []

    # Stream text chunks as they arrive
    try:
        async for chunk in provider.generate_stream(
            system_prompt=get_system_prompt(),
            messages=session.messages,
            max_tokens=DEFAULT_MAX_TOKENS,
        ):
            chunks.append(chunk)
            yield {
                "event": "chunk",
                "data": orjson.dumps({"text": chunk}).decode(),
            }
    except Exception as e:
        logger.error(f"Stream provider error: {e}")
        yield {"event": "error", "data": orjson.dumps({"error": str(e)}).decode()}
        return

    accumulated = "".join(chunks)
    sessions.add_message(session_id, "assistant", accumulated)

    # Parse and validate the complete response
    try:
        text, a2ui_messages = parse_and_validate(accumulated)
        yield {
            "event": "result",
            "data": orjson.dumps(_make_result(session_id, text, a2ui_messages)).decode(),
        }
    except Exception as e:
        logger.warning(f"Stream validation failed: {e}, retrying non-streaming")
        # Retry once with non-streaming, reusing the shared helper
        if session.messages and session.messages[-1]["role"] == "assistant":
            session.messages.pop()
        sessions.add_message(session_id, "user", build_retry_prompt(user_text, str(e)))

        try:
            result = await _try_generate_and_validate(provider, session, session_id)
            yield {"event": "result", "data": orjson.dumps(result).decode()}
        except Exception as e2:
            logger.error(f"Stream retry also failed: {e2}")
            yield {
                "event": "result",
                "data": orjson.dumps(_make_result(session_id, _ERROR_TEXT)).decode(),
            }

    yield {"event": "done", "data": ""}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    return await _generate_a2ui(_provider, session_id, req.message)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    return EventSourceResponse(_stream_a2ui(_provider, session_id, req.message))


@app.post("/api/action")
async def action(req: ActionRequest):
    action_data = req.action
    action_name = action_data.get("userAction", {}).get("name", "unknown")
    context = action_data.get("userAction", {}).get("context", {})

    if not _ACTION_NAME_RE.match(action_name):
        action_name = "unknown"

    user_text = (
        f"The user clicked the '{action_name}' button. "
        f"Action context: {orjson.dumps(context).decode()}. "
        "Please respond with an updated UI."
    )

    return await _generate_a2ui(_provider, req.session_id, user_text)


@app.get("/api/config")
async def get_config():
    return {"provider": _provider.name, "model": _provider.model}


@app.post("/api/config")
async def set_config(req: ConfigRequest):
    global _provider

    old_provider = _provider
    provider_name = req.provider or _provider.name
    new_provider = get_provider(provider_name)

    if req.model:
        new_provider.model = req.model

    _provider = new_provider  # single atomic assignment

    # Close old provider's resources (connection pools, etc)
    await old_provider.close()

    logger.info(f"Switched to provider={_provider.name}, model={_provider.model}")
    return {"provider": _provider.name, "model": _provider.model}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
