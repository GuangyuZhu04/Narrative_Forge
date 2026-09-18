import json
import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ["DEBUG"] = "false"

from app.db.session import get_db  # noqa: E402
from app.llm.prompts.long_novel import (  # noqa: E402
    LONG_NOVEL_POLISH_SYSTEM_PREFIX,
    LONG_NOVEL_WRITER_SYSTEM_PREFIX,
)
from app.llm.prompts.novel_agent_chat import (  # noqa: E402
    NOVEL_AGENT_CHAT_KERNEL,
    NOVEL_AGENT_CHAT_SCHEMA_VERSION,
    NOVEL_AGENT_CHAT_STAGE_USER,
)
from app.llm.prompts.novel_agent import NOVEL_AGENT_BLUEPRINT_SYSTEM  # noqa: E402
from app.llm.prompts.novel_polish import NOVEL_POLISH_SYSTEM  # noqa: E402
from app.llm.prompts.novel_write import (  # noqa: E402
    NOVEL_WRITE_SYSTEM,
    NOVEL_WRITE_USER,
)
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.services.chapter_service import chapter_service  # noqa: E402
from app.services.system_prompt_service import (  # noqa: E402
    NOVEL_WRITE_SYSTEM_KEY,
    NOVEL_WRITE_USER_TEMPLATE_KEY,
)


@pytest_asyncio.fixture
async def client():
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


def test_long_novel_system_prefixes_and_chat_protocol_are_cache_stable():
    assert NOVEL_WRITE_SYSTEM.startswith(LONG_NOVEL_WRITER_SYSTEM_PREFIX)
    assert NOVEL_POLISH_SYSTEM.startswith(LONG_NOVEL_POLISH_SYSTEM_PREFIX)
    assert "实际已写前文正文" in NOVEL_WRITE_SYSTEM
    assert "知识边界" in NOVEL_WRITE_SYSTEM
    assert "只允许改写【需要打磨的当前章节正文】" in NOVEL_POLISH_SYSTEM
    for placeholder in (
        "{outline_context}",
        "{volume_context}",
        "{chapter_title}",
        "{chapter_summary}",
        "{character_definitions}",
        "{scene_context}",
        "{previous_context}",
        "{previous_chapter_content}",
        "{style_requirements}",
    ):
        assert placeholder in NOVEL_WRITE_USER
    assert "{novel_bible}" in NOVEL_WRITE_USER
    assert "{chapter_contract}" in NOVEL_WRITE_USER
    assert '"style_guide"' in NOVEL_AGENT_BLUEPRINT_SYSTEM
    assert '"target_chars"' in NOVEL_AGENT_BLUEPRINT_SYSTEM
    assert '"target_chars": 10000' in NOVEL_AGENT_BLUEPRINT_SYSTEM
    assert "`target_chars=10000` 仅对应默认规模 300000 总字数 / 30 章" in (
        NOVEL_AGENT_BLUEPRINT_SYSTEM
    )
    assert "`target_chars` 总和必须与 `word_count_target` 闭环" in (
        NOVEL_AGENT_BLUEPRINT_SYSTEM
    )

    rendered = NOVEL_AGENT_CHAT_STAGE_USER.format(
        stage="characters",
        context='{"outline":"confirmed"}',
        instruction="生成两位主要人物",
    )
    assert "{stage}" not in rendered
    assert NOVEL_AGENT_CHAT_SCHEMA_VERSION in rendered
    assert "合法 JSON" in rendered
    assert "一致性分析" in NOVEL_AGENT_CHAT_KERNEL
    assert "自动打磨" in NOVEL_AGENT_CHAT_KERNEL
    assert "recommended=true" in NOVEL_AGENT_CHAT_KERNEL


def test_custom_legacy_write_template_keeps_placeholders_and_gets_kernel():
    context = {
        "chapter_id": "chapter-1",
        "chapter_title": "旧模板标题",
        "chapter_summary": "旧模板摘要",
        "outline_context": "旧模板大纲",
        "volume_context": "旧模板卷",
        "character_definitions": "旧模板人物",
        "scene_context": "旧模板场景",
        "previous_context": "旧模板前文",
        "previous_chapter_content": "旧模板正文",
        "style_requirements": "旧模板文风",
    }
    messages = chapter_service.build_novel_write_messages(
        context,
        {
            NOVEL_WRITE_SYSTEM_KEY: "管理员补充系统规则",
            NOVEL_WRITE_USER_TEMPLATE_KEY: (
                "{chapter_title}\n{chapter_summary}\n{previous_chapter_content}"
            ),
        },
    )
    assert messages[0]["content"].startswith(LONG_NOVEL_WRITER_SYSTEM_PREFIX)
    assert "管理员补充系统规则" in messages[0]["content"]
    assert messages[1]["content"] == "旧模板标题\n旧模板摘要\n旧模板正文"


async def _create_outline(client, project_id, chapter_specs):
    outline_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines",
        json={"title": "长篇主大纲", "description": "贯穿全书的因果主线"},
    )
    assert outline_response.status_code == 201
    outline_id = outline_response.json()["id"]
    volume_response = await client.post(
        f"/api/v1/projects/{project_id}/outlines/nodes",
        json={
            "outline_id": outline_id,
            "node_type": "VOLUME",
            "title": "第一卷",
            "summary": "主角追查失踪案并付出代价",
        },
    )
    assert volume_response.status_code == 201
    volume_id = volume_response.json()["id"]
    nodes = []
    for index, spec in enumerate(chapter_specs):
        response = await client.post(
            f"/api/v1/projects/{project_id}/outlines/nodes",
            json={
                "outline_id": outline_id,
                "parent_id": volume_id,
                "node_type": "CHAPTER",
                "title": spec["title"],
                "summary": spec.get("summary", "推进失踪案主线"),
                "sort_order": index,
                "metadata": spec.get("metadata"),
            },
        )
        assert response.status_code == 201
        nodes.append(response.json())
    return nodes


async def _create_character(client, project_id, name, alias=None):
    response = await client.post(
        f"/api/v1/projects/{project_id}/characters",
        json={
            "name": name,
            "aliases": [alias] if alias else [],
            "biography": f"{name}的公开人物小传",
            "setting_collection": f"{name}的私有隐藏设定不得发送",
        },
    )
    assert response.status_code == 201
    return response.json()


async def _create_scene(client, project_id, name, location):
    response = await client.post(
        f"/api/v1/projects/{project_id}/scenes",
        json={
            "name": name,
            "location": location,
            "description": f"{name}的空间与叙事功能",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.anyio
async def test_write_context_builds_bible_contract_and_filters_related_entities(
    client,
):
    settings = {
        "world_rules": ["记忆读取必须接触目标物三分钟"],
        "long_term_hooks": ["失踪者留下的蓝色火漆将在终卷回收"],
        "ending_direction": "主角放弃读取自己的记忆以保存真相",
        "style_guide": "限知第三人称，冷峻克制，短句用于危险场面",
    }
    project_response = await client.post(
        "/api/v1/projects",
        json={
            "name": "记忆之港",
            "description": "一部知识边界严格的长篇悬疑小说",
            "genre": "悬疑",
            "word_count_target": 120000,
            "settings": json.dumps(settings, ensure_ascii=False),
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    nodes = await _create_outline(
        client,
        project_id,
        [
            {"title": "第一章 湿信", "summary": "林远收到失踪者的湿信"},
            {
                "title": "第二章 火漆",
                "summary": "林远在码头验证火漆来源，但没有揭开终局真相",
                "metadata": {
                    "pov": "林远",
                    "scene_focus": ["雨夜码头"],
                    "characters": ["阿远"],
                    "hook": "仓库门后传来失踪者的口哨",
                    "target_chars": 6200,
                },
            },
        ],
    )
    await _create_character(client, project_id, "林远", "阿远")
    await _create_character(client, project_id, "苏岚")
    await _create_scene(client, project_id, "雨夜码头", "旧港")
    await _create_scene(client, project_id, "山顶疗养院", "北山")

    previous_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": nodes[0]["id"],
            "title": "第一章 湿信",
            "content": "林远把湿信贴身收好，独自赶往旧港。他尚不知道火漆属于谁。",
            "sort_order": 1,
        },
    )
    assert previous_response.status_code == 201
    current_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": nodes[1]["id"],
            "title": "数据库中的旧标题",
            "sort_order": 2,
        },
    )
    assert current_response.status_code == 201

    response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/"
        f"{current_response.json()['id']}/novel-write-context",
        json={},
    )
    assert response.status_code == 200
    context = response.json()

    assert context["target_chars"] == 6200
    assert context["target_chars_source"] == "outline_metadata"
    assert context["pov"] == "林远"
    assert context["hook"] == "仓库门后传来失踪者的口哨"
    assert context["style_requirements"] == settings["style_guide"]
    assert context["novel_bible_data"]["world_rules"] == settings["world_rules"]
    assert context["novel_bible_data"]["long_term_hooks"] == settings["long_term_hooks"]
    assert context["novel_bible_data"]["ending_direction"] == settings["ending_direction"]
    assert context["chapter_contract_data"]["target_chars"] == 6200
    assert context["chapter_contract_data"]["characters"] == ["阿远"]
    assert "林远的公开人物小传" in context["character_definitions"]
    assert "苏岚的公开人物小传" not in context["character_definitions"]
    assert "私有隐藏设定" not in context["character_definitions"]
    assert "雨夜码头" in context["scene_context"]
    assert "山顶疗养院" not in context["scene_context"]
    assert [item["selected"] for item in context["characters"]] == [True, False]
    assert [item["selected"] for item in context["scenes"]] == [True, False]
    assert "林远把湿信贴身收好" in context["previous_chapter_content"]

    messages = chapter_service.build_novel_write_messages(context)
    assert messages[0]["content"].startswith(LONG_NOVEL_WRITER_SYSTEM_PREFIX)
    assert "【小说圣经】" in messages[1]["content"]
    assert "【章节合同】" in messages[1]["content"]
    assert "【实际前文事实证据（最高优先）】" in messages[1]["content"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert "苏岚的公开人物小传" not in messages[1]["content"]
    assert "山顶疗养院" not in messages[1]["content"]
    assert "私有隐藏设定" not in messages[1]["content"]


def test_agent_context_can_omit_project_story_state_without_affecting_default():
    state_marker = "项目状态只应由对话 Session 注入一次"
    project = SimpleNamespace(
        name="上下文去重测试",
        description="",
        genre="悬疑",
        word_count_target=5000,
    )
    settings = {"story_state": {"confirmed_facts": [state_marker]}}

    default_bible = chapter_service._build_novel_bible(
        project, settings, "克制"
    )
    clean_bible = chapter_service._build_novel_bible(
        project,
        settings,
        "克制",
        include_story_state=False,
    )

    assert state_marker in json.dumps(default_bible, ensure_ascii=False)
    assert "story_state" not in clean_bible


@pytest.mark.anyio
async def test_novel_write_builds_a_fresh_two_message_window_for_each_chapter(
    client,
    monkeypatch,
):
    project_response = await client.post(
        "/api/v1/projects",
        json={
            "name": "章节窗口隔离测试",
            "settings": json.dumps(
                {
                    "story_state": {
                        "confirmed_facts": ["项目状态重复污染标记"]
                    }
                },
                ensure_ascii=False,
            ),
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    nodes = await _create_outline(
        client,
        project_id,
        [
            {"title": "第一章", "summary": "第一章计划"},
            {"title": "第二章", "summary": "第二章专用合同标记"},
        ],
    )
    first_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": nodes[0]["id"],
            "title": "第一章",
            "sort_order": 1,
        },
    )
    second_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": nodes[1]["id"],
            "title": "第二章",
            "sort_order": 2,
        },
    )
    assert first_response.status_code == 201
    assert second_response.status_code == 201
    calls = []

    async def fake_chat(_config_id, messages, **_kwargs):
        calls.append(messages)
        return "第一章实际正文衔接标记" if len(calls) == 1 else "第二章正文"

    monkeypatch.setattr(
        "app.services.chapter_service.llm_orchestrator.chat",
        fake_chat,
    )

    # Exercise the public write route twice so each call rebuilds its context
    # from the database instead of reusing any provider message history.
    first_write = await client.post(
        f"/api/v1/projects/{project_id}/chapters/"
        f"{first_response.json()['id']}/novel-write",
        json={"llm_config_id": "config-1"},
    )
    second_write = await client.post(
        f"/api/v1/projects/{project_id}/chapters/"
        f"{second_response.json()['id']}/novel-write",
        json={"llm_config_id": "config-1"},
    )

    assert first_write.status_code == 200
    assert second_write.status_code == 200
    assert [[message["role"] for message in call] for call in calls] == [
        ["system", "user"],
        ["system", "user"],
    ]
    assert calls[0] is not calls[1]
    assert "第二章专用合同标记" not in calls[0][1]["content"]
    assert "第二章专用合同标记" in calls[1][1]["content"]
    assert "第一章实际正文衔接标记" in calls[1][1]["content"]
    assert all(message["role"] != "assistant" for message in calls[1])


def test_agent_entity_selection_does_not_expand_missing_or_stale_contract_refs():
    characters = [
        SimpleNamespace(id="character-1", name="甲", aliases=[]),
        SimpleNamespace(id="character-2", name="乙", aliases=[]),
    ]
    scenes = [
        SimpleNamespace(id="scene-1", name="码头", location="旧港"),
        SimpleNamespace(id="scene-2", name="医院", location="北城"),
    ]

    selected_characters, stale_characters = chapter_service._select_characters(
        characters,
        ["已经改名的人物"],
        allow_fallback=False,
    )
    selected_scenes, stale_scenes = chapter_service._select_scenes(
        scenes,
        ["已经改名的场景"],
        allow_fallback=False,
    )

    assert selected_characters == []
    assert selected_scenes == []
    assert stale_characters is True
    assert stale_scenes is True
    assert chapter_service._select_characters(
        characters, [], allow_fallback=False
    ) == ([], False)


@pytest.mark.anyio
async def test_write_context_derives_target_and_safely_falls_back_on_stale_refs(
    client,
):
    project_response = await client.post(
        "/api/v1/projects",
        json={
            "name": "回退测试",
            "word_count_target": 21000,
            "settings": json.dumps(
                {
                    "world_rules": ["不存在瞬移"],
                    "long_term_hooks": ["旧表停在三点"],
                    "ending_direction": "回到故乡",
                    "style_guide": "第一人称",
                },
                ensure_ascii=False,
            ),
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]
    nodes = await _create_outline(
        client,
        project_id,
        [
            {"title": "第一章"},
            {
                "title": "第二章",
                "metadata": {
                    "characters": ["已被删除的人物"],
                    "scene_focus": "已经改名的场景",
                },
            },
            {"title": "第三章"},
        ],
    )
    await _create_character(client, project_id, "甲")
    await _create_character(client, project_id, "乙")
    await _create_scene(client, project_id, "车站", "南城")
    await _create_scene(client, project_id, "旧宅", "北城")
    chapter_response = await client.post(
        f"/api/v1/projects/{project_id}/chapters",
        json={
            "outline_node_id": nodes[1]["id"],
            "title": "第二章",
            "sort_order": 2,
        },
    )
    assert chapter_response.status_code == 201

    response = await client.post(
        f"/api/v1/projects/{project_id}/chapters/"
        f"{chapter_response.json()['id']}/novel-write-context",
        json={},
    )
    assert response.status_code == 200
    context = response.json()
    assert context["project_total_chapters"] == 3
    assert context["target_chars"] == 7000
    assert context["target_chars_source"] == "project_word_count"
    assert context["character_match_fallback"] is True
    assert context["scene_match_fallback"] is True
    assert context["selected_character_count"] == 2
    assert context["selected_scene_count"] == 2
    assert all(item["selected"] for item in context["characters"])
    assert all(item["selected"] for item in context["scenes"])
    assert "甲的公开人物小传" in context["character_definitions"]
    assert "乙的公开人物小传" in context["character_definitions"]
    assert "车站" in context["scene_context"]
    assert "旧宅" in context["scene_context"]
