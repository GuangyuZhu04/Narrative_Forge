from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMOutputTruncatedError(RuntimeError):
    """Raised when a provider stops because the output token limit was reached."""


class LLMContentFilteredError(RuntimeError):
    """Raised when a provider stops because output was filtered."""


class LLMProvider(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def chat_completion(self, messages: list[dict], **kwargs) -> str: ...

    @abstractmethod
    async def stream_completion(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]: ...

    @abstractmethod
    def validate_config(self) -> bool: ...
