DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}


def json_object_response_kwargs() -> dict:
    return {"response_format": DEEPSEEK_JSON_OBJECT_RESPONSE_FORMAT.copy()}


def json_schema_response_kwargs(name: str, schema: dict) -> dict:
    """Portable strict schema; each provider maps it to its native surface."""
    return {
        "response_format": {
            "type": "json_schema",
            "name": name,
            "schema": schema,
            "strict": True,
        }
    }
