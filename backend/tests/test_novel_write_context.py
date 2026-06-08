import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ["DEBUG"] = "false"

from app.db.session import get_db  # noqa: E402
from app.api.v1 import chapters as chapters_api  # noqa: E402
from app.llm.providers.base import LLMOutputTruncatedError  # noqa: E402
from app.llm.prompts.novel_polish import NOVEL_POLISH_SYSTEM  # noqa: E402
from app.llm.prompts.novel_write import NOVEL_WRITE_SYSTEM  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.schemas.chapter import NovelWriteContextOverride  # noqa: E402
from app.services.chapter_service import chapter_service  # noqa: E402


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


async def _create_project_outline_chapter(client):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "stream write context"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    outline_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"title": "Main outline", "description": "Main outline description"},
    )
    assert outline_response.status_code == 201
    outline_id = outline_response.json()["id"]

    volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "Volume one",
            "summary": "Volume one summary",
        },
    )
    assert volume_response.status_code == 201
    volume_id = volume_response.json()["id"]

    node_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "parent_id": volume_id,
            "node_type": "CHAPTER",
            "title": "大纲给出的章节标题",
            "summary": "大纲给出的章节摘要",
        },
    )
    assert node_response.status_code == 201
    node_id = node_response.json()["id"]

    chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": node_id,
            "title": "章节记录标题",
            "sort_order": 1,
        },
    )
    assert chapter_response.status_code == 201
    chapter_id = chapter_response.json()["id"]
    return project_id, chapter_id


async def _create_project_with_previous_and_current_chapters(client):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "previous context project"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    outline_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"title": "Main outline", "description": "Main outline description"},
    )
    assert outline_response.status_code == 201
    outline_id = outline_response.json()["id"]

    volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "第一卷",
            "summary": "第一卷围绕主角初入危局展开",
        },
    )
    assert volume_response.status_code == 201
    volume_id = volume_response.json()["id"]

    previous_node_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "parent_id": volume_id,
            "node_type": "CHAPTER",
            "title": "第一章 雨夜",
            "summary": "主角在雨夜发现旧案线索",
        },
    )
    assert previous_node_response.status_code == 201
    previous_node_id = previous_node_response.json()["id"]

    current_node_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "parent_id": volume_id,
            "node_type": "CHAPTER",
            "title": "第二章 旧门",
            "summary": "主角循着线索来到旧门前",
        },
    )
    assert current_node_response.status_code == 201
    current_node_id = current_node_response.json()["id"]

    previous_chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": previous_node_id,
            "title": "第一章 雨夜",
            "content": "雨夜里，主角握着染湿的信纸，意识到旧案并未结束。",
            "sort_order": 1,
        },
    )
    assert previous_chapter_response.status_code == 201

    current_chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": current_node_id,
            "title": "第二章 旧门",
            "sort_order": 2,
        },
    )
    assert current_chapter_response.status_code == 201
    current_chapter_id = current_chapter_response.json()["id"]
    return project_id, current_chapter_id


def test_novel_write_system_prompt_describes_ai_input_sections():
    for section in (
        "大纲信息",
        "卷信息",
        "章节标题",
        "章节摘要",
        "人物定义",
        "前文背景",
        "前一章内容",
        "文风要求",
    ):
        assert section in NOVEL_WRITE_SYSTEM
    assert "以【章节摘要】作为本章剧情主线" in NOVEL_WRITE_SYSTEM
    assert "以【前一章内容】保证紧邻章节的自然衔接" in NOVEL_WRITE_SYSTEM


@pytest.mark.anyio
async def test_novel_write_stream_keeps_alive_and_saves_content(
    client, monkeypatch
):
    project_id, chapter_id = await _create_project_outline_chapter(client)
    calls = []

    async def fake_stream_chat(config_id, messages, **kwargs):
        calls.append({"config_id": config_id, "messages": messages, "kwargs": kwargs})
        yield ""
        yield "第一段正文"
        yield "第二段正文"

    monkeypatch.setattr(
        chapters_api.llm_orchestrator, "stream_chat", fake_stream_chat
    )

    response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-stream",
        json={"llm_config_id": "test-config"},
    )

    assert response.status_code == 200
    body = response.text
    assert "event: ping" in body
    assert "event: done" in body
    assert "word_count" in body

    saved_response = await client.get(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}"
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    saved_content = "第一段正文第二段正文"
    assert saved["content"] == saved_content
    assert saved["word_count"] == len(saved_content)
    assert calls[0]["kwargs"]["max_tokens"] == chapters_api.NOVEL_WRITE_MAX_TOKENS


@pytest.mark.anyio
async def test_novel_write_stream_auto_continues_when_provider_truncates(
    client, monkeypatch
):
    project_id, chapter_id = await _create_project_outline_chapter(client)
    calls = []

    async def fake_stream_chat(config_id, messages, **kwargs):
        calls.append({"config_id": config_id, "messages": messages, "kwargs": kwargs})
        if len(calls) == 1:
            yield "第一段正文"
            raise LLMOutputTruncatedError("length")
        yield "第二段正文"

    monkeypatch.setattr(
        chapters_api.llm_orchestrator, "stream_chat", fake_stream_chat
    )

    response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-stream",
        json={"llm_config_id": "test-config"},
    )

    assert response.status_code == 200
    body = response.text
    assert "event: status" in body
    assert "event: error" not in body
    assert "event: done" in body
    assert len(calls) == 2
    assert calls[0]["kwargs"]["max_tokens"] == chapters_api.NOVEL_WRITE_MAX_TOKENS
    assert calls[1]["kwargs"]["max_tokens"] == chapters_api.NOVEL_WRITE_MAX_TOKENS
    assert calls[1]["messages"][-2]["role"] == "assistant"
    assert "第一段正文" in calls[1]["messages"][-2]["content"]
    assert "模型输出长度限制" in calls[1]["messages"][-1]["content"]

    saved_response = await client.get(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}"
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    assert saved["content"] == "第一段正文第二段正文"


@pytest.mark.anyio
async def test_novel_write_stream_reports_empty_content_error(
    client, monkeypatch
):
    project_id, chapter_id = await _create_project_outline_chapter(client)

    async def fake_stream_chat(config_id, messages, **kwargs):
        yield ""

    monkeypatch.setattr(
        chapters_api.llm_orchestrator, "stream_chat", fake_stream_chat
    )

    response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-stream",
        json={"llm_config_id": "test-config"},
    )

    assert response.status_code == 200
    body = response.text
    assert "event: ping" in body
    assert "event: error" in body
    assert "event: done" not in body

    saved_response = await client.get(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}"
    )
    assert saved_response.status_code == 200
    assert saved_response.json()["content"] is None


@pytest.mark.anyio
async def test_novel_write_context_uses_outline_node_title(client):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "novel write context"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    outline_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"title": "Main outline", "description": "Main outline description"},
    )
    assert outline_response.status_code == 201
    outline_id = outline_response.json()["id"]

    volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "Volume one",
            "summary": "Volume one summary",
        },
    )
    assert volume_response.status_code == 201
    volume_id = volume_response.json()["id"]

    node_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "parent_id": volume_id,
            "node_type": "CHAPTER",
            "title": "大纲给出的章节标题",
            "summary": "大纲给出的章节摘要",
        },
    )
    assert node_response.status_code == 201
    node_id = node_response.json()["id"]

    chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": node_id,
            "title": "章节记录标题",
            "sort_order": 1,
        },
    )
    assert chapter_response.status_code == 201
    chapter_id = chapter_response.json()["id"]

    character_response = await client.post(
        f"/api/v1/projects/{project_id}/characters",
        json={
            "name": "林远",
            "biography": "林远少年时曾在雪夜失去师门，因此极度害怕再次失去同伴。",
            "setting_collection": "林远真正的师门灭门线索暂不暴露给 AI 编写。",
        },
    )
    assert character_response.status_code == 201
    assert character_response.json()["biography"] == (
        "林远少年时曾在雪夜失去师门，因此极度害怕再次失去同伴。"
    )
    assert character_response.json()["setting_collection"] == (
        "林远真正的师门灭门线索暂不暴露给 AI 编写。"
    )

    context_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-context",
        json={},
    )

    assert context_response.status_code == 200
    context = context_response.json()
    assert context["chapter_title"] == "大纲给出的章节标题"
    assert "stored_chapter_title" not in context
    assert context["chapter_summary"] == "大纲给出的章节摘要"
    assert "Main outline" in context["outline_context"]
    assert "Main outline description" in context["outline_context"]
    assert "Volume one" in context["volume_context"]
    assert "Volume one summary" in context["volume_context"]
    assert "人物小传：林远少年时曾在雪夜失去师门" in context["character_definitions"]
    assert "师门灭门线索暂不暴露" not in context["character_definitions"]

    messages = chapter_service.build_novel_write_messages(context)
    assert "【大纲信息】" in messages[1]["content"]
    assert "【卷信息】" in messages[1]["content"]
    assert "【章节标题】" in messages[1]["content"]
    assert "大纲给出的章节标题" in messages[1]["content"]


@pytest.mark.anyio
async def test_novel_write_context_includes_previous_volume_context(client):
    project_id, chapter_id = await _create_project_with_previous_and_current_chapters(
        client
    )

    context_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-context",
        json={},
    )

    assert context_response.status_code == 200
    context = context_response.json()
    assert context["previous_chapter_title"] == "第一章 雨夜"
    assert "主角在雨夜发现旧案线索" in context["previous_context"]
    assert "雨夜里，主角握着染湿的信纸" in context["previous_chapter_content"]

    messages = chapter_service.build_novel_write_messages(context)
    assert "【前文背景】" in messages[1]["content"]
    assert "【前一章内容】" in messages[1]["content"]
    assert "雨夜里，主角握着染湿的信纸" in messages[1]["content"]


@pytest.mark.anyio
async def test_summarize_previous_context_uses_previous_volume_chapters(
    client, monkeypatch
):
    project_id, chapter_id = await _create_project_with_previous_and_current_chapters(
        client
    )
    captured = {}

    async def fake_chat(config_id, messages, **kwargs):
        captured["config_id"] = config_id
        captured["messages"] = messages
        captured["temperature"] = kwargs.get("temperature")
        return "AI 汇总后的前文背景"

    monkeypatch.setattr(chapters_api.llm_orchestrator, "chat", fake_chat)

    response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-context/summary",
        json={"llm_config_id": "test-config"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["previous_context"] == "AI 汇总后的前文背景"
    assert result["chapter_count"] == 1
    assert captured["config_id"] == "test-config"
    assert captured["temperature"] == 1.1
    assert "雨夜里，主角握着染湿的信纸" in captured["messages"][1]["content"]


@pytest.mark.anyio
async def test_novel_polish_uses_suggestions_and_saves_content(client, monkeypatch):
    project_id, chapter_id = await _create_project_outline_chapter(client)
    captured = {}

    async def fake_chat(config_id, messages, **kwargs):
        captured["config_id"] = config_id
        captured["messages"] = messages
        captured["temperature"] = kwargs.get("temperature")
        captured["max_tokens"] = kwargs.get("max_tokens")
        return "打磨后的完整章节正文"

    monkeypatch.setattr(chapters_api.llm_orchestrator, "chat", fake_chat)

    response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-polish",
        json={
            "llm_config_id": "test-config",
            "chapter_content": "原始章节正文",
            "polish_suggestions": "问题：人物动机不够清晰；建议：补足行动原因。",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["content"] == "打磨后的完整章节正文"
    assert result["word_count"] == len("打磨后的完整章节正文")
    assert captured["config_id"] == "test-config"
    assert captured["messages"][0]["content"] == NOVEL_POLISH_SYSTEM
    assert "原始章节正文" in captured["messages"][1]["content"]
    assert "人物动机不够清晰" in captured["messages"][1]["content"]
    assert captured["temperature"] == 1.2
    assert captured["max_tokens"] == chapters_api.NOVEL_WRITE_MAX_TOKENS

    saved_response = await client.get(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}"
    )
    assert saved_response.status_code == 200
    assert saved_response.json()["content"] == "打磨后的完整章节正文"


@pytest.mark.anyio
async def test_novel_polish_stream_saves_content(client, monkeypatch):
    project_id, chapter_id = await _create_project_outline_chapter(client)
    calls = []

    async def fake_stream_chat(config_id, messages, **kwargs):
        calls.append({"config_id": config_id, "messages": messages, "kwargs": kwargs})
        yield "打磨后第一段"
        yield ""
        yield "打磨后第二段"

    monkeypatch.setattr(
        chapters_api.llm_orchestrator, "stream_chat", fake_stream_chat
    )

    response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-polish-stream",
        json={
            "llm_config_id": "test-config",
            "chapter_content": "原始章节正文",
            "polish_suggestions": "补足人物动机。",
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "event: chunk" in body
    assert "event: ping" in body
    assert "event: done" in body
    assert "word_count" in body
    assert calls[0]["config_id"] == "test-config"
    assert calls[0]["kwargs"]["temperature"] == 1.2
    assert calls[0]["kwargs"]["max_tokens"] == chapters_api.NOVEL_WRITE_MAX_TOKENS
    assert "原始章节正文" in calls[0]["messages"][1]["content"]
    assert "补足人物动机" in calls[0]["messages"][1]["content"]

    saved_response = await client.get(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}"
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    saved_content = "打磨后第一段打磨后第二段"
    assert saved["content"] == saved_content
    assert saved["word_count"] == len(saved_content)


def test_novel_write_context_overrides_are_used_in_prompt():
    context = {
        "chapter_id": "chapter-id",
        "outline_id": "outline-id",
        "outline_title": "默认大纲",
        "outline_context": "默认大纲信息",
        "volume_node_id": "volume-id",
        "volume_title": "默认卷",
        "volume_context": "默认卷信息",
        "chapter_title": "默认标题",
        "outline_node_id": "node-id",
        "outline_node_title": "默认标题",
        "chapter_summary": "默认摘要",
        "character_definitions": "默认人物",
        "character_count": 1,
        "previous_chapter_title": "上一章",
        "previous_context": "默认前文",
        "previous_chapter_content": "默认前一章内容",
        "style_requirements": "默认文风",
    }
    overrides = NovelWriteContextOverride(
        outline_context="临时大纲信息",
        volume_context="临时卷信息",
        chapter_title="临时标题",
        chapter_summary="临时摘要",
        character_definitions="临时人物",
        previous_context="临时前文",
        previous_chapter_content="临时前一章内容",
        style_requirements="临时文风",
    )

    updated = chapter_service.apply_novel_write_context_overrides(
        context, overrides
    )
    messages = chapter_service.build_novel_write_messages(updated)

    prompt = messages[1]["content"]
    assert "临时大纲信息" in prompt
    assert "临时卷信息" in prompt
    assert "临时标题" in prompt
    assert "临时摘要" in prompt
    assert "临时人物" in prompt
    assert "临时前文" in prompt
    assert "临时前一章内容" in prompt
    assert "临时文风" in prompt
    assert "默认大纲信息" not in prompt
    assert "默认卷信息" not in prompt
    assert "默认摘要" not in prompt
    assert "默认前一章内容" not in prompt
