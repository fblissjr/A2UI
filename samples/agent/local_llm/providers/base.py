import os
from abc import ABC, abstractmethod
from typing import AsyncIterator, Literal

Role = Literal["user", "assistant"]

DEFAULT_MAX_TOKENS = 4096


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str
    model: str

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Return the full text response from the LLM."""
        ...

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncIterator[str]:
        """Yield text chunks as they arrive. Default: fall back to non-streaming."""
        result = await self.generate(system_prompt, messages, max_tokens)
        yield result

    async def close(self) -> None:
        """Release resources (connection pools, etc). Override in subclasses."""


def get_provider(name: str | None = None) -> LLMProvider:
    """Factory: return a provider instance by name.

    Reads A2UI_PROVIDER env var if name is not given.
    """
    name = name or os.environ.get("A2UI_PROVIDER", "local")

    if name == "local":
        from providers.local import LocalProvider

        return LocalProvider()
    elif name == "gemini":
        from providers.gemini import GeminiProvider

        return GeminiProvider()
    else:
        raise ValueError(f"Unknown provider: {name!r}. Use 'local' or 'gemini'.")
