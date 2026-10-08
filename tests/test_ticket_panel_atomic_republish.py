"""Un panneau ticket ne doit jamais disparaître si son remplacement échoue."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.tickets import Tickets


def context():
    events = []
    old = SimpleNamespace(id=44, delete=AsyncMock(side_effect=lambda: events.append("delete_old")))
    msg = SimpleNamespace(id=55, delete=AsyncMock(side_effect=lambda: events.append("delete_new")))

    async def fetch_message(message_id):
        assert message_id == 44
        events.append("fetch_old")
        return old

    channel = SimpleNamespace(
        id=33, mention="<#33>", fetch_message=AsyncMock(side_effect=fetch_message),
    )
    guild = SimpleNamespace(get_channel=Mock(return_value=channel))
    interaction = SimpleNamespace(
        guild_id=1, guild=guild, response=SimpleNamespace(defer=AsyncMock()),
    )

    async def execute(query, args):
        events.append("db")
        assert "UPDATE ticket_panels_v2" in query
        assert args == (55, 33, 77)

    db = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    cog = Tickets.__new__(Tickets)
    cog.bot = SimpleNamespace(db=db)
    cog.get_panel = AsyncMock(return_value={"channel_id": 33, "message_id": 44})
    cog.get_panel_types = AsyncMock(return_value=[{"id": 1}])
    cog.build_public_panel = AsyncMock(return_value=object())
    return cog, interaction, channel, old, msg, db, events


@pytest.mark.asyncio
async def test_remplacement_publish_db_puis_supprime_ancien():
    cog, interaction, channel, old, msg, db, events = context()

    async def send(where, *_args, **_kwargs):
        assert where is channel
        events.append("send_new")
        return msg

    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=send)), \
         patch("cogs.tickets.sx_panels.texte_court", AsyncMock()) as feedback:
        await cog.send_panel(interaction, 77)

    assert events == ["send_new", "db", "fetch_old", "delete_old"]
    msg.delete.assert_not_awaited()
    assert "publié" in feedback.await_args.args[1]
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)


@pytest.mark.asyncio
async def test_envoi_impossible_conserve_ancien_et_base():
    cog, interaction, channel, old, msg, db, events = context()
    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=RuntimeError("Discord HS"))), \
         patch("cogs.tickets.sx_panels.texte_court", AsyncMock()) as feedback:
        await cog.send_panel(interaction, 77)

    db.execute.assert_not_awaited()
    channel.fetch_message.assert_not_awaited()
    old.delete.assert_not_awaited()
    assert "ancien reste disponible" in feedback.await_args.args[1]
    assert events == []


@pytest.mark.asyncio
async def test_erreur_base_rollback_nouveau_sans_supprimer_ancien():
    cog, interaction, channel, old, msg, db, events = context()
    db.execute.side_effect = RuntimeError("SQLite HS")
    async def send(*_args, **_kwargs):
        events.append("send_new")
        return msg
    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=send)), \
         patch("cogs.tickets.sx_panels.texte_court", AsyncMock()) as feedback:
        await cog.send_panel(interaction, 77)

    assert events == ["send_new", "delete_new"]
    channel.fetch_message.assert_not_awaited()
    old.delete.assert_not_awaited()
    msg.delete.assert_awaited_once()
    assert "ancien reste disponible" in feedback.await_args.args[1]


@pytest.mark.asyncio
async def test_old_deja_supprime_ne_casse_pas_nouveau():
    import discord
    cog, interaction, channel, old, msg, db, events = context()
    channel.fetch_message.side_effect = discord.NotFound(Mock(status=404, reason="Not Found"), "Missing")
    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(return_value=msg)), \
         patch("cogs.tickets.sx_panels.texte_court", AsyncMock()) as feedback:
        await cog.send_panel(interaction, 77)

    db.execute.assert_awaited_once()
    old.delete.assert_not_awaited()
    msg.delete.assert_not_awaited()
    assert "publié" in feedback.await_args.args[1]
