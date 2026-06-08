from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ConsistencyAnalysisRequest(BaseModel):
    llm_config_id: str
    chapter_id: str
    dimensions: list[str] | None = None


class ConsistencyIssue(BaseModel):
    type: str
    location: str | None = None
    description: str
    severity: str | None = None
    suggestion: str | None = None
    character_name: str | None = None


class DimensionResult(BaseModel):
    issues: list[ConsistencyIssue]
    suggestions: list[Any] | None = None
    score: float | None = None


class ConsistencyAnalysisResponse(BaseModel):
    results: dict[str, DimensionResult]


class AnalysisChapterOptionResponse(BaseModel):
    id: str
    outline_node_id: str
    title: str
    summary: str | None = None
    volume_title: str | None = None
    sort_order: int


class AnalysisReportResponse(BaseModel):
    id: str
    project_id: str
    chapter_id: str | None
    chapter_title: str | None = None
    analysis_type: str
    status: str
    issues: list[dict[str, Any]] | None
    suggestions: list[Any] | None
    score: float | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
