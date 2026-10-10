"""Régressions observées le 10 octobre 2026 : logs de jeux et refus de hiérarchie.

Les cartes doivent conserver leur structure sans notifications indésirables.
Les confirmations de sanctions ordinaires restent en texte court.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs.moderation import Moderation, _hierarchy_refusal_panel
from utils import game_rewards, log_categories, sentrix_panels, wide_logs


def test_refus_hierarchie_saffiche_dans_un_vrai_panneau():
    from utils.checks import check_bot_hierarchy

    message = (
        "SentriX ne peut pas sanctionner ce membre : son rôle le plus élevé "
        "est au-dessus de celui de SentriX. Remontez le rôle **SentriX** "
        "dans Paramètres du serveur > Rôles."
    )
    panel = _hierarchy_refusal_panel(message)

    assert isinstance(panel, sentrix_panels.Panneau)
    assert panel.kind == "warning"
    rendu = sentrix_panels.texte_complet(panel)
    assert "Sanction impossible" in rendu
    assert "Comment corriger" in rendu
    assert "Paramètres du serveur" in rendu
    assert "SentriX" in rendu
    # La couche de présentation ne doit PAS aplatir cette carte en texte brut.
    with patch.object(sentrix_panels, "_commande_en_cours", return_value=("ban", "Moderation")):
        assert sentrix_panels._panneau_est_erreur_simple(panel) is False
    # La validation de permission n'est pas modifiée par la présentation.
    assert callable(check_bot_hierarchy)


def test_seules_les_hierarchies_compliquees_deviennent_des_panneaux():
    assert _hierarchy_refusal_panel("15 messages supprimés.") is None
    assert _hierarchy_refusal_panel("Il vous manque la permission de bannir.") is None
    assert _hierarchy_refusal_panel("SentriX ne peut pas gérer ce rôle : placez-le plus haut.") is not None


@pytest.mark.asyncio
async def test_reponse_moderation_choisit_la_bonne_surface():
    send_panel = AsyncMock()
    send_text = AsyncMock()
    ctx = SimpleNamespace()
    with patch.object(sentrix_panels, "envoyer", send_panel), patch.object(sentrix_panels, "texte_court", send_text):
        await Moderation._reply(
            object(),
            ctx,
            "SentriX ne peut pas sanctionner ce membre : son rôle le plus élevé est au-dessus.",
            ephemere=True,
        )
        send_panel.assert_awaited_once()
        assert send_panel.await_args.kwargs["ephemere"] is True
        send_text.assert_not_awaited()

        send_panel.reset_mock()
        await Moderation._reply(object(), ctx, "Le membre a été banni.")
        send_text.assert_awaited_once()
        send_panel.assert_not_awaited()


def test_game_reward_route_vers_serveur_et_identite_joueur():
    assert log_categories.category_for("game_reward") == "server"
    assert wide_logs._trace_identity_label("game_reward") == "Joueur"
    assert wide_logs._trace_identity_ref("game_reward", 123456789012345678) == "<@123456789012345678>"
    assert "Jeux" in wide_logs._trace_meta("game_reward")


def test_game_reward_body_separe_gain_et_reference():
    embed = discord.Embed(title="Nuit des zombies — Gagné")
    embed.add_field(name="Joueur", value="<@123456789012345678>", inline=False)
    embed.add_field(name="Récompense", value="0 🪙", inline=False)
    embed.add_field(name="Référence", value="`GAME-000042`", inline=False)
    rendu = wide_logs.narrative_body(
        embed,
        log_type="game_reward",
        identity_id=123456789012345678,
    )
    assert "**Récompense :** 0 🪙" in rendu
    assert "**Référence :** `GAME-000042`" in rendu
    assert rendu.count("GAME-000042") == 1


@pytest.mark.asyncio
async def test_game_reward_emet_le_log_structure_et_la_bonne_identite():
    member = SimpleNamespace(
        id=123456789012345678,
        display_name="tomioka",
        mention="<@123456789012345678>",
        display_avatar=SimpleNamespace(url="https://example.org/avatar.png"),
    )
    guild = SimpleNamespace(id=22, get_member=lambda user_id: member if user_id == member.id else None)
    bot = SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == guild.id else None)
    reward = game_rewards.GameReward(
        success=True,
        game_name="zombie",
        session_id="zombie:abc",
        guild_id=22,
        user_id=member.id,
        amount=0,
        result="win",
        display_id="GAME-000042",
    )
    send = AsyncMock(return_value=True)
    with patch("utils.log_service.send_log", send):
        await game_rewards._emit_game_log(bot, guild.id, reward)
    send.assert_awaited_once()
    args, kwargs = send.await_args
    assert args[2] == "game_reward"
    assert kwargs["identity_id"] == member.id
    assert kwargs["identity_name"] == "tomioka"
    assert args[3].title.endswith("— Gagné")
    champs = {field.name: field.value for field in args[3].fields}
    assert champs == {
        "Joueur": member.mention,
        "Récompense": "0 🪙",
        "Référence": "`GAME-000042`",
    }
