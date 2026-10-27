"""Rendu réel Components V2 des logs tickets SentriX.

Le ticket doit être lisible d'un coup d'oeil, avec un fichier joint à l'intérieur
du panneau, sans ajouter de bouton transcript ou supprimer les actions utiles.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import discord
import pytest

from services import ticket_log_report as report
from services import tickets as ticket_service
from utils import wide_logs

OWNER, CLAIMANT, CLOSER = 111111111111111111, 222222222222222222, 333333333333333333


def walk(children):
    for child in children:
        yield child
        yield from walk(getattr(child, "children", ()))


def ticket_embed():
    ticket = {
        "id": 425, "user_id": OWNER, "claimed_by": CLAIMANT,
        "created_at": 1700000000, "category": "Support",
    }
    events = [
        {"event": "ticket_open", "actor_id": OWNER, "created_at": 1700000000},
        {"event": "ticket_claim", "actor_id": CLAIMANT, "created_at": 1700000060},
    ]
    state = report.build_report(ticket, events, closed_at=1700003600,
                                closed_by=CLOSER, reason="Demande résolue")
    embed = discord.Embed(
        title="🔒 Fermeture du ticket", description="Ticket fermé, transcript disponible.",
        timestamp=discord.utils.utcnow(),
    )
    report.add_fields(embed, state, channel_name="ticket-demande",
                      participant_text="Membre A", reference="TK-0425-9")
    return embed


def contents(view):
    return "\n".join(str(getattr(item, "content", "")) for item in walk(view.children)
                     if isinstance(item, discord.ui.TextDisplay))


def test_close_log_uses_real_native_discord_cards_and_structured_sections():
    view = wide_logs.WideLogView(
        ticket_embed(), "", identity_name="Demandeur", identity_id=OWNER,
        log_type="ticket_close",
    )
    rendered = contents(view)
    assert "Ticket fermé · #425" in rendered
    for text in (
        "Dossier du ticket", "Horaires & durée", "Équipe de support",
        "Motif de fermeture", "Dernières actions",
        f"**Ouvert par**  <@{OWNER}>", f"**Fermé par**  <@{CLOSER}>",
        f"<@{CLAIMANT}>", "<t:1700000000:F>", "<t:1700003600:F>",
        "1 h 0 min", "1 min", "Demande résolue", "TK-0425-9",
    ):
        assert text in rendered, text
    children = list(walk(view.children))
    assert any(isinstance(item, discord.ui.Container) for item in children)
    assert sum(isinstance(item, discord.ui.TextDisplay) for item in children) < 15
    assert len(rendered) < 3000


def test_ticket_transcript_is_integrated_in_panel_as_real_file_component():
    file_name = "sentrix-ticket-425-transcript.txt"
    view = wide_logs.WideLogView(
        ticket_embed(), "", identity_name="Demandeur", identity_id=OWNER,
        log_type="ticket_close", ticket_attachment_filename=file_name,
        available_attachments={file_name},
        old_view=ticket_service.vue_voir_le_ticket(999, 123456789012345678),
    )
    children = list(walk(view.children))
    assert sum(isinstance(item, discord.ui.File) for item in children) == 1
    assert any(isinstance(item, discord.ui.ActionRow) for item in children)
    text = contents(view)
    assert "Transcript complet" in text
    assert "fichier TXT à ouvrir ou télécharger" in text
    buttons = [item for item in children if isinstance(item, discord.ui.Button)]
    assert any(item.label == "Voir le ticket" for item in buttons)
    assert not any("transcript" in (item.label or "").casefold() for item in buttons)


def test_fake_filename_does_not_add_untrusted_file_component():
    view = wide_logs.WideLogView(
        ticket_embed(), "", log_type="ticket_close",
        ticket_attachment_filename="malicious.txt",
    )
    assert not any(isinstance(item, discord.ui.File) for item in walk(view.children))


@pytest.mark.parametrize("event", (
    "ticket_open", "ticket_claim", "ticket_unclaim", "ticket_member_add",
    "ticket_member_remove", "ticket_transfer", "ticket_rename",
    "ticket_reopen", "ticket_delete", "ticket_note", "ticket_bump",
    "ticket_rating", "ticket_autoclose",
))
def test_all_other_ticket_events_still_show_their_action_and_ticket(event):
    embed = discord.Embed(title="🎫 Événement enregistré")
    embed.add_field(name="🎟️ Ticket", value="#83")
    embed.add_field(name="👤 Membre concerné", value=f"<@{OWNER}>")
    embed.add_field(name="📌 Salon", value="#ticket-test · <#123456789012345678>")
    embed.add_field(name="🔖 Référence", value="TK-0083-4")
    view = wide_logs.WideLogView(
        embed, "", identity_name="Membre", identity_id=OWNER,
        log_type=event,
    )
    body = contents(view)
    assert "#83" in body and "TK-0083-4" in body
    assert len(body) < 2500


def test_other_message_and_moderation_logs_keep_their_original_render_path():
    for event in ("message_delete", "member_warn", "role_create"):
        embed = discord.Embed(title="Journal test", description="Événement enregistré.")
        view = wide_logs.WideLogView(embed, "", log_type=event)
        body = contents(view)
        # Les événements hors tickets gardent leur narrateur métier : un
        # message supprimé sans cache affiche son fallback au lieu de reprendre
        # la description de test, ce qui est le comportement attendu.
        assert f"### {wide_logs._trace_title(event)}" in body
        assert "Dossier du ticket" not in body
        assert "Horaires & durée" not in body


def test_ticket_close_short_fields_are_sourced_from_audit_without_fake_values():
    embed = ticket_embed()
    assert wide_logs.ticket_close_blocks(embed)[0].startswith("**🎫")
    assert "Non renseigné" not in "\n".join(wide_logs.ticket_close_blocks(embed))
    embed2 = discord.Embed(title="Ticket fermé")
    sections = wide_logs.ticket_close_blocks(embed2)
    assert "Non renseigné" in "\n".join(sections)


def test_staff_report_file_still_attaches_through_canonical_log_transport():
    from pathlib import Path
    base = Path(__file__).resolve().parents[1]
    claim_src = (base / "cogs" / "ticket_claim_security.py").read_text()
    transport_src = (base / "utils" / "log_service.py").read_text()
    wide_src = (base / "utils" / "wide_logs.py").read_text()
    assert "file=report.transcript_file(transcript_text)" not in claim_src
    assert "file=transcript_file" not in claim_src
    assert "ticket_transcript_links.publish_link(" in claim_src
    assert "await ticket_transcript_html.send_closure_dm(" in claim_src
    assert "extra_file=file" in transport_src
    assert 'media=f"attachment://{filename}"' in wide_src
    assert "NO_PINGS" in wide_src
