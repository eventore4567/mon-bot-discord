"""Anti-nuke : un webhook = une entrée audit vérifiée, jamais un faux ban.

Les notifications on_webhooks_update sont regroupées/répétées par Discord.
Le compteur n'a le droit de voir qu'un ID d'audit unique dont le salon est
confirmé. Les actions inconnues ne provoquent pas de sanction automatique.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from cogs.security_runtime_hardening import SecurityHardening


def _event(entry_id, *, action, channel_id=20, actor_id=55, age=1):
    now = discord.utils.utcnow()
    actor = SimpleNamespace(id=actor_id)
    return SimpleNamespace(
        id=entry_id,
        action=action,
        created_at=now - timedelta(seconds=age),
        target=SimpleNamespace(channel_id=channel_id) if channel_id is not None else SimpleNamespace(),
        user=actor,
    )


def _runtime(events, *, exempt=False):
    automod = SimpleNamespace(
        get_automod_cached=AsyncMock(return_value={"antinuke": 1}),
        is_antinuke_exempt=AsyncMock(return_value=exempt),
        record_nuke_action=AsyncMock(return_value=False),
        punish_nuker=AsyncMock(),
    )
    bot = SimpleNamespace(get_cog=Mock(return_value=automod))
    cog = SecurityHardening(bot)
    async def audit_logs(*, limit, action):
        for item in events:
            if item.action == action:
                yield item
    guild = SimpleNamespace(id=100, audit_logs=audit_logs)
    channel = SimpleNamespace(id=20, guild=guild)
    return cog, automod, channel


@pytest.mark.asyncio
async def test_webhook_antinuke_counts_each_audit_action_once_even_with_repeated_events():
    events = [
        _event(11, action=discord.AuditLogAction.webhook_create),
        _event(12, action=discord.AuditLogAction.webhook_update),
        _event(13, action=discord.AuditLogAction.webhook_delete),
    ]
    cog, automod, channel = _runtime(events)
    automod.record_nuke_action.side_effect = [False, False, True]
    await cog.on_webhooks_update(channel)
    await cog.on_webhooks_update(channel)

    assert automod.record_nuke_action.await_count == 3
    automod.punish_nuker.assert_awaited_once_with(
        channel.guild, 55, "Modifications massives de webhooks",
    )


@pytest.mark.asyncio
async def test_webhook_antinuke_ignores_unrelated_channel_and_unattributable_entries():
    events = [
        _event(21, action=discord.AuditLogAction.webhook_create, channel_id=21),
        _event(22, action=discord.AuditLogAction.webhook_delete, channel_id=None),
        _event(23, action=discord.AuditLogAction.webhook_update, age=90),
        _event(24, action=discord.AuditLogAction.webhook_create, age=-30),
    ]
    cog, automod, channel = _runtime(events)
    await cog.on_webhooks_update(channel)

    automod.record_nuke_action.assert_not_awaited()
    automod.punish_nuker.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_antinuke_respects_owner_and_whitelist_exemptions():
    events = [_event(31, action=discord.AuditLogAction.webhook_create)]
    cog, automod, channel = _runtime(events, exempt=True)
    await cog.on_webhooks_update(channel)
    automod.is_antinuke_exempt.assert_awaited_once()
    automod.record_nuke_action.assert_not_awaited()
    automod.punish_nuker.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_antinuke_disabled_does_not_inspect_audit_history():
    cog, automod, channel = _runtime([])
    automod.get_automod_cached.return_value = {"antinuke": 0}
    channel.guild.audit_logs = Mock(side_effect=AssertionError("should not fetch audit"))
    await cog.on_webhooks_update(channel)
    channel.guild.audit_logs.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_antinuke_dedup_state_is_bounded():
    cog, automod, channel = _runtime([])
    for i in range(4300):
        cog._seen_webhook_audit[(100, i)] = float(i)
    cog._seen_webhook_audit[(100, 4300)] = float(4300)
    # A normal event must remove stale IDs and leave a bounded cache.
    cog._seen_webhook_audit.clear()
    cog._seen_webhook_audit[(100, 20)] = -10000.0
    await cog.on_webhooks_update(channel)
    assert (100, 20) not in cog._seen_webhook_audit
