"""Carte de log d'un incident AutoMod : lisible d'un coup d'œil.

22/11/2026 : « les logs d'AutoMod sont moches et ne montrent rien ; mets des
émojis, des bannières en rouge comme Raid Protect ». Mesuré sur le bot booté :
un mur de texte sous trois titres, libellés nus, sanction noyée au milieu, et
aucun liseré — retiré de TOUS les messages par embeds.clean_view.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from utils import embeds, wide_logs  # noqa: E402


@pytest.mark.parametrize(("statut", "action", "duree", "attendu"), [
    ("Action réussie — message retiré et sanction appliquée", "Message supprimé · Exclusion temporaire",
     "5 min · jusqu'à <t:1:t>", "### 🔇 Sanction : Exclusion temporaire · 5 min"),
    ("Message bloqué — retiré, sans sanction",
     "Message supprimé · Avertissement (exclusion temporaire à la prochaine infraction)", "",
     "### 🗑️ Message supprimé · ⚠️ averti"),
    ("Détection seule — aucun message retiré", "", "", "### 👁️ Détection seule"),
    ("Échec — l'action prévue n'a pas pu être appliquée", "Exclusion temporaire prévue, non appliquée", "",
     "### ❌ Sanction non appliquée"),
])
def test_le_titre_dit_ce_qui_a_ete_fait(statut, action, duree, attendu):
    titre = wide_logs._titre_incident(statut, action, duree)
    assert titre.startswith(attendu)
    assert f"-# {statut}" in titre


@pytest.mark.parametrize(("statut", "couleur"), [
    ("Action réussie — message retiré et sanction appliquée", 0xED4245),
    ("Message bloqué — retiré, sans sanction", 0xF39C12),
    ("Détection seule — aucun message retiré", 0xFEE75C),
    ("Échec — l'action prévue n'a pas pu être appliquée", 0x992D22),
])
def test_le_liseré_porte_la_couleur_de_l_issue(statut, couleur):
    etat = wide_logs._etat_incident(statut)
    assert wide_logs.ACCENT_INCIDENT[etat] == couleur


def test_le_nettoyage_final_garde_le_liseré_voulu_et_retire_les_autres():
    voulu = discord.ui.Container(accent_colour=discord.Colour(0xED4245))
    voulu._sentrix_liseré_voulu = True
    ordinaire = discord.ui.Container(accent_colour=discord.Colour(0x00FF00))
    vue = discord.ui.LayoutView()
    vue.add_item(voulu)
    vue.add_item(ordinaire)
    embeds.clean_view(vue)
    assert voulu.accent_colour is not None and voulu.accent_colour.value == 0xED4245
    assert ordinaire.accent_colour is None
