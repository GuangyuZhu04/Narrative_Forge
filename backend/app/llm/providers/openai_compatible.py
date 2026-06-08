from .deepseek import DeepSeekProvider


class OpenAICompatibleProvider(DeepSeekProvider):
    API_BASE = "https://api.openai.com/v1"
    FORCE_MAX_THINKING = False

    def __init__(self, config: dict):
        config.setdefault("base_url", self.API_BASE)
        super().__init__(config)
