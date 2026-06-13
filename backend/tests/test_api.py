import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.models.base import Base
from app.db.session import get_db


TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_db.db"

test_engine = create_async_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_list_projects_empty():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/projects")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "total" in data
        assert data["total"] == 0


@pytest.mark.anyio
async def test_create_project():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/projects",
            json={"name": "测试小说", "genre": "科幻"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "测试小说"
        assert data["genre"] == "科幻"
        assert data["status"] == "draft"
        assert "id" in data


@pytest.mark.anyio
async def test_get_project():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "获取测试"},
        )
        project_id = create_resp.json()["id"]

        response = await client.get(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "获取测试"


@pytest.mark.anyio
async def test_update_project():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "更新前"},
        )
        project_id = create_resp.json()["id"]

        response = await client.put(
            f"/api/v1/projects/{project_id}",
            json={"name": "更新后"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "更新后"


@pytest.mark.anyio
async def test_delete_project():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "删除测试"},
        )
        project_id = create_resp.json()["id"]

        response = await client.delete(f"/api/v1/projects/{project_id}")
        assert response.status_code == 204

        get_resp = await client.get(f"/api/v1/projects/{project_id}")
        assert get_resp.status_code == 404


@pytest.mark.anyio
async def test_project_not_found():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/projects/00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "PROJECT_NOT_FOUND"


@pytest.mark.anyio
async def test_create_llm_config():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/llm-configs",
            json={
                "provider": "deepseek",
                "api_key": "sk-test-key",
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-pro",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["provider"] == "deepseek"
        assert data["api_key_encrypted"] == "****masked****"
        assert data["is_active"] is True


@pytest.mark.anyio
async def test_deepseek_config_test_uses_lightweight_probe(monkeypatch):
    captured = {}

    class FakeDeepSeekProvider:
        def __init__(self, config):
            captured["config"] = config

        async def chat_completion(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return "OK"

    from app.api.v1 import llm_config as llm_config_api

    monkeypatch.setitem(
        llm_config_api.PROVIDER_MAP,
        "deepseek",
        FakeDeepSeekProvider,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_response = await client.post(
            "/api/v1/llm-configs",
            json={
                "provider": "deepseek",
                "api_key": "sk-test-key",
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-pro",
            },
        )
        config_id = create_response.json()["id"]

        response = await client.post(f"/api/v1/llm-configs/{config_id}/test")

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert captured["kwargs"]["max_tokens"] == 64
    assert captured["kwargs"]["_force_max_thinking"] is False
    assert captured["kwargs"]["thinking"] is None
    assert captured["kwargs"]["reasoning_effort"] is None
    assert captured["messages"][0]["role"] == "system"


@pytest.mark.anyio
async def test_system_prompt_settings_update_and_reset():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        list_response = await client.get("/api/v1/system-settings/prompts")
        assert list_response.status_code == 200
        prompts = list_response.json()["data"]
        assert any(item["key"] == "novel_write.system" for item in prompts)
        write_temperature = next(
            item for item in prompts if item["key"] == "novel_write.temperature"
        )
        assert write_temperature["value_type"] == "number"
        assert write_temperature["default_value"] == "1.3"
        assert write_temperature["min_value"] == 0
        assert write_temperature["max_value"] == 2

        update_response = await client.put(
            "/api/v1/system-settings/prompts/novel_write.system",
            json={"value": "自定义 AI 编写 system prompt"},
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["value"] == "自定义 AI 编写 system prompt"
        assert updated["effective_value"] == "自定义 AI 编写 system prompt"
        assert updated["is_custom"] is True

        reset_response = await client.post(
            "/api/v1/system-settings/prompts/novel_write.system/reset"
        )
        assert reset_response.status_code == 200
        reset = reset_response.json()
        assert reset["is_custom"] is False
        assert reset["effective_value"] == reset["default_value"]

        temp_response = await client.put(
            "/api/v1/system-settings/prompts/novel_write.temperature",
            json={"value": "1.5"},
        )
        assert temp_response.status_code == 200
        temp = temp_response.json()
        assert temp["value"] == "1.5"
        assert temp["effective_value"] == "1.5"
        assert temp["is_custom"] is True

        invalid_temp_response = await client.put(
            "/api/v1/system-settings/prompts/novel_write.temperature",
            json={"value": "2.5"},
        )
        assert invalid_temp_response.status_code == 400


@pytest.mark.anyio
async def test_list_llm_configs():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            "/api/v1/llm-configs",
            json={
                "provider": "deepseek",
                "api_key": "sk-test",
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-pro",
            },
        )
        response = await client.get("/api/v1/llm-configs")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) >= 1


@pytest.mark.anyio
async def test_create_character():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_resp = await client.post(
            "/api/v1/projects",
            json={"name": "人物测试项目"},
        )
        project_id = project_resp.json()["id"]

        response = await client.post(
            "/api/v1/characters",
            json={
                "project_id": project_id,
                "name": "林远",
                "basic_info": {"age": "35", "gender": "男"},
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "林远"


@pytest.mark.anyio
async def test_create_chapter():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_resp = await client.post(
            "/api/v1/projects",
            json={"name": "章节测试项目"},
        )
        project_id = project_resp.json()["id"]

        response = await client.post(
            "/api/v1/chapters",
            json={
                "project_id": project_id,
                "title": "第一章",
                "sort_order": 0,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "第一章"
        assert data["status"] == "draft"


@pytest.mark.anyio
async def test_chapter_version():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_resp = await client.post(
            "/api/v1/projects",
            json={"name": "版本测试项目"},
        )
        project_id = project_resp.json()["id"]

        chapter_resp = await client.post(
            "/api/v1/chapters",
            json={
                "project_id": project_id,
                "title": "版本测试章",
            },
        )
        chapter_id = chapter_resp.json()["id"]

        await client.put(
            f"/api/v1/chapters/{chapter_id}",
            json={"content": "第一版内容", "word_count": 5},
        )

        version_resp = await client.post(
            f"/api/v1/chapters/{chapter_id}/versions",
            json={"change_summary": "初始版本"},
        )
        assert version_resp.status_code == 201
        assert version_resp.json()["version_number"] == 1

        versions_resp = await client.get(
            f"/api/v1/chapters/{chapter_id}/versions"
        )
        assert versions_resp.status_code == 200
        assert len(versions_resp.json()["data"]) >= 1


@pytest.mark.anyio
async def test_create_outline():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_resp = await client.post(
            "/api/v1/projects",
            json={"name": "大纲测试项目"},
        )
        project_id = project_resp.json()["id"]

        response = await client.post(
            "/api/v1/outlines",
            json={
                "project_id": project_id,
                "title": "测试大纲",
            },
        )
        assert response.status_code == 201
        assert response.json()["title"] == "测试大纲"


@pytest.mark.anyio
async def test_export_project():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_resp = await client.post(
            "/api/v1/projects",
            json={"name": "导出测试项目"},
        )
        project_id = project_resp.json()["id"]

        response = await client.post(
            "/api/v1/export",
            json={"project_id": project_id, "format": "txt"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
