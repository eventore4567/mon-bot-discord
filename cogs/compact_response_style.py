"""Rendu compact des réponses ordinaires de SentriX.

But : les commandes normales répondent comme un bot de protection professionnel :
    ✅ | [PING] | Pong ! • Latence : 42 ms

Les vrais panneaux interactifs/configuration et les réponses contenant une image restent
en embed. Cette couche ne remplace pas canonical_interactions : elle ne fait que préparer
le rendu avant l'envoi.
"""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands


PANEL_ROOTS = frozenset({
    "help",
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
    "indisponible",
    "permission manquante",
    "pas les permissions",
    "n'a pas les permissions",
    "tu n'as pas accès",
    "vous n'avez pas accès",
    "problème technique",
    "probleme technique",
)
WARNING_WORDS = (
    "avertissement",
    "attention",
    "recharge",
    "cooldown",
    "patiente",
    "déjà",
    "deja",
)


def _root_from_command(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _root_from_ctx(ctx: commands.Context) -> str:
    return _root_from_command(getattr(ctx, "command", None))


def _root_from_interaction(interaction: discord.Interaction | None) -> str:
    if interaction is None:
        return ""
    command = getattr(interaction, "command", None)
    if command is not None:
        return _root_from_command(command)
    data = getattr(interaction, "data", None)
    return str(data.get("name") or "").casefold() if isinstance(data, dict) else ""


def _label_from_command(command: Any) -> str:
    qualified = str(getattr(command, "qualified_name", "") or "COMMAND")
    return qualified.replace(" ", "-").replace("_", "-").upper()[:30]


def _label_from_ctx(ctx: commands.Context) -> str:
    return _label_from_command(getattr(ctx, "command", None))


def _label_from_interaction(interaction: discord.Interaction | None) -> str:
    if interaction is None:
        return "COMMAND"
    command = getattr(interaction, "command", None)
    if command is not None:
        return _label_from_command(command)
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        return str(data.get("name") or "COMMAND").replace("_", "-").upper()[:30]
    return "COMMAND"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _has_media(embed: discord.Embed) -> bool:
    return bool(
        getattr(embed.image, "url", None)
        or getattr(embed.thumbnail, "url", None)
        or getattr(embed.video, "url", None)
    )


def _status_from_text(text: str, title: str = "") -> str:
    haystack = f"{title}\n{text}".casefold()
    if any(word in haystack for word in ERROR_WORDS):
        return "❌"
    if any(word in haystack for word in WARNING_WORDS):
        return "⚠️"
    return "✅"


def _embed_to_text(embed: Any) -> tuple[str | None, str]:
    if not isinstance(embed, discord.Embed):
        return None, "✅"
    if _has_media(embed):
        return None, "✅"

    title = _text(embed.title)
    description = _text(embed.description)
    generic_titles = {
        "information",
        "succès",
        "succes",
        "erreur",
        "erreur ia",
        "avertissement",
        "action terminée",
        "action terminee",
        "action impossible",
    }

    lines: list[str] = []
    if (
        title
        and title.casefold() not in generic_titles
        and not title.casefold().startswith("sentrix /")
    ):
        lines.append(title)
    if description:
        lines.append(description)

    for field in list(embed.fields):
        name = _text(field.name)
        value = _text(field.value)
        if not value:
            continue
        if name and name.casefold() not in {"information", "détail", "detail"}:
            lines.append(f"{name} : {value}")
        else:
            lines.append(value)

    text = "\n".join(lines).strip()
    if not text:
        return None, _status_from_text("", title)
    return text, _status_from_text(text, title)


def _decorate(text: str, label: str, status: str | None = None) -> str:
    text = _text(text)
    if not text:
        return text
    if text.startswith(("✅ | [", "❌ | [", "⚠️ | [")):
        return text

    status = status or _status_from_text(text)
    prefix = f"{status} | [{label}] | "
    if len(prefix) + len(text) > 1990:
        return text
    return prefix + text


def _prepare(
    *,
    root: str,
    label: str,
    args: tuple,
    kwargs: dict,
) -> tuple[tuple, dict]:
    if not root or root in PANEL_ROOTS:
        return args, kwargs

    args_list = list(args)
    kwargs = dict(kwargs)
    chosen_status: str | None = None

    embed = kwargs.get("embed")
    if isinstance(embed, discord.Embed):
        converted, status = _embed_to_text(embed)
        if converted is not None:
            chosen_status = status
            kwargs.pop("embed", None)
            if args_list:
                current = _text(args_list[0])
                args_list[0] = f"{current}\n{converted}".strip() if current else converted
            else:
                current = _text(kwargs.get("content"))
                kwargs["content"] = f"{current}\n{converted}".strip() if current else converted

    embeds = kwargs.get("embeds")
    if isinstance(embeds, (list, tuple)) and len(embeds) == 1:
        converted, status = _embed_to_text(embeds[0])
        if converted is not None:
            chosen_status = chosen_status or status
            kwargs.pop("embeds", None)
            if args_list:
                current = _text(args_list[0])
                args_list[0] = f"{current}\n{converted}".strip() if current else converted
            else:
                current = _text(kwargs.get("content"))
                kwargs["content"] = f"{current}\n{converted}".strip() if current else converted

    if args_list and isinstance(args_list[0], str):
        args_list[0] = _decorate(args_list[0], label, chosen_status)
    elif isinstance(kwargs.get("content"), str):
        kwargs["content"] = _decorate(kwargs["content"], label, chosen_status)

    return tuple(args_list), kwargs


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_compact_v2", False):
        return

    async def compact_context_send(self: commands.Context, *args, **kwargs):
        args, kwargs = _prepare(
            root=_root_from_ctx(self),
            label=_label_from_ctx(self),
            args=args,
            kwargs=kwargs,
        )
        return await current(self, *args, **kwargs)

    compact_context_send._sentrix_compact_v2 = True
    compact_context_send._sentrix_original = current
    commands.Context.send = compact_context_send


def _install_sentrix_context_send() -> None:
    try:
        from main import SentriXContext
    except Exception:
        return

    current = SentriXContext.send
    if getattr(current, "_sentrix_compact_v2", False):
        return

    async def compact_sentrix_send(self, *args, **kwargs):
        args, kwargs = _prepare(
            root=_root_from_ctx(self),
            label=_label_from_ctx(self),
            args=args,
            kwargs=kwargs,
        )
        return await current(self, *args, **kwargs)

    compact_sentrix_send._sentrix_compact_v2 = True
    compact_sentrix_send._sentrix_original = current
    SentriXContext.send = compact_sentrix_send


def _install_interaction_send() -> None:
    current = discord.InteractionResponse.send_message
    if getattr(current, "_sentrix_compact_v2", False):
        return

    async def compact_interaction_send(self, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        root = _root_from_interaction(interaction)
        if root:
            args, kwargs = _prepare(
                root=root,
                label=_label_from_interaction(interaction),
                args=args,
                kwargs=kwargs,
            )
        return await current(self, *args, **kwargs)

    compact_interaction_send._sentrix_compact_v2 = True
    compact_interaction_send._sentrix_original = current
    discord.InteractionResponse.send_message = compact_interaction_send


def _install_interaction_edit_original() -> None:
    current = discord.Interaction.edit_original_response
    if getattr(current, "_sentrix_compact_v2", False):
        return

    async def compact_edit_original(self: discord.Interaction, *args, **kwargs):
        root = _root_from_interaction(self)
        if root:
            args, kwargs = _prepare(
                root=root,
                label=_label_from_interaction(self),
                args=args,
                kwargs=kwargs,
            )
        return await current(self, *args, **kwargs)

    compact_edit_original._sentrix_compact_v2 = True
    compact_edit_original._sentrix_original = current
    discord.Interaction.edit_original_response = compact_edit_original


async def setup(bot: commands.Bot) -> None:
    _install_context_send()
    _install_sentrix_context_send()
    _install_interaction_send()
    _install_interaction_edit_original()
