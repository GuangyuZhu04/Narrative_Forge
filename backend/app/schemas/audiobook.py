from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AudiobookConfigUpdate(BaseModel):
    provider: str = Field(
        pattern="^(openai_compatible|comfyui|custom_http|custom_websocket|minimax_async)$"
    )
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str | None = None
    model_name: str = Field(default="tts-1", max_length=200)
    narrator_voice: str = Field(default="alloy", min_length=1, max_length=200)
    character_voices: dict[str, str] = Field(default_factory=dict)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    use_ffmpeg: bool = True
    max_chars_per_segment: int = Field(default=800, ge=100, le=50_000)
    request_timeout_seconds: int = Field(default=180, ge=10, le=1800)
    requests_per_minute: int = Field(default=20, ge=1, le=120)
    comfyui_workflow: dict[str, Any] | None = None
    custom_request: dict[str, Any] | None = None

    @field_validator("base_url")
    @classmethod
    def strip_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("character_voices")
    @classmethod
    def normalize_character_voices(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            str(character_id): str(voice).strip()
            for character_id, voice in value.items()
            if str(voice).strip()
        }


class AudiobookCharacterVoicesUpdate(BaseModel):
    character_voices: dict[str, str] = Field(default_factory=dict)

    @field_validator("character_voices")
    @classmethod
    def normalize_character_voices(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            str(character_id): str(voice).strip()
            for character_id, voice in value.items()
            if str(voice).strip()
        }


class AudiobookConfigResponse(BaseModel):
    id: str | None = None
    project_id: str
    provider: str
    base_url: str
    api_key_configured: bool
    model_name: str
    narrator_voice: str
    character_voices: dict[str, str]
    speed: float
    use_ffmpeg: bool
    max_chars_per_segment: int
    request_timeout_seconds: int
    requests_per_minute: int
    comfyui_workflow: dict[str, Any] | None
    custom_request: dict[str, Any] | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AudiobookPreviewRequest(BaseModel):
    text: str = Field(default="欢迎使用有声书生成功能。", min_length=1, max_length=300)
    voice: str | None = Field(default=None, max_length=200)


class AudiobookVoiceQueryRequest(BaseModel):
    voice_type: Literal["system", "voice_cloning", "voice_generation", "all"] = "all"


class AudiobookVoiceItem(BaseModel):
    voice_id: str
    voice_name: str | None = None
    description: list[str] = Field(default_factory=list)
    created_time: str | None = None
    voice_type: Literal["system", "voice_cloning", "voice_generation"]
    is_local_only: bool = False


class AudiobookVoiceQueryResponse(BaseModel):
    voices: list[AudiobookVoiceItem] = Field(default_factory=list)


class AudiobookVoiceDesignRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    preview_text: str = Field(min_length=1, max_length=500)
    voice_id: str | None = Field(default=None, max_length=200)
    aigc_watermark: bool = False

    @field_validator("prompt", "preview_text")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @field_validator("voice_id")
    @classmethod
    def strip_optional_voice_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AudiobookVoiceDesignResponse(BaseModel):
    voice: AudiobookVoiceItem
    trial_audio_base64: str
    trial_audio_content_type: str = "audio/mpeg"


class AudiobookVoiceDeleteRequest(BaseModel):
    voice_id: str = Field(min_length=1, max_length=200)
    voice_type: Literal["voice_cloning", "voice_generation"]

    @field_validator("voice_id")
    @classmethod
    def strip_voice_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("voice_id 不能为空")
        return value


class AudiobookVoiceDeleteResponse(BaseModel):
    voice_id: str
    voice_type: Literal["voice_cloning", "voice_generation"]
    created_time: str | None = None


class AudiobookApiDocsParseRequest(BaseModel):
    llm_config_id: str
    api_documentation: str = Field(min_length=20, max_length=100_000)


class AudiobookApiDocsParseResponse(BaseModel):
    provider: str = Field(
        pattern="^(openai_compatible|custom_http|custom_websocket|minimax_async)$"
    )
    base_url: str
    model_name: str
    narrator_voice: str
    speed: float = Field(ge=0.25, le=4.0)
    max_chars_per_segment: int = Field(ge=100, le=50_000)
    request_timeout_seconds: int = Field(ge=10, le=1800)
    requests_per_minute: int = Field(default=20, ge=1, le=120)
    custom_request: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class AudiobookJobCreate(BaseModel):
    scope_type: str = Field(pattern="^(book|volume|chapter)$")
    scope_id: str | None = None
    llm_config_id: str = Field(min_length=1, max_length=100)


class AudiobookArtifact(BaseModel):
    kind: str
    filename: str
    download_filename: str | None = None
    title: str
    size_bytes: int
    chapter_id: str | None = None


class AudiobookSegmentTask(BaseModel):
    chapter_id: str
    chapter_index: int
    segment_index: int
    voice_id: str
    status: str
    task_id: str | None = None
    file_id: str | None = None
    pause_after_ms: int = 0
    error_message: str | None = None


class AudiobookJobResponse(BaseModel):
    id: str
    project_id: str
    config_id: str | None
    script_llm_config_id: str | None
    scope_type: str
    scope_id: str | None
    scope_title: str
    status: str
    progress: int
    processed_chapters: int
    total_chapters: int
    current_chapter_title: str | None
    segment_tasks: list[AudiobookSegmentTask] = Field(default_factory=list)
    output_files: list[AudiobookArtifact]
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AudiobookScopeItem(BaseModel):
    id: str
    title: str
    chapter_count: int
    outline_title: str | None = None


class AudiobookScopesResponse(BaseModel):
    book_title: str
    book_chapter_count: int
    volumes: list[AudiobookScopeItem]
    chapters: list[AudiobookScopeItem]
