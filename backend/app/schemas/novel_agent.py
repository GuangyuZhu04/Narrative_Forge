from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.character import CharacterResponse
from app.schemas.chapter import ChapterResponse
from app.schemas.outline import OutlineResponse
from app.schemas.project import ProjectResponse
from app.schemas.scene import SceneResponse


class NovelAgentWriteRequest(BaseModel):
    session_id: str | None = None
    llm_config_id: str
    idea: str = Field(..., min_length=1, max_length=20000)
    genre: str | None = Field(None, max_length=100)
    style_requirements: str | None = None
    extra_requirements: str | None = None
    volume_count: int = Field(3, ge=1, le=12)
    chapter_count: int = Field(
        30,
        ge=1,
        le=100,
        description="全书所有卷合计生成的章节总数",
    )
    word_count_target: int = Field(300000, ge=10000, le=5000000)
    write_chapter_count: int = Field(3, ge=0, le=100)
    update_project: bool = True
    use_deepseek_responses_api: bool = True

    @model_validator(mode="after")
    def validate_total_chapter_count(self):
        if self.chapter_count < self.volume_count:
            raise ValueError("全书总章数不能少于卷数")
        return self


class NovelAgentContinueRequest(BaseModel):
    session_id: str | None = None
    llm_config_id: str
    instruction: str = Field(..., min_length=1, max_length=20000)
    style_requirements: str | None = None
    max_actions: int = Field(10, ge=1, le=50)


class NovelAgentExecuteRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class NovelAgentPlanResponse(BaseModel):
    session_id: str
    status: Literal["awaiting_confirmation"]
    plan: dict[str, Any]
    steps: list[dict[str, Any]]


class NovelAgentSessionCreate(BaseModel):
    mode: Literal["generate", "continue_edit", "chat_generate"]
    name: str | None = Field(None, max_length=200)


class NovelAgentSessionUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Agent 会话名称不能为空")
        return name


class NovelAgentSessionResponse(BaseModel):
    id: str
    project_id: str
    mode: Literal["generate", "continue_edit", "chat_generate"]
    name: str
    status: str
    request_payload: dict[str, Any] | None
    plan: dict[str, Any] | None
    result: dict[str, Any] | None
    steps: list[dict[str, Any]] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NovelAgentStepResult(BaseModel):
    step: str
    label: str
    status: str
    message: str
    current: int | None = None
    total: int | None = None


class NovelAgentWriteResponse(BaseModel):
    session_id: str | None = None
    project: ProjectResponse
    outline: OutlineResponse
    characters: list[CharacterResponse]
    scenes: list[SceneResponse]
    chapters: list[ChapterResponse]
    written_chapters: list[ChapterResponse]
    blueprint: dict[str, Any]
    steps: list[NovelAgentStepResult]


class NovelAgentChatAnswer(BaseModel):
    question_id: str = Field(..., min_length=1, max_length=100)
    option_id: str | None = Field(None, max_length=100)
    custom_text: str | None = Field(None, max_length=20000)

    @model_validator(mode="after")
    def validate_answer_value(self):
        if not self.option_id and not (self.custom_text or "").strip():
            raise ValueError("请选择一个选项或输入自定义答案")
        return self


class NovelAgentChatTurnRequest(BaseModel):
    session_id: str | None = None
    llm_config_id: str
    message: str | None = Field(None, max_length=20000)
    answers: list[NovelAgentChatAnswer] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_turn_input(self):
        if not (self.message or "").strip() and not self.answers and self.session_id:
            raise ValueError("请输入消息或回答当前问题")
        return self


class NovelAgentChatOption(BaseModel):
    id: str
    label: str
    description: str
    recommended: bool = False
    value: dict[str, Any] = Field(default_factory=dict)


class NovelAgentChatQuestion(BaseModel):
    id: str
    header: str
    question: str
    options: list[NovelAgentChatOption] = Field(min_length=2, max_length=3)
    allow_custom: bool = True
    state_version: int

    @model_validator(mode="after")
    def validate_options(self):
        option_ids = [item.id for item in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("选项 ID 必须唯一")
        if sum(item.recommended for item in self.options) != 1:
            raise ValueError("每个问题必须且只能包含一个推荐选项")
        return self
