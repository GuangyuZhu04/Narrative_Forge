DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}


def json_object_response_kwargs() -> dict:
    return {"response_format": DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT.copy()}
