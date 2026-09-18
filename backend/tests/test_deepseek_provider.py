import json
import os

import httpx
import pytest

os.environ["DEBUG"] = "false"

from app.core.security import encrypt_api_key  # noqa: E402
from app.llm.providers.base import LLMContentFilteredError  # noqa: E402
from app.llm.providers.base import LLMOutputTruncatedError  # noqa: E402
from app.llm.providers.base import LLMProviderConfigurationError  # noqa: E402
from app.llm.providers.deepseek import DeepSeekProvider  # noqa: E402
from app.llm.providers.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from app.llm.responses import parse_responses_result  # noqa: E402


def _config(default_params=None):
    return {
        "api_key_encrypted": encrypt_api_key("sk-test"),
        "model_name": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "default_params": default_params or {},
    }


def test_deepseek_payload_forces_max_thinking_mode():
    provider = DeepSeekProvider(
        _config(
            {
                "thinking": {"type": "disabled"},
                "reasoning_effort": "low",
            }
        )
    )

    payload = provider._build_payload(
        [{"role": "user", "content": "写一段小说"}],
        stream=False,
        reasoning_effort="medium",
    )

    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"
    assert payload["stream"] is False


def test_deepseek_stream_payload_forces_max_thinking_mode():
    provider = DeepSeekProvider(_config())

    payload = provider._build_payload(
        [{"role": "user", "content": "写一段小说"}],
        stream=True,
    )

    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


def test_deepseek_stream_payload_merges_explicit_stream_options():
    provider = DeepSeekProvider(_config())

    payload = provider._build_payload(
        [{"role": "user", "content": "write"}],
        stream=True,
        stream_options={"include_usage": False, "custom_option": "kept"},
    )

    assert payload["stream_options"] == {
        "include_usage": False,
        "custom_option": "kept",
    }


def test_deepseek_json_mode_payload_does_not_add_thinking_fields():
    provider = DeepSeekProvider(
        _config(
            {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "max",
            }
        )
    )

    payload = provider._build_payload(
        [{"role": "user", "content": "请返回 JSON"}],
        stream=False,
        response_format={"type": "json_object"},
    )

    assert payload["response_format"] == {"type": "json_object"}
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload


def test_deepseek_chat_downgrades_json_schema_to_json_object():
    provider = DeepSeekProvider(_config())

    payload = provider._build_payload(
        [{"role": "user", "content": "请返回 JSON"}],
        stream=False,
        response_format={
            "type": "json_schema",
            "name": "answer",
            "schema": {"type": "object"},
            "strict": True,
        },
    )

    assert payload["response_format"] == {"type": "json_object"}


def test_openai_compatible_chat_keeps_standard_json_schema():
    provider = OpenAICompatibleProvider(_config())

    payload = provider._build_payload(
        [{"role": "user", "content": "请返回 JSON"}],
        stream=False,
        response_format={
            "type": "json_schema",
            "name": "answer",
            "schema": {"type": "object"},
            "strict": True,
        },
    )

    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["name"] == "answer"


def test_deepseek_payload_can_disable_forced_thinking_for_health_check():
    provider = DeepSeekProvider(
        _config(
            {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "max",
            }
        )
    )

    payload = provider._build_payload(
        [{"role": "user", "content": "OK"}],
        stream=False,
        _force_max_thinking=False,
        thinking=None,
        reasoning_effort=None,
        max_tokens=64,
    )

    assert payload["max_tokens"] == 64
    assert "_force_max_thinking" not in payload
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload


@pytest.mark.parametrize(
    "default_token_param",
    ["max_output_tokens", "max_completion_tokens"],
)
def test_deepseek_chat_call_token_limit_overrides_default_alias(
    default_token_param,
):
    provider = DeepSeekProvider(_config({default_token_param: 16000}))

    payload = provider._build_payload(
        [{"role": "user", "content": "write"}],
        stream=False,
        max_tokens=1200,
    )

    assert payload["max_tokens"] == 1200
    assert "max_output_tokens" not in payload
    assert "max_completion_tokens" not in payload


@pytest.mark.parametrize(
    "default_token_param",
    ["max_output_tokens", "max_completion_tokens"],
)
def test_deepseek_responses_call_token_limit_overrides_default_alias(
    default_token_param,
):
    provider = DeepSeekProvider(
        {
            **_config({default_token_param: 16000}),
            "model_name": "deepseek-v4-flash",
        }
    )

    payload = provider._build_responses_payload(
        [{"role": "user", "content": "write"}],
        stream=False,
        max_tokens=1200,
    )

    assert payload["max_output_tokens"] == 1200
    assert "max_tokens" not in payload
    assert "max_completion_tokens" not in payload


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-v4-pro"])
def test_deepseek_v4_models_use_responses_api_by_default(model):
    provider = DeepSeekProvider({**_config(), "model_name": model})

    assert provider._uses_responses_api({}) is True


def test_deepseek_normalizes_model_name_before_responses_selection():
    provider = DeepSeekProvider(
        {**_config(), "model_name": "  deepseek-v4-pro  "}
    )

    assert provider.model == "deepseek-v4-pro"
    assert provider._uses_responses_api({}) is True


def test_deepseek_default_chat_mode_overrides_v4_auto_selection():
    provider = DeepSeekProvider(_config({"api_mode": "chat_completions"}))

    assert provider._uses_responses_api({}) is False

    payload = provider._build_payload(
        [{"role": "user", "content": "hello"}],
        stream=False,
        _force_max_thinking=False,
    )
    assert "api_mode" not in payload


def test_deepseek_v4_pro_can_explicitly_use_responses_api():
    provider = DeepSeekProvider(_config())

    assert provider._uses_responses_api({"api_mode": "responses"}) is True


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-v4-pro"])
def test_deepseek_explicit_chat_mode_overrides_v4_and_is_not_forwarded(model):
    provider = DeepSeekProvider({**_config(), "model_name": model})

    assert provider._uses_responses_api({"api_mode": "chat_completions"}) is False
    payload = provider._build_payload(
        [{"role": "user", "content": "hello"}],
        stream=False,
        api_mode="chat_completions",
        use_responses_api=False,
        _force_max_thinking=False,
    )

    assert "api_mode" not in payload
    assert "use_responses_api" not in payload
    assert "_force_max_thinking" not in payload


def test_deepseek_explicit_responses_rejects_unsupported_model():
    provider = DeepSeekProvider({**_config(), "model_name": "deepseek-v3"})

    with pytest.raises(LLMProviderConfigurationError, match="deepseek-v4-pro"):
        provider._uses_responses_api({"api_mode": "responses"})


@pytest.mark.parametrize(
    ("param", "value"),
    [
        ("previous_response_id", "resp_1"),
        ("conversation", "conv_1"),
        ("store", True),
        ("stream_options", {"include_usage": True}),
    ],
)
def test_deepseek_responses_rejects_silently_ignored_state_params(param, value):
    provider = DeepSeekProvider(_config())

    with pytest.raises(LLMProviderConfigurationError, match=param):
        provider._build_responses_payload(
            [{"role": "user", "content": "continue"}],
            stream=False,
            **{param: value},
        )


def test_deepseek_responses_accepts_explicit_store_false_as_noop():
    payload = DeepSeekProvider(_config())._build_responses_payload(
        [{"role": "user", "content": "continue"}],
        stream=False,
        store=False,
    )

    assert "store" not in payload


@pytest.mark.parametrize(
    ("kwargs", "expected_reasoning"),
    [
        pytest.param({}, {"effort": "max"}, id="default-max"),
        pytest.param({"_force_max_thinking": False}, None, id="forced-off"),
        pytest.param(
            {"reasoning": {"effort": "low"}},
            {"effort": "low"},
            id="explicit-reasoning",
        ),
    ],
)
def test_deepseek_responses_applies_default_reasoning_only_when_needed(
    kwargs, expected_reasoning
):
    payload = DeepSeekProvider(_config())._build_responses_payload(
        [{"role": "user", "content": "write"}],
        stream=False,
        **kwargs,
    )

    if expected_reasoning is None:
        assert "reasoning" not in payload
    else:
        assert payload["reasoning"] == expected_reasoning
    assert "_force_max_thinking" not in payload


def test_deepseek_responses_maps_reasoning_effort_none():
    payload = DeepSeekProvider(_config())._build_responses_payload(
        [{"role": "user", "content": "write without reasoning"}],
        stream=False,
        reasoning_effort="none",
        reasoning={"effort": "low"},
        temperature=1.3,
    )

    assert payload["reasoning"] == {"effort": "none"}
    assert payload["temperature"] == 1.3


@pytest.mark.anyio
async def test_deepseek_v4_pro_posts_to_responses_endpoint(monkeypatch):
    from app.llm.providers import deepseek as deepseek_module

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_pro_1",
                "model": "deepseek-v4-pro",
                "status": "completed",
                "store": False,
                "previous_response_id": None,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "完成"}],
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 1},
            },
        )

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        deepseek_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    result = await DeepSeekProvider(_config()).response(
        [{"role": "user", "content": "写作"}],
        max_tokens=321,
    )

    assert captured["url"] == "https://api.deepseek.com/responses"
    assert captured["payload"]["model"] == "deepseek-v4-pro"
    assert captured["payload"]["max_output_tokens"] == 321
    assert result.text == "完成"
    assert result.response_id == "resp_pro_1"


def test_openai_compatible_ignores_explicit_deepseek_responses_mode():
    provider = OpenAICompatibleProvider(_config())

    assert provider._uses_responses_api({"api_mode": "responses"}) is False


def test_deepseek_responses_payload_converts_messages_and_params():
    provider = DeepSeekProvider({**_config(), "model_name": "deepseek-v4-flash"})

    payload = provider._build_responses_payload(
        [
            {"role": "system", "content": "你是小说编辑"},
            {"role": "developer", "content": "只输出正文"},
            {"role": "user", "content": "写一段小说"},
        ],
        stream=False,
        max_tokens=1234,
        response_format={"type": "json_object"},
        reasoning_effort="max",
        api_mode="responses",
        thinking={"type": "enabled"},
    )

    assert payload["model"] == "deepseek-v4-flash"
    assert payload["instructions"] == "你是小说编辑\n\n只输出正文"
    assert payload["input"] == [{"role": "user", "content": "写一段小说"}]
    assert payload["stream"] is False
    assert payload["max_output_tokens"] == 1234
    assert payload["text"]["format"] == {"type": "json_object"}
    assert payload["reasoning"] == {"effort": "max"}
    assert "api_mode" not in payload
    assert "thinking" not in payload


def test_deepseek_responses_downgrades_json_schema_to_json_object():
    provider = DeepSeekProvider({**_config(), "model_name": "deepseek-v4-flash"})
    source_format = {
        "type": "json_schema",
        "name": "outline_foundation",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "rules"],
            "properties": {
                "title": {"type": "string", "maxLength": 120},
                "rules": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "items": {"type": "string", "maxLength": 160},
                },
            },
        },
    }

    payload = provider._build_responses_payload(
        [{"role": "user", "content": "return json"}],
        stream=False,
        response_format=source_format,
    )

    assert payload["text"]["format"] == {"type": "json_object"}
    assert "reasoning" not in payload
    assert source_format["schema"]["properties"]["title"]["maxLength"] == 120


def test_deepseek_responses_retains_semantic_history_and_normalizes_tools():
    provider = DeepSeekProvider({**_config(), "model_name": "deepseek-v4-flash"})
    history_items = [
        {"type": "reasoning", "id": "reasoning_1", "summary": []},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup_character",
            "arguments": "{}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": '{"name":"Lin"}',
        },
        {"type": "web_search_call", "id": "search_1", "status": "completed"},
    ]

    payload = provider._build_responses_payload(
        [*history_items, {"role": "user", "content": "continue"}],
        stream=False,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup_character",
                    "description": "lookup",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )

    assert payload["input"][:4] == history_items
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "lookup_character",
            "description": "lookup",
            "parameters": {"type": "object"},
        }
    ]


def test_deepseek_responses_parser_keeps_items_tools_and_cache_usage():
    provider = DeepSeekProvider({**_config(), "model_name": "deepseek-v4-flash"})
    data = {
        "id": "resp_1",
        "model": "deepseek-v4-flash",
        "status": "completed",
        "output": [
            {"type": "reasoning", "id": "reasoning_1", "summary": []},
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "lookup_character",
                "arguments": '{"id":1}',
            },
            {"type": "web_search_call", "id": "search_1"},
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 80},
            "output_tokens_details": {"reasoning_tokens": 12},
        },
    }

    result = provider._extract_response_text(data)
    rich_result = parse_responses_result(data)

    assert result == ""
    assert [item["type"] for item in rich_result.output_items] == [
        "reasoning",
        "function_call",
        "web_search_call",
    ]
    assert rich_result.tool_calls[0].name == "lookup_character"
    assert rich_result.usage.cached_input_tokens == 80
    assert rich_result.usage.reasoning_tokens == 12


def test_deepseek_extracts_responses_output_text():
    provider = DeepSeekProvider({**_config(), "model_name": "deepseek-v4-flash"})

    text = provider._extract_response_text(
        {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": "第一段"},
                        {"type": "text", "text": "第二段"},
                    ]
                }
            ]
        }
    )

    assert text == "第一段第二段"


def test_deepseek_stream_timeout_allows_long_thinking_gaps():
    provider = DeepSeekProvider(_config())

    timeout = provider.STREAM_TIMEOUT.as_dict()

    assert timeout["connect"] == 30.0
    assert timeout["read"] is None


def test_deepseek_delta_reasoning_content_becomes_thinking_event():
    provider = DeepSeekProvider(_config())

    event = provider._event_from_delta({"reasoning_content": "先分析人物动机"})

    assert event == {"type": "thinking", "content": "先分析人物动机"}


def test_deepseek_delta_content_becomes_content_event():
    provider = DeepSeekProvider(_config())

    event = provider._event_from_delta({"content": "正式回复"})

    assert event == {"type": "content", "content": "正式回复"}


def test_deepseek_finish_reason_length_is_treated_as_truncation():
    provider = DeepSeekProvider(_config())

    with pytest.raises(LLMOutputTruncatedError):
        provider._raise_for_finish_reason("length")


def test_deepseek_finish_reason_content_filter_is_reported():
    provider = DeepSeekProvider(_config())

    with pytest.raises(LLMContentFilteredError):
        provider._raise_for_finish_reason("content_filter")


def test_deepseek_non_stream_resource_interruption_is_failure():
    provider = DeepSeekProvider(_config())

    with pytest.raises(RuntimeError, match="insufficient_system_resource"):
        provider._parse_chat_result(
            {
                "choices": [
                    {
                        "finish_reason": "insufficient_system_resource",
                        "message": {"content": "partial chapter"},
                    }
                ]
            }
        )

    assert (
        provider._chat_finish_status("insufficient_system_resource").value
        == "failed"
    )


def test_deepseek_incomplete_content_filter_is_reported():
    provider = DeepSeekProvider({**_config(), "model_name": "deepseek-v4-flash"})

    with pytest.raises(LLMContentFilteredError):
        provider._raise_for_response_status(
            {
                "status": "incomplete",
                "incomplete_details": {"reason": "content_filter"},
            }
        )


def test_openai_compatible_payload_does_not_add_deepseek_thinking_fields():
    provider = OpenAICompatibleProvider(
        {
            **_config(),
            "base_url": "https://example.com/v1",
        }
    )

    payload = provider._build_payload(
        [{"role": "user", "content": "写一段小说"}],
        stream=False,
    )

    assert "thinking" not in payload
    assert "reasoning_effort" not in payload
    assert "stream_options" not in provider._build_payload(
        [{"role": "user", "content": "write"}],
        stream=True,
    )
