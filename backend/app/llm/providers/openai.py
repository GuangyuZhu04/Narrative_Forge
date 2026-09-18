from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, AsyncIterator

import httpx

from app.core.security import decrypt_api_key
from app.llm.contracts import LLMResult, LLMStreamEvent
from app.llm.responses import (
    convert_messages_to_responses,
    normalize_responses_tools,
    parse_responses_result,
    pop_output_format,
    usage_stream_event,
)

from .base import (
    LLMContentFilteredError,
    LLMOutputTruncatedError,
    LLMProvider,
    LLMStreamProtocolError,
)


class OpenAIProvider(LLMProvider):
    API_BASE = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-5.5"
    CHAT_TIMEOUT = httpx.Timeout(600.0, connect=30.0)
    STREAM_TIMEOUT = httpx.Timeout(
        connect=30.0,
        read=None,
        write=30.0,
        pool=30.0,
    )
    RESPONSE_PARAMS = {
        "temperature",
        "top_p",
        "reasoning",
        "text",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "store",
        "service_tier",
        "metadata",
        "include",
        "background",
        "truncation",
        "max_tool_calls",
        "prompt_cache_key",
        "safety_identifier",
    }

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = decrypt_api_key(config["api_key_encrypted"])
        self.model = config.get("model_name") or self.DEFAULT_MODEL
        self.base_url = (config.get("base_url") or self.API_BASE).rstrip("/")
        self.default_params = config.get("default_params") or {}

    async def response(self, messages: list[dict], **kwargs) -> LLMResult:
        payload = self._build_payload(messages, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=self.CHAT_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/responses",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        self._raise_for_response_status(data)
        return parse_responses_result(data)

    async def chat_completion(self, messages: list[dict], **kwargs) -> str:
        return (await self.response(messages, **kwargs)).text

    async def stream_completion(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        async for event in self.stream_completion_events(messages, **kwargs):
            if event.get("type") == "content":
                yield event.get("content", "")

    async def stream_completion_events(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        payload = self._build_payload(messages, stream=True, **kwargs)
        terminal_seen = False
        current_event_type: str | None = None
        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/responses",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event_type = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw_data = line[5:].lstrip()
                    if raw_data == "[DONE]":
                        continue
                    event = json.loads(raw_data)
                    event_type = (
                        event.get("type")
                        or event.get("event")
                        or current_event_type
                    )
                    if event_type == "response.output_text.delta":
                        if delta := event.get("delta"):
                            yield {"type": "content", "content": str(delta)}
                    elif event_type in {
                        "response.reasoning_text.delta",
                        "response.reasoning_summary_text.delta",
                    }:
                        if delta := event.get("delta"):
                            yield {"type": "thinking", "content": str(delta)}
                    elif event_type == "response.function_call_arguments.delta":
                        yield {
                            "type": "tool_call_delta",
                            "content": str(event.get("delta") or ""),
                            "call_id": str(event.get("call_id") or ""),
                            "name": str(event.get("name") or ""),
                        }
                    elif event_type == "response.output_item.done":
                        if item := event.get("item"):
                            yield {
                                "type": "output_item",
                                "content": "",
                                "item": deepcopy(item),
                            }
                    elif event_type == "response.completed":
                        terminal_seen = True
                        response_data = event.get("response") or event
                        self._raise_for_response_status(response_data)
                        yield usage_stream_event(
                            parse_responses_result(response_data)
                        )
                        break
                    elif event_type == "response.incomplete":
                        terminal_seen = True
                        self._raise_for_response_status(
                            event.get("response") or {"status": "incomplete"}
                        )
                    elif event_type in {
                        "response.failed",
                        "response.cancelled",
                        "error",
                    }:
                        terminal_seen = True
                        response_data = event.get("response") or {
                            "status": (
                                "failed"
                                if event_type == "error"
                                else event_type.removeprefix("response.")
                            ),
                            "error": event.get("error"),
                        }
                        self._raise_for_response_status(response_data)
        if not terminal_seen:
            raise LLMStreamProtocolError(
                "OpenAI Responses stream ended without a terminal event"
            )

    def _build_payload(
        self, messages: list[dict], stream: bool, **kwargs
    ) -> dict:
        params: dict[str, Any] = {**self.default_params, **kwargs}
        instructions, input_items = convert_messages_to_responses(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_items or "",
            "stream": stream,
        }
        if instructions:
            payload["instructions"] = instructions

        max_tokens = self._pop_first(
            params,
            "max_output_tokens",
            "max_completion_tokens",
            "max_tokens",
        )
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens

        output_format = pop_output_format(params)
        if output_format:
            text_config = params.get("text") or {}
            params["text"] = {**text_config, "format": output_format}
        if verbosity := params.pop("verbosity", None):
            text_config = params.get("text") or {}
            params["text"] = {**text_config, "verbosity": verbosity}
        if tools := params.get("tools"):
            params["tools"] = normalize_responses_tools(tools)

        payload.update(
            {
                key: value
                for key, value in params.items()
                if key in self.RESPONSE_PARAMS and value is not None
            }
        )
        return payload

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        return convert_messages_to_responses(messages)

    def _extract_text(self, data: dict) -> str:
        return parse_responses_result(data).text

    def _raise_for_response_status(self, data: dict) -> None:
        status = data.get("status")
        if status == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason")
            if reason in {"max_output_tokens", "max_tokens"}:
                raise LLMOutputTruncatedError(
                    f"LLM output stopped early: {reason}"
                )
            if reason in {"content_filter", "safety"}:
                raise LLMContentFilteredError(
                    f"LLM output was filtered: {reason}"
                )
            raise RuntimeError(f"OpenAI response incomplete: {reason or 'unknown'}")
        if status == "failed":
            error = data.get("error") or {}
            raise RuntimeError(error.get("message") or "OpenAI response failed")
        if status == "cancelled":
            raise LLMContentFilteredError("OpenAI response was cancelled")

    @staticmethod
    def _pop_first(params: dict[str, Any], *keys: str) -> Any:
        result = None
        found = False
        for key in keys:
            value = params.pop(key, None)
            if not found and value is not None:
                result = value
                found = True
        return result

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)
