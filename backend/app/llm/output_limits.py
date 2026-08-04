from urllib.parse import urlparse

from app.models.llm_config import LLMConfig

# DeepSeek V4 official model table (checked 2026-08-03):
# 1M context window and 384K maximum output.
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing
DEEPSEEK_V4_MAX_OUTPUT_TOKENS = 384 * 1024


def is_deepseek_config(config: LLMConfig | None) -> bool:
    if not config:
        return False
    hostname = (urlparse(config.base_url or "").hostname or "").lower()
    return config.provider == "deepseek" or hostname == "api.deepseek.com"


def model_output_token_budget(
    config: LLMConfig | None,
    default_tokens: int,
) -> int:
    """Return the supported per-request output budget for an Agent call."""
    if is_deepseek_config(config):
        return DEEPSEEK_V4_MAX_OUTPUT_TOKENS
    return default_tokens
