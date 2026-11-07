"""Regression checks for direct, strictly authorized ticket panel repairs."""

from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.tickets import Tickets
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
async def test_regular_member_cannot_repair_or_publish_panel():
    db = SimpleNamespace(is_bot_creator=AsyncMock(return_value=False), fetchall=AsyncMock())
    bot = SimpleNamespace(db=db)
    cog = Tickets.__new__(Tickets)
    cog.bot = bot
    cog._ticket_repair_requests = {}
    cog.repair_published_ticket_panel = AsyncMock()
    ctx = SimpleNamespace(
        author=SimpleNamespace(id=99),
        guild=SimpleNamespace(id=10, owner_id=42),
        reply=AsyncMock(),
    )
    await Tickets.ticketrepair.callback(cog, ctx)
    cog.repair_published_ticket_panel.assert_not_awaited()
    db.fetchall.assert_not_awaited()
    assert "réservée" in ctx.reply.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_id,is_creator", [(42, False), (99, True)])
async def test_guild_owner_and_registered_bot_creator_can_repair_without_approval(
    caller_id, is_creator,
):
    db = SimpleNamespace(
        is_bot_creator=AsyncMock(return_value=is_creator),
        fetchall=AsyncMock(return_value=[{
            "id": 5, "guild_id": 10, "name": "Support",
        }]),
    )
    cog = Tickets.__new__(Tickets)
    cog.bot = SimpleNamespace(db=db)
    cog._ticket_repair_requests = {}
    cog.repair_published_ticket_panel = AsyncMock(return_value=(
        SimpleNamespace(jump_url="https://discord.com/channels/10/100/202"),
        True,
    ))
    ctx = SimpleNamespace(
        author=SimpleNamespace(id=caller_id),
        guild=SimpleNamespace(id=10, owner_id=42),
        reply=AsyncMock(),
    )

    await Tickets.ticketrepair.callback(cog, ctx)
    cog.repair_published_ticket_panel.assert_awaited_once_with(10, 5)
    assert "Panel réparé" in ctx.reply.await_args.args[0]
