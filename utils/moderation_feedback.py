"""Compact SentriX moderation acknowledgements, built with native Discord V2.

The full numbered sanction dossier stays in the configured logs. The response
at the command location is a concise card (not a second 800px report), with
clickable member identity, a real reason, and the persistent History action.
"""
from __future__ import annotations

import re

import discord


# 24/11/2026 Jayden : « enlève ce gros panneau dans mute ban warn unmute unban,
# un truc simple, petite phrase ». Une phrase, sans bannière ni sections ; le
# dossier complet reste dans les logs.
_PHRASES: dict[str, tuple[str, str]] = {
    "ban": ("🔨", "{m} a été banni."),
    "tempban": ("⏳", "{m} a été banni{d}."),
    "hackban": ("🔨", "{m} a été banni par identifiant."),
    "kick": ("🚪", "{m} a été expulsé."),
    "mute": ("🔇", "{m} est réduit au silence{d}."),
    "unmute": ("🔊", "{m} peut de nouveau parler."),
    "warn": ("⚠️", "{m} a reçu un avertissement."),
    "unban": ("🔓", "{m} a été débanni."),
}

_SNOWFLAKE = re.compile(r"^[0-9]{17,22}$")


def _mark_safe(content: object, *, max_length: int = 360) -> str:
    """Escape user-supplied Markdown and avoid mass-mention text rendering."""
    result = discord.utils.escape_markdown(str(content or "Aucune raison fournie")[:max_length])
    return result.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")


def _valid_id(value: object) -> bool:
    return bool(_SNOWFLAKE.fullmatch(str(value or "")))


def _phrase_seule(texte: str, *, refus: bool) -> discord.ui.LayoutView:
    """Une petite carte d'une phrase, sans bannière.

    Une sanction réussie garde ses boutons de suite (« Lever l'exclusion »…)
    et la ligne de mémoire du membre ; un refus n'a ni l'un ni l'autre.
    """
    view = discord.ui.LayoutView(timeout=None)
    card = discord.ui.Container()
    card.add_item(discord.ui.TextDisplay(texte))
    view.add_item(card)
    view._sentrix_phrase_seule = refus
    view._sentrix_sans_suites = refus
    return view


def phrase_de_sanction(
    *, action: str, target: discord.abc.User, reason: str = "",
    case_number: int | None = None, suffix: str = "", duration: str | None = None,
) -> str:
    """La phrase envoyée après une sanction (texte simple, 25/11/2026)."""
    return texte_de(build_sanction_confirmation(
        action=action, target=target, reason=reason, case_number=case_number,
        suffix=suffix, duration=duration,
    ))


def phrase_de_refus(message: str) -> str | None:
    vue = build_hierarchy_refusal(message)
    return texte_de(vue) if vue is not None else None


def texte_de(vue: discord.ui.LayoutView) -> str:
    morceaux: list[str] = []

    def parcourir(item) -> None:
        if isinstance(getattr(item, "content", None), str):
            morceaux.append(item.content)
        for enfant in list(getattr(item, "children", ()) or ()):
            parcourir(enfant)

    parcourir(vue)
    return "\n".join(morceaux)


def build_sanction_confirmation(
    *, action: str, target: discord.abc.User,
    actor: discord.abc.User | None = None,
    guild_id: int | None = None,
    reason: str = "",
    case_number: int | None = None,
    suffix: str = "",
    duration: str | None = None,
) -> discord.ui.LayoutView:
    """Une phrase : qui, quoi, combien de temps, et le motif s'il y en a un.

    Une écriture du dossier en base qui échoue ne transforme JAMAIS une vraie
    sanction en fausse erreur : la phrase le signale discrètement.
    """
    emoji, modele = _PHRASES.get(action, ("🛡️", "Action effectuée sur {m}."))
    target_id = getattr(target, "id", None)
    mention = (
        f"<@{int(target_id)}>" if target_id is not None
        else _mark_safe(getattr(target, "name", None) or "ce compte", max_length=60)
    )
    d = f" pour {_mark_safe(duration, max_length=70)}" if duration else ""
    texte = f"{emoji} " + modele.format(m=mention, d=d)
    motif = str(reason or "").strip()
    if motif and motif.casefold() not in {"aucune raison fournie", "aucune raison"}:
        motif_propre = _mark_safe(motif, max_length=200)
        texte += f" Motif : {motif_propre}" + ("" if motif_propre.endswith((".", "!", "?", "…")) else ".")
    if suffix:
        texte += f" {_mark_safe(suffix, max_length=120)}"
    if case_number is None:
        texte += "\n-# Dossier non enregistré."
    return _phrase_seule(texte, refus=False)


def build_hierarchy_refusal(message: str) -> discord.ui.LayoutView | None:
    """Refus de hiérarchie : une phrase, sans bouton de suite."""
    text = str(message or "").casefold()
    if "ne peut pas sanctionner ce membre" in text:
        phrase = "❌ Impossible : ce membre a un rôle au-dessus de celui de SentriX."
    elif "ne peut pas gérer ce rôle" in text:
        phrase = "❌ Impossible : ce rôle est au-dessus de celui de SentriX."
    elif "vous ne pouvez pas sanctionner un membre ayant un rôle supérieur ou égal" in text:
        phrase = "❌ Impossible : ce membre a un rôle égal ou supérieur au vôtre."
    else:
        return None
    return _phrase_seule(phrase, refus=True)


__all__ = [
    "build_hierarchy_refusal",
    "build_sanction_confirmation",
]
