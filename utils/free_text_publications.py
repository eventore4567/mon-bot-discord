"""Publications libres SentriX : vrai cadre Discord, sans Markdown décoratif.

Ce composant ne touche ni aux messages des membres ni aux citations des logs :
seules les publications explicitement envoyées par l'équipe avec +say l'utilisent.
Un titre de règlement est promu en titre de carte et le texte reste intégral.
"""
from __future__ import annotations

import re

import discord


MAX_PUBLICATION_TEXT = 3500

_RULE_HEADING = re.compile(
    r"^\s*(?:#{1,3}\s+)?(?:`{1,3})?"
    r"(?:📜\s*)?(?:r[èe]gle|article)\s*n[°ºo]?\s*(?P<number>\d{1,3})"
    r"\s*(?:`{1,3})?\s*(?:[:：\-–—]\s*)?(?P<rest>.*)$",
    re.IGNORECASE,
)


def _dequote_whole_block(content: str) -> str:
    """Ne retire le style citation que lorsque le message ENTIER est une citation."""
    text = content.strip()
    if text.startswith(">>> "):
        return text[4:].strip()
    lines = text.splitlines()
    if lines and all(not line.strip() or line.lstrip().startswith(">") for line in lines):
        return "\n".join(
            re.sub(r"^\s*> ?", "", line) if line.strip() else ""
            for line in lines
        ).strip()
    return text


def publication_parts(content: str) -> tuple[str, str, str]:
    """(titre, corps, famille) sans tronquer ni réécrire les mots du message."""
    text = _dequote_whole_block(str(content or "").replace("\r\n", "\n")).strip()
    if not text:
        raise ValueError("Le message ne peut pas être vide.")

    first_line, sep, remainder = text.partition("\n")
    match = _RULE_HEADING.match(first_line)
    if match:
        rule_no = int(match.group("number"))
        heading = "Article" if first_line.lstrip(" `#").casefold().startswith("article") else "Règle"
        tail = match.group("rest").strip()
        # Le code inline autour du titre ne doit pas produire de badge gris.
        if tail.endswith("`") and first_line.count("`") >= 2:
            tail = tail[:-1].rstrip()
        body = "\n".join(part for part in (tail, remainder.strip()) if part).strip()
        if not body:
            raise ValueError("Ajoutez un texte après le numéro de la règle.")
        if len(body) > MAX_PUBLICATION_TEXT:
            raise ValueError(f"Le texte dépasse {MAX_PUBLICATION_TEXT} caractères.")
        return f"{heading} n°{rule_no}", body, "Règlement"

    if len(text) > MAX_PUBLICATION_TEXT:
        raise ValueError(f"Le texte dépasse {MAX_PUBLICATION_TEXT} caractères.")
    return "Message du serveur", text, "Publication"


class PublicationCard(discord.ui.LayoutView):
    """Cadre natif Components V2 : un seul message, lisible sur mobile et desktop."""

    def __init__(self, text: str):
        super().__init__(timeout=None)
        title, body, family = publication_parts(text)
        container = discord.ui.Container()
        container.add_item(discord.ui.TextDisplay(f"## {title}"))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(body))
        container.add_item(discord.ui.TextDisplay(f"-# {family} · SentriX"))
        self.add_item(container)


__all__ = ["MAX_PUBLICATION_TEXT", "PublicationCard", "publication_parts"]
