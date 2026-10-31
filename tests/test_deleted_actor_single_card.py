"""Journal de suppression : exécuteur fiable, profil cliquable, zéro doublon."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from cogs.logs import Logs
from cogs.logs_unified_v6 import _deleted_message_already_logged_here
from utils import wide_logs


def _embed(actor: str):
    embed = discord.Embed(title="Message supprimé")
    embed.add_field(name="Auteur", value="<@1457325087928881212>")
    embed.add_field(name="Salon", value="<#1565501048326463488>")
    embed.add_field(name="Contenu", value="Selimor x Tomioka")
    embed.add_field(name="Supprimé par", value=actor)
    return embed


def test_deleted_log_displays_deleter_in_narration_once():
    text = wide_logs.narrative_body(
        _embed("<@1457325087928881000>\nID : \`1457325087928881000\`"),
        log_type="message_delete",
        identity_id=1457325087928881212,
    )
    assert "Selimor x Tomioka" in text
    assert "**Supprimé par :** <@1457325087928881000>" in text
    assert text.count("Supprimé par") == 1


def test_deleted_log_unverified_actor_is_explicit():
    text = wide_logs.narrative_body(
        _embed("Exécuteur inconnu · suppression par l’auteur possible"),
        log_type="message_delete",
    )
    assert "Non identifié" in text
    assert "<@1457325087928881000>" not in text


def test_mentions_remain_clickable_without_pinging():
    view = wide_logs.WideLogView(
        _embed("<@1457325087928881000>"), banner_filename="",
        log_type="message_delete", identity_id=1457325087928881212,
    )
    rendered = []
    def walk(items):
        for item in items:
            if isinstance(item, discord.ui.TextDisplay):
                rendered.append(item.content)
            walk(getattr(item, "children", ()))
    walk(view.children)
    data = "\n".join(rendered)
    assert "<@1457325087928881212>" in data
    assert "<@1457325087928881000>" in data
    assert wide_logs.NO_PINGS.everyone is False


@pytest.mark.asyncio
async def test_delete_audit_entry_cannot_be_reused_for_another_message():
    actor = SimpleNamespace(id=444)
    entry = SimpleNamespace(
        id=9001, user=actor,
        created_at=discord.utils.utcnow(),
        target=SimpleNamespace(id=222),
        extra=SimpleNamespace(count=1, channel=SimpleNamespace(id=333)),
    )
    async def audit_logs(**kwargs):
        yield entry
    guild = SimpleNamespace(
        id=11,
        me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
        audit_logs=audit_logs,
    )
    bot = SimpleNamespace(user=SimpleNamespace(id=111),get_user=lambda x: None)
    cog = Logs(bot)
    found, _ = await cog._message_delete_actor(guild, 222, 333, message_id=888)
    assert found is actor
    again, _ = await cog._message_delete_actor(guild, 222, 333, message_id=889)
    assert again is None


@pytest.mark.asyncio
async def test_bulk_or_cross_channel_audit_does_not_guess_deleter():
    actor = SimpleNamespace(id=444)
    entry = SimpleNamespace(
        id=9002, user=actor, created_at=discord.utils.utcnow(),
        target=SimpleNamespace(id=222),
        extra=SimpleNamespace(count=3, channel=SimpleNamespace(id=333)),
    )
    async def audit_logs(**kwargs):
        yield entry
    guild = SimpleNamespace(
        id=11,
        me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
        audit_logs=audit_logs,
    )
    cog = Logs(SimpleNamespace(user=SimpleNamespace(id=111)))
    assert (await cog._message_delete_actor(guild, 222, 333))[0] is None
    entry.extra.count = 1
    assert (await cog._message_delete_actor(guild, 222, 444))[0] is None


@pytest.mark.asyncio
async def test_file_log_does_not_repeat_message_log_in_same_channel(monkeypatch):
    from cogs import logs_unified_v6
    async def settings(_bot, _guild_id, category):
        return {"channel_id": 123, "enabled": True} if category in ("messages","files") else {}
    monkeypatch.setattr(logs_unified_v6.log_service, "get_log_setting", settings)
    assert await _deleted_message_already_logged_here(None, 1)


@pytest.mark.asyncio
async def test_separate_files_channel_keeps_archive(monkeypatch):
    from cogs import logs_unified_v6
    async def settings(_bot, _guild_id, category):
        return {"channel_id": 123 if category == "messages" else 456, "enabled": True}
    monkeypatch.setattr(logs_unified_v6.log_service, "get_log_setting", settings)
    assert not await _deleted_message_already_logged_here(None, 1)


@pytest.mark.asyncio
async def test_delayed_audit_entry_is_still_attributed_without_guessing(monkeypatch):
    """Discord peut publier le journal d'audit après les premières lectures."""
    actor = SimpleNamespace(id=444)
    entry = SimpleNamespace(
        id=9101, user=actor, created_at=discord.utils.utcnow(),
        target=SimpleNamespace(id=222),
        extra=SimpleNamespace(count=1, channel=SimpleNamespace(id=333)),
    )
    calls = 0

    async def audit_logs(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            yield entry

    guild = SimpleNamespace(
        id=11,
        me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
        audit_logs=audit_logs,
    )
    monkeypatch.setattr("cogs.logs.asyncio.sleep", AsyncMock())
    cog = Logs(SimpleNamespace(user=SimpleNamespace(id=111)))
    found, proof = await cog._message_delete_actor(guild, 222, 333, message_id=888)
    assert found is actor
    assert proof is entry
    assert calls == 4


@pytest.mark.asyncio
async def test_unknown_deleter_is_not_assumed_to_be_message_author(monkeypatch):
    """Sans preuve Discord, ne pas accuser le créateur du message."""
    async def audit_logs(**kwargs):
        if False:
            yield None

    guild = SimpleNamespace(
        id=11,
        me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True)),
        audit_logs=audit_logs,
    )
    monkeypatch.setattr("cogs.logs.asyncio.sleep", AsyncMock())
    cog = Logs(SimpleNamespace(user=SimpleNamespace(id=111)))
    actor, audit = await cog._message_delete_actor(guild, 222, 333, message_id=888)
    assert actor is None
    assert audit is None
