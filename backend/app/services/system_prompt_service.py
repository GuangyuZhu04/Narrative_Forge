from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.prompts.chapter import CHARACTER_IMPORT_SYSTEM
from app.llm.prompts.novel_polish import (
    NOVEL_POLISH_DEFAULT_SUGGESTIONS,
    NOVEL_POLISH_SYSTEM,
    NOVEL_POLISH_USER,
)
from app.llm.prompts.novel_write import (
    NOVEL_DEFAULT_STYLE_REQUIREMENTS,
    NOVEL_PREVIOUS_CONTEXT_SUMMARY_SYSTEM,
    NOVEL_PREVIOUS_CONTEXT_SUMMARY_USER,
    NOVEL_WRITE_CONTINUATION_USER,
    NOVEL_WRITE_SYSTEM,
    NOVEL_WRITE_USER,
)
from app.llm.prompts.outline import OUTLINE_EXPAND_SYSTEM, OUTLINE_OPTIMIZE_SYSTEM
from app.llm.prompts.scene import SCENE_IMPORT_SYSTEM
from app.core.exceptions import ValidationException
from app.models.system_prompt_setting import SystemPromptSetting
from app.schemas.system_settings import SystemPromptSettingResponse

NOVEL_WRITE_SYSTEM_KEY = "novel_write.system"
NOVEL_WRITE_USER_TEMPLATE_KEY = "novel_write.user_template"
NOVEL_WRITE_CONTINUATION_USER_KEY = "novel_write.continuation_user"
NOVEL_WRITE_PREVIOUS_SUMMARY_SYSTEM_KEY = "novel_write.previous_summary_system"
NOVEL_WRITE_PREVIOUS_SUMMARY_USER_KEY = "novel_write.previous_summary_user"
NOVEL_WRITE_DEFAULT_STYLE_KEY = "novel_write.default_style_requirements"
NOVEL_WRITE_TEMPERATURE_KEY = "novel_write.temperature"
NOVEL_WRITE_PREVIOUS_SUMMARY_TEMPERATURE_KEY = (
    "novel_write.previous_summary_temperature"
)

NOVEL_POLISH_SYSTEM_KEY = "novel_polish.system"
NOVEL_POLISH_USER_TEMPLATE_KEY = "novel_polish.user_template"
NOVEL_POLISH_DEFAULT_SUGGESTIONS_KEY = "novel_polish.default_suggestions"
NOVEL_POLISH_TEMPERATURE_KEY = "novel_polish.temperature"

OUTLINE_OPTIMIZE_SYSTEM_KEY = "outline_optimize.system"
OUTLINE_OPTIMIZE_DEFAULT_DIRECTION_KEY = "outline_optimize.default_direction"
OUTLINE_OPTIMIZE_TEMPERATURE_KEY = "outline_optimize.temperature"
OUTLINE_EXPAND_SYSTEM_KEY = "outline_expand.system"
OUTLINE_EXPAND_DEFAULT_COUNT_KEY = "outline_expand.default_count"
OUTLINE_EXPAND_TEMPERATURE_KEY = "outline_expand.temperature"
OUTLINE_GENERATE_TEMPERATURE_KEY = "outline_generate.temperature"
CHARACTER_IMPORT_SYSTEM_KEY = "character_import.system"
CHARACTER_IMPORT_TEMPERATURE_KEY = "character_import.temperature"
CHARACTER_GENERATE_TEMPERATURE_KEY = "character_generate.temperature"
SCENE_IMPORT_SYSTEM_KEY = "scene_import.system"
SCENE_IMPORT_TEMPERATURE_KEY = "scene_import.temperature"
CHAPTER_CONTINUE_TEMPERATURE_KEY = "chapter_continue.temperature"
CHAPTER_REWRITE_TEMPERATURE_KEY = "chapter_rewrite.temperature"
CHAPTER_POLISH_TEMPERATURE_KEY = "chapter_polish.temperature"
CHAPTER_EXPAND_TEMPERATURE_KEY = "chapter_expand.temperature"
CHAPTER_SUMMARIZE_TEMPERATURE_KEY = "chapter_summarize.temperature"
CHAPTER_DIALOGUE_TEMPERATURE_KEY = "chapter_dialogue.temperature"
CONSISTENCY_ANALYSIS_TEMPERATURE_KEY = "consistency_analysis.temperature"
DISCUSSION_TEMPERATURE_KEY = "discussion.temperature"

SETTING_TYPE_TEXT = "text"
SETTING_TYPE_NUMBER = "number"


@dataclass(frozen=True)
class PromptDefinition:
    key: str
    category: str
    title: str
    description: str
    default_value: str
    value_type: str = SETTING_TYPE_TEXT
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    integer_only: bool = False


def temperature_definition(
    key: str,
    category: str,
    title: str,
    description: str,
    default_value: str,
) -> PromptDefinition:
    return PromptDefinition(
        key,
        category,
        title,
        description,
        default_value,
        value_type=SETTING_TYPE_NUMBER,
        min_value=0,
        max_value=2,
        step=0.1,
    )


PROMPT_DEFINITIONS: tuple[PromptDefinition, ...] = (
    PromptDefinition(
        NOVEL_WRITE_SYSTEM_KEY,
        "AI 编写",
        "章节正文生成 system prompt",
        "控制 AI 编写整章正文时的角色、原则、输出边界和质量要求。",
        NOVEL_WRITE_SYSTEM,
    ),
    PromptDefinition(
        NOVEL_WRITE_USER_TEMPLATE_KEY,
        "AI 编写",
        "章节正文生成用户模板",
        "定义大纲、卷、章节摘要、人物、前文和文风等输入信息如何拼接给模型。",
        NOVEL_WRITE_USER,
    ),
    PromptDefinition(
        NOVEL_WRITE_CONTINUATION_USER_KEY,
        "AI 编写",
        "自动续写用户提示",
        "模型输出长度受限时，继续补完当前章节所使用的提示。",
        NOVEL_WRITE_CONTINUATION_USER,
    ),
    PromptDefinition(
        NOVEL_WRITE_PREVIOUS_SUMMARY_SYSTEM_KEY,
        "AI 编写",
        "前文背景总结 system prompt",
        "在 AI 编写输入面板中总结当前卷前文背景时使用。",
        NOVEL_PREVIOUS_CONTEXT_SUMMARY_SYSTEM,
    ),
    PromptDefinition(
        NOVEL_WRITE_PREVIOUS_SUMMARY_USER_KEY,
        "AI 编写",
        "前文背景总结用户模板",
        "定义卷信息、章节摘要和前文章节素材如何拼接给前文总结模型。",
        NOVEL_PREVIOUS_CONTEXT_SUMMARY_USER,
    ),
    PromptDefinition(
        NOVEL_WRITE_DEFAULT_STYLE_KEY,
        "AI 编写",
        "默认文风要求",
        "用户未单独填写文风要求时，AI 编写默认使用的风格信息。",
        NOVEL_DEFAULT_STYLE_REQUIREMENTS,
    ),
    temperature_definition(
        NOVEL_WRITE_TEMPERATURE_KEY,
        "AI 编写",
        "章节正文生成 temperature",
        "控制 AI 编写整章正文时的创作发散度；DeepSeek 正文叙事质量稳定建议 1.2 ~ 1.4，默认 1.3。",
        "1.3",
    ),
    temperature_definition(
        NOVEL_WRITE_PREVIOUS_SUMMARY_TEMPERATURE_KEY,
        "AI 编写",
        "前文背景总结 temperature",
        "控制前文背景总结的发散度；总结类任务更强调稳定和设定一致，默认 1.1。",
        "1.1",
    ),
    PromptDefinition(
        NOVEL_POLISH_SYSTEM_KEY,
        "AI 打磨",
        "章节打磨 system prompt",
        "控制 AI 根据一致性分析和打磨建议修订章节正文时的编辑原则。",
        NOVEL_POLISH_SYSTEM,
    ),
    PromptDefinition(
        NOVEL_POLISH_USER_TEMPLATE_KEY,
        "AI 打磨",
        "章节打磨用户模板",
        "定义章节正文和打磨建议如何拼接给模型。",
        NOVEL_POLISH_USER,
    ),
    PromptDefinition(
        NOVEL_POLISH_DEFAULT_SUGGESTIONS_KEY,
        "AI 打磨",
        "默认打磨建议",
        "用户没有提供具体建议时，AI 打磨使用的兜底说明。",
        NOVEL_POLISH_DEFAULT_SUGGESTIONS,
    ),
    temperature_definition(
        NOVEL_POLISH_TEMPERATURE_KEY,
        "AI 打磨",
        "章节打磨 temperature",
        "控制 AI 打磨正文时的改写幅度；默认 1.2，兼顾修订稳定性和文本表现力。",
        "1.2",
    ),
    PromptDefinition(
        OUTLINE_EXPAND_SYSTEM_KEY,
        "AI 扩展",
        "大纲节点扩展 system prompt",
        "控制每一卷、每一章等大纲节点执行 AI 扩展时的角色、输出结构和扩展原则。",
        OUTLINE_EXPAND_SYSTEM,
    ),
    PromptDefinition(
        OUTLINE_EXPAND_DEFAULT_COUNT_KEY,
        "AI 扩展",
        "默认扩展子节点数量",
        "点击大纲节点的 AI 扩展时，配置弹窗默认填入的子节点数量；后端最大支持 100。",
        "3",
        value_type=SETTING_TYPE_NUMBER,
        min_value=1,
        max_value=100,
        step=1,
        integer_only=True,
    ),
    temperature_definition(
        OUTLINE_EXPAND_TEMPERATURE_KEY,
        "AI 扩展",
        "大纲节点扩展 temperature",
        "控制卷、章等大纲节点 AI 扩展时的发散度；DeepSeek 大纲/设定建议 1.0 ~ 1.2，默认 1.1。",
        "1.1",
    ),
    PromptDefinition(
        OUTLINE_OPTIMIZE_SYSTEM_KEY,
        "AI 打磨",
        "大纲打磨 system prompt",
        "控制大纲页面的 AI 打磨功能如何分析和优化当前大纲。",
        OUTLINE_OPTIMIZE_SYSTEM,
    ),
    PromptDefinition(
        OUTLINE_OPTIMIZE_DEFAULT_DIRECTION_KEY,
        "AI 打磨",
        "大纲默认打磨方向",
        "大纲打磨未填写方向时使用的默认信息。",
        "综合优化",
    ),
    temperature_definition(
        OUTLINE_OPTIMIZE_TEMPERATURE_KEY,
        "AI 打磨",
        "大纲打磨 temperature",
        "控制大纲打磨建议的发散度；默认 1.1，偏向稳定修订和设定一致性。",
        "1.1",
    ),
    temperature_definition(
        OUTLINE_GENERATE_TEMPERATURE_KEY,
        "大纲",
        "大纲生成 temperature",
        "控制从项目要求生成完整大纲时的发散度；DeepSeek 大纲/世界观建议 1.0 ~ 1.2，默认 1.1。",
        "1.1",
    ),
    PromptDefinition(
        CHARACTER_IMPORT_SYSTEM_KEY,
        "人物",
        "人物一键导入 system prompt",
        "控制人物页面一键导入时如何从粘贴文本中提取、推断并生成结构化人物档案。",
        CHARACTER_IMPORT_SYSTEM,
    ),
    temperature_definition(
        CHARACTER_IMPORT_TEMPERATURE_KEY,
        "人物",
        "人物一键导入 temperature",
        "控制人物一键导入时的推断发散度；DeepSeek 人物设定建议 1.0 ~ 1.2，默认 1.1。",
        "1.1",
    ),
    temperature_definition(
        CHARACTER_GENERATE_TEMPERATURE_KEY,
        "人物",
        "人物生成 temperature",
        "控制根据描述生成人物档案时的发散度；DeepSeek 人物设定建议 1.0 ~ 1.2，默认 1.1。",
        "1.1",
    ),
    PromptDefinition(
        SCENE_IMPORT_SYSTEM_KEY,
        "场景",
        "场景 AI 导入 system prompt",
        "控制场景页面 AI 导入时如何从自然语言描述中提取、拆分并生成结构化场景卡片。",
        SCENE_IMPORT_SYSTEM,
    ),
    temperature_definition(
        SCENE_IMPORT_TEMPERATURE_KEY,
        "场景",
        "场景 AI 导入 temperature",
        "控制场景 AI 导入时的推断发散度；场景设定整理偏向稳定与可复用，默认 1.1。",
        "1.1",
    ),
    temperature_definition(
        CHAPTER_CONTINUE_TEMPERATURE_KEY,
        "章节编辑",
        "章节续写 temperature",
        "控制章节编辑器中 AI 续写的叙事发散度；DeepSeek 正文叙事建议 1.2 ~ 1.4，默认 1.3。",
        "1.3",
    ),
    temperature_definition(
        CHAPTER_REWRITE_TEMPERATURE_KEY,
        "章节编辑",
        "章节改写 temperature",
        "控制章节编辑器中 AI 改写的发散度；默认 1.2，兼顾稳定和表达变化。",
        "1.2",
    ),
    temperature_definition(
        CHAPTER_POLISH_TEMPERATURE_KEY,
        "章节编辑",
        "章节润色 temperature",
        "控制章节编辑器中 AI 润色的发散度；默认 1.2，保持原意并提升表达。",
        "1.2",
    ),
    temperature_definition(
        CHAPTER_EXPAND_TEMPERATURE_KEY,
        "章节编辑",
        "章节扩写 temperature",
        "控制章节编辑器中 AI 扩写细节的发散度；默认 1.3，适合正文叙事扩展。",
        "1.3",
    ),
    temperature_definition(
        CHAPTER_SUMMARIZE_TEMPERATURE_KEY,
        "章节编辑",
        "章节摘要 temperature",
        "控制章节摘要生成的发散度；默认 1.1，偏向稳定提炼。",
        "1.1",
    ),
    temperature_definition(
        CHAPTER_DIALOGUE_TEMPERATURE_KEY,
        "章节编辑",
        "对话生成 temperature",
        "控制章节编辑器中 AI 生成对话的发散度；默认 1.3，兼顾角色声音和稳定叙事。",
        "1.3",
    ),
    temperature_definition(
        CONSISTENCY_ANALYSIS_TEMPERATURE_KEY,
        "一致性分析",
        "一致性分析 temperature",
        "控制人物、情节、连续性和内容一致性分析的发散度；默认 1.1，偏向稳定判断。",
        "1.1",
    ),
    temperature_definition(
        DISCUSSION_TEMPERATURE_KEY,
        "小说讨论",
        "小说讨论 temperature",
        "控制小说讨论中多轮对话的创作发散度；默认 1.3，适合正文情节讨论和稳定输出。",
        "1.3",
    ),
)

PROMPT_DEFINITION_BY_KEY = {definition.key: definition for definition in PROMPT_DEFINITIONS}


class SystemPromptService:
    async def list_settings(self, db: AsyncSession) -> list[SystemPromptSettingResponse]:
        rows = await self._load_rows(db)
        return [self._build_response(definition, rows.get(definition.key)) for definition in PROMPT_DEFINITIONS]

    async def get_setting(self, db: AsyncSession, key: str) -> SystemPromptSettingResponse | None:
        definition = PROMPT_DEFINITION_BY_KEY.get(key)
        if not definition:
            return None
        row = await self._get_row(db, key)
        return self._build_response(definition, row)

    async def update_setting(
        self, db: AsyncSession, key: str, value: str
    ) -> SystemPromptSettingResponse | None:
        definition = PROMPT_DEFINITION_BY_KEY.get(key)
        if not definition:
            return None
        value = self._normalize_value(definition, value)

        row = await self._get_row(db, key)
        if row:
            row.value = value
            row.is_custom = value != definition.default_value
        else:
            row = SystemPromptSetting(
                setting_key=key,
                value=value,
                is_custom=value != definition.default_value,
            )
            db.add(row)
        await db.commit()
        await db.refresh(row)
        return self._build_response(definition, row)

    async def reset_setting(self, db: AsyncSession, key: str) -> SystemPromptSettingResponse | None:
        definition = PROMPT_DEFINITION_BY_KEY.get(key)
        if not definition:
            return None
        row = await self._get_row(db, key)
        if row:
            await db.delete(row)
            await db.commit()
        return self._build_response(definition, None)

    async def get_effective_value(self, db: AsyncSession, key: str) -> str:
        definition = PROMPT_DEFINITION_BY_KEY[key]
        row = await self._get_row(db, key)
        if row and row.is_custom:
            return row.value
        return definition.default_value

    async def get_effective_float(self, db: AsyncSession, key: str) -> float:
        value = await self.get_effective_value(db, key)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(PROMPT_DEFINITION_BY_KEY[key].default_value)

    async def get_effective_values(self, db: AsyncSession, keys: list[str]) -> dict[str, str]:
        rows = await self._load_rows(db, keys)
        values: dict[str, str] = {}
        for key in keys:
            definition = PROMPT_DEFINITION_BY_KEY[key]
            row = rows.get(key)
            values[key] = row.value if row and row.is_custom else definition.default_value
        return values

    async def get_effective_float_values(
        self, db: AsyncSession, keys: list[str]
    ) -> dict[str, float]:
        values = await self.get_effective_values(db, keys)
        float_values: dict[str, float] = {}
        for key, value in values.items():
            try:
                float_values[key] = float(value)
            except (TypeError, ValueError):
                float_values[key] = float(PROMPT_DEFINITION_BY_KEY[key].default_value)
        return float_values

    async def _get_row(self, db: AsyncSession, key: str) -> SystemPromptSetting | None:
        result = await db.execute(
            select(SystemPromptSetting).where(SystemPromptSetting.setting_key == key)
        )
        return result.scalar_one_or_none()

    async def _load_rows(
        self, db: AsyncSession, keys: list[str] | None = None
    ) -> dict[str, SystemPromptSetting]:
        stmt = select(SystemPromptSetting)
        if keys is not None:
            stmt = stmt.where(SystemPromptSetting.setting_key.in_(keys))
        result = await db.execute(stmt)
        return {row.setting_key: row for row in result.scalars().all()}

    def _build_response(
        self, definition: PromptDefinition, row: SystemPromptSetting | None
    ) -> SystemPromptSettingResponse:
        is_custom = bool(row and row.is_custom)
        value = row.value if row else definition.default_value
        effective_value = value if is_custom else definition.default_value
        return SystemPromptSettingResponse(
            key=definition.key,
            category=definition.category,
            title=definition.title,
            description=definition.description,
            value=value,
            default_value=definition.default_value,
            effective_value=effective_value,
            is_custom=is_custom,
            value_type=definition.value_type,
            min_value=definition.min_value,
            max_value=definition.max_value,
            step=definition.step,
            integer_only=definition.integer_only,
            updated_at=row.updated_at if row else None,
        )

    def _normalize_value(self, definition: PromptDefinition, value: str) -> str:
        if definition.value_type != SETTING_TYPE_NUMBER:
            return value

        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValidationException("系统设置必须是数字") from exc

        if definition.min_value is not None and parsed < definition.min_value:
            raise ValidationException(
                f"系统设置不能小于 {definition.min_value:g}"
            )
        if definition.max_value is not None and parsed > definition.max_value:
            raise ValidationException(
                f"系统设置不能大于 {definition.max_value:g}"
            )
        if definition.integer_only and not parsed.is_integer():
            raise ValidationException("系统设置必须是整数")
        if definition.integer_only:
            return str(int(parsed))
        return f"{parsed:g}"


system_prompt_service = SystemPromptService()
