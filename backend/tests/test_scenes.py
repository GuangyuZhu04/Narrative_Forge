import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ["DEBUG"] = "false"

from app.db.session import get_db  # noqa: E402
from app.llm.json_mode import DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT  # noqa: E402
from app.llm.providers.base import LLMOutputTruncatedError  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.services.scene_service import SCENE_IMPORT_MAX_TOKENS  # noqa: E402


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


@pytest.mark.anyio
async def test_scene_crud_and_novel_write_context(client):
    project_resp = await client.post(
        "/api/v1/projects",
        json={"name": "场景测试项目"},
    )
    project_id = project_resp.json()["id"]

    scene_resp = await client.post(
        f"/api/v1/projects/{project_id}/scenes",
        json={
            "name": "雨夜码头",
            "location": "旧港",
            "time": "深夜",
            "atmosphere": "潮湿、压抑",
            "description": "灯光在水面碎成冷白色。",
        },
    )
    assert scene_resp.status_code == 201
    scene = scene_resp.json()
    assert scene["name"] == "雨夜码头"

    list_resp = await client.get(f"/api/v1/projects/{project_id}/scenes")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["data"]) == 1

    chapter_resp = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={"title": "第一章"},
    )
    chapter_id = chapter_resp.json()["id"]

    context_resp = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-context",
        json={},
    )
    assert context_resp.status_code == 200
    context = context_resp.json()
    assert context["scene_context"] == "暂无场景信息"
    assert context["scene_count"] == 1
    assert context["scenes"][0]["name"] == "雨夜码头"
    assert context["scenes"][0]["selected"] is False

    update_resp = await client.put(
        f"/api/v1/projects/{project_id}/scenes/{scene['id']}",
        json={"atmosphere": "危险、冷清"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["atmosphere"] == "危险、冷清"

    delete_resp = await client.delete(
        f"/api/v1/projects/{project_id}/scenes/{scene['id']}"
    )
    assert delete_resp.status_code == 204


@pytest.mark.anyio
async def test_scene_move_order_is_used_by_novel_write_context(client):
    project_resp = await client.post(
        "/api/v1/projects",
        json={"name": "场景排序项目"},
    )
    project_id = project_resp.json()["id"]

    created = []
    for name in ("旧港码头", "玻璃温室", "地下书库"):
        response = await client.post(
            f"/api/v1/projects/{project_id}/scenes",
            json={"name": name, "description": f"{name}描述"},
        )
        assert response.status_code == 201
        created.append(response.json())

    move_resp = await client.put(
        f"/api/v1/projects/{project_id}/scenes/{created[0]['id']}/move",
        json={"new_order": 2},
    )
    assert move_resp.status_code == 200
    assert [scene["name"] for scene in move_resp.json()["data"]] == [
        "玻璃温室",
        "地下书库",
        "旧港码头",
    ]

    list_resp = await client.get(f"/api/v1/projects/{project_id}/scenes")
    assert list_resp.status_code == 200
    assert [scene["name"] for scene in list_resp.json()["data"]] == [
        "玻璃温室",
        "地下书库",
        "旧港码头",
    ]

    chapter_resp = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={"title": "第一章"},
    )
    chapter_id = chapter_resp.json()["id"]

    context_resp = await client.post(
        f"/api/v1/projects/{project_id}/chapters/{chapter_id}/novel-write-context",
        json={},
    )
    assert context_resp.status_code == 200
    assert [scene["name"] for scene in context_resp.json()["scenes"]] == [
        "玻璃温室",
        "地下书库",
        "旧港码头",
    ]


@pytest.mark.anyio
async def test_scene_import_uses_system_prompt_setting(client, monkeypatch):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "scene import prompt project"},
    )
    project_id = project_response.json()["id"]

    custom_prompt = "Use this custom scene import system prompt."
    update_response = await client.put(
        "/api/v1/system-settings/prompts/scene_import.system",
        json={"value": custom_prompt},
    )
    assert update_response.status_code == 200

    captured = {}

    async def fake_chat(config_id, messages, **kwargs):
        captured["config_id"] = config_id
        captured["messages"] = messages
        captured["temperature"] = kwargs.get("temperature")
        captured["max_tokens"] = kwargs.get("max_tokens")
        captured["response_format"] = kwargs.get("response_format")
        return """
        {
          "scenes": [
            {
              "name": "雨夜码头",
              "location": "旧港",
              "time": "深夜",
              "atmosphere": "潮湿、压抑",
              "description": "灯光在水面碎成冷白色。",
              "details": "铁链、雾号、积水、摇晃的旧船。",
              "notes": "适合秘密交易或告别戏。"
            },
            {
              "name": "玻璃温室",
              "location": "庄园后院",
              "time": "清晨",
              "atmosphere": "温柔、潮湿",
              "description": "植物香气包裹着细碎晨光。",
              "details": "裂纹玻璃、雾气、白色长桌。",
              "notes": ""
            }
          ]
        }
        """

    monkeypatch.setattr("app.services.scene_service.llm_orchestrator.chat", fake_chat)

    import_response = await client.post(
        f"/api/v1/projects/{project_id}/scenes/import",
        json={
            "llm_config_id": "test-config",
            "text_content": "旧港雨夜码头和庄园玻璃温室的场景描述。",
        },
    )

    assert import_response.status_code == 201
    body = import_response.json()
    assert body["count"] == 2
    assert [scene["name"] for scene in body["data"]] == ["雨夜码头", "玻璃温室"]
    assert captured["config_id"] == "test-config"
    assert captured["messages"][0]["content"] == custom_prompt
    assert captured["temperature"] == 1.1
    assert captured["max_tokens"] == SCENE_IMPORT_MAX_TOKENS
    assert captured["response_format"] == DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT


@pytest.mark.anyio
async def test_scene_import_returns_clear_error_for_invalid_json(
    client, monkeypatch
):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "scene import invalid json"},
    )
    project_id = project_response.json()["id"]

    async def fake_chat(config_id, messages, **kwargs):
        return "这里不是 JSON"

    monkeypatch.setattr("app.services.scene_service.llm_orchestrator.chat", fake_chat)

    import_response = await client.post(
        f"/api/v1/projects/{project_id}/scenes/import",
        json={
            "llm_config_id": "test-config",
            "text_content": "旧港雨夜码头。",
        },
    )

    assert import_response.status_code == 400
    assert "合法 JSON" in import_response.json()["detail"]


@pytest.mark.anyio
async def test_scene_import_returns_clear_error_when_llm_truncates(
    client, monkeypatch
):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "scene import truncated"},
    )
    project_id = project_response.json()["id"]

    async def fake_chat(config_id, messages, **kwargs):
        raise LLMOutputTruncatedError("LLM output stopped early: length")

    monkeypatch.setattr("app.services.scene_service.llm_orchestrator.chat", fake_chat)

    import_response = await client.post(
        f"/api/v1/projects/{project_id}/scenes/import",
        json={
            "llm_config_id": "test-config",
            "text_content": "很多场景描述文本",
        },
    )

    assert import_response.status_code == 400
    assert "模型长度限制" in import_response.json()["detail"]
