from .deepseek import DeepSeekProvider


class OpenAICompatibleProvider(DeepSeekProvider):
    """Conservative OpenAI Chat Completions adapter.

    Compatible endpoints vary widely and must never switch API surfaces merely
    because a model name happens to match a DeepSeek model.
    """

    API_BASE = "https://api.openai.com/v1"
    FORCE_MAX_THINKING = False
    SUPPORTS_CHAT_JSON_SCHEMA = True
    INCLUDE_CHAT_STREAM_USAGE = False

    def __init__(self, config: dict):
        config.setdefault("base_url", self.API_BASE)
        super().__init__(config)

    def _uses_responses_api(self, kwargs: dict) -> bool:
        return False
