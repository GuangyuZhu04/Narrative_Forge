import json
from copy import deepcopy
from typing import Any, AsyncIterator

import httpx

from app.core.security import decrypt_api_key
from app.llm.contracts import (
    LLMFinishStatus,
    LLMResult,
    LLMStreamEvent,
    LLMToolCall,
    LLMUsage,
)
from app.llm.responses import pop_output_format

from .base import LLMContentFilteredError, LLMOutputTruncatedError, LLMProvider


class AnthropicProvider(LLMProvider):
    API_BASE = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"
    DEFAULT_MODEL = "claude-sonnet-4-6"
    DEFAULT_MAX_TOKENS = 4096
    CHAT_TIMEOUT = httpx.Timeout(600.0, connect=30.0)
    STREAM_TIMEOUT = httpx.Timeout(
        connect=30.0,
        read=None,
        write=30.0,
        pool=30.0,
    )
    MESSAGE_PARAMS = {
        "temperature",
        "top_p",
        "top_k",
        "stop_sequences",
        "metadata",
        "thinking",
        "service_tier",
        "tools",
        "tool_choice",
        "output_config",
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
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            self._raise_for_stop_reason(data.get("stop_reason"))
            return self._parse_result(data)

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
        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/messages",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                last_stop_reason = None
                input_tokens = 0
                output_tokens = 0
                cached_input_tokens = 0
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    event = json.loads(line[5:].lstrip())
                    event_type = event.get("type")
                    if event_type == "message_start":
                        usage = (event.get("message") or {}).get("usage") or {}
                        input_tokens = int(usage.get("input_tokens") or 0)
                        cached_input_tokens = int(
                            usage.get("cache_read_input_tokens") or 0
                        )
                    elif event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield {"type": "content", "content": delta["text"]}
                        elif delta.get("type") in {
                            "thinking_delta",
                            "signature_delta",
                        } and delta.get("thinking"):
                            yield {
                                "type": "thinking",
                                "content": delta["thinking"],
                            }
                    elif event_type == "message_delta":
                        delta = event.get("delta") or {}
                        last_stop_reason = delta.get("stop_reason") or last_stop_reason
                        usage = event.get("usage") or {}
                        output_tokens = int(
                            usage.get("output_tokens") or output_tokens
                        )
                    elif event_type == "message_stop":
                        usage = LLMUsage(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cached_input_tokens=cached_input_tokens,
                        )
                        yield {
                            "type": "usage",
                            "content": "",
                            "usage": usage.to_dict(),
                            "finish_status": self._finish_status(
                                last_stop_reason
                            ).value,
                        }
                    elif event_type == "error":
                        error = event.get("error") or {}
                        raise RuntimeError(error.get("message") or "Anthropic stream failed")
                self._raise_for_stop_reason(last_stop_reason)

    def _build_payload(
        self, messages: list[dict], stream: bool, **kwargs
    ) -> dict:
        params = {**(self.default_params or {}), **kwargs}
        system, converted_messages = self._convert_messages(messages)
        max_tokens = params.pop("max_tokens", None) or params.pop(
            "max_output_tokens", None
        )
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.DEFAULT_MAX_TOKENS,
            "messages": converted_messages,
            "stream": stream,
        }
        if system:
            payload["system"] = system
        output_format = pop_output_format(params)
        if output_format:
            # Anthropic accepts only json_schema here.  A portable json_object
            # request must fall back to the prompt instead of sending an
            # invalid output_config.format type and receiving HTTP 400.
            params.pop("output_config", None)
            if output_format.get("type") == "json_schema":
                output_config: dict[str, Any] = {
                    "format": self._anthropic_output_format(output_format)
                }
                params["output_config"] = output_config
        payload.update(
            {
                key: value
                for key, value in params.items()
                if key in self.MESSAGE_PARAMS and value is not None
            }
        )
        return payload

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        system_parts: list[str] = []
        converted: list[dict] = []
        for message in messages:
            role = message.get("role") or "user"
            content = str(message.get("content") or "")
            if role in {"system", "developer"}:
                system_parts.append(content)
                continue
            anthropic_role = "assistant" if role == "assistant" else "user"
            if converted and converted[-1]["role"] == anthropic_role:
                converted[-1]["content"] += f"\n\n{content}"
            else:
                converted.append({"role": anthropic_role, "content": content})
        if not converted:
            converted.append({"role": "user", "content": ""})
        return "\n\n".join(part for part in system_parts if part).strip() or None, converted

    def _extract_text(self, data: dict) -> str:
        chunks: list[str] = []
        for block in data.get("content") or []:
            if block.get("type") == "text" and block.get("text"):
                chunks.append(block["text"])
        return "".join(chunks)

    def _parse_result(self, data: dict[str, Any]) -> LLMResult:
        output_items: list[dict[str, Any]] = []
        tool_calls: list[LLMToolCall] = []
        for block in data.get("content") or []:
            block_type = block.get("type")
            if block_type == "text":
                output_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": block.get("text") or ""}
                        ],
                    }
                )
            elif block_type == "thinking":
                output_items.append(
                    {
                        "type": "reasoning",
                        "content": deepcopy(block),
                    }
                )
            elif block_type == "tool_use":
                arguments = json.dumps(
                    block.get("input") or {}, ensure_ascii=False, separators=(",", ":")
                )
                tool_call = LLMToolCall(
                    id=str(block.get("id") or ""),
                    name=str(block.get("name") or ""),
                    arguments=arguments,
                )
                tool_calls.append(tool_call)
                output_items.append(tool_call.to_response_item())
        usage_data = data.get("usage") or {}
        usage = LLMUsage(
            input_tokens=int(usage_data.get("input_tokens") or 0),
            output_tokens=int(usage_data.get("output_tokens") or 0),
            cached_input_tokens=int(usage_data.get("cache_read_input_tokens") or 0),
        )
        return LLMResult(
            text=self._extract_text(data),
            output_items=output_items,
            tool_calls=tool_calls,
            usage=usage,
            finish_status=self._finish_status(data.get("stop_reason")),
            response_id=data.get("id"),
            model=data.get("model") or self.model,
        )

    @staticmethod
    def _anthropic_output_format(output_format: dict[str, Any]) -> dict[str, Any]:
        if output_format.get("type") != "json_schema":
            return output_format
        return {
            "type": "json_schema",
            "schema": output_format.get("schema") or {},
        }

    @staticmethod
    def _finish_status(stop_reason: str | None) -> LLMFinishStatus:
        if stop_reason == "tool_use":
            return LLMFinishStatus.TOOL_CALLS
        if stop_reason == "max_tokens":
            return LLMFinishStatus.INCOMPLETE
        if stop_reason in {"refusal", "content_filter"}:
            return LLMFinishStatus.CANCELLED
        return LLMFinishStatus.COMPLETED if stop_reason else LLMFinishStatus.UNKNOWN

    def _raise_for_stop_reason(self, stop_reason: str | None) -> None:
        if stop_reason == "max_tokens":
            raise LLMOutputTruncatedError("LLM output stopped early: max_tokens")
        if stop_reason in {"refusal", "content_filter"}:
            raise LLMContentFilteredError(f"LLM output was filtered: {stop_reason}")

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)
