"""Présentation des réponses de l'IA (10/11/2026).

« Quand c'est un grand message, mets-le dans un embed ou une belle présentation, car
c'est moche. » Une réponse courte reste du texte simple (c'est une conversation). Une
réponse longue ou structurée part dans une carte Components V2 : bord coloré, texte
Markdown, signature discrète. Au-delà de la limite d'une carte, plusieurs cartes.
"""
from __future__ import annotations

import discord

COULEUR = 0x5865F2
SEUIL_CARACTERES = 500
SEUIL_LIGNES = 6
#: Discord limite le texte d'un message Components V2 à 4000 caractères.
TAILLE_CARTE = 3700
SIGNATURE = "-# 🤖 SentriX IA"


def doit_etre_en_carte(texte: str) -> bool:
    texte = str(texte or "").strip()
    if not texte:
        return False
    lignes = [ligne for ligne in texte.splitlines() if ligne.strip()]
    return len(texte) > SEUIL_CARACTERES or len(lignes) >= SEUIL_LIGNES


def _morceaux(texte: str, taille: int = TAILLE_CARTE) -> list[str]:
    """Coupe aux paragraphes, puis aux lignes, sans casser un bloc de code."""
    texte = texte.strip()
    if len(texte) <= taille:
        return [texte]
    morceaux, courant, dans_code = [], "", False
    for ligne in texte.splitlines(keepends=True):
        if ligne.lstrip().startswith("```"):
            dans_code = not dans_code
        if len(courant) + len(ligne) > taille and courant:
            if dans_code:
                courant += "```\n"
                morceaux.append(courant.strip())
                courant = "```\n" + ligne
            else:
                morceaux.append(courant.strip())
                courant = ligne
        else:
            courant += ligne
        while len(courant) > taille:  # ligne géante sans retour
            morceaux.append(courant[:taille])
            courant = courant[taille:]
    if courant.strip():
        morceaux.append(courant.strip())
    return morceaux


def cartes(texte: str) -> list[discord.ui.LayoutView]:
    parties = _morceaux(str(texte or ""))
    vues = []
    for index, partie in enumerate(parties):
        vue = discord.ui.LayoutView(timeout=None)
        carte = discord.ui.Container(accent_colour=discord.Colour(COULEUR))
        carte.add_item(discord.ui.TextDisplay(partie))
        if index == len(parties) - 1:
            carte.add_item(discord.ui.Separator(visible=False))
            carte.add_item(discord.ui.TextDisplay(SIGNATURE))
        vue.add_item(carte)
        vues.append(vue)
    return vues


__all__ = ["doit_etre_en_carte", "cartes", "SEUIL_CARACTERES"]
