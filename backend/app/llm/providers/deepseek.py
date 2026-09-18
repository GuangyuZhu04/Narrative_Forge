from __future__ import annotations

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
)
from app.llm.responses import (
    convert_messages_to_responses,
    normalize_chat_tools,
    normalize_responses_tools,
    parse_responses_result,
    parse_responses_usage,
    pop_output_format,
    usage_stream_event,
)

from .base import (
    LLMContentFilteredError,
    LLMOutputTruncatedError,
    LLMProvider,
    LLMProviderConfigurationError,
    LLMStreamProtocolError,
)


class DeepSeekProvider(LLMProvider):
    API_BASE = "https://api.deepseek.com"
    TRUNCATED_FINISH_REASONS = {"length", "max_tokens"}
    FILTERED_FINISH_REASONS = {"content_filter"}
    FAILED_FINISH_REASONS = {"insufficient_system_resource"}
    FORCE_MAX_THINKING = True
    SUPPORTS_CHAT_JSON_SCHEMA = False
    SUPPORTS_RESPONSES_JSON_SCHEMA = False
    INCLUDE_CHAT_STREAM_USAGE = True
    CHAT_TIMEOUT = httpx.Timeout(600.0, connect=30.0)
    STREAM_TIMEOUT = httpx.Timeout(
        connect=30.0,
        read=None,
        write=30.0,
        pool=30.0,
    )
    RESPONSES_MODELS = frozenset(
        {
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        }
    )
    DEFAULT_RESPONSES_MODELS = RESPONSES_MODELS
    API_MODE_PARAMS = {
        "api_mode",
        "interface",
        "use_responses_api",
        "_force_max_thinking",
    }
    TOKEN_LIMIT_PARAMS = {
        "max_tokens": (
            "max_tokens",
            "max_completion_tokens",
            "max_output_tokens",
        ),
        "max_output_tokens": (
            "max_output_tokens",
            "max_completion_tokens",
            "max_tokens",
        ),
    }
    UNSUPPORTED_STRICT_SCHEMA_KEYWORDS = {
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }
    RESPONSE_PARAMS = {
        "temperature",
        "top_p",
        "top_logprobs",
        "tools",
        "tool_choice",
        "reasoning",
        "text",
        "user",
    }
    UNSUPPORTED_RESPONSES_PARAMS = {
        "background",
        "context_management",
        "conversation",
        "include",
        "metadata",
        "previous_response_id",
        "prompt",
        "prompt_cache_key",
        "prompt_cache_retention",
        "safety_identifier",
        "service_tier",
        "store",
        "stream_options",
        "truncation",
    }

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = decrypt_api_key(config["api_key_encrypted"])
        self.model = (config.get("model_name") or "deepseek-v4-pro").strip()
        self.base_url = (config.get("base_url") or self.API_BASE).rstrip("/")
        self.default_params = config.get("default_params") or {}

    async def response(self, messages: list[dict], **kwargs) -> LLMResult:
        if self._uses_responses_api(kwargs):
            payload = self._build_responses_payload(messages, stream=False, **kwargs)
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

        payload = self._build_payload(messages, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=self.CHAT_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        return self._parse_chat_result(data)

    async def chat_completion(self, messages: list[dict], **kwargs) -> str:
        return (await self.response(messages, **kwargs)).text

    async def stream_completion(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        async for event in self.stream_completion_events(messages, **kwargs):
            yield event.get("content", "") if event.get("type") == "content" else ""

    async def stream_completion_events(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        if self._uses_responses_api(kwargs):
            async for event in self._stream_responses_events(messages, **kwargs):
                yield event
            return

        payload = self._build_payload(messages, stream=True, **kwargs)
        terminal_seen = False
        last_finish_reason: str | None = None
        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw_data = line[5:].lstrip()
                    if raw_data == "[DONE]":
                        terminal_seen = True
                        break
                    chunk = json.loads(raw_data)
                    choices = chunk.get("choices") or []
                    if choices:
                        choice = choices[0]
                        if finish_reason := choice.get("finish_reason"):
                            last_finish_reason = finish_reason
                            terminal_seen = True
                        delta = choice.get("delta") or {}
                        if event := self._event_from_delta(delta):
                            yield event
                        for tool_delta in delta.get("tool_calls") or []:
                            function = tool_delta.get("function") or {}
                            yield {
                                "type": "tool_call_delta",
                                "content": str(function.get("arguments") or ""),
                                "call_id": str(tool_delta.get("id") or ""),
                                "name": str(function.get("name") or ""),
                            }
                    if usage := chunk.get("usage"):
                        parsed_usage = parse_responses_usage(usage)
                        yield {
                            "type": "usage",
                            "content": "",
                            "usage": parsed_usage.to_dict(),
                            "finish_status": self._chat_finish_status(
                                last_finish_reason
                            ).value,
                            **({"response_id": chunk["id"]} if chunk.get("id") else {}),
                            **({"model": chunk["model"]} if chunk.get("model") else {}),
                        }
        if not terminal_seen:
            raise LLMStreamProtocolError(
                "DeepSeek chat stream ended without a terminal event"
            )
        self._raise_for_finish_reason(last_finish_reason)

    def _build_payload(
        self, messages: list[dict], stream: bool, **kwargs
    ) -> dict:
        params = self._merge_params_with_token_limit(
            kwargs,
            canonical_key="max_tokens",
        )
        force_max_thinking = params.pop(
            "_force_max_thinking", self.FORCE_MAX_THINKING
        )
        for private_key in self.API_MODE_PARAMS:
            params.pop(private_key, None)
        output_format = pop_output_format(params)
        if output_format:
            params["response_format"] = (
                self._to_chat_response_format(output_format)
                if self.SUPPORTS_CHAT_JSON_SCHEMA
                else {"type": "json_object"}
            )
        if tools := params.get("tools"):
            params["tools"] = normalize_chat_tools(tools)

        safe_params = {
            key: value
            for key, value in params.items()
            if key not in {"model", "messages", "stream"} and value is not None
        }
        payload = {
            **safe_params,
            "model": self.model,
            "messages": deepcopy(messages),
            "stream": stream,
        }
        if stream and self.INCLUDE_CHAT_STREAM_USAGE:
            explicit_stream_options = payload.get("stream_options")
            if explicit_stream_options is None:
                explicit_stream_options = {}
            if isinstance(explicit_stream_options, dict):
                payload["stream_options"] = {
                    "include_usage": True,
                    **explicit_stream_options,
                }
        uses_json_mode = isinstance(payload.get("response_format"), dict)
        if uses_json_mode:
            payload.pop("thinking", None)
            payload.pop("reasoning_effort", None)
        elif force_max_thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "max"
        return payload

    def _uses_responses_api(self, kwargs: dict) -> bool:
        params: dict[str, Any] = {**self.default_params, **kwargs}
        mode = params.get("api_mode")
        if mode is None:
            mode = params.get("interface")
        if mode is not None:
            normalized_mode = str(mode).lower().replace("-", "_")
            if normalized_mode in {"chat", "chat_completions"}:
                return False
            if normalized_mode == "responses":
                self._validate_responses_model()
                return True
            raise LLMProviderConfigurationError(
                f"Unsupported DeepSeek api_mode: {mode}"
            )
        if "use_responses_api" in params and params["use_responses_api"] is not None:
            enabled = bool(params["use_responses_api"])
            if enabled:
                self._validate_responses_model()
            return enabled
        return self.model in self.DEFAULT_RESPONSES_MODELS

    @classmethod
    def supports_responses_model(cls, model: str | None) -> bool:
        return (model or "").strip() in cls.RESPONSES_MODELS

    def _validate_responses_model(self) -> None:
        if not self.supports_responses_model(self.model):
            raise LLMProviderConfigurationError(
                "DeepSeek /responses currently supports deepseek-v4-flash "
                "and deepseek-v4-pro"
            )

    def _build_responses_payload(
        self, messages: list[dict], stream: bool, **kwargs
    ) -> dict:
        self._validate_responses_model()
        params = self._merge_params_with_token_limit(
            kwargs,
            canonical_key="max_output_tokens",
        )
        force_max_thinking = params.pop(
            "_force_max_thinking", self.FORCE_MAX_THINKING
        )
        unsupported_params = sorted(
            key
            for key in self.UNSUPPORTED_RESPONSES_PARAMS
            if key in params
            and params[key] is not None
            and not (key == "store" and params[key] is False)
        )
        if unsupported_params:
            raise LLMProviderConfigurationError(
                "DeepSeek Responses does not support: "
                + ", ".join(unsupported_params)
            )
        for private_key in self.API_MODE_PARAMS | {"thinking"}:
            params.pop(private_key, None)

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
            if (
                output_format.get("type") == "json_schema"
                and not self.SUPPORTS_RESPONSES_JSON_SCHEMA
            ):
                output_format = {"type": "json_object"}
            else:
                output_format = self._sanitize_responses_output_format(
                    output_format
                )
            text_config = params.get("text") or {}
            params["text"] = {**text_config, "format": output_format}

        reasoning_effort = params.pop("reasoning_effort", None)
        if reasoning_effort:
            reasoning_config = params.get("reasoning") or {}
            params["reasoning"] = {
                **reasoning_config,
                "effort": reasoning_effort,
            }
        elif force_max_thinking and not output_format and not params.get("reasoning"):
            params["reasoning"] = {"effort": "max"}
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

    async def _stream_responses_events(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        payload = self._build_responses_payload(messages, stream=True, **kwargs)
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
                "DeepSeek Responses stream ended without a terminal event"
            )

    def _parse_chat_result(self, data: dict[str, Any]) -> LLMResult:
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("DeepSeek response did not contain a choice")
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        self._raise_for_finish_reason(finish_reason)
        message = choice.get("message") or {}
        content = message.get("content") or ""
        output_items: list[dict[str, Any]] = []
        if content:
            output_items.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": str(content)}],
                }
            )
        if reasoning := message.get("reasoning_content"):
            output_items.append(
                {
                    "type": "reasoning",
                    "content": [{"type": "reasoning_text", "text": reasoning}],
                }
            )
        tool_calls: list[LLMToolCall] = []
        for source in message.get("tool_calls") or []:
            function = source.get("function") or {}
            tool_call = LLMToolCall(
                id=str(source.get("id") or ""),
                name=str(function.get("name") or ""),
                arguments=str(function.get("arguments") or ""),
            )
            tool_calls.append(tool_call)
            output_items.append(tool_call.to_response_item())
        return LLMResult(
            text=str(content),
            output_items=output_items,
            tool_calls=tool_calls,
            usage=parse_responses_usage(data.get("usage") or {}),
            finish_status=self._chat_finish_status(finish_reason),
            response_id=data.get("id"),
            model=data.get("model") or self.model,
        )

    def _extract_response_text(self, data: dict[str, Any]) -> str:
        """Compatibility helper retained for existing provider callers/tests."""

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
            raise RuntimeError(f"DeepSeek response incomplete: {reason or 'unknown'}")
        if status == "failed":
            error = data.get("error") or {}
            raise RuntimeError(error.get("message") or "DeepSeek response failed")
        if status == "cancelled":
            raise LLMContentFilteredError("DeepSeek response was cancelled")

    def _event_from_delta(self, delta: dict) -> LLMStreamEvent | None:
        if content := delta.get("content"):
            return {"type": "content", "content": str(content)}
        if reasoning_content := delta.get("reasoning_content"):
            return {"type": "thinking", "content": str(reasoning_content)}
        return None

    def _raise_for_finish_reason(self, finish_reason: str | None) -> None:
        if finish_reason in self.TRUNCATED_FINISH_REASONS:
            raise LLMOutputTruncatedError(
                f"LLM output stopped early: {finish_reason}"
            )
        if finish_reason in self.FILTERED_FINISH_REASONS:
            raise LLMContentFilteredError(
                f"LLM output was filtered: {finish_reason}"
            )
        if finish_reason in self.FAILED_FINISH_REASONS:
            raise RuntimeError(f"DeepSeek response failed: {finish_reason}")

    @staticmethod
    def _chat_finish_status(reason: str | None) -> LLMFinishStatus:
        if reason in {"tool_calls", "function_call"}:
            return LLMFinishStatus.TOOL_CALLS
        if reason in {"length", "max_tokens"}:
            return LLMFinishStatus.INCOMPLETE
        if reason == "content_filter":
            return LLMFinishStatus.CANCELLED
        if reason in DeepSeekProvider.FAILED_FINISH_REASONS:
            return LLMFinishStatus.FAILED
        return LLMFinishStatus.COMPLETED if reason else LLMFinishStatus.UNKNOWN

    @staticmethod
    def _to_chat_response_format(output_format: dict[str, Any]) -> dict[str, Any]:
        if output_format.get("type") != "json_schema":
            return output_format
        return {
            "type": "json_schema",
            "json_schema": {
                key: value
                for key, value in output_format.items()
                if key in {"name", "description", "schema", "strict"}
            },
        }

    def _merge_params_with_token_limit(
        self,
        kwargs: dict[str, Any],
        *,
        canonical_key: str,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {**self.default_params, **kwargs}
        token_keys = self.TOKEN_LIMIT_PARAMS[canonical_key]
        token_limit = next(
            (
                source[key]
                for source in (kwargs, self.default_params)
                for key in token_keys
                if source.get(key) is not None
            ),
            None,
        )
        for key in token_keys:
            params.pop(key, None)
        if token_limit is not None:
            params[canonical_key] = token_limit
        return params

    @classmethod
    def _sanitize_responses_output_format(
        cls, output_format: dict[str, Any]
    ) -> dict[str, Any]:
        """Remove strict-schema keywords rejected by DeepSeek before inference."""

        normalized = deepcopy(output_format)
        if normalized.get("type") != "json_schema":
            return normalized
        schema = normalized.get("schema")
        if isinstance(schema, dict):
            normalized["schema"] = cls._sanitize_strict_schema(schema)
        return normalized

    @classmethod
    def _sanitize_strict_schema(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [cls._sanitize_strict_schema(item) for item in value]
        if not isinstance(value, dict):
            return deepcopy(value)
        return {
            key: cls._sanitize_strict_schema(item)
            for key, item in value.items()
            if key not in cls.UNSUPPORTED_STRICT_SCHEMA_KEYWORDS
        }

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
