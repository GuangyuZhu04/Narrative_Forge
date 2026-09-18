"""Stored defaults follow prompt upgrades; explicit custom values remain intact."""

from pathlib import Path
import sys

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# The same regression runs against the desktop backend and the Android runtime.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "runtime" if (PROJECT_ROOT / "runtime").is_dir() else PROJECT_ROOT))

# Import the application to register every related ORM model, as at normal startup.
from app.main import app  # noqa: E402, F401
from app.models.system_prompt_setting import SystemPromptSetting  # noqa: E402
from app.services.system_prompt_service import (  # noqa: E402
    NOVEL_WRITE_SYSTEM_KEY,
    PROMPT_DEFINITION_BY_KEY,
    system_prompt_service,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("is_custom", [False, True])
async def test_saved_prompt_defaults_follow_upgrade_without_overwriting_custom(is_custom):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SystemPromptSetting.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            stored = "Previously saved prompt, before the default was upgraded."
            db.add(SystemPromptSetting(
                setting_key=NOVEL_WRITE_SYSTEM_KEY, value=stored, is_custom=is_custom
            ))
            await db.commit()
            default = PROMPT_DEFINITION_BY_KEY[NOVEL_WRITE_SYSTEM_KEY].default_value
            expected = stored if is_custom else default
            setting = await system_prompt_service.get_setting(db, NOVEL_WRITE_SYSTEM_KEY)
            assert setting.value == setting.effective_value == expected
            assert setting.default_value == default
            assert setting.is_custom is is_custom
            listed = {item.key: item for item in await system_prompt_service.list_settings(db)}
            assert listed[NOVEL_WRITE_SYSTEM_KEY].value == expected
            assert await system_prompt_service.get_effective_value(db, NOVEL_WRITE_SYSTEM_KEY) == expected
            assert (await system_prompt_service.get_effective_values(db, [NOVEL_WRITE_SYSTEM_KEY]))[NOVEL_WRITE_SYSTEM_KEY] == expected
            reset = await system_prompt_service.reset_setting(db, NOVEL_WRITE_SYSTEM_KEY)
            assert reset.value == reset.effective_value == default
            assert reset.is_custom is False
    finally:
        await engine.dispose()
