"""Régressions réelles : activation volontaire et restauration des routes Soundboard."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from database.db import Database
from cogs import setup_v2_core as core


def test_security_off_masks_all_filters_and_preserves_saved_settings(monkeypatch):
    # 24/11/2026 (refactorisation, étape 1) : la règle vivait dans un enrobage
    # posé par core._patch_security ; AutoMod.get_automod_cached l'applique
    # maintenant lui-même. Même vérification, sur la vraie méthode.
    from cogs.automod import AutoMod

    async def scenario():
        saved = {key: 1 for key in ('antispam', 'antiinsult', 'antinuke', 'security_permissions', 'security_prune', 'security_vanity', 'join_gate', 'risk_engine')}
        automod = AutoMod.__new__(AutoMod)
        automod.bot = SimpleNamespace()
        automod.automod_cache = {42: saved}
        enabled = AsyncMock(return_value=False)
        monkeypatch.setattr(core, 'module_enabled', enabled)
        muted = await automod.get_automod_cached(42)
        assert muted['security_module_disabled'] is True
        assert all(muted[key] == 0 for key in saved)
        assert all(saved[key] == 1 for key in saved)
        enabled.return_value = True
        assert await automod.get_automod_cached(42) == saved
    asyncio.run(scenario())


def test_un_membre_de_confiance_est_exempte_sans_enrobage(monkeypatch):
    from cogs.automod import AutoMod
    import discord

    async def scenario():
        automod = AutoMod.__new__(AutoMod)
        automod.bot = SimpleNamespace(user=SimpleNamespace(id=1))
        monkeypatch.setattr(core, 'is_trusted', AsyncMock(return_value=True))
        guild = SimpleNamespace(id=42, owner_id=9)
        membre = discord.Object(id=77)
        assert await automod.is_antinuke_exempt(guild, membre) is True
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


def test_mp_de_sanction_borne_et_proprietaire_protege_sans_couche():
    # 24/11/2026 (refactorisation, étape 1) : ces deux règles vivaient dans
    # cogs/sentrix_v22 et cogs/owner_sanction_immunity ; Moderation les porte.
    from cogs import moderation as mod

    async def scenario():
        cog = mod.Moderation.__new__(mod.Moderation)

        async def lent(*_a, **_k):
            await asyncio.sleep(10)
            return True

        cog._envoyer_mp_de_sanction = lent
        mod.MP_SANCTION_DELAI_MAX, avant = 0.05, mod.MP_SANCTION_DELAI_MAX
        try:
            assert await cog._send_sanction_dm(SimpleNamespace(), SimpleNamespace(), "warn", "x") is False
        finally:
            mod.MP_SANCTION_DELAI_MAX = avant

        from utils import owner_access
        import utils.sentrix_panels as panels
        envoye = AsyncMock()
        orig_envoyer, orig_owner = panels.envoyer, owner_access.is_bot_owner_id
        panels.envoyer = envoye
        owner_access.is_bot_owner_id = lambda uid: uid == 4242
        try:
            assert await cog.check_targetable(SimpleNamespace(), SimpleNamespace(id=4242)) is False
            envoye.assert_awaited_once()
        finally:
            panels.envoyer, owner_access.is_bot_owner_id = orig_envoyer, orig_owner
    asyncio.run(scenario())
