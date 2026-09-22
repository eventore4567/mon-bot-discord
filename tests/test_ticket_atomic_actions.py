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

def test_active_ticket_security_patch_is_also_compare_and_set():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "ticket_claim_security.py"
    ).read_text(encoding="utf-8")

    claim = source.split("async def secure_claim", 1)[1].split(
        "async def secure_unclaim", 1
    )[0]
    assert "claimed_by IS NULL" in claim
    assert "claimed_by = ?" in claim
    assert "rowcount" in claim

    unclaim = source.split("async def secure_unclaim", 1)[1].split(
        "tickets.Tickets.log_action", 1
    )[0]
    assert "status = 'ouvert' AND claimed_by = ?" in unclaim
    assert "rowcount" in unclaim

    close = source.split("async def secure_close_ticket", 1)[1].split(
        "async def secure_claim", 1
    )[0]
    assert "WHERE id=? AND status='ouvert'" in close
    assert "rowcount" in close

def test_v22_does_not_override_canonical_ticket_callbacks_anymore():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "cogs" / "sentrix_v22.py"
    ).read_text(encoding="utf-8")
    block = source.split("def _install_ticket_hardening", 1)[1].split(
        "def _install_ai_cache", 1
    )[0]

    assert "tickets_cog.btn_claim = types.MethodType" not in block
    assert "tickets_cog.btn_unclaim = types.MethodType" not in block
    assert "tickets_cog.close_ticket = types.MethodType" not in block
    assert "ticket_claim_security.py" in block

def test_integrity_layer_does_not_shadow_canonical_ticket_control_permissions():
    from pathlib import Path

    integrity = (
        Path(__file__).resolve().parents[1] / "cogs" / "integrity_hardening.py"
    ).read_text(encoding="utf-8")
    security = (
        Path(__file__).resolve().parents[1] / "cogs" / "ticket_claim_security.py"
    ).read_text(encoding="utf-8")

    block = integrity.split("def _install_tickets", 1)[1].split(
        "def _install_games", 1
    )[0]
    assert "staff_only_controls" not in block
    assert "tickets.handle_control_button = types.MethodType" not in block

    assert '_STAFF_ONLY_KEYS = {"claim", "unclaim", "add", "remove", "rename", "transfer", "note", "bump"}' in security
    assert 'elif key == "close":' in security
    assert 'interaction.user.id != ticket["user_id"]' in security

