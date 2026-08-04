import base64
import io
import json
import os
import zipfile
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from websockets.exceptions import ConnectionClosedOK
from websockets.frames import Close

os.environ["DEBUG"] = "false"

from app.db.session import get_db  # noqa: E402
from app.api.v1.audiobook import job_response  # noqa: E402
from app.main import app, ensure_runtime_schema  # noqa: E402
from app.models.audiobook import AudiobookConfig, AudiobookJob  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.chapter import Chapter  # noqa: E402
from app.models.character import Character  # noqa: E402
from app.models.llm_config import LLMConfig  # noqa: E402
from app.models.outline import Outline, OutlineNode  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.services.audiobook_service import (  # noqa: E402
    AudiobookValidationError,
    audiobook_service,
)
from app.tts import (  # noqa: E402
    AudioResult,
    CustomHTTPTTSProvider,
    CustomWebSocketTTSProvider,
    MiniMaxAsyncTTSProvider,
)
from app.tts.providers import (  # noqa: E402
    TTSProviderError,
    _RequestRateLimiter,
    _shared_websocket_rate_limiter,
)


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(audiobook_service, "start_job", lambda _job_id: None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client

    app.dependency_overrides.pop(get_db, None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def create_project(client: AsyncClient) -> str:
    response = await client.post("/api/v1/projects", json={"name": "有声测试小说"})
    assert response.status_code == 201
    return response.json()["id"]


async def create_llm_config(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/llm-configs",
        json={
            "provider": "openai_compatible",
            "api_key": "llm-secret",
            "base_url": "http://llm.local/v1",
            "model_name": "audiobook-script-model",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.anyio
async def test_audiobook_config_masks_key_and_supports_local_service(client: AsyncClient):
    project_id = await create_project(client)
    default_response = await client.get(f"/api/v1/projects/{project_id}/audiobook/config")
    assert default_response.status_code == 200
    assert default_response.json()["id"] is None
    assert default_response.json()["use_ffmpeg"] is True
    assert default_response.json()["requests_per_minute"] == 20

    save_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:8000/v1/",
            "api_key": "secret-key",
            "model_name": "local-tts",
            "narrator_voice": "narrator",
            "character_voices": {},
            "speed": 1,
            "max_chars_per_segment": 500,
            "request_timeout_seconds": 60,
        },
    )
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["base_url"] == "http://127.0.0.1:8000/v1"
    assert saved["api_key_configured"] is True
    assert "api_key" not in saved
    assert "api_key_encrypted" not in saved


@pytest.mark.anyio
async def test_minimax_async_config_accepts_official_direct_text_limit(client: AsyncClient):
    project_id = await create_project(client)
    payload = {
        "provider": "minimax_async",
        "base_url": "https://api.minimaxi.com/v1",
        "api_key": "voice-secret",
        "model_name": "speech-2.8-hd",
        "narrator_voice": "male-qn-qingse",
        "character_voices": {},
        "speed": 1,
        "max_chars_per_segment": 50_000,
        "request_timeout_seconds": 1800,
    }

    save_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config", json=payload
    )
    assert save_response.status_code == 200
    assert save_response.json()["max_chars_per_segment"] == 50_000

    too_long_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={**payload, "max_chars_per_segment": 50_001},
    )
    assert too_long_response.status_code == 422


@pytest.mark.anyio
async def test_character_voices_can_be_saved_independently(client: AsyncClient):
    project_id = await create_project(client)

    initial_response = await client.patch(
        f"/api/v1/projects/{project_id}/audiobook/config/character-voices",
        json={
            "character_voices": {
                "character-zhang": " voice-zhang ",
                "character-empty": "   ",
            }
        },
    )
    assert initial_response.status_code == 200
    assert initial_response.json()["id"] is not None
    assert initial_response.json()["character_voices"] == {
        "character-zhang": "voice-zhang"
    }

    config_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={
            "provider": "openai_compatible",
            "base_url": "http://tts.example/v1",
            "model_name": "novel-tts",
            "narrator_voice": "narrator-special",
            "character_voices": initial_response.json()["character_voices"],
            "speed": 1.25,
        },
    )
    assert config_response.status_code == 200

    saved_response = await client.patch(
        f"/api/v1/projects/{project_id}/audiobook/config/character-voices",
        json={"character_voices": {"character-li": "voice-li"}},
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    assert saved["character_voices"] == {"character-li": "voice-li"}
    assert saved["base_url"] == "http://tts.example/v1"
    assert saved["model_name"] == "novel-tts"
    assert saved["narrator_voice"] == "narrator-special"
    assert saved["speed"] == 1.25

    loaded_response = await client.get(
        f"/api/v1/projects/{project_id}/audiobook/config"
    )
    assert loaded_response.json()["character_voices"] == {
        "character-li": "voice-li"
    }


@pytest.mark.anyio
async def test_runtime_schema_adds_managed_voice_cache_to_existing_database():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE characters ("
                "id TEXT, biography TEXT, setting_collection TEXT, sort_order INTEGER)"
            )
        )
        await conn.execute(text("CREATE TABLE projects (id TEXT, cover_url TEXT)"))
        await conn.execute(
            text(
                "CREATE TABLE audiobook_configs ("
                "id TEXT, custom_request JSON, use_ffmpeg BOOLEAN)"
            )
        )
        await conn.execute(
            text("CREATE TABLE audiobook_jobs (id TEXT, segment_tasks JSON)")
        )
        await ensure_runtime_schema(conn)
        result = await conn.execute(text("PRAGMA table_info(audiobook_configs)"))
        columns = {row[1] for row in result.fetchall()}
        assert "managed_voices" in columns
        assert "deleted_voice_ids" in columns
        assert "requests_per_minute" in columns
        job_result = await conn.execute(text("PRAGMA table_info(audiobook_jobs)"))
        job_columns = {row[1] for row in job_result.fetchall()}
        assert "script_llm_config_id" in job_columns
        assert "speech_scripts" in job_columns
    await engine.dispose()


@pytest.mark.anyio
async def test_volume_scope_and_job_creation(client: AsyncClient):
    project_id = await create_project(client)
    llm_config_id = await create_llm_config(client)
    config_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:8000/v1",
            "model_name": "local-tts",
            "narrator_voice": "narrator",
        },
    )
    assert config_response.status_code == 200

    outline = (
        await client.post(
            f"/api/v1/projects/{project_id}/outlines",
            json={"title": "主大纲"},
        )
    ).json()
    volume = (
        await client.post(
            f"/api/v1/projects/{project_id}/outlines/nodes",
            json={
                "outline_id": outline["id"],
                "node_type": "VOLUME",
                "title": "第一卷",
            },
        )
    ).json()
    chapter_node = (
        await client.post(
            f"/api/v1/projects/{project_id}/outlines/nodes",
            json={
                "outline_id": outline["id"],
                "parent_id": volume["id"],
                "node_type": "CHAPTER",
                "title": "启程",
            },
        )
    ).json()
    chapter = (
        await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "outline_node_id": chapter_node["id"],
                "title": "数据库中的旧标题",
                "content": "<p>张三说：“出发吧！”</p>",
            },
        )
    ).json()

    scopes_response = await client.get(f"/api/v1/projects/{project_id}/audiobook/scopes")
    assert scopes_response.status_code == 200
    scopes = scopes_response.json()
    assert scopes["book_chapter_count"] == 1
    assert scopes["volumes"][0]["id"] == volume["id"]
    assert scopes["volumes"][0]["chapter_count"] == 1
    assert scopes["chapters"][0]["title"] == "启程"

    job_response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/jobs",
        json={
            "scope_type": "volume",
            "scope_id": volume["id"],
            "llm_config_id": llm_config_id,
        },
    )
    assert job_response.status_code == 202
    job = job_response.json()
    assert job["scope_title"] == "第一卷"
    assert job["status"] == "queued"
    assert job["total_chapters"] == 1
    assert job["script_llm_config_id"] == llm_config_id

    chapter_job = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/jobs",
        json={
            "scope_type": "chapter",
            "scope_id": chapter["id"],
            "llm_config_id": llm_config_id,
        },
    )
    assert chapter_job.status_code == 202
    assert chapter_job.json()["scope_title"] == "启程"


@pytest.mark.anyio
async def test_scopes_follow_novel_content_tree_and_ignore_deleted_chapters(
    client: AsyncClient,
):
    project_id = await create_project(client)
    outline = (
        await client.post(
            f"/api/v1/projects/{project_id}/outlines",
            json={"title": "主大纲"},
        )
    ).json()

    async def create_node(
        node_type: str,
        title: str,
        *,
        parent_id: str | None = None,
        sort_order: int,
    ) -> dict:
        response = await client.post(
            f"/api/v1/projects/{project_id}/outlines/nodes",
            json={
                "outline_id": outline["id"],
                "parent_id": parent_id,
                "node_type": node_type,
                "title": title,
                "sort_order": sort_order,
            },
        )
        assert response.status_code == 201
        return response.json()

    first_volume = await create_node("VOLUME", "第一卷", sort_order=0)
    second_volume = await create_node("VOLUME", "第二卷", sort_order=1)
    first_node = await create_node(
        "CHAPTER", "第一章：启程", parent_id=first_volume["id"], sort_order=0
    )
    deleted_node = await create_node(
        "CHAPTER", "已删除章节", parent_id=first_volume["id"], sort_order=1
    )
    second_node = await create_node(
        "CHAPTER", "第二章：追踪", parent_id=first_volume["id"], sort_order=2
    )
    third_node = await create_node(
        "CHAPTER", "第三章：重逢", parent_id=second_volume["id"], sort_order=0
    )

    async def create_chapter(node: dict | None, title: str, sort_order: int) -> dict:
        response = await client.post(
            f"/api/v1/projects/{project_id}/chapters",
            json={
                "outline_node_id": node["id"] if node else None,
                "title": title,
                "content": f"<p>{title}正文</p>",
                "sort_order": sort_order,
            },
        )
        assert response.status_code == 201
        return response.json()

    first_chapter = await create_chapter(first_node, "旧标题一", 20)
    deleted_chapter = await create_chapter(deleted_node, "数据库中的已删除章节", -1)
    second_chapter = await create_chapter(second_node, "旧标题二", 10)
    third_chapter = await create_chapter(third_node, "旧标题三", 0)
    orphan_chapter = await create_chapter(None, "无大纲节点的旧章节", -2)

    delete_response = await client.delete(
        f"/api/v1/projects/{project_id}/outlines/nodes/{deleted_node['id']}"
    )
    assert delete_response.status_code == 204

    chapters_response = await client.get(f"/api/v1/projects/{project_id}/chapters")
    persisted_ids = {item["id"] for item in chapters_response.json()["data"]}
    assert deleted_chapter["id"] in persisted_ids
    assert orphan_chapter["id"] in persisted_ids

    scopes_response = await client.get(
        f"/api/v1/projects/{project_id}/audiobook/scopes"
    )
    assert scopes_response.status_code == 200
    scopes = scopes_response.json()
    assert scopes["book_chapter_count"] == 3
    assert [item["id"] for item in scopes["volumes"]] == [
        first_volume["id"],
        second_volume["id"],
    ]
    assert [item["chapter_count"] for item in scopes["volumes"]] == [2, 1]
    assert [item["id"] for item in scopes["chapters"]] == [
        first_chapter["id"],
        second_chapter["id"],
        third_chapter["id"],
    ]
    assert [item["title"] for item in scopes["chapters"]] == [
        "第一章：启程",
        "第二章：追踪",
        "第三章：重逢",
    ]


@pytest.mark.anyio
async def test_ai_parses_docs_and_custom_config_can_be_saved(client: AsyncClient, monkeypatch):
    project_id = await create_project(client)
    llm_response = await client.post(
        "/api/v1/llm-configs",
        json={
            "provider": "openai_compatible",
            "api_key": "llm-secret",
            "base_url": "http://llm.local/v1",
            "model_name": "doc-parser",
        },
    )
    assert llm_response.status_code == 201
    llm_config_id = llm_response.json()["id"]

    async def fake_parse(_llm_config_id: str, _documentation: str):
        return {
            "provider": "custom_http",
            "base_url": "https://voice.example/v1/speech",
            "model_name": "voice-model",
            "narrator_voice": "female-1",
            "speed": 1.0,
            "max_chars_per_segment": 600,
            "request_timeout_seconds": 120,
            "custom_request": {
                "method": "POST",
                "headers": {"X-API-Key": "{{api_key}}"},
                "query": {},
                "body_type": "json",
                "body": {"content": "{{text}}", "voice": "{{voice}}"},
                "response": {"type": "base64", "path": "data.audio"},
            },
            "warnings": ["请确认音色名称"],
        }

    monkeypatch.setattr(audiobook_service, "parse_api_documentation", fake_parse)
    parse_response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/config/parse-docs",
        json={
            "llm_config_id": llm_config_id,
            "api_documentation": "POST https://voice.example/v1/speech，返回 Base64 MP3 音频。",
        },
    )
    assert parse_response.status_code == 200
    suggestion = parse_response.json()
    assert suggestion["provider"] == "custom_http"
    assert suggestion["custom_request"]["body"]["content"] == "{{text}}"

    save_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={
            **{key: value for key, value in suggestion.items() if key != "warnings"},
            "api_key": "voice-secret",
            "character_voices": {},
        },
    )
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["provider"] == "custom_http"
    assert saved["api_key_configured"] is True
    assert "voice-secret" not in str(saved)


@pytest.mark.anyio
async def test_websocket_config_can_be_saved(client: AsyncClient):
    project_id = await create_project(client)
    payload = {
        "provider": "custom_websocket",
        "base_url": "wss://api.minimaxi.com/ws/v1/t2a_v2",
        "api_key": "voice-secret",
        "model_name": "speech-2.8-hd",
        "narrator_voice": "male-qn-qingse",
        "requests_per_minute": 12,
        "custom_request": {
            **audiobook_service._default_websocket_request(),
            "requests_per_minute": 7,
        },
    }
    save_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json=payload,
    )
    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["provider"] == "custom_websocket"
    assert saved["api_key_configured"] is True
    assert saved["requests_per_minute"] == 12
    assert "requests_per_minute" not in saved["custom_request"]
    assert saved["custom_request"]["continue_message"]["text"] == "{{text}}"

    invalid_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={**payload, "requests_per_minute": 0},
    )
    assert invalid_response.status_code == 422


@pytest.mark.anyio
async def test_minimax_async_config_can_be_saved(client: AsyncClient):
    project_id = await create_project(client)
    response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={
            "provider": "minimax_async",
            "base_url": "https://api.minimaxi.com/v1/t2a_async_v2",
            "api_key": "voice-secret",
            "model_name": "speech-2.8-hd",
            "narrator_voice": "male-qn-qingse",
            "character_voices": {},
            "speed": 1,
            "max_chars_per_segment": 800,
            "request_timeout_seconds": 180,
            "use_ffmpeg": False,
        },
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["provider"] == "minimax_async"
    assert saved["api_key_configured"] is True
    assert saved["use_ffmpeg"] is False


@pytest.mark.anyio
async def test_minimax_voice_query_and_design_follow_documented_contract(
    client: AsyncClient, monkeypatch
):
    project_id = await create_project(client)
    save_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={
            "provider": "custom_websocket",
            "base_url": "wss://api.minimaxi.com/ws/v1/t2a_v2",
            "api_key": "voice-secret",
            "model_name": "speech-2.8-hd",
            "narrator_voice": "male-qn-qingse",
            "custom_request": audiobook_service._default_websocket_request(),
        },
    )
    assert save_response.status_code == 200

    requests: list[Request] = []

    def handler(request: Request) -> Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer voice-secret"
        assert request.headers["Content-Type"].startswith("application/json")
        body = json.loads(request.content)
        if request.url.path == "/v1/get_voice":
            assert body in ({"voice_type": "all"}, {"voice_type": "voice_generation"})
            return Response(
                200,
                json={
                    "system_voice": [
                        {
                            "voice_id": "Chinese_Mandarin_News_Anchor",
                            "voice_name": "新闻女声",
                            "description": ["专业新闻主播"],
                            "created_time": "1970-01-01",
                        }
                    ],
                    "voice_cloning": [
                        {
                            "voice_id": "clone-1",
                            "description": [],
                            "created_time": "2025-08-20",
                        }
                    ],
                    "voice_generation": [
                        {
                            "voice_id": "ttv-generated-1",
                            "description": ["低沉男声"],
                            "created_time": "2025-08-21",
                        }
                    ],
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                },
            )
        if request.url.path == "/v1/voice_design":
            assert body == {
                "prompt": "低沉而富有磁性的悬疑男声",
                "preview_text": "夜幕降临，故事才刚刚开始。",
                "voice_id": "detective-narrator",
                "aigc_watermark": False,
            }
            return Response(
                200,
                json={
                    "voice_id": "detective-narrator",
                    "trial_audio": b"\xff\xfbtrial-mp3".hex(),
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                },
            )
        assert request.url.path == "/v1/delete_voice"
        assert body == {
            "voice_type": "voice_generation",
            "voice_id": "detective-narrator",
        }
        return Response(
            200,
            json={
                "voice_id": "detective-narrator",
                "created_time": "2026-07-16",
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
        )

    transport = MockTransport(handler)

    def client_factory(*args, **kwargs):
        return AsyncClient(*args, transport=transport, **kwargs)

    monkeypatch.setattr(
        "app.services.audiobook_service.httpx.AsyncClient", client_factory
    )

    query_response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/voices/query",
        json={"voice_type": "all"},
    )
    assert query_response.status_code == 200
    voices = query_response.json()["voices"]
    assert [voice["voice_type"] for voice in voices] == [
        "system",
        "voice_cloning",
        "voice_generation",
    ]
    assert voices[0]["voice_name"] == "新闻女声"

    design_response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/voices/design",
        json={
            "prompt": "低沉而富有磁性的悬疑男声",
            "preview_text": "夜幕降临，故事才刚刚开始。",
            "voice_id": "detective-narrator",
            "aigc_watermark": False,
        },
    )
    assert design_response.status_code == 200
    designed = design_response.json()
    assert designed["voice"]["voice_id"] == "detective-narrator"
    assert designed["voice"]["is_local_only"] is True
    assert base64.b64decode(designed["trial_audio_base64"]) == b"\xff\xfbtrial-mp3"

    refreshed_response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/voices/query",
        json={"voice_type": "voice_generation"},
    )
    assert refreshed_response.status_code == 200
    refreshed_voices = refreshed_response.json()["voices"]
    persisted_voice = next(
        voice for voice in refreshed_voices if voice["voice_id"] == "detective-narrator"
    )
    assert persisted_voice["is_local_only"] is True
    assert persisted_voice["description"] == ["低沉而富有磁性的悬疑男声"]

    delete_response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/voices/delete",
        json={
            "voice_type": "voice_generation",
            "voice_id": "detective-narrator",
        },
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "voice_id": "detective-narrator",
        "voice_type": "voice_generation",
        "created_time": "2026-07-16",
    }

    recreate_response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/voices/design",
        json={
            "prompt": "尝试复用已删除音色",
            "preview_text": "这次请求不应发送到 MiniMax。",
            "voice_id": "detective-narrator",
            "aigc_watermark": False,
        },
    )
    assert recreate_response.status_code == 400
    assert "平台不允许再次使用" in recreate_response.json()["detail"]
    assert "留空让 MiniMax 自动生成" in recreate_response.json()["detail"]

    after_delete_response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/voices/query",
        json={"voice_type": "voice_generation"},
    )
    assert after_delete_response.status_code == 200
    assert "detective-narrator" not in {
        voice["voice_id"] for voice in after_delete_response.json()["voices"]
    }
    assert [request.url.path for request in requests] == [
        "/v1/get_voice",
        "/v1/voice_design",
        "/v1/get_voice",
        "/v1/delete_voice",
        "/v1/get_voice",
    ]
    assert [
        json.loads(request.content)["voice_type"]
        for request in requests
        if request.url.path == "/v1/get_voice"
    ] == ["all", "voice_generation", "voice_generation"]
    assert all(request.url.host == "api.minimaxi.com" for request in requests)


@pytest.mark.anyio
async def test_minimax_duplicate_voice_id_returns_actionable_error(
    client: AsyncClient, monkeypatch
):
    project_id = await create_project(client)
    save_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={
            "provider": "minimax_async",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key": "voice-secret",
            "model_name": "speech-2.8-hd",
            "narrator_voice": "male-qn-qingse",
        },
    )
    assert save_response.status_code == 200

    def handler(request: Request) -> Response:
        assert request.url.path == "/v1/voice_design"
        return Response(
            200,
            json={
                "base_resp": {
                    "status_code": 2013,
                    "status_msg": "voice clone voice id duplicate",
                }
            },
        )

    transport = MockTransport(handler)

    def client_factory(*args, **kwargs):
        return AsyncClient(*args, transport=transport, **kwargs)

    monkeypatch.setattr(
        "app.services.audiobook_service.httpx.AsyncClient", client_factory
    )
    response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/voices/design",
        json={
            "prompt": "沉稳男声",
            "preview_text": "测试试听。",
            "voice_id": "already-used",
            "aigc_watermark": False,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "voice_id already-used 已被 MiniMax 占用，删除后也不能复用。"
        "请填写新的 voice_id，或留空让 MiniMax 自动生成。"
    )


@pytest.mark.anyio
async def test_minimax_voice_management_requires_minimax_config(client: AsyncClient):
    project_id = await create_project(client)
    save_response = await client.put(
        f"/api/v1/projects/{project_id}/audiobook/config",
        json={
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "not-minimax",
            "model_name": "tts-1",
            "narrator_voice": "alloy",
        },
    )
    assert save_response.status_code == 200
    response = await client.post(
        f"/api/v1/projects/{project_id}/audiobook/voices/query",
        json={"voice_type": "all"},
    )
    assert response.status_code == 400
    assert "仅支持 MiniMax" in response.json()["detail"]


def test_api_suggestion_sanitizes_documented_secret_and_custom_templates():
    suggestion = audiobook_service.normalize_api_suggestion(
        {
            "provider": "custom_http",
            "base_url": "https://voice.example/speech",
            "model_name": "tts",
            "narrator_voice": "voice-a",
            "custom_request": {
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer sk-example-secret",
                    "X-API-Key": "example-key",
                },
                "body": {"text": "{{text}}"},
                "response": {"type": "url", "path": "data.0.url"},
            },
        }
    )
    headers = suggestion["custom_request"]["headers"]
    assert headers["Authorization"] == "Bearer {{api_key}}"
    assert headers["X-API-Key"] == "{{api_key}}"
    assert (
        CustomHTTPTTSProvider._get_path(
            {"data": [{"url": "https://example/audio.mp3"}]}, "data.0.url"
        )
        == "https://example/audio.mp3"
    )
    redacted = audiobook_service.redact_document_secrets(
        '"Authorization": "Bearer sk-live-example12345"\n"api_key": "voice-secret-12345"'
    )
    assert "sk-live-example12345" not in redacted
    assert "voice-secret-12345" not in redacted


def test_websocket_api_suggestion_is_normalized_and_sanitized():
    suggestion = audiobook_service.normalize_api_suggestion(
        {
            "provider": "custom_http",
            "base_url": "wss://api.minimaxi.com/ws/v1/t2a_v2",
            "model_name": "speech-2.8-hd",
            "narrator_voice": "male-qn-qingse",
            "custom_request": {
                "headers": {"Authorization": "Bearer sk-example-secret"},
                "requests_per_minute": 7,
                "start_message": {
                    "event": "task_start",
                    "model": "{{model}}",
                    "voice_setting": {
                        "voice_id": "{{voice}}",
                        "speed": "{{speed}}",
                    },
                    "audio_setting": {"format": "mp3"},
                },
                "continue_message": {"event": "task_continue", "text": "{{text}}"},
                "response": {
                    "audio_path": "data.audio",
                    "audio_encoding": "hex",
                    "final_path": "is_final",
                    "final_value": True,
                },
            },
            "warnings": ["当前适配器仅支持 HTTP，无法直接使用 WebSocket"],
        }
    )
    assert suggestion["provider"] == "custom_websocket"
    assert suggestion["requests_per_minute"] == 7
    assert "requests_per_minute" not in suggestion["custom_request"]
    assert suggestion["custom_request"]["headers"]["Authorization"] == (
        "Bearer {{api_key}}"
    )
    assert suggestion["custom_request"]["finish_message"] == {"event": "task_finish"}
    assert all("当前适配器仅支持 HTTP" not in warning for warning in suggestion["warnings"])
    assert any("finish_message" in warning for warning in suggestion["warnings"])


def test_websocket_api_suggestion_replaces_old_http_fallback():
    suggestion = audiobook_service.normalize_api_suggestion(
        {
            "provider": "custom_http",
            "base_url": "wss://api.minimaxi.com/ws/v1/t2a_v2",
            "model_name": "speech-2.8-hd",
            "narrator_voice": "male-qn-qingse",
            "custom_request": None,
            "warnings": [
                "该 API 使用 WebSocket 协议，当前适配器仅支持 HTTP，无法直接使用"
            ],
        }
    )
    assert suggestion["provider"] == "custom_websocket"
    assert suggestion["custom_request"]["start_message"]["event"] == "task_start"
    assert suggestion["custom_request"]["response"]["audio_encoding"] == "hex"
    assert all("当前适配器仅支持 HTTP" not in warning for warning in suggestion["warnings"])


def test_minimax_async_api_suggestion_strips_create_endpoint():
    suggestion = audiobook_service.normalize_api_suggestion(
        {
            "provider": "custom_http",
            "base_url": "https://api.minimaxi.com/v1/t2a_async_v2",
            "model_name": "speech-2.8-hd",
            "narrator_voice": "male-qn-qingse",
            "custom_request": {"body": {"text": "{{text}}"}},
        }
    )
    assert suggestion["provider"] == "minimax_async"
    assert suggestion["base_url"] == "https://api.minimaxi.com/v1"
    assert suggestion["max_chars_per_segment"] == 50_000
    assert suggestion["custom_request"] is None


def test_build_websocket_provider_uses_saved_connection_limit():
    config = SimpleNamespace(
        provider="custom_websocket",
        base_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key_encrypted=None,
        model_name="speech-2.8-hd",
        custom_request=audiobook_service._default_websocket_request(),
        request_timeout_seconds=30,
        requests_per_minute=12,
    )

    provider = audiobook_service.build_provider(config)

    assert isinstance(provider, CustomWebSocketTTSProvider)
    assert provider.requests_per_minute == 12


@pytest.mark.anyio
async def test_custom_websocket_provider_collects_hex_mp3_chunks(monkeypatch):
    responses = [
        {"event": "connected_success", "base_resp": {"status_code": 0}},
        {"event": "task_started", "base_resp": {"status_code": 0}},
        {
            "data": {"audio": b"\xff\xfbfirst".hex()},
            "is_final": False,
            "base_resp": {"status_code": 0},
        },
        {
            "data": {"audio": b"second".hex()},
            "is_final": True,
            "base_resp": {"status_code": 0},
        },
    ]

    class FakeWebSocket:
        def __init__(self):
            self.sent = []

        async def recv(self):
            if len(responses) == 2:
                assert self.sent[-1] == {
                    "event": "task_continue",
                    "text": "测试文本",
                }
            return json.dumps(responses.pop(0))

        async def send(self, message):
            self.sent.append(json.loads(message))

    websocket = FakeWebSocket()
    captured = {}

    class FakeConnection:
        async def __aenter__(self):
            return websocket

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def fake_connect(endpoint, **kwargs):
        captured["endpoint"] = endpoint
        captured["kwargs"] = kwargs
        return FakeConnection()

    monkeypatch.setattr("app.tts.providers.websockets.connect", fake_connect)
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=audiobook_service._default_websocket_request(),
    )
    assert provider.requests_per_minute == 20
    provider.requests_per_minute = 0
    result = await provider.synthesize("测试文本", "male-qn-qingse", 1.25, "preview")

    assert result.content == b"\xff\xfbfirstsecond"
    assert captured["endpoint"] == "wss://api.minimaxi.com/ws/v1/t2a_v2"
    assert captured["kwargs"]["additional_headers"] == {
        "Authorization": "Bearer voice-secret"
    }
    assert websocket.sent[0]["event"] == "task_start"
    assert websocket.sent[0]["voice_setting"]["voice_id"] == "male-qn-qingse"
    assert websocket.sent[0]["voice_setting"]["speed"] == 1.25
    assert websocket.sent[1] == {"event": "task_continue", "text": "测试文本"}
    assert len(websocket.sent) == 2

    await provider.aclose()

    assert websocket.sent[2] == {"event": "task_finish"}


@pytest.mark.anyio
async def test_custom_websocket_provider_reuses_session_for_same_voice(monkeypatch):
    responses = [
        {"event": "connected_success", "base_resp": {"status_code": 0}},
        {"event": "task_started", "base_resp": {"status_code": 0}},
        {
            "data": {"audio": b"\xff\xfbfirst".hex()},
            "is_final": True,
            "base_resp": {"status_code": 0},
        },
        {
            "data": {"audio": b"\xff\xfbsecond".hex()},
            "is_final": True,
            "base_resp": {"status_code": 0},
        },
    ]
    connect_count = 0

    class FakeWebSocket:
        def __init__(self):
            self.sent = []

        async def recv(self):
            return json.dumps(responses.pop(0))

        async def send(self, message):
            self.sent.append(json.loads(message))

    websocket = FakeWebSocket()

    class FakeConnection:
        async def __aenter__(self):
            return websocket

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def fake_connect(_endpoint, **_kwargs):
        nonlocal connect_count
        connect_count += 1
        return FakeConnection()

    monkeypatch.setattr("app.tts.providers.websockets.connect", fake_connect)
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=audiobook_service._default_websocket_request(),
    )
    provider.requests_per_minute = 0

    first = await provider.synthesize("第一段", "same-voice", 1, "first")
    second = await provider.synthesize("第二段", "same-voice", 1, "second")
    await provider.aclose()

    assert first.content == b"\xff\xfbfirst"
    assert second.content == b"\xff\xfbsecond"
    assert connect_count == 1
    assert [message["event"] for message in websocket.sent] == [
        "task_start",
        "task_continue",
        "task_continue",
        "task_finish",
    ]
    assert websocket.sent[1]["text"] == "第一段"
    assert websocket.sent[2]["text"] == "第二段"


@pytest.mark.anyio
async def test_custom_websocket_provider_uses_separate_sessions_for_voices(monkeypatch):
    websockets_created = []

    class FakeWebSocket:
        def __init__(self):
            self.sent = []
            self.responses = [
                {"event": "connected_success", "base_resp": {"status_code": 0}},
                {"event": "task_started", "base_resp": {"status_code": 0}},
                {
                    "data": {"audio": b"\xff\xfbaudio".hex()},
                    "is_final": True,
                    "base_resp": {"status_code": 0},
                },
            ]

        async def recv(self):
            return json.dumps(self.responses.pop(0))

        async def send(self, message):
            self.sent.append(json.loads(message))

    class FakeConnection:
        def __init__(self, websocket):
            self.websocket = websocket

        async def __aenter__(self):
            return self.websocket

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def fake_connect(_endpoint, **_kwargs):
        websocket = FakeWebSocket()
        websockets_created.append(websocket)
        return FakeConnection(websocket)

    monkeypatch.setattr("app.tts.providers.websockets.connect", fake_connect)
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=audiobook_service._default_websocket_request(),
    )
    provider.requests_per_minute = 0

    await provider.synthesize("甲", "voice-a", 1, "a")
    await provider.synthesize("乙", "voice-b", 1, "b")
    await provider.aclose()

    assert len(websockets_created) == 2
    assert [ws.sent[0]["voice_setting"]["voice_id"] for ws in websockets_created] == [
        "voice-a",
        "voice-b",
    ]
    assert all(ws.sent[-1] == {"event": "task_finish"} for ws in websockets_created)


@pytest.mark.anyio
async def test_custom_websocket_provider_retries_rpm_error_after_cooldown(monkeypatch):
    connections = []
    sleeps = []

    class FakeWebSocket:
        def __init__(self, responses):
            self.responses = responses
            self.sent = []

        async def recv(self):
            return json.dumps(self.responses.pop(0))

        async def send(self, message):
            self.sent.append(json.loads(message))

    class FakeConnection:
        def __init__(self, websocket):
            self.websocket = websocket

        async def __aenter__(self):
            return self.websocket

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def fake_connect(_endpoint, **_kwargs):
        if not connections:
            responses = [
                {"event": "connected_success", "base_resp": {"status_code": 0}},
                {
                    "event": "task_failed",
                    "base_resp": {
                        "status_code": 1002,
                        "status_msg": "rate limit exceeded(RPM)",
                    },
                },
            ]
        else:
            responses = [
                {"event": "connected_success", "base_resp": {"status_code": 0}},
                {"event": "task_started", "base_resp": {"status_code": 0}},
                {
                    "data": {"audio": b"\xff\xfbretried".hex()},
                    "is_final": True,
                    "base_resp": {"status_code": 0},
                },
            ]
        websocket = FakeWebSocket(responses)
        connections.append(websocket)
        return FakeConnection(websocket)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("app.tts.providers.websockets.connect", fake_connect)
    monkeypatch.setattr("app.tts.providers.asyncio.sleep", fake_sleep)
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=audiobook_service._default_websocket_request(),
    )
    provider.requests_per_minute = 0

    result = await provider.synthesize("测试文本", "voice-a", 1, "preview")
    await provider.aclose()

    assert result.content == b"\xff\xfbretried"
    assert len(connections) == 2
    assert sleeps == [60.0]


@pytest.mark.anyio
async def test_custom_websocket_provider_reconnects_stale_reused_session(monkeypatch):
    connections = []

    class FakeWebSocket:
        def __init__(self, fail_second_continue):
            self.fail_second_continue = fail_second_continue
            self.continue_count = 0
            self.sent = []
            self.responses = [
                {"event": "connected_success", "base_resp": {"status_code": 0}},
                {"event": "task_started", "base_resp": {"status_code": 0}},
                {
                    "data": {"audio": b"\xff\xfbaudio".hex()},
                    "is_final": True,
                    "base_resp": {"status_code": 0},
                },
            ]

        async def recv(self):
            return json.dumps(self.responses.pop(0))

        async def send(self, message):
            payload = json.loads(message)
            if payload["event"] == "task_continue":
                self.continue_count += 1
                if self.fail_second_continue and self.continue_count == 2:
                    close = Close(1000, "idle timeout")
                    raise ConnectionClosedOK(close, close, True)
            self.sent.append(payload)

    class FakeConnection:
        def __init__(self, websocket):
            self.websocket = websocket

        async def __aenter__(self):
            return self.websocket

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def fake_connect(_endpoint, **_kwargs):
        websocket = FakeWebSocket(fail_second_continue=not connections)
        connections.append(websocket)
        return FakeConnection(websocket)

    monkeypatch.setattr("app.tts.providers.websockets.connect", fake_connect)
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=audiobook_service._default_websocket_request(),
    )
    provider.requests_per_minute = 0

    first = await provider.synthesize("第一段", "same-voice", 1, "first")
    second = await provider.synthesize("第二段", "same-voice", 1, "second")
    await provider.aclose()

    assert first.content == b"\xff\xfbaudio"
    assert second.content == b"\xff\xfbaudio"
    assert len(connections) == 2


@pytest.mark.anyio
async def test_websocket_rate_limiter_spaces_requests_and_is_shared_by_credential():
    now = 100.0
    delays = []

    def clock():
        return now

    async def sleep(seconds):
        nonlocal now
        delays.append(seconds)
        now += seconds

    limiter = _RequestRateLimiter(30, clock=clock, sleep=sleep)
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()

    assert delays == [2.0, 2.0]
    shared_a = _shared_websocket_rate_limiter(
        "wss://rate-limit-test.example/ws",
        "same-key",
        30,
    )
    shared_b = _shared_websocket_rate_limiter(
        "wss://rate-limit-test.example/ws",
        "same-key",
        30,
    )
    other_credential = _shared_websocket_rate_limiter(
        "wss://rate-limit-test.example/ws",
        "other-key",
        30,
    )
    assert shared_a is shared_b
    assert shared_a is not other_credential


@pytest.mark.anyio
async def test_custom_websocket_provider_accepts_clean_close_after_audio(monkeypatch):
    responses = [
        {"event": "connected_success", "base_resp": {"status_code": 0}},
        {"event": "task_started", "base_resp": {"status_code": 0}},
        {
            "data": {"audio": b"\xff\xfbaudio".hex()},
            "is_final": False,
            "base_resp": {"status_code": 0},
        },
    ]

    class FakeWebSocket:
        async def recv(self):
            if responses:
                return json.dumps(responses.pop(0))
            close = Close(1000, "OK")
            raise ConnectionClosedOK(close, close, True)

        async def send(self, _message):
            pass

    class FakeConnection:
        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(
        "app.tts.providers.websockets.connect", lambda _endpoint, **_kwargs: FakeConnection()
    )
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=audiobook_service._default_websocket_request(),
    )
    provider.requests_per_minute = 0

    result = await provider.synthesize("测试文本", "male-qn-qingse", 1, "preview")

    assert result.content == b"\xff\xfbaudio"


@pytest.mark.anyio
async def test_custom_websocket_provider_retries_clean_close_without_audio(monkeypatch):
    attempts = 0
    sleeps = []

    class FakeWebSocket:
        def __init__(self, include_audio):
            self.responses = [
                {"event": "connected_success", "base_resp": {"status_code": 0}},
                {"event": "task_started", "base_resp": {"status_code": 0}},
            ]
            if include_audio:
                self.responses.extend(
                    [
                        {
                            "event": "task_continued",
                            "data": {"audio": b"\xff\xfbretried".hex()},
                            "base_resp": {"status_code": 0},
                        },
                        {
                            "event": "task_finished",
                            "base_resp": {"status_code": 0},
                        },
                    ]
                )

        async def recv(self):
            if self.responses:
                return json.dumps(self.responses.pop(0))
            close = Close(1000, "OK")
            raise ConnectionClosedOK(close, close, True)

        async def send(self, _message):
            pass

    class FakeConnection:
        def __init__(self, websocket):
            self.websocket = websocket

        async def __aenter__(self):
            return self.websocket

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def fake_connect(_endpoint, **_kwargs):
        nonlocal attempts
        attempts += 1
        return FakeConnection(FakeWebSocket(include_audio=attempts == 2))

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("app.tts.providers.websockets.connect", fake_connect)
    monkeypatch.setattr("app.tts.providers.asyncio.sleep", fake_sleep)
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=audiobook_service._default_websocket_request(),
    )
    provider.EMPTY_AUDIO_MAX_ATTEMPTS = 2
    provider.requests_per_minute = 0

    result = await provider.synthesize("测试文本", "male-qn-qingse", 1, "preview")

    assert result.content == b"\xff\xfbretried"
    assert attempts == 2
    assert sleeps == [2.0]


@pytest.mark.anyio
async def test_custom_websocket_provider_rejects_repeated_empty_audio(monkeypatch):
    attempts = 0

    class FakeWebSocket:
        def __init__(self):
            self.responses = [
                {"event": "connected_success", "base_resp": {"status_code": 0}},
                {"event": "task_started", "base_resp": {"status_code": 0}},
            ]

        async def recv(self):
            if self.responses:
                return json.dumps(self.responses.pop(0))
            close = Close(1000, "OK")
            raise ConnectionClosedOK(close, close, True)

        async def send(self, _message):
            pass

    class FakeConnection:
        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    def fake_connect(_endpoint, **_kwargs):
        nonlocal attempts
        attempts += 1
        return FakeConnection()

    async def fake_sleep(_seconds):
        pass

    monkeypatch.setattr("app.tts.providers.websockets.connect", fake_connect)
    monkeypatch.setattr("app.tts.providers.asyncio.sleep", fake_sleep)
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=audiobook_service._default_websocket_request(),
    )
    provider.EMPTY_AUDIO_MAX_ATTEMPTS = 2
    provider.requests_per_minute = 0

    with pytest.raises(TTSProviderError, match="连续 2 次返回了空音频"):
        await provider.synthesize("测试文本", "male-qn-qingse", 1, "preview")
    assert attempts == 2


@pytest.mark.anyio
async def test_custom_websocket_provider_reports_minimax_task_failure_without_mapping(
    monkeypatch,
):
    responses = [
        {"event": "connected_success", "base_resp": {"status_code": 0}},
        {"event": "task_started", "base_resp": {"status_code": 0}},
        {
            "event": "task_failed",
            "base_resp": {"status_code": 1008, "status_msg": "请求过于频繁"},
        },
    ]

    class FakeWebSocket:
        async def recv(self):
            return json.dumps(responses.pop(0))

        async def send(self, _message):
            pass

    class FakeConnection:
        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(
        "app.tts.providers.websockets.connect",
        lambda _endpoint, **_kwargs: FakeConnection(),
    )
    request_config = audiobook_service._default_websocket_request()
    request_config["response"] = {
        "audio_path": "data.audio",
        "audio_encoding": "hex",
        "final_path": "is_final",
        "final_value": True,
    }
    provider = CustomWebSocketTTSProvider(
        endpoint_url="wss://api.minimaxi.com/ws/v1/t2a_v2",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        request_config=request_config,
    )
    provider.requests_per_minute = 0

    with pytest.raises(TTSProviderError, match="请求过于频繁"):
        await provider.synthesize("测试文本", "male-qn-qingse", 1, "preview")


@pytest.mark.anyio
async def test_minimax_async_provider_creates_polls_and_downloads_wav_zip(monkeypatch):
    wav_bytes = b"RIFF\x00\x00\x00\x00WAVEfmt "
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("result/subtitle.json", "{}")
        archive.writestr("result/audio.wav", wav_bytes)
    calls: list[str] = []
    query_count = 0

    def handler(request: Request) -> Response:
        nonlocal query_count
        calls.append(request.url.path)
        if request.url.path == "/v1/t2a_async_v2":
            body = json.loads(request.content)
            assert body["voice_setting"] == {
                "voice_id": "voice-a",
                "speed": 1.1,
                "vol": 1.0,
                "pitch": 0,
            }
            assert body["audio_setting"]["audio_sample_rate"] == 32000
            assert body["audio_setting"]["format"] == "wav"
            return Response(200, json={"task_id": "task-1", "base_resp": {"status_code": 0}})
        if request.url.path == "/v1/query/t2a_async_query_v2":
            query_count += 1
            if query_count == 1:
                return Response(
                    200,
                    json={"status": "Processing", "base_resp": {"status_code": 0}},
                )
            return Response(
                200,
                json={
                    "status": "Success",
                    "file_id": 42,
                    "base_resp": {"status_code": 0},
                },
            )
        if request.url.path == "/v1/files/retrieve":
            return Response(
                200,
                json={
                    "file": {
                        "filename": "task-1.zip",
                        "download_url": "https://download.example/task-1.zip",
                    },
                    "base_resp": {"status_code": 0},
                },
            )
        if request.url.path == "/task-1.zip":
            return Response(200, content=archive_buffer.getvalue())
        raise AssertionError(f"unexpected request: {request.url}")

    http_client = AsyncClient(transport=MockTransport(handler))
    monkeypatch.setattr(
        "app.tts.providers.httpx.AsyncClient", lambda **_kwargs: http_client
    )
    statuses = []

    async def capture_status(status, metadata):
        statuses.append((status, metadata))

    provider = MiniMaxAsyncTTSProvider(
        base_url="https://api.minimaxi.com/v1",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        poll_interval_seconds=0,
    )
    result = await provider.synthesize(
        "你终于来了。",
        "voice-a",
        1.1,
        "segment-1",
        task_status_callback=capture_status,
    )

    assert result.content == wav_bytes
    assert result.extension == ".wav"
    assert result.task_id == "task-1"
    assert result.file_id == "42"
    assert [status for status, _ in statuses] == ["processing", "downloading"]
    assert calls == [
        "/v1/t2a_async_v2",
        "/v1/query/t2a_async_query_v2",
        "/v1/query/t2a_async_query_v2",
        "/v1/files/retrieve",
        "/task-1.zip",
    ]


@pytest.mark.anyio
async def test_minimax_async_provider_can_request_mp3_without_ffmpeg():
    captured = {}

    def handler(request: Request) -> Response:
        captured.update(json.loads(request.content))
        return Response(
            200,
            json={"task_id": "task-mp3", "base_resp": {"status_code": 0}},
        )

    provider = MiniMaxAsyncTTSProvider(
        base_url="https://api.minimaxi.com/v1",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        output_format="mp3",
    )
    async with AsyncClient(transport=MockTransport(handler)) as client:
        task_id = await provider._create_task(
            client,
            {"Authorization": "Bearer voice-secret"},
            "直接输出 MP3。",
            "voice-a",
            1.0,
        )

    assert task_id == "task-mp3"
    assert captured["audio_setting"]["format"] == "mp3"


@pytest.mark.anyio
async def test_minimax_async_provider_rejects_text_above_direct_limit():
    def handler(_request: Request) -> Response:
        raise AssertionError("超长文本不应发送到 MiniMax")

    provider = MiniMaxAsyncTTSProvider(
        base_url="https://api.minimaxi.com/v1",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
    )
    async with AsyncClient(transport=MockTransport(handler)) as client:
        with pytest.raises(TTSProviderError, match="5 万字符"):
            await provider._create_task(
                client,
                {"Authorization": "Bearer voice-secret"},
                "文" * 50_001,
                "voice-a",
                1.0,
            )


@pytest.mark.anyio
async def test_parse_docs_calls_existing_llm_with_redacted_document(monkeypatch):
    captured = {}

    async def fake_chat(config_id, messages, **kwargs):
        captured["config_id"] = config_id
        captured["messages"] = messages
        return """{
          "provider": "openai_compatible",
          "base_url": "https://voice.example/v1/audio/speech",
          "model_name": "tts-model",
          "narrator_voice": "alloy",
          "warnings": []
        }"""

    monkeypatch.setattr("app.services.audiobook_service.llm_orchestrator.chat", fake_chat)
    result = await audiobook_service.parse_api_documentation(
        "existing-llm-id",
        'POST /audio/speech，"api_key": "voice-secret-12345"',
    )
    assert captured["config_id"] == "existing-llm-id"
    assert "voice-secret-12345" not in captured["messages"][1]["content"]
    assert result["provider"] == "openai_compatible"
    assert result["base_url"] == "https://voice.example/v1"


@pytest.mark.anyio
async def test_llm_generates_validated_speech_script_json_before_tts(monkeypatch):
    captured = {}
    character = SimpleNamespace(id="zhang", name="张三", aliases=["老张"])
    chapter = SimpleNamespace(
        title="风停之后",
        content="风停了。张三说：“我们走吧。”",
    )

    async def fake_chat(config_id, messages, **kwargs):
        captured["config_id"] = config_id
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return json.dumps(
            {
                "segments": [
                    {"speaker_id": None, "text": "风停了。张三说："},
                    {"speaker_id": "zhang", "text": "我们走吧。"},
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.services.audiobook_service.llm_orchestrator.chat", fake_chat)
    segments = await audiobook_service.generate_speech_script(
        llm_config_id="script-llm",
        chapter=chapter,
        characters=[character],
        max_chars=800,
    )

    assert captured["config_id"] == "script-llm"
    assert '"id":"zhang"' in captured["messages"][1]["content"]
    assert "风停之后" in captured["messages"][1]["content"]
    assert captured["kwargs"]["max_tokens"] == 16 * 1024
    assert captured["kwargs"]["response_format"] == {"type": "json_object"}
    assert [(segment.speaker_id, segment.text) for segment in segments] == [
        (None, "风停了。张三说："),
        ("zhang", "我们走吧。"),
    ]


def test_deepseek_speech_script_uses_official_384k_output_limit():
    deepseek_config = SimpleNamespace(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        default_params={"max_tokens": 4096},
    )
    assert audiobook_service.speech_script_max_tokens(deepseek_config) == 384 * 1024

    compatible_config = SimpleNamespace(
        provider="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        default_params={"max_tokens": 4096},
    )
    assert audiobook_service.speech_script_max_tokens(compatible_config) == 384 * 1024


def test_llm_speech_script_uses_narrator_for_unknown_character_and_rejects_large_omission():
    character = SimpleNamespace(id="zhang", name="张三", aliases=[])
    segments = audiobook_service.normalize_speech_script_segments(
        {"segments": [{"speaker_id": "unknown", "text": "你好。"}]},
        [character],
        "张三说你好。",
        validate_coverage=True,
    )
    assert segments[0].speaker_id is None
    assert audiobook_service.build_chunks(
        segments,
        {"unknown": "stale-character-voice"},
        "narrator",
        100,
    ) == [("你好。", "narrator")]

    with pytest.raises(AudiobookValidationError, match="大幅删减"):
        audiobook_service.normalize_speech_script_segments(
            {"segments": [{"speaker_id": None, "text": "太短。"}]},
            [character],
            "这是一个必须完整保留的很长章节正文。" * 20,
            validate_coverage=True,
        )


def test_dialogue_speaker_detection_and_chunk_voice_mapping():
    characters = [
        SimpleNamespace(id="zhang", name="张三", aliases=["老张", "张老板", "三爷"]),
        SimpleNamespace(id="li", name="李四", aliases=[]),
    ]
    segments = audiobook_service.split_dialogue(
        (
            "<p>张三说：“你好！”</p>"
            "<p>老张问：“准备好了吗？”</p>"
            "<p>“出发吧。”张老板说道。</p>"
            "<p>三爷喊：“跟上！”</p>"
            "<p>风吹过走廊。“走吧。”李四说道。</p>"
        ),
        characters,
    )
    spoken = [(segment.text, segment.speaker_id) for segment in segments]
    assert ("你好！", "zhang") in spoken
    assert ("准备好了吗？", "zhang") in spoken
    assert ("出发吧。", "zhang") in spoken
    assert ("跟上！", "zhang") in spoken
    assert ("走吧。", "li") in spoken

    chunks = audiobook_service.build_chunks(
        [
            segment
            for segment in segments
            if segment.text in {"你好！", "准备好了吗？", "出发吧。", "跟上！"}
        ],
        {"zhang": "voice-a"},
        "narrator",
        100,
    )
    assert chunks == [("你好！ 准备好了吗？ 出发吧。 跟上！", "voice-a")]


def test_dialogue_speaker_detection_prefers_longer_overlapping_name():
    characters = [
        SimpleNamespace(id="short", name="张", aliases=[]),
        SimpleNamespace(id="zhang", name="张三", aliases=["老张"]),
    ]
    segments = audiobook_service.split_dialogue("张三说：“是我。”", characters)
    assert any(
        segment.text == "是我。" and segment.speaker_id == "zhang" for segment in segments
    )


def test_segment_pauses_distinguish_chunk_and_voice_switches():
    assert audiobook_service.segment_pauses(
        [
            ("同音色长段一", "voice-a"),
            ("同音色长段二", "voice-a"),
            ("换人", "voice-b"),
        ]
    ) == [200, 400, 800]


@pytest.mark.anyio
async def test_minimax_segment_tasks_are_persisted_and_cached(tmp_path):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        project = Project(name="片段缓存测试")
        db.add(project)
        await db.flush()
        config = AudiobookConfig(
            project_id=project.id,
            provider="minimax_async",
            base_url="https://api.minimaxi.com/v1",
            model_name="speech-2.8-hd",
            narrator_voice="narrator",
        )
        chapter = Chapter(
            project_id=project.id,
            title="第一章",
            content="测试",
            sort_order=0,
        )
        db.add_all([config, chapter])
        await db.flush()
        job = AudiobookJob(
            project_id=project.id,
            config_id=config.id,
            scope_type="chapter",
            scope_id=chapter.id,
            scope_title="第一章",
            chapter_ids=[chapter.id],
            total_chapters=1,
            segment_tasks=[],
            output_files=[],
        )
        db.add(job)
        await db.commit()

        provider = MiniMaxAsyncTTSProvider(
            base_url="https://api.minimaxi.com/v1",
            api_key="voice-secret",
            model_name="speech-2.8-hd",
            timeout_seconds=30,
            poll_interval_seconds=0,
        )
        synthesize_calls = []

        async def fake_synthesize(text, voice, speed, filename_prefix, **kwargs):
            index = len(synthesize_calls)
            synthesize_calls.append((text, voice))
            callback = kwargs["task_status_callback"]
            await callback(
                "processing", {"task_id": f"task-{index}", "file_id": None}
            )
            await callback(
                "downloading",
                {"task_id": f"task-{index}", "file_id": f"file-{index}"},
            )
            return AudioResult(
                content=b"RIFF\x00\x00\x00\x00WAVE",
                extension=".wav",
                content_type="audio/wav",
                task_id=f"task-{index}",
                file_id=f"file-{index}",
            )

        provider.synthesize = fake_synthesize
        chunks = [("旁白", "narrator"), ("对白", "voice-a")]
        paths = await audiobook_service._generate_minimax_segments(
            db=db,
            job=job,
            provider=provider,
            config=config,
            chapter=chapter,
            chapter_index=0,
            chapter_count=1,
            chunks=chunks,
            output_dir=tmp_path,
        )
        assert len(paths) == 2
        assert all(path.is_file() for path in paths)
        assert [item["status"] for item in job.segment_tasks] == [
            "completed",
            "completed",
        ]
        assert {item["file_id"] for item in job.segment_tasks} == {"file-0", "file-1"}

        async def should_not_synthesize(*_args, **_kwargs):
            raise AssertionError("cached segment should not call MiniMax again")

        provider.synthesize = should_not_synthesize
        cached_paths = await audiobook_service._generate_minimax_segments(
            db=db,
            job=job,
            provider=provider,
            config=config,
            chapter=chapter,
            chapter_index=0,
            chapter_count=1,
            chunks=chunks,
            output_dir=tmp_path,
        )
        assert cached_paths == paths

    await engine.dispose()


@pytest.mark.anyio
async def test_minimax_job_without_ffmpeg_uses_ordered_mp3_concatenation(
    monkeypatch, tmp_path
):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        project = Project(name="无 FFmpeg 拼接测试")
        db.add(project)
        await db.flush()
        character = Character(project_id=project.id, name="张三", aliases=[])
        llm_config = LLMConfig(
            provider="openai_compatible",
            api_key_encrypted="configured",
            base_url="http://llm.local/v1",
            model_name="script-model",
            default_params={},
            is_active=True,
        )
        db.add_all([character, llm_config])
        await db.flush()
        config = AudiobookConfig(
            project_id=project.id,
            provider="minimax_async",
            base_url="https://api.minimaxi.com/v1",
            api_key_encrypted="configured",
            model_name="speech-2.8-hd",
            narrator_voice="narrator",
            character_voices={character.id: "voice-zhang"},
            use_ffmpeg=False,
        )
        chapter = Chapter(
            project_id=project.id,
            title="第一章",
            content="张三说：“你好。”风停了。",
            sort_order=0,
        )
        db.add_all([config, chapter])
        await db.flush()
        character_id = character.id
        job = AudiobookJob(
            project_id=project.id,
            config_id=config.id,
            script_llm_config_id=llm_config.id,
            scope_type="chapter",
            scope_id=chapter.id,
            scope_title="第一章",
            chapter_ids=[chapter.id],
            total_chapters=1,
            speech_scripts={},
            segment_tasks=[],
            output_files=[],
        )
        db.add(job)
        await db.commit()
        job_id = job.id
        project_id = project.id
        script_llm_config_id = llm_config.id

    provider = MiniMaxAsyncTTSProvider(
        base_url="https://api.minimaxi.com/v1",
        api_key="voice-secret",
        model_name="speech-2.8-hd",
        timeout_seconds=30,
        output_format="mp3",
    )
    calls = []
    pipeline_events = []

    async def fake_chat(config_id, messages, **kwargs):
        assert config_id == script_llm_config_id
        assert "张三" in messages[1]["content"]
        pipeline_events.append("llm")
        return json.dumps(
            {
                "segments": [
                    {"speaker_id": None, "text": "张三说："},
                    {"speaker_id": character_id, "text": "你好。"},
                    {"speaker_id": None, "text": "风停了。"},
                ]
            },
            ensure_ascii=False,
        )

    async def fake_synthesize(text, voice, speed, filename_prefix, **kwargs):
        pipeline_events.append("tts")
        calls.append((text, voice, filename_prefix))
        callback = kwargs["task_status_callback"]
        await callback(
            "processing", {"task_id": filename_prefix, "file_id": None}
        )
        await callback(
            "downloading",
            {"task_id": filename_prefix, "file_id": f"file-{filename_prefix}"},
        )
        return AudioResult(
            content=b"\xff\xfb" + filename_prefix.encode(),
            extension=".mp3",
            content_type="audio/mpeg",
            task_id=filename_prefix,
            file_id=f"file-{filename_prefix}",
        )

    def fail_if_ffmpeg_is_checked():
        raise AssertionError("FFmpeg must not be required when the option is disabled")

    provider.synthesize = fake_synthesize
    monkeypatch.setattr("app.services.audiobook_service.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.audiobook_service.AUDIOBOOK_ROOT", tmp_path)
    monkeypatch.setattr(audiobook_service, "build_provider", lambda _config: provider)
    monkeypatch.setattr(audiobook_service, "require_ffmpeg", fail_if_ffmpeg_is_checked)
    monkeypatch.setattr("app.services.audiobook_service.llm_orchestrator.chat", fake_chat)

    await audiobook_service.run_job(job_id)

    async with session_factory() as db:
        completed = await db.get(AudiobookJob, job_id)
        assert completed.status == "completed"
        assert pipeline_events[0] == "llm"
        assert pipeline_events[1] == "tts"
        assert chapter.id in completed.speech_scripts
        assert len(calls) >= 2
        assert all(item["status"] == "completed" for item in completed.segment_tasks)
        for artifact in completed.output_files:
            path = tmp_path / project_id / job_id / artifact["filename"]
            assert path.read_bytes().startswith(b"\xff\xfb")

    await engine.dispose()


def test_mp3_concatenation_removes_following_id3_header():
    second = b"ID3\x04\x00\x00\x00\x00\x00\x03abc" + b"audio-two"
    combined = audiobook_service.concatenate_mp3([b"audio-one", second])
    assert combined == b"audio-oneaudio-two"


@pytest.mark.anyio
async def test_background_job_generates_chapter_and_combined_mp3(monkeypatch, tmp_path):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        project = Project(name="后台任务测试")
        db.add(project)
        await db.flush()
        outline = Outline(project_id=project.id, title="主大纲")
        db.add(outline)
        await db.flush()
        first_node = OutlineNode(
            outline_id=outline.id,
            parent_id=None,
            node_type="CHAPTER",
            title="前一章",
            sort_order=0,
        )
        target_node = OutlineNode(
            outline_id=outline.id,
            parent_id=None,
            node_type="CHAPTER",
            title="大纲中的正确标题",
            sort_order=1,
        )
        db.add_all([first_node, target_node])
        await db.flush()
        character = Character(
            project_id=project.id,
            name="张三",
            aliases=["老张", "张老板"],
        )
        llm_config = LLMConfig(
            provider="openai_compatible",
            api_key_encrypted="configured",
            base_url="http://llm.local/v1",
            model_name="script-model",
            default_params={},
            is_active=True,
        )
        db.add_all([character, llm_config])
        await db.flush()
        config = AudiobookConfig(
            project_id=project.id,
            provider="openai_compatible",
            base_url="http://local/v1",
            model_name="tts",
            narrator_voice="narrator",
            character_voices={character.id: "voice-zhang"},
        )
        first_chapter = Chapter(
            project_id=project.id,
            outline_node_id=first_node.id,
            title="前一章的数据库标题",
            content="前一章正文",
            sort_order=0,
        )
        chapter = Chapter(
            project_id=project.id,
            outline_node_id=target_node.id,
            title="数据库中的旧标题",
            content="<p>老张说：“这是正文。”</p><p>张老板又道：“继续出发。”</p>",
            sort_order=1,
        )
        db.add_all([config, first_chapter, chapter])
        await db.flush()
        character_id = character.id
        job = AudiobookJob(
            project_id=project.id,
            config_id=config.id,
            script_llm_config_id=llm_config.id,
            scope_type="chapter",
            scope_id=chapter.id,
            scope_title="数据库中的旧标题",
            chapter_ids=[chapter.id],
            total_chapters=1,
            speech_scripts={},
            output_files=[],
        )
        db.add(job)
        await db.commit()
        job_id = job.id
        project_id = project.id
        script_llm_config_id = llm_config.id

    provider_calls = []
    pipeline_events = []

    async def fake_chat(config_id, messages, **kwargs):
        assert config_id == script_llm_config_id
        assert "大纲中的正确标题" in messages[1]["content"]
        pipeline_events.append("llm")
        return json.dumps(
            {
                "segments": [
                    {"speaker_id": None, "text": "老张说："},
                    {"speaker_id": character_id, "text": "这是正文。"},
                    {"speaker_id": None, "text": "张老板又道："},
                    {"speaker_id": character_id, "text": "继续出发。"},
                ]
            },
            ensure_ascii=False,
        )

    class FakeProvider:
        async def synthesize(self, text, voice, speed, filename_prefix):
            assert text
            pipeline_events.append("tts")
            provider_calls.append((text, voice))
            return AudioResult(content=b"\xff\xfbmock-mp3")

    monkeypatch.setattr("app.services.audiobook_service.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.audiobook_service.AUDIOBOOK_ROOT", tmp_path)
    monkeypatch.setattr(audiobook_service, "build_provider", lambda _config: FakeProvider())
    monkeypatch.setattr("app.services.audiobook_service.llm_orchestrator.chat", fake_chat)
    await audiobook_service.run_job(job_id)

    async with session_factory() as db:
        completed = await db.get(AudiobookJob, job_id)
        assert completed.status == "completed"
        assert pipeline_events[0] == "llm"
        assert pipeline_events[1] == "tts"
        assert chapter.id in completed.speech_scripts
        assert completed.progress == 100
        assert completed.processed_chapters == 1
        assert completed.scope_title == "大纲中的正确标题"
        assert [item["kind"] for item in completed.output_files] == [
            "combined",
            "chapter",
        ]
        assert completed.output_files[0]["filename"] == "大纲中的正确标题.mp3"
        assert completed.output_files[1]["title"] == "大纲中的正确标题"
        assert completed.output_files[1]["filename"] == "002_大纲中的正确标题.mp3"
        for artifact in completed.output_files:
            assert (tmp_path / project_id / job_id / artifact["filename"]).is_file()

        chapter_display_info = await audiobook_service.get_chapter_display_info(
            db, project_id
        )
        completed.scope_title = "数据库中的旧标题"
        completed.output_files = [
            {
                "kind": "combined",
                "filename": "数据库中的旧标题.mp3",
                "title": "数据库中的旧标题",
                "size_bytes": 10,
                "chapter_id": None,
            },
            {
                "kind": "chapter",
                "filename": "001_数据库中的旧标题.mp3",
                "title": "数据库中的旧标题",
                "size_bytes": 10,
                "chapter_id": chapter.id,
            },
        ]
        presented = await job_response(db, completed, chapter_display_info)
        assert presented.scope_title == "大纲中的正确标题"
        assert presented.output_files[0].download_filename == "大纲中的正确标题.mp3"
        assert presented.output_files[1].title == "大纲中的正确标题"
        assert (
            presented.output_files[1].download_filename
            == "002_大纲中的正确标题.mp3"
        )

    assert provider_calls[0][0].startswith("第2章，大纲中的正确标题。")
    assert provider_calls[0][1] == "narrator"

    alias_calls = [
        (text, voice)
        for text, voice in provider_calls
        if "这是正文" in text or "继续出发" in text
    ]
    assert alias_calls == [
        ("这是正文。", "voice-zhang"),
        ("继续出发。", "voice-zhang"),
    ]

    await engine.dispose()
