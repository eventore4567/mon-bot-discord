"""Carte de log AutoMod complète (utils/automod_incident_card, 29/10/2026)."""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import automod_incident_card as carte  # noqa: E402


def _champs(**kw):
    base = dict(filter_name="antilink", reason="Lien non autorisé.", guild_id=1, channel_id=2, message_id=3,
                created_at=1_790_000_000.0, contenu="va sur https://evil.example/x", deleted=1,
                deleted_ok=True, action=None, duree_s=None, infractions=1, spam_stage=0,
                memoire="1er incident", ref="SX-TEST")
    base.update(kw)
    return carte.champs(**base)


def test_liens_invitations_et_mentions_globales_sont_neutralises():
    texte = carte.neutraliser("https://evil.example/a discord.gg/abc @everyone ```x```")
    assert "https://" not in texte and "hxxps://evil[.]example/a" in texte
    assert "discord[.]gg/abc" in texte
    assert "@everyone" not in texte and "```" not in texte


def test_quatre_statuts_distincts():
    assert carte.statut(True, None) == "bloque"
    assert carte.statut(True, "mute") == "reussie"
    assert carte.statut(None, None) == "detection"
    assert carte.statut(False, None) == "erreur"
    assert carte.statut(True, "mute_failed") == "erreur"


def test_chaque_information_a_son_champ():
    champs, fichier = _champs(action="mute", duree_s=600)
    for nom in ("Statut", "Protection", "Règle", "Motif", "Élément détecté", "Salon", "Date",
                "Action", "Durée", "Infractions (1 h)", "Récidive", "Contenu"):
        assert champs.get(nom), nom
    assert fichier is None
    assert champs["Élément détecté"] == "`evil[.]example`"
    assert "https://discord.com/channels/1/2" in champs["Salon"]
    assert champs["Date"] == "<t:1790000000:F> · <t:1790000000:R>"
    assert champs["Durée"].startswith("10 min") and "<t:1790000600:t>" in champs["Durée"]
    assert "Exclusion temporaire" in champs["Action"] and "Message supprimé" in champs["Action"]


def test_contenu_long_en_fichier_joint_pas_tronque_en_silence():
    long = "x " * 900
    champs, fichier = _champs(contenu=long)
    assert fichier is not None and fichier.filename == "automod-SX-TEST.txt"
    assert "Contenu complet" in champs["Contenu"] and len(champs["Contenu"]) < 1024
    corps = fichier.fp.read().decode("utf-8")
    assert long.strip() in corps


def test_detection_sans_action_le_dit():
    champs, _ = _champs(deleted_ok=None)
    assert champs["Statut"].startswith("Détection seule")
    assert champs["Action"] == "Aucune action (détection seule)"
