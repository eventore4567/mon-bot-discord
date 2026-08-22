"""Politique finale des réponses SentriX.

Les commandes passent désormais par le moteur visuel premium afin d'afficher la photo de
profil actuelle du bot et l'icône correspondant à leur catégorie. Le module conserve son
nom historique et son marqueur d'installation pour rester compatible avec les runtimes
déjà en production.
"""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands


RICH_ROOTS = frozenset({
    "help",
    "setup",
    "ticketsetup",
    "ticketpanel",
    "tickettype",
    "ticketform",
    "ticketconfig",
    "logsetup",
    "aisetup",
    "aidiag",
    "designsetup",
    "embed",
    "embed-builder",
    "shoppanel",
    "rolepanel",
    "verify-panel",
    "create",
})

ERROR_WORDS = (
    "erreur",
    "impossible",
    "introuvable",
    "refus",
    "échoué",
    "echoue",
    "permission",
    "problème",
    "probleme",
    "indisponible",
)


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    try:
        from .community_v32 import strip_decorative_emoji
        return strip_decorative_emoji(text).strip()
    except Exception:
        return text


def _root(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _label(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    name = str(getattr(command, "qualified_name", "") or "SENTRIX")
    return name.replace("_", "-").replace(" ", "-").upper()[:30]


def _embed_to_text(embed: Any) -> str | None:
    if not isinstance(embed, discord.Embed):
        return None

    parts: list[str] = []
    title = _clean(embed.title)
    description = _clean(embed.description)

    generic_titles = {
        "information",
        "succès",
        "succes",
        "erreur",
        "avertissement",
        "sentrix / utilitaires",
        "sentrix / économie",
        "sentrix / economie",
        "sentrix / modération",
        "sentrix / moderation",
    }

    if title and title.casefold() not in generic_titles and not title.casefold().startswith("sentrix /"):
        parts.append(title)
    if description:
        parts.append(description)

    for field in list(embed.fields):
        name = _clean(field.name)
        value = _clean(field.value)
        if not value:
            continue
        if name and name.casefold() not in {"information", "détail", "detail"}:
            parts.append(f"{name} : {value}")
        else:
            parts.append(value)

    text = "\n".join(parts).strip()
    return text or None


def _format(text: str, label: str) -> str:
    text = _clean(text)
    if not text:
        return text
    if text.startswith(("✅ | [", "❌ | [", "• | [", "! | [")):
        return text
    error = any(word in text.casefold() for word in ERROR_WORDS)
    marker = "❌" if error else "✅"
    prefix = f"{marker} | [{label}] | "
    if len(prefix) + len(text) > 1990:
        return text
    return prefix + text


def _convert(args: tuple[Any, ...], kwargs: dict[str, Any], label: str):
    args = list(args)
    kwargs = dict(kwargs)

    embed_text = _embed_to_text(kwargs.get("embed"))
    if embed_text:
        kwargs.pop("embed", None)
        current = str(args[0] if args else kwargs.get("content") or "").strip()
        merged = f"{current}\n{embed_text}".strip() if current else embed_text
        if args:
            args[0] = merged
            kwargs.pop("content", None)
        else:
            kwargs["content"] = merged

    embeds = kwargs.get("embeds")
    if isinstance(embeds, (list, tuple)) and len(embeds) == 1:
        embed_text = _embed_to_text(embeds[0])
        if embed_text:
            kwargs.pop("embeds", None)
            current = str(args[0] if args else kwargs.get("content") or "").strip()
            merged = f"{current}\n{embed_text}".strip() if current else embed_text
            if args:
                args[0] = merged
                kwargs.pop("content", None)
            else:
                kwargs["content"] = merged

    if args and isinstance(args[0], str):
        args[0] = _format(args[0], label)
    elif isinstance(kwargs.get("content"), str):
        kwargs["content"] = _format(kwargs["content"], label)

    return tuple(args), kwargs


def install(bot: commands.Bot | None = None) -> None:
    """Réinstalle la politique autour du Context.send actuellement actif.

    On ne mémorise pas un ancien wrapper comme source de vérité : les runtimes historiques
    peuvent encore remplacer Context.send pendant le chargement. L'installateur est donc
    rappelé en dernier après chaque extension et enveloppe toujours la version courante.
    """
    current = commands.Context.send
    if getattr(current, "_sentrix_plain_response_policy", False):
        return

    async def plain_send(self: commands.Context, *args, **kwargs):
        # Le wrapper premium placé juste en dessous transforme le texte simple en embed,
        # applique la catégorie, ajoute la photo du bot puis joint l'icône correspondante.
        # Les mentions, références, fichiers métier et réponses éphémères sont conservés.
        return await current(self, *args, **kwargs)

    plain_send._sentrix_plain_response_policy = True
    plain_send._sentrix_original = current
    commands.Context.send = plain_send
