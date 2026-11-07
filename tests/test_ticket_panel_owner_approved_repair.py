"""Regression checks for permission-free requests and owner-approved panel repairs."""

from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.tickets import TicketPanelRepairApprovalView, Tickets
from database.db import Database


@pytest.mark.asyncio
async def test_repair_preserves_panel_and_types_and_removes_old_message():
    with tempfile.TemporaryDirectory() as folder:
        db = Database(os.path.join(folder, "ticketrepair.db"))
        await db.connect()
        try:
            await db.execute(
                "INSERT INTO ticket_panels_v2 "
                "(id,guild_id,name,title,description,channel_id,message_id,enabled,style) "
                "VALUES (1,10,'Support','Help','Original description',100,101,1,'select')"
            )
            await db.execute(
                "INSERT INTO ticket_types "
                "(id,panel_id,guild_id,name,staff_role_id,category_id) "
                "VALUES (3,1,10,'Questions',999,123)"
            )

            old = SimpleNamespace(author=SimpleNamespace(id=88), delete=AsyncMock())
            channel = MagicMock(spec=discord.TextChannel)
            channel.fetch_message = AsyncMock(return_value=old)
            guild = SimpleNamespace(get_channel=lambda cid: channel if cid == 100 else None)
            new = SimpleNamespace(id=202, jump_url="https://discord.com/channels/10/100/202", delete=AsyncMock())
            bot = SimpleNamespace(
                db=db,
                get_guild=lambda gid: guild if gid == 10 else None,
                user=SimpleNamespace(id=88),
                add_view=MagicMock(),
            )
            cog = Tickets.__new__(Tickets)
            cog.bot = bot
            cog._ticket_repair_locks = {}

            with patch("cogs.tickets.sx_panels.envoyer", new_callable=AsyncMock, return_value=new), \
                 patch("cogs.tickets.sx_panels.depuis_embed", return_value=object()), \
                 patch("cogs.tickets.sx_panels.avec_composants", return_value=object()):
                message, removed = await cog.repair_published_ticket_panel(10, 1)

            assert message.id == 202
            assert removed is True
            old.delete.assert_awaited_once()
            bot.add_view.assert_called_once()
            row = await db.fetchone("SELECT * FROM ticket_panels_v2 WHERE id=1")
            assert row["message_id"] == 202
            assert row["name"] == "Support"
            assert row["description"] == "Original description"
            assert row["channel_id"] == 100
            kind = await db.fetchone("SELECT * FROM ticket_types WHERE id=3")
            assert kind["panel_id"] == 1
            assert kind["staff_role_id"] == 999
            assert kind["category_id"] == 123
        finally:
            await db._conn.close()


@pytest.mark.asyncio
async def test_repair_send_failure_leaves_old_message_and_database_unchanged():
    with tempfile.TemporaryDirectory() as folder:
        db = Database(os.path.join(folder, "ticketrepair.db"))
        await db.connect()
        try:
            await db.execute(
                "INSERT INTO ticket_panels_v2 "
                "(id,guild_id,name,channel_id,message_id,enabled) "
                "VALUES (1,10,'Support',100,101,1)"
            )
            await db.execute(
                "INSERT INTO ticket_types (id,panel_id,guild_id,name) "
                "VALUES (3,1,10,'Questions')"
            )
            old = SimpleNamespace(author=SimpleNamespace(id=88), delete=AsyncMock())
            channel = MagicMock(spec=discord.TextChannel)
            channel.fetch_message = AsyncMock(return_value=old)
            guild = SimpleNamespace(get_channel=lambda _: channel)
            bot = SimpleNamespace(
                db=db, get_guild=lambda _: guild, user=SimpleNamespace(id=88)
            )
            cog = Tickets.__new__(Tickets)
            cog.bot = bot
            cog._ticket_repair_locks = {}
            with patch("cogs.tickets.sx_panels.envoyer", new_callable=AsyncMock, side_effect=RuntimeError("Discord error")), \
                 patch("cogs.tickets.sx_panels.depuis_embed", return_value=object()), \
                 patch("cogs.tickets.sx_panels.avec_composants", return_value=object()):
                with pytest.raises(RuntimeError):
                    await cog.repair_published_ticket_panel(10, 1)
            assert (await db.fetchone("SELECT message_id FROM ticket_panels_v2 WHERE id=1"))["message_id"] == 101
            old.delete.assert_not_awaited()
        finally:
            await db._conn.close()


@pytest.mark.asyncio
async def test_only_current_guild_owner_can_approve():
    guild = SimpleNamespace(owner_id=42)
    bot = SimpleNamespace(get_guild=lambda _: guild)
    cog = SimpleNamespace(bot=bot)
    view = TicketPanelRepairApprovalView(cog, 10, 3, 42, 99)
    response = SimpleNamespace(send_message=AsyncMock())

    assert not await view.interaction_check(SimpleNamespace(user=SimpleNamespace(id=99), response=response))
    response.send_message.assert_awaited_once()

    assert await view.interaction_check(SimpleNamespace(user=SimpleNamespace(id=42), response=response))
    guild.owner_id = 77
    assert not await view.interaction_check(SimpleNamespace(user=SimpleNamespace(id=42), response=response))
    view.stop()
