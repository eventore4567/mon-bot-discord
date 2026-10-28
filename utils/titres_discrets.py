"""Titres discrets partout : « # » et « ## » deviennent « ### », « ### » du gras.

28/10/2026 (Jayden, captures de /setup et des tickets) : « les trucs gros ça sert
à rien, c'est moche ». Les panneaux Components V2 ouvraient sur un titre
Markdown « # » — le plus grand de Discord — et chaque section en « ## »/« ### ».

Un seul point d'application : la sérialisation de ``TextDisplay``. Tous les
panneaux (setup, aide, tickets, journaux…) passent par là, quel que soit le
module qui les construit ; le texte des vues n'est pas modifié, seul ce qui part
vers Discord l'est. Les sous-titres « -# » restent tels quels.
"""
from __future__ import annotations

import re

import discord

_TITRE = re.compile(r"^(#{1,3}) (.+)$", re.MULTILINE)


def adoucir(texte: str) -> str:
    def remplacer(m: re.Match) -> str:
        niveau, contenu = len(m.group(1)), m.group(2).strip()
        if niveau == 3:
            # Déjà en gras ? ne pas empiler les astérisques.
            return contenu if contenu.startswith("**") and contenu.endswith("**") else f"**{contenu}**"
        return f"### {contenu}"

    return _TITRE.sub(remplacer, texte) if texte and "#" in texte else texte


def installer() -> None:
    original = discord.ui.TextDisplay.to_component_dict
    if getattr(original, "_sentrix_titres_discrets", False):
        return

    def to_component_dict(self):
        donnees = original(self)
        contenu = donnees.get("content")
        if isinstance(contenu, str):
            donnees["content"] = adoucir(contenu)
        return donnees

    to_component_dict._sentrix_titres_discrets = True
    discord.ui.TextDisplay.to_component_dict = to_component_dict


installer()
