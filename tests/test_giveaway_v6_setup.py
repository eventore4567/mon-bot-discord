"""Giveaway V6 : panneau complet, barre native, conditions XP et publication."""
from __future__ import annotations

import datetime
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs import giveaway_v2
from database.db import Database
from utils import sentrix_panels as panels


def _builder():
    guild = SimpleNamespace(id=42, get_channel=lambda n: SimpleNamespace(mention=f"<#{n}>") if n else None)
    ctx = SimpleNamespace(guild=guild, author=SimpleNamespace(id=123, mention="<@123>"))
    cog = giveaway_v2.GiveawayV2.__new__(giveaway_v2.GiveawayV2)
    cog.bot = SimpleNamespace()
    builder = giveaway_v2.GiveawayBuilderView(cog, ctx)
    builder.state.prize = "Nitro Classic"
    builder.state.duration_text = "2h"
    builder.state.duration_seconds = 7200
    builder.state.channel_id = 456
    builder.state.min_level = 5
    builder.state.min_invites = 2
    builder.state.required_roles = [66]
    builder.state.bonus_roles = [88]
    builder.state.bonus_multipliers[88] = 3
    return builder


def test_panneau_setup_diviseur_large_et_toutes_options():
    builder = _builder()
    panel = builder.setup_panel()
    container = next(c for c in panel.children if isinstance(c, discord.ui.Container))
    separators = [c for c in container.children if isinstance(c, discord.ui.Separator)]
    assert len(separators) == 1, "un vrai séparateur horizontal entre les parties du setup"
    text = panels.texte_complet(panel)
    assert "Nitro Classic" in text
    assert "Informations principales" in text
    assert "Conditions de participation" in text
    assert "Niveau XP" in text and "5 min." in text
    assert "<@&88> x3" in text
    assert "Rôles et chances" in text
    assert "Annonce" in text
    assert "4/4" in text
    selects = [c for c in builder.children if isinstance(c, discord.ui.Select)]
    assert len(selects) == 1 and len(selects[0].options) == 5
    assert all(c.label in ("Aperçu", "Publier", "Annuler") for c in builder.children if isinstance(c, discord.ui.Button))


def test_panneau_avertit_des_parametres_manquants():
    builder = _builder()
    builder.state.prize = None
    builder.state.channel_id = None
    text = panels.texte_complet(builder.setup_panel())
    assert "À compléter" in text
    assert "le lot" in text and "le salon" in text


def test_conditions_modal_contains_level_without_exceeding_discord_limit():
    modal = giveaway_v2.ConditionsModal(_builder())
    assert len(modal.children) <= 5
    assert "Niveau XP minimum" in [item.label for item in modal.children]


@pytest.mark.asyncio
async def test_migration_adds_min_level_and_new_records_persist_it():
    with tempfile.TemporaryDirectory() as temp:
        db = Database(os.path.join(temp, "giveaway-v6.db"))
        await db.connect()
        try:
            # Simule une base installée avant l'arrivée du champ min_level.
            legacy = giveaway_v2.SCHEMA[0].replace(
                "        min_level INTEGER NOT NULL DEFAULT 0,\n", ""
            )
            await db.execute(legacy)
            await db.execute(giveaway_v2.SCHEMA[1])
            cog = giveaway_v2.GiveawayV2.__new__(giveaway_v2.GiveawayV2)
            cog.bot = SimpleNamespace(db=db)
            cog._schema_ready = False
            await cog.ensure_schema()
            cols = await db.fetchall("PRAGMA table_info(giveaways_v2)")
            assert "min_level" in {x["name"] for x in cols}
            assert "result_message_id" in {x["name"] for x in cols}

            channel = SimpleNamespace(id=567, send=AsyncMock())
            guild = SimpleNamespace(id=42, get_channel=lambda n: channel)
            state = giveaway_v2.BuilderState(
                author_id=123, guild_id=42, prize="Nitro", duration_text="1h",
                duration_seconds=3600, winners=1, channel_id=567, min_level=12,
            )
            message = SimpleNamespace(id=777888, attachments=[], jump_url="https://discord.com/channels/42/567/777888")
            with patch.object(giveaway_v2.panels, "envoyer", new_callable=AsyncMock, return_value=message):
                published = await cog.publish(guild, state, SimpleNamespace(id=123, mention="<@123>"))
            assert published.id == 777888
            saved = await db.fetchone("SELECT min_level FROM giveaways_v2 WHERE message_id=?", (777888,))
            assert saved and saved["min_level"] == 12
        finally:
            await db.close()


@pytest.mark.asyncio
async def test_min_level_is_verified_on_entry_and_draw():
    db = SimpleNamespace(
        fetchone=AsyncMock(return_value=None),
        get_level=AsyncMock(return_value={"level": 4}),
    )
    cog = giveaway_v2.GiveawayV2.__new__(giveaway_v2.GiveawayV2)
    cog.bot = SimpleNamespace(db=db)
    member = SimpleNamespace(
        id=123, roles=[], guild=SimpleNamespace(id=42),
        created_at=discord.utils.utcnow() - datetime.timedelta(days=100),
        joined_at=discord.utils.utcnow() - datetime.timedelta(days=100),
    )
    row = {
        "required_roles_json": "[]", "excluded_roles_json": "[]",
        "bonus_roles_json": "{}", "min_level": 10,
        "min_invites": 0, "min_account_age_days": 0, "min_server_age_days": 0,
    }
    allowed, reason, weight = await cog._eligibility(row, member)
    assert not allowed and "10" in reason and weight == 1
    db.get_level.return_value = {"level": 10}
    allowed, reason, weight = await cog._eligibility(row, member)
    assert allowed and reason is None and weight == 1


@pytest.mark.asyncio
async def test_publication_error_removes_orphan_and_never_pings_role():
    db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("database unavailable")))
    cog = giveaway_v2.GiveawayV2.__new__(giveaway_v2.GiveawayV2)
    cog.bot = SimpleNamespace(db=db)
    cog.ensure_schema = AsyncMock()
    channel = SimpleNamespace(id=567, send=AsyncMock())
    guild = SimpleNamespace(id=42, get_channel=lambda n: channel)
    state = giveaway_v2.BuilderState(
        author_id=123, guild_id=42, prize="Nitro", duration_seconds=3600,
        winners=1, channel_id=567, ping_role_id=66,
    )
    message = SimpleNamespace(id=999, attachments=[], delete=AsyncMock())
    with patch.object(giveaway_v2.panels, "envoyer", new_callable=AsyncMock, return_value=message):
        with pytest.raises(RuntimeError, match="database unavailable"):
            await cog.publish(guild, state, SimpleNamespace(id=123, mention="<@123>"))
    message.delete.assert_awaited_once()
    channel.send.assert_not_awaited()
