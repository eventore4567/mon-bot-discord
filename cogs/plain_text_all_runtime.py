"""Politique finale de réponses texte SentriX.

Toutes les réponses de COMMANDES ordinaires sont envoyées en texte Discord natif :
    ✅ | [PING] | Pong !
    Latence: 68ms

Les vrais panneaux de configuration restent en embed. Les logs, panneaux de tickets et
messages automatiques envoyés directement dans un salon ne sont pas transformés.

Cette couche contourne explicitement premium_style_runtime pour les transports de réponse
aux commandes. C'est indispensable : l'ancien runtime premium transformait de nouveau le
texte en embed après les anciennes tentatives de nettoyage.
"""
from __future__ import annotations

import re
from typing import Any

import discord
from discord.ext import commands


# Uniquement les interfaces qui ont réellement besoin d'une carte riche pour fonctionner.
RICH_ROOTS = frozenset({
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
    "shoppanel",
    "create",
})

ERROR_WORDS = (
    "erreur", "impossible", "introuvable", "invalide", "refus", "échoué", "echoue",
    "échec", "echec", "permission", "problème", "probleme", "indisponible", "cooldown",
    "recharge", "blacklist", "banni", "interdit",
)

_EXISTING_PREFIX_RE = re.compile(
    r"^(?:(?:✅|❌|⚠️|•|!)\s*)?\|\s*\[[^\]]+\]\s*\|\s*",
    re.IGNORECASE,
)


def _raw_transport(name: str, fallback):
    """Récupère le vrai transport discord.py sauvegardé avant le style premium."""
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
    name = str(getattr(command, "qualified_name", "") or getattr(command, "name", "") or "SENTRIX")
    return name.replace("_", "-").replace(" ", "-").upper()[:32]


def _label_from_ctx(ctx: commands.Context) -> str:
    return _label_from_command(getattr(ctx, "command", None))


def _label_from_interaction(interaction: discord.Interaction | None) -> str:
    if interaction is not None and getattr(interaction, "command", None) is not None:
        return _label_from_command(interaction.command)
    data = getattr(interaction, "data", None) if interaction is not None else None
    if isinstance(data, dict) and data.get("type", 1) == 1:
        return str(data.get("name") or "SENTRIX").replace("_", "-").replace(" ", "-").upper()[:32]
    return "SENTRIX"


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    # Les anciens embeds mettent presque tout en gras. Le style compact demandé est plus net.
    text = text.replace("**", "")
    return text


def _embed_to_text(embed: Any) -> str:
    if not isinstance(embed, discord.Embed):
        return ""

    lines: list[str] = []
    title = _clean(embed.title)
    description = _clean(embed.description)

    generic_titles = {
        "information", "succès", "succes", "erreur", "avertissement",
        "action terminée", "action terminee", "sentrix / utilitaires",
        "sentrix / économie", "sentrix / economie", "sentrix / modération",
        "sentrix / moderation", "sentrix / intelligence artificielle",
    }
    if title and title.casefold() not in generic_titles and not title.casefold().startswith("sentrix /"):
        lines.append(title)
    if description:
        lines.append(description)

    for field in list(embed.fields):
        name = _clean(field.name)
        value = _clean(field.value)
        if not value:
            continue
        if name and name.casefold() not in {"information", "détail", "detail"}:
            lines.append(f"{name}: {value}")
        else:
            lines.append(value)

    # Si une commande affichait une image dans une carte (avatar, bannière, etc.), on garde
    # l'accès à l'image sous forme de lien sans aperçu automatique afin de ne recréer aucune box.
    for proxy in (getattr(embed, "image", None), getattr(embed, "thumbnail", None)):
        url = str(getattr(proxy, "url", "") or "").strip()
        if url:
            lines.append(f"<{url}>")

    return "\n".join(part for part in lines if part).strip()


def _body_from_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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


def _is_error(text: str) -> bool:
    lowered = text.casefold()
    return any(word in lowered for word in ERROR_WORDS)


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
    marker = "❌" if _is_error(body) else "✅"
    prefix = f"{marker} | [{label}] | "
    available = max(400, 1950 - len(prefix))
    parts = _split_body(body, available)
    return [prefix + part if part else prefix.rstrip() for part in parts]


def _secondary_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Les fichiers/boutons ne doivent être joints qu'au premier morceau d'une longue réponse."""
    result = dict(kwargs)
    for key in (
        "file", "files", "attachments", "view", "stickers", "reference", "mention_author",
        "suppress_embeds", "silent", "delete_after",
    ):
        result.pop(key, None)
    return result


def install(bot: commands.Bot) -> None:
    # Les originaux premium sont les transports discord.py AVANT transformation en embed.
    raw_messageable_send = _raw_transport("messageable_send", discord.abc.Messageable.send)
    raw_message_edit = _raw_transport("message_edit", discord.Message.edit)
    raw_context_send = _raw_transport("context_send", commands.Context.send)
    raw_context_reply = _raw_transport("context_reply", commands.Context.reply)
    raw_interaction_send = _raw_transport("interaction_send", discord.InteractionResponse.send_message)
    raw_interaction_edit = _raw_transport("interaction_edit", discord.InteractionResponse.edit_message)
    raw_edit_original = _raw_transport("interaction_edit_original", discord.Interaction.edit_original_response)
    raw_webhook_send = _raw_transport("webhook_send", discord.Webhook.send)

    # Retire définitivement l'enveloppe premium des transports génériques. Les embeds
    # explicitement envoyés par les logs/panels restent des embeds ; seul l'auto-wrap disparaît.
    discord.abc.Messageable.send = raw_messageable_send
    discord.Message.edit = raw_message_edit
    discord.Webhook.send = raw_webhook_send

    previous_context_send = commands.Context.send
    previous_context_reply = commands.Context.reply
    previous_interaction_send = discord.InteractionResponse.send_message
    previous_interaction_edit = discord.InteractionResponse.edit_message
    previous_edit_original = discord.Interaction.edit_original_response

    async def context_send(self: commands.Context, *args, **kwargs):
        root = _root_from_ctx(self)
        if root in RICH_ROOTS:
            return await previous_context_send(self, *args, **kwargs)

        body, clean_kwargs = _body_from_args(tuple(args), kwargs)
        if not body:
            # Réponse sans texte (ex. uniquement un fichier) : pas de transformation forcée.
            return await raw_context_send(self, *args, **kwargs)

        chunks = _formatted_chunks(body, _label_from_ctx(self))
        first_kwargs = dict(clean_kwargs)

        result = await raw_context_send(self, chunks[0], **first_kwargs)
        if len(chunks) == 1:
            return result

        follow_kwargs = _secondary_kwargs(first_kwargs)
        if self.interaction is not None:
            # Après le premier envoi, les morceaux suivants sont de vrais follow-ups slash.
            for chunk in chunks[1:]:
                await raw_webhook_send(self.interaction.followup, chunk, **follow_kwargs)
        else:
            for chunk in chunks[1:]:
                await raw_messageable_send(self.channel, chunk, **follow_kwargs)
        return result

    async def context_reply(self: commands.Context, *args, **kwargs):
        root = _root_from_ctx(self)
        if root in RICH_ROOTS:
            return await previous_context_reply(self, *args, **kwargs)
        if self.interaction is None and self.message is not None and "reference" not in kwargs:
            kwargs["reference"] = self.message.to_reference(fail_if_not_exists=False)
            kwargs.setdefault("mention_author", False)
        return await context_send(self, *args, **kwargs)

    async def interaction_send(self: discord.InteractionResponse, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        root = _root_from_interaction(interaction)
        # Les clics de composants n'ont généralement pas de command root : on les laisse
        # intacts pour ne pas casser les panneaux de configuration/tickets.
        if not root or root in RICH_ROOTS:
            return await raw_interaction_send(self, *args, **kwargs)

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
        if not root or root in RICH_ROOTS:
            return await raw_interaction_edit(self, *args, **kwargs)
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
        if not root or root in RICH_ROOTS:
            return await raw_edit_original(self, *args, **kwargs)
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

    # Marqueurs utiles pour les diagnostics et pour éviter les doubles préfixes.
    context_send._sentrix_plain_text_all = True
    context_send._sentrix_original = raw_context_send
    context_reply._sentrix_plain_text_all = True
    interaction_send._sentrix_plain_text_all = True
    interaction_send._sentrix_original = raw_interaction_send
    interaction_edit._sentrix_plain_text_all = True
    interaction_edit._sentrix_original = raw_interaction_edit
    edit_original._sentrix_plain_text_all = True
    edit_original._sentrix_original = raw_edit_original

    commands.Context.send = context_send
    commands.Context.reply = context_reply
    discord.InteractionResponse.send_message = interaction_send
    discord.InteractionResponse.edit_message = interaction_edit
    discord.Interaction.edit_original_response = edit_original

    bot._sentrix_plain_text_all_runtime = True
