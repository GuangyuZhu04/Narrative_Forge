"""Provider-neutral contracts for LLM requests and responses.

The application historically reduced every provider response to a string.  The
string API remains available, but these contracts retain the information an
agent loop needs (tool calls, finish state and token/cache usage).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal, TypedDict


class LLMFinishStatus(str, Enum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TOOL_CALLS = "tool_calls"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        if not self.total_tokens:
            self.total_tokens = self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments: str
    type: str = "function"
    status: str | None = None

    def to_response_item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "type": "function_call",
            "call_id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }
        if self.status:
            item["status"] = self.status
        return item


@dataclass(slots=True)
class LLMResult:
    text: str = ""
    output_items: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    finish_status: LLMFinishStatus = LLMFinishStatus.UNKNOWN
    response_id: str | None = None
    model: str | None = None


class LLMStreamEvent(TypedDict, total=False):
    type: Literal[
        "content",
        "thinking",
        "tool_call_delta",
        "output_item",
        "usage",
        "ping",
    ]
    content: str
    item: dict[str, Any]
    call_id: str
    name: str
    usage: dict[str, int]
    finish_status: str
    response_id: str
    model: str

