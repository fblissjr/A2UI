import logging
import os
import re

import httpx
import orjson

from providers.base import DEFAULT_MAX_TOKENS, LLMProvider

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)


class LocalProvider(LLMProvider):
    """Calls heylookitsanllm /v1/messages via httpx (Anthropic Messages format)."""

    name = "local"

    def __init__(self):
        self.base_url = os.environ.get("HEYLOOK_URL", "http://localhost:8080")
        self.model = os.environ.get("HEYLOOK_MODEL", "google_gemma-3-27b-it-mlx-bf16")
        self.timeout = float(os.environ.get("HEYLOOK_TIMEOUT", "120"))
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _build_payload(self, system_prompt: str, messages: list[dict], max_tokens: int, stream: bool) -> dict:
        return {
            "model": self.model,
            "system": system_prompt,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        payload = self._build_payload(system_prompt, messages, max_tokens, stream=False)

        client = await self._get_client()
        logger.info(f"Calling {self.base_url}/v1/messages (model={self.model})")
        resp = await client.post(f"{self.base_url}/v1/messages", json=payload)
        resp.raise_for_status()
        data = resp.json()

        # Extract text from content blocks, skip thinking blocks
        text_parts = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
        full_text = _THINK_RE.sub("", "\n".join(text_parts)).strip()

        logger.info(f"Local response: {len(full_text)} chars, usage={data.get('usage', {})}")
        return full_text

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        """Yield text chunks as they arrive from heylookitsanllm SSE stream.

        Only yields text_delta content -- thinking deltas are skipped at the
        source (heylookitsanllm separates them into thinking blocks).
        """
        payload = self._build_payload(system_prompt, messages, max_tokens, stream=True)

        client = await self._get_client()
        logger.info(f"Streaming from {self.base_url}/v1/messages (model={self.model})")

        async with client.stream("POST", f"{self.base_url}/v1/messages", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = orjson.loads(line[6:])
                except Exception:
                    continue

                event_type = event.get("type", "")
                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield delta.get("text", "")
                elif event_type == "message_stop":
                    break
