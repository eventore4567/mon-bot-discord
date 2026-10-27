"""Logs de tickets : acteurs, horaires, prises en charge et transcript staff."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from services import ticket_log_report as reports
from utils import wide_logs

OWNER = 111111111111111111
STAFF1 = 333333333333333333
STAFF2 = 222222222222222222
CLOSER = 444444444444444444
CREATED, CLOSED = 1700000000, 1700003600


@pytest.fixture
def ticket():
    return {"id": 425, "guild_id": 999, "user_id": OWNER, "category": "Assistance",
            "created_at": CREATED, "claimed_by": STAFF2, "status": "ouvert"}


@pytest.fixture
def events():
    return [
        {"event": "ticket_open", "actor_id": OWNER, "created_at": CREATED},
        {"event": "ticket_claim", "actor_id": STAFF1, "created_at": CREATED + 120},
        {"event": "ticket_unclaim", "actor_id": STAFF1, "created_at": CREATED + 200},
        {"event": "ticket_claim", "actor_id": STAFF2, "created_at": CREATED + 250},
        {"event": "ticket_note", "actor_id": STAFF2, "created_at": CREATED + 310, "details": "Note interne privée"},
        {"event": "ticket_close", "actor_id": CLOSER, "created_at": CLOSED},
    ]


def report(ticket, events, **kwargs):
    return reports.build_report(ticket, events, closed_at=CLOSED, closed_by=CLOSER,
                                reason="Problème résolu", **kwargs)


def test_report_traces_actual_staff_and_durations(ticket, events):
    r = report(ticket, events)
    assert r.owner_id == OWNER and r.closed_by == CLOSER
    assert r.handlers == (STAFF1, STAFF2)
    assert r.current_handler == f"<@{STAFF2}>"
    assert r.duration == "1 h 0 min"
    assert r.first_claim_wait == "2 min"
    assert len([e for e in r.events if e[0] == "ticket_close"]) == 1


def test_staff_transcript_has_metadata_actions_and_messages_but_not_note_content(ticket, events):
    r = report(ticket, events)
    file = r.transcript_file("bonjour\nréponse du staff\n")
    assert file.filename == "sentrix-ticket-425-transcript.txt"
    content = file.fp.read().decode("utf-8")
    for marker in (f"Ouvert par : <@{OWNER}>", f"Fermé par : <@{CLOSER}>",
                   f"<@{STAFF1}>", f"<@{STAFF2}>", "1 h 0 min",
                   "Première prise en charge après : 2 min",
                   "Prise en charge libérée", "bonjour\nréponse du staff"):
        assert marker in content, marker
    assert "Note interne privée" not in content


def test_wide_log_shows_short_dates_claimants_and_reason(ticket, events):
    r = report(ticket, events)
    embed = discord.Embed(title="🔒 Fermeture du ticket",
                          description=f"Ticket #425 fermé par <@{CLOSER}>.")
    reports.add_fields(embed, r, channel_name="ticket-support",
                       participant_text="Alice\nStaff", reference="TK-0425-33")
    mapping = dict(wide_logs._field_map(embed))
    assert mapping["🕒 Ouverture"] == f"<t:{CREATED}:F>"
    assert mapping["🕒 Fermeture"] == f"<t:{CLOSED}:F>"
    assert mapping["⏱️ Avant première prise en charge"] == "2 min"
    assert mapping["⏳ Durée totale"] == "1 h 0 min"
    assert mapping["🔖 Référence"] == chr(96) + "TK-0425-33" + chr(96)
    body = wide_logs.narrative_body(embed, log_type="ticket_close",
                                    identity_name="Alice", identity_id=OWNER)
    for marker in ("Ouverture", "Fermeture", "Pris en charge",
                   "Équipe ayant pris en charge", "Avant première prise en charge",
                   "Durée totale", "Motif", "TK-0425-33"):
        assert marker in body, marker
    assert f"**Ouvert par :** <@{OWNER}>" in body
    assert f"**Fermé par :** <@{CLOSER}>" in body
    compact = wide_logs.compact_fields(embed)
    assert "**📝 Motif :**" not in compact
    assert "🧭 Historique" in compact
    assert "👥 Participants" in compact


def test_no_claim_never_creates_fictional_staff(ticket):
    r = reports.build_report(dict(ticket, claimed_by=None, created_at=CREATED + 100), [],
                             closed_at=CREATED + 40, closed_by=CLOSER, reason="")
    assert r.current_handler == "Non pris en charge"
    assert r.first_claim_wait == "Aucune prise en charge enregistrée"
    assert r.duration is None
    assert r.reason == "Non précisée"


def test_legacy_claims_work_without_duplicate_owner(ticket):
    r = report(ticket, [], legacy_claims=[{"staff_id": STAFF2, "claimed_at": CREATED + 120}])
    assert r.handlers == (STAFF2,)
    assert r.first_claim_wait == "2 min"


@pytest.mark.asyncio
async def test_audit_unavailable_does_not_block_close(ticket):
    bot = SimpleNamespace(db=SimpleNamespace(fetchall=AsyncMock(side_effect=RuntimeError("offline"))))
    r = await reports.load_report(bot, 999, ticket,
                                  closed_at=CLOSED, closed_by=CLOSER, reason="OK")
    assert r.current_handler == f"<@{STAFF2}>"
    assert r.owner_id == OWNER
    assert r.duration == "1 h 0 min"


@pytest.mark.asyncio
async def test_history_query_scoped_to_ticket_and_guild(ticket, events):
    db = SimpleNamespace(fetchall=AsyncMock(return_value=events))
    r = await reports.load_report(SimpleNamespace(db=db), 999, ticket,
                                  closed_at=CLOSED, closed_by=CLOSER, reason="OK")
    assert r.first_claim_wait == "2 min"
    sql, params = db.fetchall.await_args.args
    assert "guild_id=?" in sql and "ticket_id=?" in sql
    assert params == (999, 425)


def test_new_html_dm_and_existing_audit_ticket_view_are_preserved():
    source = (Path(__file__).resolve().parents[1] / "cogs" / "ticket_claim_security.py").read_text()
    assert "ticket_log_report.load_report(" in source
    assert "file=report.transcript_file(transcript_text)" not in source
    assert "ticket_transcript_html.transcript_html_file(" not in source
    assert "ticket_transcript_links.publish_link(" in source
    assert "await ticket_transcript_html.send_closure_dm(" in source
    assert 'actor_id=interaction.user.id' in source
    assert "vue_voir_le_ticket(guild.id, channel.id)" in source
