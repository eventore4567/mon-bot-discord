"""Insultes : le contexte se lit autour de chaque mot (26/11/2026).

Une candidature de 2900 caractères contenant « fermer sa gueule (jrigole) »
était supprimée avec exclusion : un « tu » d'une autre ligne en faisait une
« attaque adressée ». Revue Codex (PR #731) : une plaisanterie à un endroit
n'excuse pas une vraie insulte plus loin.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.moderation_dataset import MultilingualModerationDataset  # noqa: E402
from utils import automod_incident_card as carte  # noqa: E402

DATASET = MultilingualModerationDataset()


def test_plaisanterie_isolee_dans_un_long_texte_n_est_pas_une_attaque():
    texte = (
        "tu es le bienvenu, voici ma candidature. " * 5
        + "\n17. je lui dit qu'il a cas créer son serv lui meme et fermer sa gueule (jrigole) nan en vrai jsp\n"
        + "merci de votre lecture, toi qui lis ceci. " * 5
    )
    resultat = DATASET.match(texte)
    assert resultat is None or resultat.confidence < 0.70, resultat


def test_une_blague_ailleurs_n_excuse_pas_une_vraie_insulte():
    texte = "gueule mdr " + "bonjour " * 20 + "tu es un connard"
    resultat = DATASET.match(texte)
    assert resultat is not None and resultat.confidence >= 0.92, resultat


def test_vraies_insultes_adressees_toujours_detectees():
    for texte in ("ferme ta gueule", "tu es un connard", "t es qu une folle"):
        resultat = DATASET.match(texte)
        assert resultat is not None and resultat.confidence >= 0.92, texte


def test_message_long_affiche_et_fichier_de_securite():
    """Revue Codex (PR #731) : affiché en entier ET fichier joint au-delà de 900."""
    texte = "\n".join(f"{i}. une ligne de candidature assez longue pour remplir la carte" for i in range(1, 30))
    champs, fichier = carte.champs(
        filter_name="antiinsult", reason="x", guild_id=1, channel_id=2, message_id=3,
        created_at=0, contenu=texte, deleted=1, deleted_ok=True, action=None, duree_s=None,
        infractions=0, spam_stage=0, memoire="", ref="SX-1",
    )
    morceaux = [v for k, v in champs.items() if k.startswith("Contenu")]
    assert "29. une ligne" in "\n".join(morceaux)
    assert all(len(v) < 1024 for v in morceaux)
    assert fichier is not None and texte in fichier.fp.read().decode("utf-8")


def test_un_long_message_d_insultes_reste_rapide():
    """Revue Codex (PR #731) : 4000 caractères analysés en millisecondes, pas en
    secondes — l'analyse est synchrone et bloquait toute la boucle du bot."""
    import time

    debut = time.perf_counter()
    DATASET.match("con " * 1000)
    assert time.perf_counter() - debut < 0.25
