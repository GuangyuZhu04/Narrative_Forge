import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.api.v1.novel_agent import _error_message
from app.llm.output_limits import DEEPSEEK_V4_MAX_OUTPUT_TOKENS
from app.models.agent_session import NovelAgentSession
from app.models.base import Base
from app.models.character import CharacterRelationship
from app.db.session import get_db
from app.services.novel_agent_service import NovelAgentOutputError, novel_agent_service


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


def parse_sse_events(response) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


async def execute_agent_session(
    client: AsyncClient,
    project_id: str,
    mode: str,
    session_id: str,
):
    endpoint = (
        "write-execute-stream"
        if mode == "generate"
        else "continue-execute-stream"
    )
    response = await client.post(
        f"/api/v1/projects/{project_id}/novel-agent/{endpoint}",
        json={"session_id": session_id},
    )
    return response, parse_sse_events(response)


def test_agent_error_message_keeps_sanitized_upstream_http_detail():
    request = httpx.Request("POST", "https://api.deepseek.com/responses")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "Invalid schema keyword: maxLength"}},
    )
    error = httpx.HTTPStatusError(
        "Bad Request", request=request, response=response
    )

    assert _error_message(error) == (
        "上游模型 API 返回 HTTP 400：Invalid schema keyword: maxLength"
    )


@pytest.mark.anyio
async def test_guided_chat_session_starts_and_persists_welcome_state():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects", json={"name": "对话创作测试"}
        )
        project_id = project_response.json()["id"]

        response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/chat-turn-stream",
            json={"llm_config_id": "configured-later", "answers": []},
        )

        assert response.status_code == 200
        events = parse_sse_events(response)
        sessions = [item["session"] for item in events if item["type"] == "session"]
        assert sessions[-1]["mode"] == "chat_generate"
        assert sessions[-1]["status"] == "awaiting_input"
        state = sessions[-1]["request_payload"]["chat_state"]
        assert state["stage"] == "intake"
        assert state["messages"][0]["role"] == "assistant"


@pytest.mark.anyio
async def test_chat_session_sync_endpoint_backfills_confirmed_outline():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects", json={"name": "旧会话同步测试"}
        )
        project_id = project_response.json()["id"]
        session_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/sessions",
            json={"mode": "chat_generate", "name": "旧对话"},
        )
        session_id = session_response.json()["id"]

        async with TestSessionLocal() as db:
            session = await db.get(NovelAgentSession, session_id)
            assert session is not None
            session.request_payload = {
                "chat_state": {
                    "schema_version": "novel.agent.chat.v1",
                    "stage": "character_scope",
                    "state_version": 1,
                    "messages": [],
                    "pending_questions": [],
                    "artifacts": {
                        "outline": {
                            "project": {
                                "name": "旧钟",
                                "description": "时间从旧钟里泄漏。",
                                "genre": "奇幻悬疑",
                                "word_count_target": 5000,
                                "settings": {},
                            },
                            "style_guide": "克制、清晰。",
                            "outline": {
                                "title": "旧钟大纲",
                                "description": "旧会话中的已确认大纲。",
                                "children": [],
                            },
                        }
                    },
                    "confirmed": {"outline": True},
                    "selections": {},
                    "scale": {},
                    "quality_policy": {},
                    "execution": {"chapter_results": []},
                    "structure_created": False,
                    "result": None,
                }
            }
            session.status = "awaiting_input"
            await db.commit()

        sync_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/sessions/"
            f"{session_id}/sync-confirmed-artifacts"
        )
        assert sync_response.status_code == 200
        synced_state = sync_response.json()["request_payload"]["chat_state"]
        assert synced_state["materialized_structure"]["outline_id"]

        outlines_response = await client.get(
            f"/api/v1/projects/{project_id}/outlines"
        )
        assert outlines_response.status_code == 200
        outlines = outlines_response.json()["data"]
        assert len(outlines) == 1
        assert outlines[0]["title"] == "旧钟大纲"


@pytest.mark.anyio
async def test_guided_chat_failure_survives_rollback_and_marks_session_failed(
    monkeypatch,
):
    persisted_steps = [
        {
            "step": "outline",
            "label": "分卷级大纲",
            "status": "running",
            "message": "正在生成",
        }
    ]
    persisted_result = {"partial": "已提交的对话创作结果"}

    async def failing_chat_turn(db, project_id, session, data):
        session.steps = persisted_steps
        session.result = persisted_result
        await db.commit()
        yield {"type": "progress", "step": "outline", "message": "正在生成"}
        raise NovelAgentOutputError("Agent 生成未返回蓝图内容")

    monkeypatch.setattr(
        "app.api.v1.novel_agent.novel_agent_chat_service.handle_turn_stream",
        failing_chat_turn,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects", json={"name": "对话创作异常测试"}
        )
        project_id = project_response.json()["id"]
        session_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/sessions",
            json={"mode": "chat_generate", "name": "异常会话"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/chat-turn-stream",
            json={
                "session_id": session_id,
                "llm_config_id": "configured-later",
                "message": "继续生成大纲",
                "answers": [],
            },
        )

        assert response.status_code == 200
        events = parse_sse_events(response)
        assert events[-1] == {
            "type": "error",
            "error": "Agent 生成未返回蓝图内容",
        }

        persisted_session = await client.get(
            f"/api/v1/projects/{project_id}/novel-agent/sessions/{session_id}"
        )
        session_data = persisted_session.json()
        assert session_data["status"] == "failed"
        assert session_data["error_message"] == "Agent 生成未返回蓝图内容"
        assert session_data["steps"] == persisted_steps
        assert session_data["result"] == persisted_result


@pytest.mark.anyio
async def test_guided_chat_failure_yields_error_when_failure_persistence_fails(
    monkeypatch,
):
    async def failing_chat_turn(db, project_id, session, data):
        yield {"type": "progress", "step": "outline", "message": "正在生成"}
        raise NovelAgentOutputError("Agent 生成未返回蓝图内容")

    async def failing_fail_run(*args, **kwargs):
        raise RuntimeError("failed to persist failure state")

    monkeypatch.setattr(
        "app.api.v1.novel_agent.novel_agent_chat_service.handle_turn_stream",
        failing_chat_turn,
    )
    monkeypatch.setattr(
        "app.api.v1.novel_agent.novel_agent_session_service.fail_run",
        failing_fail_run,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects", json={"name": "对话创作失败兜底测试"}
        )
        project_id = project_response.json()["id"]
        session_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/sessions",
            json={"mode": "chat_generate", "name": "失败兜底会话"},
        )
        session_id = session_response.json()["id"]

        response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/chat-turn-stream",
            json={
                "session_id": session_id,
                "llm_config_id": "configured-later",
                "message": "继续生成大纲",
                "answers": [],
            },
        )

        assert response.status_code == 200
        assert parse_sse_events(response)[-1] == {
            "type": "error",
            "error": "Agent 生成未返回蓝图内容",
        }


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
async def test_project_cover_upload_update_and_delete():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "封面测试"},
        )
        project_id = create_resp.json()["id"]

        invalid_response = await client.put(
            f"/api/v1/projects/{project_id}/cover",
            content=b"not an image",
            headers={"content-type": "text/plain"},
        )
        assert invalid_response.status_code == 400

        upload_response = await client.put(
            f"/api/v1/projects/{project_id}/cover",
            content=b"cover bytes",
            headers={"content-type": "image/png"},
        )
        assert upload_response.status_code == 200
        cover_url = upload_response.json()["cover_url"]
        assert cover_url.startswith(f"/uploads/projects/{project_id}/")

        cover_path = Path("data/uploads") / cover_url.removeprefix("/uploads/")
        assert cover_path.exists()

        delete_cover_response = await client.delete(
            f"/api/v1/projects/{project_id}/cover"
        )
        assert delete_cover_response.status_code == 200
        assert delete_cover_response.json()["cover_url"] is None
        assert not cover_path.exists()

        second_upload_response = await client.put(
            f"/api/v1/projects/{project_id}/cover",
            content=b"second cover bytes",
            headers={"content-type": "image/webp"},
        )
        assert second_upload_response.status_code == 200
        second_cover_url = second_upload_response.json()["cover_url"]
        second_cover_path = (
            Path("data/uploads") / second_cover_url.removeprefix("/uploads/")
        )
        assert second_cover_path.exists()

        project_delete_response = await client.delete(f"/api/v1/projects/{project_id}")
        assert project_delete_response.status_code == 204
        assert not second_cover_path.exists()


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
async def test_update_and_delete_llm_config_invalidate_provider_cache(monkeypatch):
    invalidated: list[str] = []
    from app.api.v1 import llm_config as llm_config_api

    monkeypatch.setattr(
        llm_config_api.llm_orchestrator,
        "invalidate",
        invalidated.append,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/llm-configs",
            json={
                "provider": "deepseek",
                "api_key": "sk-test-key",
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-pro",
            },
        )
        config_id = created.json()["id"]

        updated = await client.put(
            f"/api/v1/llm-configs/{config_id}",
            json={"model_name": "deepseek-v4-flash"},
        )
        deleted = await client.delete(f"/api/v1/llm-configs/{config_id}")

    assert updated.status_code == 200
    assert deleted.status_code == 204
    assert invalidated == [config_id, config_id]


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
            f"/api/v1/projects/{project_id}/characters",
            json={
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
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "title": "第一章",
                "sort_order": 0,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "第一章"
        assert data["status"] == "draft"


@pytest.mark.anyio
async def test_novel_agent_writes_project_from_idea(monkeypatch):
    blueprint = {
        "project": {
            "name": "记忆书店",
            "description": "旧书店与记忆改写交织的悬疑长篇。",
            "genre": "悬疑",
            "word_count_target": 120000,
            "settings": {
                "logline": "女孩接手旧书店后发现书能改变记忆。",
                "core_promise": "每本书都是一桩记忆谜案。",
            },
        },
        "style_guide": "冷静克制，线索公平，对白有潜台词。",
        "outline": {
            "title": "记忆书店大纲",
            "description": "围绕旧书店、失踪父亲和被篡改的城市记忆展开。",
            "children": [
                {
                    "node_type": "VOLUME",
                    "title": "第一卷 旧书开门",
                    "summary": "女主进入旧书店，发现第一本异常书。",
                    "metadata": {"goal": "建立规则"},
                    "children": [
                        {
                            "node_type": "CHAPTER",
                            "title": "第一章 旧书店的钥匙",
                            "summary": "女主收到钥匙，进入书店，并发现一本写着自己童年的书。",
                            "metadata": {
                                "pov": "女主",
                                "hook": "书页出现陌生名字",
                            },
                            "children": [],
                        }
                    ],
                }
            ],
        },
        "characters": [
            {
                "name": "林照",
                "aliases": ["小照"],
                "basic_info": {"年龄": "26", "职业": "旧书店继承人"},
                "personality": {
                    "性格特征": "克制敏锐",
                    "欲望": "找出父亲失踪真相",
                    "恐惧": "自己的记忆也不可信",
                    "说话风格": "短句，带试探",
                },
                "growth_arc": {
                    "初始状态": "逃避旧书店",
                    "发展方向": "主动追查真相",
                },
                "biography": "从小离开旧书店，成年后被迫返回。",
                "notes": "她的童年记忆有缺口。",
            }
        ],
        "scenes": [
            {
                "name": "云阶旧书店",
                "location": "老城区巷尾",
                "time": "雨夜",
                "atmosphere": "安静压抑",
                "description": "一间只在雨夜显得明亮的旧书店。",
                "details": "柜台下有铜铃，二楼不能点灯。",
                "notes": "记忆书只会在闭店后出现。",
            }
        ],
        "agent_plan": [{"step": "write_chapters", "goal": "写首章"}],
    }
    calls = []

    async def fake_chat(config_id, messages, **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        if kwargs.get("response_format"):
            return json.dumps(blueprint, ensure_ascii=False)
        return "这是自动写出的第一章正文。"

    monkeypatch.setattr(
        "app.services.novel_agent_service.llm_orchestrator.chat", fake_chat
    )
    monkeypatch.setattr(
        "app.services.chapter_service.llm_orchestrator.chat", fake_chat
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        llm_config_response = await client.post(
            "/api/v1/llm-configs",
            json={
                "provider": "deepseek",
                "api_key": "test-key",
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-pro",
                "default_params": {"max_tokens": 4096},
            },
        )
        llm_config_id = llm_config_response.json()["id"]
        project_resp = await client.post(
            "/api/v1/projects",
            json={"name": "待生成项目"},
        )
        project_id = project_resp.json()["id"]

        stream_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/write-stream",
            json={
                "llm_config_id": llm_config_id,
                "idea": "一个女孩继承旧书店，发现书会改写记忆。",
                "volume_count": 1,
                "chapter_count": 1,
                "write_chapter_count": 1,
                "word_count_target": 120000,
            },
        )

        assert stream_response.status_code == 200
        plan_events = [
            json.loads(line.removeprefix("data: "))
            for line in stream_response.text.splitlines()
            if line.startswith("data: ")
        ]
        session_data = plan_events[0]["session"]
        assert plan_events[0]["type"] == "session"
        assert session_data["mode"] == "generate"
        assert next(event for event in plan_events if event["type"] == "plan")[
            "plan"
        ]["outline"]["title"] == "记忆书店大纲"
        confirmation_event = next(
            event
            for event in plan_events
            if event["type"] == "confirmation_required"
        )
        assert confirmation_event["session"]["status"] == "awaiting_confirmation"
        assert not any(event["type"] == "result" for event in plan_events)
        assert plan_events[-1]["type"] == "done"

        project_before_confirmation = await client.get(
            f"/api/v1/projects/{project_id}"
        )
        outlines_before_confirmation = await client.get(
            f"/api/v1/projects/{project_id}/outlines"
        )
        assert project_before_confirmation.json()["name"] == "待生成项目"
        assert outlines_before_confirmation.json()["data"] == []
        assert len(calls) == 1

        session_response = await client.get(
            f"/api/v1/projects/{project_id}/novel-agent/sessions/{session_data['id']}"
        )
        awaiting_session = session_response.json()
        assert awaiting_session["status"] == "awaiting_confirmation"
        assert awaiting_session["result"] is None

        execute_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/write-execute-stream",
            json={"session_id": session_data["id"]},
        )
        execute_events = [
            json.loads(line.removeprefix("data: "))
            for line in execute_response.text.splitlines()
            if line.startswith("data: ")
        ]
        result_event = next(
            event for event in execute_events if event["type"] == "result"
        )
        data = result_event["result"]
        assert data["project"]["name"] == "记忆书店"
        assert data["outline"]["title"] == "记忆书店大纲"
        assert len(data["characters"]) == 1
        assert data["characters"][0]["name"] == "林照"
        assert len(data["scenes"]) == 1
        assert len(data["chapters"]) == 1
        assert len(data["written_chapters"]) == 1
        assert data["written_chapters"][0]["content"] == "这是自动写出的第一章正文。"
        assert execute_events[-1]["type"] == "done"
        assert calls[0]["kwargs"]["response_format"] == {"type": "json_object"}
        assert calls[0]["kwargs"]["max_tokens"] == DEEPSEEK_V4_MAX_OUTPUT_TOKENS
        assert calls[1]["kwargs"]["max_tokens"] == DEEPSEEK_V4_MAX_OUTPUT_TOKENS

        session_response = await client.get(
            f"/api/v1/projects/{project_id}/novel-agent/sessions/{session_data['id']}"
        )
        persisted_session = session_response.json()
        assert persisted_session["status"] == "completed"
        assert persisted_session["plan"]["outline"]["title"] == "记忆书店大纲"
        assert persisted_session["result"]["outline"]["title"] == "记忆书店大纲"

        duplicate_execute = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/write-execute-stream",
            json={"session_id": session_data["id"]},
        )
        assert duplicate_execute.status_code == 409


def test_novel_agent_chapter_count_is_book_total():
    def volume(chapter_count: int) -> dict:
        return {
            "node_type": "VOLUME",
            "children": [
                {"node_type": "CHAPTER", "children": []}
                for _index in range(chapter_count)
            ],
        }

    valid_blueprint = {
        "outline": {"children": [volume(2), volume(1)]},
    }
    novel_agent_service._ensure_blueprint_scale(valid_blueprint, 2, 3)

    per_volume_blueprint = {
        "outline": {"children": [volume(3), volume(3)]},
    }
    with pytest.raises(NovelAgentOutputError, match="实际为 2 卷、全书共 6 章"):
        novel_agent_service._ensure_blueprint_scale(per_volume_blueprint, 2, 3)


@pytest.mark.anyio
async def test_novel_agent_repairs_blueprint_missing_outline(monkeypatch):
    def volume(title: str, chapter_titles: list[str]) -> dict:
        return {
            "node_type": "VOLUME",
            "title": title,
            "children": [
                {
                    "node_type": "CHAPTER",
                    "title": chapter_title,
                    "children": [],
                }
                for chapter_title in chapter_titles
            ],
        }

    incomplete_blueprint = {
        "project": {
            "name": "死者正在输入",
            "description": "数字人格引发的身份悬疑。",
            "genre": "科幻悬疑",
        },
        "style_guide": "冷峻克制。",
    }
    repaired_blueprint = {
        **incomplete_blueprint,
        "outline": {
            "title": "死者正在输入大纲",
            "description": "林默追查数字母亲与自身身份。",
            "children": [
                volume("第一卷", ["第一章", "第二章", "第三章"]),
                volume("第二卷", ["第四章"]),
                volume("第三卷", ["第五章"]),
            ],
        },
        "characters": [],
        "scenes": [],
        "agent_plan": [],
    }
    outputs = iter([incomplete_blueprint, repaired_blueprint])
    calls = []

    async def fake_chat(config_id, messages, **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        return json.dumps(next(outputs), ensure_ascii=False)

    monkeypatch.setattr(
        "app.services.novel_agent_service.llm_orchestrator.chat", fake_chat
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        llm_config_response = await client.post(
            "/api/v1/llm-configs",
            json={
                "provider": "deepseek",
                "api_key": "test-key",
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-pro",
            },
        )
        llm_config_id = llm_config_response.json()["id"]
        project_response = await client.post(
            "/api/v1/projects",
            json={"name": "Agent 蓝图补全测试"},
        )
        project_id = project_response.json()["id"]

        response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/write-stream",
            json={
                "llm_config_id": llm_config_id,
                "idea": "数字遗产清理师收到已故母亲发来的消息。",
                "chapter_count": 5,
                "write_chapter_count": 0,
                "word_count_target": 100000,
            },
        )

    assert response.status_code == 200
    events = parse_sse_events(response)
    assert not any(event["type"] == "error" for event in events)
    plan = next(event["plan"] for event in events if event["type"] == "plan")
    assert plan["outline"]["title"] == "死者正在输入大纲"
    assert [
        len(volume_node["children"])
        for volume_node in plan["outline"]["children"]
    ] == [3, 1, 1]
    assert len(calls) == 2
    assert calls[1]["kwargs"]["api_mode"] == "responses"
    assert calls[1]["kwargs"]["response_format"] == {"type": "json_object"}
    assert calls[1]["messages"][-2]["role"] == "assistant"
    assert "缺少必要字段：outline" in calls[1]["messages"][-1]["content"]
    assert (
        "全书所有卷合计必须恰好生成 5 个 CHAPTER"
        in calls[1]["messages"][1]["content"]
    )


@pytest.mark.anyio
async def test_novel_agent_v4_pro_can_explicitly_fall_back_to_chat(monkeypatch):
    blueprint = {
        "project": {"name": "回退测试"},
        "outline": {
            "title": "回退测试大纲",
            "description": "",
            "children": [
                {
                    "node_type": "VOLUME",
                    "title": "第一卷",
                    "summary": "",
                    "children": [
                        {
                            "node_type": "CHAPTER",
                            "title": "第一章",
                            "summary": "",
                            "children": [],
                        }
                    ],
                }
            ],
        },
        "characters": [],
        "scenes": [],
        "agent_plan": [],
    }
    calls: list[dict] = []

    async def fake_chat(config_id, messages, **kwargs):
        calls.append(kwargs)
        return json.dumps(blueprint, ensure_ascii=False)

    monkeypatch.setattr(
        "app.services.novel_agent_service.llm_orchestrator.chat", fake_chat
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        llm_config_response = await client.post(
            "/api/v1/llm-configs",
            json={
                "provider": "deepseek",
                "api_key": "test-key",
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-pro",
            },
        )
        project_response = await client.post(
            "/api/v1/projects", json={"name": "Responses 回退测试"}
        )
        response = await client.post(
            f"/api/v1/projects/{project_response.json()['id']}/novel-agent/write-stream",
            json={
                "llm_config_id": llm_config_response.json()["id"],
                "idea": "测试显式 Chat 回退。",
                "volume_count": 1,
                "chapter_count": 1,
                "write_chapter_count": 0,
                "use_deepseek_responses_api": False,
            },
        )

    assert response.status_code == 200
    assert calls[0]["api_mode"] == "chat_completions"


@pytest.mark.anyio
async def test_novel_agent_continue_plan_executes_and_persists_session(monkeypatch):
    plan = {
        "summary": "先生成空章节，再打磨已有章节。",
        "actions": [],
    }
    generated_outputs = iter(["自动生成的新正文。", "按计划打磨后的正文。"])
    calls = []

    async def fake_chat(config_id, messages, **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        if kwargs.get("response_format"):
            return json.dumps(plan, ensure_ascii=False)
        return next(generated_outputs)

    monkeypatch.setattr(
        "app.services.novel_agent_continue_service.llm_orchestrator.chat",
        fake_chat,
    )
    monkeypatch.setattr(
        "app.services.chapter_service.llm_orchestrator.chat",
        fake_chat,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        llm_config_response = await client.post(
            "/api/v1/llm-configs",
            json={
                "provider": "deepseek",
                "api_key": "test-key",
                "base_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-pro",
                "default_params": {"max_tokens": 4096},
            },
        )
        llm_config_id = llm_config_response.json()["id"]
        project_response = await client.post(
            "/api/v1/projects",
            json={"name": "Agent 续写改编测试"},
        )
        project_id = project_response.json()["id"]
        first_response = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={"title": "第一章", "content": "", "sort_order": 0},
        )
        second_response = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={"title": "第二章", "content": "旧正文", "sort_order": 1},
        )
        first_id = first_response.json()["id"]
        second_id = second_response.json()["id"]
        plan["actions"] = [
            {
                "action": "write",
                "chapter_id": first_id,
                "instruction": "生成承接开篇的完整正文",
            },
            {
                "action": "polish",
                "chapter_id": second_id,
                "instruction": "加强人物动机和章末悬念",
                "include_previous_chapter": True,
            },
        ]

        stream_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/continue-stream",
            json={
                "llm_config_id": llm_config_id,
                "instruction": "续写第一章并打磨第二章",
                "style_requirements": "冷峻简洁",
                "max_actions": 5,
            },
        )

        assert stream_response.status_code == 200
        plan_events = parse_sse_events(stream_response)
        assert plan_events[0]["type"] == "session"
        session_id = plan_events[0]["session"]["id"]
        plan_event = next(
            event for event in plan_events if event["type"] == "plan"
        )
        assert len(plan_event["plan"]["actions"]) == 2
        assert next(
            event
            for event in plan_events
            if event["type"] == "confirmation_required"
        )["session"]["status"] == "awaiting_confirmation"
        assert not any(event["type"] == "result" for event in plan_events)
        assert (await client.get(
            f"/api/v1/projects/{project_id}/chapters/{first_id}"
        )).json()["content"] == ""
        assert (await client.get(
            f"/api/v1/projects/{project_id}/chapters/{second_id}"
        )).json()["content"] == "旧正文"

        execute_response, events = await execute_agent_session(
            client, project_id, "continue_edit", session_id
        )
        assert execute_response.status_code == 200
        result_event = next(event for event in events if event["type"] == "result")
        assert result_event["result"]["session_id"] == session_id
        assert len(result_event["result"]["actions"]) == 2
        worker_session_ids = [
            action["worker_session_id"]
            for action in result_event["result"]["actions"]
        ]
        assert len(set(worker_session_ids)) == 2
        assert all(
            call["kwargs"]["max_tokens"] == DEEPSEEK_V4_MAX_OUTPUT_TOKENS
            for call in calls
        )
        assert events[-1]["type"] == "done"

        first_chapter = await client.get(
            f"/api/v1/projects/{project_id}/chapters/{first_id}"
        )
        second_chapter = await client.get(
            f"/api/v1/projects/{project_id}/chapters/{second_id}"
        )
        assert first_chapter.json()["content"] == "自动生成的新正文。"
        assert second_chapter.json()["content"] == "按计划打磨后的正文。"

        session_response = await client.get(
            f"/api/v1/projects/{project_id}/novel-agent/sessions/{session_id}"
        )
        persisted_session = session_response.json()
        assert persisted_session["status"] == "completed"
        assert persisted_session["request_payload"] == {
            "llm_config_id": llm_config_id,
            "instruction": "续写第一章并打磨第二章",
            "style_requirements": "冷峻简洁",
            "max_actions": 5,
        }
        assert persisted_session["plan"] == plan_event["plan"]
        assert persisted_session["result"] == result_event["result"]
        assert len(persisted_session["steps"]) == 3
        assert all(
            step["status"] == "completed"
            for step in persisted_session["steps"]
        )

        rename_response = await client.put(
            f"/api/v1/projects/{project_id}/novel-agent/sessions/{session_id}",
            json={"name": "第二卷续写计划"},
        )
        assert rename_response.status_code == 200
        assert rename_response.json()["name"] == "第二卷续写计划"

        blank_name_response = await client.put(
            f"/api/v1/projects/{project_id}/novel-agent/sessions/{session_id}",
            json={"name": "   "},
        )
        assert blank_name_response.status_code == 422


@pytest.mark.anyio
async def test_novel_agent_continue_repairs_too_short_multi_chapter_plan(
    monkeypatch,
):
    chapter_ids: list[str] = []
    plan_call_count = 0
    generated_outputs = iter(["第一章正文", "第二章正文", "第三章正文"])

    async def fake_chat(config_id, messages, **kwargs):
        nonlocal plan_call_count
        if kwargs.get("response_format"):
            plan_call_count += 1
            planned_ids = chapter_ids[:1] if plan_call_count == 1 else chapter_ids
            return json.dumps(
                {
                    "summary": "连续续写三个章节",
                    "actions": [
                        {
                            "action": "write",
                            "chapter_id": chapter_id,
                            "instruction": f"连续生成第 {index} 个章节",
                        }
                        for index, chapter_id in enumerate(planned_ids, start=1)
                    ],
                },
                ensure_ascii=False,
            )
        return next(generated_outputs)

    monkeypatch.setattr(
        "app.services.novel_agent_continue_service.llm_orchestrator.chat",
        fake_chat,
    )
    monkeypatch.setattr(
        "app.services.chapter_service.llm_orchestrator.chat",
        fake_chat,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects",
            json={"name": "连续多章节续写测试"},
        )
        project_id = project_response.json()["id"]
        for index in range(1, 4):
            chapter_response = await client.post(
                f"/api/v1/projects/{project_id}/chapters",
                json={
                    "title": f"第{index}章",
                    "content": "",
                    "sort_order": index,
                },
            )
            chapter_ids.append(chapter_response.json()["id"])

        stream_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/continue-stream",
            json={
                "llm_config_id": "test-config",
                "instruction": "连续续写接下来的三个空章节",
                "max_actions": 5,
            },
        )
        plan_events = parse_sse_events(stream_response)

        assert plan_call_count == 2
        plan_event = next(
            event for event in plan_events if event["type"] == "plan"
        )
        assert [
            action["chapter_id"] for action in plan_event["plan"]["actions"]
        ] == chapter_ids
        for chapter_id in chapter_ids:
            chapter_before_confirmation = await client.get(
                f"/api/v1/projects/{project_id}/chapters/{chapter_id}"
            )
            assert not chapter_before_confirmation.json()["content"].strip()
        _, events = await execute_agent_session(
            client,
            project_id,
            "continue_edit",
            plan_events[0]["session"]["id"],
        )
        result_event = next(event for event in events if event["type"] == "result")
        assert len(result_event["result"]["actions"]) == 3
        assert events[-1]["type"] == "done"

        chapters = [
            (
                await client.get(
                    f"/api/v1/projects/{project_id}/chapters/{chapter_id}"
                )
            ).json()
            for chapter_id in chapter_ids
        ]
        assert [chapter["content"] for chapter in chapters] == [
            "第一章正文",
            "第二章正文",
            "第三章正文",
        ]


@pytest.mark.anyio
async def test_novel_agent_continue_locates_all_remaining_blank_chapters(
    monkeypatch,
):
    blank_chapter_ids: list[str] = []
    plan_call_count = 0
    generated_outputs = iter(["第二章正文", "第三章正文", "第四章正文"])

    async def fake_chat(config_id, messages, **kwargs):
        nonlocal plan_call_count
        if kwargs.get("response_format"):
            plan_call_count += 1
            return json.dumps(
                {
                    "summary": "模型仍然只选择了一个空白章节",
                    "actions": [
                        {
                            "action": "write",
                            "chapter_id": blank_chapter_ids[0],
                            "instruction": "续写这一章",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        return next(generated_outputs)

    monkeypatch.setattr(
        "app.services.novel_agent_continue_service.llm_orchestrator.chat",
        fake_chat,
    )
    monkeypatch.setattr(
        "app.services.chapter_service.llm_orchestrator.chat",
        fake_chat,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects",
            json={"name": "定位全部剩余空白章节"},
        )
        project_id = project_response.json()["id"]
        written_response = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={"title": "第一章", "content": "已有正文", "sort_order": 1},
        )
        written_chapter_id = written_response.json()["id"]
        for index in range(2, 5):
            chapter_response = await client.post(
                f"/api/v1/projects/{project_id}/chapters",
                json={
                    "title": f"第{index}章",
                    "content": "   " if index == 3 else "",
                    "sort_order": index,
                },
            )
            blank_chapter_ids.append(chapter_response.json()["id"])

        stream_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/continue-stream",
            json={
                "llm_config_id": "test-config",
                "instruction": "批量续写剩余的多个空白章节",
                "max_actions": 10,
            },
        )
        plan_events = parse_sse_events(stream_response)

        assert plan_call_count == 2
        plan_event = next(
            event for event in plan_events if event["type"] == "plan"
        )
        assert [
            action["chapter_id"] for action in plan_event["plan"]["actions"]
        ] == blank_chapter_ids
        assert all(
            action["action"] == "write"
            for action in plan_event["plan"]["actions"]
        )
        _, events = await execute_agent_session(
            client,
            project_id,
            "continue_edit",
            plan_events[0]["session"]["id"],
        )
        result_event = next(event for event in events if event["type"] == "result")
        assert len(result_event["result"]["actions"]) == 3
        assert events[-1]["type"] == "done"

        written_chapter = await client.get(
            f"/api/v1/projects/{project_id}/chapters/{written_chapter_id}"
        )
        assert written_chapter.json()["content"] == "已有正文"


@pytest.mark.anyio
async def test_novel_agent_continue_treats_unmaterialized_outline_nodes_as_blank(
    monkeypatch,
):
    pending_target_ids: list[str] = []
    generated_outputs = iter(["第二章正文", "第三章正文"])

    async def fake_chat(config_id, messages, **kwargs):
        if kwargs.get("response_format"):
            return json.dumps(
                {
                    "summary": "续写大纲中尚未创建的空白章节",
                    "actions": [
                        {
                            "action": "write",
                            "chapter_id": target_id,
                            "instruction": f"按大纲续写第 {index} 个空白章节",
                        }
                        for index, target_id in enumerate(
                            pending_target_ids, start=1
                        )
                    ],
                },
                ensure_ascii=False,
            )
        return next(generated_outputs)

    monkeypatch.setattr(
        "app.services.novel_agent_continue_service.llm_orchestrator.chat",
        fake_chat,
    )
    monkeypatch.setattr(
        "app.services.chapter_service.llm_orchestrator.chat",
        fake_chat,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects",
            json={"name": "大纲空白章节实例化测试"},
        )
        project_id = project_response.json()["id"]
        outline_response = await client.post(
            f"/api/v1/projects/{project_id}/outlines",
            json={"title": "三章大纲"},
        )
        outline_id = outline_response.json()["id"]
        volume_response = await client.post(
            f"/api/v1/projects/{project_id}/outlines/nodes",
            json={
                "outline_id": outline_id,
                "node_type": "VOLUME",
                "title": "第一卷",
                "sort_order": 0,
            },
        )
        volume_id = volume_response.json()["id"]
        node_ids = []
        for index in range(1, 4):
            node_response = await client.post(
                f"/api/v1/projects/{project_id}/outlines/nodes",
                json={
                    "outline_id": outline_id,
                    "parent_id": volume_id,
                    "node_type": "CHAPTER",
                    "title": f"第{index}章",
                    "summary": f"第{index}章大纲摘要",
                    "sort_order": index - 1,
                },
            )
            node_ids.append(node_response.json()["id"])

        first_chapter_response = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "outline_node_id": node_ids[0],
                "title": "第1章",
                "content": "第一章已有正文",
                "sort_order": 0,
            },
        )
        first_chapter_id = first_chapter_response.json()["id"]
        pending_target_ids.extend(
            f"outline-node:{node_id}" for node_id in node_ids[1:]
        )

        plan_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/continue-stream",
            json={
                "llm_config_id": "test-config",
                "instruction": "续写下面所有的空白章节",
                "max_actions": 10,
            },
        )
        plan_events = parse_sse_events(plan_response)
        assert not any(event["type"] == "error" for event in plan_events)
        plan = next(
            event["plan"] for event in plan_events if event["type"] == "plan"
        )
        assert [
            action["chapter_id"] for action in plan["actions"]
        ] == pending_target_ids

        chapters_before_confirmation = await client.get(
            f"/api/v1/projects/{project_id}/chapters"
        )
        assert len(chapters_before_confirmation.json()["data"]) == 1

        second_chapter_response = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "outline_node_id": node_ids[1],
                "title": "第2章",
                "content": "",
                "sort_order": 1,
            },
        )
        second_chapter_id = second_chapter_response.json()["id"]

        _, execute_events = await execute_agent_session(
            client,
            project_id,
            "continue_edit",
            plan_events[0]["session"]["id"],
        )
        result = next(
            event["result"]
            for event in execute_events
            if event["type"] == "result"
        )
        assert len(result["actions"]) == 2
        assert all(
            not action["chapter_id"].startswith("outline-node:")
            for action in result["actions"]
        )

        chapters_after_confirmation = await client.get(
            f"/api/v1/projects/{project_id}/chapters"
        )
        chapters_by_node_id = {
            chapter["outline_node_id"]: chapter
            for chapter in chapters_after_confirmation.json()["data"]
        }
        assert len(chapters_by_node_id) == 3
        assert chapters_by_node_id[node_ids[0]]["id"] == first_chapter_id
        assert chapters_by_node_id[node_ids[0]]["content"] == "第一章已有正文"
        assert chapters_by_node_id[node_ids[1]]["id"] == second_chapter_id
        assert chapters_by_node_id[node_ids[1]]["content"] == "第二章正文"
        assert chapters_by_node_id[node_ids[2]]["content"] == "第三章正文"


@pytest.mark.anyio
async def test_novel_agent_continue_syncs_project_knowledge_into_plan_and_write(
    monkeypatch,
):
    target_chapter_id = ""
    calls = []

    async def fake_chat(config_id, messages, **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        if kwargs.get("response_format"):
            return json.dumps(
                {
                    "summary": "同步项目资料后续写",
                    "actions": [
                        {
                            "action": "write",
                            "chapter_id": target_chapter_id,
                            "instruction": "依据完整设定写出雪港会合",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        return "同步资料生成的正文"

    monkeypatch.setattr(
        "app.services.novel_agent_continue_service.llm_orchestrator.chat",
        fake_chat,
    )
    monkeypatch.setattr(
        "app.services.chapter_service.llm_orchestrator.chat",
        fake_chat,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects",
            json={
                "name": "同步资料测试",
                "description": "追查失落星图的长篇故事",
                "genre": "奇幻",
                "settings": "魔法必须遵守代价守恒",
            },
        )
        project_id = project_response.json()["id"]
        outline_response = await client.post(
            f"/api/v1/projects/{project_id}/outlines",
            json={"title": "星图远征大纲", "description": "雪港篇后进入王都篇"},
        )
        outline_id = outline_response.json()["id"]
        node_response = await client.post(
            f"/api/v1/projects/{project_id}/outlines/nodes",
            json={
                "outline_id": outline_id,
                "node_type": "CHAPTER",
                "title": "第二章 雪港会合",
                "summary": "林远在雪港与苏岚会合并发现星图缺角",
                "sort_order": 2,
            },
        )
        outline_node_id = node_response.json()["id"]
        await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "title": "第一章 旧信",
                "content": "林远收到苏岚从雪港寄来的旧信。",
                "sort_order": 1,
            },
        )
        target_response = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "outline_node_id": outline_node_id,
                "title": "第二章",
                "content": "",
                "sort_order": 2,
            },
        )
        target_chapter_id = target_response.json()["id"]
        first_character = await client.post(
            f"/api/v1/projects/{project_id}/characters",
            json={
                "name": "林远",
                "biography": "谨慎的星图修复师",
                "setting_collection": "这段私密人物设定不得提供给 AI",
            },
        )
        second_character = await client.post(
            f"/api/v1/projects/{project_id}/characters",
            json={"name": "苏岚", "personality": {"特质": "果断"}},
        )
        async with TestSessionLocal() as db:
            db.add(
                CharacterRelationship(
                    project_id=project_id,
                    source_id=first_character.json()["id"],
                    target_id=second_character.json()["id"],
                    relationship_type="ALLY",
                    description="共同寻找完整星图",
                    intensity=5,
                )
            )
            await db.commit()
        await client.post(
            f"/api/v1/projects/{project_id}/scenes",
            json={
                "name": "雪港钟楼",
                "location": "北境雪港",
                "atmosphere": "风雪与钟声交织",
                "description": "星图交易的秘密地点",
            },
        )

        stream_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/continue-stream",
            json={
                "llm_config_id": "test-config",
                "instruction": "续写所有剩余空白章节",
                "max_actions": 10,
            },
        )
        plan_events = parse_sse_events(stream_response)
        assert plan_events[-1]["type"] == "done"
        target_before_confirmation = await client.get(
            f"/api/v1/projects/{project_id}/chapters/{target_chapter_id}"
        )
        assert target_before_confirmation.json()["content"] == ""
        _, execute_events = await execute_agent_session(
            client,
            project_id,
            "continue_edit",
            plan_events[0]["session"]["id"],
        )
        assert execute_events[-1]["type"] == "done"

    planner_call = next(call for call in calls if call["kwargs"].get("response_format"))
    planner_prompt = planner_call["messages"][1]["content"]
    assert "魔法必须遵守代价守恒" in planner_prompt
    assert "星图远征大纲" in planner_prompt
    assert "林远在雪港与苏岚会合并发现星图缺角" in planner_prompt
    assert "谨慎的星图修复师" in planner_prompt
    assert "共同寻找完整星图" in planner_prompt
    assert "雪港钟楼" in planner_prompt
    assert '"written_count": 1' in planner_prompt
    assert '"blank_count": 1' in planner_prompt
    assert f'"chapter_ids": ["{target_chapter_id}"]' in planner_prompt
    assert "这段私密人物设定不得提供给 AI" not in planner_prompt

    writer_call = next(call for call in calls if not call["kwargs"].get("response_format"))
    writer_prompt = writer_call["messages"][1]["content"]
    assert "魔法必须遵守代价守恒" in writer_prompt
    assert "雪港篇后进入王都篇" in writer_prompt
    assert "林远在雪港与苏岚会合并发现星图缺角" in writer_prompt
    assert "谨慎的星图修复师" in writer_prompt
    assert "雪港钟楼" in writer_prompt
    assert "林远收到苏岚从雪港寄来的旧信" in writer_prompt
    assert "依据完整设定写出雪港会合" in writer_prompt
    assert "这段私密人物设定不得提供给 AI" not in writer_prompt


@pytest.mark.anyio
async def test_novel_agent_continue_persists_partial_progress_on_failure(
    monkeypatch,
):
    plan = {
        "summary": "先续写，再打磨。",
        "actions": [
            {"action": "write", "chapter_id": "chapter-1"},
            {"action": "polish", "chapter_id": "chapter-2"},
        ],
    }

    async def fake_plan_stream(db, project_id, data):
        plan_step = {
            "step": "plan_continue",
            "label": "续写改编计划",
            "status": "completed",
            "message": "计划已生成",
            "current": 1,
            "total": 2,
        }
        yield {"type": "steps", "steps": [plan_step]}
        yield {"type": "plan", "plan": plan}

    async def fake_execute_stream(db, project_id, session_id, data, persisted_plan):
        plan_step = {
            "step": "plan_continue",
            "label": "续写改编计划",
            "status": "completed",
            "message": "计划已确认",
            "current": 2,
            "total": 2,
        }
        first_step = {
            "step": "action_1",
            "label": "内容生成 · 第一章",
            "status": "completed",
            "message": "第一章已完成",
            "current": 1,
            "total": 2,
        }
        second_step = {
            "step": "action_2",
            "label": "AI 打磨 · 第二章",
            "status": "failed",
            "message": "第二章执行失败",
            "current": 1,
            "total": 2,
        }
        yield {"type": "steps", "steps": [plan_step, first_step]}
        yield {
            "type": "action_result",
            "result": {
                "index": 1,
                "action": "write",
                "chapter_id": "chapter-1",
                "chapter_title": "第一章",
                "instruction": "续写正文",
                "status": "completed",
                "word_count": 1200,
                "content": "已生成正文",
                "backup_version_id": "version-1",
            },
        }
        yield {"type": "step", "step": second_step}
        raise RuntimeError("second action failed")

    monkeypatch.setattr(
        "app.api.v1.novel_agent.novel_agent_continue_service."
        "plan_continue_stream",
        fake_plan_stream,
    )
    monkeypatch.setattr(
        "app.api.v1.novel_agent.novel_agent_continue_service."
        "execute_continue_plan_stream",
        fake_execute_stream,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_response = await client.post(
            "/api/v1/projects",
            json={"name": "部分进度持久化测试"},
        )
        project_id = project_response.json()["id"]
        stream_response = await client.post(
            f"/api/v1/projects/{project_id}/novel-agent/continue-stream",
            json={
                "llm_config_id": "test-config",
                "instruction": "续写后打磨",
                "style_requirements": "克制",
                "max_actions": 2,
            },
        )
        plan_events = parse_sse_events(stream_response)
        session_id = plan_events[0]["session"]["id"]
        execute_response, events = await execute_agent_session(
            client, project_id, "continue_edit", session_id
        )
        assert execute_response.status_code == 200
        assert events[-1] == {
            "type": "error",
            "error": "Agent 执行失败，请稍后重试。",
        }

        session_response = await client.get(
            f"/api/v1/projects/{project_id}/novel-agent/sessions/{session_id}"
        )
        persisted_session = session_response.json()
        assert persisted_session["status"] == "failed"
        assert persisted_session["request_payload"]["instruction"] == "续写后打磨"
        assert persisted_session["plan"]["summary"] == "先续写，再打磨。"
        assert persisted_session["result"]["summary"] == "先续写，再打磨。"
        assert [
            action["chapter_id"]
            for action in persisted_session["result"]["actions"]
        ] == ["chapter-1"]
        assert persisted_session["steps"][-1]["status"] == "failed"


@pytest.mark.anyio
async def test_novel_polish_can_include_adjacent_chapter_context(monkeypatch):
    captured = {}

    async def fake_chat(config_id, messages, **kwargs):
        captured["config_id"] = config_id
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return "打磨后的当前章节"

    monkeypatch.setattr(
        "app.services.chapter_service.llm_orchestrator.chat", fake_chat
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_resp = await client.post(
            "/api/v1/projects",
            json={"name": "打磨上下文测试项目"},
        )
        project_id = project_resp.json()["id"]

        prev_resp = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "title": "前章",
                "content": "前章正文",
                "sort_order": 0,
            },
        )
        current_resp = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "title": "当前章",
                "content": "当前原文",
                "sort_order": 1,
            },
        )
        next_resp = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "title": "后章",
                "content": "后章正文",
                "sort_order": 2,
            },
        )

        await client.put(
            f"/api/v1/projects/{project_id}/chapters/{prev_resp.json()['id']}",
            json={"summary": "前章摘要"},
        )
        await client.put(
            f"/api/v1/projects/{project_id}/chapters/{next_resp.json()['id']}",
            json={"summary": "后章摘要"},
        )

        response = await client.post(
            f"/api/v1/projects/{project_id}/chapters/{current_resp.json()['id']}/novel-polish",
            json={
                "llm_config_id": "test-config",
                "chapter_content": "当前草稿",
                "polish_suggestions": "保持衔接",
                "include_previous_chapter": True,
                "include_next_chapter": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["content"] == "打磨后的当前章节"
    user_prompt = captured["messages"][1]["content"]
    assert "【打磨参考上下文】" in user_prompt
    assert "【前一章节】" in user_prompt
    assert "标题：前章" in user_prompt
    assert "章节摘要：前章摘要" in user_prompt
    assert "前章正文" in user_prompt
    assert "【后一章节】" in user_prompt
    assert "标题：后章" in user_prompt
    assert "章节摘要：后章摘要" in user_prompt
    assert "后章正文" in user_prompt
    assert "【需要打磨的当前章节正文】" in user_prompt
    assert "当前草稿" in user_prompt


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
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "title": "版本测试章",
            },
        )
        chapter_id = chapter_resp.json()["id"]

        await client.put(
            f"/api/v1/projects/{project_id}/chapters/{chapter_id}",
            json={"content": "第一版内容", "word_count": 5},
        )

        version_resp = await client.post(
            f"/api/v1/projects/{project_id}/chapters/{chapter_id}/versions",
            json={"change_summary": "初始版本"},
        )
        assert version_resp.status_code == 201
        assert version_resp.json()["version_number"] == 1

        versions_resp = await client.get(
            f"/api/v1/projects/{project_id}/chapters/{chapter_id}/versions"
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
            f"/api/v1/projects/{project_id}/outlines",
            json={
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
            f"/api/v1/projects/{project_id}/export",
            json={"format": "txt"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"


@pytest.mark.anyio
async def test_export_to_platform():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        project_resp = await client.post(
            "/api/v1/projects",
            json={"name": "平台导出测试项目", "description": "项目简介"},
        )
        project_id = project_resp.json()["id"]

        await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "title": "第一章 风起",
                "content": "第一章正文内容。\n第二段。",
                "sort_order": 0,
            },
        )
        await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "title": "第二章 云涌",
                "content": "第二章正文内容。",
                "sort_order": 1,
            },
        )

        response = await client.post(
            f"/api/v1/projects/{project_id}/export/platform",
            json={"platform": "fanqie"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["platform"] == "fanqie"
        assert data["platform_name"] == "番茄小说"
        assert data["target_url"].startswith("https://fanqienovel.com")
        assert data["chapter_count"] == 2
        assert data["total_word_count"] > 0
        assert data["chapters"][0]["title"] == "第一章 风起"
        assert "《平台导出测试项目》" in data["clipboard_text"]
        assert "第二章正文内容。" in data["clipboard_text"]

        qidian_response = await client.post(
            f"/api/v1/projects/{project_id}/export/platform",
            json={"platform": "qidian"},
        )
        assert qidian_response.status_code == 200
        assert "write.qq.com" in qidian_response.json()["target_url"]
