import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ["DEBUG"] = "false"

from app.db.session import get_db  # noqa: E402
from app.llm.providers.base import LLMOutputTruncatedError  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.services.discussion_service import DISCUSSION_MAX_TOKENS  # noqa: E402


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_db, None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _create_project(client):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "discussion project"},
    )
    assert project_response.status_code == 201
    return project_response.json()["id"]


@pytest.mark.anyio
async def test_discussion_sends_multi_round_history(client, monkeypatch):
    project_id = await _create_project(client)
    create_response = await client.post(
        f"/api/v1/projects/{project_id}/discussions",
        json={"title": "剧情讨论", "system_prompt": "你是小说顾问。"},
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["id"]

    calls = []

    async def fake_chat(config_id, messages, **kwargs):
        calls.append({"config_id": config_id, "messages": messages, "kwargs": kwargs})
        return "第一轮建议" if len(calls) == 1 else "第二轮建议"

    monkeypatch.setattr(
        "app.services.discussion_service.llm_orchestrator.chat", fake_chat
    )

    first_response = await client.post(
        f"/api/v1/projects/{project_id}/discussions/{session_id}/messages",
        json={"llm_config_id": "test-config", "content": "帮我设计主角"},
    )
    assert first_response.status_code == 200
    assert first_response.json()["assistant_message"]["content"] == "第一轮建议"

    second_response = await client.post(
        f"/api/v1/projects/{project_id}/discussions/{session_id}/messages",
        json={"llm_config_id": "test-config", "content": "继续补充反派"},
    )
    assert second_response.status_code == 200
    assert second_response.json()["assistant_message"]["content"] == "第二轮建议"

    assert calls[0]["config_id"] == "test-config"
    assert calls[0]["kwargs"]["temperature"] == 1.3
    assert calls[0]["kwargs"]["max_tokens"] == DISCUSSION_MAX_TOKENS
    assert calls[0]["messages"] == [
        {"role": "system", "content": "你是小说顾问。"},
        {"role": "user", "content": "帮我设计主角"},
    ]
    assert calls[1]["messages"] == [
        {"role": "system", "content": "你是小说顾问。"},
        {"role": "user", "content": "帮我设计主角"},
        {"role": "assistant", "content": "第一轮建议"},
        {"role": "user", "content": "继续补充反派"},
    ]

    detail_response = await client.get(
        f"/api/v1/projects/{project_id}/discussions/{session_id}"
    )
    assert detail_response.status_code == 200
    assert [item["role"] for item in detail_response.json()["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


@pytest.mark.anyio
async def test_discussion_returns_clear_error_when_llm_truncates(client, monkeypatch):
    project_id = await _create_project(client)
    create_response = await client.post(
        f"/api/v1/projects/{project_id}/discussions",
        json={"title": "截断测试"},
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["id"]

    async def fake_chat(config_id, messages, **kwargs):
        raise LLMOutputTruncatedError("LLM output stopped early: length")

    monkeypatch.setattr(
        "app.services.discussion_service.llm_orchestrator.chat", fake_chat
    )

    response = await client.post(
        f"/api/v1/projects/{project_id}/discussions/{session_id}/messages",
        json={"llm_config_id": "test-config", "content": "长篇讨论"},
    )
    assert response.status_code == 400
    assert "AI 回复达到模型长度限制" in response.json()["detail"]


@pytest.mark.anyio
async def test_discussion_streams_response_and_saves_messages(client, monkeypatch):
    project_id = await _create_project(client)
    create_response = await client.post(
        f"/api/v1/projects/{project_id}/discussions",
        json={"title": "流式讨论", "system_prompt": "你是小说顾问。"},
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["id"]

    calls = []

    async def fake_stream_chat(config_id, messages, **kwargs):
        calls.append({"config_id": config_id, "messages": messages, "kwargs": kwargs})
        yield "第一段"
        yield ""
        yield "第二段"

    monkeypatch.setattr(
        "app.api.v1.discussions.llm_orchestrator.stream_chat", fake_stream_chat
    )

    response = await client.post(
        f"/api/v1/projects/{project_id}/discussions/{session_id}/messages/stream",
        json={"llm_config_id": "test-config", "content": "帮我设计冲突"},
    )

    assert response.status_code == 200
    body = response.text
    assert '"type": "chunk"' in body
    assert "第一段" in body
    assert "第二段" in body
    assert '"type": "done"' in body
    assert calls[0]["config_id"] == "test-config"
    assert calls[0]["kwargs"]["temperature"] == 1.3
    assert calls[0]["kwargs"]["max_tokens"] == DISCUSSION_MAX_TOKENS
    assert calls[0]["messages"] == [
        {"role": "system", "content": "你是小说顾问。"},
        {"role": "user", "content": "帮我设计冲突"},
    ]

    detail_response = await client.get(
        f"/api/v1/projects/{project_id}/discussions/{session_id}"
    )
    assert detail_response.status_code == 200
    messages = detail_response.json()["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "第一段第二段"
