import httpx

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.llm_config import LLMConfig
from app.core.security import encrypt_api_key, decrypt_api_key
from app.schemas.llm_config import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMConfigResponse,
    LLMConfigTestResponse,
)
from app.core.exceptions import LLMConfigNotFoundException, LLMConfigInactiveException

router = APIRouter()

MASKED_KEY = "****masked****"


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
        api_key = decrypt_api_key(config.api_key_encrypted)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{config.base_url}/chat/completions",
                json={
                    "model": config.model_name,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            latency_ms = int(resp.elapsed.total_seconds() * 1000)
            if resp.status_code == 200:
                return LLMConfigTestResponse(
                    success=True,
                    message="连接成功",
                    model_info={
                        "model_name": config.model_name,
                        "latency_ms": latency_ms,
                    },
                )
            else:
                return LLMConfigTestResponse(
                    success=False,
                    message=f"认证失败：HTTP {resp.status_code}",
                    model_info=None,
                )
    except Exception as e:
        return LLMConfigTestResponse(
            success=False, message=str(e), model_info=None
        )
