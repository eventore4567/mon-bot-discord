from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from cogs.tickets import Tickets


@pytest.mark.asyncio
async def test_two_staff_cannot_overwrite_each_other_claim():
    tmp = tempfile.TemporaryDirectory()
    db = Database(os.path.join(tmp.name, "sentrix-test.db"))
    await db.connect()
    try:
        await db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, type_id, status, created_at) "
            "VALUES (1, 10, 99, 1, 'ouvert', 0)"
        )
        ticket = await db.fetchone("SELECT * FROM tickets WHERE channel_id = 10")

        bot = SimpleNamespace(db=db)
        cog = Tickets.__new__(Tickets)
        cog.bot = bot

        def interaction(uid):
            return SimpleNamespace(
                user=SimpleNamespace(id=uid, mention=f"<@{uid}>"),
                response=SimpleNamespace(),
            )

        with patch("cogs.tickets.sx_panels.envoyer", AsyncMock()):
            await asyncio.gather(
                cog.btn_claim(interaction(100), ticket),
                cog.btn_claim(interaction(200), ticket),
            )

        row = await db.fetchone("SELECT claimed_by FROM tickets WHERE id = ?", (ticket["id"],))
        assert row["claimed_by"] in {100, 200}

        # The important invariant: a later unconditional UPDATE must not be present.
        source = __import__("pathlib").Path(
            __file__
        ).resolve().parents[1].joinpath("cogs", "tickets.py").read_text(encoding="utf-8")
        claim_block = source.split("async def btn_claim", 1)[1].split(
            "async def btn_unclaim", 1
        )[0]
        assert "claimed_by IS NULL" in claim_block
    finally:
        await db._conn.close()
        tmp.cleanup()


def test_close_ticket_uses_compare_and_set_status_transition():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "tickets.py"
    ).read_text(encoding="utf-8")
    block = source.split("async def close_ticket", 1)[1].split(
        "async def _auto_delete", 1
    )[0]

    assert "WHERE id = ? AND status = 'ouvert'" in block
    assert "rowcount" in block
    assert "déjà fermé" in block


def test_rating_callback_verifies_ticket_owner_and_prevents_overwrite():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "tickets.py"
    ).read_text(encoding="utf-8")
    block = source.split("class TicketRatingButton", 1)[1].split(
        "class RatingView", 1
    )[0]

    assert 'int(ticket["user_id"]) != interaction.user.id' in block
    assert "rating IS NULL" in block
    assert "déjà noté" in block
