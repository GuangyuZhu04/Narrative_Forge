import json
from typing import AsyncIterator

import httpx

from .base import LLMContentFilteredError, LLMOutputTruncatedError, LLMProvider
from app.core.security import decrypt_api_key


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
    }

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = decrypt_api_key(config["api_key_encrypted"])
        self.model = config.get("model_name") or self.DEFAULT_MODEL
        self.base_url = (config.get("base_url") or self.API_BASE).rstrip("/")
        self.default_params = config.get("default_params") or {}

    async def chat_completion(self, messages: list[dict], **kwargs) -> str:
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
            return self._extract_text(data)

    async def stream_completion(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
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
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    event_type = event.get("type")
                    if event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield delta["text"]
                    elif event_type == "message_delta":
                        delta = event.get("delta") or {}
                        last_stop_reason = delta.get("stop_reason") or last_stop_reason
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
