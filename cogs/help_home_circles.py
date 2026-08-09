"""Rend uniquement l'accueil de +help sobre avec des puces noires."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import discord
from discord.ext import commands

from .antigif_runtime import install as install_antigif_runtime
from .command_clarity import install as install_command_clarity
from .help_category_rework import install as install_help_category_rework

logger = logging.getLogger("bot.help-home-circles")
_INSTALLED = False
_CIRCLE = "●"
_SECTION_NAMES = {"Essentiels", "Communauté", "Administration"}


def _remove_leading_symbol(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith(f"{_CIRCLE} "):
        text = text[len(_CIRCLE) + 1 :].lstrip()
    first, separator, rest = text.partition(" ")
    if separator and first and not any(character.isalnum() for character in first):
        return rest.strip()
    return text


def _circle_label(value: str) -> str:
    clean = _remove_leading_symbol(value)
    return f"{_CIRCLE} {clean}" if clean else _CIRCLE


def _circle_category_lines(value: str) -> str:
    lines: list[str] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        bold_index = line.find("**")
        if bold_index >= 0:
            line = line[bold_index:]
        else:
            line = _remove_leading_symbol(line)
        lines.append(_circle_label(line))
    return "\n".join(lines)


def _apply_circle_home(embed: discord.Embed) -> discord.Embed:
    if embed.title:
        embed.title = _remove_leading_symbol(str(embed.title))
    for index, field in enumerate(list(embed.fields)):
        clean_name = _remove_leading_symbol(str(field.name))
        new_value = str(field.value)
        if clean_name in _SECTION_NAMES:
            new_value = _circle_category_lines(new_value)
        embed.set_field_at(index, name=_circle_label(clean_name), value=new_value, inline=bool(field.inline))
    return embed


def _clean_home_components(view: discord.ui.View) -> None:
    for item in view.children:
        try:
            if isinstance(item, discord.ui.Select):
                item.placeholder = "Choisissez une catégorie..."
                for option in item.options:
                    option.label = _circle_label(option.label)[:100]
                    option.emoji = None
            elif isinstance(item, discord.ui.Button):
                if item.label:
                    item.label = _circle_label(item.label)[:80]
                item.emoji = None
        except Exception:
            logger.debug("Composant de l'accueil help non modifiable.", exc_info=True)


async def _configured_prefix(bot: commands.Bot, message: discord.Message) -> str:
    if message.guild is None:
        return "+"
    cached = getattr(bot, "prefix_cache", {}).get(message.guild.id)
    if cached:
        return str(cached)
    try:
        conf = await bot.db.get_guild_config(message.guild.id)
        prefix = conf["prefix"] if conf and conf["prefix"] else "+"
    except Exception:
        prefix = "+"
    return str(prefix)


def _install_plus_help_shortcut(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_plus_help_shortcut", False):
        return

    async def plus_help_listener(message: discord.Message):
        if message.author.bot:
            return
        if str(message.content or "").strip().casefold() != "+help":
            return
        if await _configured_prefix(bot, message) == "+":
            return

        help_command = bot.get_command("help")
        if help_command is None:
            return

        try:
            ctx = await bot.get_context(message)
            if ctx.command is not None:
                return
            ctx.command = help_command
            ctx.invoked_with = "help"
            ctx.prefix = "+"
            view = getattr(ctx, "view", None)
            if view is not None:
                view.index = len(view.buffer)
                view.previous = view.index
            await bot.invoke(ctx)
        except Exception:
            logger.exception("Le raccourci universel +help a échoué.")

    bot.add_listener(plus_help_listener, "on_message")
    bot._sentrix_plus_help_shortcut = True
    logger.info("Raccourci universel +help actif : aucun argument requis.")


def _patch_clean_help_callback_compat() -> None:
    """Corrige le bug où discord.py demandait `ctx` après +help."""
    try:
        from . import help_clean_style

        original = help_clean_style._clean_help_callback
        if getattr(original, "_sentrix_ctx_compat", False):
            return

        async def compatible_help_callback(cog_or_ctx, ctx: commands.Context | None = None, *, commande: str = None):
            # Selon l'ordre des patches, la commande peut être liée au Cog Utility ou
            # temporairement vue comme autonome. Les deux formes sont acceptées.
            if isinstance(cog_or_ctx, commands.Context) and ctx is None:
                real_ctx = cog_or_ctx
                utility_cog = real_ctx.bot.get_cog("Utility")
                if utility_cog is None:
                    utility_cog = SimpleNamespace(bot=real_ctx.bot)
                return await original(utility_cog, real_ctx, commande=commande)
            return await original(cog_or_ctx, ctx, commande=commande)

        compatible_help_callback._sentrix_ctx_compat = True
        help_clean_style._clean_help_callback = compatible_help_callback
        logger.info("Correctif +help installé : ctx n'est plus un argument utilisateur.")
    except Exception:
        logger.exception("Impossible d'installer le correctif callback +help.")


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    install_help_category_rework(bot)

    try:
        install_antigif_runtime(bot)
    except Exception:
        logger.exception("Impossible d'installer le runtime anti-GIF.")

    from . import help_complete, utility

    original_module_home = help_complete._home_embed

    def module_home_with_circles(*args, **kwargs):
        return _apply_circle_home(original_module_home(*args, **kwargs))

    help_complete._home_embed = module_home_with_circles

    original_utility_home = utility.build_help_home

    def utility_home_with_circles(*args, **kwargs):
        return _apply_circle_home(original_utility_home(*args, **kwargs))

    utility.build_help_home = utility_home_with_circles

    original_help_view_init = utility.HelpView.__init__

    def help_view_init(self, *args, **kwargs):
        original_help_view_init(self, *args, **kwargs)
        _clean_home_components(self)

    utility.HelpView.__init__ = help_view_init

    _install_plus_help_shortcut(bot)
    _patch_clean_help_callback_compat()
    install_command_clarity(bot)

    _INSTALLED = True
    logger.info("Accueil de +help simplifié : catégories canoniques, cercles noirs et aide claire actifs.")
