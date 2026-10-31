"""Staff transcript links stay private, survive a restart and work without DMs."""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from services import ticket_transcript_links
from services.ticket_transcript_staff_button import StaffTranscriptButton, staff_may_view


OWNER = 123456789012345678
STAFF = 223456789012345678
ROLE = 323456789012345678


def fake_member(user_id: int, *, admin=False, manage=False, roles=()):
    return SimpleNamespace(
        id=user_id,
        guild_permissions=SimpleNamespace(administrator=admin, manage_channels=manage),
        roles=[SimpleNamespace(id=x) for x in roles],
    )


def test_only_server_staff_may_open_transcripts():
    guild = SimpleNamespace(owner_id=OWNER)
    assert staff_may_view(fake_member(OWNER), guild, None)
    assert staff_may_view(fake_member(STAFF, admin=True), guild, None)
    assert staff_may_view(fake_member(STAFF, manage=True), guild, None)
    assert staff_may_view(fake_member(STAFF, roles=[ROLE]), guild, ROLE)
    assert not staff_may_view(fake_member(STAFF), guild, ROLE)
    assert not staff_may_view(fake_member(STAFF, roles=[ROLE]), guild, ROLE + 1)


def test_stable_dynamic_custom_id_contains_no_transcript_token():
    button = StaffTranscriptButton(81)
    assert button.item.custom_id == "sentrix:ticket:transcript:81"
    assert button.item.style == discord.ButtonStyle.secondary
    assert "https://" not in button.item.custom_id
    assert re.fullmatch(r"sentrix:ticket:transcript:[0-9]{1,19}", button.item.custom_id)


def test_archive_saved_without_issuing_public_link(monkeypatch):
    async def exercise():
        calls = []
        class Db:
            async def execute(self, sql, values=()):
                calls.append((sql, values))
        monkeypatch.setattr(ticket_transcript_links, "ensure_schema", AsyncMock())
        await ticket_transcript_links.store_archive(
            SimpleNamespace(db=Db()),
            ticket_id=81, guild_id=1,
            channel_id=71, channel_name="ticket-test",
            transcript_text="Conversation privée",
        )
        assert len(calls) == 1
        assert "ticket_transcripts" in calls[0][0]
        assert calls[0][1][:5] == (81, 1, 71, "ticket-test", "Conversation privée")
        assert "ticket_transcript_links" not in calls[0][0]
    asyncio.run(exercise())


def test_real_closure_uses_staff_button_and_archives_before_logging():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "cogs" / "ticket_claim_security.py").read_text()
    assert "await ticket_transcript_links.store_archive(" in text
    assert 'custom_id=f"sentrix:ticket:transcript:{int(ticket_id)}"' in text
    assert text.index("await ticket_transcript_links.store_archive(") < text.index(
        '"ticket_close",\n            log_embed,'
    )
