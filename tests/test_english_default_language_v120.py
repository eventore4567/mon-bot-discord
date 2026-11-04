"""English is the default SentriX language without erasing explicit French choices."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci-placeholder-not-a-real-token")

from cogs import language_runtime as lang  # noqa: E402


def make_bot(existing=None):
    state = dict(existing or {})
    async def execute(sql, args=()):
        if "INSERT INTO guild_language_settings" in sql:
            state[int(args[0])] = args[1]
    async def fetchone(sql, args=()):
        language = state.get(int(args[0]))
        return {"language": language} if language else None
    db = SimpleNamespace(execute=AsyncMock(side_effect=execute), fetchone=AsyncMock(side_effect=fetchone))
    return SimpleNamespace(db=db), state


def test_default_english_for_unconfigured_server_and_dm():
    bot, _state = make_bot()
    assert lang.DEFAULT_LANGUAGE == lang.LANG_EN
    assert asyncio.run(lang.get_language(bot, 777)) == "en"
    assert lang.cached_language(bot, 777) == "en"
    assert asyncio.run(lang.get_language(bot, None)) == "en"


def test_preserve_french_when_explicitly_selected():
    bot, _state = make_bot({321: "fr"})
    assert asyncio.run(lang.get_language(bot, 321)) == "fr"
    asyncio.run(lang.set_language(bot, 321, "en"))
    assert asyncio.run(lang.get_language(bot, 321)) == "en"
    asyncio.run(lang.set_language(bot, 321, "fr"))
    assert asyncio.run(lang.get_language(bot, 321)) == "fr"


def test_default_database_column_is_english():
    source = Path("cogs/language_runtime.py").read_text(encoding="utf-8")
    assert "language TEXT NOT NULL DEFAULT 'en'" in source
    assert "language TEXT NOT NULL DEFAULT 'fr'" not in source


def test_new_onboarding_prioritizes_english():
    source = Path("cogs/public_language_choice.py").read_text(encoding="utf-8")
    assert 'label="English"' in source
    assert 'style=discord.ButtonStyle.primary' in source
    source = Path("cogs/guild_arrival.py").read_text(encoding="utf-8")
    english = source[source.index('label="English"'):source.index('custom_id="sentrix:guild-arrival:language:en:v3"')]
    assert "discord.ButtonStyle.primary" in english


def test_language_picker_keeps_both_choices_available():
    from cogs import public_language_choice
    source = Path(public_language_choice.__file__).read_text(encoding="utf-8")
    assert 'value=language_runtime.LANG_FR' not in source or 'language_runtime.LANG_FR' in source
    assert '"fr"' in Path("cogs/language_runtime.py").read_text(encoding="utf-8")
    assert '"en"' in Path("cogs/language_runtime.py").read_text(encoding="utf-8")
