"""Retours du 07/11/2026 (suite) : insultes non averties, @everyone d'un admin,
bannière en MP, spam laissé au 1er rappel, image à améliorer en réponse."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from cogs import automod as am  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("texte", ["fpd", "vas te fair enculer", "va te faire enculer", "je te baise ta mere au foot"])
def test_les_insultes_non_averties_sont_detectees(texte):
    from utils.moderation_dataset import MultilingualModerationDataset

    trouve = MultilingualModerationDataset().match(texte)
    assert trouve is not None and trouve.confidence >= 0.92


@pytest.mark.parametrize("texte", [
    "tu vas bien ?", "je vais faire mes devoirs", "gg ez", "je te ez",          # « ez » n'est pas une insulte
    "je te baise au foot mdr", "jte baise a fifa", "on vous nique en 1v1",
])
def test_les_phrases_banales_restent_permises(texte):
    from utils.moderation_dataset import MultilingualModerationDataset

    assert MultilingualModerationDataset().match(texte) is None


def _automod_factice():
    cog = SimpleNamespace()
    cog._delete_and_warn = AsyncMock(return_value="averti")
    cog._maybe_escalate = AsyncMock(return_value=(None, 1))
    cog._delete_and_timeout = AsyncMock(return_value="mute")
    cog.get_immunity_override_cached = AsyncMock(return_value=None)
    bot = SimpleNamespace(get_cog=lambda nom: cog if nom == "Automod" else None)
    return cog, bot


def test_une_insulte_confirmee_avertit_puis_mute_a_la_recidive():
    from cogs import content_filter_policy as politique

    cog, bot = _automod_factice()
    original_avertir, original_mute = cog._delete_and_warn, cog._delete_and_timeout
    politique._patch_automod(bot)
    message = SimpleNamespace(guild=SimpleNamespace(id=1, owner_id=999), author=SimpleNamespace(id=7))

    asyncio.run(cog._delete_and_timeout(message, "insulte", detection_kind="phrase"))
    assert original_mute.await_count == 0
    kwargs = original_avertir.await_args
    assert kwargs.args[2] == "multilingual_toxicity" and "prochaine fois" in kwargs.args[1]

    asyncio.run(cog._delete_and_timeout(message, "insulte", detection_kind="phrase"))
    original_mute.assert_awaited_once()          # 2e insulte dans l'heure : mute


def test_les_options_des_avertissements_sont_transmises():
    for chemin in ("cogs/content_filter_policy.py", "cogs/forbidden_words_ui.py"):
        source = (RACINE / chemin).read_text(encoding="utf-8")
        assert "**options," in source and "**options" in source.split("original_delete_and_warn(", 2)[-1], chemin


def test_l_everyone_d_un_admin_n_est_plus_supprime_par_le_filtre_de_mentions():
    source = (RACINE / "cogs" / "security_runtime_hardening.py").read_text(encoding="utf-8")
    assert "if not message.mention_everyone and (len(message.role_mentions) >= 3" in source
    message = SimpleNamespace(delete=AsyncMock(), guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2))
    cog = am.AutoMod.__new__(am.AutoMod)
    asyncio.run(cog._incident_admin(message, "Mention massive", "antimention"))
    message.delete.assert_not_awaited()


def test_un_panneau_envoye_en_mp_n_a_pas_de_banniere():
    from utils import embeds, sentrix_panels as panels

    panneau = panels.depuis_embed(embeds.warning("test"))
    assert panneau.avec_banniere
    envoye = {}

    class MembreFactice(discord.Member):
        async def send(self, **kwargs):
            envoye.update(kwargs)

    membre = MembreFactice.__new__(MembreFactice)
    asyncio.run(panels.envoyer(membre, panneau))
    galeries = [i for c in panneau.children for i in getattr(c, "children", []) if isinstance(i, discord.ui.MediaGallery)]
    assert not galeries and not envoye.get("files")


def test_la_carte_anti_nuke_en_mp_est_coloree_et_sans_banniere():
    vue = am.carte_securite_mp(
        "Anti-nuke déclenché", {"Statut": "Serveur protégé", "Compte": "<@1>", "Action": "banni"}, serveur="Test",
    )
    carte = vue.children[0]
    assert carte.accent_colour is not None
    textes = " ".join(getattr(i, "content", "") for i in carte.children)
    assert "Anti-nuke déclenché" in textes and "Serveur protégé" in textes and "Test" in textes
    assert not any(isinstance(i, discord.ui.MediaGallery) for i in carte.children)
    assert am.carte_securite_mp("x", {}, echec=True).children[0].accent_colour.value == 0xED4245


def _message_spam(joined_days: float | None):
    from datetime import timedelta

    auteur = SimpleNamespace(
        id=7, guild_permissions=SimpleNamespace(administrator=False),
        joined_at=None if joined_days is None else discord.utils.utcnow() - timedelta(days=joined_days),
    )
    return SimpleNamespace(guild=SimpleNamespace(id=1), author=auteur)


def test_seule_la_premiere_rafale_d_un_membre_etabli_est_laissee(monkeypatch):
    monkeypatch.setattr(am, "_as_member", lambda m, g: m)
    cog = am.AutoMod.__new__(am.AutoMod)
    cog._renfort_actif = lambda gid: False
    assert cog._premier_rappel_spam(_message_spam(30)) is True     # 1re rafale : laissée
    assert cog._premier_rappel_spam(_message_spam(30)) is False    # récidive : supprimée
    assert cog._premier_rappel_spam(_message_spam(0.1)) is False   # compte récent : supprimé
    assert cog._premier_rappel_spam(_message_spam(None)) is False
    cog2 = am.AutoMod.__new__(am.AutoMod)
    cog2._renfort_actif = lambda gid: True
    assert cog2._premier_rappel_spam(_message_spam(30)) is False   # raid : tout part


def test_un_raid_revele_supprime_les_messages_laisses(monkeypatch):
    cog = am.AutoMod.__new__(am.AutoMod)
    file_ = SimpleNamespace(supprimer=AsyncMock())
    cog._purge = file_
    cog._mark_xp_skip = lambda mid: None

    async def scenario():
        cog._noter_laisses(1, [SimpleNamespace(id=10), SimpleNamespace(id=11)])
        cog._supprimer_laisses(1)
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert file_.supprimer.await_count == 2


def test_repondre_a_une_image_de_sentrix_en_genere_une_nouvelle_version():
    source = (RACINE / "cogs" / "ai.py").read_text(encoding="utf-8")
    assert 'memoire[int(envoye.id)] = description[:3000]' in source
    assert "Nouvelle version demandée : {question}" in source


def test_une_regle_de_mots_bloques_peut_muter_sur_choix():
    from cogs import mots_bloques as mb

    regle = SimpleNamespace(
        id=5, name=f"{mb.PREFIXE} 1", trigger=SimpleNamespace(keyword_filter=["sab"]),
        actions=[SimpleNamespace(custom_message="non")], exempt_channel_ids=[], edit=AsyncMock(),
    )
    assert mb.mute_de(regle) == 0                     # par défaut : aucun mute
    asyncio.run(mb.changer_mute(regle, 600))
    nouvelles = regle.edit.await_args.kwargs["actions"]
    assert nouvelles[0].custom_message == "non"
    assert nouvelles[1].duration.total_seconds() == 600
    assert mb.mute_de(SimpleNamespace(actions=nouvelles)) == 600
    asyncio.run(mb.changer_mute(regle, 0))
    assert len(regle.edit.await_args.kwargs["actions"]) == 1


def test_mieux_pls_retrouve_l_image_meme_apres_un_redemarrage():
    from cogs import ai as ai_module

    assert ai_module._RETOUCHE_RE.search("mieux pls") and ai_module._RETOUCHE_RE.search("mieu stp")
    assert not ai_module._RETOUCHE_RE.search("merci")
    classe = next(v for v in vars(ai_module).values() if isinstance(v, type) and hasattr(v, "_description_image"))
    cog = classe.__new__(classe)
    demande = SimpleNamespace(content="sentrix dessine un chat")
    cite_ns = SimpleNamespace(
        id=1, attachments=[SimpleNamespace(filename="sentrix-image-1024x1024.jpg")],
        reference=SimpleNamespace(resolved=demande, message_id=2), channel=None,
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ai_module.discord, "Message", SimpleNamespace)
        assert asyncio.run(cog._description_image(cite_ns)) == "dessine un chat"
