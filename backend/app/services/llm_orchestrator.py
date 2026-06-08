from typing import AsyncIterator

from app.llm.providers.base import LLMProvider
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.llm.rate_limiter import TokenBucketRateLimiter

PROVIDER_MAP = {
    "deepseek": DeepSeekProvider,
    "openai_compatible": OpenAICompatibleProvider,
}


class LLMOrchestrator:
    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}
        self._rate_limiter = TokenBucketRateLimiter()

    async def initialize(self, config_id: str, db_config_dict: dict):
        provider_cls = PROVIDER_MAP.get(
            db_config_dict["provider"], OpenAICompatibleProvider
        )
        provider = provider_cls(db_config_dict)
        if rate_limit := db_config_dict.get("rate_limit"):
            self._rate_limiter.configure(rate_limit)
        self._providers[config_id] = provider

    async def chat(
        self, config_id: str, messages: list[dict], **kwargs
    ) -> str:
        provider = self._providers.get(config_id)
        if not provider:
            provider = await self._load_provider(config_id)
        await self._rate_limiter.acquire()
        return await provider.chat_completion(messages, **kwargs)

    async def stream_chat(
        self, config_id: str, messages: list[dict], **kwargs
    ) -> AsyncIterator[str]:
        provider = self._providers.get(config_id)
        if not provider:
            provider = await self._load_provider(config_id)
        await self._rate_limiter.acquire()
        async for chunk in provider.stream_completion(messages, **kwargs):
            yield chunk

    async def _load_provider(self, config_id: str) -> LLMProvider:
        from app.db.session import AsyncSessionLocal
        from app.models.llm_config import LLMConfig
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            config = await db.get(LLMConfig, config_id)
            if not config:
                raise ValueError(f"LLM config {config_id} not found")
            config_dict = {
                "provider": config.provider,
                "api_key_encrypted": config.api_key_encrypted,
                "base_url": config.base_url,
                "model_name": config.model_name,
                # Coerce legacy NULL rows to {} so providers can always
                # dict-merge default_params without TypeError.
                "default_params": config.default_params or {},
                "rate_limit": config.rate_limit,
            }
        provider_cls = PROVIDER_MAP.get(
            config_dict["provider"], OpenAICompatibleProvider
        )
        provider = provider_cls(config_dict)
        if rate_limit := config_dict.get("rate_limit"):
            self._rate_limiter.configure(rate_limit)
        self._providers[config_id] = provider
        return provider


llm_orchestrator = LLMOrchestrator()
