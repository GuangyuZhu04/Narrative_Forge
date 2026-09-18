from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.llm.contracts import LLMFinishStatus, LLMResult, LLMStreamEvent


class LLMOutputTruncatedError(RuntimeError):
    """Raised when a provider stops because the output token limit was reached."""


class LLMContentFilteredError(RuntimeError):
    """Raised when a provider stops because output was filtered."""


class LLMStreamProtocolError(RuntimeError):
    """Raised when a provider stream ends before a terminal event."""


class LLMProviderConfigurationError(ValueError):
    """Raised when a model/API-surface combination is unsupported."""


class LLMProvider(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def chat_completion(self, messages: list[dict], **kwargs) -> str: ...

    async def response(self, messages: list[dict], **kwargs) -> LLMResult:
        """Rich response API with a compatibility fallback for custom providers."""

        text = await self.chat_completion(messages, **kwargs)
        return LLMResult(text=text, finish_status=LLMFinishStatus.COMPLETED)

    @abstractmethod
    async def stream_completion(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]: ...

    async def stream_completion_events(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        async for chunk in self.stream_completion(messages, **kwargs):
            yield {
                "type": "content" if chunk else "ping",
                "content": chunk,
            }

    @abstractmethod
    def validate_config(self) -> bool: ...
