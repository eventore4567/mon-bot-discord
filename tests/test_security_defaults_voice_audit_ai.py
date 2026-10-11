from __future__ import annotations

import sqlite3
from datetime import timedelta
from types import SimpleNamespace

import pytest

from cogs import security_verification_v71 as security_v71
from utils.audit_correlation import correlate_audit_entry
from utils.moderation_dataset import MultilingualModerationDataset


class AsyncSqlite:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row

    async def execute(self, sql, params=()):
        self.connection.execute(sql, params)
        self.connection.commit()

    async def fetchone(self, sql, params=()):
        return self.connection.execute(sql, params).fetchone()


async def _security_bot():
    db = AsyncSqlite()
    await db.execute(
        "CREATE TABLE guild_config (guild_id INTEGER PRIMARY KEY, "
        "verification_channel INTEGER, verify_role INTEGER, verification_role INTEGER)"
    )
    return SimpleNamespace(db=db)


@pytest.mark.asyncio
async def test_new_guild_has_no_fictitious_honeypot_or_verification_activation():
    bot = await _security_bot()
    result = await security_v71.settings(bot, 123)
    assert result["honeypot_enabled"] is False
    assert result["verification_enabled"] is False


@pytest.mark.asyncio
async def test_migration_preserves_existing_real_resources_but_disables_placeholder_rows():
    bot = await _security_bot()
    await bot.db.execute(security_v71.SCHEMA)
    await bot.db.execute(security_v71.HONEYPOT_SCHEMA)
    await bot.db.execute(
        "INSERT INTO sentrix_security_v71"
        "(guild_id,honeypot_enabled,verification_enabled,updated_at) VALUES(1,1,1,0),(2,1,1,0)"
    )
    await bot.db.execute(
        "INSERT INTO honeypot_verification"
        "(guild_id,enabled,trap_channel_id,unverified_role_id,created_at) VALUES(1,1,10,20,1)"
    )
    await bot.db.execute(
        "INSERT INTO guild_config(guild_id,verification_channel,verify_role) VALUES(1,30,40)"
    )
    await security_v71.ensure_schema(bot)
    real = await security_v71.settings(bot, 1)
    placeholder = await security_v71.settings(bot, 2)
    assert real["honeypot_enabled"] is True
    assert real["verification_enabled"] is True
    assert placeholder["honeypot_enabled"] is False
    assert placeholder["verification_enabled"] is False


def test_toxicity_confidence_uses_target_and_reporting_context():
    dataset = MultilingualModerationDataset()
    standalone = dataset.match("connard")
    targeted = dataset.match("tu es un connard")
    reported = dataset.match("il m'a dit connard")
    assert standalone and standalone.confidence == pytest.approx(0.70)
    assert targeted and targeted.targeted and targeted.confidence >= 0.92
    assert reported and reported.confidence < 0.70
    assert dataset.match("connexion au serveur") is None


def test_uncertain_toxicity_is_removed_without_risk_or_escalation():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "cogs" / "automod.py"
    ).read_text(encoding="utf-8")
    assert "dataset_match.confidence >= 0.92" in source
    assert "dataset_match.confidence >= 0.70" in source
    assert '"multilingual_toxicity",\n                    allow_escalation=False' in source


class _AuditIterator:
    def __init__(self, entries):
        self.entries = entries

    def __aiter__(self):
        self.iterator = iter(self.entries)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


@pytest.mark.asyncio
async def test_audit_correlation_requires_action_target_and_recent_timestamp():
    import discord

    now = discord.utils.utcnow()
    wrong = SimpleNamespace(
        target=SimpleNamespace(id=999), created_at=now, user=SimpleNamespace(id=1)
    )
    stale = SimpleNamespace(
        target=SimpleNamespace(id=42), created_at=now - timedelta(minutes=2), user=SimpleNamespace(id=2)
    )
    correct = SimpleNamespace(
        target=SimpleNamespace(id=42), created_at=now - timedelta(seconds=2), user=SimpleNamespace(id=3)
    )
    guild = SimpleNamespace(
        me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
        audit_logs=lambda **_kwargs: _AuditIterator([wrong, stale, correct]),
    )
    result = await correlate_audit_entry(
        guild,
        discord.AuditLogAction.kick,
        target_id=42,
        retry_delays=(0.0,),
    )
    assert result.status == "attribue"
    assert result.actor.id == 3


@pytest.mark.asyncio
async def test_audit_correlation_is_resilient_without_permission():
    import discord

    guild = SimpleNamespace(
        me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=False))
    )
    result = await correlate_audit_entry(
        guild,
        discord.AuditLogAction.kick,
        target_id=42,
        retry_delays=(0.0,),
    )
    assert result.entry is None
    assert result.status == "permission_manquante"


def test_dashboard_states_voice_and_stream_limits_without_fake_toggle():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "web" / "dashboard_ui" / "js" / "30_modules.js"
    ).read_text(encoding="utf-8")
    assert "Un salon vocal par serveur" in source
    assert "Aucun son n’est enregistré ni transcrit" in source
    assert "pas les images du partage d’écran" in source
