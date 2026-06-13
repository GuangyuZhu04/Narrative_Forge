import os

import pytest

os.environ["DEBUG"] = "false"

from app.core.security import encrypt_api_key  # noqa: E402
from app.llm.providers.base import LLMContentFilteredError  # noqa: E402
from app.llm.providers.base import LLMOutputTruncatedError  # noqa: E402
from app.llm.providers.deepseek import DeepSeekProvider  # noqa: E402
from app.llm.providers.openai_compatible import OpenAICompatibleProvider  # noqa: E402


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
