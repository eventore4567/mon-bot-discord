"""SentriX Ticket Cards V3 — vrai rendu Discord, contrôle et sécurité de suppression."""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from PIL import Image

from cogs import tickets as commands_tickets
from cogs import ticket_controls_minimal
from services import ticket_panels_v3 as cards
from services import tickets as service_tickets
from utils import sentrix_panels as sx_panels

ROOT = Path(__file__).resolve().parents[1]


def user(identifier=123456789012345678):
    return SimpleNamespace(
        id=identifier,
        mention=f"<@{identifier}>",
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/avatars/1/a.png"),
        guild_permissions=SimpleNamespace(manage_channels=True, administrator=False),
    )


def walk(children):
    for child in children:
        yield child
        yield from walk(getattr(child, "children", ()))


def contents(view):
    return "\n".join(
        str(getattr(item, "content", ""))
        for item in walk(view.children)
        if isinstance(item, discord.ui.TextDisplay)
    )


def test_ticket_banner_is_real_image_not_invisible_24px_strip():
    image_data = cards.banner_bytes()
    image = Image.open(io.BytesIO(image_data))
    assert image.format == "PNG"
    assert image.size == (1200, 172)
    assert len(image_data) > 1000
    assert len(image_data) < 500_000
    assert cards.banner_bytes() is cards.banner_bytes()


def test_new_ticket_open_panel_contains_banner_answers_and_two_main_actions():
    maker = user()
    staff = SimpleNamespace(mention="<@&666666666666666666>")
    panel = cards.opening_card(
        ticket_number=9,
        ticket_type="Support SentriX",
        opener=maker,
        description="Décris ta demande ici.",
        staff_role=staff,
        answers=[("Votre question", "Le dashboard affiche une ancienne interface")],
    )
    panel = sx_panels.avec_composants(
        panel, commands_tickets.TicketControlView(commands_tickets.default_button_settings())
    )
    children = list(walk(panel.children))
    body = contents(panel)
    assert "Ticket #9" in body
    assert "Votre question" in body
    assert maker.mention in body and staff.mention in body
    assert "CENTRE DE SUPPORT" in body
    assert "Résumé automatique" not in body
    assert any(isinstance(child, discord.ui.MediaGallery) for child in children)
    buttons = [
        x.custom_id for x in children
        if isinstance(x, discord.ui.Button) and x.custom_id
    ]
    assert "ticket_ctrl_claim" in buttons
    assert "ticket_ctrl_close" in buttons
    assert len(panel.fichiers()) == 1
    assert panel.fichiers()[0].filename == cards.BANNER_FILENAME


def test_ticket_creation_receipt_is_navigable_and_never_says_inconnu():
    receipt = cards.ticket_created_confirmation(
        ticket_number=9,
        ticket_type="Support SentriX",
        guild_id=123456789012345678,
        channel_id=987654321098765432,
        channel_name="ticket-tomioka",
    )
    children = list(walk(receipt.children))
    text = contents(receipt)
    assert "Ticket #9 créé" in text
    assert "Support SentriX" in text
    assert "`#ticket-tomioka`" in text
    assert "# inconnu" not in text
    assert "Ce qui suit" not in text
    assert "Votre ticket est prêt" not in text
    assert "en attente de prise en charge" in text
    assert any(isinstance(item, discord.ui.MediaGallery) for item in children)
    assert receipt.fichiers()[0].filename == cards.BANNER_FILENAME
    links = [
        item for item in children
        if isinstance(item, discord.ui.Button)
        and item.style == discord.ButtonStyle.link
    ]
    assert len(links) == 1
    assert links[0].label == "Ouvrir mon ticket"
    assert links[0].url == (
        "https://discord.com/channels/123456789012345678/987654321098765432"
    )
    assert not links[0].custom_id


def test_ticket_creation_confirmation_uses_real_destination_in_runtime():
    source = (ROOT / "cogs/tickets.py").read_text(encoding="utf-8")
    assert "ticket_panels_v3.ticket_created_confirmation(" in source
    assert "guild_id=int(guild.id)" in source
    assert "channel_id=int(channel.id)" in source
    assert "channel_name=str(channel.name)" in source
    assert "ephemere=True" in source
    # Do not silently regress to the former oversized response.
    assert 'titre="Ticket ouvert"' not in source
    assert 'sous_titre=f"Votre ticket est prêt dans {channel.mention}."' not in source


def test_closed_ticket_has_native_downloadable_file_reopen_and_delete():
    opener = user(123456789012345678)
    closer = user(222222222222222222)
    panel = cards.closed_card(
        ticket_id=9, opener_id=opener.id, closer=closer,
        reason="Demande résolue", duration="34 min",
        transcript_filename="transcript-ticket-9.txt",
        avatar_url=str(opener.display_avatar.url),
        claimed_by_id=444444444444444444,
        closed_at=1700003600,
    )
    panel = sx_panels.avec_composants(panel, service_tickets.vue_ticket_ferme(9))
    body = contents(panel)
    children = list(walk(panel.children))
    assert "Ticket #9 · Fermé" in body
    assert opener.mention in body and closer.mention in body
    assert "Demande résolue" in body and "34 min" in body
    assert "<@444444444444444444>" in body
    assert "<t:1700003600:F>" in body
    assert "Transcription du ticket" in body
    assert "Rouvrir" in [getattr(x, "label", "") for x in children] or \
        "Rouvrir" in [getattr(getattr(x, "item", None), "label", "") for x in children]
    assert any(isinstance(x, discord.ui.File) for x in children)
    assert any(isinstance(x, discord.ui.MediaGallery) for x in children)
    assert sum(isinstance(x, discord.ui.Container) for x in children) == 1


def test_reopened_card_restores_complete_buttons_and_banner():
    moderator = user()
    panel = sx_panels.avec_composants(
        cards.reopened_card(ticket_id=42, by=moderator),
        commands_tickets.TicketControlView(commands_tickets.default_button_settings()),
    )
    assert "Ticket #42 · Rouvert" in contents(panel)
    assert "Réouvert par" in contents(panel)
    assert any(isinstance(x, discord.ui.MediaGallery) for x in walk(panel.children))


def test_delete_button_requires_real_confirmation_form():
    panel = service_tickets.vue_ticket_ferme(9)
    delete = next(x for x in panel.children if getattr(x, "custom_id", "").startswith("sx_ticket_del:"))
    assert delete.item.style is discord.ButtonStyle.danger
    modal = service_tickets.ConfirmerSuppressionTicket(9)
    assert modal.reason.required is False
    assert modal.confirmation.required is True
    assert modal.confirmation.min_length == 9
    assert modal.confirmation.max_length == 9
    assert modal.ticket_id == 9


def fake_interaction(*, status="ferme", permission=True, db_error=False):
    guild = SimpleNamespace(id=999, owner_id=987654321098765432)
    channel = Mock(spec=discord.TextChannel)
    channel.id = 555555555555555555
    channel.delete = AsyncMock(side_effect=discord.HTTPException(
        Mock(status=403, reason="Forbidden"), "Forbidden"
    ) if db_error else None)
    actor = user()
    actor.guild_permissions.manage_channels = permission
    response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    row = {"id": 9, "guild_id": 999, "channel_id": channel.id, "status": status}
    db = SimpleNamespace(
        fetchone=AsyncMock(return_value=row),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
    )
    client = SimpleNamespace(db=db)
    interaction = SimpleNamespace(
        guild=guild, channel=channel, user=actor, response=response,
        followup=followup, client=client,
    )
    return interaction


@pytest.mark.asyncio
async def test_delete_fails_closed_status_guard_without_deleting(monkeypatch):
    interaction = fake_interaction(status="ouvert")
    monkeypatch.setattr(service_tickets, "journaliser_evenement", AsyncMock())
    await service_tickets.supprimer_ticket_apres_confirmation(
        interaction, ticket_id=9, raison="Terminé"
    )
    interaction.channel.delete.assert_not_awaited()
    interaction.client.db.execute.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_refuses_non_staff_without_side_effects(monkeypatch):
    interaction = fake_interaction(permission=False)
    monkeypatch.setattr(service_tickets, "journaliser_evenement", AsyncMock())
    await service_tickets.supprimer_ticket_apres_confirmation(
        interaction, ticket_id=9, raison="Terminé"
    )
    interaction.channel.delete.assert_not_awaited()
    interaction.client.db.fetchone.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirmed_delete_logs_real_staff_reason_and_deletes_closed_channel(monkeypatch):
    interaction = fake_interaction()
    audit = AsyncMock(return_value="TKT-9")
    monkeypatch.setattr(service_tickets, "journaliser_evenement", audit)
    await service_tickets.supprimer_ticket_apres_confirmation(
        interaction, ticket_id=9, raison="Assistance terminée"
    )
    interaction.response.defer.assert_awaited_once()
    interaction.channel.delete.assert_awaited_once()
    assert "Assistance terminée" in interaction.channel.delete.await_args.kwargs["reason"]
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["raison"] == "Assistance terminée"
    assert audit.await_args.kwargs["avec_bouton"] is False


@pytest.mark.asyncio
async def test_discord_delete_error_rolls_back_durable_ticket_status(monkeypatch):
    interaction = fake_interaction(db_error=True)
    audit = AsyncMock()
    monkeypatch.setattr(service_tickets, "journaliser_evenement", audit)
    await service_tickets.supprimer_ticket_apres_confirmation(
        interaction, ticket_id=9, raison="Vérification"
    )
    audit.assert_not_awaited()
    assert interaction.client.db.execute.await_count == 2
    assert "status='ferme'" in interaction.client.db.execute.await_args.args[0]
    interaction.followup.send.assert_awaited_once()


def test_ticket_open_and_close_use_v3_in_real_runtime():
    opener = (ROOT / "cogs/tickets.py").read_text(encoding="utf-8")
    closer = (ROOT / "cogs/ticket_claim_security.py").read_text(encoding="utf-8")
    buttons = (ROOT / "services/tickets.py").read_text(encoding="utf-8")
    migration = (ROOT / "cogs/ticket_controls_minimal.py").read_text(encoding="utf-8")
    for token in (
        "ticket_panels_v3.opening_card(", "view=control_card",
        "files=control_card.fichiers()", "users=[user]",
        "roles=[staff_ping] if staff_ping else []",
    ):
        assert token in opener, token
    assert 'embed=e,' not in opener
    assert "ticket_panels_v3.closed_card(" in closer
    assert "file=transcript_file" in closer
    assert "ticket_panels_v3.reopened_card(" in buttons
    assert "ConfirmerSuppressionTicket(self.ticket_id)" in buttons
    assert "ticket_panels_v3.opening_card(" in migration
    assert "await control_message.delete()" in migration
    assert "allowed_mentions=discord.AllowedMentions.none()" in migration
