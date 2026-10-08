"""La migration des anciens panels tickets au boot ne doit jamais les perdre."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
from cogs.tickets import Tickets


def make_world():
    events = []

    async def delete_old():
        events.append("delete_old")

    async def delete_new():
        events.append("delete_new")

    old = SimpleNamespace(id=44, embeds=[object()], delete=AsyncMock(side_effect=delete_old))
    new = SimpleNamespace(id=55, delete=AsyncMock(side_effect=delete_new))
    channel = SimpleNamespace(id=33, fetch_message=AsyncMock(return_value=old))

    guild = SimpleNamespace(get_channel=Mock(return_value=channel))
    bot = SimpleNamespace(
        db=SimpleNamespace(
            fetchall=AsyncMock(return_value=[{
                "id": 77, "guild_id": 1, "channel_id": 33,
                "message_id": 44, "enabled": 1,
            }]),
            execute=AsyncMock(),
        ),
        get_guild=Mock(return_value=guild),
        add_view=Mock(side_effect=lambda _view, *, message_id: events.append(f"view_{message_id}")),
    )
    cog = Tickets.__new__(Tickets)
    cog.bot = bot
    cog.get_panel_types = AsyncMock(return_value=[{"id": 1}])
    cog.build_public_panel = AsyncMock(return_value=object())
    return cog, bot, old, new, channel, events


@pytest.mark.asyncio
async def test_migration_persiste_avant_de_supprimer_ancien():
    cog, bot, old, new, channel, events = make_world()

    async def send(*_args, **_kwargs):
        events.append("send_new")
        return new

    async def write(sql, args):
        assert "UPDATE ticket_panels_v2" in sql
        assert args == (55, 77)
        events.append("persist")

    bot.db.execute.side_effect = write
    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=send)), \
         patch("cogs.tickets.TicketPanelView", return_value=object()):
        restored = await cog.restore_panel_views()
    assert restored == 1
    assert events == ["send_new", "persist", "delete_old", "view_55"]
    new.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_migration_echec_db_supprime_nouveau_mais_garde_ancien():
    cog, bot, old, new, channel, events = make_world()

    async def send(*_args, **_kwargs):
        events.append("send_new")
        return new

    async def fail(_sql, _args):
        events.append("db_error")
        raise RuntimeError("SQLite unavailable")

    bot.db.execute.side_effect = fail
    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=send)), \
         patch("cogs.tickets.TicketPanelView", return_value=object()):
        restored = await cog.restore_panel_views()
    assert restored == 1
    assert events == ["send_new", "db_error", "delete_new", "view_44"]
    old.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_migration_echec_discord_conserve_lancien():
    cog, bot, old, new, channel, events = make_world()
    with patch("cogs.tickets.language_runtime.get_language", AsyncMock(return_value="fr")), \
         patch("cogs.tickets.sx_panels.envoyer", AsyncMock(side_effect=RuntimeError("Discord HS"))), \
         patch("cogs.tickets.TicketPanelView", return_value=object()):
        restored = await cog.restore_panel_views()
    assert restored == 1
    assert events == ["view_44"]
    bot.db.execute.assert_not_awaited()
    old.delete.assert_not_awaited()
