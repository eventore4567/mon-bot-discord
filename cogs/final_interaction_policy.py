"""Transport Discord officiel et unique de SentriX.

Règles finales :
- toutes les réponses de commandes + et / utilisent le design SentriX officiel ;
- les anciennes réponses texte sont converties en cartes ;
- les réponses longues sont paginées sur plusieurs messages sans troncature ;
- les embeds historiques sont normalisés au dernier moment ;
- les pings explicitement autorisés restent intacts ;
- seule la conversation directe ``sentrix`` reste en texte Discord normal.
"""
from __future__ import annotations

import contextvars
import logging
import re
import time
from typing import Any

import discord
from discord.ext import commands

from . import permission_guard
from utils import embeds as sentrix_embeds

logger = logging.getLogger("bot.final-interaction-policy")

_COMMAND_ROOT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "sentrix_command_root", default=""
)
_COMMAND_CONTEXT: contextvars.ContextVar[commands.Context | None] = contextvars.ContextVar(
    "sentrix_command_context", default=None
)
_PLAIN_WEBHOOK_TOKENS: dict[str, float] = {}
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_IMAGE_URL_RE = re.compile(
    r"^https?://\S+\.(?:png|jpe?g|gif|webp)(?:\?\S*)?$", re.IGNORECASE
)
_MENTION_RE = re.compile(r"<@!?\d{15,22}>|<@&\d{15,22}>|@everyone|@here", re.IGNORECASE)
_CARD_TEXT_LIMIT = 3400
_SECONDARY_DROP_KEYS = {
    "view", "file", "files", "stickers", "poll", "nonce", "reference",
    "mention_author", "delete_after",
}


def _unwrap(callable_obj):
    seen: set[int] = set()
    current = callable_obj
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _root_name(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    value = (
        getattr(root, "name", "")
        or getattr(command, "qualified_name", "")
        or getattr(command, "name", "")
        or ""
    )
    return str(value).split()[0].casefold()


def _root_from_interaction(interaction: discord.Interaction | None) -> str:
    if interaction is None:
        return ""
    command = getattr(interaction, "command", None)
    if command is not None:
        return _root_name(command)
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        return str(data.get("name") or "").casefold()
    return ""


def _plain_root(root: str) -> bool:
    return str(root or "").casefold() == "sentrix"


def _remember_plain_interaction(interaction: discord.Interaction | None) -> None:
    if interaction is None or not _plain_root(_root_from_interaction(interaction)):
        return
    token = str(getattr(interaction, "token", "") or "")
    if not token:
        return
    now = time.monotonic()
    _PLAIN_WEBHOOK_TOKENS[token] = now
    if len(_PLAIN_WEBHOOK_TOKENS) > 512:
        cutoff = now - 1800
        for key, stamp in list(_PLAIN_WEBHOOK_TOKENS.items()):
            if stamp < cutoff:
                _PLAIN_WEBHOOK_TOKENS.pop(key, None)


def _clean_embed(
    embed: discord.Embed | None,
    *,
    root: str = "",
    bot: Any = None,
) -> discord.Embed | None:
    return sentrix_embeds.style_existing(embed, root=root, bot=bot)


def _title_for_text(text: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in (
        "erreur", "introuvable", "impossible", "refus", "interdit",
        "permission", "échoué", "echoue",
    )):
        return "Erreur"
    if any(word in lowered for word in (
        "attention", "attendre", "cooldown", "recharge", "déjà", "deja",
    )):
        return "Vérification nécessaire"
    if any(word in lowered for word in (
        "réussi", "reussi", "effectué", "effectue", "créé", "cree",
        "ajouté", "ajoute", "retiré", "retire", "enregistré", "enregistre",
        "activé", "active", "terminé", "termine",
    )):
        return "Action effectuée"
    return "Information"


def _split_text(value: Any, limit: int = _CARD_TEXT_LIMIT) -> list[str]:
    """Découpe sans perte en privilégiant les sauts de ligne puis les espaces."""
    text = str(value or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut < max(400, limit // 4):
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut < max(400, limit // 4):
            cut = limit
        chunk = remaining[:cut].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            cut = len(chunk)
        chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    return chunks


def _cards_from_text(value: Any) -> list[discord.Embed]:
    text = str(value or "").strip()
    if not text:
        return [sentrix_embeds.standard("Information", "Aucune information à afficher.")]

    if _IMAGE_URL_RE.match(text):
        card = sentrix_embeds.standard("Résultat", "Image générée.")
        card.set_image(url=text)
        return [card]
    if _URL_RE.match(text):
        return [sentrix_embeds.standard("Lien", f"[Ouvrir le lien]({text})")]

    chunks = _split_text(text)
    total = len(chunks)
    cards: list[discord.Embed] = []
    for index, chunk in enumerate(chunks, start=1):
        title = _title_for_text(chunk) if total == 1 else f"Réponse {index}/{total}"
        cards.append(sentrix_embeds.standard(title, chunk))
    return cards


def _explicit_ping_requested(kwargs: dict) -> bool:
    allowed = kwargs.get("allowed_mentions")
    if allowed is None:
        return False
    for name in ("everyone", "users", "roles"):
        value = getattr(allowed, name, False)
        if value is True or isinstance(value, (list, tuple, set)) and len(value) > 0:
            return True
    return False


def _ping_stub(value: Any) -> str | None:
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


def _readable_without_mentions(value: Any) -> str:
    return _MENTION_RE.sub("", str(value or "")).strip(" \n\t,;:|•-—–")


def _content_from(args: tuple, kwargs: dict) -> tuple[Any, bool]:
    if kwargs.get("content") is not None:
        return kwargs.get("content"), False
    if args:
        return args[0], True
    return None, False


def _set_content(
    args: tuple,
    kwargs: dict,
    *,
    positional: bool,
    value: Any,
) -> tuple[tuple, dict]:
    mutable = list(args)
    if positional and mutable:
        mutable[0] = value
        kwargs.pop("content", None)
    else:
        kwargs["content"] = value
    return tuple(mutable), kwargs


def _normalize_existing(
    args: tuple,
    kwargs: dict,
    *,
    editing: bool,
    root: str,
    bot: Any,
) -> tuple[tuple, dict]:
    new_kwargs = dict(kwargs)
    if isinstance(new_kwargs.get("embed"), discord.Embed):
        new_kwargs["embed"] = _clean_embed(new_kwargs["embed"], root=root, bot=bot)
    if new_kwargs.get("embeds"):
        new_kwargs["embeds"] = [
            _clean_embed(item, root=root, bot=bot) if isinstance(item, discord.Embed) else item
            for item in list(new_kwargs["embeds"])
        ][:10]
    if new_kwargs.get("view") is not None:
        new_kwargs["view"] = sentrix_embeds.clean_view(new_kwargs["view"])
    if editing and (new_kwargs.get("embed") is not None or new_kwargs.get("embeds")):
        new_kwargs["content"] = None
    return tuple(args), new_kwargs


def _secondary_kwargs(kwargs: dict) -> dict:
    result = dict(kwargs)
    for key in _SECONDARY_DROP_KEYS:
        result.pop(key, None)
    result.pop("content", None)
    result.pop("embed", None)
    result.pop("embeds", None)
    return result


def _embed_chars(embed: discord.Embed) -> int:
    try:
        return int(len(embed))
    except Exception:
        return len(str(embed.title or "")) + len(str(embed.description or ""))


def _payload_pages(
    args: tuple,
    kwargs: dict,
    *,
    editing: bool = False,
    force_embed: bool = True,
    root: str = "",
    bot: Any = None,
) -> list[tuple[tuple, dict]]:
    """Construit des payloads Discord valides sans jamais perdre le texte utilisateur."""
    base_args, base_kwargs = _normalize_existing(
        args, kwargs, editing=editing, root=root, bot=bot
    )
    content, positional = _content_from(base_args, base_kwargs)
    if not force_embed or content is None or not str(content).strip():
        return [(base_args, base_kwargs)]

    ping_requested = _explicit_ping_requested(base_kwargs)
    ping_content = _ping_stub(content) if ping_requested else None
    readable = _readable_without_mentions(content) if ping_requested else str(content).strip()

    existing: list[discord.Embed] = []
    single = base_kwargs.get("embed")
    if isinstance(single, discord.Embed):
        existing.append(single)
    existing.extend(
        item for item in list(base_kwargs.get("embeds") or [])
        if isinstance(item, discord.Embed)
    )

    if not readable:
        normalized_args, normalized_kwargs = _set_content(
            base_args, base_kwargs, positional=positional, value=ping_content
        )
        return [(normalized_args, normalized_kwargs)]

    cards = [
        _clean_embed(card, root=root, bot=bot)
        for card in _cards_from_text(readable)
    ]
    cards = [card for card in cards if isinstance(card, discord.Embed)]
    if not cards:
        return [(base_args, base_kwargs)]

    if existing:
        total_chars = sum(_embed_chars(item) for item in [*cards, *existing])
        if len(cards) + len(existing) <= 10 and total_chars <= 5800:
            merged = dict(base_kwargs)
            merged.pop("embed", None)
            merged["embeds"] = [*cards, *existing]
            normalized_args, merged = _set_content(
                base_args, merged, positional=positional, value=ping_content
            )
            return [(normalized_args, merged)]

        first_kwargs = dict(base_kwargs)
        first_args, first_kwargs = _set_content(
            base_args, first_kwargs, positional=positional, value=ping_content
        )
        pages: list[tuple[tuple, dict]] = [(first_args, first_kwargs)]
        secondary = _secondary_kwargs(base_kwargs)
        for card in cards:
            page_kwargs = dict(secondary)
            page_kwargs["embed"] = card
            pages.append(((), page_kwargs))
        return pages

    first_base = dict(base_kwargs)
    first_base.pop("embed", None)
    first_base.pop("embeds", None)
    pages = []
    for index, card in enumerate(cards):
        page_kwargs = dict(first_base if index == 0 else _secondary_kwargs(first_base))
        page_kwargs["embed"] = card
        page_args = base_args if index == 0 else ()
        page_args, page_kwargs = _set_content(
            page_args,
            page_kwargs,
            positional=(positional and index == 0),
            value=(ping_content if index == 0 else None),
        )
        pages.append((page_args, page_kwargs))
    return pages


def _normalize_payload(
    args: tuple,
    kwargs: dict,
    *,
    editing: bool = False,
    force_embed: bool = True,
    root: str = "",
    bot: Any = None,
):
    """Compatibilité : retourne le premier payload d'un envoi."""
    return _payload_pages(
        args,
        kwargs,
        editing=editing,
        force_embed=force_embed,
        root=root,
        bot=bot,
    )[0]


def _mark_context_response(ctx: commands.Context | None, result: Any) -> None:
    if ctx is None:
        return
    ctx._sentrix_response_sent = True
    if result is not None:
        ctx._sentrix_last_response = result


async def _send_pages_with_callable(sender, target, pages):
    first = None
    for page_args, page_kwargs in pages:
        result = await sender(target, *page_args, **page_kwargs)
        if first is None:
            first = result
    return first


def _install_bot_invoke_context() -> None:
    current = commands.Bot.invoke
    if getattr(current, "_sentrix_embed_context", False):
        return
    base = _unwrap(current)

    async def invoke_with_root(self: commands.Bot, ctx: commands.Context):
        root = _root_name(getattr(ctx, "command", None))
        root_token = _COMMAND_ROOT.set(root)
        context_token = _COMMAND_CONTEXT.set(ctx)
        try:
            return await base(self, ctx)
        finally:
            _COMMAND_CONTEXT.reset(context_token)
            _COMMAND_ROOT.reset(root_token)

    invoke_with_root._sentrix_embed_context = True
    invoke_with_root._sentrix_original = base
    commands.Bot.invoke = invoke_with_root


def _install_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_official_embed", False):
        return
    base = _unwrap(current)

    async def context_send(self: commands.Context, *args, **kwargs):
        root = _root_name(getattr(self, "command", None)) or _COMMAND_ROOT.get()
        if _plain_root(root):
            result = await base(self, *args, **kwargs)
            _mark_context_response(self, result)
            return result
        pages = _payload_pages(
            args, kwargs, root=root, bot=getattr(self, "bot", None)
        )
        first = None
        for page_args, page_kwargs in pages:
            result = await base(self, *page_args, **page_kwargs)
            if first is None:
                first = result
        _mark_context_response(self, first)
        return first

    context_send._sentrix_official_embed = True
    context_send._sentrix_original = base
    commands.Context.send = context_send


def _install_messageable_send() -> None:
    current = discord.abc.Messageable.send
    if getattr(current, "_sentrix_official_command_embed", False):
        return
    base = _unwrap(current)

    async def messageable_send(self, *args, **kwargs):
        root = _COMMAND_ROOT.get()
        ctx = _COMMAND_CONTEXT.get()
        if root and not _plain_root(root):
            pages = _payload_pages(args, kwargs, root=root)
            first = await _send_pages_with_callable(base, self, pages)
            _mark_context_response(ctx, first)
            return first
        if isinstance(kwargs.get("embed"), discord.Embed):
            kwargs["embed"] = _clean_embed(kwargs["embed"])
            if kwargs.get("view") is not None:
                kwargs["view"] = sentrix_embeds.clean_view(kwargs["view"])
        result = await base(self, *args, **kwargs)
        if root:
            _mark_context_response(ctx, result)
        return result

    messageable_send._sentrix_official_command_embed = True
    messageable_send._sentrix_original = base
    discord.abc.Messageable.send = messageable_send


def _install_message_edit() -> None:
    current = discord.Message.edit
    if getattr(current, "_sentrix_official_command_embed", False):
        return
    base = _unwrap(current)

    async def message_edit(self: discord.Message, *args, **kwargs):
        root = _COMMAND_ROOT.get()
        if not root or _plain_root(root):
            return await base(self, *args, **kwargs)
        pages = _payload_pages(args, kwargs, editing=True, root=root)
        first_args, first_kwargs = pages[0]
        result = await base(self, *first_args, **first_kwargs)
        if len(pages) > 1:
            raw_send = _unwrap(discord.abc.Messageable.send)
            for page_args, page_kwargs in pages[1:]:
                await raw_send(self.channel, *page_args, **page_kwargs)
        return result

    message_edit._sentrix_official_command_embed = True
    message_edit._sentrix_original = base
    discord.Message.edit = message_edit


async def _send_interaction_pages(
    interaction: discord.Interaction | None,
    base_send,
    response,
    pages: list[tuple[tuple, dict]],
):
    first_args, first_kwargs = pages[0]
    result = await base_send(response, *first_args, **first_kwargs)
    if interaction is not None:
        for page_args, page_kwargs in pages[1:]:
            await interaction.followup.send(*page_args, **page_kwargs)
    return result


def _install_interactions() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_official_embed", False):
        base_send = _unwrap(current_send)

        async def response_send(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = _root_from_interaction(interaction) or _COMMAND_ROOT.get()
            if _plain_root(root):
                _remember_plain_interaction(interaction)
                return await base_send(self, *args, **kwargs)
            pages = _payload_pages(
                args,
                kwargs,
                root=root,
                bot=getattr(interaction, "client", None),
            )
            return await _send_interaction_pages(
                interaction, base_send, self, pages
            )

        response_send._sentrix_official_embed = True
        response_send._sentrix_original = base_send
        discord.InteractionResponse.send_message = response_send

    current_defer = discord.InteractionResponse.defer
    if not getattr(current_defer, "_sentrix_official_embed", False):
        base_defer = _unwrap(current_defer)

        async def response_defer(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            if _plain_root(_root_from_interaction(interaction)):
                _remember_plain_interaction(interaction)
            return await base_defer(self, *args, **kwargs)

        response_defer._sentrix_official_embed = True
        response_defer._sentrix_original = base_defer
        discord.InteractionResponse.defer = response_defer

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, "_sentrix_official_embed", False):
        base_edit = _unwrap(current_edit)

        async def response_edit(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = _root_from_interaction(interaction) or _COMMAND_ROOT.get()
            if _plain_root(root):
                _remember_plain_interaction(interaction)
                return await base_edit(self, *args, **kwargs)
            pages = _payload_pages(
                args,
                kwargs,
                editing=True,
                root=root,
                bot=getattr(interaction, "client", None),
            )
            first_args, first_kwargs = pages[0]
            result = await base_edit(self, *first_args, **first_kwargs)
            if interaction is not None:
                for page_args, page_kwargs in pages[1:]:
                    await interaction.followup.send(*page_args, **page_kwargs)
            return result

        response_edit._sentrix_official_embed = True
        response_edit._sentrix_original = base_edit
        discord.InteractionResponse.edit_message = response_edit

    current_original = discord.Interaction.edit_original_response
    if not getattr(current_original, "_sentrix_official_embed", False):
        base_original = _unwrap(current_original)

        async def edit_original(self: discord.Interaction, *args, **kwargs):
            root = _root_from_interaction(self) or _COMMAND_ROOT.get()
            if _plain_root(root):
                _remember_plain_interaction(self)
                return await base_original(self, *args, **kwargs)
            pages = _payload_pages(
                args,
                kwargs,
                editing=True,
                root=root,
                bot=getattr(self, "client", None),
            )
            first_args, first_kwargs = pages[0]
            result = await base_original(self, *first_args, **first_kwargs)
            for page_args, page_kwargs in pages[1:]:
                await self.followup.send(*page_args, **page_kwargs)
            return result

        edit_original._sentrix_official_embed = True
        edit_original._sentrix_original = base_original
        discord.Interaction.edit_original_response = edit_original


def _install_followups() -> None:
    current = discord.Webhook.send
    if getattr(current, "_sentrix_official_embed", False):
        return
    base = _unwrap(current)

    async def webhook_send(self: discord.Webhook, *args, **kwargs):
        if getattr(self, "type", None) != discord.WebhookType.application:
            return await base(self, *args, **kwargs)
        token = str(getattr(self, "token", "") or "")
        if token and token in _PLAIN_WEBHOOK_TOKENS:
            return await base(self, *args, **kwargs)
        root = _COMMAND_ROOT.get()
        pages = _payload_pages(args, kwargs, root=root)
        return await _send_pages_with_callable(base, self, pages)

    webhook_send._sentrix_official_embed = True
    webhook_send._sentrix_original = base
    discord.Webhook.send = webhook_send


async def _permission_denial(interaction: discord.Interaction, decision) -> None:
    text = str(getattr(decision, "reason", None) or "Vous n'avez pas accès à cette commande.")
    panel = sentrix_embeds.error(text)
    try:
        if interaction.response.is_done():
            response_type = getattr(interaction.response, "type", None)
            if response_type == discord.InteractionResponseType.deferred_channel_message:
                await interaction.edit_original_response(content=None, embed=panel)
            else:
                await interaction.followup.send(embed=panel, ephemeral=True)
        else:
            await interaction.response.send_message(embed=panel, ephemeral=True)
    except (discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
        logger.debug("Impossible d'envoyer un refus slash.", exc_info=True)


def _slash_error_embed(error: BaseException) -> discord.Embed:
    original = getattr(error, "original", error)
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        return sentrix_embeds.warning(
            f"Cette commande est en recharge. Réessayez dans {max(1, round(error.retry_after))} s."
        )
    if isinstance(error, discord.app_commands.MissingPermissions):
        return sentrix_embeds.error("Vous n'avez pas les permissions nécessaires pour cette commande.")
    if isinstance(error, discord.app_commands.BotMissingPermissions):
        return sentrix_embeds.error("SentriX n'a pas les permissions nécessaires pour terminer cette action.")
    if isinstance(original, discord.Forbidden):
        return sentrix_embeds.error("Discord a refusé cette action. Vérifiez les permissions du bot.")
    if isinstance(error, discord.app_commands.CheckFailure):
        return sentrix_embeds.error("Vous n'avez pas accès à cette commande.")
    return sentrix_embeds.error("Cette commande a rencontré un problème technique.")


def _install_errors(bot: commands.Bot) -> None:
    permission_guard._send_interaction_denial = _permission_denial

    async def tree_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        panel = _slash_error_embed(error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=panel, ephemeral=True)
                return
            response_type = getattr(interaction.response, "type", None)
            if response_type in {
                discord.InteractionResponseType.deferred_channel_message,
                discord.InteractionResponseType.deferred_message_update,
            }:
                await interaction.edit_original_response(content=None, embed=panel, view=None)
                return
            await interaction.edit_original_response(content=None, embed=panel)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
            logger.warning("Impossible d'envoyer l'erreur slash finale.")

    tree_error._sentrix_official_error_owner = True
    bot.tree.on_error = tree_error


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_official_embed_transport", False):
        return
    _install_bot_invoke_context()
    _install_context_send()
    _install_messageable_send()
    _install_message_edit()
    _install_interactions()
    _install_followups()
    _install_errors(bot)
    bot._sentrix_official_embed_transport = True
    logger.info(
        "Transport officiel actif : cartes SentriX sans troncature, pagination longue et réponse unique."
    )


__all__ = [
    "install",
    "_normalize_payload",
    "_payload_pages",
    "_cards_from_text",
    "_clean_embed",
    "_explicit_ping_requested",
    "_root_from_interaction",
    "_root_name",
    "_plain_root",
    "_COMMAND_ROOT",
    "_COMMAND_CONTEXT",
    "_unwrap",
]
