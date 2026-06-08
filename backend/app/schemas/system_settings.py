from datetime import datetime

from pydantic import BaseModel


class SystemPromptSettingUpdate(BaseModel):
    value: str


class SystemPromptSettingResponse(BaseModel):
    key: str
    category: str
    title: str
    description: str
    value: str
    default_value: str
    effective_value: str
    is_custom: bool
    value_type: str = "text"
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    integer_only: bool = False
    updated_at: datetime | None = None


class SystemPromptSettingsResponse(BaseModel):
    data: list[SystemPromptSettingResponse]
