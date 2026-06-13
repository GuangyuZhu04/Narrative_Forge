from datetime import datetime

from pydantic import BaseModel, Field


class SceneCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    location: str | None = None
    time: str | None = None
    atmosphere: str | None = None
    description: str | None = None
    details: str | None = None
    notes: str | None = None


class SceneUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    location: str | None = None
    time: str | None = None
    atmosphere: str | None = None
    description: str | None = None
    details: str | None = None
    notes: str | None = None


class SceneMoveRequest(BaseModel):
    new_order: int = Field(..., ge=0)


class SceneImportRequest(BaseModel):
    llm_config_id: str
    text_content: str = Field(..., min_length=1)


class SceneResponse(BaseModel):
    id: str
    project_id: str
    name: str
    location: str | None
    time: str | None
    atmosphere: str | None
    description: str | None
    details: str | None
    notes: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
