import json
from typing import AsyncIterator
from urllib.parse import quote

import httpx

from .base import LLMContentFilteredError, LLMOutputTruncatedError, LLMProvider
from app.core.security import decrypt_api_key


class GoogleProvider(LLMProvider):
    API_BASE = "https://generativelanguage.googleapis.com/v1beta"
    DEFAULT_MODEL = "gemini-3.5-flash"
    CHAT_TIMEOUT = httpx.Timeout(600.0, connect=30.0)
    STREAM_TIMEOUT = httpx.Timeout(
        connect=30.0,
        read=None,
        write=30.0,
        pool=30.0,
    )
    GENERATION_CONFIG_MAP = {
        "max_tokens": "maxOutputTokens",
        "max_output_tokens": "maxOutputTokens",
        "temperature": "temperature",
        "top_p": "topP",
        "topP": "topP",
        "top_k": "topK",
        "topK": "topK",
        "stop_sequences": "stopSequences",
        "stopSequences": "stopSequences",
        "candidate_count": "candidateCount",
        "candidateCount": "candidateCount",
    }
    FILTERED_REASONS = {
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "RECITATION",
    }

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = decrypt_api_key(config["api_key_encrypted"])
        self.model = config.get("model_name") or self.DEFAULT_MODEL
        self.base_url = (config.get("base_url") or self.API_BASE).rstrip("/")
        self.default_params = config.get("default_params") or {}

    async def chat_completion(self, messages: list[dict], **kwargs) -> str:
        payload = self._build_payload(messages, **kwargs)
        async with httpx.AsyncClient(timeout=self.CHAT_TIMEOUT) as client:
            resp = await client.post(
                self._endpoint("generateContent"),
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._raise_for_candidates(data.get("candidates") or [])
            return self._extract_text(data)

    async def stream_completion(
        self, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        payload = self._build_payload(messages, **kwargs)
        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                self._endpoint("streamGenerateContent", stream=True),
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                resp.raise_for_status()
                last_candidates = []
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = json.loads(line[6:])
                    candidates = data.get("candidates") or []
                    if candidates:
                        last_candidates = candidates
                    text = self._extract_text(data)
                    if text:
                        yield text
                self._raise_for_candidates(last_candidates)

    def _build_payload(self, messages: list[dict], **kwargs) -> dict:
        params = {**(self.default_params or {}), **kwargs}
        system, contents = self._convert_messages(messages)
        payload = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        generation_config = params.pop("generationConfig", None) or {}
        for key, target_key in self.GENERATION_CONFIG_MAP.items():
            if key in params and params[key] is not None:
                generation_config[target_key] = params[key]
        if generation_config:
            payload["generationConfig"] = generation_config

        if safety_settings := params.get("safetySettings") or params.get(
            "safety_settings"
        ):
            payload["safetySettings"] = safety_settings
        return payload

    def _convert_messages(self, messages: list[dict]) -> tuple[str | None, list[dict]]:
        system_parts: list[str] = []
        contents: list[dict] = []
        for message in messages:
            role = message.get("role") or "user"
            content = str(message.get("content") or "")
            if role in {"system", "developer"}:
                system_parts.append(content)
                continue
            gemini_role = "model" if role == "assistant" else "user"
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].append({"text": f"\n\n{content}"})
            else:
                contents.append({"role": gemini_role, "parts": [{"text": content}]})
        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})
        return "\n\n".join(part for part in system_parts if part).strip() or None, contents

    def _extract_text(self, data: dict) -> str:
        chunks: list[str] = []
        for candidate in data.get("candidates") or []:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if text := part.get("text"):
                    chunks.append(text)
        return "".join(chunks)

    def _raise_for_candidates(self, candidates: list[dict]) -> None:
        for candidate in candidates:
            reason = candidate.get("finishReason")
            if reason == "MAX_TOKENS":
                raise LLMOutputTruncatedError("LLM output stopped early: MAX_TOKENS")
            if reason in self.FILTERED_REASONS:
                raise LLMContentFilteredError(f"LLM output was filtered: {reason}")

    def _endpoint(self, method: str, stream: bool = False) -> str:
        model = self.model.removeprefix("models/")
        suffix = "?alt=sse" if stream else ""
        separator = "&" if stream else "?"
        return (
            f"{self.base_url}/models/{quote(model)}:{method}"
            f"{suffix}{separator}key={quote(self.api_key)}"
        )

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)
