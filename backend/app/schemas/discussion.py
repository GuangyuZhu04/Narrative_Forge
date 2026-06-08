from datetime import datetime

from pydantic import BaseModel, Field


class DiscussionSessionCreate(BaseModel):
    title: str | None = Field(None, max_length=200)
    system_prompt: str | None = None


class DiscussionSessionUpdate(BaseModel):
    title: str | None = Field(None, max_length=200)
    system_prompt: str | None = None


class DiscussionMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscussionSessionResponse(BaseModel):
    id: str
    project_id: str
    title: str
    system_prompt: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscussionSessionDetail(DiscussionSessionResponse):
    messages: list[DiscussionMessageResponse]


class DiscussionSendRequest(BaseModel):
    llm_config_id: str
    content: str = Field(..., min_length=1)
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1, le=32768)


class DiscussionSendResponse(BaseModel):
    session: DiscussionSessionResponse
    user_message: DiscussionMessageResponse
    assistant_message: DiscussionMessageResponse
