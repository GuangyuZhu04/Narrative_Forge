from typing import Any, Literal

from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    format: str
    options: dict[str, Any] | None = None


class PlatformExportRequest(BaseModel):
    platform: Literal["fanqie", "qidian"]
    options: dict[str, Any] | None = None


class PlatformExportChapter(BaseModel):
    title: str
    content: str
    word_count: int
    sort_order: int
    status: str


class PlatformExportResponse(BaseModel):
    platform: str
    platform_name: str
    target_url: str
    project_name: str
    chapter_count: int
    total_word_count: int
    clipboard_text: str
    chapters: list[PlatformExportChapter]
    warnings: list[str] = Field(default_factory=list)
