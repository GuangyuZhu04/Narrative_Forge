"""Shared conversion and parsing helpers for Responses-style APIs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.llm.contracts import (
    LLMFinishStatus,
    LLMResult,
    LLMToolCall,
    LLMUsage,
)


RESPONSES_ITEM_TYPES = {
    "message",
    "function_call",
    "function_call_output",
    "reasoning",
    "web_search_call",
}


def convert_messages_to_responses(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert chat messages while retaining Responses semantic history items.

    DeepSeek Responses is stateless, so callers can feed a previous ``output``
    list back into this function together with the next user message.  Tool and
    reasoning items are intentionally not flattened into prose.
    """

    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []

    for source in messages:
        item = deepcopy(source)
        item_type = item.get("type")
        if item_type in RESPONSES_ITEM_TYPES:
            input_items.append(item)
            continue

        role = item.get("role") or "user"
        content = item.get("content")
        if role in {"system", "developer"}:
            instructions.append(_content_to_text(content))
            continue

        if role == "tool":
            call_id = item.get("call_id") or item.get("tool_call_id")
            if call_id:
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(call_id),
                        "output": content if content is not None else "",
                    }
                )
            continue

        message_content = content if content is not None else ""
        tool_calls = item.get("tool_calls") or []
        if message_content != "" or not tool_calls:
            input_items.append(
                {
                    "role": "assistant" if role == "assistant" else "user",
                    "content": deepcopy(message_content),
                }
            )
        for tool_call in tool_calls:
            function = tool_call.get("function") or tool_call
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": str(
                        tool_call.get("call_id") or tool_call.get("id") or ""
                    ),
                    "name": str(function.get("name") or ""),
                    "arguments": function.get("arguments") or "",
                }
            )

    instruction_text = "\n\n".join(
        part for part in instructions if part
    ).strip()
    return instruction_text or None, input_items


def normalize_responses_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Accept Chat- or Responses-shaped function definitions."""

    normalized: list[dict[str, Any]] = []
    for source in tools or []:
        tool = deepcopy(source)
        if tool.get("type") != "function" or "function" not in tool:
            normalized.append(tool)
            continue
        function = tool.pop("function") or {}
        normalized.append(
            {
                "type": "function",
                **{
                    key: value
                    for key, value in function.items()
                    if key in {"name", "description", "parameters", "strict"}
                    and value is not None
                },
            }
        )
    return normalized


def normalize_chat_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Accept Responses- or Chat-shaped function definitions."""

    normalized: list[dict[str, Any]] = []
    for source in tools or []:
        tool = deepcopy(source)
        if tool.get("type") != "function" or "function" in tool:
            normalized.append(tool)
            continue
        function = {
            key: tool[key]
            for key in ("name", "description", "parameters", "strict")
            if key in tool and tool[key] is not None
        }
        normalized.append({"type": "function", "function": function})
    return normalized


def pop_output_format(params: dict[str, Any]) -> dict[str, Any] | None:
    """Pop legacy/portable structured-output arguments into Responses format."""

    response_format = params.pop("response_format", None)
    json_schema = params.pop("json_schema", None)
    schema_name = params.pop("schema_name", None) or params.pop(
        "response_schema_name", None
    )

    if json_schema is not None:
        if isinstance(json_schema, dict) and json_schema.get("type") == "json_schema":
            response_format = json_schema
        else:
            response_format = {
                "type": "json_schema",
                "name": schema_name or "response",
                "schema": json_schema,
                "strict": True,
            }

    if not isinstance(response_format, dict):
        return None
    normalized = deepcopy(response_format)
    if normalized.get("type") != "json_schema":
        return normalized

    nested = normalized.pop("json_schema", None)
    if isinstance(nested, dict):
        for key in ("name", "description", "schema", "strict"):
            if key in nested and key not in normalized:
                normalized[key] = nested[key]
    normalized.setdefault("name", schema_name or "response")
    normalized.setdefault("strict", True)
    return normalized


def parse_responses_result(data: dict[str, Any]) -> LLMResult:
    output_items = deepcopy(data.get("output") or [])
    text_chunks: list[str] = []
    tool_calls: list[LLMToolCall] = []

    for item in output_items:
        if item.get("type") == "function_call":
            tool_calls.append(
                LLMToolCall(
                    id=str(item.get("call_id") or item.get("id") or ""),
                    name=str(item.get("name") or ""),
                    arguments=str(item.get("arguments") or ""),
                    status=item.get("status"),
                )
            )
        for content in item.get("content") or []:
            if content.get("type") in {"output_text", "text"}:
                if content.get("text"):
                    text_chunks.append(str(content["text"]))

    text = data.get("output_text")
    if not isinstance(text, str):
        text = "".join(text_chunks)
    status = _finish_status(data.get("status"))
    return LLMResult(
        text=text,
        output_items=output_items,
        tool_calls=tool_calls,
        usage=parse_responses_usage(data.get("usage") or {}),
        finish_status=status,
        response_id=data.get("id"),
        model=data.get("model"),
    )


def parse_responses_usage(usage: dict[str, Any]) -> LLMUsage:
    input_details = usage.get("input_tokens_details") or usage.get(
        "prompt_tokens_details"
    ) or {}
    output_details = usage.get("output_tokens_details") or usage.get(
        "completion_tokens_details"
    ) or {}
    input_tokens = _integer(usage.get("input_tokens", usage.get("prompt_tokens")))
    output_tokens = _integer(
        usage.get("output_tokens", usage.get("completion_tokens"))
    )
    cached_tokens = _integer(input_details.get("cached_tokens"))
    cached_tokens = cached_tokens or _integer(usage.get("prompt_cache_hit_tokens"))
    cached_tokens = cached_tokens or _integer(usage.get("cached_tokens"))
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_integer(usage.get("total_tokens")),
        cached_input_tokens=cached_tokens,
        reasoning_tokens=(
            _integer(output_details.get("reasoning_tokens"))
            or _integer(usage.get("reasoning_tokens"))
        ),
    )


def usage_stream_event(result: LLMResult) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "usage",
        "content": "",
        "usage": result.usage.to_dict(),
        "finish_status": result.finish_status.value,
    }
    if result.response_id:
        event["response_id"] = result.response_id
    if result.model:
        event["model"] = result.model
    return event


def _finish_status(status: Any) -> LLMFinishStatus:
    try:
        return LLMFinishStatus(str(status))
    except ValueError:
        return LLMFinishStatus.UNKNOWN


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict) and part.get("text"):
                chunks.append(str(part["text"]))
        return "".join(chunks)
    return "" if content is None else str(content)
