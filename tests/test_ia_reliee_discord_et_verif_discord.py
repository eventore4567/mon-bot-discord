"""06/11/2026 : l'IA sait qu'elle EST SentriX (permissions réelles) ; la vérification
se fait dans Discord, sans site ni « SentriX souhaite accéder à votre compte »."""
from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import ai_context_v9, verification_discord  # noqa: E402


def _perms(**actives):
    return SimpleNamespace(**actives)


def _bot(*, admin_bot=False, perms_bot=None, perms_membre=None):
    moi = SimpleNamespace(
        id=1, top_role=SimpleNamespace(name="SentriX", position=12),
        guild_permissions=_perms(administrator=True) if admin_bot else (perms_bot or _perms()),
    )
    membre = SimpleNamespace(
        id=5, display_name="Dream", top_role=SimpleNamespace(name="Meta"),
        guild_permissions=perms_membre or _perms(),
    )
    salon = SimpleNamespace(name="général", permissions_for=lambda _m: moi.guild_permissions)
    guild = SimpleNamespace(
        id=10, name="Serveur de tomioka", me=moi, member_count=3, owner_id=7,
        owner=SimpleNamespace(display_name="tomioka"),
        roles=[object()] * 14, channels=[object()] * 30,
        get_channel=lambda _cid: salon, get_member=lambda uid: membre if uid == 5 else None,
    )
    return SimpleNamespace(get_guild=lambda _gid: guild)


def test_l_ia_connait_ses_vraies_permissions_d_administrateur():
    texte = ai_context_v9.contexte_discord_reel(_bot(admin_bot=True), 10, 20, 5)
    assert "Tu ES SentriX, le bot Discord présent sur ce serveur" in texte
    assert "Tes permissions sur le serveur : Administrateur (toutes les permissions)" in texte
    assert "Ton rôle le plus haut : SentriX (position 12 sur 13)" in texte
    assert "jamais « je n'ai aucune permission »" in texte
    assert "La personne qui te parle : Dream · rôle le plus haut : Meta" in texte


def test_sans_administrateur_la_liste_reelle_est_donnee():
    bot = _bot(perms_bot=_perms(manage_messages=True, ban_members=True, send_messages=True))
    texte = ai_context_v9.contexte_discord_reel(bot, 10, 20, None)
    assert "Gérer les messages" in texte and "Bannir" in texte
    assert "Administrateur" not in texte.split("Tes permissions sur le serveur : ")[1].splitlines()[0]


def test_hors_serveur_aucun_contexte():
    assert ai_context_v9.contexte_discord_reel(_bot(), None, None, None) == ""


def test_le_prompt_dit_que_l_ia_est_le_bot_lui_meme():
    from utils import ai_service

    assert "Tu es SentriX, le bot Discord lui-même" in ai_service.SYSTEM_PROMPT
    assert "assistant intelligent officiel du bot" not in ai_service.SYSTEM_PROMPT


# ---------------------------------------------------------------- vérification Discord

def test_le_test_propose_quatre_emojis_dont_la_bonne_reponse():
    attendu, propositions = verification_discord.tirer_test()
    assert len(propositions) == 4 and len(set(propositions)) == 4
    assert attendu in propositions


def test_le_panneau_ne_renvoie_plus_vers_le_site():
    from cogs import honeypot_verification_v48 as v48

    async def langue(_bot, _gid):
        return "fr"

    from cogs import language_runtime

    original = language_runtime.get_language
    language_runtime.get_language = langue
    try:
        panneau = asyncio.run(v48._web_panel(SimpleNamespace(), SimpleNamespace(id=10)))
    finally:
        language_runtime.get_language = original
    (bouton,) = panneau.boutons_source
    assert bouton.url is None
    assert bouton.custom_id == verification_discord.BOUTON_DEMARRER
    assert bouton.libelle == "Se vérifier"
    assert callable(bouton.callback)


def _interaction(user_id=5):
    reponse = SimpleNamespace(edit_message=AsyncMock(), defer=AsyncMock(), send_message=AsyncMock())
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id), response=reponse, edit_original_response=AsyncMock(),
    )


def _test(monkeypatch, *, complete=None, verrou=0):
    from web import public_verification_v120 as web_verif

    monkeypatch.setattr(web_verif, "_record_failure", AsyncMock(return_value=verrou))
    monkeypatch.setattr(web_verif, "_complete_verification", complete or AsyncMock())
    membre = SimpleNamespace(id=5)
    guild = SimpleNamespace(id=10, get_member=lambda _uid: membre)
    return verification_discord.TestHumain(SimpleNamespace(), guild, 5, reglement=True), web_verif


def _callbacks(test):
    vue = test.vue()
    rangee = [c for c in vue.children[0].children if isinstance(c, discord.ui.ActionRow)][0]
    return {
        nom: bouton.callback
        for bouton, (_emoji, nom) in zip(rangee.children, test.propositions)
    }


def test_la_bonne_reponse_lance_les_controles_du_site_et_verifie(monkeypatch):
    complete = AsyncMock(return_value=({"already_verified": False, "channel_id": "42"}, None))
    test, web_verif = _test(monkeypatch, complete=complete)
    interaction = _interaction()
    asyncio.run(_callbacks(test)[test.attendu[1]](interaction))
    args, kwargs = complete.await_args
    assert kwargs == {"accept_rules": True, "methode": "discord+challenge"}
    vue = interaction.edit_original_response.await_args.kwargs["view"]
    assert "✅ Vérifié" in vue.children[0].children[0].content
    assert "<#42>" in vue.children[0].children[0].content


def test_un_refus_des_controles_est_explique(monkeypatch):
    from aiohttp import web

    erreur = web.json_response({"ok": False, "error": "Ton compte Discord est trop récent."}, status=429)
    test, _ = _test(monkeypatch, complete=AsyncMock(return_value=(None, erreur)))
    interaction = _interaction()
    asyncio.run(_callbacks(test)[test.attendu[1]](interaction))
    vue = interaction.edit_original_response.await_args.kwargs["view"]
    assert "Ton compte Discord est trop récent." in vue.children[0].children[0].content


def test_une_mauvaise_reponse_redonne_un_test_puis_verrouille(monkeypatch):
    test, web_verif = _test(monkeypatch)
    mauvais = next(nom for _e, nom in test.propositions if nom != test.attendu[1])
    interaction = _interaction()
    asyncio.run(_callbacks(test)[mauvais](interaction))
    web_verif._complete_verification.assert_not_awaited()
    vue = interaction.response.edit_message.await_args.kwargs["view"]
    assert "Mauvaise réponse" in vue.children[0].children[0].content

    test2, _ = _test(monkeypatch, verrou=300)
    mauvais2 = next(nom for _e, nom in test2.propositions if nom != test2.attendu[1])
    interaction2 = _interaction()
    asyncio.run(_callbacks(test2)[mauvais2](interaction2))
    vue2 = interaction2.response.edit_message.await_args.kwargs["view"]
    assert "Trop d'erreurs" in vue2.children[0].children[0].content


def test_quelqu_un_d_autre_ne_peut_pas_repondre(monkeypatch):
    test, web_verif = _test(monkeypatch)
    intrus = _interaction(user_id=99)
    asyncio.run(_callbacks(test)[test.attendu[1]](intrus))
    web_verif._complete_verification.assert_not_awaited()
    assert test.termine is False


def test_le_message_d_erreur_json_est_lu():
    reponse = SimpleNamespace(body=json.dumps({"error": "Règlement requis."}).encode())
    assert verification_discord.message_d_erreur(reponse) == "Règlement requis."
    assert "Réessayez" in verification_discord.message_d_erreur(SimpleNamespace(body=b"oops"))
