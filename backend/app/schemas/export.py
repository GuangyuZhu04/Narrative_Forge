from typing import Any

from pydantic import BaseModel


class ExportRequest(BaseModel):
    format: str
    options: dict[str, Any] | None = None
