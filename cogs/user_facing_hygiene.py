"""Hygiène d'affichage globale des commandes SentriX.

Cette couche ne modifie jamais les signatures internes utilisées par discord.py.
Elle agit uniquement sur les textes visibles : aide, syntaxes, erreurs techniques et
cooldowns. Cela évite qu'un correctif d'affichage casse les commandes slash/hybrides.
"""
from __future__ import annotations

import logging
import math
import re

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.user-facing-hygiene")

_INTERNAL_PARAMS = {"ctx", "context", "interaction", "self", "cog", "_ctx"}
_INTERNAL_TOKEN_RE = re.compile(
    r"(?:\s+)(?:<|\[|\()(?:ctx|context|interaction|self|cog|_ctx)(?:>|\]|\))",
    re.IGNORECASE,
)
_RAW_TECHNICAL_ERROR_RE = re.compile(
    r"^\s*Erreur technique\s*:\s*[A-Za-z_][A-Za-z0-9_]*(?:\s*\n.*)?$",
    re.IGNORECASE | re.DOTALL,
)


def _is_internal(name: str) -> bool:
    return str(name or "").casefold().strip() in _INTERNAL_PARAMS


def sanitize_usage_text(value: str | None) -> str:
    """Retire uniquement les paramètres techniques d'un texte destiné au membre."""
    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = _INTERNAL_TOKEN_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def visible_usage(command: commands.Command, prefix: str = "+") -> str:
    """Construit une syntaxe utilisateur sans toucher à ``command.params``."""
    parts = [f"{prefix}{command.qualified_name}"]
    for name, parameter in getattr(command, "clean_params", {}).items():
        if _is_internal(name):
            continue
        display = str(name).replace("_", " ")
        parts.append(f"<{display}>" if getattr(parameter, "required", False) else f"[{display}]")
    return " ".join(parts)


def _repair_help_categories() -> None:
    """Synchronise CATEGORIES et CATEGORY_BY_KEY, notamment pour SentriX V2."""
    try:
        from . import help_complete
    except Exception:
        return

    help_complete.CATEGORY_BY_KEY = {
        category.key: category for category in help_complete.CATEGORIES
    }

    current = help_complete._category_for
    if not getattr(current, "_sentrix_category_map_safe", False):
        def safe_category_for(command):
            try:
                return current(command)
            except KeyError:
                help_complete.CATEGORY_BY_KEY = {
                    category.key: category for category in help_complete.CATEGORIES
                }
                try:
                    return current(command)
                except KeyError:
                    return help_complete.CATEGORY_BY_KEY.get(
                        "other", next(iter(help_complete.CATEGORIES))
                    )

        safe_category_for._sentrix_category_map_safe = True
        safe_category_for._sentrix_original = current
        help_complete._category_for = safe_category_for

    try:
        from . import language_runtime
        language_runtime.CATEGORY_I18N.setdefault("v2", ("SentriX V2", "SentriX V2"))
    except Exception:
        pass

    try:
        from . import help_category_rework
        help_category_rework.COG_DEFAULT_CATEGORY.setdefault("SentriXV2", "v2")
    except Exception:
        pass


def _patch_main_usage() -> None:
    try:
        import main
    except Exception:
        return

    def command_usage(ctx: commands.Context) -> str | None:
        command = getattr(ctx, "command", None)
        if command is None:
            return None
        prefix = getattr(ctx, "clean_prefix", None) or "+"
        return visible_usage(command, str(prefix))

    command_usage._sentrix_no_internal_params = True
    main.command_usage = command_usage


def _patch_help_renderers() -> None:
    """Nettoie les anciennes couches qui pourraient encore afficher <ctx>/[ctx]."""
    try:
        from . import utility
    except Exception:
        utility = None

    if utility is not None:
        current = utility.format_command_line
        if not getattr(current, "_sentrix_no_internal_params", False):
            def format_command_line(command, prefix: str, slash_names: set):
                return sanitize_usage_text(current(command, prefix, slash_names))

            format_command_line._sentrix_no_internal_params = True
            format_command_line._sentrix_original = current
            utility.format_command_line = format_command_line

    try:
        from . import language_runtime
        current_usage = language_runtime._command_usage
        if not getattr(current_usage, "_sentrix_no_internal_params", False):
            def language_usage(command, prefix: str, language: str):
                return sanitize_usage_text(current_usage(command, prefix, language))

            language_usage._sentrix_no_internal_params = True
            language_usage._sentrix_original = current_usage
            language_runtime._command_usage = language_usage
    except Exception:
        pass

    try:
        from . import help_complete
        current_compact = help_complete._compact_command_line
        if not getattr(current_compact, "_sentrix_no_internal_params", False):
            def compact_line(*args, **kwargs):
                return sanitize_usage_text(current_compact(*args, **kwargs))

            compact_line._sentrix_no_internal_params = True
            compact_line._sentrix_original = current_compact
            help_complete._compact_command_line = compact_line
    except Exception:
        pass

    # La V2.3 avait importé usage_line directement. On nettoie donc son global local
    # plutôt que de modifier les paramètres réels de la commande.
    try:
        from . import sentrix_accessibility
        current_usage_line = sentrix_accessibility.usage_line
        if not getattr(current_usage_line, "_sentrix_no_internal_params", False):
            def accessibility_usage_line(prefix: str, command_name: str, signature=None):
                return current_usage_line(prefix, command_name, sanitize_usage_text(signature))

            accessibility_usage_line._sentrix_no_internal_params = True
            accessibility_usage_line._sentrix_original = current_usage_line
            sentrix_accessibility.usage_line = accessibility_usage_line
    except Exception:
        pass


def _patch_raw_technical_errors() -> None:
    """Les traces Python restent dans les logs, jamais dans Discord."""
    current = embeds.error
    if getattr(current, "_sentrix_hide_raw_technical_error", False):
        return

    def safe_error(description: str, title: str = "Action impossible"):
        text = str(description or "")
        if _RAW_TECHNICAL_ERROR_RE.match(text):
            description = (
                "Cette commande a rencontré un problème technique. "
                "Réessaie dans un instant. Si le problème continue, consulte les logs du bot."
            )
        return current(description, title=title)

    safe_error._sentrix_hide_raw_technical_error = True
    safe_error._sentrix_original = current
    embeds.error = safe_error


def _cooldown_text(seconds: float) -> str:
    total = max(1, int(math.ceil(float(seconds))))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} j")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} s")
    return " ".join(parts[:3])


def _cooldown_retry_after(error) -> float | None:
    candidates = [error, getattr(error, "original", None)]
    for candidate in candidates:
        if isinstance(candidate, (commands.CommandOnCooldown, discord.app_commands.CommandOnCooldown)):
            try:
                return float(candidate.retry_after)
            except (TypeError, ValueError):
                return 1.0
    return None


async def _send_slash_cooldown(interaction: discord.Interaction, retry_after: float) -> None:
    embed = embeds.warning(
        f"Cette commande est en cooldown. Réessaie dans **{_cooldown_text(retry_after)}**.",
        title="Cooldown actif",
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except (discord.HTTPException, discord.InteractionResponded):
        logger.debug("Impossible d'envoyer le cooldown slash.", exc_info=True)


def _patch_slash_cooldown_errors(bot: commands.Bot) -> None:
    """Couvre les cooldowns app_commands ET ceux des commandes hybrides.

    Une commande hybride exécutée avec / peut remonter ``commands.CommandOnCooldown``
    dans ``error.original``. Le handler historique ne vérifiait que la variante
    ``app_commands.CommandOnCooldown`` et pouvait donc afficher une erreur technique.
    """
    current = bot.tree.on_error
    if getattr(current, "_sentrix_cooldown_ux", False):
        return

    async def slash_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        retry_after = _cooldown_retry_after(error)
        if retry_after is not None:
            return await _send_slash_cooldown(interaction, retry_after)
        return await current(interaction, error)

    slash_error._sentrix_cooldown_ux = True
    slash_error._sentrix_original = current
    bot.tree.on_error = slash_error


def apply(bot: commands.Bot) -> None:
    # Important : ne jamais modifier command.params / command.callback ici.
    _repair_help_categories()
    _patch_main_usage()
    _patch_help_renderers()
    _patch_raw_technical_errors()
    _patch_slash_cooldown_errors(bot)
    bot._sentrix_user_facing_hygiene = True


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_user_facing_hygiene_listener", False):
        apply(bot)
        return

    apply(bot)

    async def reapply_on_ready():
        # Les dernières couches runtime peuvent être installées après Stats.
        apply(bot)

    bot.add_listener(reapply_on_ready, "on_ready")
    bot._sentrix_user_facing_hygiene_listener = True
    logger.info(
        "Hygiène utilisateur active : signatures intactes, ctx masqué à l'affichage, cooldowns slash explicites."
    )
