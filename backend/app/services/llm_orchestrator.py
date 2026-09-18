from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, AsyncIterator

from app.core.exceptions import LLMConfigInactiveException
from app.llm.contracts import LLMResult, LLMStreamEvent
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.base import LLMProvider
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.google import GoogleProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.llm.rate_limiter import TokenBucketRateLimiter

PROVIDER_MAP = {
    "deepseek": DeepSeekProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "openai_compatible": OpenAICompatibleProvider,
}


class LLMOrchestrator:
    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}
        self._fingerprints: dict[str, str] = {}
        self._rate_limiters: dict[str, TokenBucketRateLimiter] = {}
        self._load_locks: dict[str, asyncio.Lock] = {}
        self._generations: dict[str, int] = {}

    async def initialize(self, config_id: str, db_config_dict: dict) -> None:
        """Preload a provider; normal calls still verify the persisted config."""

        if db_config_dict.get("is_active") is False:
            raise LLMConfigInactiveException()
        self._install_provider(config_id, db_config_dict)

    def invalidate(self, config_id: str) -> None:
        """Forget decrypted credentials and rate state for one configuration."""

        self._providers.pop(config_id, None)
        self._fingerprints.pop(config_id, None)
        self._rate_limiters.pop(config_id, None)
        # Keep the per-config lock stable: replacing it while an old loader is
        # running would allow that loader to reinstall stale credentials.
        self._generations[config_id] = self._generations.get(config_id, 0) + 1

    async def response(
        self, config_id: str, messages: list[dict], **kwargs
    ) -> LLMResult:
        provider, limiter = await self._provider_and_limiter(config_id)
        await limiter.acquire()
        return await provider.response(messages, **kwargs)

    async def chat(
        self, config_id: str, messages: list[dict], **kwargs
    ) -> str:
        """Backward-compatible text-only facade."""

        return (await self.response(config_id, messages, **kwargs)).text

    async def stream_chat(
        self, config_id: str, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        provider, limiter = await self._provider_and_limiter(config_id)
        await limiter.acquire()
        async for chunk in provider.stream_completion(messages, **kwargs):
            yield chunk

    async def stream_chat_events(
        self, config_id: str, messages: list[dict], **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        provider, limiter = await self._provider_and_limiter(config_id)
        await limiter.acquire()
        async for event in provider.stream_completion_events(messages, **kwargs):
            yield event

    async def _provider_and_limiter(
        self, config_id: str
    ) -> tuple[LLMProvider, TokenBucketRateLimiter]:
        provider = await self._load_provider(config_id)
        return provider, self._rate_limiters[config_id]

    async def _load_provider(self, config_id: str) -> LLMProvider:
        lock = self._load_locks.setdefault(config_id, asyncio.Lock())
        async with lock:
            while True:
                generation = self._generations.get(config_id, 0)
                config_dict = await self._fetch_config(config_id)
                # update/delete may invalidate while the DB read is awaiting;
                # discard that snapshot and read once more under the same lock.
                if generation != self._generations.get(config_id, 0):
                    continue
                fingerprint = self._config_fingerprint(config_dict)
                cached = self._providers.get(config_id)
                if (
                    cached is not None
                    and self._fingerprints.get(config_id) == fingerprint
                ):
                    return cached
                return self._install_provider(config_id, config_dict, fingerprint)

    async def _fetch_config(self, config_id: str) -> dict[str, Any]:
        from app.db.session import AsyncSessionLocal
        from app.models.llm_config import LLMConfig

        async with AsyncSessionLocal() as db:
            config = await db.get(LLMConfig, config_id)
            if not config:
                self.invalidate(config_id)
                raise ValueError(f"LLM config {config_id} not found")
            if not config.is_active:
                self.invalidate(config_id)
                raise LLMConfigInactiveException()
            return {
                "provider": config.provider,
                "api_key_encrypted": config.api_key_encrypted,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "default_params": config.default_params or {},
                "rate_limit": config.rate_limit,
                "is_active": config.is_active,
                "updated_at": config.updated_at,
            }

    def _install_provider(
        self,
        config_id: str,
        config_dict: dict[str, Any],
        fingerprint: str | None = None,
    ) -> LLMProvider:
        provider_cls = PROVIDER_MAP.get(
            config_dict["provider"], OpenAICompatibleProvider
        )
        provider = provider_cls(config_dict)
        limiter = TokenBucketRateLimiter()
        if rate_limit := config_dict.get("rate_limit"):
            limiter.configure(rate_limit)
        self._providers[config_id] = provider
        self._rate_limiters[config_id] = limiter
        self._fingerprints[config_id] = fingerprint or self._config_fingerprint(
            config_dict
        )
        return provider

    @staticmethod
    def _config_fingerprint(config_dict: dict[str, Any]) -> str:
        serialized = json.dumps(
            config_dict,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


llm_orchestrator = LLMOrchestrator()
