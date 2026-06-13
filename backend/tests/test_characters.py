import os
from pathlib import Path

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
from app.services.character_service import CHARACTER_IMPORT_MAX_TOKENS  # noqa: E402


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
async def test_character_move_persists_order(client):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "character order project"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    created = []
    for name in ("林远", "苏婉", "秦烈"):
        response = await client.post(
            f"/api/v1/projects/{project_id}/characters",
            json={"name": name},
        )
        assert response.status_code == 201
        created.append(response.json())

    assert [c["sort_order"] for c in created] == [0, 1, 2]

    move_response = await client.put(
        f"/api/v1/projects/{project_id}/characters/{created[0]['id']}/move",
        json={"new_order": 2},
    )
    assert move_response.status_code == 200
    moved_names = [c["name"] for c in move_response.json()["data"]]
    assert moved_names == ["苏婉", "秦烈", "林远"]

    list_response = await client.get(f"/api/v1/projects/{project_id}/characters")
    assert list_response.status_code == 200
    listed = list_response.json()["data"]
    assert [c["name"] for c in listed] == ["苏婉", "秦烈", "林远"]
    assert [c["sort_order"] for c in listed] == [0, 1, 2]


@pytest.mark.anyio
async def test_character_image_upload_and_delete(client):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "character image project"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    create_response = await client.post(
        f"/api/v1/projects/{project_id}/characters",
        json={"name": "Image Hero"},
    )
    assert create_response.status_code == 201
    character_id = create_response.json()["id"]

    invalid_response = await client.put(
        f"/api/v1/projects/{project_id}/characters/{character_id}/image",
        content=b"not an image",
        headers={"content-type": "text/plain"},
    )
    assert invalid_response.status_code == 400

    upload_response = await client.put(
        f"/api/v1/projects/{project_id}/characters/{character_id}/image",
        content=b"image bytes",
        headers={"content-type": "image/png"},
    )
    assert upload_response.status_code == 200
    avatar_url = upload_response.json()["avatar_url"]
    assert avatar_url.startswith(f"/uploads/characters/{project_id}/")

    image_path = Path("data/uploads") / avatar_url.removeprefix("/uploads/")
    assert image_path.exists()

    delete_response = await client.delete(
        f"/api/v1/projects/{project_id}/characters/{character_id}/image"
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["avatar_url"] is None
    assert not image_path.exists()

    second_upload_response = await client.put(
        f"/api/v1/projects/{project_id}/characters/{character_id}/image",
        content=b"second image bytes",
        headers={"content-type": "image/png"},
    )
    assert second_upload_response.status_code == 200
    second_avatar_url = second_upload_response.json()["avatar_url"]
    second_image_path = (
        Path("data/uploads") / second_avatar_url.removeprefix("/uploads/")
    )
    assert second_image_path.exists()

    character_delete_response = await client.delete(
        f"/api/v1/projects/{project_id}/characters/{character_id}"
    )
    assert character_delete_response.status_code == 204
    assert not second_image_path.exists()


@pytest.mark.anyio
async def test_character_import_uses_system_prompt_setting(client, monkeypatch):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "character import prompt project"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    custom_prompt = "Use this custom character import system prompt."
    update_response = await client.put(
        "/api/v1/system-settings/prompts/character_import.system",
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
          "characters": [
            {
              "name": "Imported Hero",
              "aliases": ["Hero"],
              "basic_info": {"age": "20"},
              "personality": {"traits": ["brave"]},
              "growth_arc": {"starting_state": "unknown"},
              "biography": "Imported biography",
              "notes": "Imported notes"
            }
          ]
        }
        """

    monkeypatch.setattr(
        "app.services.character_service.llm_orchestrator.chat", fake_chat
    )

    import_response = await client.post(
        f"/api/v1/projects/{project_id}/characters/import",
        json={
            "llm_config_id": "test-config",
            "text_content": "A short source text about the hero.",
        },
    )

    assert import_response.status_code == 201
    body = import_response.json()
    assert body["count"] == 1
    assert body["data"][0]["name"] == "Imported Hero"
    assert captured["config_id"] == "test-config"
    assert captured["temperature"] == 1.1
    assert captured["max_tokens"] == CHARACTER_IMPORT_MAX_TOKENS
    assert captured["response_format"] == DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT
    assert captured["messages"][0]["content"] == custom_prompt


@pytest.mark.anyio
async def test_character_import_returns_clear_error_when_llm_truncates(
    client, monkeypatch
):
    project_response = await client.post(
        "/api/v1/projects",
        json={"name": "character import truncated project"},
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    async def fake_chat(config_id, messages, **kwargs):
        raise LLMOutputTruncatedError("LLM output stopped early: length")

    monkeypatch.setattr(
        "app.services.character_service.llm_orchestrator.chat", fake_chat
    )

    import_response = await client.post(
        f"/api/v1/projects/{project_id}/characters/import",
        json={
            "llm_config_id": "test-config",
            "text_content": "很多人物设定文本",
        },
    )

    assert import_response.status_code == 400
    assert "AI 导入输出达到模型长度限制" in import_response.json()["detail"]
