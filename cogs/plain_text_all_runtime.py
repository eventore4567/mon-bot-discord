"""Politique finale de rendu des commandes SentriX.

Exactement 30 commandes simples utilisent un message Discord natif sans embed.
Toutes les autres commandes conservent le rendu encadré/premium déjà produit par SentriX.

Cette couche ne modifie jamais les logs, les messages automatiques ou les panneaux envoyés
hors du contexte d'une commande. Elle ne remplace pas le moteur d'exécution des commandes.
"""
from __future__ import annotations

import re
from typing import Any

import discord
from discord.ext import commands


# EXACTEMENT 30 commandes en texte libre. Tout le reste reste en box.
PLAIN_ROOTS = frozenset({
    "ping",
    "balance",
    "daily",
    "weekly",
    "work",
    "rob",
    "pay",
    "deposit",
    "withdraw",
    "gamble",
    "sell",
    "afk",
    "roll",
    "choose",
    "translate",
    "weather",
    "remind",
    "reminder-list",
    "reminder-cancel",
    "membercount",
    "ban",
    "tempban",
    "unban",
    "kick",
    "mute",
    "unmute",
    "warn",
    "unwarn",
    "clear",
    "slowmode",
})

ERROR_WORDS = (
    "erreur",
    "impossible",
    "introuvable",
    "invalide",
    "refus",
    "échoué",
    "echoue",
    "échec",
    "echec",
    "permission",
    "problème",
    "probleme",
    "indisponible",
    "blacklist",
    "banni",
    "interdit",
)

WARNING_WORDS = (
    "attention",
    "avertissement",
    "cooldown",
    "patiente",
    "attends",
    "déjà",
    "deja",
)

_EXISTING_PREFIX_RE = re.compile(
    r"^(?:(?:✅|❌|⚠️|•|!)\s*)?\|\s*\[[^\]]+\]\s*\|\s*",
    re.IGNORECASE,
)


def _raw_transport(name: str, fallback):
    """Récupère le transport discord.py sauvegardé avant premium_style_runtime."""
    try:
        from . import premium_style_runtime

        candidate = premium_style_runtime._ORIGINALS.get(name)
        if callable(candidate):
            return candidate
    except Exception:
        pass
    return fallback


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
    if isinstance(data, dict) and data.get("type", 1) == 1:
        return str(data.get("name") or "").casefold()
    return ""


def _label_from_command(command: Any) -> str:
    if command is None:
        return "SENTRIX"
    name = str(
        getattr(command, "qualified_name", "")
        or getattr(command, "name", "")
        or "SENTRIX"
    )
    return name.replace("_", "-").replace(" ", "-").upper()[:32]


def _label_from_ctx(ctx: commands.Context) -> str:
    return _label_from_command(getattr(ctx, "command", None))


def _label_from_interaction(interaction: discord.Interaction | None) -> str:
    if interaction is not None and getattr(interaction, "command", None) is not None:
        return _label_from_command(interaction.command)
    data = getattr(interaction, "data", None) if interaction is not None else None
    if isinstance(data, dict) and data.get("type", 1) == 1:
        return (
            str(data.get("name") or "SENTRIX")
            .replace("_", "-")
            .replace(" ", "-")
            .upper()[:32]
        )
    return "SENTRIX"


def _clean(value: Any) -> str:
    return str(value or "").strip().replace("**", "")


def _embed_to_text(embed: Any) -> str:
    """Convertit uniquement les embeds des 30 commandes simples en texte lisible."""
    if not isinstance(embed, discord.Embed):
        return ""

    lines: list[str] = []
    title = _clean(embed.title)
    description = _clean(embed.description)

    generic_titles = {
        "information",
        "succès",
        "succes",
        "erreur",
        "avertissement",
        "action terminée",
        "action terminee",
        "sentrix / utilitaires",
        "sentrix / économie",
        "sentrix / economie",
        "sentrix / modération",
        "sentrix / moderation",
        "sentrix / intelligence artificielle",
    }

    if (
        title
        and title.casefold() not in generic_titles
        and not title.casefold().startswith("sentrix /")
    ):
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

    # On ne transforme jamais une image/avatar en URL brute.
    return "\n".join(part for part in lines if part).strip()


def _body_from_args(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    mutable_kwargs = dict(kwargs)
    pieces: list[str] = []

    if args and isinstance(args[0], str) and args[0].strip():
        pieces.append(_clean(args[0]))
    elif isinstance(mutable_kwargs.get("content"), str) and mutable_kwargs["content"].strip():
        pieces.append(_clean(mutable_kwargs.pop("content")))

    embed = mutable_kwargs.pop("embed", None)
    text = _embed_to_text(embed)
    if text:
        pieces.append(text)

    embeds = mutable_kwargs.pop("embeds", None)
    if isinstance(embeds, (list, tuple)):
        for item in embeds:
            text = _embed_to_text(item)
            if text:
                pieces.append(text)

    body = "\n".join(piece for piece in pieces if piece).strip()
    body = _EXISTING_PREFIX_RE.sub("", body, count=1).strip()
    return body, mutable_kwargs


def _status(text: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ERROR_WORDS):
        return "❌"
    if any(word in lowered for word in WARNING_WORDS):
        return "⚠️"
    return "✅"


def _split_body(text: str, limit: int) -> list[str]:
    text = text.strip()
    if not text:
        return [""]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()

    if remaining or not chunks:
        chunks.append(remaining)
    return chunks


def _formatted_chunks(body: str, label: str) -> list[str]:
    prefix = f"{_status(body)} | [{label}] | "
    available = max(400, 1950 - len(prefix))
    parts = _split_body(body, available)

    result: list[str] = []
    for index, part in enumerate(parts):
        if index == 0:
            result.append(prefix + part if part else prefix.rstrip())
        else:
            # Une longue réponse reste aérée ; on ne répète pas le préfixe à chaque bloc.
            result.append(part)
    return result


def _secondary_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    result = dict(kwargs)
    for key in (
        "file",
        "files",
        "attachments",
        "view",
        "stickers",
        "reference",
        "mention_author",
        "suppress_embeds",
        "silent",
        "delete_after",
    ):
        result.pop(key, None)
    return result


def _boxed_fallback(current, marker_name: str):
    """Évite d'empiler notre propre wrapper lors du second install(on_ready)."""
    if getattr(current, "_sentrix_plain_30", False):
        previous = getattr(current, marker_name, None)
        if callable(previous):
            return previous
    return current


def install(bot: commands.Bot) -> None:
    raw_context_send = _raw_transport("context_send", commands.Context.send)
    raw_context_reply = _raw_transport("context_reply", commands.Context.reply)
    raw_interaction_send = _raw_transport(
        "interaction_send", discord.InteractionResponse.send_message
    )
    raw_interaction_edit = _raw_transport(
        "interaction_edit", discord.InteractionResponse.edit_message
    )
    raw_edit_original = _raw_transport(
        "interaction_edit_original", discord.Interaction.edit_original_response
    )
    raw_messageable_send = _raw_transport(
        "messageable_send", discord.abc.Messageable.send
    )
    raw_webhook_send = _raw_transport("webhook_send", discord.Webhook.send)

    # Pour les commandes hors liste, on garde EXACTEMENT la chaîne de style existante.
    boxed_context_send = _boxed_fallback(
        commands.Context.send, "_sentrix_boxed_context_send"
    )
    boxed_context_reply = _boxed_fallback(
        commands.Context.reply, "_sentrix_boxed_context_reply"
    )
    boxed_interaction_send = _boxed_fallback(
        discord.InteractionResponse.send_message,
        "_sentrix_boxed_interaction_send",
    )
    boxed_interaction_edit = _boxed_fallback(
        discord.InteractionResponse.edit_message,
        "_sentrix_boxed_interaction_edit",
    )
    boxed_edit_original = _boxed_fallback(
        discord.Interaction.edit_original_response,
        "_sentrix_boxed_edit_original",
    )

    async def context_send(self: commands.Context, *args, **kwargs):
        root = _root_from_ctx(self)
        if root not in PLAIN_ROOTS:
            return await boxed_context_send(self, *args, **kwargs)

        body, clean_kwargs = _body_from_args(tuple(args), kwargs)
        if not body:
            return await raw_context_send(self, *args, **kwargs)

        chunks = _formatted_chunks(body, _label_from_ctx(self))
        result = await raw_context_send(self, chunks[0], **dict(clean_kwargs))

        if len(chunks) > 1:
            follow_kwargs = _secondary_kwargs(clean_kwargs)
            if self.interaction is not None:
                for chunk in chunks[1:]:
                    await raw_webhook_send(self.interaction.followup, chunk, **follow_kwargs)
            else:
                for chunk in chunks[1:]:
                    await raw_messageable_send(self.channel, chunk, **follow_kwargs)
        return result

    async def context_reply(self: commands.Context, *args, **kwargs):
        root = _root_from_ctx(self)
        if root not in PLAIN_ROOTS:
            return await boxed_context_reply(self, *args, **kwargs)

        if self.interaction is None and self.message is not None and "reference" not in kwargs:
            kwargs["reference"] = self.message.to_reference(fail_if_not_exists=False)
            kwargs.setdefault("mention_author", False)
        return await context_send(self, *args, **kwargs)

    async def interaction_send(self: discord.InteractionResponse, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        root = _root_from_interaction(interaction)
        if not root or root not in PLAIN_ROOTS:
            return await boxed_interaction_send(self, *args, **kwargs)

        body, clean_kwargs = _body_from_args(tuple(args), kwargs)
        if not body:
            return await raw_interaction_send(self, *args, **kwargs)

        chunks = _formatted_chunks(body, _label_from_interaction(interaction))
        result = await raw_interaction_send(self, chunks[0], **clean_kwargs)

        if interaction is not None and len(chunks) > 1:
            follow_kwargs = _secondary_kwargs(clean_kwargs)
            for chunk in chunks[1:]:
                await raw_webhook_send(interaction.followup, chunk, **follow_kwargs)
        return result

    async def interaction_edit(self: discord.InteractionResponse, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        root = _root_from_interaction(interaction)
        if not root or root not in PLAIN_ROOTS:
            return await boxed_interaction_edit(self, *args, **kwargs)

        body, clean_kwargs = _body_from_args(tuple(args), kwargs)
        if not body:
            return await raw_interaction_edit(self, *args, **kwargs)

        chunks = _formatted_chunks(body, _label_from_interaction(interaction))
        clean_kwargs["content"] = chunks[0]
        clean_kwargs["embeds"] = []
        result = await raw_interaction_edit(self, **clean_kwargs)

        if interaction is not None and len(chunks) > 1:
            follow_kwargs = _secondary_kwargs(clean_kwargs)
            follow_kwargs.pop("embeds", None)
            for chunk in chunks[1:]:
                await raw_webhook_send(interaction.followup, chunk, **follow_kwargs)
        return result

    async def edit_original(self: discord.Interaction, *args, **kwargs):
        root = _root_from_interaction(self)
        if not root or root not in PLAIN_ROOTS:
            return await boxed_edit_original(self, *args, **kwargs)

        body, clean_kwargs = _body_from_args(tuple(args), kwargs)
        if not body:
            return await raw_edit_original(self, *args, **kwargs)

        chunks = _formatted_chunks(body, _label_from_interaction(self))
        clean_kwargs["content"] = chunks[0]
        clean_kwargs["embeds"] = []
        result = await raw_edit_original(self, **clean_kwargs)

        if len(chunks) > 1:
            follow_kwargs = _secondary_kwargs(clean_kwargs)
            follow_kwargs.pop("embeds", None)
            for chunk in chunks[1:]:
                await raw_webhook_send(self.followup, chunk, **follow_kwargs)
        return result

    # Marqueurs + références au vrai fallback boxed pour les réinstallations on_ready.
    context_send._sentrix_plain_30 = True
    context_send._sentrix_boxed_context_send = boxed_context_send
    context_reply._sentrix_plain_30 = True
    context_reply._sentrix_boxed_context_reply = boxed_context_reply
    interaction_send._sentrix_plain_30 = True
    interaction_send._sentrix_boxed_interaction_send = boxed_interaction_send
    interaction_edit._sentrix_plain_30 = True
    interaction_edit._sentrix_boxed_interaction_edit = boxed_interaction_edit
    edit_original._sentrix_plain_30 = True
    edit_original._sentrix_boxed_edit_original = boxed_edit_original

    commands.Context.send = context_send
    commands.Context.reply = context_reply
    discord.InteractionResponse.send_message = interaction_send
    discord.InteractionResponse.edit_message = interaction_edit
    discord.Interaction.edit_original_response = edit_original

    bot._sentrix_plain_text_all_runtime = True
