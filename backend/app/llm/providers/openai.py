import json
from typing import AsyncIterator

import httpx

from .base import LLMContentFilteredError, LLMOutputTruncatedError, LLMProvider
from app.core.security import decrypt_api_key


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
                f"{self.base_url}/responses",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            self._raise_for_response_status(data)
            return self._extract_text(data)

    async def stream_completion(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        payload = self._build_payload(messages, stream=True, **kwargs)
        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/responses",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                completed_response = None
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    event_type = event.get("type")
                    if event_type == "response.output_text.delta":
                        if delta := event.get("delta"):
                            yield delta
                    elif event_type == "response.completed":
                        completed_response = event.get("response")
                    elif event_type == "response.failed":
                        error = event.get("response", {}).get("error") or {}
                        raise RuntimeError(error.get("message") or "OpenAI response failed")
                if completed_response:
                    self._raise_for_response_status(completed_response)

    def _build_payload(
        self, messages: list[dict], stream: bool, **kwargs
    ) -> dict:
        params = {**(self.default_params or {}), **kwargs}
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

        verbosity = params.pop("verbosity", None)
        if verbosity:
            text_config = params.get("text") or {}
            params["text"] = {**text_config, "verbosity": verbosity}

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
        return "\n\n".join(part for part in instructions if part).strip() or None, input_messages

    def _extract_text(self, data: dict) -> str:
        if output_text := data.get("output_text"):
            return output_text
        chunks: list[str] = []
        for item in data.get("output") or []:
            for content in item.get("content") or []:
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(content["text"])
        return "".join(chunks)

    def _raise_for_response_status(self, data: dict) -> None:
        if data.get("status") == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason")
            if reason in {"max_output_tokens", "max_tokens"}:
                raise LLMOutputTruncatedError(f"LLM output stopped early: {reason}")
            raise RuntimeError(f"OpenAI response incomplete: {reason}")
        if data.get("status") == "failed":
            error = data.get("error") or {}
            raise RuntimeError(error.get("message") or "OpenAI response failed")
        if data.get("status") == "cancelled":
            raise LLMContentFilteredError("OpenAI response was cancelled")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)
