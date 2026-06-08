import json
from typing import AsyncIterator

import httpx

from .base import LLMContentFilteredError, LLMOutputTruncatedError, LLMProvider
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
                        if content := delta.get("content"):
                            yield content
                        elif delta.get("reasoning_content"):
                            yield ""
                self._raise_for_finish_reason(last_finish_reason)

    def _build_payload(
        self, messages: list[dict], stream: bool, **kwargs
    ) -> dict:
        params = {**(self.default_params or {}), **kwargs}
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            **{k: v for k, v in params.items() if v is not None},
        }
        if self.FORCE_MAX_THINKING:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "max"
        return payload

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
