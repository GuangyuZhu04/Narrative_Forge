from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=200)
    description: str | None = None
    genre: str | None = Field(None, max_length=100)
    word_count_target: int | None = None
    settings: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    description: str | None = None
    genre: str | None = Field(None, max_length=100)
    word_count_target: int | None = None
    settings: str | None = None
    status: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    genre: str | None
    status: str
    word_count_target: int | None
    settings: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaginatedResponse(BaseModel):
    data: list[Any]
    total: int
    page: int
    page_size: int


class DataResponse(BaseModel):
    data: Any
    message: str = "success"
