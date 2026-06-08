import os

import pytest

os.environ["DEBUG"] = "false"

from app.core.security import encrypt_api_key  # noqa: E402
from app.llm.providers.anthropic import AnthropicProvider  # noqa: E402
from app.llm.providers.base import LLMContentFilteredError  # noqa: E402
from app.llm.providers.base import LLMOutputTruncatedError  # noqa: E402
from app.llm.providers.google import GoogleProvider  # noqa: E402
from app.llm.providers.openai import OpenAIProvider  # noqa: E402


def _config(provider: str, model_name: str, base_url: str):
    return {
        "provider": provider,
        "api_key_encrypted": encrypt_api_key("sk-test"),
        "model_name": model_name,
        "base_url": base_url,
        "default_params": {},
    }


def test_openai_provider_builds_responses_payload():
    provider = OpenAIProvider(
        _config("openai", "gpt-5.5", "https://api.openai.com/v1")
    )

    payload = provider._build_payload(
        [
            {"role": "system", "content": "你是小说创作助手"},
            {"role": "user", "content": "写一个开场"},
        ],
        stream=False,
        max_tokens=128,
        verbosity="medium",
    )

    assert payload["model"] == "gpt-5.5"
    assert payload["instructions"] == "你是小说创作助手"
    assert payload["input"] == [{"role": "user", "content": "写一个开场"}]
    assert payload["max_output_tokens"] == 128
    assert payload["text"] == {"verbosity": "medium"}
    assert payload["stream"] is False


def test_anthropic_provider_builds_messages_payload():
    provider = AnthropicProvider(
        _config("anthropic", "claude-sonnet-4-6", "https://api.anthropic.com/v1")
    )

    payload = provider._build_payload(
        [
            {"role": "system", "content": "你是小说创作助手"},
            {"role": "user", "content": "写一个开场"},
            {"role": "assistant", "content": "好的。"},
        ],
        stream=True,
        max_tokens=256,
    )

    assert payload["model"] == "claude-sonnet-4-6"
    assert payload["system"] == "你是小说创作助手"
    assert payload["messages"] == [
        {"role": "user", "content": "写一个开场"},
        {"role": "assistant", "content": "好的。"},
    ]
    assert payload["max_tokens"] == 256
    assert payload["stream"] is True


def test_google_provider_builds_generate_content_payload():
    provider = GoogleProvider(
        _config(
            "google",
            "gemini-3.5-flash",
            "https://generativelanguage.googleapis.com/v1beta",
        )
    )

    payload = provider._build_payload(
        [
            {"role": "system", "content": "你是小说创作助手"},
            {"role": "user", "content": "写一个开场"},
            {"role": "assistant", "content": "好的。"},
        ],
        max_tokens=256,
        top_p=0.9,
    )

    assert payload["systemInstruction"] == {
        "parts": [{"text": "你是小说创作助手"}]
    }
    assert payload["contents"] == [
        {"role": "user", "parts": [{"text": "写一个开场"}]},
        {"role": "model", "parts": [{"text": "好的。"}]},
    ]
    assert payload["generationConfig"] == {
        "maxOutputTokens": 256,
        "topP": 0.9,
    }


def test_openai_incomplete_max_tokens_is_truncation():
    provider = OpenAIProvider(
        _config("openai", "gpt-5.5", "https://api.openai.com/v1")
    )

    with pytest.raises(LLMOutputTruncatedError):
        provider._raise_for_response_status(
            {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            }
        )


def test_anthropic_and_google_filtered_reasons_are_reported():
    anthropic = AnthropicProvider(
        _config("anthropic", "claude-sonnet-4-6", "https://api.anthropic.com/v1")
    )
    google = GoogleProvider(
        _config(
            "google",
            "gemini-3.5-flash",
            "https://generativelanguage.googleapis.com/v1beta",
        )
    )

    with pytest.raises(LLMContentFilteredError):
        anthropic._raise_for_stop_reason("content_filter")

    with pytest.raises(LLMContentFilteredError):
        google._raise_for_candidates([{"finishReason": "SAFETY"}])
