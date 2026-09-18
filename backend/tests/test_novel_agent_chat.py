from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.llm.contracts import LLMResult, LLMUsage
from app.llm.output_limits import DEEPSEEK_V4_MAX_OUTPUT_TOKENS
from app.models.base import Base
from app.models.chapter import Chapter
from app.models.character import Character
from app.models.outline import Outline, OutlineNode
from app.models.project import Project
from app.models.scene import Scene
from app.schemas.novel_agent import NovelAgentChatAnswer, NovelAgentChatTurnRequest
from app.services.novel_agent_chat_service import (
    CHAPTER_BATCH_MAX_ATTEMPTS,
    OUTLINE_FOUNDATION_MAX_TOKENS,
    OUTLINE_FOUNDATION_RESPONSE_SCHEMA,
    OUTLINE_VOLUME_MAX_TOKENS,
    OUTLINE_VOLUME_RESPONSE_SCHEMA,
    WRITE_SCOPE_SELECTION_VERSION,
    NovelAgentChatService,
)
from app.services.novel_agent_service import (
    NovelAgentOutputError,
    NovelAgentStructuredOutputError,
    novel_agent_service,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_generated_questions_follow_plan_option_protocol():
    service = NovelAgentChatService()
    state = {"state_version": 4, "scale": {"chapter_count": 18}}
    write_state = {
        "state_version": 4,
        "scale": {"chapter_count": 18},
        "execution": {
            "chapter_labels": [
                {"id": f"chapter-{index}", "title": f"第 {index} 章", "order": index}
                for index in range(1, 19)
            ]
        },
    }

    for kind in (
        "direction",
        "character_scope",
        "scene_scope",
        "chapter_scope",
        "write_scope",
        "outline_review",
    ):
        question_state = write_state if kind == "write_scope" else state
        question = service._fallback_question(kind, 5, question_state)
        assert 2 <= len(question["options"]) <= 3
        assert len({item["id"] for item in question["options"]}) == len(question["options"])
        assert sum(item["recommended"] for item in question["options"]) == 1


def _chapter_label_state(count=60):
    return {
        "state_version": 8,
        "scale": {"chapter_count": count},
        "execution": {
            "chapter_labels": [
                {
                    "id": f"chapter-{index}",
                    "title": "书房的雨夜" if index == 1 else f"第 {index} 章标题",
                    "order": index,
                }
                for index in range(1, count + 1)
            ]
        },
    }


@pytest.mark.anyio
async def test_write_scope_for_sixty_chapters_starts_at_first_chapter(monkeypatch):
    service = NovelAgentChatService()
    state = _chapter_label_state()

    async def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("正文范围应由程序计算，不应调用模型")

    monkeypatch.setattr(service, "_model_question", unexpected_model_call)

    question = await service._scope_question(object(), "config-1", state, "write_scope")
    options = {item["id"]: item for item in question["options"]}

    assert [item["id"] for item in question["options"]] == ["multiple", "single", "all"]
    assert "第 1-5 章" in options["multiple"]["description"]
    assert "第 1 章·书房的雨夜" in options["single"]["description"]
    assert "第 1-60 章" in options["all"]["description"]
    assert "第31章" not in "".join(item["description"] for item in question["options"])

    assert service._select_chapter_ids({"option": options["single"]}, state) == ["chapter-1"]
    assert service._select_chapter_ids({"option": options["multiple"]}, state) == [
        f"chapter-{index}" for index in range(1, 6)
    ]
    assert service._select_chapter_ids({"option": options["all"]}, state) == [
        f"chapter-{index}" for index in range(1, 61)
    ]


def test_saved_write_scope_is_refreshed_and_rejects_stale_question_identity():
    service = NovelAgentChatService()
    state = _chapter_label_state()
    state.update(
        {
            "stage": "write_scope",
            "pending_questions": [
                {
                    "id": "write_scope:8:1",
                    "header": "正文生成范围",
                    "question": "本次希望生成多少章的正文？",
                    "options": [
                        service._option(
                            "multiple",
                            "批量生成",
                            "默认一次生成5章正文（自第31章起）。",
                            True,
                            {"mode": "multiple", "count": 5},
                        ),
                        service._option(
                            "single",
                            "单章生成",
                            "仅生成下一章（第31章·开庭之前）。",
                            False,
                            {"mode": "single"},
                        ),
                        service._option(
                            "all",
                            "全部生成",
                            "一次生成第31至60章全部剩余正文。",
                            False,
                            {"mode": "all"},
                        ),
                    ],
                    "allow_custom": True,
                    "state_version": 8,
                }
            ],
        }
    )

    assert service._refresh_pending_write_scope(state) is True

    refreshed = state["pending_questions"][0]
    assert refreshed["id"] == "write_scope:9:1"
    assert refreshed["state_version"] == 9
    assert state["state_version"] == 9
    assert "第 1-5 章" in refreshed["options"][0]["description"]
    assert "第31章" not in "".join(item["description"] for item in refreshed["options"])
    assert service._refresh_pending_write_scope(state) is False

    with pytest.raises(NovelAgentOutputError, match="回答与当前待处理问题不匹配"):
        service._validate_answers(
            state["pending_questions"],
            [NovelAgentChatAnswer(question_id="write_scope:8:1", option_id="multiple")],
            "",
        )


@pytest.mark.anyio
async def test_stale_write_scope_submission_persists_and_returns_replacement(monkeypatch):
    service = NovelAgentChatService()
    state = _chapter_label_state()
    state.update(
        {
            "schema_version": "novel.agent.chat.v1",
            "stage": "write_scope",
            "llm_config_id": "config-1",
            "messages": [{"id": "m1", "role": "assistant", "kind": "text", "content": "请选择"}],
            "pending_questions": [
                {
                    "id": "write_scope:8:1",
                    "header": "正文生成范围",
                    "question": "本次希望生成多少章的正文？",
                    "options": [
                        service._option(
                            "multiple",
                            "批量生成",
                            "默认一次生成5章正文（自第31章起）。",
                            True,
                            {"mode": "multiple", "count": 5},
                        ),
                        service._option(
                            "single",
                            "单章生成",
                            "仅生成下一章（第31章·开庭之前）。",
                            False,
                            {"mode": "single"},
                        ),
                        service._option(
                            "all",
                            "全部生成",
                            "一次生成第31至60章全部剩余正文。",
                            False,
                            {"mode": "all"},
                        ),
                    ],
                    "allow_custom": True,
                    "state_version": 8,
                }
            ],
            "artifacts": {},
            "confirmed": {},
            "selections": {},
            "quality_policy": {},
            "materialized_structure": {},
            "structure_created": True,
            "result": None,
        }
    )
    session = SimpleNamespace(id="session-1", request_payload={"chat_state": state})
    saved = []

    async def fake_sync(*_args):
        return None

    async def fake_save(_db, _session, current, **_kwargs):
        saved.append(deepcopy(current))

    monkeypatch.setattr(service, "_sync_confirmed_artifacts", fake_sync)
    monkeypatch.setattr(service, "_save", fake_save)
    request = NovelAgentChatTurnRequest(
        session_id="session-1",
        llm_config_id="config-1",
        answers=[
            NovelAgentChatAnswer(question_id="write_scope:8:1", option_id="multiple")
        ],
    )

    events = [
        event
        async for event in service._handle_turn_stream_unlocked(
            object(), "project-1", session, request
        )
    ]

    assert len(saved) == 1
    replacement = saved[0]["pending_questions"][0]
    assert replacement["id"] == "write_scope:9:1"
    assert "第 1-5 章" in replacement["options"][0]["description"]
    assert events == [{"type": "question", "question": replacement}]


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["quality_gate", "resume"])
async def test_legacy_unwritten_quality_gate_reasks_write_scope(stage):
    service = NovelAgentChatService()
    state = _chapter_label_state()
    state.update(
        {
            "stage": stage,
            "pending_questions": [],
            "execution": {
                **state["execution"],
                "pending_chapter_ids": [f"chapter-{index}" for index in range(1, 6)],
                "selected_count": 5,
                "chapter_results": [],
            },
        }
    )
    if stage == "resume":
        state["inflight_turn"] = {
            "resume_stage": "quality_gate",
            "answers": {},
            "questions": [],
        }

    chapters = {
        f"chapter-{index}": SimpleNamespace(
            id=f"chapter-{index}",
            project_id="project-1",
            content="",
            word_count=0,
        )
        for index in range(1, 61)
    }

    async def fake_get(_model, chapter_id):
        return chapters.get(chapter_id)

    assert (
        await service._reset_legacy_unwritten_write_selection(
            SimpleNamespace(get=fake_get), "project-1", state
        )
        is True
    )
    assert state["stage"] == "write_scope"
    assert "inflight_turn" not in state
    assert "pending_chapter_ids" not in state["execution"]
    assert "selected_count" not in state["execution"]
    assert "第 1-5 章" in state["pending_questions"][0]["options"][0]["description"]


@pytest.mark.anyio
async def test_quality_gate_with_current_selection_or_written_results_is_not_reset():
    service = NovelAgentChatService()
    current = _chapter_label_state()
    current.update(
        {
            "stage": "quality_gate",
            "execution": {
                **current["execution"],
                "pending_chapter_ids": ["chapter-1"],
                "chapter_results": [],
                "write_scope_selection_version": WRITE_SCOPE_SELECTION_VERSION,
            },
        }
    )
    written = deepcopy(current)
    written["execution"].pop("write_scope_selection_version")
    written["execution"]["chapter_results"] = [{"chapter_id": "chapter-1"}]

    db = SimpleNamespace()
    assert (
        await service._reset_legacy_unwritten_write_selection(db, "project-1", current)
        is False
    )
    assert (
        await service._reset_legacy_unwritten_write_selection(db, "project-1", written)
        is False
    )


@pytest.mark.anyio
async def test_legacy_quality_gate_is_not_reset_when_any_chapter_has_content():
    service = NovelAgentChatService()
    state = _chapter_label_state(3)
    state.update(
        {
            "stage": "quality_gate",
            "execution": {
                **state["execution"],
                "pending_chapter_ids": ["chapter-1"],
                "chapter_results": [],
            },
        }
    )
    before = deepcopy(state)

    async def fake_get(_model, chapter_id):
        return SimpleNamespace(
            id=chapter_id,
            project_id="project-1",
            content="已有正文" if chapter_id == "chapter-2" else "",
            word_count=0,
        )

    assert (
        await service._reset_legacy_unwritten_write_selection(
            SimpleNamespace(get=fake_get), "project-1", state
        )
        is False
    )
    assert state == before


@pytest.mark.anyio
@pytest.mark.parametrize(
    "pending_ids",
    [None, [], "chapter-1", [""], ["chapter-1", "chapter-1"], ["unknown"]],
)
async def test_legacy_quality_gate_invalid_targets_fail_closed(pending_ids):
    service = NovelAgentChatService()
    state = _chapter_label_state(2)
    state.update(
        {
            "stage": "quality_gate",
            "execution": {
                **state["execution"],
                "pending_chapter_ids": pending_ids,
                "chapter_results": [],
            },
        }
    )
    before = deepcopy(state)

    assert (
        await service._reset_legacy_unwritten_write_selection(
            SimpleNamespace(), "project-1", state
        )
        is False
    )
    assert state == before


@pytest.mark.parametrize("failure", ["missing", "duplicate", "extra"])
def test_ordered_chapter_labels_fail_closed_on_invalid_state(failure):
    state = _chapter_label_state(3)
    if failure == "missing":
        state["execution"].pop("chapter_labels")
    elif failure == "duplicate":
        state["execution"]["chapter_labels"][2]["order"] = 2
    else:
        state["execution"]["chapter_labels"].append(
            {"id": "chapter-duplicate", "title": "重复章", "order": 3}
        )

    with pytest.raises(NovelAgentOutputError, match="待写章节顺序"):
        NovelAgentChatService._ordered_chapter_labels(state)


@pytest.mark.parametrize(
    "option",
    [
        {"id": "multiple", "value": {"mode": "multiple", "count": 0}},
        {"id": "multiple", "value": {"mode": "multiple", "count": 61}},
        {"id": "multiple", "value": {"mode": "multiple", "count": True}},
        {"id": "single", "value": {"mode": "all"}},
        {"id": "unknown", "value": {"mode": "unknown"}},
    ],
)
def test_select_chapter_ids_rejects_invalid_standard_ranges(option):
    with pytest.raises(NovelAgentOutputError):
        NovelAgentChatService._select_chapter_ids(
            {"option": option}, _chapter_label_state()
        )


def test_stale_or_incomplete_question_answers_are_rejected():
    service = NovelAgentChatService()
    question = service._fallback_question("character_scope", 2)
    state = {"state_version": 1, "stage": "direction", "pending_questions": []}
    service._set_questions(state, "character_scope", [question])

    with pytest.raises(NovelAgentOutputError):
        service._validate_answers(
            state["pending_questions"],
            [NovelAgentChatAnswer(question_id="character_scope:1:1", option_id="single")],
            "",
        )


def test_review_action_uses_option_id_instead_of_model_value():
    assert (
        NovelAgentChatService._answer_action(
            {
                "option": {
                    "id": "accept",
                    "value": {"action": "regenerate"},
                }
            }
        )
        == "accept"
    )


def test_quality_artifact_summarizes_policy_for_display():
    assert NovelAgentChatService._quality_artifact(
        {
            "consistency": True,
            "polish": False,
            "approval_scope": "each",
        },
        3,
    ) == {
        "consistency_analysis": "启用",
        "automatic_polish": "关闭",
        "application_scope": "逐章确认",
        "target_chapter_count": 3,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stage", "generator_name", "artifact_name", "count"),
    [
        ("character_scope", "_generate_characters", "characters", 4),
        ("scene_scope", "_generate_scenes", "scenes", 5),
    ],
)
async def test_collection_scope_generation_emits_start_and_completion_progress(
    monkeypatch,
    stage,
    generator_name,
    artifact_name,
    count,
):
    service = NovelAgentChatService()
    state = {
        "stage": stage,
        "selections": {},
        "scale": {"chapter_count": 6},
        "artifacts": {"outline": {}, "characters": []},
    }
    generated = [{"name": f"项目 {index}"} for index in range(count)]

    async def fake_generate(*_args, **_kwargs):
        return generated

    async def fake_review(*_args, **_kwargs):
        if False:
            yield {}

    monkeypatch.setattr(service, generator_name, fake_generate)
    monkeypatch.setattr(service, "_review_artifact", fake_review)
    events = [
        event
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            state,
            {
                "scope-question": {
                    "option": {"id": "core", "value": {"count": count}}
                }
            },
            "config-1",
        )
    ]

    progress = [event["progress"] for event in events if event["type"] == "progress"]
    assert [
        (item["current"], item["total"], item["status"]) for item in progress
    ] == [(0, 1, "running"), (1, 1, "completed")]
    assert progress[0]["step"] == artifact_name
    assert state["artifacts"][artifact_name] == generated
    assert events[-1]["type"] == "artifact"


@pytest.mark.anyio
async def test_chapter_contract_stream_reports_each_completed_batch(monkeypatch):
    service = NovelAgentChatService()
    state = {
        "scale": {"chapter_count": 5, "word_count_target": 50000},
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "测试大纲",
                    "description": "",
                    "children": [
                        {
                            "node_type": "VOLUME",
                            "title": "第一卷",
                            "children": [],
                        }
                    ],
                }
            },
            "characters": [],
            "scenes": [],
        },
    }
    ranges = []

    async def fake_request(_db, _config_id, _stage, context, *_args, **_kwargs):
        chapter_range = context["range"]
        ranges.append((chapter_range["start"], chapter_range["count"]))
        return {
            "chapters": [
                {
                    "volume_index": 1,
                    "title": f"第 {index} 章",
                    "summary": "推进主线",
                    "metadata": {},
                }
                for index in range(
                    chapter_range["start"],
                    chapter_range["start"] + chapter_range["count"],
                )
            ]
        }

    monkeypatch.setattr(service, "_request_json", fake_request)
    events = [
        event
        async for event in service._generate_chapters_stream(
            object(), "config-1", state, batch_size=2
        )
    ]

    progress = [event["progress"] for event in events if event["type"] == "progress"]
    assert ranges == [(1, 2), (3, 2), (5, 1)]
    assert [item["current"] for item in progress] == [0, 2, 4, 5]
    assert all(item["total"] == 5 for item in progress)
    assert [item["status"] for item in progress] == [
        "running",
        "running",
        "running",
        "completed",
    ]
    assert progress[0]["message"].startswith("正在规划第 1-2 章章节合同")
    assert "正在规划第 5 章，尚未生成正文" in progress[2]["message"]
    assert "第 5-5 章" not in progress[2]["message"]
    artifact_events = [event for event in events if event["type"] == "artifact"]
    assert len(artifact_events) == 1
    chapters = artifact_events[0]["artifact"]["data"]["children"][0]["children"]
    assert len(chapters) == 5


@pytest.mark.anyio
async def test_single_chapter_batches_never_render_duplicate_range(monkeypatch):
    service = NovelAgentChatService()
    state = {
        "scale": {"chapter_count": 2, "word_count_target": 10000},
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "测试大纲",
                    "children": [
                        {"node_type": "VOLUME", "title": "第一卷", "children": []}
                    ],
                }
            },
            "characters": [],
            "scenes": [],
        },
    }

    async def fake_request(_db, _config_id, _stage, context, *_args, **_kwargs):
        index = context["range"]["start"]
        return {
            "chapters": [
                {
                    "volume_index": 1,
                    "title": f"第 {index} 章",
                    "summary": "推进主线",
                    "metadata": {},
                }
            ]
        }

    monkeypatch.setattr(service, "_request_json", fake_request)
    events = [
        event
        async for event in service._generate_chapters_stream(
            object(), "config-1", state, batch_size=1
        )
    ]

    progress = [event["progress"] for event in events if event["type"] == "progress"]
    assert progress[0]["message"].startswith("正在规划第 1 章章节合同")
    assert "正在规划第 2 章，尚未生成正文" in progress[1]["message"]
    assert all("第 1-1 章" not in item["message"] for item in progress)
    assert all("第 2-2 章" not in item["message"] for item in progress)


@pytest.mark.anyio
async def test_chapter_contract_stream_checkpoints_and_resumes_remaining_batches(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = {
        "scale": {"chapter_count": 3, "word_count_target": 30000},
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "测试大纲",
                    "description": "",
                    "children": [
                        {
                            "node_type": "VOLUME",
                            "title": "第一卷",
                            "children": [],
                        }
                    ],
                }
            },
            "characters": [],
            "scenes": [],
        },
    }
    ranges = []
    checkpoints = []
    fail_second_batch = True

    async def fake_request(_db, _config_id, _stage, context, *_args, **_kwargs):
        nonlocal fail_second_batch
        chapter_range = context["range"]
        start = chapter_range["start"]
        count = chapter_range["count"]
        ranges.append((start, count, len(context["generated_chapters"])))
        if start == 2 and fail_second_batch:
            fail_second_batch = False
            raise NovelAgentOutputError("第二批章节合同失败")
        return {
            "chapters": [
                {
                    "volume_index": 1,
                    "title": f"第 {index} 章",
                    "summary": "推进主线",
                    "metadata": {},
                }
                for index in range(start, start + count)
            ]
        }

    async def fake_checkpoint(_db, _session, checkpoint, **_kwargs):
        checkpoints.append(deepcopy(checkpoint))

    monkeypatch.setattr(service, "_request_json", fake_request)
    monkeypatch.setattr(service, "_save_recovery_checkpoint", fake_checkpoint)
    stream_kwargs = {
        "session": SimpleNamespace(),
        "resume_stage": "chapter_scope",
        "resume_answers": {"q": {"option": {"id": "single"}}},
        "resume_questions": [],
    }

    with pytest.raises(NovelAgentOutputError, match="第二批章节合同失败"):
        async for _event in service._generate_chapters_stream(
            object(), "config-1", state, batch_size=1, **stream_kwargs
        ):
            pass

    assert ranges == [(1, 1, 0), (2, 1, 1)]
    assert len(checkpoints[0]["chapter_generation"]["chapters"]) == 1
    assert checkpoints[0]["chapter_generation"]["last_error"] is None
    failed_checkpoint = checkpoints[-1]
    assert len(failed_checkpoint["chapter_generation"]["chapters"]) == 1
    assert failed_checkpoint["chapter_generation"]["last_error"]["start"] == 2

    recovered_state = deepcopy(failed_checkpoint)
    events = [
        event
        async for event in service._generate_chapters_stream(
            object(), "config-1", recovered_state, batch_size=1, **stream_kwargs
        )
    ]

    assert ranges == [
        (1, 1, 0),
        (2, 1, 1),
        (2, 1, 1),
        (3, 1, 2),
    ]
    progress = [event["progress"] for event in events if event["type"] == "progress"]
    assert progress[0]["current"] == 1
    assert "已恢复" in progress[0]["message"]
    artifact_events = [event for event in events if event["type"] == "artifact"]
    assert len(artifact_events) == 1
    chapters = artifact_events[0]["artifact"]["data"]["children"][0]["children"]
    assert len(chapters) == 3
    assert "chapter_generation" not in recovered_state


@pytest.mark.anyio
async def test_non_monotonic_saved_chapter_checkpoint_restarts_from_first_chapter(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = {
        "scale": {
            "volume_count": 2,
            "chapter_count": 4,
            "word_count_target": 20000,
        },
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "测试大纲",
                    "children": [
                        {"node_type": "VOLUME", "title": "第一卷", "children": []},
                        {"node_type": "VOLUME", "title": "第二卷", "children": []},
                    ],
                }
            },
            "characters": [],
            "scenes": [],
        },
    }
    signature = service._chapter_generation_signature(
        state, batch_size=2, revision=None
    )
    state["chapter_generation"] = {
        "signature": signature,
        "batch_size": 2,
        "revision": None,
        "chapters": [
            {
                "volume_index": 2,
                "title": "旧第一章",
                "summary": "推进",
                "metadata": {},
            },
            {
                "volume_index": 1,
                "title": "旧第二章",
                "summary": "推进",
                "metadata": {},
            },
        ],
        "last_error": None,
    }
    starts = []

    async def fake_request(_db, _config_id, _stage, context, *_args, **_kwargs):
        start = context["range"]["start"]
        count = context["range"]["count"]
        starts.append(start)
        return {
            "chapters": [
                {
                    "volume_index": 1 if index <= 2 else 2,
                    "title": f"第 {index} 章",
                    "summary": "推进",
                    "metadata": {},
                }
                for index in range(start, start + count)
            ]
        }

    monkeypatch.setattr(service, "_request_json", fake_request)

    events = [
        event
        async for event in service._generate_chapters_stream(
            object(), "config-1", state, batch_size=2
        )
    ]

    assert starts == [1, 3]
    artifact = [event for event in events if event["type"] == "artifact"][-1]
    flattened = service._flatten_chapter_contracts(artifact["artifact"]["data"])
    assert [item["title"] for item in flattened] == [
        "第 1 章",
        "第 2 章",
        "第 3 章",
        "第 4 章",
    ]


@pytest.mark.anyio
async def test_single_chapter_stream_retries_malformed_json_at_chapter_11(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = {
        "scale": {
            "volume_count": 1,
            "chapter_count": 11,
            "word_count_target": 55000,
        },
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "十一章大纲",
                    "children": [
                        {"node_type": "VOLUME", "title": "第一卷", "children": []}
                    ],
                }
            },
            "characters": [],
            "scenes": [],
        },
    }
    calls = []
    config = SimpleNamespace(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model_name="deepseek-v4-flash",
    )

    async def fake_get(*_args):
        return config

    async def fake_response(_config_id, messages, **kwargs):
        calls.append({"messages": deepcopy(messages), "kwargs": deepcopy(kwargs)})
        call_number = len(calls)
        if call_number == 11:
            return LLMResult(
                text='{"chapters":[{"title":"第 11 章"}',
                usage=LLMUsage(input_tokens=100, output_tokens=30),
            )
        chapter_index = call_number if call_number <= 10 else 11
        return LLMResult(
            text=json.dumps(
                {
                    "chapters": [
                        {
                            "volume_index": 1,
                            "title": f"第 {chapter_index} 章",
                            "summary": "推进主线",
                            "metadata": {},
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            usage=LLMUsage(input_tokens=100, output_tokens=30),
        )

    monkeypatch.setattr(
        "app.services.novel_agent_chat_service.llm_orchestrator.response",
        fake_response,
    )

    events = [
        event
        async for event in service._generate_chapters_stream(
            SimpleNamespace(get=fake_get),
            "config-1",
            state,
            batch_size=1,
        )
    ]

    assert len(calls) == 12
    assert all(call["kwargs"]["temperature"] == 0.2 for call in calls)
    assert "第 11 章结构化输出重试" in calls[-1]["messages"][-1]["content"]
    retry_progress = [
        event["progress"]
        for event in events
        if event["type"] == "progress"
        and "结构化输出异常" in event["progress"]["message"]
    ]
    assert len(retry_progress) == 1
    assert "第 11 章" in retry_progress[0]["message"]
    chapters = [
        event["artifact"]["data"]["children"][0]["children"]
        for event in events
        if event["type"] == "artifact"
    ][0]
    assert [chapter["title"] for chapter in chapters] == [
        f"第 {index} 章" for index in range(1, 12)
    ]


@pytest.mark.anyio
async def test_chapter_stream_exhausts_structured_retries_and_keeps_checkpoint(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = {
        "scale": {
            "volume_count": 1,
            "chapter_count": 11,
            "word_count_target": 55000,
        },
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "十一章大纲",
                    "children": [
                        {"node_type": "VOLUME", "title": "第一卷", "children": []}
                    ],
                }
            },
            "characters": [],
            "scenes": [],
        },
    }
    state["chapter_generation"] = {
        "signature": service._chapter_generation_signature(
            state, batch_size=1, revision=None
        ),
        "batch_size": 1,
        "revision": None,
        "chapters": [
            {
                "volume_index": 1,
                "title": f"第 {index} 章",
                "summary": "推进主线",
                "metadata": {},
            }
            for index in range(1, 11)
        ],
        "last_error": None,
    }
    calls = []
    checkpoints = []

    async def fake_request(*_args, **_kwargs):
        calls.append(1)
        raise NovelAgentStructuredOutputError(
            "chapters 阶段返回的内容不是完整合法 JSON"
        )

    async def fake_checkpoint(_db, _session, checkpoint, **_kwargs):
        checkpoints.append(deepcopy(checkpoint))

    monkeypatch.setattr(service, "_request_json", fake_request)
    monkeypatch.setattr(service, "_save_recovery_checkpoint", fake_checkpoint)

    with pytest.raises(
        NovelAgentOutputError,
        match=r"第 11 章.*连续 3 次.*已保存 10/11 章章节规划",
    ):
        async for _event in service._generate_chapters_stream(
            object(),
            "config-1",
            state,
            batch_size=1,
            session=SimpleNamespace(),
            resume_stage="chapter_scope",
            resume_answers={"q": {"option": {"id": "single"}}},
            resume_questions=[],
        ):
            pass

    assert len(calls) == CHAPTER_BATCH_MAX_ATTEMPTS
    assert len(checkpoints) == CHAPTER_BATCH_MAX_ATTEMPTS
    failed = checkpoints[-1]["chapter_generation"]
    assert len(failed["chapters"]) == 10
    assert failed["last_error"]["attempt"] == CHAPTER_BATCH_MAX_ATTEMPTS
    assert failed["last_error"]["retryable"] is True


@pytest.mark.anyio
async def test_chapter_scope_answer_connects_progress_stream_to_state(monkeypatch):
    service = NovelAgentChatService()
    state = {
        "stage": "chapter_scope",
        "selections": {},
        "scale": {"chapter_count": 3},
        "artifacts": {"outline": {}, "characters": [], "scenes": []},
    }
    artifact = {"title": "章节合同", "children": []}
    batch_sizes = []

    async def fake_stream(
        _db, _config_id, _state, batch_size, _revision=None, **_kwargs
    ):
        batch_sizes.append(batch_size)
        yield service._progress("chapters", "正在生成章节合同", 0, 3)
        yield service._artifact("chapters", "章节合同", artifact)

    async def fake_review(*_args, **_kwargs):
        if False:
            yield {}

    monkeypatch.setattr(service, "_generate_chapters_stream", fake_stream)
    monkeypatch.setattr(service, "_review_artifact", fake_review)
    events = [
        event
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            state,
            {
                "chapter-scope-question": {
                    "option": {"id": "batch", "value": {"batch_size": 2}}
                }
            },
            "config-1",
        )
    ]

    assert batch_sizes == [2]
    assert events[0]["type"] == "progress"
    assert events[0]["progress"]["step"] == "chapters"
    assert events[-1]["type"] == "artifact"
    assert state["artifacts"]["chapters"] == artifact


@pytest.mark.anyio
async def test_confirmed_chat_artifacts_are_materialized_incrementally_and_once():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            project = Project(name="旧钟测试项目")
            db.add(project)
            await db.flush()
            project_id = project.id
            state = {
                "artifacts": {
                    "outline": {
                        "project": {
                            "name": "旧钟",
                            "description": "时间从旧钟里泄漏。",
                            "genre": "奇幻悬疑",
                            "word_count_target": 5000,
                            "settings": {"theme": "时间与责任"},
                        },
                        "style_guide": "克制、清晰。",
                        "outline": {
                            "title": "旧钟分卷大纲",
                            "description": "围绕时间泄漏逐步升级。",
                            "children": [
                                {
                                    "node_type": "VOLUME",
                                    "title": "第一卷",
                                    "summary": "发现时间泄漏。",
                                    "metadata": {},
                                    "children": [],
                                }
                            ],
                        },
                    },
                    "characters": [
                        {
                            "name": "周明恕",
                            "role": "刑侦顾问",
                            "age": 39,
                            "desire": "让每条证据回到正确位置",
                            "fear": "再次错过关键时间证据",
                            "false_belief": "只要排序正确就必然得到正义",
                            "action_logic": "先固定时间锚点",
                            "speech_style": "以问句推进",
                            "growth_arc": "从独自举证到相信程序",
                        }
                    ],
                    "scenes": [
                        {
                            "name": "旧钟修理铺",
                            "location": "老城区",
                            "time": "深夜",
                            "atmosphere": "安静而压迫",
                            "description": "钟摆声逐渐错拍。",
                            "details": "墙上挂满停在不同时间的旧钟。",
                            "notes": "反复出现的核心场景",
                        }
                    ],
                },
                "confirmed": {
                    "outline": True,
                    "characters": True,
                    "scenes": True,
                },
                "scale": {"chapter_count": 1},
                "execution": {"chapter_results": []},
                "materialized_structure": {},
                "structure_created": False,
            }
            service = NovelAgentChatService()

            await service._sync_confirmed_artifacts(db, project_id, state)
            await service._sync_confirmed_artifacts(db, project_id, state)

            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Outline)
                    .where(Outline.project_id == project_id)
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Character)
                    .where(Character.project_id == project_id)
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count()).select_from(Scene).where(Scene.project_id == project_id)
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Chapter)
                    .where(Chapter.project_id == project_id)
                )
                == 0
            )

            character = await db.scalar(select(Character).where(Character.project_id == project_id))
            assert character is not None
            assert character.basic_info == {"role": "刑侦顾问", "age": 39}
            assert character.personality["desire"] == "让每条证据回到正确位置"
            assert character.personality["false_belief"] == ("只要排序正确就必然得到正义")
            assert character.growth_arc == {"development_direction": "从独自举证到相信程序"}

            state["artifacts"]["chapters"] = {
                "title": "旧钟章节合同",
                "description": "第一卷章节安排。",
                "children": [
                    {
                        "node_type": "VOLUME",
                        "title": "第一卷",
                        "summary": "发现时间泄漏。",
                        "metadata": {},
                        "children": [
                            {
                                "node_type": "CHAPTER",
                                "title": "第一章 停摆",
                                "summary": "修表匠发现整条街的钟同时停摆。",
                                "metadata": {
                                    "target_chars": 5000,
                                    "hook": "一只旧钟开始倒走",
                                },
                                "children": [],
                            }
                        ],
                    }
                ],
            }
            state["confirmed"]["chapters"] = True
            await service._sync_confirmed_artifacts(db, project_id, state)

            chapters = list(
                (
                    await db.execute(select(Chapter).where(Chapter.project_id == project_id))
                ).scalars()
            )
            assert len(chapters) == 1
            assert chapters[0].title == "第一章 停摆"
            assert chapters[0].summary == "修表匠发现整条街的钟同时停摆。"
            assert state["structure_created"] is True
            assert state["execution"]["chapter_ids"] == [chapters[0].id]
            chapter_node = await db.scalar(
                select(OutlineNode).where(OutlineNode.node_type == "CHAPTER")
            )
            assert chapter_node is not None
            assert chapter_node.metadata_["hook"] == "一只旧钟开始倒走"
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


def test_custom_direction_closes_volume_chapter_and_word_targets():
    scale = NovelAgentChatService._scale_from_answer(
        {
            "option": None,
            "custom_text": "我要一部 4 卷、32 章、48 万字的历史群像小说",
        }
    )

    assert scale["volume_count"] == 4
    assert scale["chapter_count"] == 32
    assert scale["word_count_target"] == 480000


def _foundation_fixture() -> dict:
    return {
        "project": {
            "name": "旧钟",
            "description": "时间从旧钟里泄漏。",
            "genre": "奇幻悬疑",
            "word_count_target": 300000,
            "settings": {
                "logline": "修表匠必须阻止城市失去时间。",
                "world_rules": ["时间只能被旧钟储存。"],
                "long_term_hooks": ["旧钟由谁制造"],
                "ending_direction": "主角决定归还被偷走的时间。",
            },
        },
        "style_guide": "克制、清晰，以可验证细节呈现异常。",
        "outline": {
            "title": "旧钟分卷大纲",
            "description": "围绕时间泄漏逐卷升级。",
            "children": [],
        },
    }


def _outline_state(volume_count: int = 3) -> dict:
    return {
        "idea": "一名修表匠发现时间会从旧钟里泄漏",
        "scale": {
            "volume_count": volume_count,
            "chapter_count": 30,
            "word_count_target": 300001,
            "direction": "奇幻悬疑",
        },
        "selections": {"direction": {"custom_text": "奇幻悬疑"}},
        "artifacts": {"foundation": _foundation_fixture()},
        "state_version": 3,
        "messages": [],
        "pending_questions": [],
        "confirmed": {"foundation": True},
        "structure_created": False,
        "result": None,
    }


def test_foundation_and_volume_normalizers_preserve_uncapped_creative_text():
    service = NovelAgentChatService()
    state = _outline_state()
    response = _foundation_fixture()
    response["project"]["name"] = "书" * 120
    response["project"]["description"] = "简介" * 900
    response["style_guide"] = "风" * 3000
    response["project"]["settings"].update(
        {
            "world_rules": [f"{index}" + "规" * 400 for index in range(10)],
            "narrative_rules": [f"{index}" + "叙" * 400 for index in range(10)],
            "continuity_rules": [f"{index}" + "连" * 400 for index in range(10)],
            "forbidden_moves": [f"{index}" + "禁" * 400 for index in range(10)],
        }
    )

    foundation = service._normalize_outline_foundation(response, state)
    volume = service._normalize_outline_volume(
        {
            "volume": {
                "node_type": "volume",
                "title": "卷" * 200,
                "summary": "摘要" * 1200,
                "metadata": {
                    "goal": "目标" * 400,
                    "must_reveal": [f"{index}" + "揭示" * 200 for index in range(9)],
                    "must_not_reveal": [f"{index}" + "保密" * 200 for index in range(9)],
                    "target_chars": 1,
                },
                "children": [{"node_type": "CHAPTER"}],
            }
        },
        index=1,
        target_chars=100001,
    )

    assert len(foundation["project"]["name"]) == 80
    assert foundation["project"]["description"] == "简介" * 900
    assert foundation["style_guide"] == "风" * 3000
    assert len(foundation["project"]["settings"]["world_rules"]) == 6
    assert all(len(item) > 160 for item in foundation["project"]["settings"]["narrative_rules"])
    assert foundation["outline"]["children"] == []
    assert volume["node_type"] == "VOLUME"
    assert len(volume["title"]) == 120
    assert volume["summary"] == "摘要" * 1200
    assert len(volume["metadata"]["must_reveal"]) == 4
    assert all(len(item) > 180 for item in volume["metadata"]["must_not_reveal"])
    assert volume["metadata"]["target_chars"] == 100001
    assert volume["children"] == []


@pytest.mark.parametrize("as_json_string", [False, True])
def test_foundation_normalizes_structured_style_guide_settings(as_json_string):
    service = NovelAgentChatService()
    state = _outline_state()
    response = _foundation_fixture()
    response["project"]["settings"].update(
        {
            "world_rules": ["项目中已经确认的世界规则"],
            "long_term_hooks": [],
            "ending_direction": "",
            "narrative_rules": ["项目中已经确认的叙事规则"],
            "continuity_rules": [],
            "forbidden_moves": [],
        }
    )
    structured_style_guide = {
        "settings": {
            "world_hard_rules": ["风格对象中的世界规则"],
            "long_term_foreshadowing": ["旧钟背面刻着失踪者姓名"],
            "ending_direction": ["主角归还时间", "城市重新开始计时"],
            "narrative_rules": ["风格对象中的叙事规则"],
            "continuity_rules": ["每章结束后更新时间状态"],
            "prohibited_areas": ["禁止用梦境解释时间异常"],
        }
    }
    response["style_guide"] = (
        json.dumps(structured_style_guide, ensure_ascii=False)
        if as_json_string
        else structured_style_guide
    )

    foundation = service._normalize_outline_foundation(response, state)
    settings = foundation["project"]["settings"]

    assert settings["world_rules"] == ["项目中已经确认的世界规则"]
    assert settings["long_term_hooks"] == ["旧钟背面刻着失踪者姓名"]
    assert settings["ending_direction"] == "- 主角归还时间\n- 城市重新开始计时"
    assert settings["narrative_rules"] == ["项目中已经确认的叙事规则"]
    assert settings["continuity_rules"] == ["每章结束后更新时间状态"]
    assert settings["forbidden_moves"] == ["禁止用梦境解释时间异常"]
    assert settings["style_guide"] == foundation["style_guide"]
    assert json.loads(foundation["style_guide"]) == structured_style_guide


def test_foundation_preserves_structured_style_guide_without_dict_repr():
    service = NovelAgentChatService()
    state = _outline_state()
    response = _foundation_fixture()
    response["style_guide"] = {
        "settings": {
            "world_hard_rules": ["时间只能被旧钟储存。"],
            "notes": "风" * 3000,
        }
    }

    foundation = service._normalize_outline_foundation(response, state)

    assert len(foundation["style_guide"]) > 1600
    assert "{'settings'" not in foundation["style_guide"]
    assert '"settings"' in foundation["style_guide"]
    assert json.loads(foundation["style_guide"]) == response["style_guide"]


def test_outline_part_schemas_leave_creative_text_uncapped():
    project = OUTLINE_FOUNDATION_RESPONSE_SCHEMA["properties"]["project"]
    settings = project["properties"]["settings"]["properties"]
    outline = OUTLINE_FOUNDATION_RESPONSE_SCHEMA["properties"]["outline"]
    volume = OUTLINE_VOLUME_RESPONSE_SCHEMA["properties"]["volume"]["properties"]
    metadata = volume["metadata"]["properties"]

    assert "maxLength" not in project["properties"]["description"]
    assert "maxLength" not in OUTLINE_FOUNDATION_RESPONSE_SCHEMA["properties"]["style_guide"]
    assert "maxLength" not in outline["properties"]["description"]
    assert outline["properties"]["children"]["items"] == {"type": "string"}
    assert settings["world_rules"]["maxItems"] == 6
    assert settings["world_rules"]["items"] == {"type": "string"}
    assert "maxLength" not in volume["summary"]
    assert metadata["must_reveal"]["maxItems"] == 4
    assert metadata["must_reveal"]["items"] == {"type": "string"}
    assert volume["children"]["items"] == {"type": "string"}


@pytest.mark.anyio
async def test_foundation_generation_uses_default_budget_and_repairs_shape(monkeypatch):
    service = NovelAgentChatService()
    state = _outline_state()
    calls = []
    instructions = []
    responses = iter([{}, _foundation_fixture()])

    async def fake_request(*args, **kwargs):
        calls.append(deepcopy(kwargs))
        instructions.append(args[4])
        return next(responses)

    monkeypatch.setattr(service, "_request_json", fake_request)

    foundation = await service._generate_outline_foundation(object(), "config-1", state)

    assert foundation["project"]["name"] == "旧钟"
    assert len(calls) == 2
    assert all(call["max_tokens"] == OUTLINE_FOUNDATION_MAX_TOKENS for call in calls)
    assert all(call["response_schema"] == OUTLINE_FOUNDATION_RESPONSE_SCHEMA for call in calls)
    assert calls[1]["dynamic_context_keys"] == ("validation_error",)
    assert all("不超过" not in instruction for instruction in instructions)
    assert all("7000 字以内" not in instruction for instruction in instructions)


@pytest.mark.anyio
async def test_outline_stream_checkpoints_each_volume_and_resumes_only_remaining(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = _outline_state(volume_count=3)
    calls = []
    checkpoints = []
    fail_second = True

    async def fake_volume(
        _db,
        _config_id,
        _state,
        _foundation,
        index,
        _previous,
        _revision,
    ):
        nonlocal fail_second
        calls.append(index)
        if index == 2 and fail_second:
            fail_second = False
            raise NovelAgentOutputError("第二卷结构错误")
        return service._normalize_outline_volume(
            {
                "volume": {
                    "title": f"第 {index} 卷",
                    "summary": f"推进第 {index} 阶段。",
                    "metadata": {},
                }
            },
            index=index,
            target_chars=service._volume_target_chars(state["scale"], index),
        )

    async def fake_checkpoint(_db, _session, checkpoint, **_kwargs):
        checkpoints.append(deepcopy(checkpoint))

    monkeypatch.setattr(service, "_generate_outline_volume", fake_volume)
    monkeypatch.setattr(service, "_save_recovery_checkpoint", fake_checkpoint)
    stream_kwargs = {
        "resume_stage": "foundation_review",
        "resume_answers": {"q": {"option": {"id": "accept"}}},
        "resume_questions": [],
    }

    with pytest.raises(NovelAgentOutputError, match="第二卷结构错误"):
        async for _event in service._generate_outline_stream(
            object(), "config-1", SimpleNamespace(), state, **stream_kwargs
        ):
            pass

    assert calls == [1, 2]
    assert len(state["outline_generation"]["volumes"]) == 1
    assert checkpoints[-1]["outline_generation"]["last_error"]["volume_index"] == 2
    state["outline_generation"]["volumes"][0]["summary"] = "过长" * 1000

    events = [
        event
        async for event in service._generate_outline_stream(
            object(), "config-1", SimpleNamespace(), state, **stream_kwargs
        )
    ]

    assert calls == [1, 2, 2, 3]
    assert "outline_generation" not in state
    assert len(state["artifacts"]["outline"]["outline"]["children"]) == 3
    assert state["artifacts"]["outline"]["outline"]["children"][0]["summary"] == "过长" * 1000
    assert (
        sum(
            item["metadata"]["target_chars"]
            for item in state["artifacts"]["outline"]["outline"]["children"]
        )
        == state["scale"]["word_count_target"]
    )
    assert [event["artifact"]["title"] for event in events if event["type"] == "artifact"][
        -1
    ] == "完整分卷级大纲"


@pytest.mark.anyio
async def test_outline_volume_generation_uses_schema_and_default_budget(monkeypatch):
    service = NovelAgentChatService()
    state = _outline_state(volume_count=1)
    calls = []
    instructions = []

    async def fake_request(*args, **kwargs):
        calls.append(deepcopy(kwargs))
        instructions.append(args[4])
        return {
            "volume": {
                "node_type": "VOLUME",
                "title": "第一卷",
                "summary": "主角确认时间泄漏的代价。",
                "metadata": {},
                "children": [],
            }
        }

    monkeypatch.setattr(service, "_request_json", fake_request)
    volume = await service._generate_outline_volume(
        object(),
        "config-1",
        state,
        state["artifacts"]["foundation"],
        1,
        [],
        None,
    )

    assert volume["node_type"] == "VOLUME"
    assert calls[0]["max_tokens"] == OUTLINE_VOLUME_MAX_TOKENS
    assert calls[0]["response_schema"] == OUTLINE_VOLUME_RESPONSE_SCHEMA
    assert "previous_volumes" in calls[0]["dynamic_context_keys"]
    assert "不超过" not in instructions[0]
    assert "4500 字以内" not in instructions[0]


def test_chapter_contracts_are_distributed_and_receive_target_chars():
    state = {
        "scale": {"chapter_count": 4, "word_count_target": 40000},
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "测试大纲",
                    "description": "",
                    "children": [
                        {
                            "node_type": "VOLUME",
                            "title": "第一卷",
                            "children": [],
                        },
                        {
                            "node_type": "VOLUME",
                            "title": "第二卷",
                            "children": [],
                        },
                    ],
                }
            }
        },
    }
    chapters = [
        {"volume_index": 1, "title": f"第{index}章", "summary": "推进"} for index in range(1, 5)
    ]

    outline = NovelAgentChatService._chapters_into_outline(state, chapters)
    saved = [chapter for volume in outline["children"] for chapter in volume["children"]]
    assert len(saved) == 4
    assert all(item["metadata"]["target_chars"] == 10000 for item in saved)
    assert all("pov" in item["metadata"] for item in saved)


def test_chapter_contracts_reject_volume_index_that_reorders_absolute_chapters():
    state = {
        "scale": {
            "volume_count": 2,
            "chapter_count": 60,
            "word_count_target": 360000,
        },
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "测试大纲",
                    "children": [
                        {"node_type": "VOLUME", "title": "第一卷", "children": []},
                        {"node_type": "VOLUME", "title": "第二卷", "children": []},
                    ],
                }
            }
        },
    }
    chapters = [
        {
            "chapter_index": index,
            "volume_index": 2 if index <= 30 else 1,
            "title": f"原第 {index} 章",
            "summary": "推进",
            "metadata": {},
        }
        for index in range(1, 61)
    ]

    with pytest.raises(NovelAgentStructuredOutputError, match="单调不减"):
        NovelAgentChatService._chapters_into_outline(state, chapters)


def test_chapter_contracts_preserve_absolute_indices_across_two_volumes():
    state = {
        "scale": {
            "volume_count": 2,
            "chapter_count": 60,
            "word_count_target": 360000,
        },
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "测试大纲",
                    "children": [
                        {"node_type": "VOLUME", "title": "第一卷", "children": []},
                        {"node_type": "VOLUME", "title": "第二卷", "children": []},
                    ],
                }
            }
        },
    }
    chapters = [
        {
            "chapter_index": index,
            "volume_index": 1 if index <= 30 else 2,
            "title": f"第 {index} 章",
            "summary": "推进",
            "metadata": {},
        }
        for index in range(1, 61)
    ]

    outline = NovelAgentChatService._chapters_into_outline(state, chapters)
    flattened = NovelAgentChatService._flatten_chapter_contracts(outline)

    assert [item["title"] for item in flattened] == [
        f"第 {index} 章" for index in range(1, 61)
    ]
    assert [item["metadata"]["chapter_index"] for item in flattened] == list(
        range(1, 61)
    )


def test_materialized_chapter_mapping_requires_exact_absolute_order():
    service = NovelAgentChatService()
    chapters = [
        SimpleNamespace(
            id="chapter-1",
            outline_node_id="node-1",
            title="第一章",
        ),
        SimpleNamespace(
            id="chapter-2",
            outline_node_id="node-2",
            title="第二章",
        ),
    ]
    state = {
        "artifacts": {
            "chapters": {
                "children": [
                    {
                        "children": [
                            {
                                "title": "第一章",
                                "metadata": {"chapter_index": 1},
                            },
                            {
                                "title": "第二章",
                                "metadata": {"chapter_index": 2},
                            },
                        ]
                    }
                ]
            }
        },
        "execution": {},
    }

    service._remember_materialized_chapters(state, chapters)

    assert state["execution"]["chapter_labels"] == [
        {
            "id": "chapter-1",
            "outline_node_id": "node-1",
            "title": "第一章",
            "order": 1,
            "chapter_index": 1,
        },
        {
            "id": "chapter-2",
            "outline_node_id": "node-2",
            "title": "第二章",
            "order": 2,
            "chapter_index": 2,
        },
    ]
    assert state["execution"]["chapter_contracts_by_id"]["chapter-1"]["title"] == (
        "第一章"
    )

    bad_order = deepcopy(state)
    bad_order["artifacts"]["chapters"]["children"][0]["children"][1]["metadata"][
        "chapter_index"
    ] = 3
    with pytest.raises(NovelAgentOutputError, match="绝对章序"):
        service._remember_materialized_chapters(bad_order, chapters)

    missing_contract = deepcopy(state)
    missing_contract["artifacts"]["chapters"]["children"][0]["children"].pop()
    with pytest.raises(NovelAgentOutputError, match="数量不一致"):
        service._remember_materialized_chapters(missing_contract, chapters)


def test_chapter_targets_are_clamped_and_rescaled_to_executable_book_total():
    state = {
        "scale": {"chapter_count": 3, "word_count_target": 30000},
        "artifacts": {
            "outline": {
                "outline": {
                    "title": "测试大纲",
                    "children": [{"node_type": "VOLUME", "title": "第一卷", "children": []}],
                }
            }
        },
    }
    chapters = [
        {
            "volume_index": 1,
            "title": f"第{index + 1}章",
            "summary": "推进",
            "metadata": {"target_chars": target},
        }
        for index, target in enumerate((20000, 1000, 1000))
    ]

    outline = NovelAgentChatService._chapters_into_outline(state, chapters)
    targets = [item["metadata"]["target_chars"] for item in outline["children"][0]["children"]]

    assert targets == [12000, 9000, 9000]
    assert sum(targets) == state["scale"]["word_count_target"]


def test_story_state_merges_actual_chapter_deltas_without_duplicate_facts():
    chapter = SimpleNamespace(id="chapter-2", title="第二章")
    current = {
        "confirmed_facts": ["林川拿到了钥匙"],
        "character_states": {
            "林川": {
                "location": "钟楼",
                "injury": "左手受伤",
                "knowledge": {"船长": "身份不明"},
            }
        },
        "object_states": {"钥匙": {"owner": "林川", "condition": "生锈"}},
        "open_threads": ["旧钟为何倒转"],
        "chapter_summaries": [],
    }
    delta = {
        "summary": "林川在码头确认钥匙属于失踪的船长。",
        "confirmed_facts": ["林川拿到了钥匙", "钥匙属于失踪船长"],
        "character_states": {"林川": {"location": "码头"}},
        "relationship_changes": [],
        "object_states": {"钥匙": {"owner": "船长"}},
        "opened_threads": ["船长去了哪里"],
        "resolved_threads": ["旧钟为何倒转"],
        "foreshadowing_updates": [],
        "story_clock": {"day": 2},
    }

    merged = NovelAgentChatService._merge_story_state(current, chapter, delta)

    assert merged["confirmed_facts"] == ["林川拿到了钥匙", "钥匙属于失踪船长"]
    assert merged["character_states"]["林川"]["location"] == "码头"
    assert merged["character_states"]["林川"]["injury"] == "左手受伤"
    assert merged["character_states"]["林川"]["knowledge"]["船长"] == "身份不明"
    assert merged["object_states"]["钥匙"] == {
        "owner": "船长",
        "condition": "生锈",
    }
    assert merged["open_threads"] == ["船长去了哪里"]
    assert merged["resolved_threads"] == ["旧钟为何倒转"]
    assert merged["after_chapter_id"] == "chapter-2"
    assert merged["chapter_summaries"][0]["summary"].startswith("林川在码头")


def _story_state_delta(marker):
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


def test_story_state_ledger_replays_only_chapters_before_target_out_of_order():
    service = NovelAgentChatService()
    state = _chapter_label_state(3)

    service._record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-3", title="第三章"),
        _story_state_delta("第三章"),
    )
    service._record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-1", title="第一章"),
        _story_state_delta("第一章"),
    )

    snapshot = service._story_state_before_chapter(state, "chapter-2")
    override = service._story_state_override(state, "chapter-2")

    assert snapshot["confirmed_facts"] == ["第一章事实"]
    assert [item["chapter_id"] for item in snapshot["chapter_summaries"]] == [
        "chapter-1"
    ]
    assert override is not None
    assert "第一章事实" in (override.previous_context or "")
    assert "第三章事实" not in (override.previous_context or "")


def test_story_state_ledger_accumulates_chapter_one_then_two():
    service = NovelAgentChatService()
    state = _chapter_label_state(3)

    for chapter_id, title in (("chapter-1", "第一章"), ("chapter-2", "第二章")):
        service._record_story_state_delta(
            state,
            SimpleNamespace(id=chapter_id, title=title),
            _story_state_delta(title),
        )

    snapshot = service._story_state_before_chapter(state, "chapter-3")

    assert snapshot["confirmed_facts"] == ["第一章事实", "第二章事实"]
    assert [item["chapter_id"] for item in snapshot["chapter_summaries"]] == [
        "chapter-1",
        "chapter-2",
    ]
    assert state["execution"]["story_state"] == snapshot


def test_story_state_ledger_rewrite_replaces_same_chapter_delta():
    service = NovelAgentChatService()
    state = _chapter_label_state(2)
    chapter = SimpleNamespace(id="chapter-1", title="第一章")

    service._record_story_state_delta(state, chapter, _story_state_delta("旧版第一章"))
    service._record_story_state_delta(state, chapter, _story_state_delta("新版第一章"))

    snapshot = service._story_state_before_chapter(state, "chapter-2")
    ledger = state["execution"]["story_state_deltas"]

    assert list(ledger) == ["chapter-1"]
    assert ledger["chapter-1"]["delta"]["summary"] == "新版第一章摘要"
    assert snapshot["confirmed_facts"] == ["新版第一章事实"]
    assert [item["summary"] for item in snapshot["chapter_summaries"]] == [
        "新版第一章摘要"
    ]


def test_story_state_ledger_merges_legacy_base_only_once():
    service = NovelAgentChatService()
    state = _chapter_label_state(3)
    legacy = {
        "schema_version": "story_state.v1",
        "after_chapter_id": "chapter-1",
        "after_chapter_title": "第一章",
        "confirmed_facts": ["第一章遗留事实"],
        "chapter_summaries": [
            {
                "chapter_id": "chapter-1",
                "title": "第一章",
                "summary": "第一章遗留摘要",
            }
        ],
    }
    state["execution"]["story_state"] = deepcopy(legacy)

    service._record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-2", title="第二章"),
        _story_state_delta("第二章"),
    )
    service._record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-3", title="第三章"),
        _story_state_delta("第三章"),
    )

    snapshot = state["execution"]["story_state"]

    assert state["execution"]["story_state_base"] == legacy
    assert list(state["execution"]["story_state_deltas"]) == [
        "chapter-2",
        "chapter-3",
    ]
    assert snapshot["confirmed_facts"] == [
        "第一章遗留事实",
        "第二章事实",
        "第三章事实",
    ]
    assert snapshot["confirmed_facts"].count("第一章遗留事实") == 1
    assert [item["chapter_id"] for item in snapshot["chapter_summaries"]] == [
        "chapter-1",
        "chapter-2",
        "chapter-3",
    ]


def test_story_state_ledger_invalidates_opaque_base_when_rewriting_earlier_chapter():
    service = NovelAgentChatService()
    state = _chapter_label_state(3)
    state["execution"]["story_state"] = {
        "schema_version": "story_state.v1",
        "after_chapter_id": "chapter-2",
        "after_chapter_title": "第二章",
        "confirmed_facts": ["旧版第一章事实", "第二章未来事实"],
        "chapter_summaries": [
            {
                "chapter_id": "chapter-2",
                "title": "第二章",
                "summary": "包含旧版第一章与第二章的不可拆分遗留快照",
            }
        ],
    }

    service._record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-1", title="第一章"),
        _story_state_delta("新版第一章"),
    )

    before_chapter_two = service._story_state_before_chapter(state, "chapter-2")
    aggregate = state["execution"]["story_state"]

    assert before_chapter_two["confirmed_facts"] == ["新版第一章事实"]
    assert [
        item["summary"] for item in before_chapter_two["chapter_summaries"]
    ] == ["新版第一章摘要"]
    assert aggregate["confirmed_facts"] == ["新版第一章事实"]
    assert [item["summary"] for item in aggregate["chapter_summaries"]] == [
        "新版第一章摘要"
    ]
    assert "story_state_base" not in state["execution"]


def test_story_state_override_is_target_relative_and_excludes_future_state():
    service = NovelAgentChatService()
    state = _chapter_label_state(3)
    state["execution"]["story_state"] = {
        "schema_version": "story_state.v1",
        "after_chapter_id": "chapter-1",
        "after_chapter_title": "第一章",
        "confirmed_facts": ["仅来自第一章的必要事实"],
    }

    override = service._story_state_override(state, "chapter-2")

    assert override is not None
    assert "仅来自第一章的必要事实" in (override.previous_context or "")
    assert service._story_state_override(state, "chapter-1") is None
    state["execution"]["story_state"]["after_chapter_id"] = "chapter-3"
    assert service._story_state_override(state, "chapter-2") is None
    state["execution"]["story_state"].pop("after_chapter_id")
    assert service._story_state_override(state, "chapter-2") is None


@pytest.mark.anyio
async def test_chat_write_uses_clean_chapter_context_without_duplicate_project_state(
    monkeypatch,
):
    service = NovelAgentChatService()
    chapter = SimpleNamespace(
        id="chapter-2",
        project_id="project-1",
        title="第二章",
        content="",
        word_count=0,
    )
    state = _chapter_label_state(3)
    state.update(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "对话历史污染标记不得进入正文上下文",
                }
            ],
            "artifacts": {
                "outline": {"style_guide": "克制、清晰。"},
                "unrelated": "其他阶段产物污染标记",
            },
        }
    )
    state["execution"]["story_state"] = {
        "schema_version": "story_state.v1",
        "after_chapter_id": "chapter-1",
        "confirmed_facts": ["第一章实际状态锚点"],
    }
    captured = {}

    async def fake_get(model, item_id):
        if model is Chapter and item_id == chapter.id:
            return chapter
        return None

    async def fake_novel_write(
        _db,
        _config_id,
        _project_id,
        _chapter_id,
        **kwargs,
    ):
        captured.update(kwargs)
        return {"content": "第二章正文", "word_count": 5}

    async def fake_extract(*_args, **_kwargs):
        raise RuntimeError("状态提取不影响已生成正文")

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )
    monkeypatch.setattr(service, "_extract_story_state", fake_extract)

    result = await service._write_chapter_pipeline(
        SimpleNamespace(get=fake_get),
        "project-1",
        "config-1",
        chapter.id,
        state,
        {"consistency": False, "polish": False},
    )

    assert result["content"] == "第二章正文"
    assert captured["include_project_story_state"] is False
    assert captured["allow_entity_fallback"] is False
    override = captured["overrides"]
    assert override is not None
    assert "第一章实际状态锚点" in (override.previous_context or "")
    assert "对话历史污染标记" not in (override.previous_context or "")
    assert "其他阶段产物污染标记" not in (override.previous_context or "")


@pytest.mark.anyio
async def test_chat_write_and_state_extraction_share_target_before_snapshot(
    monkeypatch,
):
    service = NovelAgentChatService()
    chapter = SimpleNamespace(
        id="chapter-2",
        project_id="project-1",
        title="第二章",
        content="",
        word_count=0,
    )
    state = _chapter_label_state(3)
    state["artifacts"] = {"outline": {"style_guide": "克制、清晰。"}}
    service._record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-3", title="第三章"),
        _story_state_delta("第三章"),
    )
    service._record_story_state_delta(
        state,
        SimpleNamespace(id="chapter-1", title="第一章"),
        _story_state_delta("第一章"),
    )
    expected = service._story_state_before_chapter(state, chapter.id)
    captured = {}

    async def fake_get(model, item_id):
        if model is Chapter and item_id == chapter.id:
            return chapter
        return None

    async def fake_novel_write(
        _db,
        _config_id,
        _project_id,
        _chapter_id,
        **kwargs,
    ):
        captured["write_override"] = kwargs["overrides"]
        return {"content": "第二章实际正文", "word_count": 8}

    async def fake_extract(
        _db,
        _config_id,
        _state,
        _chapter,
        _content,
        *,
        previous_story_state=None,
    ):
        captured["extract_snapshot"] = deepcopy(previous_story_state)
        return _story_state_delta("第二章")

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )
    monkeypatch.setattr(service, "_extract_story_state", fake_extract)

    result = await service._write_chapter_pipeline(
        SimpleNamespace(get=fake_get),
        "project-1",
        "config-1",
        chapter.id,
        state,
        {"consistency": False, "polish": False},
    )

    override = captured["write_override"]
    prompt_snapshot = json.loads((override.previous_context or "").split("\n", 1)[1])
    assert prompt_snapshot == captured["extract_snapshot"] == expected
    assert prompt_snapshot["confirmed_facts"] == ["第一章事实"]
    assert "第三章事实" not in json.dumps(prompt_snapshot, ensure_ascii=False)
    assert result["story_state_updated"] is True


@pytest.mark.anyio
async def test_failed_state_extraction_after_rewrite_clears_stale_chapter_delta(
    monkeypatch,
):
    service = NovelAgentChatService()
    chapter = SimpleNamespace(
        id="chapter-2",
        project_id="project-1",
        title="第二章",
        content="第二章旧正文",
        word_count=7,
    )
    state = _chapter_label_state(3)
    state["artifacts"] = {"outline": {"style_guide": "克制、清晰。"}}
    state["execution"]["story_state_deltas"] = {
        "chapter-1": {
            "chapter_id": "chapter-1",
            "chapter_title": "第一章",
            "delta": _story_state_delta("第一章"),
        },
        "chapter-2": {
            "chapter_id": "chapter-2",
            "chapter_title": "第二章",
            "delta": _story_state_delta("第二章旧版"),
        },
    }
    state["execution"]["story_state"] = service._story_state_before_order(state, 4)
    persisted = []

    async def fake_get(model, item_id):
        if model is Chapter and item_id == chapter.id:
            return chapter
        return None

    async def fake_save_version(*_args, **_kwargs):
        return None

    async def fake_novel_write(*_args, **_kwargs):
        chapter.content = "第二章重写后的正文"
        chapter.word_count = 10
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def failed_extract(*_args, **_kwargs):
        raise RuntimeError("状态提取失败")

    async def capture_persist(_db, _project_id, story_state):
        persisted.append(deepcopy(story_state))

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.save_version",
        fake_save_version,
    )
    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )
    monkeypatch.setattr(service, "_extract_story_state", failed_extract)
    monkeypatch.setattr(service, "_persist_project_story_state", capture_persist)

    result = await service._write_chapter_pipeline(
        SimpleNamespace(get=fake_get),
        "project-1",
        "config-1",
        chapter.id,
        state,
        {"consistency": False, "polish": False},
    )

    aggregate = state["execution"]["story_state"]
    assert result["content"] == "第二章重写后的正文"
    assert result["story_state_updated"] is False
    assert "chapter-2" not in state["execution"]["story_state_deltas"]
    assert aggregate["confirmed_facts"] == ["第一章事实"]
    assert "第二章旧版事实" not in json.dumps(aggregate, ensure_ascii=False)
    assert persisted == [aggregate]


@pytest.mark.anyio
async def test_failed_state_extraction_after_rewrite_clears_opaque_legacy_base(
    monkeypatch,
):
    service = NovelAgentChatService()
    chapter = SimpleNamespace(
        id="chapter-2",
        project_id="project-1",
        title="第二章",
        content="第二章旧正文",
        word_count=7,
    )
    state = _chapter_label_state(3)
    state["artifacts"] = {"outline": {"style_guide": "克制、清晰。"}}
    opaque_base = {
        "schema_version": "story_state.v1",
        "after_chapter_id": "chapter-2",
        "after_chapter_title": "第二章",
        "confirmed_facts": ["不可拆分的旧事实", "第二章旧版事实"],
        "chapter_summaries": [
            {
                "chapter_id": "chapter-2",
                "title": "第二章",
                "summary": "截至第二章的旧聚合摘要",
            }
        ],
    }
    state["execution"].update(
        {
            "story_state_base": deepcopy(opaque_base),
            "story_state_deltas": {
                "chapter-1": {
                    "chapter_id": "chapter-1",
                    "chapter_title": "第一章",
                    "delta": _story_state_delta("第一章可归因"),
                },
                "chapter-2": {
                    "chapter_id": "chapter-2",
                    "chapter_title": "第二章",
                    "delta": _story_state_delta("第二章旧版"),
                },
            },
            "story_state": deepcopy(opaque_base),
        }
    )
    persisted = []

    async def fake_get(model, item_id):
        if model is Chapter and item_id == chapter.id:
            return chapter
        return None

    async def fake_save_version(*_args, **_kwargs):
        return None

    async def fake_novel_write(*_args, **_kwargs):
        chapter.content = "第二章重写后的正文"
        chapter.word_count = 10
        return {"content": chapter.content, "word_count": chapter.word_count}

    async def failed_extract(*_args, **_kwargs):
        raise RuntimeError("状态提取失败")

    async def capture_persist(_db, _project_id, story_state):
        persisted.append(deepcopy(story_state))

    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.save_version",
        fake_save_version,
    )
    monkeypatch.setattr(
        "app.services.agent_chapter_pipeline_service.chapter_service.novel_write",
        fake_novel_write,
    )
    monkeypatch.setattr(service, "_extract_story_state", failed_extract)
    monkeypatch.setattr(service, "_persist_project_story_state", capture_persist)

    result = await service._write_chapter_pipeline(
        SimpleNamespace(get=fake_get),
        "project-1",
        "config-1",
        chapter.id,
        state,
        {"consistency": False, "polish": False},
    )

    aggregate = state["execution"]["story_state"]
    assert result["content"] == "第二章重写后的正文"
    assert result["story_state_updated"] is False
    assert "story_state_base" not in state["execution"]
    assert "chapter-2" not in state["execution"]["story_state_deltas"]
    assert aggregate["confirmed_facts"] == ["第一章可归因事实"]
    assert "旧事实" not in json.dumps(aggregate, ensure_ascii=False)
    assert persisted == [aggregate]


def test_llm_usage_tracks_cached_token_hit_ratio():
    state = {}
    NovelAgentChatService._record_usage(
        state,
        "outline",
        {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cached_input_tokens": 600,
            "reasoning_tokens": 50,
        },
    )
    NovelAgentChatService._record_usage(
        state,
        "outline_review",
        {
            "input_tokens": 500,
            "output_tokens": 50,
            "cached_input_tokens": 300,
            "reasoning_tokens": 10,
        },
    )

    assert state["llm_usage"]["input_tokens"] == 1500
    assert state["llm_usage"]["cached_input_tokens"] == 900
    assert state["llm_usage"]["cache_hit_ratio"] == 0.6


@pytest.mark.anyio
async def test_request_json_retries_one_blank_response_and_records_both_usages(
    monkeypatch,
):
    service = NovelAgentChatService()
    usage_state = {}
    calls = []
    results = iter(
        [
            LLMResult(
                text=" \n\t",
                usage=LLMUsage(input_tokens=10, output_tokens=3),
            ),
            LLMResult(
                text='{"project":{"name":"重试成功"}}',
                usage=LLMUsage(input_tokens=12, output_tokens=7),
            ),
        ]
    )

    async def fake_response(_config_id, messages, **_kwargs):
        calls.append(deepcopy(messages))
        return next(results)

    async def fake_get(*_args):
        return None

    monkeypatch.setattr(
        "app.services.novel_agent_chat_service.llm_orchestrator.response",
        fake_response,
    )

    parsed = await service._request_json(
        SimpleNamespace(get=fake_get),
        "config-1",
        "outline",
        {"idea": "旧钟里的时间"},
        "返回 project 对象",
        max_tokens=12000,
        usage_state=usage_state,
    )

    assert parsed == {"project": {"name": "重试成功"}}
    assert len(calls) == 2
    assert calls[1][:-1] == calls[0]
    assert calls[1][-1]["role"] == "user"
    assert "outline 阶段空响应重试" in calls[1][-1]["content"]
    assert "合法的 JSON 对象" in calls[1][-1]["content"]
    assert usage_state["llm_usage"]["input_tokens"] == 22
    assert usage_state["llm_usage"]["output_tokens"] == 10
    assert len(usage_state["llm_usage"]["calls"]) == 2


@pytest.mark.anyio
async def test_chapter_request_reports_blank_response_to_batch_retry(monkeypatch):
    service = NovelAgentChatService()
    call_count = 0

    async def fake_response(_config_id, _messages, **_kwargs):
        nonlocal call_count
        call_count += 1
        return LLMResult(text="", usage=LLMUsage())

    async def fake_get(*_args):
        return None

    monkeypatch.setattr(
        "app.services.novel_agent_chat_service.llm_orchestrator.response",
        fake_response,
    )

    with pytest.raises(NovelAgentStructuredOutputError, match="返回空内容"):
        await service._request_json(
            SimpleNamespace(get=fake_get),
            "config-1",
            "chapters",
            {},
            "返回章节合同 JSON",
            max_tokens=11000,
        )

    assert call_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-v4-pro"])
async def test_request_json_expands_deepseek_v4_output_budget(monkeypatch, model):
    service = NovelAgentChatService()
    captured = {}
    usage_state = {}
    config = SimpleNamespace(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model_name=model,
    )

    async def fake_response(_config_id, _messages, **kwargs):
        captured.update(kwargs)
        return LLMResult(
            text='{"ok":true}',
            usage=LLMUsage(input_tokens=3, output_tokens=2),
        )

    async def fake_get(*_args):
        return config

    monkeypatch.setattr(
        "app.services.novel_agent_chat_service.llm_orchestrator.response",
        fake_response,
    )

    parsed = await service._request_json(
        SimpleNamespace(get=fake_get),
        "config-1",
        "outline_volume",
        {},
        "返回 JSON 对象",
        max_tokens=OUTLINE_VOLUME_MAX_TOKENS,
        usage_state=usage_state,
    )

    assert parsed == {"ok": True}
    assert captured["max_tokens"] == DEEPSEEK_V4_MAX_OUTPUT_TOKENS
    assert "api_mode" not in captured
    assert usage_state["llm_usage"]["calls"][0]["max_tokens"] == DEEPSEEK_V4_MAX_OUTPUT_TOKENS


@pytest.mark.anyio
async def test_request_json_reports_stage_after_two_blank_responses(monkeypatch):
    service = NovelAgentChatService()
    usage_state = {}
    calls = []
    results = iter(
        [
            LLMResult(text="", usage=LLMUsage(input_tokens=4, output_tokens=1)),
            LLMResult(text="\t", usage=LLMUsage(input_tokens=5, output_tokens=2)),
        ]
    )

    async def fake_response(_config_id, messages, **_kwargs):
        calls.append(messages)
        return next(results)

    async def fake_get(*_args):
        return None

    monkeypatch.setattr(
        "app.services.novel_agent_chat_service.llm_orchestrator.response",
        fake_response,
    )

    with pytest.raises(
        NovelAgentOutputError,
        match="outline 阶段连续两次返回空内容",
    ):
        await service._request_json(
            SimpleNamespace(get=fake_get),
            "config-1",
            "outline",
            {},
            "返回 JSON 对象",
            max_tokens=12000,
            usage_state=usage_state,
        )

    assert len(calls) == 2
    assert len(usage_state["llm_usage"]["calls"]) == 2
    assert [item["total_tokens"] for item in usage_state["llm_usage"]["calls"]] == [5, 7]


@pytest.mark.anyio
async def test_request_json_does_not_retry_nonempty_invalid_json(monkeypatch):
    service = NovelAgentChatService()
    usage_state = {}
    call_count = 0

    async def fake_response(_config_id, _messages, **_kwargs):
        nonlocal call_count
        call_count += 1
        return LLMResult(
            text="not-json",
            usage=LLMUsage(input_tokens=6, output_tokens=2),
        )

    async def fake_get(*_args):
        return None

    monkeypatch.setattr(
        "app.services.novel_agent_chat_service.llm_orchestrator.response",
        fake_response,
    )

    with pytest.raises(NovelAgentStructuredOutputError, match="合法 JSON"):
        await service._request_json(
            SimpleNamespace(get=fake_get),
            "config-1",
            "outline",
            {},
            "返回 JSON 对象",
            max_tokens=12000,
            usage_state=usage_state,
        )

    assert call_count == 1
    assert len(usage_state["llm_usage"]["calls"]) == 1


@pytest.mark.anyio
async def test_request_json_wraps_non_object_as_structured_output_error(monkeypatch):
    service = NovelAgentChatService()

    async def fake_response(_config_id, _messages, **_kwargs):
        return LLMResult(
            text='["not", "an", "object"]',
            usage=LLMUsage(input_tokens=4, output_tokens=4),
        )

    async def fake_get(*_args):
        return None

    monkeypatch.setattr(
        "app.services.novel_agent_chat_service.llm_orchestrator.response",
        fake_response,
    )

    with pytest.raises(
        NovelAgentStructuredOutputError,
        match="chapters 阶段未返回 JSON 对象",
    ):
        await service._request_json(
            SimpleNamespace(get=fake_get),
            "config-1",
            "chapters",
            {},
            "返回 JSON 对象",
            max_tokens=12000,
        )


def test_extract_json_skips_invalid_brace_prefix_and_honors_braces_in_strings():
    parsed = novel_agent_service._extract_json(
        '说明 {not-json} 后续 {"chapters":[{"summary":"保留 } 和 { 字符"}]} 尾注'
    )

    assert parsed == {"chapters": [{"summary": "保留 } 和 { 字符"}]}


def test_extract_json_never_recovers_inner_object_from_truncated_outer_json():
    with pytest.raises(json.JSONDecodeError):
        novel_agent_service._extract_json(
            '{"chapters":[{"title":"第 11 章"}'
        )

    with pytest.raises(json.JSONDecodeError):
        novel_agent_service._extract_json(
            '[{"chapters":[]}'
        )


def test_extract_json_handles_escaped_quotes_and_backslashes_in_strings():
    parsed = novel_agent_service._extract_json(
        '说明 {"summary":"保留 { }、\\\"引号\\\" 和 \\\\ 路径"} 尾注'
    )

    assert parsed == {"summary": '保留 { }、"引号" 和 \\ 路径'}


@pytest.mark.anyio
async def test_request_json_normalizes_malformed_json_parser_error(monkeypatch):
    service = NovelAgentChatService()

    async def fake_response(_config_id, _messages, **_kwargs):
        return LLMResult(text='{"project":', usage=LLMUsage())

    async def fake_get(*_args):
        return None

    monkeypatch.setattr(
        "app.services.novel_agent_chat_service.llm_orchestrator.response",
        fake_response,
    )

    with pytest.raises(NovelAgentOutputError, match="不是完整合法 JSON"):
        await service._request_json(
            SimpleNamespace(get=fake_get),
            "config-1",
            "foundation",
            {},
            "返回 JSON 对象",
            max_tokens=OUTLINE_FOUNDATION_MAX_TOKENS,
        )


def test_chapter_contract_lookup_uses_persisted_chapter_id_before_title():
    state = {
        "execution": {
            "chapter_contracts_by_id": {"chapter-2": {"title": "同名章", "summary": "第二个合同"}}
        },
        "artifacts": {
            "chapters": {
                "children": [
                    {
                        "children": [
                            {"title": "同名章", "summary": "第一个合同"},
                            {"title": "同名章", "summary": "第二个合同"},
                        ]
                    }
                ]
            }
        },
    }

    contract = NovelAgentChatService._chapter_plan(state, "chapter-2", "同名章")

    assert contract["summary"] == "第二个合同"


@pytest.mark.anyio
async def test_first_chat_turn_persists_model_authored_question(monkeypatch):
    service = NovelAgentChatService()
    session = SimpleNamespace(request_payload=None)
    saved = []

    async def fake_save(_db, _session, state, **_kwargs):
        saved.append(state.copy())

    async def fake_direction(_db, _config_id, state):
        return service._fallback_question("direction", state["state_version"] + 1, state)

    monkeypatch.setattr(service, "_save", fake_save)
    monkeypatch.setattr(service, "_direction_question", fake_direction)
    request = NovelAgentChatTurnRequest(
        llm_config_id="config-1", message="一名修表匠发现时间会从旧钟里泄漏"
    )

    events = [
        event async for event in service.handle_turn_stream(object(), "project-1", session, request)
    ]

    assert any(event["type"] == "question" for event in events)
    assert any(
        item["stage"] == "resume" and item["inflight_turn"]["resume_stage"] == "intake"
        for item in saved
    )
    assert saved[-1]["stage"] == "direction"
    assert saved[-1]["idea"] == "一名修表匠发现时间会从旧钟里泄漏"
    assert len(saved[-1]["pending_questions"][0]["options"]) == 3


@pytest.mark.anyio
async def test_recovery_redo_restores_original_questions_with_fresh_ids(monkeypatch):
    service = NovelAgentChatService()
    state = {
        "state_version": 2,
        "stage": "character_scope",
        "messages": [],
        "pending_questions": [],
        "artifacts": {},
        "structure_created": False,
        "result": None,
    }
    service._set_questions(
        state,
        "character_scope",
        [service._fallback_question("character_scope", 3, state)],
    )
    original_questions = deepcopy(state["pending_questions"])
    original_id = original_questions[0]["id"]
    saved = []

    async def fake_save(_db, _session, checkpoint, **_kwargs):
        saved.append(deepcopy(checkpoint))

    monkeypatch.setattr(service, "_save", fake_save)
    await service._save_recovery_checkpoint(
        object(),
        SimpleNamespace(),
        state,
        resume_stage="character_scope",
        answers={original_id: {"custom_text": "四人核心组"}},
        resume_questions=original_questions,
    )
    checkpoint = saved[-1]
    recovery = checkpoint["pending_questions"][0]
    redo = recovery["options"][1]
    events = [
        event
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            checkpoint,
            {
                recovery["id"]: {
                    "option": redo,
                    "custom_text": None,
                }
            },
            "config-1",
        )
    ]

    assert checkpoint["stage"] == "character_scope"
    assert checkpoint["pending_questions"][0]["id"] != original_id
    assert events[0]["type"] == "question"


@pytest.mark.anyio
async def test_chapter_recovery_redo_discards_partial_plan_and_restores_question(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = {
        "state_version": 2,
        "stage": "chapter_scope",
        "messages": [],
        "pending_questions": [],
        "artifacts": {},
        "scale": {"chapter_count": 3},
        "chapter_generation": {
            "signature": "saved-plan",
            "batch_size": 1,
            "revision": None,
            "chapters": [{"title": "第一章"}],
            "last_error": {"start": 2, "count": 1, "message": "连接中断"},
        },
        "structure_created": False,
        "result": None,
    }
    service._set_questions(
        state,
        "chapter_scope",
        [service._fallback_question("chapter_scope", 3, state)],
    )
    original_questions = deepcopy(state["pending_questions"])
    original_id = original_questions[0]["id"]
    saved = []

    async def fake_save(_db, _session, checkpoint, **_kwargs):
        saved.append(deepcopy(checkpoint))

    monkeypatch.setattr(service, "_save", fake_save)
    await service._save_recovery_checkpoint(
        object(),
        SimpleNamespace(),
        state,
        resume_stage="chapter_scope",
        answers={original_id: {"option": {"id": "single"}}},
        resume_questions=original_questions,
    )

    checkpoint = saved[-1]
    recovery = checkpoint["pending_questions"][0]
    assert "已保存 1/3" in recovery["question"]
    redo = recovery["options"][1]
    events = [
        event
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            checkpoint,
            {recovery["id"]: {"option": redo, "custom_text": None}},
            "config-1",
        )
    ]

    assert "chapter_generation" not in checkpoint
    assert checkpoint["stage"] == "chapter_scope"
    assert checkpoint["pending_questions"][0]["id"] != original_id
    assert checkpoint["pending_questions"][0]["question"] == original_questions[0]["question"]
    assert events == [
        {"type": "question", "question": checkpoint["pending_questions"][0]}
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["continue", "redo"])
async def test_write_scope_recovery_always_reasks_deterministic_range(action):
    service = NovelAgentChatService()
    state = _chapter_label_state()
    state.update(
        {
            "stage": "write_scope",
            "messages": [],
            "pending_questions": [],
            "artifacts": {},
            "selections": {},
            "confirmed": {},
            "quality_policy": {},
            "structure_created": True,
            "result": None,
        }
    )
    old_question = service._fallback_question("write_scope", 8, state)
    old_question["id"] = "write_scope:8:1"
    old_question["state_version"] = 8
    state["inflight_turn"] = {
        "resume_stage": "write_scope",
        "answers": {
            "write_scope:8:1": {
                "option": {
                    "id": "multiple",
                    "value": {"mode": "multiple", "count": 5},
                },
                "custom_text": None,
            }
        },
        "questions": [old_question],
    }
    service._set_questions(
        state,
        "resume",
        [service._recovery_question(state["state_version"] + 1, state)],
    )
    recovery = state["pending_questions"][0]
    selected = next(item for item in recovery["options"] if item["id"] == action)

    events = [
        event
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            state,
            {recovery["id"]: {"option": selected, "custom_text": None}},
            "config-1",
        )
    ]

    assert state["stage"] == "write_scope"
    assert "inflight_turn" not in state
    assert "pending_chapter_ids" not in state["execution"]
    question = state["pending_questions"][0]
    assert "第 1-5 章" in question["options"][0]["description"]
    assert events == [{"type": "question", "question": question}]


@pytest.mark.anyio
async def test_direction_failure_can_resume_into_foundation_review(monkeypatch):
    service = NovelAgentChatService()
    state = {
        "schema_version": "novel.agent.chat.v1",
        "state_version": 0,
        "stage": "intake",
        "idea": "雪夜孤宅中的密室疑案",
        "messages": [],
        "pending_questions": [],
        "artifacts": {},
        "confirmed": {},
        "selections": {},
        "scale": {},
        "quality_policy": {},
        "execution": {"chapter_results": []},
        "structure_created": False,
        "result": None,
    }
    service._set_questions(
        state,
        "direction",
        [service._fallback_question("direction", 1, state)],
    )
    original_questions = deepcopy(state["pending_questions"])
    direction_option = original_questions[0]["options"][0]
    direction_answers = {
        original_questions[0]["id"]: {
            "option": direction_option,
            "custom_text": None,
        }
    }
    saved = []
    foundation_calls = 0

    async def fake_save(_db, _session, checkpoint, **_kwargs):
        saved.append(deepcopy(checkpoint))

    async def fake_foundation(_db, _config_id, _state, _revision=None):
        nonlocal foundation_calls
        foundation_calls += 1
        if foundation_calls == 1:
            raise RuntimeError("upstream rejected schema")
        return _foundation_fixture()

    async def fake_review_question(_db, _config_id, review_state, artifact_name, _label):
        return service._fallback_question(
            f"{artifact_name}_review",
            review_state["state_version"] + 1,
            review_state,
        )

    monkeypatch.setattr(service, "_save", fake_save)
    monkeypatch.setattr(service, "_generate_outline_foundation", fake_foundation)
    monkeypatch.setattr(service, "_review_question", fake_review_question)

    await service._save_recovery_checkpoint(
        object(),
        SimpleNamespace(),
        state,
        resume_stage="direction",
        answers=direction_answers,
        resume_questions=original_questions,
    )
    checkpoint = saved[-1]

    with pytest.raises(RuntimeError, match="rejected schema"):
        async for _event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            state,
            direction_answers,
            "config-1",
            answered_questions=original_questions,
        ):
            pass

    recovery_question = checkpoint["pending_questions"][0]
    continue_option = recovery_question["options"][0]
    events = [
        event
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            checkpoint,
            {
                recovery_question["id"]: {
                    "option": continue_option,
                    "custom_text": None,
                }
            },
            "config-1",
        )
    ]

    assert foundation_calls == 2
    assert checkpoint["stage"] == "foundation_review"
    assert checkpoint["artifacts"]["foundation"]["project"]["name"] == "旧钟"
    assert any(event["type"] == "artifact" for event in events)
    assert events[-1]["type"] == "question"


@pytest.mark.anyio
async def test_quality_artifact_is_emitted_and_recoverable_before_first_write(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = {
        "state_version": 5,
        "stage": "quality_gate",
        "messages": [],
        "pending_questions": [],
        "artifacts": {},
        "structure_created": False,
        "result": None,
        "execution": {
            "pending_chapter_ids": ["chapter-1", "chapter-2"],
            "chapter_results": [],
        },
    }
    answers = {
        "quality_gate:5:1": {"option": {"id": "yes", "value": {"enabled": True}}},
        "quality_gate:5:2": {"option": {"id": "no", "value": {"enabled": False}}},
        "quality_gate:5:3": {"option": {"id": "batch", "value": {"scope": "batch"}}},
    }
    saved = []

    async def fake_pipeline(*_args, **_kwargs):
        raise NovelAgentOutputError("首章模型失败")

    async def fake_save(_db, _session, checkpoint, **_kwargs):
        saved.append(deepcopy(checkpoint))

    monkeypatch.setattr(service, "_write_chapter_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_save", fake_save)

    events = []
    with pytest.raises(NovelAgentOutputError, match="首章模型失败"):
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            state,
            answers,
            "config-1",
        ):
            events.append(event)

    quality = {
        "consistency_analysis": "启用",
        "automatic_polish": "关闭",
        "application_scope": "整批执行",
        "target_chapter_count": 2,
    }
    assert events[0] == {
        "type": "artifact",
        "artifact": {"stage": "quality", "title": "质量策略", "data": quality},
    }
    assert events[1]["type"] == "message"
    assert events[1]["message"]["kind"] == "artifact_preview"
    assert events[1]["message"]["payload"] == {"artifact": "quality"}
    assert events[2]["type"] == "progress"
    assert events[2]["progress"]["step"] == "write"
    assert saved[0]["stage"] == "resume"
    assert saved[0]["artifacts"]["quality"] == quality
    assert saved[0]["messages"][-1] == events[1]["message"]


@pytest.mark.anyio
async def test_batch_failure_keeps_remaining_chapters_in_recovery_checkpoint(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = {
        "state_version": 5,
        "stage": "quality_gate",
        "messages": [],
        "pending_questions": [],
        "artifacts": {},
        "structure_created": False,
        "result": None,
        "execution": {
            "pending_chapter_ids": ["chapter-1", "chapter-2"],
            "chapter_results": [],
        },
    }
    answers = {
        "quality_gate:5:1": {"option": {"id": "yes", "value": {"enabled": True}}},
        "quality_gate:5:2": {"option": {"id": "yes", "value": {"enabled": True}}},
        "quality_gate:5:3": {"option": {"id": "batch", "value": {"scope": "batch"}}},
    }
    saved = []

    async def fake_pipeline(_db, _project_id, _config_id, chapter_id, _state, _policy):
        if chapter_id == "chapter-2":
            raise NovelAgentOutputError("第二章模型失败")
        return {"kind": "chapter", "chapter_id": chapter_id}

    async def fake_save(_db, _session, checkpoint, **_kwargs):
        saved.append(deepcopy(checkpoint))

    monkeypatch.setattr(service, "_write_chapter_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_save", fake_save)

    with pytest.raises(NovelAgentOutputError, match="第二章模型失败"):
        async for _event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            state,
            answers,
            "config-1",
        ):
            pass

    checkpoint = saved[-1]
    assert checkpoint["stage"] == "resume"
    assert checkpoint["inflight_turn"]["resume_stage"] == "quality_gate"
    assert checkpoint["execution"]["pending_chapter_ids"] == ["chapter-2"]


@pytest.mark.anyio
async def test_per_chapter_approval_saves_next_questions_without_reusing_answers(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = {
        "state_version": 5,
        "stage": "quality_gate",
        "messages": [],
        "pending_questions": [],
        "artifacts": {},
        "structure_created": False,
        "result": None,
        "execution": {
            "pending_chapter_ids": ["chapter-1", "chapter-2"],
            "chapter_results": [],
        },
    }
    answers = {
        "quality_gate:5:1": {"option": {"id": "yes", "value": {"enabled": True}}},
        "quality_gate:5:2": {"option": {"id": "yes", "value": {"enabled": True}}},
        "quality_gate:5:3": {"option": {"id": "each", "value": {"scope": "each"}}},
    }
    saved = []

    async def fake_pipeline(_db, _project_id, _config_id, chapter_id, _state, _policy):
        return {"kind": "chapter", "chapter_id": chapter_id}

    async def fake_save(_db, _session, checkpoint, **_kwargs):
        saved.append(deepcopy(checkpoint))

    monkeypatch.setattr(service, "_write_chapter_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_save", fake_save)

    events = [
        event
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            state,
            answers,
            "config-1",
        )
    ]

    checkpoint = saved[-1]
    assert checkpoint["stage"] == "quality_gate"
    assert "inflight_turn" not in checkpoint
    assert checkpoint["execution"]["pending_chapter_ids"] == ["chapter-2"]
    assert len(checkpoint["pending_questions"]) == 2
    assert sum(event["type"] == "question" for event in events) == 2
def _write_loop_state(chapter_count=3):
    state = _chapter_label_state(chapter_count)
    state.update(
        {
            "schema_version": "novel.agent.chat.v1",
            "stage": "write_scope",
            "llm_config_id": "config-1",
            "messages": [
                {
                    "id": "m1",
                    "role": "assistant",
                    "kind": "text",
                    "content": "请选择正文生成范围。",
                }
            ],
            "pending_questions": [],
            "artifacts": {},
            "confirmed": {},
            "selections": {},
            "quality_policy": {},
            "materialized_structure": {},
            "structure_created": False,
            "result": None,
        }
    )
    state["execution"]["chapter_results"] = []
    state["execution"]["write_scope_selection_version"] = (
        WRITE_SCOPE_SELECTION_VERSION
    )
    return state


def _set_write_continue_question(service, state):
    service._set_questions(
        state,
        "write_continue",
        [
            {
                "id": "pending",
                "header": "继续生成",
                "question": "本批正文已生成，是否继续生成剩余章节？",
                "options": [
                    service._option(
                        "continue",
                        "继续生成",
                        "刷新章节状态并选择下一批正文。",
                        True,
                        {"action": "continue"},
                    ),
                    service._option(
                        "finish",
                        "结束生成",
                        "保留本次已经生成的章节并结束流程。",
                        False,
                        {"action": "finish"},
                    ),
                ],
                "allow_custom": False,
                "state_version": state["state_version"] + 1,
            }
        ],
    )
    return state["pending_questions"][0]


def _quality_gate_answers(state):
    return [
        NovelAgentChatAnswer(
            question_id=question["id"],
            option_id=question["options"][0]["id"],
        )
        for question in state["pending_questions"]
    ]


@pytest.mark.anyio
async def test_write_scope_records_mode_and_clears_previous_completion_reason():
    service = NovelAgentChatService()
    state = _write_loop_state(3)
    state["execution"]["completion_reason"] = "stale_reason"
    question = service._fallback_question(
        "write_scope", state["state_version"] + 1, state
    )
    selected = next(option for option in question["options"] if option["id"] == "all")

    events = [
        event
        async for event in service._advance_from_answers(
            object(),
            "project-1",
            SimpleNamespace(),
            state,
            {"write_scope:1:1": {"option": selected, "custom_text": None}},
            "config-1",
        )
    ]

    assert state["execution"]["write_scope_mode"] == "all"
    assert "completion_reason" not in state["execution"]
    assert state["execution"]["pending_chapter_ids"] == [
        "chapter-1",
        "chapter-2",
        "chapter-3",
    ]
    assert state["stage"] == "quality_gate"
    assert all(event["type"] == "question" for event in events)


def test_mark_chapter_written_initializes_and_updates_remaining_scope():
    service = NovelAgentChatService()
    state = _chapter_label_state(3)
    state["execution"]["remaining_chapter_ids"] = []

    assert [
        item["id"] for item in service._remaining_chapter_labels(state)
    ] == ["chapter-1", "chapter-2", "chapter-3"]

    service._mark_chapter_written(state, "chapter-2")

    execution = state["execution"]
    assert execution["write_status_initialized"] is True
    assert execution["written_chapter_ids"] == ["chapter-2"]
    assert execution["written_count"] == 1
    assert execution["remaining_chapter_ids"] == ["chapter-1", "chapter-3"]
    assert execution["remaining_count"] == 2
    assert service._select_chapter_ids(
        {"option": {"id": "all", "value": {"mode": "all"}}}, state
    ) == ["chapter-1", "chapter-3"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "target_ids",
    [["chapter-1"], ["chapter-1", "chapter-2"]],
    ids=["single", "partial_batch"],
)
async def test_partial_write_batch_asks_to_continue_without_completing_session(
    monkeypatch,
    target_ids,
):
    service = NovelAgentChatService()
    state = _write_loop_state(3)
    state["execution"].update(
        {
            "pending_chapter_ids": target_ids,
            "selected_count": len(target_ids),
        }
    )
    service._set_questions(
        state,
        "quality_gate",
        service._quality_questions(state, len(target_ids)),
    )
    chapters = {
        chapter_id: SimpleNamespace(
            id=chapter_id,
            project_id="project-1",
            content="",
            word_count=0,
        )
        for chapter_id in ("chapter-1", "chapter-2", "chapter-3")
    }
    written_ids = []
    get_calls = []
    saves = []

    async def fake_get(_model, chapter_id):
        get_calls.append(chapter_id)
        return chapters.get(chapter_id)

    async def fake_pipeline(
        _db,
        _project_id,
        _config_id,
        chapter_id,
        _state,
        _policy,
    ):
        written_ids.append(chapter_id)
        chapters[chapter_id].content = f"{chapter_id} 正文"
        chapters[chapter_id].word_count = 100
        return {
            "kind": "chapter",
            "chapter_id": chapter_id,
            "content": chapters[chapter_id].content,
            "word_count": 100,
        }

    async def fake_save(_db, _session, current, **kwargs):
        saves.append(
            {
                "status": kwargs.get("status", "awaiting_input"),
                "state": deepcopy(current),
                "result": deepcopy(kwargs.get("result")),
            }
        )

    monkeypatch.setattr(service, "_write_chapter_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_save", fake_save)
    session = SimpleNamespace(id="session-1", request_payload={"chat_state": state})
    request = NovelAgentChatTurnRequest(
        session_id="session-1",
        llm_config_id="config-1",
        answers=_quality_gate_answers(state),
    )

    events = [
        event
        async for event in service._handle_turn_stream_unlocked(
            SimpleNamespace(get=fake_get), "project-1", session, request
        )
    ]

    assert written_ids == target_ids
    assert get_calls == []
    assert saves[-1]["status"] == "awaiting_input"
    assert saves[-1]["state"]["stage"] == "write_continue"
    assert not any(item["status"] == "completed" for item in saves)
    assert not any(item["state"]["stage"] == "completed" for item in saves)
    question = saves[-1]["state"]["pending_questions"][0]
    assert [option["id"] for option in question["options"]] == [
        "continue",
        "finish",
    ]
    assert sum(option["recommended"] for option in question["options"]) == 1
    assert events[-1] == {"type": "question", "question": question}
    assert [
        item["chapter_id"]
        for item in saves[-1]["state"]["execution"]["chapter_results"]
    ] == target_ids
    assert saves[-1]["state"]["execution"]["write_status_initialized"] is True
    assert saves[-1]["state"]["execution"]["remaining_chapter_ids"] == [
        chapter_id
        for chapter_id in ("chapter-1", "chapter-2", "chapter-3")
        if chapter_id not in target_ids
    ]


@pytest.mark.anyio
async def test_write_continue_refreshes_database_and_reasks_from_next_unwritten_chapter(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = _write_loop_state(4)
    accumulated = [
        {"kind": "chapter", "chapter_id": "chapter-1", "word_count": 120}
    ]
    state["execution"].update(
        {
            "chapter_results": deepcopy(accumulated),
            "remaining_chapter_ids": [
                "chapter-2",
                "chapter-3",
                "chapter-4",
            ],
            "remaining_count": 3,
        }
    )
    state["result"] = {
        "chapter_results": deepcopy(accumulated),
        "completed_count": 1,
    }
    question = _set_write_continue_question(service, state)
    chapters = {
        "chapter-1": SimpleNamespace(
            id="chapter-1",
            project_id="project-1",
            content="数据库中的第一章正文",
            word_count=0,
        ),
        "chapter-2": SimpleNamespace(
            id="chapter-2",
            project_id="project-1",
            content="",
            word_count=321,
        ),
        "chapter-3": SimpleNamespace(
            id="chapter-3",
            project_id="project-1",
            content="",
            word_count=0,
        ),
        "chapter-4": SimpleNamespace(
            id="chapter-4",
            project_id="project-1",
            content=None,
            word_count=0,
        ),
    }
    saves = []

    async def fake_get(_model, chapter_id):
        return chapters.get(chapter_id)

    async def fake_save(_db, _session, current, **kwargs):
        saves.append(
            {
                "status": kwargs.get("status", "awaiting_input"),
                "state": deepcopy(current),
            }
        )

    monkeypatch.setattr(service, "_save", fake_save)
    session = SimpleNamespace(id="session-1", request_payload={"chat_state": state})
    request = NovelAgentChatTurnRequest(
        session_id="session-1",
        llm_config_id="config-1",
        answers=[
            NovelAgentChatAnswer(question_id=question["id"], option_id="continue")
        ],
    )

    events = [
        event
        async for event in service._handle_turn_stream_unlocked(
            SimpleNamespace(get=fake_get), "project-1", session, request
        )
    ]

    current = saves[-1]["state"]
    assert saves[-1]["status"] == "awaiting_input"
    assert current["stage"] == "write_scope"
    assert current["execution"]["chapter_results"] == accumulated
    assert current["execution"]["write_status_initialized"] is True
    options = {
        option["id"]: option for option in current["pending_questions"][0]["options"]
    }
    assert "第 3 章" in options["single"]["description"]
    assert service._select_chapter_ids({"option": options["single"]}, current) == [
        "chapter-3"
    ]
    assert service._select_chapter_ids({"option": options["multiple"]}, current) == [
        "chapter-3",
        "chapter-4",
    ]
    assert service._select_chapter_ids({"option": options["all"]}, current) == [
        "chapter-3",
        "chapter-4",
    ]
    assert events[-1] == {
        "type": "question",
        "question": current["pending_questions"][0],
    }


@pytest.mark.anyio
async def test_write_continue_finish_completes_and_preserves_accumulated_results(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = _write_loop_state(3)
    accumulated = [
        {"kind": "chapter", "chapter_id": "chapter-1", "word_count": 100},
        {"kind": "chapter", "chapter_id": "chapter-2", "word_count": 110},
    ]
    state["execution"].update(
        {
            "chapter_results": deepcopy(accumulated),
            "remaining_chapter_ids": ["chapter-3"],
            "remaining_count": 1,
        }
    )
    state["result"] = {
        "chapter_results": deepcopy(accumulated),
        "completed_count": 2,
    }
    question = _set_write_continue_question(service, state)
    saves = []

    async def fake_save(_db, _session, current, **kwargs):
        saves.append(
            {
                "status": kwargs.get("status", "awaiting_input"),
                "state": deepcopy(current),
                "result": deepcopy(kwargs.get("result")),
            }
        )

    monkeypatch.setattr(service, "_save", fake_save)
    session = SimpleNamespace(id="session-1", request_payload={"chat_state": state})
    request = NovelAgentChatTurnRequest(
        session_id="session-1",
        llm_config_id="config-1",
        answers=[NovelAgentChatAnswer(question_id=question["id"], option_id="finish")],
    )

    events = [
        event
        async for event in service._handle_turn_stream_unlocked(
            object(), "project-1", session, request
        )
    ]

    assert saves[-1]["status"] == "completed"
    assert saves[-1]["state"]["stage"] == "completed"
    assert saves[-1]["state"]["pending_questions"] == []
    assert saves[-1]["state"]["execution"]["chapter_results"] == accumulated
    assert saves[-1]["state"]["result"]["chapter_results"] == accumulated
    assert saves[-1]["state"]["result"]["completed_count"] == 2
    assert saves[-1]["result"] == saves[-1]["state"]["result"]
    assert not any(event["type"] == "question" for event in events)


@pytest.mark.anyio
async def test_all_write_scope_conditionally_refreshes_known_remaining_before_completion(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = _write_loop_state(3)
    target_ids = ["chapter-1", "chapter-2"]
    state["execution"].update(
        {
            "pending_chapter_ids": target_ids,
            "selected_count": len(target_ids),
            "write_scope_mode": "all",
            "write_status_initialized": True,
            "remaining_chapter_ids": [
                "chapter-1",
                "chapter-2",
                "chapter-3",
            ],
            "remaining_count": 3,
        }
    )
    service._set_questions(
        state,
        "quality_gate",
        service._quality_questions(state, len(target_ids)),
    )
    chapters = {
        "chapter-1": SimpleNamespace(
            id="chapter-1", project_id="project-1", content="", word_count=0
        ),
        "chapter-2": SimpleNamespace(
            id="chapter-2", project_id="project-1", content="", word_count=0
        ),
        "chapter-3": SimpleNamespace(
            id="chapter-3",
            project_id="project-1",
            content="数据库中已存在的正文",
            word_count=0,
        ),
    }
    get_calls = []
    saves = []

    async def fake_get(_model, chapter_id):
        get_calls.append(chapter_id)
        return chapters.get(chapter_id)

    async def fake_pipeline(
        _db,
        _project_id,
        _config_id,
        chapter_id,
        _state,
        _policy,
    ):
        chapters[chapter_id].content = f"{chapter_id} 正文"
        chapters[chapter_id].word_count = 100
        return {
            "kind": "chapter",
            "chapter_id": chapter_id,
            "content": chapters[chapter_id].content,
            "word_count": 100,
        }

    async def fake_save(_db, _session, current, **kwargs):
        saves.append(
            {
                "status": kwargs.get("status", "awaiting_input"),
                "state": deepcopy(current),
            }
        )

    monkeypatch.setattr(service, "_write_chapter_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_save", fake_save)
    session = SimpleNamespace(id="session-1", request_payload={"chat_state": state})
    request = NovelAgentChatTurnRequest(
        session_id="session-1",
        llm_config_id="config-1",
        answers=_quality_gate_answers(state),
    )

    events = [
        event
        async for event in service._handle_turn_stream_unlocked(
            SimpleNamespace(get=fake_get), "project-1", session, request
        )
    ]

    assert get_calls == ["chapter-1", "chapter-2", "chapter-3"]
    awaiting_index = next(
        index for index, item in enumerate(saves) if item["status"] == "awaiting_input"
    )
    completed_index = next(
        index for index, item in enumerate(saves) if item["status"] == "completed"
    )
    assert awaiting_index < completed_index
    assert saves[-1]["status"] == "completed"
    assert saves[-1]["state"]["stage"] == "completed"
    assert saves[-1]["state"]["execution"]["remaining_chapter_ids"] == []
    assert saves[-1]["state"]["execution"]["write_status_initialized"] is True
    assert saves[-1]["state"]["execution"]["completion_reason"] == "all_written"
    assert not any(event["type"] == "question" for event in events)


@pytest.mark.anyio
async def test_write_batch_that_exhausts_all_chapters_completes_without_continue_question(
    monkeypatch,
):
    service = NovelAgentChatService()
    state = _write_loop_state(2)
    target_ids = ["chapter-1", "chapter-2"]
    state["execution"].update(
        {
            "pending_chapter_ids": target_ids,
            "selected_count": len(target_ids),
        }
    )
    service._set_questions(
        state,
        "quality_gate",
        service._quality_questions(state, len(target_ids)),
    )
    chapters = {
        chapter_id: SimpleNamespace(
            id=chapter_id,
            project_id="project-1",
            content="",
            word_count=0,
        )
        for chapter_id in target_ids
    }
    saves = []

    async def fake_get(_model, chapter_id):
        return chapters.get(chapter_id)

    async def fake_pipeline(
        _db,
        _project_id,
        _config_id,
        chapter_id,
        _state,
        _policy,
    ):
        chapters[chapter_id].content = f"{chapter_id} 正文"
        chapters[chapter_id].word_count = 100
        return {
            "kind": "chapter",
            "chapter_id": chapter_id,
            "content": chapters[chapter_id].content,
            "word_count": 100,
        }

    async def fake_save(_db, _session, current, **kwargs):
        saves.append(
            {
                "status": kwargs.get("status", "awaiting_input"),
                "state": deepcopy(current),
                "result": deepcopy(kwargs.get("result")),
            }
        )

    monkeypatch.setattr(service, "_write_chapter_pipeline", fake_pipeline)
    monkeypatch.setattr(service, "_save", fake_save)
    session = SimpleNamespace(id="session-1", request_payload={"chat_state": state})
    request = NovelAgentChatTurnRequest(
        session_id="session-1",
        llm_config_id="config-1",
        answers=_quality_gate_answers(state),
    )

    events = [
        event
        async for event in service._handle_turn_stream_unlocked(
            SimpleNamespace(get=fake_get), "project-1", session, request
        )
    ]

    assert saves[-1]["status"] == "completed"
    assert saves[-1]["state"]["stage"] == "completed"
    assert saves[-1]["state"]["result"]["completed_count"] == 2
    assert [
        item["chapter_id"]
        for item in saves[-1]["state"]["result"]["chapter_results"]
    ] == target_ids
    assert not any(
        item["state"]["stage"] == "write_continue" for item in saves
    )
    assert not any(event["type"] == "question" for event in events)
