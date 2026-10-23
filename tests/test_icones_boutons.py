"""Les 114 icônes SentriX téléversées doivent se voir sur les boutons.

Mesuré le 23/10/2026 : `synchroniser()` téléverse bien le pack (« 114 déjà en
place, 0 échecs ») et `traduire()` est appliquée — mais UNIQUEMENT aux titres
de panneau et de section. Les libellés de boutons gardaient leur Unicode.

Un libellé ne peut pas porter de marquage `<:nom:id>` : Discord l'afficherait
tel quel. L'icône passe donc par `emoji=`.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from utils import sentrix_emojis as se  # noqa: E402
from utils.sentrix_panels import _icone_de_bouton  # noqa: E402

ICONE = "<:sentrix_ticket:123456789012345678>"


def _amorcer():
    se.reinitialiser()
    se.amorcer({"ticket": ICONE})


def test_l_emoji_de_tete_devient_une_icone_sentrix():
    _amorcer()
    try:
        libelle, icone = _icone_de_bouton("🎫 Ouvrir un ticket", None)
        assert libelle == "Ouvrir un ticket", "l'emoji doit quitter le libellé"
        assert isinstance(icone, discord.PartialEmoji)
        assert icone.id == 123456789012345678
    finally:
        se.reinitialiser()


def test_aucun_marquage_texte_ne_part_dans_un_libelle():
    # Le piège : Discord afficherait « <:sentrix_ticket:123…> » en toutes lettres.
    _amorcer()
    try:
        libelle, _ = _icone_de_bouton("🎫 Ouvrir", None)
        assert "<:" not in libelle and ":" not in libelle
    finally:
        se.reinitialiser()


def test_un_bouton_qui_a_deja_son_emoji_n_est_pas_touche():
    _amorcer()
    try:
        depart = discord.PartialEmoji(name="x")
        libelle, icone = _icone_de_bouton("🎫 Ouvrir", depart)
        assert libelle == "🎫 Ouvrir" and icone is depart
    finally:
        se.reinitialiser()


def test_sans_icone_disponible_le_libelle_reste_entier():
    # Un bouton sans emoji reste valide ; un libellé amputé, non.
    se.reinitialiser()
    libelle, icone = _icone_de_bouton("🎫 Ouvrir", None)
    assert libelle == "🎫 Ouvrir"
    assert icone is None


def test_un_emoji_seul_reste_le_libelle():
    # Le déplacer donnerait un bouton sans texte NI image.
    _amorcer()
    try:
        libelle, icone = _icone_de_bouton("🎫", None)
        assert libelle == "🎫" and icone is None
    finally:
        se.reinitialiser()


def test_un_libelle_sans_emoji_passe_tel_quel():
    _amorcer()
    try:
        assert _icone_de_bouton("Confirmer", None) == ("Confirmer", None)
    finally:
        se.reinitialiser()


def test_un_emoji_au_milieu_n_est_pas_deplace():
    # Seul l'emoji de TÊTE est décoratif ; au milieu, il fait partie du texte.
    _amorcer()
    try:
        libelle, icone = _icone_de_bouton("Voir 🎫 ici", None)
        assert libelle == "Voir 🎫 ici" and icone is None
    finally:
        se.reinitialiser()
