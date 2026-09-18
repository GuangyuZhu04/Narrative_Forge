import json
from copy import deepcopy
from typing import Any
from typing import AsyncIterator
from urllib.parse import quote

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

    async def response(self, messages: list[dict], **kwargs) -> LLMResult:
        payload = self._build_payload(messages, **kwargs)
        async with httpx.AsyncClient(timeout=self.CHAT_TIMEOUT) as client:
            resp = await client.post(
                self._endpoint("generateContent"),
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            self._raise_for_prompt_feedback(data.get("promptFeedback") or {})
            self._raise_for_candidates(data.get("candidates") or [])
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
        payload = self._build_payload(messages, **kwargs)
        async with httpx.AsyncClient(timeout=self.STREAM_TIMEOUT) as client:
            async with client.stream(
                "POST",
                self._endpoint("streamGenerateContent", stream=True),
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                last_candidates = []
                last_usage: dict[str, Any] = {}
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].lstrip())
                    self._raise_for_prompt_feedback(data.get("promptFeedback") or {})
                    candidates = data.get("candidates") or []
                    if candidates:
                        last_candidates = candidates
                    if data.get("usageMetadata"):
                        last_usage = data["usageMetadata"]
                    text = self._extract_text(data)
                    if text:
                        yield {"type": "content", "content": text}
                self._raise_for_candidates(last_candidates)
                if last_usage:
                    usage = self._parse_usage(last_usage)
                    yield {
                        "type": "usage",
                        "content": "",
                        "usage": usage.to_dict(),
                        "finish_status": self._finish_status(last_candidates).value,
                    }

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
        output_format = pop_output_format(params)
        if output_format:
            generation_config["responseMimeType"] = "application/json"
            if output_format.get("type") == "json_schema":
                generation_config["responseJsonSchema"] = deepcopy(
                    output_format.get("schema") or {}
                )
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

    def _parse_result(self, data: dict[str, Any]) -> LLMResult:
        output_items: list[dict[str, Any]] = []
        tool_calls: list[LLMToolCall] = []
        for candidate in data.get("candidates") or []:
            message_parts: list[dict[str, Any]] = []
            for part in (candidate.get("content") or {}).get("parts") or []:
                if part.get("text"):
                    message_parts.append(
                        {"type": "output_text", "text": str(part["text"])}
                    )
                if function_call := part.get("functionCall"):
                    tool_call = LLMToolCall(
                        id=str(function_call.get("id") or ""),
                        name=str(function_call.get("name") or ""),
                        arguments=json.dumps(
                            function_call.get("args") or {},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                    tool_calls.append(tool_call)
                    output_items.append(tool_call.to_response_item())
            if message_parts:
                output_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": message_parts,
                    }
                )
        return LLMResult(
            text=self._extract_text(data),
            output_items=output_items,
            tool_calls=tool_calls,
            usage=self._parse_usage(data.get("usageMetadata") or {}),
            finish_status=self._finish_status(data.get("candidates") or []),
            response_id=data.get("responseId"),
            model=data.get("modelVersion") or self.model,
        )

    @staticmethod
    def _parse_usage(usage: dict[str, Any]) -> LLMUsage:
        return LLMUsage(
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0),
            total_tokens=int(usage.get("totalTokenCount") or 0),
            cached_input_tokens=int(usage.get("cachedContentTokenCount") or 0),
            reasoning_tokens=int(usage.get("thoughtsTokenCount") or 0),
        )

    @staticmethod
    def _finish_status(candidates: list[dict]) -> LLMFinishStatus:
        reasons = {candidate.get("finishReason") for candidate in candidates}
        if "MAX_TOKENS" in reasons:
            return LLMFinishStatus.INCOMPLETE
        if reasons & GoogleProvider.FILTERED_REASONS:
            return LLMFinishStatus.CANCELLED
        return LLMFinishStatus.COMPLETED if candidates else LLMFinishStatus.UNKNOWN

    def _raise_for_candidates(self, candidates: list[dict]) -> None:
        for candidate in candidates:
            reason = candidate.get("finishReason")
            if reason == "MAX_TOKENS":
                raise LLMOutputTruncatedError("LLM output stopped early: MAX_TOKENS")
            if reason in self.FILTERED_REASONS:
                raise LLMContentFilteredError(f"LLM output was filtered: {reason}")

    def _raise_for_prompt_feedback(self, feedback: dict[str, Any]) -> None:
        reason = feedback.get("blockReason")
        if reason:
            raise LLMContentFilteredError(f"LLM prompt was filtered: {reason}")

    def _endpoint(self, method: str, stream: bool = False) -> str:
        model = self.model.removeprefix("models/")
        suffix = "?alt=sse" if stream else ""
        return f"{self.base_url}/models/{quote(model)}:{method}{suffix}"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def validate_config(self) -> bool:
        return bool(self.api_key and self.model)
