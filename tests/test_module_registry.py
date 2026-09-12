"""Milestone 2 (Configuration Platform), priorité P1 #8 : registre central des
modules. core/modules/registry.py est le contrat générique ; core/modules/
definitions.py enregistre les modules réels, lus depuis les tables déjà
utilisées en production (guild_config, automod_settings, ticket_types,
ai_settings, level_roles) — aucune nouvelle table, aucun nouvel état.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from core.modules import definitions, registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


# ------------------------------------------------------------- registry.py --

def test_register_and_all_modules():
    async def describe(bot, guild_id):
        return registry.ModuleStatus(enabled=True, configured=True, summary="ok")

    registry.register(registry.ModuleDefinition(key="test", label="Test", describe=describe))
    assert [m.key for m in registry.all_modules()] == ["test"]


def test_register_same_key_replaces_not_duplicates():
    async def describe(bot, guild_id):
        return registry.ModuleStatus(enabled=True, configured=True, summary="v1")

    async def describe_v2(bot, guild_id):
        return registry.ModuleStatus(enabled=True, configured=True, summary="v2")

    registry.register(registry.ModuleDefinition(key="test", label="Test", describe=describe))
    registry.register(registry.ModuleDefinition(key="test", label="Test", describe=describe_v2))
    modules = registry.all_modules()
    assert len(modules) == 1
    assert modules[0].describe is describe_v2


def test_status_for_unknown_module_returns_none():
    async def run():
        return await registry.status_for(Mock(), 1, "does-not-exist")

    assert asyncio.run(run()) is None


def test_status_for_returns_error_status_without_crashing():
    async def broken_describe(bot, guild_id):
        raise RuntimeError("boom")

    registry.register(registry.ModuleDefinition(key="broken", label="Broken", describe=broken_describe))

    async def run():
        return await registry.status_for(Mock(), 1, "broken")

    status = asyncio.run(run())
    assert status.enabled is False
    assert status.issues


def test_all_statuses_isolates_one_broken_module_from_the_rest():
    async def ok_describe(bot, guild_id):
        return registry.ModuleStatus(enabled=True, configured=True, summary="ok")

    async def broken_describe(bot, guild_id):
        raise RuntimeError("boom")

    registry.register(registry.ModuleDefinition(key="ok", label="OK", describe=ok_describe))
    registry.register(registry.ModuleDefinition(key="broken", label="Broken", describe=broken_describe))

    async def run():
        return await registry.all_statuses(Mock(), 1)

    statuses = asyncio.run(run())
    assert statuses["ok"].summary == "ok"
    assert statuses["broken"].enabled is False


# ---------------------------------------------------------- definitions.py --

def _row(data: dict):
    """Émule un aiosqlite.Row : accès par clé, KeyError si absent."""
    class _Row(dict):
        def __getitem__(self, key):
            return dict.__getitem__(self, key)
    return _Row(data)


def _bot_with(**db_methods) -> Mock:
    bot = Mock()
    bot.db = Mock()
    for name, value in db_methods.items():
        setattr(bot.db, name, value)
    return bot


def test_install_registers_all_eight_modules():
    definitions.install()
    keys = {m.key for m in registry.all_modules()}
    assert keys == {
        "moderation", "automod", "tickets", "verification",
        "logs", "welcome", "levels", "ai",
    }


def test_moderation_reports_missing_roles():
    bot = _bot_with(get_guild_config=AsyncMock(return_value=_row({"mod_role": None, "mute_role": None, "warn_role": None})))

    async def run():
        return await definitions._describe_moderation(bot, 1)

    status = asyncio.run(run())
    assert status.configured is False
    assert "mod_role" in status.issues[0] or "staff" in status.issues[0]


def test_moderation_reports_configured_when_role_present():
    bot = _bot_with(get_guild_config=AsyncMock(return_value=_row({"mod_role": 111, "mute_role": 222, "warn_role": None})))

    async def run():
        return await definitions._describe_moderation(bot, 1)

    status = asyncio.run(run())
    assert status.configured is True
    assert status.issues == ()


def test_automod_counts_active_filters():
    bot = _bot_with(get_automod=AsyncMock(return_value=_row({
        "antispam": 1, "antilink": 1, "antiinvite": 0, "antimention": 0,
        "anticaps": 0, "antiemoji": 0, "antiraid": 0, "antibot": 0,
        "antiaccount": 0, "antiscam": 0, "antinuke": 0,
    })))

    async def run():
        return await definitions._describe_automod(bot, 1)

    status = asyncio.run(run())
    assert status.enabled is True
    assert "2/11" in status.summary


def test_automod_disabled_when_no_filter_active():
    bot = _bot_with(get_automod=AsyncMock(return_value=_row({name: 0 for name in (
        "antispam", "antilink", "antiinvite", "antimention", "anticaps",
        "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
    )})))

    async def run():
        return await definitions._describe_automod(bot, 1)

    status = asyncio.run(run())
    assert status.enabled is False


def test_tickets_reports_missing_role_and_category():
    bot = _bot_with(fetchall=AsyncMock(return_value=[
        _row({"id": 1, "staff_role_id": None, "category_id": 50}),
        _row({"id": 2, "staff_role_id": 60, "category_id": None}),
    ]))

    async def run():
        return await definitions._describe_tickets(bot, 1)

    status = asyncio.run(run())
    assert status.enabled is True
    assert status.configured is False
    assert any("sans rôle support" in issue for issue in status.issues)
    assert any("sans catégorie" in issue for issue in status.issues)


def test_tickets_disabled_when_no_type_exists():
    bot = _bot_with(fetchall=AsyncMock(return_value=[]))

    async def run():
        return await definitions._describe_tickets(bot, 1)

    status = asyncio.run(run())
    assert status.enabled is False
    assert status.configured is False


def test_verification_ready_when_role_and_channel_set():
    bot = _bot_with(get_guild_config=AsyncMock(return_value=_row({
        "verification_role": 1, "verify_role": None, "verification_channel": 2,
        "verify_captcha_enabled": 1,
    })))

    async def run():
        return await definitions._describe_verification(bot, 1)

    status = asyncio.run(run())
    assert status.configured is True
    assert "CAPTCHA actif" in status.summary


def test_welcome_not_configured_without_message():
    bot = _bot_with(get_guild_config=AsyncMock(return_value=_row({
        "welcome_channel": 5, "welcome_message": None,
    })))

    async def run():
        return await definitions._describe_welcome(bot, 1)

    status = asyncio.run(run())
    assert status.configured is False
    assert status.issues


def test_ai_reports_disabled_when_row_says_so():
    bot = _bot_with(fetchone=AsyncMock(return_value=_row({"enabled": 0, "default_model": "terra"})))

    async def run():
        return await definitions._describe_ai(bot, 1)

    status = asyncio.run(run())
    assert status.enabled is False


def test_ai_reports_defaults_when_no_row_exists_yet():
    bot = _bot_with(fetchone=AsyncMock(return_value=None))

    async def run():
        return await definitions._describe_ai(bot, 1)

    status = asyncio.run(run())
    assert status.configured is False
