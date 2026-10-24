"""Régressions réelles : activation volontaire et restauration des routes Soundboard."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from database.db import Database
from cogs import setup_v2_core as core


def test_security_off_masks_all_filters_and_preserves_saved_settings(monkeypatch):
    async def scenario():
        saved = {key: 1 for key in ('antispam', 'antiinsult', 'antinuke', 'security_permissions', 'security_prune', 'security_vanity', 'join_gate', 'risk_engine')}
        automod = SimpleNamespace(
            is_automod_exempt=AsyncMock(return_value=False),
            is_antinuke_exempt=AsyncMock(return_value=False),
            get_automod_cached=AsyncMock(return_value=saved),
        )
        bot = SimpleNamespace(get_cog=lambda _: automod)
        enabled = AsyncMock(return_value=False)
        monkeypatch.setattr(core, 'module_enabled', enabled)
        core._patch_security(bot)
        muted = await automod.get_automod_cached(42)
        assert muted['security_module_disabled'] is True
        assert all(muted[key] == 0 for key in saved)
        assert all(saved[key] == 1 for key in saved)
        enabled.return_value = True
        assert await automod.get_automod_cached(42) == saved
    asyncio.run(scenario())


def test_soundboard_archived_route_is_restored_without_overwriting_choice(tmp_path):
    async def scenario():
        db = Database(str(tmp_path / 'logs.db'))
        await db.connect()
        try:
            await db.execute('CREATE TABLE log_settings_backup (guild_id INTEGER,log_type TEXT,channel_id INTEGER,enabled INTEGER,updated_at INTEGER)')
            await db.execute("INSERT INTO log_settings_backup VALUES (42,'log_soundboard',500,1,10),(43,'soundboard_play',501,1,11)")
            await db.execute("INSERT INTO log_config VALUES (43,'soundboard',502,0,20)")
            await db._migrate_logs()
            restored = await db.fetchone("SELECT * FROM log_config WHERE guild_id=42 AND category='soundboard'")
            assert restored['channel_id'] == 500
            chosen = await db.fetchone("SELECT * FROM log_config WHERE guild_id=43 AND category='soundboard'")
            assert chosen['channel_id'] == 502 and chosen['enabled'] == 0
            await db._migrate_logs()
            assert len(await db.fetchall("SELECT * FROM log_config WHERE category='soundboard'")) == 2
        finally:
            await db.close()
    asyncio.run(scenario())


def test_old_inferred_enables_are_removed_but_signed_choices_survive(tmp_path):
    async def scenario():
        core.invalidate_module_cache()
        db = Database(str(tmp_path / 'modules.db'))
        await db.connect()
        bot = SimpleNamespace(db=db)
        try:
            await db.execute('CREATE TABLE sentrix_migrations(name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)')
            await db.execute("INSERT INTO sentrix_migrations VALUES ('module_defaults_absent_is_off_v1',123)")
            await db.execute('CREATE TABLE module_settings(guild_id INTEGER,module TEXT,enabled INTEGER,updated_by INTEGER,updated_at INTEGER,PRIMARY KEY(guild_id,module))')
            await db.execute("INSERT INTO module_settings VALUES (42,'welcome',1,NULL,123),(42,'economy',1,NULL,123),(43,'welcome',1,99,123),(44,'logs',0,NULL,123)")
            await core.ensure_schema(bot)
            assert not await core.module_enabled(bot, 42, 'welcome')
            # Économie : fonction des membres, active sans réglage depuis le 24/10/2026.
            assert await core.module_enabled(bot, 42, 'economy')
            assert await core.module_enabled(bot, 43, 'welcome')
            assert await core.module_state(bot, 44, 'logs') == core.MODULE_STATE_DISABLED
            await core.migrate_module_defaults(bot)
            assert await core.module_enabled(bot, 43, 'welcome')
        finally:
            core.invalidate_module_cache()
            await db.close()
    asyncio.run(scenario())


def test_ai_requires_explicit_switch_and_can_be_enabled(tmp_path):
    from utils import ai_service
    async def scenario():
        core.invalidate_module_cache()
        db = Database(str(tmp_path / 'ai.db'))
        await db.connect()
        bot = SimpleNamespace(db=db)
        try:
            assert not (await ai_service.get_settings(bot, 42))['enabled']
            await ai_service.update_setting(bot, 42, 'enabled', 1)
            assert (await ai_service.get_settings(bot, 42))['enabled']
            await ai_service.update_setting(bot, 42, 'enabled', 0)
            assert not (await ai_service.get_settings(bot, 42))['enabled']
        finally:
            core.invalidate_module_cache()
            await db.close()
    asyncio.run(scenario())
