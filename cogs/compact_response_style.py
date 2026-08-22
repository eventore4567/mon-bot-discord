"""Style final compact des réponses de commandes SentriX.

Cette couche est volontairement petite : elle ne gère ni les deffers ni les erreurs slash,
qui restent sous la responsabilité de canonical_interactions. Elle intervient uniquement
sur Context.send afin de transformer les réponses ordinaires en texte Discord natif au
format compact inspiré des grands bots de protection.

Les vrais centres de configuration et panels restent en embed.
"""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands


CONFIG_ROOTS = frozenset({
    "setup",
    "ticketsetup",
    "ticketpanel",
    "tickettype",
    "ticketform",
    "ticketconfig",
    "ticketlogs",
    "ticketlimit",
    "ticketautoclose",
    "logsetup",
    "aisetup",
    "aidiag",
    "designsetup",
    "embed",
    "embed-builder",
    "rolepanel",
    "verify-panel",
    "create",
})

ERROR_HINTS = (
    "erreur",
    "impossible",
    "introuvable",
    "refus",
    "échoué",
    "echoue",
    "indisponible",
    "pas les permissions",
    "n'a pas les permissions",
    "tu n'as pas accès",
    "vous n'avez pas accès",
    "problème technique",
    "probleme technique",
)


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    try:
        from .community_v32 import strip_decorative_emoji
        text = strip_decorative_emoji(text).strip()
    except Exception:
        pass
    return text


def _root(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _label(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    qualified = str(getattr(command, "qualified_name", "") or "COMMAND")
    label = qualified.replace(" ", "-").replace("_", "-").upper()
    return label[:28]


def _embed_text(embed: Any) -> str | None:
    if not isinstance(embed, discord.Embed):
        return None
    lines: list[str] = []
    title = _clean(embed.title)
    description = _clean(embed.description)
    generic = {
        "information", "succès", "succes", "erreur", "avertissement",
        "action terminée", "action terminee", "sentrix / utilitaires",
    }
    if title and title.casefold() not in generic and not title.casefold().startswith("sentrix /"):
        lines.append(title)
    if description:
        lines.append(description)
    for field in list(embed.fields):
        name = _clean(field.name)
        value = _clean(field.value)
        if not value:
            continue
        if name and name.casefold() not in {"information", "détail", "detail"}:
            lines.append(f"{name} : {value}")
        else:
            lines.append(value)
    text = "\n".join(lines).strip()
    return text or None


def _compact(text: str, label: str) -> str:
    text = _clean(text)
    if not text:
        return text
    if text.startswith(("• | [", "! | [")):
        return text
    marker = "!" if any(word in text.casefold() for word in ERROR_HINTS) else "•"
    prefix = f"{marker} | [{label}] | "
    # Discord refuse les messages > 2000 caractères. Les longues réponses IA ont déjà
    # leur propre découpage ; on ne risque pas de les casser juste pour ajouter le préfixe.
    if len(prefix) + len(text) > 1990:
        return text
    return prefix + text


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_compact_style", False):
        return

    async def compact_send(self: commands.Context, *args, **kwargs):
        root = _root(self)
        if root in CONFIG_ROOTS:
            return await current(self, *args, **kwargs)

        args = list(args)
        kwargs = dict(kwargs)

        text_from_embed = _embed_text(kwargs.get("embed"))
        if text_from_embed:
            kwargs.pop("embed", None)
            kwargs["embeds"] = [] if "embeds" not in kwargs else kwargs.get("embeds")
            if args:
                existing = str(args[0] or "").strip()
                args[0] = f"{existing}\n{text_from_embed}".strip() if existing else text_from_embed
            else:
                existing = str(kwargs.get("content") or "").strip()
                kwargs["content"] = f"{existing}\n{text_from_embed}".strip() if existing else text_from_embed

        embeds = kwargs.get("embeds")
        if isinstance(embeds, (list, tuple)) and len(embeds) == 1:
            text_from_embeds = _embed_text(embeds[0])
            if text_from_embeds:
                kwargs.pop("embeds", None)
                if args:
                    existing = str(args[0] or "").strip()
                    args[0] = f"{existing}\n{text_from_embeds}".strip() if existing else text_from_embeds
                else:
                    existing = str(kwargs.get("content") or "").strip()
                    kwargs["content"] = f"{existing}\n{text_from_embeds}".strip() if existing else text_from_embeds

        label = _label(self)
        if args and isinstance(args[0], str):
            args[0] = _compact(args[0], label)
        elif isinstance(kwargs.get("content"), str):
            kwargs["content"] = _compact(kwargs["content"], label)

        return await current(self, *tuple(args), **kwargs)

    compact_send._sentrix_compact_style = True
    compact_send._sentrix_original = current
    commands.Context.send = compact_send


async def setup(bot: commands.Bot) -> None:
    _install_context_send()
