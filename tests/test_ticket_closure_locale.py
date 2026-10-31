"""Les fermetures de tickets suivent la langue du serveur sans altérer l'audit."""
from __future__ import annotations

from types import SimpleNamespace
import discord

from services import ticket_log_report as report
from services import ticket_panels_v3
from utils import wide_logs


OWNER = 111111111111111111
CLOSER = 333333333333333333
STAFF = 222222222222222222


def walk(nodes):
    for item in nodes:
        yield item
        yield from walk(getattr(item, "children", ()))


def content(view):
    return "\n".join(str(item.content) for item in walk(view.children)
                     if isinstance(item, discord.ui.TextDisplay))


def closure():
    ticket = {"id": 89, "user_id": OWNER, "claimed_by": STAFF,
              "created_at": 1700000000, "category": "Support"}
    events = [
        {"event": "ticket_open", "actor_id": OWNER, "created_at": 1700000000},
        {"event": "ticket_claim", "actor_id": STAFF, "created_at": 1700000060},
    ]
    state = report.build_report(ticket, events, closed_at=1700003600,
                                closed_by=CLOSER, reason="Fixed")
    return state


def test_english_ticket_log_is_structured_and_localized():
    embed = discord.Embed(title="🔒 Ticket closed", description="Saved privately")
    report.add_fields(embed, closure(), channel_name="support-89",
                      participant_text="Member", reference="TK-0089-3", language="en")
    rendered = content(wide_logs.WideLogView(embed, "", log_type="ticket_close", language="en"))
    for token in ("Ticket closed", "Ticket record", "Times & duration",
                  "Support team", "Closing reason", "Recent actions",
                  "Opened by", "Closed by", "Claimed", "Fixed"):
        assert token in rendered, token
    for unwanted in ("Dossier du ticket", "Horaires & durée", "Motif de fermeture",
                     "Aucune prise en charge"):
        assert unwanted not in rendered, unwanted


def test_french_ticket_log_remains_unchanged():
    embed = discord.Embed(title="🔒 Fermeture du ticket", description="Enregistré")
    report.add_fields(embed, closure(), channel_name="support-89",
                      participant_text="Membre", reference="TK-0089-3")
    rendered = content(wide_logs.WideLogView(embed, "", log_type="ticket_close"))
    assert "Dossier du ticket" in rendered
    assert "Fermé par" in rendered
    assert "Dernières actions" in rendered
    assert "Motif de fermeture" in rendered


def test_closure_panel_status_and_reason_translate_without_changing_reason():
    closer = SimpleNamespace(mention=f"<@{CLOSER}>", id=CLOSER)
    params = dict(ticket_id=89, opener_id=OWNER, closer=closer, reason="Fixed",
                  duration="1 h", transcript_filename=None)
    english = content(ticket_panels_v3.closed_card(**params, language="en"))
    french = content(ticket_panels_v3.closed_card(**params, language="fr"))
    for token in ("Closed", "Closure", "Reason", "closed by", "Fixed"):
        assert token in english, token
    assert "Fermé" not in english
    assert "Clôture" in french and "Raison" in french
