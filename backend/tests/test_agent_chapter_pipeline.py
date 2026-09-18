import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.llm.contracts import LLMResult
from app.models.chapter import Chapter
from app.models.llm_config import LLMConfig
from app.models.project import Project
from app.services.agent_chapter_pipeline_service import AgentChapterPipelineService
from app.services.novel_agent_continue_service import NovelAgentContinueService
from app.services.novel_agent_service import NovelAgentService


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _story_delta(marker: str) -> dict:
    return {
        "summary": f"{marker}摘要",
        "confirmed_facts": [f"{marker}事实"],
        "character_states": {},
        "relationship_changes": [],
        "object_states": {},
        "opened_threads": [],
        "resolved_threads": [],
        "foreshadowing_updates": [],
        "story_clock": {},
    }


def _state(chapter_count: int = 3) -> dict:
    return {
        "scale": {"chapter_count": chapter_count},
        "execution": {
            "chapter_labels": [
                {
                    "id": f"chapter-{index}",
                    "title": f"第{index}章",
                    "order": index,
                    "chapter_index": index,
                }
                for index in range(1, chapter_count + 1)
            ],
            "chapter_contracts_by_id": {
                f"chapter-{index}": {
                    "title": f"第{index}章",
                    "summary": f"第{index}章合同",
                }
                for index in range(1, chapter_count + 1)
            },
        },
    }


class FakeDB:
    def __init__(self, *, chapters=None, project=None, config=None):
        self.chapters = chapters or {}
        self.project = project
        self.config = config
        self.commit_count = 0

    async def get(self, model, item_id):
        if model is Chapter:
            return self.chapters.get(item_id)
        if model is Project and self.project and self.project.id == item_id:
            return self.project
        if model is LLMConfig and self.config and self.config.id == item_id:
            return self.config
        return None

    async def commit(self):
        self.commit_count += 1


@pytest.mark.anyio
async def test_write_uses_strict_target_relative_context(monkeypatch):
    service = AgentChapterPipelineService()
    chapter = SimpleNamespace(
        id="chapter-2",
        project_id="project-1",
        title="第二章",
        content="",
        word_count=0,
    )
    project = SimpleNamespace(id="project-1", settings="{}")
    db = FakeDB(chapters={chapter.id: chapter}, project=project)
    state = _state()
    state["execution"]["story_state_deltas"] = {
        "chapter-3": {
            "chapter_id": "chapter-3",
            "chapter_title": "第三章",
            "delta": _story_delta("第三章未来"),
        },
        "chapter-1": {
            "chapter_id": "chapter-1",
            "chapter_title": "第一章",
            "delta": _story_delta("第一章实际"),
        },
    }
    captured = {}

    async def fake_novel_write(
        _db,
        _config_id,
        _project_id,
        _chapter_id,
        **kwargs,
    ):
        captured.update(kwargs)
        chapter.content = "第二章新正文"
        chapter.word_count = 8
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def failed_extract(*_args, **_kwargs):
        raise RuntimeError("本用例只验证正文上下文")

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )

    result = await service.execute_write(
        db,
        llm_config_id="config-1",
        project_id="project-1",
        chapter_id=chapter.id,
        state=state,
        style_requirements="克制、清晰",
        state_extractor=failed_extract,
    )

    assert result["content"] == "第二章新正文"
    assert result["story_state_updated"] is False
    assert captured["include_project_story_state"] is False
    assert captured["allow_entity_fallback"] is False
    assert captured["style_requirements"] == "克制、清晰"
    override = captured["overrides"]
    assert override is not None
    assert "第一章实际事实" in (override.previous_context or "")
    assert "第三章未来事实" not in (override.previous_context or "")


@pytest.mark.anyio
async def test_extract_story_state_prefers_uuid_contract_for_duplicate_titles(
    monkeypatch,
):
    service = AgentChapterPipelineService()
    state = _state(2)
    state["execution"]["chapter_labels"][0]["title"] = "同名章"
    state["execution"]["chapter_labels"][1]["title"] = "同名章"
    state["execution"]["chapter_contracts_by_id"] = {
        "chapter-1": {"title": "同名章", "summary": "第一个 UUID 合同"},
        "chapter-2": {"title": "同名章", "summary": "第二个 UUID 合同"},
    }
    state["artifacts"] = {
        "chapters": {
            "children": [
                {
                    "children": [
                        {"title": "同名章", "summary": "标题回退合同不得使用"}
                    ]
                }
            ]
        }
    }
    chapter = SimpleNamespace(id="chapter-2", title="同名章")
    config = SimpleNamespace(
        id="config-1",
        provider="openai",
        model_name="gpt-test",
        base_url="https://api.openai.com/v1",
        default_params=None,
    )
    db = FakeDB(config=config)
    captured = {}

    async def fake_response(_config_id, messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return LLMResult(text=json.dumps(_story_delta("第二章实际"), ensure_ascii=False))

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.llm_orchestrator.response",
        fake_response,
    )

    delta = await service.extract_story_state(
        db,
        "config-1",
        state,
        chapter,
        "第二章最终正文",
        previous_story_state={"confirmed_facts": ["第一章事实"]},
    )

    prompt = captured["messages"][-1]["content"]
    assert delta["summary"] == "第二章实际摘要"
    assert "第二个 UUID 合同" in prompt
    assert "第一个 UUID 合同" not in prompt
    assert "标题回退合同不得使用" not in prompt
    assert "第二章最终正文" in prompt
    assert "第一章事实" in prompt
    assert captured["kwargs"]["response_format"] == {"type": "json_object"}


@pytest.mark.anyio
async def test_rewrite_clears_stale_delta_before_failed_extraction(monkeypatch):
    service = AgentChapterPipelineService()
    chapter = SimpleNamespace(
        id="chapter-2",
        project_id="project-1",
        title="第二章",
        content="第二章旧正文",
        word_count=7,
    )
    project = SimpleNamespace(id="project-1", settings="{}")
    db = FakeDB(chapters={chapter.id: chapter}, project=project)
    state = _state()
    state["execution"]["story_state_deltas"] = {
        "chapter-1": {
            "chapter_id": "chapter-1",
            "chapter_title": "第一章",
            "delta": _story_delta("第一章"),
        },
        "chapter-2": {
            "chapter_id": "chapter-2",
            "chapter_title": "第二章",
            "delta": _story_delta("第二章旧版"),
        },
    }
    state["execution"]["story_state"] = service.story_state_before_order(state, 4)
    call_order = []
    persisted = []

    async def fake_save_version(*_args, **_kwargs):
        call_order.append("backup")
        return SimpleNamespace(id="version-before-write")

    async def fake_novel_write(*_args, **_kwargs):
        call_order.append("write")
        chapter.content = "第二章重写正文"
        chapter.word_count = 9
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def capture_persist(_db, _project_id, story_state, *, state=None):
        call_order.append("persist")
        persisted.append(deepcopy(story_state))

    async def failed_extract(*_args, **_kwargs):
        call_order.append("extract")
        raise RuntimeError("状态提取失败")

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.save_version",
        fake_save_version,
    )
    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )
    monkeypatch.setattr(service, "persist_project_story_state", capture_persist)

    result = await service.execute_write(
        db,
        llm_config_id="config-1",
        project_id="project-1",
        chapter_id=chapter.id,
        state=state,
        backup_summary="重写前备份",
        state_extractor=failed_extract,
    )

    assert call_order == ["backup", "write", "persist", "extract"]
    assert result["content"] == "第二章重写正文"
    assert result["backup_version_id"] == "version-before-write"
    assert result["story_state_updated"] is False
    assert "chapter-2" not in state["execution"]["story_state_deltas"]
    assert persisted[0]["confirmed_facts"] == ["第一章事实"]
    assert "第二章旧版" not in json.dumps(persisted, ensure_ascii=False)


@pytest.mark.anyio
async def test_write_polish_extracts_final_content_and_uses_distinct_backups(
    monkeypatch,
):
    service = AgentChapterPipelineService()
    chapter = SimpleNamespace(
        id="chapter-2",
        project_id="project-1",
        title="第二章",
        content="第二章旧正文",
        word_count=7,
    )
    project = SimpleNamespace(id="project-1", settings="{}")
    db = FakeDB(chapters={chapter.id: chapter}, project=project)
    state = _state()
    service.record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-1", title="第一章"),
        _story_delta("第一章"),
    )
    backup_summaries = []
    extracted = {}
    persisted = []

    async def fake_save_version(_db, _chapter_id, data):
        backup_summaries.append(data.change_summary)
        return SimpleNamespace(id=f"version-{len(backup_summaries)}")

    async def fake_novel_write(*_args, **_kwargs):
        chapter.content = "第二章生成草稿"
        chapter.word_count = 8
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def fake_polish(*_args, **_kwargs):
        chapter.content = "第二章打磨后最终正文"
        chapter.word_count = 11
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def capture_persist(_db, _project_id, story_state, *, state=None):
        persisted.append(deepcopy(story_state))

    async def fake_extract(
        _db,
        _config_id,
        _state,
        _chapter,
        content,
        *,
        previous_story_state=None,
    ):
        extracted["content"] = content
        extracted["previous"] = deepcopy(previous_story_state)
        return _story_delta("第二章新版")

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.save_version",
        fake_save_version,
    )
    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )
    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_polish",
        fake_polish,
    )
    monkeypatch.setattr(service, "persist_project_story_state", capture_persist)

    result = await service.execute_write(
        db,
        llm_config_id="config-1",
        project_id="project-1",
        chapter_id=chapter.id,
        state=state,
        policy={"consistency": False, "polish": True},
        backup_summary="正文重写前备份",
        polish_backup_summary="自动打磨前草稿",
        state_extractor=fake_extract,
    )

    assert backup_summaries == ["正文重写前备份", "自动打磨前草稿"]
    assert extracted["content"] == "第二章打磨后最终正文"
    assert extracted["previous"]["confirmed_facts"] == ["第一章事实"]
    assert result["content"] == "第二章打磨后最终正文"
    assert result["word_count"] == 11
    assert result["auto_polished"] is True
    assert result["story_state_updated"] is True
    assert result["backup_version_id"] == "version-1"
    assert len(persisted) == 2
    assert persisted[0]["confirmed_facts"] == ["第一章事实"]
    assert persisted[-1]["confirmed_facts"] == ["第一章事实", "第二章新版事实"]


@pytest.mark.anyio
async def test_execute_polish_extracts_polished_content_after_backup(monkeypatch):
    service = AgentChapterPipelineService()
    chapter = SimpleNamespace(
        id="chapter-2",
        project_id="project-1",
        title="第二章",
        content="第二章待打磨正文",
        word_count=8,
    )
    project = SimpleNamespace(id="project-1", settings="{}")
    db = FakeDB(chapters={chapter.id: chapter}, project=project)
    state = _state()
    service.record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-1", title="第一章"),
        _story_delta("第一章"),
    )
    captured = {}

    async def fake_save_version(_db, _chapter_id, data):
        captured["backup_summary"] = data.change_summary
        return SimpleNamespace(id="polish-backup")

    async def fake_polish(
        _db,
        _config_id,
        _project_id,
        _chapter_id,
        suggestions,
        **kwargs,
    ):
        captured["suggestions"] = suggestions
        captured["polish_kwargs"] = kwargs
        chapter.content = "第二章独立打磨后正文"
        chapter.word_count = 12
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def fake_extract(
        _db,
        _config_id,
        _state,
        _chapter,
        content,
        *,
        previous_story_state=None,
    ):
        captured["extracted_content"] = content
        captured["previous"] = deepcopy(previous_story_state)
        return _story_delta("第二章打磨版")

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.save_version",
        fake_save_version,
    )
    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_polish",
        fake_polish,
    )

    result = await service.execute_polish(
        db,
        llm_config_id="config-1",
        project_id="project-1",
        chapter_id=chapter.id,
        state=state,
        suggestions="加强章末悬念",
        include_previous_chapter=True,
        include_next_chapter=True,
        max_tokens=1234,
        backup_summary="续写改编执行前备份",
        state_extractor=fake_extract,
    )

    assert captured["backup_summary"] == "续写改编执行前备份"
    assert captured["suggestions"] == "加强章末悬念"
    assert captured["polish_kwargs"] == {
        "include_previous_chapter": True,
        "include_next_chapter": True,
        "max_tokens": 1234,
    }
    assert captured["extracted_content"] == "第二章独立打磨后正文"
    assert captured["previous"]["confirmed_facts"] == ["第一章事实"]
    assert result["content"] == "第二章独立打磨后正文"
    assert result["backup_version_id"] == "polish-backup"
    assert result["story_state_updated"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("accepts_state", [False, True], ids=["legacy", "state-aware"])
async def test_custom_story_state_persister_bypasses_default_and_supports_signatures(
    monkeypatch,
    accepts_state,
):
    service = AgentChapterPipelineService()
    chapter = SimpleNamespace(
        id="chapter-1",
        project_id="project-1",
        title="第一章",
        content="",
        word_count=0,
    )
    db = FakeDB(chapters={chapter.id: chapter})
    state = _state(1)
    persisted = []

    async def fake_novel_write(*_args, **_kwargs):
        chapter.content = "第一章正文"
        chapter.word_count = 6
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def fake_extract(*_args, **_kwargs):
        return _story_delta("第一章")

    async def unexpected_default(*_args, **_kwargs):
        raise AssertionError("提供 callback 后不应调用默认 Project settings persister")

    if accepts_state:

        async def custom_persister(
            _db,
            project_id,
            story_state,
            *,
            state=None,
        ):
            persisted.append(
                {
                    "project_id": project_id,
                    "story_state": deepcopy(story_state),
                    "state": deepcopy(state),
                }
            )

    else:

        async def custom_persister(_db, project_id, story_state):
            persisted.append(
                {
                    "project_id": project_id,
                    "story_state": deepcopy(story_state),
                }
            )

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )
    monkeypatch.setattr(service, "persist_project_story_state", unexpected_default)

    result = await service.execute_write(
        db,
        llm_config_id="config-1",
        project_id="project-1",
        chapter_id=chapter.id,
        state=state,
        state_extractor=fake_extract,
        story_state_persister=custom_persister,
    )

    assert result["story_state_updated"] is True
    assert [item["project_id"] for item in persisted] == [
        "project-1",
        "project-1",
    ]
    assert persisted[0]["story_state"] == {}
    assert persisted[-1]["story_state"]["confirmed_facts"] == ["第一章事实"]
    if accepts_state:
        assert persisted[-1]["state"]["execution"]["story_state_deltas"][
            "chapter-1"
        ]["delta"]["summary"] == "第一章摘要"


@pytest.mark.anyio
async def test_backup_empty_chapter_for_continue_worker(monkeypatch):
    service = AgentChapterPipelineService()
    chapter = SimpleNamespace(
        id="chapter-1",
        project_id="project-1",
        title="第一章",
        content="",
        word_count=0,
    )
    db = FakeDB(chapters={chapter.id: chapter})
    state = _state(1)
    backups = []

    async def fake_save_version(_db, _chapter_id, data):
        backups.append(data.change_summary)
        return SimpleNamespace(id="empty-chapter-backup")

    async def fake_novel_write(*_args, **_kwargs):
        chapter.content = "空章生成后的正文"
        chapter.word_count = 7
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def failed_extract(*_args, **_kwargs):
        raise RuntimeError("本用例只验证空章节备份")

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.save_version",
        fake_save_version,
    )
    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )

    result = await service.execute_write(
        db,
        llm_config_id="config-1",
        project_id="project-1",
        chapter_id=chapter.id,
        state=state,
        backup_empty_chapter=True,
        backup_summary="续写改编空章节执行前备份",
        state_extractor=failed_extract,
    )

    assert backups == ["续写改编空章节执行前备份"]
    assert result["backup_version_id"] == "empty-chapter-backup"
    assert result["content"] == "空章生成后的正文"


@pytest.mark.anyio
async def test_persist_story_state_preserves_plain_legacy_project_settings():
    service = AgentChapterPipelineService()
    legacy_settings = "魔法必须遵守代价守恒"
    project = SimpleNamespace(id="project-1", settings=legacy_settings)
    db = FakeDB(project=project)
    state = _state(1)
    state["execution"]["story_state_deltas"] = {
        "chapter-1": {
            "chapter_id": "chapter-1",
            "chapter_title": "第一章",
            "delta": _story_delta("第一章"),
        }
    }
    story_state = service.story_state_before_order(state, 2)
    state["execution"]["story_state"] = story_state

    await service.persist_project_story_state(
        db,
        "project-1",
        story_state,
        state=state,
    )

    persisted = json.loads(project.settings)
    assert persisted["legacy_settings"] == legacy_settings
    assert persisted["story_state"]["confirmed_facts"] == ["第一章事实"]
    assert persisted["story_state_ledger"]["story_state_deltas"]["chapter-1"][
        "delta"
    ]["summary"] == "第一章摘要"
    assert db.commit_count == 1


def test_remember_project_story_state_loads_legacy_aggregate_without_ledger():
    service = AgentChapterPipelineService()
    state = _state(2)
    legacy_story_state = {
        "schema_version": "story_state.v1",
        "after_chapter_id": "chapter-1",
        "after_chapter_title": "第一章",
        "confirmed_facts": ["旧版聚合事实"],
    }

    service.remember_project_story_state(
        state,
        json.dumps({"story_state": legacy_story_state}, ensure_ascii=False),
    )

    assert state["execution"]["story_state"] == legacy_story_state
    assert "story_state_base" not in state["execution"]
    assert "story_state_deltas" not in state["execution"]
    legacy_story_state["confirmed_facts"].append("外部修改")
    assert state["execution"]["story_state"]["confirmed_facts"] == [
        "旧版聚合事实"
    ]


def test_continue_plan_keeps_write_then_polish_for_same_chapter_and_deduplicates_each():
    service = NovelAgentContinueService()
    chapter = SimpleNamespace(id="chapter-1", title="第一章")
    plan = {
        "summary": "先重写再打磨",
        "actions": [
            {
                "action": "write",
                "chapter_id": chapter.id,
                "instruction": "先重写完整正文",
            },
            {
                "action": "write",
                "chapter_id": chapter.id,
                "instruction": "重复 write 不应执行",
            },
            {
                "action": "polish",
                "chapter_id": chapter.id,
                "instruction": "再打磨章末悬念",
                "include_previous_chapter": True,
            },
            {
                "action": "polish",
                "chapter_id": chapter.id,
                "instruction": "重复 polish 不应执行",
            },
        ],
    }

    normalized = service._normalize_plan(plan, [chapter], max_actions=10)

    assert [item["action"] for item in normalized["actions"]] == [
        "write",
        "polish",
    ]
    assert [item["instruction"] for item in normalized["actions"]] == [
        "先重写完整正文",
        "再打磨章末悬念",
    ]
    assert normalized["actions"][1]["include_previous_chapter"] is True


def test_legacy_contract_refs_keep_existing_refs_and_exclude_future_evidence():
    service = NovelAgentContinueService()
    state = _state(3)
    state["execution"]["chapter_contracts_by_id"]["chapter-2"].update(
        {
            "characters": ["权威人物"],
            "scene_focus": ["权威场景"],
        }
    )
    chapter = SimpleNamespace(
        id="chapter-2",
        title="第二章",
        summary="主角继续追查旧信",
    )
    project_context = {
        "characters": [
            {"name": "权威人物", "aliases": []},
            {"name": "前章人物", "aliases": []},
            {"name": "未来人物", "aliases": []},
        ],
        "scenes": [
            {"name": "权威场景", "location": "旧城"},
            {"name": "前章码头", "location": "北港"},
            {"name": "未来王宫", "location": "王都"},
        ],
        "chapters": [
            {
                "id": "chapter-1",
                "title": "第一章",
                "summary": "",
                "content_excerpt": "前章人物在前章码头留下旧信。",
            },
            {
                "id": "chapter-2",
                "title": "第二章",
                "summary": "主角继续追查旧信",
                "content_excerpt": "",
            },
            {
                "id": "chapter-3",
                "title": "第三章",
                "summary": "",
                "content_excerpt": "未来人物将在未来王宫现身。",
            },
        ],
    }

    service._prepare_legacy_chapter_contract_refs(
        state,
        project_context,
        chapter,
        {"instruction": "承接前章继续调查"},
    )

    contract = state["execution"]["chapter_contracts_by_id"]["chapter-2"]
    assert contract["characters"] == ["权威人物"]
    assert contract["scene_focus"] == ["权威场景"]
    assert "未来人物" not in contract["characters"]
    assert "未来王宫" not in contract["scene_focus"]


def test_legacy_contract_refs_infer_only_target_and_previous_chapter_entities():
    service = NovelAgentContinueService()
    state = _state(3)
    contract = state["execution"]["chapter_contracts_by_id"]["chapter-2"]
    contract.pop("characters", None)
    contract.pop("scene_focus", None)
    chapter = SimpleNamespace(
        id="chapter-2",
        title="第二章",
        summary="苏岚追查雪港钟楼的失窃星图",
    )
    project_context = {
        "characters": [
            {"name": "林远", "aliases": ["阿远"]},
            {"name": "苏岚", "aliases": []},
            {"name": "未来反派", "aliases": []},
            {"name": "无关人物", "aliases": []},
        ],
        "scenes": [
            {"name": "雪港钟楼", "location": "北境雪港"},
            {"name": "未来王宫", "location": "王都"},
            {"name": "无关山谷", "location": "南境"},
        ],
        "chapters": [
            {
                "id": "chapter-1",
                "title": "第一章",
                "summary": "",
                "content_excerpt": "阿远把旧信交给苏岚后离开雪港钟楼。",
            },
            {
                "id": "chapter-2",
                "title": "第二章",
                "summary": chapter.summary,
                "content_excerpt": "",
            },
            {
                "id": "chapter-3",
                "title": "第三章",
                "summary": "",
                "content_excerpt": "未来反派将在未来王宫伏击众人。",
            },
        ],
    }

    service._prepare_legacy_chapter_contract_refs(
        state,
        project_context,
        chapter,
        {"instruction": "承接阿远的旧信，让苏岚检查钟楼机关"},
    )

    assert contract["characters"] == ["林远", "苏岚"]
    assert contract["scene_focus"] == ["雪港钟楼"]
    assert "未来反派" not in contract["characters"]
    assert "无关人物" not in contract["characters"]
    assert "未来王宫" not in contract["scene_focus"]
    assert "无关山谷" not in contract["scene_focus"]


def _blueprint_with_chapter_weights(*weights) -> dict:
    return {
        "outline": {
            "children": [
                {
                    "node_type": "VOLUME",
                    "title": "第一卷",
                    "children": [
                        {
                            "node_type": "CHAPTER",
                            "title": f"第{index}章",
                            "summary": "推进主线",
                            "metadata": (
                                {"target_chars": weight}
                                if weight is not None
                                else {}
                            ),
                            "children": [],
                        }
                        for index, weight in enumerate(weights, start=1)
                    ],
                }
            ]
        }
    }


@pytest.mark.parametrize(
    ("word_count_target", "expected_total"),
    [
        (1000, 3000),
        (9000, 9000),
        (50000, 24000),
    ],
    ids=["min-clamped", "exact", "max-clamped"],
)
def test_generate_chapter_contracts_fill_fields_and_close_word_budget(
    word_count_target,
    expected_total,
):
    blueprint = _blueprint_with_chapter_weights(None, None)

    NovelAgentService._normalize_blueprint_chapter_contracts(
        blueprint,
        word_count_target,
    )

    chapters = blueprint["outline"]["children"][0]["children"]
    required_metadata = {
        "chapter_index",
        "pov",
        "scene_focus",
        "characters",
        "hook",
        "target_chars",
        "ordered_beats",
        "must_reveal",
        "must_not_reveal",
        "expected_state_deltas",
    }
    assert [item["metadata"]["chapter_index"] for item in chapters] == [1, 2]
    assert all(set(item["metadata"]) == required_metadata for item in chapters)
    assert sum(item["metadata"]["target_chars"] for item in chapters) == expected_total
    assert all(
        1500 <= item["metadata"]["target_chars"] <= 12000
        for item in chapters
    )


def test_generate_chapter_contracts_preserve_weights_and_are_idempotent():
    blueprint = _blueprint_with_chapter_weights(1, 2)

    NovelAgentService._normalize_blueprint_chapter_contracts(blueprint, 9000)
    first = deepcopy(blueprint)
    NovelAgentService._normalize_blueprint_chapter_contracts(blueprint, 9000)

    chapters = blueprint["outline"]["children"][0]["children"]
    assert [item["metadata"]["target_chars"] for item in chapters] == [3000, 6000]
    assert blueprint == first


@pytest.mark.parametrize("invalid_weight", ["NaN", "Infinity", "-Infinity"])
def test_generate_chapter_contracts_replace_nonfinite_weights(invalid_weight):
    blueprint = _blueprint_with_chapter_weights(invalid_weight, 3000)

    NovelAgentService._normalize_blueprint_chapter_contracts(blueprint, 9000)

    targets = [
        item["metadata"]["target_chars"]
        for item in blueprint["outline"]["children"][0]["children"]
    ]
    assert sum(targets) == 9000
    assert all(isinstance(item, int) and 1500 <= item <= 12000 for item in targets)


def test_continue_plan_repair_score_counts_distinct_chapters_not_actions():
    plan = {
        "actions": [
            {"action": "write", "chapter_id": "chapter-1"},
            {"action": "polish", "chapter_id": "chapter-1"},
            {"action": "write", "chapter_id": "chapter-2"},
        ]
    }

    assert NovelAgentContinueService._plan_repair_score(plan, None) == (2, 3)
    required = [
        SimpleNamespace(id="chapter-1"),
        SimpleNamespace(id="chapter-2"),
        SimpleNamespace(id="chapter-3"),
    ]
    assert NovelAgentContinueService._plan_repair_score(plan, required) == (2, 3)


def test_required_blank_actions_keep_write_when_later_polish_targets_same_chapter():
    service = NovelAgentContinueService()
    required = [SimpleNamespace(id="chapter-1", title="第一章")]
    plan = {
        "summary": "先续写再打磨",
        "actions": [
            {
                "action": "write",
                "chapter_id": "chapter-1",
                "chapter_title": "第一章",
                "instruction": "续写空白正文",
                "style_requirements": "克制",
                "include_previous_chapter": False,
                "include_next_chapter": False,
            },
            {
                "action": "polish",
                "chapter_id": "chapter-1",
                "chapter_title": "第一章",
                "instruction": "稍后打磨",
            },
        ],
    }

    normalized = service._enforce_required_blank_actions(plan, required)

    assert len(normalized["actions"]) == 1
    assert normalized["actions"][0]["action"] == "write"
    assert normalized["actions"][0]["instruction"] == "续写空白正文"
    assert normalized["actions"][0]["style_requirements"] == "克制"
