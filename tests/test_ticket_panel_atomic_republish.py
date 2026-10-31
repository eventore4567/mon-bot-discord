"""Un panneau ticket ne doit jamais disparaître si son remplacement échoue."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.tickets import Tickets


@pytest.fixture(autouse=True)
def isoler_activation():
    # Cette suite mesure l'atomicité de publication. L'activation réelle
    # est contrôlée dans test_setup_private_compact_v121.py.
    with patch("cogs.setup_v2_core.set_module_enabled", new_callable=AsyncMock) as activate:
        yield activate


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
async def test_republication_actualise_le_message_existant_sans_doublon():
    cog, interaction, channel, old, msg, db, events = context()

    async def send(where, *_args, **_kwargs):
        assert where is channel
        events.append("send_new")
        return msg

    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=send)), \
         patch("cogs.tickets.sx_panels.editer", AsyncMock(side_effect=lambda *_: events.append("edit_old"))), \
         patch("cogs.tickets.sx_panels.texte_court", AsyncMock()) as feedback:
        await cog.send_panel(interaction, 77)

    assert events == ["fetch_old", "edit_old"]
    db.execute.assert_not_awaited()
    msg.delete.assert_not_awaited()
    assert "actualisé" in feedback.await_args.args[1]
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)


@pytest.mark.asyncio
async def test_envoi_impossible_conserve_ancien_et_base():
    cog, interaction, channel, old, msg, db, events = context()
    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=RuntimeError("Discord HS"))), \
         patch("cogs.tickets.sx_panels.editer", AsyncMock(side_effect=RuntimeError("Discord HS"))), \
         patch("cogs.tickets.sx_panels.texte_court", AsyncMock()) as feedback:
        await cog.send_panel(interaction, 77)

    db.execute.assert_not_awaited()
    channel.fetch_message.assert_awaited_once_with(44)
    old.delete.assert_not_awaited()
    assert "ancien reste disponible" in feedback.await_args.args[1]
    assert events == ["fetch_old"]


@pytest.mark.asyncio
async def test_erreur_base_rollback_nouveau_sans_supprimer_ancien():
    cog, interaction, channel, old, msg, db, events = context()
    db.execute.side_effect = RuntimeError("SQLite HS")
    import discord
    channel.fetch_message.side_effect = discord.NotFound(Mock(status=404, reason="Not Found"), "Missing")
    async def send(*_args, **_kwargs):
        events.append("send_new")
        return msg
    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=send)), \
         patch("cogs.tickets.sx_panels.texte_court", AsyncMock()) as feedback:
        await cog.send_panel(interaction, 77)

    assert events == ["send_new", "delete_new"]
    channel.fetch_message.assert_awaited_once_with(44)
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
    assert "actualisé" in feedback.await_args.args[1]


@pytest.mark.asyncio
async def test_deux_publications_simultanees_restent_serialisees():
    cog, first_interaction, channel, old, first_msg, db, events = context()
    second_msg = SimpleNamespace(id=66, delete=AsyncMock())
    second_interaction = SimpleNamespace(
        guild_id=1,
        guild=first_interaction.guild,
        response=SimpleNamespace(defer=AsyncMock()),
    )
    current = {"id": 44}
    initial_message = old
    stored_messages = {44: initial_message, 55: first_msg, 66: second_msg}
    first_msg.delete = AsyncMock(side_effect=lambda: events.append("delete_55"))
    second_msg.delete = AsyncMock(side_effect=lambda: events.append("delete_66"))

    async def fresh_panel(_id):
        return {"channel_id": 33, "message_id": current["id"]}

    async def edit(_message, *_args, **_kwargs):
        events.append("edit")
        # Laisser l'autre interaction se présenter au verrou.
        await asyncio.sleep(0)

    async def persist(_sql, args):
        events.append("db")
        current["id"] = args[0]

    async def fetch(mid):
        events.append(f"fetch_{mid}")
        return stored_messages[mid]

    channel.fetch_message.side_effect = fetch
    cog.get_panel.side_effect = fresh_panel
    db.execute.side_effect = persist

    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.editer", AsyncMock(side_effect=edit)), \
         patch("cogs.tickets.sx_panels.texte_court", AsyncMock()):
        await asyncio.gather(
            cog.send_panel(first_interaction, 77),
            cog.send_panel(second_interaction, 77),
        )

    assert current["id"] == 44
    assert events == [
        "fetch_44", "edit",
        "fetch_44", "edit",
    ]
    second_msg.delete.assert_not_awaited()
