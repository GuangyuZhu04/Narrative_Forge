from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, AliasChoices


class OutlineCreate(BaseModel):
    title: str = Field(..., max_length=300)
    description: str | None = None


class OutlineUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    description: str | None = None


class OutlineResponse(BaseModel):
    id: str
    project_id: str
    title: str
    description: str | None
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OutlineNodeCreate(BaseModel):
    outline_id: str
    parent_id: str | None = None
    node_type: str = Field(..., pattern="^(VOLUME|CHAPTER|SCENE|PLOT_POINT|KEY_EVENT)$")
    title: str
    summary: str | None = None
    sort_order: int | None = None
    metadata: dict[str, Any] | None = None


class OutlineNodeUpdate(BaseModel):
    node_type: str | None = Field(
        None, pattern="^(VOLUME|CHAPTER|SCENE|PLOT_POINT|KEY_EVENT)$"
    )
    title: str | None = None
    summary: str | None = None
    sort_order: int | None = None
    metadata: dict[str, Any] | None = None


class OutlineNodeMove(BaseModel):
    new_parent_id: str | None
    new_order: int


class OutlineNodeResponse(BaseModel):
    id: str
    outline_id: str
    parent_id: str | None
    node_type: str
    title: str
    summary: str | None
    sort_order: int
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_", "metadata"),
    )
    llm_generated: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class OutlineNodeTreeItem(BaseModel):
    id: str
    node_type: str
    title: str
    summary: str | None
    sort_order: int
    metadata: dict[str, Any] | None
    llm_generated: bool
    children: list["OutlineNodeTreeItem"] = []


class OutlineTreeResponse(BaseModel):
    outline: OutlineResponse
    tree: list[OutlineNodeTreeItem]


class OutlineGenerateRequest(BaseModel):
    llm_config_id: str
    params: dict[str, str]


class OutlineExpandRequest(BaseModel):
    llm_config_id: str
    params: dict[str, Any] | None = None


class OutlineOptimizeRequest(BaseModel):
    llm_config_id: str
    direction: str | None = None
