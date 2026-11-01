"""Garde la création d'image réelle et les fermetures de tickets compactes.

Ces tests ne contactent PAS l'API OpenAI. Ils simulent la réponse binaire
qui doit être envoyée comme fichier Discord, et non des pages de SVG.
"""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest
from PIL import Image

from cogs.ai import Ai
from services import ticket_log_report
from utils import wide_logs
from utils.ai_image_intents import is_image_creation_request, requested_image_size


@pytest.mark.parametrize("prompt", [
    "Recréer une capture d'écran réaliste de Discord au format 1536 x 408.",
    "SentriX crée une image avec un salon #général visible et des tickets fermés.",
    "Génère un visuel du panneau de sécurité.",
    "Fais une bannière simple pour un serveur.",
    "Draw a picture of a Discord dashboard.",
])
def test_creation_visual_request_is_detected(prompt):
    assert is_image_creation_request(prompt)


@pytest.mark.parametrize("prompt", [
    "SentriX analyse cette image",
    "Pourquoi tu ne peux pas générer une image ?",
    "Rends le salon #général visible.",
    "Ferme ce ticket et affiche les logs.",
    "Décris la capture que j'ai envoyée.",
    "Est-ce que tu peux créer des images ?",
])
def test_analysis_questions_and_real_server_actions_are_not_generation(prompt):
    assert not is_image_creation_request(prompt)


def test_requested_final_dimensions_are_exact_and_bounded():
    assert requested_image_size("Capture réaliste 1536 × 408 pixels") == (1536, 408)
    assert requested_image_size("20000 × 20000") is None
    assert requested_image_size("aucune dimension") is None


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_image_creation_sends_a_real_cropped_discord_jpeg():
    original = io.BytesIO()
    Image.new("RGB", (800, 600), color="#494e61").save(original, "JPEG")
    result = SimpleNamespace(ok=True, data=original.getvalue(), error=None)
    guild = SimpleNamespace(id=123)
    channel = SimpleNamespace(id=456, typing=lambda: _Typing(), send=AsyncMock())
    author = SimpleNamespace(id=789, roles=[SimpleNamespace(id=999)])
    message = SimpleNamespace(guild=guild, channel=channel, author=author, reply=AsyncMock())
    ai = SimpleNamespace(bot=SimpleNamespace(), _channel_blocks_ai=AsyncMock(return_value=False))
    question = (
        "Recréer une capture d'écran réaliste Discord 1536 × 408 "
        "avec un salon #général visible et une erreur de ticket fermé."
    )
    settings = dict(
        enabled=True, daily_limit=5, max_question_length=3500,
        allowed_role_ids=[], allowed_channel_ids=[],
    )
    with patch("cogs.ai.ai_service.get_settings", AsyncMock(return_value=settings)):
        with patch("cogs.ai.ai_service.get_daily_usage", AsyncMock(return_value=0)):
            with patch("cogs.ai.ai_service.generate_image", AsyncMock(return_value=result)) as generation:
                with patch("cogs.ai.ai_service.record_usage", AsyncMock()) as record:
                    assert await Ai._send_generated_image_natural(ai, message, question) is True

    generation.assert_awaited_once()
    assert generation.await_args.args[0] == question
    assert generation.await_args.kwargs["guild_id"] == 123
    record.assert_awaited_once()
    image_file = message.reply.await_args.kwargs["file"]
    assert isinstance(image_file, discord.File)
    image_file.fp.seek(0)
    with Image.open(image_file.fp) as actual:
        assert actual.size == (1536, 408)
        assert actual.format == "JPEG"
    assert "1536 × 408" in message.reply.await_args.kwargs["content"]
    assert "svg" not in message.reply.await_args.kwargs["content"].casefold()
    assert message.reply.await_args.kwargs["allowed_mentions"].everyone is False


@pytest.mark.asyncio
async def test_server_action_router_is_never_called_for_image_description():
    question = (
        "Recréer une capture Discord avec #général à nouveau visible "
        "et un bouton permettant de fermer un ticket."
    )
    msg = SimpleNamespace()
    response = AsyncMock(return_value=True)
    fake_ai = SimpleNamespace(_send_generated_image_natural=response)
    assert await Ai._invoke_natural_command(fake_ai, msg, question, "+") is True
    response.assert_awaited_once_with(msg, question)


def _embed_for_close(*, claimed_by=None):
    owner = 111111111111111111
    closer = 222222222222222222
    ticket = {
        "id": 84,
        "user_id": owner,
        "claimed_by": claimed_by,
        "created_at": 1700000000,
        "category": "Support général",
    }
    events = [
        {"event": "ticket_open", "actor_id": owner, "created_at": 1700000000},
    ]
    if claimed_by:
        events.append({
            "event": "ticket_claim", "actor_id": claimed_by,
            "created_at": 1700000060,
        })
    report = ticket_log_report.build_report(
        ticket, events, closed_at=1700000015 if not claimed_by else 1700003600,
        closed_by=closer, reason="Demande terminée",
    )
    embed = discord.Embed(title="Ticket fermé")
    ticket_log_report.add_fields(
        embed, report, channel_name="support-84",
        participant_text="Membre A", reference="TK-0084-33",
    )
    return embed


def test_ticket_without_claim_does_not_invent_or_repeat_staff():
    output = "\n".join(wide_logs.ticket_close_blocks(_embed_for_close()))
    assert "Dossier du ticket" in output
    assert "Ouvert par" in output and "<@111111111111111111>" in output
    assert "Fermé par" in output and "<@222222222222222222>" in output
    assert output.count("Aucune prise en charge enregistrée") == 1
    assert "Responsable à la clôture : Non pris en charge" not in output
    assert "Aucun membre du staff enregistré" not in output
    assert "15 s" in output
    assert "Demande terminée" in output
    assert len(output) < 950


def test_ticket_with_claim_keeps_real_handler_and_first_claim_delay():
    output = "\n".join(wide_logs.ticket_close_blocks(_embed_for_close(
        claimed_by=333333333333333333,
    )))
    assert "<@333333333333333333>" in output
    assert "Première prise" in output
    assert "1 min" in output
    assert "Dernières actions" in output
    assert len(output) < 1200


def test_close_logs_stay_french_by_default_and_english_on_request():
    embed = _embed_for_close()
    en = "\n".join(wide_logs.ticket_close_blocks(embed, language="en"))
    assert "Ticket record" in en and "Closing reason" in en
    assert "Support team" in en
    assert "Aucune prise en charge" not in en
