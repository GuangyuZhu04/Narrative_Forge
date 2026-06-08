from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CharacterCreate(BaseModel):
    name: str = Field(..., max_length=100)
    aliases: list[str] | None = None
    avatar_url: str | None = None
    basic_info: dict[str, Any] | None = None
    personality: dict[str, Any] | None = None
    growth_arc: dict[str, Any] | None = None
    biography: str | None = None
    setting_collection: str | None = None
    notes: str | None = None


class CharacterUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    aliases: list[str] | None = None
    avatar_url: str | None = None
    basic_info: dict[str, Any] | None = None
    personality: dict[str, Any] | None = None
    growth_arc: dict[str, Any] | None = None
    biography: str | None = None
    setting_collection: str | None = None
    notes: str | None = None


class CharacterResponse(BaseModel):
    id: str
    project_id: str
    name: str
    aliases: list[str] | None
    avatar_url: str | None
    basic_info: dict[str, Any] | None
    personality: dict[str, Any] | None
    growth_arc: dict[str, Any] | None
    biography: str | None
    setting_collection: str | None
    notes: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RelationshipCreate(BaseModel):
    source_id: str
    target_id: str
    relationship_type: str = Field(
        ...,
        pattern="^(FAMILY|FRIEND|ENEMY|LOVER|MENTOR|SUBORDINATE|ALLY|RIVAL|OTHER)$",
    )
    description: str | None = None
    intensity: int = Field(5, ge=1, le=10)
    start_chapter: str | None = None
    end_chapter: str | None = None


class RelationshipUpdate(BaseModel):
    relationship_type: str | None = Field(
        None,
        pattern="^(FAMILY|FRIEND|ENEMY|LOVER|MENTOR|SUBORDINATE|ALLY|RIVAL|OTHER)$",
    )
    description: str | None = None
    intensity: int | None = Field(None, ge=1, le=10)
    start_chapter: str | None = None
    end_chapter: str | None = None


class RelationshipResponse(BaseModel):
    id: str
    project_id: str
    source_id: str
    target_id: str
    relationship_type: str
    description: str | None
    intensity: int
    start_chapter: str | None
    end_chapter: str | None
    metadata: dict[str, Any] | None = None
    source_name: str | None = None
    target_name: str | None = None

    model_config = {"from_attributes": True}


class CharacterGenerateRequest(BaseModel):
    llm_config_id: str
    description: str


class CharacterImportRequest(BaseModel):
    llm_config_id: str
    text_content: str


class CharacterMoveRequest(BaseModel):
    new_order: int = Field(..., ge=0)
