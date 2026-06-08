from fastapi import HTTPException


class AppException(HTTPException):
    def __init__(self, status_code: int, detail: str, error_code: str):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class NotFoundException(AppException):
    def __init__(self, detail: str = "资源不存在", error_code: str = "NOT_FOUND"):
        super().__init__(status_code=404, detail=detail, error_code=error_code)


class ProjectNotFoundException(NotFoundException):
    def __init__(self):
        super().__init__(detail="项目不存在", error_code="PROJECT_NOT_FOUND")


class OutlineNotFoundException(NotFoundException):
    def __init__(self):
        super().__init__(detail="大纲不存在", error_code="OUTLINE_NOT_FOUND")


class ChapterNotFoundException(NotFoundException):
    def __init__(self):
        super().__init__(detail="章节不存在", error_code="CHAPTER_NOT_FOUND")


class CharacterNotFoundException(NotFoundException):
    def __init__(self):
        super().__init__(detail="人物不存在", error_code="CHARACTER_NOT_FOUND")


class LLMConfigNotFoundException(NotFoundException):
    def __init__(self):
        super().__init__(detail="LLM 配置不存在", error_code="LLM_CONFIG_NOT_FOUND")


class LLMConfigInactiveException(AppException):
    def __init__(self):
        super().__init__(
            status_code=400, detail="LLM 配置未激活", error_code="LLM_CONFIG_INACTIVE"
        )


class LLMRequestFailedException(AppException):
    def __init__(self, detail: str = "LLM 请求失败"):
        super().__init__(
            status_code=502, detail=detail, error_code="LLM_REQUEST_FAILED"
        )


class LLMRateLimitedException(AppException):
    def __init__(self):
        super().__init__(
            status_code=429, detail="LLM 请求频率超限", error_code="LLM_RATE_LIMITED"
        )


class ValidationException(AppException):
    def __init__(self, detail: str = "数据校验失败"):
        super().__init__(
            status_code=400, detail=detail, error_code="VALIDATION_ERROR"
        )
