"""Rapports de sécurité : synthèse lisible et données réelles conservées."""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest
import discord
from cogs import automod as mod


@pytest.mark.asyncio
async def test_automod_status_compact_with_counts_and_exemptions():
    cog = mod.AutoMod.__new__(mod.AutoMod)
    settings = {field: 0 for field in mod.AUTOMOD_TOGGLE_LABELS}
    settings.update(antispam=1, antiraid=0, escalation=0)
    db = SimpleNamespace(
        get_automod=AsyncMock(return_value=settings),
        automod_stats_since=AsyncMock(return_value=[
            {"filter_name": "antispam", "c": 4},
        ]),
        list_automod_exempt_roles=AsyncMock(return_value=[{"role_id": 123}]),
    )
    cog.bot = SimpleNamespace(db=db)
    cog.moderation_dataset = SimpleNamespace(loaded=True)
    ctx = SimpleNamespace(guild=SimpleNamespace(id=42))
    with (
        patch.object(mod.panels, "envoyer", new_callable=AsyncMock) as envoyer,
        patch.object(mod.panels, "depuis_embed", side_effect=lambda embed: embed),
    ):
        await mod.AutoMod.automod_status.callback(cog, ctx)
    embed = envoyer.await_args.args[1]
    assert isinstance(embed, discord.Embed)
    assert len(embed.fields) <= 5
    assert "4 action(s)" in (embed.description or "")
    assert any("spam" in f.value.casefold() for f in embed.fields)
    assert any("<@&123>" in f.value for f in embed.fields)
    assert len(embed) < 1800
