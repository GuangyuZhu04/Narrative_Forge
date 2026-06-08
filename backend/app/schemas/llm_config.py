from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LLMConfigCreate(BaseModel):
    provider: str = Field(
        ...,
        pattern="^(deepseek|openai|anthropic|google|openai_compatible)$",
    )
    api_key: str
    base_url: str
    model_name: str
    default_params: dict[str, Any] | None = None
    rate_limit: dict[str, Any] | None = None


class LLMConfigUpdate(BaseModel):
    provider: str | None = Field(
        None,
        pattern="^(deepseek|openai|anthropic|google|openai_compatible)$",
    )
    api_key: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    default_params: dict[str, Any] | None = None
    rate_limit: dict[str, Any] | None = None
    is_active: bool | None = None


class LLMConfigResponse(BaseModel):
    id: str
    provider: str
    api_key_encrypted: str
    base_url: str
    model_name: str
    default_params: dict[str, Any] | None
    rate_limit: dict[str, Any] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LLMConfigTestResponse(BaseModel):
    success: bool
    message: str
    model_info: dict[str, Any] | None = None
