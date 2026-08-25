"""Transport Discord officiel et unique de SentriX.

Règles :
- toutes les réponses de commandes + et / sont des ``discord.Embed`` ;
- les réponses envoyées indirectement depuis une commande (``ctx.channel.send``,
  ``message.reply``...) sont également converties grâce au contexte d'invocation ;
- les embeds déjà construits sont conservés ;
- les pings explicitement autorisés et les notifications métier ne sont pas cassés ;
- seule la conversation directe ``sentrix`` reste en texte Discord normal ;
- les erreurs et refus slash utilisent les petites cartes officielles.

Aucun autre module ne doit aplatir les embeds en texte.
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
_PLAIN_WEBHOOK_TOKENS: dict[str, float] = {}
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_IMAGE_URL_RE = re.compile(
    r"^https?://\S+\.(?:png|jpe?g|gif|webp)(?:\?\S*)?$", re.IGNORECASE
)


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
    return root == "sentrix"


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


def _clean_embed(embed: discord.Embed | None) -> discord.Embed | None:
    if not isinstance(embed, discord.Embed):
        return embed
    if embed.title:
        embed.title = sentrix_embeds.clean_ui_text(embed.title, 256, "Information")
    embed.colour = discord.Colour(sentrix_embeds.SENTRIX_COLOR)
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=sentrix_embeds.clean_ui_text(field.name, 256, "Information"),
            value=str(field.value or "—")[:1024],
            inline=bool(field.inline),
        )
    footer = getattr(embed.footer, "text", None)
    if not footer:
        embed.set_footer(text="SentriX")
    return embed


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

    chunks: list[str] = []
    remaining = text
    while remaining and len(chunks) < 10:
        if len(remaining) <= 3900:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, 3900)
        if cut < 800:
            cut = remaining.rfind(" ", 0, 3900)
        if cut < 800:
            cut = 3900
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining and chunks:
        chunks[-1] = (chunks[-1][:3700] + "\n\nRéponse tronquée.")[:3900]

    total = len(chunks)
    cards = []
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


def _normalize_payload(
    args: tuple,
    kwargs: dict,
    *,
    editing: bool = False,
    force_embed: bool = True,
):
    new_args = list(args)
    new_kwargs = dict(kwargs)

    if isinstance(new_kwargs.get("embed"), discord.Embed):
        new_kwargs["embed"] = _clean_embed(new_kwargs["embed"])
    if new_kwargs.get("embeds"):
        new_kwargs["embeds"] = [
            _clean_embed(item) if isinstance(item, discord.Embed) else item
            for item in list(new_kwargs["embeds"])
        ]

    content = new_kwargs.get("content")
    positional = False
    if content is None and new_args:
        content = new_args[0]
        positional = True

    has_embed = new_kwargs.get("embed") is not None or bool(new_kwargs.get("embeds"))
    if (
        force_embed
        and content is not None
        and str(content).strip()
        and not has_embed
        and not _explicit_ping_requested(new_kwargs)
    ):
        cards = _cards_from_text(content)
        if len(cards) == 1:
            new_kwargs["embed"] = cards[0]
        else:
            new_kwargs["embeds"] = cards
        if positional and new_args:
            new_args[0] = None
            new_kwargs.pop("content", None)
        else:
            new_kwargs["content"] = None

    if editing and (new_kwargs.get("embed") is not None or new_kwargs.get("embeds")):
        new_kwargs["content"] = None

    return tuple(new_args), new_kwargs


def _install_bot_invoke_context() -> None:
    current = commands.Bot.invoke
    if getattr(current, "_sentrix_embed_context", False):
        return
    base = _unwrap(current)

    async def invoke_with_root(self: commands.Bot, ctx: commands.Context):
        root = _root_name(getattr(ctx, "command", None))
        token = _COMMAND_ROOT.set(root)
        try:
            return await base(self, ctx)
        finally:
            _COMMAND_ROOT.reset(token)

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
            return await base(self, *args, **kwargs)
        args, kwargs = _normalize_payload(args, kwargs)
        return await base(self, *args, **kwargs)

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
        if root and not _plain_root(root):
            args, kwargs = _normalize_payload(args, kwargs)
        elif isinstance(kwargs.get("embed"), discord.Embed):
            kwargs["embed"] = _clean_embed(kwargs["embed"])
        return await base(self, *args, **kwargs)

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
        if root and not _plain_root(root):
            args, kwargs = _normalize_payload(args, kwargs, editing=True)
        return await base(self, *args, **kwargs)

    message_edit._sentrix_official_command_embed = True
    message_edit._sentrix_original = base
    discord.Message.edit = message_edit


def _install_interactions() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_official_embed", False):
        base_send = _unwrap(current_send)

        async def response_send(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            root = _root_from_interaction(interaction)
            if _plain_root(root):
                _remember_plain_interaction(interaction)
                return await base_send(self, *args, **kwargs)
            args, kwargs = _normalize_payload(args, kwargs)
            return await base_send(self, *args, **kwargs)

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
            root = _root_from_interaction(interaction)
            if _plain_root(root):
                _remember_plain_interaction(interaction)
                return await base_edit(self, *args, **kwargs)
            args, kwargs = _normalize_payload(args, kwargs, editing=True)
            return await base_edit(self, *args, **kwargs)

        response_edit._sentrix_official_embed = True
        response_edit._sentrix_original = base_edit
        discord.InteractionResponse.edit_message = response_edit

    current_original = discord.Interaction.edit_original_response
    if not getattr(current_original, "_sentrix_official_embed", False):
        base_original = _unwrap(current_original)

        async def edit_original(self: discord.Interaction, *args, **kwargs):
            root = _root_from_interaction(self)
            if _plain_root(root):
                _remember_plain_interaction(self)
                return await base_original(self, *args, **kwargs)
            args, kwargs = _normalize_payload(args, kwargs, editing=True)
            return await base_original(self, *args, **kwargs)

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
        args, kwargs = _normalize_payload(args, kwargs)
        return await base(self, *args, **kwargs)

    webhook_send._sentrix_official_embed = True
    webhook_send._sentrix_original = base
    discord.Webhook.send = webhook_send


async def _permission_denial(interaction: discord.Interaction, decision) -> None:
    text = str(getattr(decision, "reason", None) or "Vous n'avez pas accès à cette commande.")
    panel = sentrix_embeds.error(text)
    try:
        if interaction.response.is_done():
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
            if interaction.response.is_done():
                await interaction.followup.send(embed=panel, ephemeral=True)
            else:
                await interaction.response.send_message(embed=panel, ephemeral=True)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
            logger.warning("Impossible d'envoyer l'erreur slash finale.")

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
        "Transport officiel actif : toutes les commandes en embeds ; conversation sentrix en texte normal."
    )


__all__ = ["install", "_normalize_payload"]
