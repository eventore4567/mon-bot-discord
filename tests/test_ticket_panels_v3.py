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


def test_ticket_banner_is_the_same_transparent_strip_as_sentrix_core():
    from utils.premium_log_banners import BANNER_FILENAME as SHARED_BANNER, get_premium_log_banner
    image_data = cards.banner_bytes()
    image = Image.open(io.BytesIO(image_data))
    assert image.format == "PNG"
    assert image.mode == "RGBA"
    assert image.size == (1200, 24)
    assert image.getpixel((0, 0))[3] == 0
    assert image_data == get_premium_log_banner().read_bytes()
    assert cards.BANNER_FILENAME == SHARED_BANNER
    assert len(image_data) < 500_000


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
    # En-tête propre : icônes SentriX si disponibles, jamais d'émojis Unicode.
    assert "Support · Ouvert" in body
    assert "🎫" not in body
    assert "🟢" not in body
    assert "Résumé automatique" not in body
    assert "sentrix-ticket-cover-v3.png" not in str(children)
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


def test_ticket_creation_confirmation_is_one_short_ephemeral_line_with_mention():
    """27/10/2026 (Jayden) : « Votre ticket a bien été ouvert : #salon », rien d'autre."""
    source = (ROOT / "cogs/tickets.py").read_text(encoding="utf-8")
    assert 'texte = f"Votre ticket a bien été ouvert : {channel.mention}"' in source
    assert "ticket_panels_v3.ticket_created_confirmation(" not in source
    # Jamais edit_original_response ici : après un defer d'update, il réécrit le panneau public.
    bloc = source[source.index('texte = f"Votre ticket a bien été ouvert'):][:900]
    assert "interaction.followup.send(" in bloc and "ephemeral=True" in bloc
    assert "edit_original_response" not in bloc


def test_private_reply_never_overwrites_the_public_ticket_panel():
    """Le panneau d'ouverture reste inchangé : la réponse éphémère part en follow-up."""
    import asyncio
    from unittest.mock import AsyncMock
    from utils import sentrix_panels as sx

    class Reponse:
        type = discord.InteractionResponseType.deferred_message_update

        def is_done(self):
            return True

    interaction = SimpleNamespace(
        id=1, response=Reponse(),
        message=SimpleNamespace(flags=SimpleNamespace(ephemeral=False)),
        edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()),
    )
    assert sx._ecraserait_un_message_public(interaction, True) is True
    assert sx._ecraserait_un_message_public(interaction, False) is False
    interaction.message.flags.ephemeral = True
    assert sx._ecraserait_un_message_public(interaction, True) is False


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


def test_close_modal_has_private_defer_and_real_acknowledgement():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")
    handler = (ROOT / "cogs" / "ticket_claim_security.py").read_text(encoding="utf-8")
    block = source[source.index("class CloseReasonModal"):source.index("class TicketNoteModal")]
    assert "await interaction.response.defer(ephemeral=True)" in block
    # Une unique carte publique est publiée ; le defer modal est simplement supprimé.
    assert "ticket_panels_v3.closed_card(" in handler
    assert "ticket_panels_v3.ticket_closed_confirmation(" not in handler
    assert "await interaction.delete_original_response()" in handler
    card = cards.ticket_closed_confirmation(
        ticket_id=9, closer=user(222222222222222222),
        reason="Problème traité", duration="42 min",
        guild_id=123456789012345678, channel_id=987654321098765432,
        channel_name="ticket-tomioka", closed_at=1700003600,
    )
    body = contents(card)
    assert "Ticket #9 fermé" in body
    assert "Problème traité" in body and "42 min" in body
    assert "<t:1700003600:F>" in body
    # Minimalisme (28/10/2026) : plus de paragraphe « Le staff peut rouvrir… », les boutons suffisent.
    assert "Le staff peut" not in body
    links = [x for x in walk(card.children) if isinstance(x, discord.ui.Button) and x.style == discord.ButtonStyle.link]
    assert len(links) == 1
    assert links[0].label == "Voir le ticket fermé"
    assert links[0].url == "https://discord.com/channels/123456789012345678/987654321098765432"
    assert card.fichiers()[0].filename == cards.BANNER_FILENAME


def test_deleted_ticket_receipt_is_compact_and_has_no_dead_channel_link():
    receipt = cards.ticket_deleted_confirmation(
        ticket_id=9, deleted_by=user(222222222222222222),
        reason="Ticket résolu", channel_name="ticket-tomioka",
        event_time=1700003650,
    )
    body = contents(receipt)
    for expected in ("Ticket #9 supprimé", "Ticket résolu", "ticket-tomioka",
                     "<t:1700003650:F>", "<@222222222222222222>",
                     "salon a été supprimé définitivement"):
        assert expected in body, expected
    assert "archives" not in body.casefold() or "archivés" in body.casefold()
    children = list(walk(receipt.children))
    assert any(isinstance(x, discord.ui.MediaGallery) for x in children)
    assert not any(isinstance(x, discord.ui.Button) for x in children)
    assert len(receipt.fichiers()) == 1


def test_failure_receipt_does_not_falsely_claim_deletion():
    view = cards.ticket_action_failure(
        ticket_id=9, action="Suppression refusée",
        explanation="Impossible de supprimer le salon.",
    )
    assert "Aucune modification" in contents(view)
    assert "Impossible de supprimer" in contents(view)
    assert "Non effectué" in contents(view)
    assert "Ticket #9" in contents(view)


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
    # 27/10/2026 (Jayden) : plus de saisie « SUPPRIMER », deux boutons.
    vue = service_tickets.ConfirmerSuppressionTicket(9, 42)
    assert not isinstance(vue, discord.ui.Modal)
    labels = [getattr(c, "label", None) for c in vue.children]
    assert labels == ["Annuler", "Confirmer la suppression"]
    assert vue.ticket_id == 9 and vue.author_id == 42


def fake_interaction(*, status="ferme", permission=True, db_error=False):
    guild = SimpleNamespace(id=999, owner_id=987654321098765432, get_member=lambda _: None)
    channel = Mock(spec=discord.TextChannel)
    channel.id = 555555555555555555
    channel.name = "ticket-test"
    channel.delete = AsyncMock(side_effect=discord.HTTPException(
        Mock(status=403, reason="Forbidden"), "Forbidden"
    ) if db_error else None)
    actor = user()
    actor.guild_permissions.manage_channels = permission
    response = SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    row = {"id": 9, "guild_id": 999, "channel_id": channel.id, "status": status,
           "user_id": 123456789012345678, "claimed_by": 222222222222222222,
           "created_at": 1700000000, "closed_at": 1700003600}
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
    extra = audit.await_args.kwargs["extra"]
    assert extra["📌 Ancien salon"] == f"#{interaction.channel.name}"
    assert extra["👤 Demandeur"].startswith("<@")
    assert extra["📁 Résultat"] == "Salon supprimé définitivement"
    notice = interaction.followup.send.await_args.kwargs
    assert notice["ephemeral"] is True
    assert isinstance(notice["view"], cards.TicketCardV3)
    assert "Ticket #9 supprimé" in contents(notice["view"])
    assert notice["files"][0].filename == cards.BANNER_FILENAME


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
    assert "file=transcript_file" not in closer
    assert "ticket_transcript_links.publish_link(" in closer
    assert "ticket_panels_v3.reopened_card(" in buttons
    assert "ConfirmerSuppressionTicket(self.ticket_id, interaction.user.id)" in buttons
    assert "send_modal(ConfirmerSuppressionTicket" not in buttons
    assert "ticket_panels_v3.opening_card(" in migration
    assert "await control_message.delete()" in migration
    assert "allowed_mentions=discord.AllowedMentions.none()" in migration
