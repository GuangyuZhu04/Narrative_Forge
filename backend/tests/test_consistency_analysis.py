import json
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ["DEBUG"] = "false"

from app.db.session import get_db  # noqa: E402
from app.llm.json_mode import DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
import app.services.consistency_service as consistency_module  # noqa: E402


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


async def _create_project_with_outline_chapter(
    client: AsyncClient,
    project_name: str = "consistency project",
) -> tuple[str, str]:
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": project_name},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    outline_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"title": "主线大纲", "description": "主线大纲说明"},
    )
    assert outline_response.status_code == 201
    outline_id = outline_response.json()["id"]

    volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "第一卷",
            "summary": "第一卷摘要",
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
            "title": "大纲章节标题",
            "summary": "大纲章节摘要",
        },
    )
    assert node_response.status_code == 201
    node_id = node_response.json()["id"]

    chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": node_id,
            "title": "章节记录标题",
            "summary": "章节记录摘要",
            "content": "当前章节正文内容。",
            "sort_order": 1,
        },
    )
    assert chapter_response.status_code == 201
    chapter_id = chapter_response.json()["id"]
    return project_id, chapter_id


async def _create_project_with_neighbor_chapters(
    client: AsyncClient,
) -> tuple[str, str]:
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "continuity neighbor project"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    outline_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"title": "跨卷大纲", "description": "用于测试前后章节"},
    )
    assert outline_response.status_code == 201
    outline_id = outline_response.json()["id"]

    first_volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "第一卷",
            "summary": "第一卷摘要",
            "sort_order": 0,
        },
    )
    assert first_volume_response.status_code == 201
    first_volume_id = first_volume_response.json()["id"]

    second_volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "第二卷",
            "summary": "第二卷摘要",
            "sort_order": 1,
        },
    )
    assert second_volume_response.status_code == 201
    second_volume_id = second_volume_response.json()["id"]

    previous_node_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "parent_id": first_volume_id,
            "node_type": "CHAPTER",
            "title": "上一章",
            "summary": "上一章摘要",
            "sort_order": 0,
        },
    )
    assert previous_node_response.status_code == 201
    previous_node_id = previous_node_response.json()["id"]

    current_node_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "parent_id": first_volume_id,
            "node_type": "CHAPTER",
            "title": "当前章",
            "summary": "当前章摘要",
            "sort_order": 1,
        },
    )
    assert current_node_response.status_code == 201
    current_node_id = current_node_response.json()["id"]

    next_node_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "parent_id": second_volume_id,
            "node_type": "CHAPTER",
            "title": "下一章",
            "summary": "下一章摘要",
            "sort_order": 0,
        },
    )
    assert next_node_response.status_code == 201
    next_node_id = next_node_response.json()["id"]

    previous_chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": previous_node_id,
            "title": "上一章记录",
            "content": "上一章正文：主角在雨夜收到密信。",
            "sort_order": 0,
        },
    )
    assert previous_chapter_response.status_code == 201

    current_chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": current_node_id,
            "title": "当前章记录",
            "content": "当前章正文：主角决定启程寻找真相。",
            "sort_order": 1,
        },
    )
    assert current_chapter_response.status_code == 201

    next_chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": next_node_id,
            "title": "下一章记录",
            "content": "下一章正文：主角抵达边城并遇见旧友。",
            "sort_order": 2,
        },
    )
    assert next_chapter_response.status_code == 201

    return project_id, current_chapter_response.json()["id"]


@pytest.mark.anyio
async def test_consistency_analysis_uses_outline_chapter_info(client, monkeypatch):
    project_id, chapter_id = await _create_project_with_outline_chapter(client)
    captured_messages = []
    captured_kwargs = []

    async def fake_chat(config_id, messages, **kwargs):
        captured_messages.append(messages)
        captured_kwargs.append(kwargs)
        return json.dumps({"issues": [], "suggestions": ["保持本章演绎方向。"], "score": 91})

    monkeypatch.setattr(consistency_module.llm_orchestrator, "chat", fake_chat)

    analyze_response = await client.post(
        f"/api/v1/projects/{project_id}/analysis/consistency",
        json={
            "llm_config_id": "test-config",
            "chapter_id": chapter_id,
            "dimensions": ["plot"],
        },
    )

    assert analyze_response.status_code == 200
    assert captured_messages
    assert (
        captured_kwargs[0]["response_format"] == DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT
    )
    user_prompt = captured_messages[0][1]["content"]
    assert "大纲章节标题" in user_prompt
    assert "大纲章节摘要" in user_prompt
    assert "章节记录标题" not in user_prompt
    assert "章节记录摘要" not in user_prompt

    reports_response = await client.get(
        f"/api/v1/projects/{project_id}/analysis/reports"
    )
    assert reports_response.status_code == 200
    reports = reports_response.json()["data"]
    assert reports[0]["chapter_id"] == chapter_id
    assert reports[0]["chapter_title"] == "大纲章节标题"
    assert reports[0]["suggestions"] == ["保持本章演绎方向。"]


@pytest.mark.anyio
async def test_plot_continuity_includes_previous_and_next_chapter_content(
    client, monkeypatch
):
    project_id, chapter_id = await _create_project_with_neighbor_chapters(client)
    captured_messages = []
    captured_kwargs = []

    async def fake_chat(config_id, messages, **kwargs):
        captured_messages.append(messages)
        captured_kwargs.append(kwargs)
        return json.dumps({"issues": [], "suggestions": [], "score": 90})

    monkeypatch.setattr(consistency_module.llm_orchestrator, "chat", fake_chat)

    analyze_response = await client.post(
        f"/api/v1/projects/{project_id}/analysis/consistency",
        json={
            "llm_config_id": "test-config",
            "chapter_id": chapter_id,
            "dimensions": ["plot_continuity"],
        },
    )

    assert analyze_response.status_code == 200
    assert captured_messages
    assert (
        captured_kwargs[0]["response_format"] == DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT
    )
    user_prompt = captured_messages[0][1]["content"]
    assert "上一章正文：主角在雨夜收到密信。" in user_prompt
    assert "当前章正文：主角决定启程寻找真相。" in user_prompt
    assert "下一章正文：主角抵达边城并遇见旧友。" in user_prompt


@pytest.mark.anyio
async def test_consistency_chapter_options_hide_deleted_outline_nodes(
    client, monkeypatch
):
    project_id, chapter_id = await _create_project_with_outline_chapter(client)

    async def fake_chat(config_id, messages, **kwargs):
        return json.dumps({"issues": [], "suggestions": [], "score": 90})

    monkeypatch.setattr(consistency_module.llm_orchestrator, "chat", fake_chat)

    chapter_list_response = await client.get(
        f"/api/v1/projects/{project_id}/chapters"
    )
    assert chapter_list_response.status_code == 200
    stored_title = chapter_list_response.json()["data"][0]["title"]

    options_response = await client.get(
        f"/api/v1/projects/{project_id}/analysis/chapters"
    )
    assert options_response.status_code == 200
    options = options_response.json()["data"]
    assert len(options) == 1
    assert options[0]["id"] == chapter_id
    assert options[0]["title"] != stored_title
    outline_node_id = options[0]["outline_node_id"]

    analyze_response = await client.post(
        f"/api/v1/projects/{project_id}/analysis/consistency",
        json={
            "llm_config_id": "test-config",
            "chapter_id": chapter_id,
            "dimensions": ["plot_consistency"],
        },
    )
    assert analyze_response.status_code == 200

    delete_response = await client.delete(
        f"/api/v1/projects/{project_id}/outlines/nodes/{outline_node_id}"
    )
    assert delete_response.status_code == 204

    options_after_delete = await client.get(
        f"/api/v1/projects/{project_id}/analysis/chapters"
    )
    assert options_after_delete.status_code == 200
    assert options_after_delete.json()["data"] == []

    reports_after_delete = await client.get(
        f"/api/v1/projects/{project_id}/analysis/reports"
    )
    assert reports_after_delete.status_code == 200
    assert reports_after_delete.json()["data"] == []

    stale_analyze_response = await client.post(
        f"/api/v1/projects/{project_id}/analysis/consistency",
        json={
            "llm_config_id": "test-config",
            "chapter_id": chapter_id,
            "dimensions": ["plot_consistency"],
        },
    )
    assert stale_analyze_response.status_code == 404


@pytest.mark.anyio
async def test_consistency_reports_only_show_latest_result(client, monkeypatch):
    project_id, chapter_id = await _create_project_with_outline_chapter(client)
    call_count = 0

    async def fake_chat(config_id, messages, **kwargs):
        nonlocal call_count
        call_count += 1
        return json.dumps(
            {
                "issues": [],
                "suggestions": [f"第 {call_count} 次分析建议"],
                "score": 80 + call_count,
            }
        )

    monkeypatch.setattr(consistency_module.llm_orchestrator, "chat", fake_chat)

    for _ in range(2):
        response = await client.post(
            f"/api/v1/projects/{project_id}/analysis/consistency",
            json={
                "llm_config_id": "test-config",
                "chapter_id": chapter_id,
                "dimensions": ["plot_consistency"],
            },
        )
        assert response.status_code == 200

    reports_response = await client.get(
        f"/api/v1/projects/{project_id}/analysis/reports",
        params={"chapter_id": chapter_id},
    )

    assert reports_response.status_code == 200
    reports = reports_response.json()["data"]
    assert len(reports) == 1
    assert reports[0]["analysis_type"] == "plot_consistency"
    assert reports[0]["score"] == 82
    assert reports[0]["suggestions"] == ["第 2 次分析建议"]


@pytest.mark.anyio
async def test_consistency_analysis_rejects_chapter_from_other_project(client):
    project_one_response = await client.post(
        "/api/v1/projects",
        json={"name": "project one"},
    )
    assert project_one_response.status_code == 201
    project_one_id = project_one_response.json()["id"]

    _, other_chapter_id = await _create_project_with_outline_chapter(
        client, "project two"
    )

    response = await client.post(
        f"/api/v1/projects/{project_one_id}/analysis/consistency",
        json={
            "llm_config_id": "test-config",
            "chapter_id": other_chapter_id,
            "dimensions": ["plot"],
        },
    )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_stream_consistency_analysis_uses_outline_and_character_info(
    client, monkeypatch
):
    project_id, chapter_id = await _create_project_with_outline_chapter(client)
    character_response = await client.post(
        f"/api/v1/projects/{project_id}/characters",
        json={"name": "林远", "biography": "少年时曾失去师门。"},
    )
    assert character_response.status_code == 201
    captured = {}

    async def fake_stream_chat(config_id, messages, **kwargs):
        captured["messages"] = messages
        yield "分析片段"

    monkeypatch.setattr(
        consistency_module.llm_orchestrator, "stream_chat", fake_stream_chat
    )

    response = await client.post(
        f"/api/v1/projects/{project_id}/analysis/consistency/stream",
        json={
            "llm_config_id": "test-config",
            "chapter_id": chapter_id,
            "dimensions": ["character"],
        },
    )

    assert response.status_code == 200
    assert "event: chunk" in response.text
    user_prompt = captured["messages"][1]["content"]
    assert "大纲章节标题" in user_prompt
    assert "大纲章节摘要" in user_prompt
    assert "林远" in user_prompt
    assert "少年时曾失去师门" in user_prompt
