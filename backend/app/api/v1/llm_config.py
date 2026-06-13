import time

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.llm_config import LLMConfig
from app.core.security import encrypt_api_key
from app.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.services.llm_orchestrator import PROVIDER_MAP
from app.schemas.llm_config import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMConfigResponse,
    LLMConfigTestResponse,
)
from app.core.exceptions import LLMConfigNotFoundException, LLMConfigInactiveException

router = APIRouter()

MASKED_KEY = "****masked****"
TEST_CONNECTION_MAX_TOKENS = 64


def _test_connection_kwargs(provider: str) -> dict:
    kwargs = {"max_tokens": TEST_CONNECTION_MAX_TOKENS}
    if provider == "deepseek":
        kwargs.update(
            {
                "_force_max_thinking": False,
                "thinking": None,
                "reasoning_effort": None,
            }
        )
    return kwargs


@router.get("")
async def list_configs(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    result = await db.execute(select(LLMConfig))
    configs = result.scalars().all()
    data = []
    for c in configs:
        resp = LLMConfigResponse.model_validate(c)
        resp_dict = resp.model_dump()
        resp_dict["api_key_encrypted"] = MASKED_KEY
        data.append(resp_dict)
    return {"data": data}


@router.get("/{config_id}")
async def get_config(
    config_id: str, db: AsyncSession = Depends(get_db)
):
    config = await db.get(LLMConfig, config_id)
    if not config:
        raise LLMConfigNotFoundException()
    resp = LLMConfigResponse.model_validate(config)
    resp_dict = resp.model_dump()
    resp_dict["api_key_encrypted"] = MASKED_KEY
    return resp_dict


@router.post("", response_model=LLMConfigResponse, status_code=201)
async def create_config(
    data: LLMConfigCreate, db: AsyncSession = Depends(get_db)
):
    encrypted_key = encrypt_api_key(data.api_key)
    config = LLMConfig(
        provider=data.provider,
        api_key_encrypted=encrypted_key,
        base_url=data.base_url,
        model_name=data.model_name,
        default_params=data.default_params,
        rate_limit=data.rate_limit,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    resp = LLMConfigResponse.model_validate(config)
    resp_dict = resp.model_dump()
    resp_dict["api_key_encrypted"] = MASKED_KEY
    return resp_dict


@router.put("/{config_id}")
async def update_config(
    config_id: str,
    data: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(LLMConfig, config_id)
    if not config:
        raise LLMConfigNotFoundException()
    update_data = data.model_dump(exclude_unset=True)
    if "api_key" in update_data and update_data["api_key"]:
        update_data["api_key_encrypted"] = encrypt_api_key(
            update_data.pop("api_key")
        )
    elif "api_key" in update_data:
        del update_data["api_key"]
    for key, value in update_data.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    resp = LLMConfigResponse.model_validate(config)
    resp_dict = resp.model_dump()
    resp_dict["api_key_encrypted"] = MASKED_KEY
    return resp_dict


@router.delete("/{config_id}", status_code=204)
async def delete_config(
    config_id: str, db: AsyncSession = Depends(get_db)
):
    config = await db.get(LLMConfig, config_id)
    if not config:
        raise LLMConfigNotFoundException()
    await db.delete(config)
    await db.commit()


@router.post("/{config_id}/test", response_model=LLMConfigTestResponse)
async def test_config(
    config_id: str, db: AsyncSession = Depends(get_db)
):
    config = await db.get(LLMConfig, config_id)
    if not config:
        raise LLMConfigNotFoundException()
    if not config.is_active:
        raise LLMConfigInactiveException()

    try:
        provider_cls = PROVIDER_MAP.get(config.provider, OpenAICompatibleProvider)
        provider = provider_cls(
            {
                "provider": config.provider,
                "api_key_encrypted": config.api_key_encrypted,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "default_params": config.default_params or {},
                "rate_limit": config.rate_limit,
            }
        )
        started = time.perf_counter()
        await provider.chat_completion(
            [
                {
                    "role": "system",
                    "content": "You are testing an API connection. Reply with exactly OK.",
                },
                {"role": "user", "content": "OK"},
            ],
            **_test_connection_kwargs(config.provider),
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return LLMConfigTestResponse(
            success=True,
            message="连接成功",
            model_info={
                "provider": config.provider,
                "model_name": config.model_name,
                "latency_ms": latency_ms,
            },
        )
    except Exception as e:
        return LLMConfigTestResponse(
            success=False, message=str(e), model_info=None
        )
