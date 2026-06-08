from datetime import datetime

from pydantic import BaseModel, Field


class ChapterCreate(BaseModel):
    outline_node_id: str | None = None
    title: str
    content: str | None = None
    sort_order: int = 0


class ChapterUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    status: str | None = Field(
        None, pattern="^(draft|in_progress|completed|revised)$"
    )
    word_count: int | None = None


class ChapterResponse(BaseModel):
    id: str
    project_id: str
    outline_node_id: str | None
    title: str
    content: str | None
    summary: str | None
    sort_order: int
    status: str
    word_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AIAssistRequest(BaseModel):
    llm_config_id: str
    action: str = Field(
        ..., pattern="^(continue|rewrite|polish|expand|summarize|dialogue)$"
    )
    selection: str | None = None
    context: str | None = None


class AIAssistResponse(BaseModel):
    content: str
    action: str
    tokens_used: int


class NovelWriteContextOverride(BaseModel):
    outline_context: str | None = None
    volume_context: str | None = None
    chapter_title: str | None = None
    chapter_summary: str | None = None
    character_definitions: str | None = None
    previous_context: str | None = None
    previous_chapter_content: str | None = None
    style_requirements: str | None = None


class NovelWriteRequest(BaseModel):
    llm_config_id: str
    style_requirements: str | None = None
    write_context: NovelWriteContextOverride | None = None


class NovelWriteContextRequest(BaseModel):
    style_requirements: str | None = None


class NovelWritePreviousContextSummaryRequest(BaseModel):
    llm_config_id: str
    style_requirements: str | None = None


class NovelPolishRequest(BaseModel):
    llm_config_id: str
    polish_suggestions: str
    chapter_content: str | None = None


class VersionCreate(BaseModel):
    change_summary: str | None = None


class VersionResponse(BaseModel):
    id: str
    chapter_id: str
    version_number: int
    word_count: int
    change_summary: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class VersionCompareResponse(BaseModel):
    version1: int
    version2: int
    additions: int
    deletions: int
    unified_diff: list[str]
    html_diff: str
