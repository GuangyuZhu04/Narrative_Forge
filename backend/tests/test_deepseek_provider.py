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


def test_deepseek_stream_timeout_allows_long_thinking_gaps():
    provider = DeepSeekProvider(_config())

    timeout = provider.STREAM_TIMEOUT.as_dict()

    assert timeout["connect"] == 30.0
    assert timeout["read"] is None


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
