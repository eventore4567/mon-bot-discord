"""Invariant de contexte pour les réponses de commandes SentriX.

Le transport et la pagination appartiennent uniquement à ``final_interaction_policy``.
Cette garde, chargée très tard sur Railway, ne ré-emballe plus Context.send, Messageable,
les interactions et les webhooks : ces wrappers en double pouvaient reconvertir une même
réponse et regrouper plusieurs gros embeds dans un payload Discord invalide.

Elle conserve :
- le contexte de racine pour les app_commands qui envoient directement dans un salon ;
- les helpers de normalisation utilisés par les tests et les anciennes intégrations.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from . import final_interaction_policy as policy

logger = logging.getLogger("bot.command-embed-invariant")

_MARKER = "_sentrix_command_embed_invariant_v2"
_MENTION_RE = re.compile(r"<@!?\d{15,22}>|<@&\d{15,22}>|@everyone|@here", re.IGNORECASE)


def _content_from(args: tuple, kwargs: dict) -> tuple[Any, bool]:
    if kwargs.get("content") is not None:
        return kwargs.get("content"), False
    if args:
        return args[0], True
    return None, False


def _ping_stub(value: Any) -> str | None:
    """Conserve uniquement les mentions nécessaires à une vraie notification Discord."""
    seen: set[str] = set()
    tokens: list[str] = []
    for match in _MENTION_RE.findall(str(value or "")):
        key = match.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(match)
    text = " ".join(tokens).strip()
    return text[:1900] or None


def _has_non_ping_text(value: Any) -> bool:
    text = _MENTION_RE.sub("", str(value or ""))
    return bool(text.strip(" \n\t,;:|•-—–"))


def _move_content_next_to_existing_embeds(
    kwargs: dict,
    content: Any,
    *,
    root: str,
    bot: Any,
) -> dict:
    """Compatibilité helper : déplace un ancien content + embed dans des cartes.

    Le runtime n'utilise plus cette fonction pour envoyer : la vraie pagination sûre est
    effectuée par ``final_interaction_policy._payload_pages``. Elle reste ici pour les
    intégrations/tests qui inspectent un payload normalisé sans l'expédier.
    """
    text = str(content or "").strip()
    if not text:
        return kwargs

    existing: list[discord.Embed] = []
    single = kwargs.pop("embed", None)
    if isinstance(single, discord.Embed):
        existing.append(single)
    for item in list(kwargs.pop("embeds", []) or []):
        if isinstance(item, discord.Embed):
            existing.append(item)

    cards = [
        policy._clean_embed(card, root=root, bot=bot)
        for card in policy._cards_from_text(text)
    ]
    cards = [card for card in cards if isinstance(card, discord.Embed)]
    combined = cards + existing
    if len(combined) == 1:
        kwargs["embed"] = combined[0]
    elif combined:
        kwargs["embeds"] = combined[:10]
    return kwargs


def _set_remaining_content(
    args: tuple,
    kwargs: dict,
    *,
    positional: bool,
    value: str | None,
) -> tuple[tuple, dict]:
    mutable_args = list(args)
    if positional and mutable_args:
        mutable_args[0] = value
        kwargs.pop("content", None)
    else:
        kwargs["content"] = value
    return tuple(mutable_args), kwargs


def _normalize_command_payload(
    args: tuple,
    kwargs: dict,
    *,
    editing: bool = False,
    root: str = "",
    bot: Any = None,
):
    """Normalise un payload unique pour compatibilité et tests.

    L'envoi réel ne passe plus ici : il utilise ``policy._payload_pages`` afin qu'une
    longue réponse produise plusieurs messages valides au lieu d'être tronquée.
    """
    original_kwargs = dict(kwargs)
    original_content, positional = _content_from(args, original_kwargs)
    allowed_mentions = original_kwargs.get("allowed_mentions")
    ping_requested = policy._explicit_ping_requested(original_kwargs)
    original_had_embed = (
        isinstance(original_kwargs.get("embed"), discord.Embed)
        or bool(original_kwargs.get("embeds"))
    )

    work_kwargs = dict(original_kwargs)
    if ping_requested:
        work_kwargs.pop("allowed_mentions", None)

    new_args, new_kwargs = policy._normalize_payload(
        args,
        work_kwargs,
        editing=editing,
        force_embed=True,
        root=root,
        bot=bot,
    )

    if allowed_mentions is not None:
        new_kwargs["allowed_mentions"] = allowed_mentions

    if original_content is not None and str(original_content).strip():
        if original_had_embed and (not ping_requested or _has_non_ping_text(original_content)):
            readable = (
                _MENTION_RE.sub("", str(original_content)).strip(" \n\t,;:|•-—–")
                if ping_requested
                else original_content
            )
            new_kwargs = _move_content_next_to_existing_embeds(
                new_kwargs,
                readable,
                root=root,
                bot=bot,
            )

        remaining = _ping_stub(original_content) if ping_requested else None
        new_args, new_kwargs = _set_remaining_content(
            new_args,
            new_kwargs,
            positional=positional,
            value=remaining,
        )

    return new_args, new_kwargs


def _install_app_command_context() -> None:
    """Donne une racine aux envois directs effectués pendant une commande slash."""
    current = getattr(app_commands.Command, "_invoke_with_namespace", None)
    if current is None or getattr(current, _MARKER, False):
        return

    async def invoke_with_embed_context(self, interaction: discord.Interaction, *args, **kwargs):
        root = policy._root_from_interaction(interaction) or policy._root_name(self)
        token = policy._COMMAND_ROOT.set(root)
        try:
            return await current(self, interaction, *args, **kwargs)
        finally:
            policy._COMMAND_ROOT.reset(token)

    setattr(invoke_with_embed_context, _MARKER, True)
    invoke_with_embed_context._sentrix_original = current
    app_commands.Command._invoke_with_namespace = invoke_with_embed_context


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_command_embed_invariant_v2", False):
        return
    _install_app_command_context()
    bot._sentrix_command_embed_invariant_v2 = True
    # Ancien marqueur gardé pour les diagnostics/healthchecks historiques.
    bot._sentrix_command_embed_invariant_v1 = True
    logger.info(
        "Invariant embed V2 actif : contexte slash conservé, transport unique délégué à final_interaction_policy."
    )


async def setup(bot: commands.Bot) -> None:
    install(bot)


__all__ = [
    "install",
    "_normalize_command_payload",
    "_ping_stub",
    "_has_non_ping_text",
]
