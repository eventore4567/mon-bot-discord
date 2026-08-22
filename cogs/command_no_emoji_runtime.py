"""Politique globale : aucune décoration emoji dans les commandes SentriX.

Cette couche est volontairement transversale. Elle nettoie au dernier moment les réponses
issues des commandes préfixées, hybrides, slash et de leurs composants interactifs. Ainsi,
un ancien cog ou une future commande peut encore contenir un pictogramme dans son code sans
qu'il réapparaisse dans l'interface utilisateur.

Les images, avatars, pièces jointes, mentions, IDs et données fonctionnelles ne sont jamais
supprimés. Seuls les emojis Unicode / emojis Discord décoratifs présents dans le texte des
réponses et les propriétés `emoji` des composants sont retirés.
"""
from __future__ import annotations

import logging
import re
from contextvars import ContextVar

import discord
from discord.ext import commands

logger = logging.getLogger("bot.command-no-emoji")

_INSTALLED = False
_COMMAND_DEPTH: ContextVar[int] = ContextVar("sentrix_command_depth", default=0)
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_~]+:\d+>")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MANY_BLANKS_RE = re.compile(r"\n{3,}")

# Plages utilisées par les emojis/pictogrammes décoratifs modernes. Les caractères de
# structure textuelle (puces simples, barres, markdown, flèches ASCII) restent intacts.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
)
_EMOJI_SINGLETONS = {
    0x200D,  # zero-width joiner
    0x20E3,  # keycap combining mark
    0xFE0E,  # text variation selector
    0xFE0F,  # emoji variation selector
}


def _is_emoji_char(char: str) -> bool:
    code = ord(char)
    if code in _EMOJI_SINGLETONS:
        return True
    return any(start <= code <= end for start, end in _EMOJI_RANGES)


def has_emoji(value: object | None) -> bool:
    if value is None:
        return False
    text = str(value)
    if _CUSTOM_EMOJI_RE.search(text):
        return True
    return any(_is_emoji_char(char) for char in text)


def clean_text(value: object | None, *, fallback: str = "") -> str:
    """Retire les emojis tout en conservant le texte et le markdown utiles."""
    if value is None:
        return fallback
    text = _CUSTOM_EMOJI_RE.sub("", str(value))
    text = "".join(char for char in text if not _is_emoji_char(char))
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = _MANY_BLANKS_RE.sub("\n\n", text)
    text = text.strip()
    return text or fallback


def clean_embed(embed: discord.Embed | None) -> discord.Embed | None:
    if embed is None:
        return None

    # La copie évite de modifier un template réutilisé ailleurs par un cog.
    cleaned = embed.copy()
    if cleaned.title is not None:
        cleaned.title = clean_text(cleaned.title, fallback="SentriX")
    if cleaned.description is not None:
        cleaned.description = clean_text(cleaned.description)

    fields = list(cleaned.fields)
    for index, field in enumerate(fields):
        cleaned.set_field_at(
            index,
            name=clean_text(field.name, fallback="Information"),
            value=clean_text(field.value, fallback="\u200b"),
            inline=bool(field.inline),
        )

    footer_text = getattr(cleaned.footer, "text", None)
    footer_icon = getattr(cleaned.footer, "icon_url", None)
    if footer_text is not None or footer_icon:
        kwargs = {"text": clean_text(footer_text, fallback="SentriX")}
        if footer_icon:
            kwargs["icon_url"] = str(footer_icon)
        cleaned.set_footer(**kwargs)

    author_name = getattr(cleaned.author, "name", None)
    if author_name is not None:
        kwargs = {"name": clean_text(author_name, fallback="SentriX")}
        author_url = getattr(cleaned.author, "url", None)
        author_icon = getattr(cleaned.author, "icon_url", None)
        if author_url:
            kwargs["url"] = str(author_url)
        if author_icon:
            kwargs["icon_url"] = str(author_icon)
        cleaned.set_author(**kwargs)

    return cleaned


def _clean_component_item(item) -> None:
    """Nettoie boutons, selects et champs de formulaire sans modifier leur logique."""
    if hasattr(item, "emoji"):
        try:
            item.emoji = None
        except Exception:
            pass

    label = getattr(item, "label", None)
    if label is not None:
        fallback = "Ouvrir" if getattr(item, "url", None) else "Action"
        try:
            item.label = clean_text(label, fallback=fallback)[:80]
        except Exception:
            pass

    placeholder = getattr(item, "placeholder", None)
    if placeholder is not None:
        try:
            item.placeholder = clean_text(placeholder, fallback="Selectionner...")[:150]
        except Exception:
            pass

    options = getattr(item, "options", None)
    if options:
        for option in options:
            try:
                option.emoji = None
            except Exception:
                pass
            try:
                option.label = clean_text(option.label, fallback="Option")[:100]
            except Exception:
                pass
            try:
                if option.description is not None:
                    description = clean_text(option.description)
                    option.description = description[:100] if description else None
            except Exception:
                pass

    # TextInput : label/placeholder sont déjà couverts ci-dessus.


def clean_view(view):
    if view is None:
        return None
    for item in list(getattr(view, "children", ()) or ()):
        _clean_component_item(item)
    return view


def clean_modal(modal):
    if modal is None:
        return None
    title = getattr(modal, "title", None)
    if title is not None:
        try:
            modal.title = clean_text(title, fallback="SentriX")[:45]
        except Exception:
            # Certaines versions exposent le titre en lecture seule après construction.
            try:
                modal._title = clean_text(title, fallback="SentriX")[:45]
            except Exception:
                pass
    return clean_view(modal)


def _clean_send_args(args: tuple, kwargs: dict) -> tuple[tuple, dict]:
    """Nettoie les paramètres d'envoi sans toucher aux sentinelles internes discord.py."""
    args = list(args)
    kwargs = dict(kwargs)
    missing = getattr(discord.utils, "MISSING", object())

    # discord.py utilise MISSING pour distinguer « argument absent » de None.
    # Il ne faut surtout pas convertir cette sentinelle en texte ou tenter de l'itérer.
    if args and args[0] is not None and args[0] is not missing:
        args[0] = clean_text(args[0], fallback="SentriX")

    content = kwargs.get("content", missing)
    if content is not missing and content is not None:
        kwargs["content"] = clean_text(content, fallback="SentriX")

    embed = kwargs.get("embed", missing)
    if embed is not missing and embed is not None:
        kwargs["embed"] = clean_embed(embed)

    embeds = kwargs.get("embeds", missing)
    if embeds is not missing and embeds is not None:
        kwargs["embeds"] = [clean_embed(item) for item in embeds]

    view = kwargs.get("view", missing)
    if view is not missing and view is not None:
        kwargs["view"] = clean_view(view)

    return tuple(args), kwargs


def _clean_edit_kwargs(kwargs: dict) -> dict:
    """Version prudente pour les APIs d'édition qui utilisent parfois MISSING."""
    cleaned = dict(kwargs)
    missing = getattr(discord.utils, "MISSING", object())

    content = cleaned.get("content", missing)
    if content is not missing and content is not None:
        cleaned["content"] = clean_text(content, fallback="SentriX")

    embed = cleaned.get("embed", missing)
    if embed is not missing and embed is not None:
        cleaned["embed"] = clean_embed(embed)

    embeds = cleaned.get("embeds", missing)
    if embeds is not missing and embeds is not None:
        cleaned["embeds"] = [clean_embed(item) for item in embeds]

    view = cleaned.get("view", missing)
    if view is not missing and view is not None:
        cleaned["view"] = clean_view(view)
    return cleaned


def _clean_command_metadata(bot: commands.Bot) -> None:
    """Nettoie aussi les descriptions visibles dans le catalogue et les slash commands."""
    for command in bot.walk_commands():
        for attr in ("help", "brief", "description", "usage"):
            value = getattr(command, attr, None)
            if isinstance(value, str) and has_emoji(value):
                try:
                    setattr(command, attr, clean_text(value))
                except Exception:
                    pass
        app_command = getattr(command, "app_command", None)
        description = getattr(app_command, "description", None)
        if isinstance(description, str) and has_emoji(description):
            try:
                app_command.description = clean_text(description, fallback="Commande SentriX")[:100]
            except Exception:
                pass


def _patch_command_scope() -> None:
    current = commands.Command.invoke
    if not getattr(current, "_sentrix_no_emoji_scope", False):
        async def command_invoke(self, ctx):
            token = _COMMAND_DEPTH.set(_COMMAND_DEPTH.get() + 1)
            try:
                return await current(self, ctx)
            finally:
                _COMMAND_DEPTH.reset(token)

        command_invoke._sentrix_no_emoji_scope = True
        commands.Command.invoke = command_invoke

    # Group possède sa propre implémentation dans discord.py. Le wrapper est donc posé
    # séparément pour que les envois directs dans un groupe soient aussi couverts.
    current_group = commands.Group.invoke
    if not getattr(current_group, "_sentrix_no_emoji_scope", False):
        async def group_invoke(self, ctx):
            token = _COMMAND_DEPTH.set(_COMMAND_DEPTH.get() + 1)
            try:
                return await current_group(self, ctx)
            finally:
                _COMMAND_DEPTH.reset(token)

        group_invoke._sentrix_no_emoji_scope = True
        commands.Group.invoke = group_invoke


def _patch_context_send() -> None:
    current = commands.Context.send
    if getattr(current, "_sentrix_no_emoji_commands", False):
        return

    async def context_send(self, *args, **kwargs):
        args, kwargs = _clean_send_args(args, kwargs)
        return await current(self, *args, **kwargs)

    context_send._sentrix_no_emoji_commands = True
    commands.Context.send = context_send


def _patch_messageable_send() -> None:
    current = discord.abc.Messageable.send
    if getattr(current, "_sentrix_no_emoji_commands", False):
        return

    async def messageable_send(self, *args, **kwargs):
        # Les envois directs `ctx.channel.send(...)` sont nettoyés uniquement pendant
        # l'exécution d'une commande afin de ne pas modifier les messages configurés par
        # les utilisateurs (welcome, annonces automatiques, notifications sociales...).
        if _COMMAND_DEPTH.get() > 0:
            args, kwargs = _clean_send_args(args, kwargs)
        return await current(self, *args, **kwargs)

    messageable_send._sentrix_no_emoji_commands = True
    discord.abc.Messageable.send = messageable_send


def _patch_interactions() -> None:
    current_send = discord.InteractionResponse.send_message
    if not getattr(current_send, "_sentrix_no_emoji_commands", False):
        async def response_send(self, *args, **kwargs):
            args, kwargs = _clean_send_args(args, kwargs)
            return await current_send(self, *args, **kwargs)

        response_send._sentrix_no_emoji_commands = True
        discord.InteractionResponse.send_message = response_send

    current_edit = discord.InteractionResponse.edit_message
    if not getattr(current_edit, "_sentrix_no_emoji_commands", False):
        async def response_edit(self, **kwargs):
            return await current_edit(self, **_clean_edit_kwargs(kwargs))

        response_edit._sentrix_no_emoji_commands = True
        discord.InteractionResponse.edit_message = response_edit

    current_modal = discord.InteractionResponse.send_modal
    if not getattr(current_modal, "_sentrix_no_emoji_commands", False):
        async def response_modal(self, modal):
            return await current_modal(self, clean_modal(modal))

        response_modal._sentrix_no_emoji_commands = True
        discord.InteractionResponse.send_modal = response_modal

    current_original = discord.Interaction.edit_original_response
    if not getattr(current_original, "_sentrix_no_emoji_commands", False):
        async def edit_original(self, **kwargs):
            return await current_original(self, **_clean_edit_kwargs(kwargs))

        edit_original._sentrix_no_emoji_commands = True
        discord.Interaction.edit_original_response = edit_original


def _patch_application_webhooks() -> None:
    """Nettoie les followups d'interactions sans toucher aux webhooks Discord classiques."""
    current = discord.Webhook.send
    if getattr(current, "_sentrix_no_emoji_commands", False):
        return

    async def webhook_send(self, *args, **kwargs):
        is_application = False
        try:
            is_application = self.type is discord.WebhookType.application
        except Exception:
            pass
        if is_application or _COMMAND_DEPTH.get() > 0:
            args, kwargs = _clean_send_args(args, kwargs)
        return await current(self, *args, **kwargs)

    webhook_send._sentrix_no_emoji_commands = True
    discord.Webhook.send = webhook_send


def install(bot: commands.Bot) -> None:
    """Installe le verrou visuel final et le réapplique aux nouvelles commandes chargées."""
    global _INSTALLED

    # Ce passage est volontairement répété après chaque extension : les futures commandes
    # chargées plus tard héritent ainsi de la même politique sans intervention manuelle.
    _clean_command_metadata(bot)

    if not _INSTALLED:
        _patch_command_scope()
        _patch_context_send()
        _patch_messageable_send()
        _patch_interactions()
        _patch_application_webhooks()
        _INSTALLED = True

    bot._sentrix_no_emoji_commands = True
    logger.info("Politique commandes sans emoji active : réponses, embeds et composants nettoyés globalement.")
