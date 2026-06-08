from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.exceptions import NotFoundException
from app.schemas.system_settings import (
    SystemPromptSettingResponse,
    SystemPromptSettingsResponse,
    SystemPromptSettingUpdate,
)
from app.services.system_prompt_service import system_prompt_service

router = APIRouter()


@router.get("/prompts", response_model=SystemPromptSettingsResponse)
async def list_system_prompts(db: AsyncSession = Depends(get_db)):
    return {"data": await system_prompt_service.list_settings(db)}


@router.get("/prompts/{setting_key}", response_model=SystemPromptSettingResponse)
async def get_system_prompt(setting_key: str, db: AsyncSession = Depends(get_db)):
    setting = await system_prompt_service.get_setting(db, setting_key)
    if not setting:
        raise NotFoundException(detail="系统设置不存在", error_code="SYSTEM_SETTING_NOT_FOUND")
    return setting


@router.put("/prompts/{setting_key}", response_model=SystemPromptSettingResponse)
async def update_system_prompt(
    setting_key: str,
    data: SystemPromptSettingUpdate,
    db: AsyncSession = Depends(get_db),
):
    setting = await system_prompt_service.update_setting(db, setting_key, data.value)
    if not setting:
        raise NotFoundException(detail="系统设置不存在", error_code="SYSTEM_SETTING_NOT_FOUND")
    return setting


@router.post("/prompts/{setting_key}/reset", response_model=SystemPromptSettingResponse)
async def reset_system_prompt(setting_key: str, db: AsyncSession = Depends(get_db)):
    setting = await system_prompt_service.reset_setting(db, setting_key)
    if not setting:
        raise NotFoundException(detail="系统设置不存在", error_code="SYSTEM_SETTING_NOT_FOUND")
    return setting
