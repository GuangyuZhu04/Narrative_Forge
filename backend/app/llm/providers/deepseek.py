import json
from typing import AsyncIterator

import httpx

from .base import (
    LLMContentFilteredError,
    LLMOutputTruncatedError,
    LLMProvider,
    LLMStreamEvent,
)
from app.core.security import decrypt_api_key


class DeepSeekProvider(LLMProvider):
    API_BASE = "https://api.deepseek.com"
    TRUNCATED_FINISH_REASONS = {"length", "max_tokens"}
    FILTERED_FINISH_REASONS = {"content_filter"}
    FORCE_MAX_THINKING = True
    CHAT_TIMEOUT = httpx.Timeout(600.0, connect=30.0)
    STREAM_TIMEOUT = httpx.Timeout(
        connect=30.0,
        read=None,
        write=30.0,
        pool=30.0,
    )
    RESPONSES_MODEL = "deepseek-v4-flash"
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

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = decrypt_api_key(config["api_key_encrypted"])
        self.model = config.get("model_name", "deepseek-v4-pro")
        self.base_url = config.get("base_url", self.API_BASE)
        # dict.get only returns the default when the key is MISSING; if the key
        # is present with a None value (e.g. unconfigured LLM rows), fall
        # through to `or {}` so downstream dict-merge calls never crash.
        self.default_params = config.get("default_params") or {}

    async def chat_completion(self, messages: list[dict], **kwargs) -> str:
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
                return self._extract_response_text(data)

        payload = self._build_payload(messages, stream=False, **kwargs)
        async with httpx.AsyncClient(timeout=self.CHAT_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            choice = resp.json()["choices"][0]
            self._raise_for_finish_reason(choice.get("finish_reason"))
            return choice["message"]["content"]

    async def stream_completion(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        async for event in self.stream_completion_events(messages, **kwargs):
            yield event["content"] if event["type"] == "content" else ""

    async def stream_completion_events(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        if self._uses_responses_api(kwargs):
            async for event in self._stream_responses_events(messages, **kwargs):
                yield event
            return

        payload = self._build_payload(messages, stream=True, **kwargs)
        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                last_finish_reason = None
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        if finish_reason := choice.get("finish_reason"):
                            last_finish_reason = finish_reason
                        delta = choice.get("delta", {})
                        event = self._event_from_delta(delta)
                        if event:
                            yield event
                self._raise_for_finish_reason(last_finish_reason)

    def _build_payload(
        self, messages: list[dict], stream: bool, **kwargs
    ) -> dict:
        params = {**(self.default_params or {}), **kwargs}
        force_max_thinking = params.pop("_force_max_thinking", self.FORCE_MAX_THINKING)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            **{k: v for k, v in params.items() if v is not None},
        }
        uses_json_mode = (
            isinstance(payload.get("response_format"), dict)
            and payload["response_format"].get("type") == "json_object"
        )
        if uses_json_mode:
            payload.pop("thinking", None)
            payload.pop("reasoning_effort", None)
        elif force_max_thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "max"
        return payload

    def _uses_responses_api(self, kwargs: dict) -> bool:
        params = {**(self.default_params or {}), **kwargs}
        api_mode = params.get("api_mode") or params.get("interface")
        if api_mode == "chat_completions":
            return False
        return (
            api_mode == "responses"
            or params.get("use_responses_api") is True
            or self.model == self.RESPONSES_MODEL
        )

    def _build_responses_payload(
        self, messages: list[dict], stream: bool, **kwargs
    ) -> dict:
        params = {**(self.default_params or {}), **kwargs}
        for private_key in (
            "api_mode",
            "interface",
            "use_responses_api",
            "_force_max_thinking",
            "thinking",
        ):
            params.pop(private_key, None)

        instructions, input_messages = self._convert_messages(messages)
        payload = {
            "model": self.model,
            "input": input_messages or "",
            "stream": stream,
        }
        if instructions:
            payload["instructions"] = instructions

        max_tokens = params.pop("max_output_tokens", None)
        max_tokens = max_tokens or params.pop("max_completion_tokens", None)
        max_tokens = max_tokens or params.pop("max_tokens", None)
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens

        if response_format := params.pop("response_format", None):
            text_config = params.get("text") or {}
            params["text"] = {**text_config, "format": response_format}

        if reasoning_effort := params.pop("reasoning_effort", None):
            reasoning_config = params.get("reasoning") or {}
            params["reasoning"] = {**reasoning_config, "effort": reasoning_effort}

        payload.update(
            {
                key: value
                for key, value in params.items()
                if key in self.RESPONSE_PARAMS and value is not None
            }
        )
        return payload

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        instructions: list[str] = []
        input_messages: list[dict] = []
        for message in messages:
            role = message.get("role") or "user"
            content = message.get("content") or ""
            if role in {"system", "developer"}:
                instructions.append(str(content))
                continue
            input_messages.append(
                {
                    "role": "assistant" if role == "assistant" else "user",
                    "content": str(content),
                }
            )
        return (
            "\n\n".join(part for part in instructions if part).strip() or None,
            input_messages,
        )

    async def _stream_responses_events(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        payload = self._build_responses_payload(messages, stream=True, **kwargs)
        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/responses",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                current_event_type = None
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event: "):
                        current_event_type = line[7:].strip()
                        continue
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    event_type = (
                        event.get("type")
                        or event.get("event")
                        or current_event_type
                    )
                    if event_type == "response.output_text.delta":
                        if delta := event.get("delta"):
                            yield {"type": "content", "content": delta}
                    elif event_type == "response.reasoning_text.delta":
                        if delta := event.get("delta"):
                            yield {"type": "thinking", "content": delta}
                    elif event_type == "response.completed":
                        self._raise_for_response_status(
                            event.get("response") or event
                        )
                        break
                    elif event_type == "response.incomplete":
                        self._raise_for_response_status(
                            event.get("response") or {"status": "incomplete"}
                        )
                    elif event_type == "response.failed":
                        response = event.get("response") or {}
                        error = response.get("error") or event.get("error") or {}
                        raise RuntimeError(
                            error.get("message") or "DeepSeek response failed"
                        )

    def _extract_response_text(self, data: dict) -> str:
        if output_text := data.get("output_text"):
            return output_text
        chunks: list[str] = []
        for item in data.get("output") or []:
            for content in item.get("content") or []:
                if (
                    content.get("type") in {"output_text", "text"}
                    and content.get("text")
                ):
                    chunks.append(content["text"])
        return "".join(chunks)

    def _raise_for_response_status(self, data: dict) -> None:
        if data.get("status") == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason")
            if reason in {"max_output_tokens", "max_tokens"}:
                raise LLMOutputTruncatedError(
                    f"LLM output stopped early: {reason}"
                )
            raise RuntimeError(f"DeepSeek response incomplete: {reason}")
        if data.get("status") == "failed":
            error = data.get("error") or {}
            raise RuntimeError(error.get("message") or "DeepSeek response failed")
        if data.get("status") == "cancelled":
            raise LLMContentFilteredError("DeepSeek response was cancelled")

    def _event_from_delta(self, delta: dict) -> LLMStreamEvent | None:
        if content := delta.get("content"):
            return {"type": "content", "content": content}
        if reasoning_content := delta.get("reasoning_content"):
            return {"type": "thinking", "content": reasoning_content}
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

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)
