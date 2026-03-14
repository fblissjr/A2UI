import logging
import os

from providers.base import DEFAULT_MAX_TOKENS, LLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    """Calls Gemini via google-genai SDK."""

    name = "gemini"

    def __init__(self):
        self.model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self._api_key = os.environ.get("GEMINI_API_KEY")
        self._use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() == "TRUE"
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            if self._use_vertex:
                project = os.environ.get("GOOGLE_CLOUD_PROJECT")
                location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
                self._client = genai.Client(vertexai=True, project=project, location=location)
            elif self._api_key:
                self._client = genai.Client(api_key=self._api_key)
            else:
                raise RuntimeError(
                    "Gemini provider requires GEMINI_API_KEY or "
                    "GOOGLE_GENAI_USE_VERTEXAI=TRUE with GOOGLE_CLOUD_PROJECT set."
                )
        return self._client

    def _build_contents(self, messages: list[dict]):
        from google.genai import types

        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            msg_content = msg["content"]
            msg_text = msg_content if isinstance(msg_content, str) else msg_content[0]["text"]
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg_text)]))
        return contents

    def _build_config(self, system_prompt: str, max_tokens: int):
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        )

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        client = self._get_client()
        contents = self._build_contents(messages)
        config = self._build_config(system_prompt, max_tokens)

        logger.info(f"Calling Gemini (model={self.model}, {len(contents)} messages)")

        response = await client.aio.models.generate_content(
            model=self.model, contents=contents, config=config,
        )

        result = response.text or ""
        logger.info(f"Gemini response: {len(result)} chars")
        return result

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        """Yield text chunks from Gemini streaming API."""
        client = self._get_client()
        contents = self._build_contents(messages)
        config = self._build_config(system_prompt, max_tokens)

        logger.info(f"Streaming from Gemini (model={self.model}, {len(contents)} messages)")

        async for chunk in await client.aio.models.generate_content_stream(
            model=self.model, contents=contents, config=config,
        ):
            if chunk.text:
                yield chunk.text
