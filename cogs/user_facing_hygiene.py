"""Hygiène d'affichage globale des commandes SentriX.

Aucune logique métier et aucune nouvelle commande ici. Cette couche garantit que les
paramètres internes de discord.py (ctx/context/interaction/self/cog) ne sont jamais
présentés aux membres et répare la catégorie d'aide V2 ajoutée dynamiquement.
"""
from __future__ import annotations

import logging
import re

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


def sanitize_usage_text(value: str) -> str:
    """Retire les paramètres techniques d'une syntaxe destinée à un membre."""
    text = str(value or "")
    previous = None
    while previous != text:
        previous = text
        text = _INTERNAL_TOKEN_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _sanitize_registered_commands(bot: commands.Bot) -> None:
    """Nettoie la source même des signatures Discord.py.

    Certaines anciennes couches runtime ont pu conserver ``ctx`` dans ``command.params``
    ou dans ``command.usage``. Dans discord.py ces deux valeurs alimentent ensuite
    ``command.signature`` : masquer seulement le texte de +help ne suffit donc pas.
    On retire ici uniquement les paramètres techniques qui ne sont jamais saisis par un
    utilisateur. Les vrais arguments (montant, membre, raison...) restent inchangés.
    """
    cleaned = 0
    for command in bot.walk_commands():
        params = getattr(command, "params", None)
        if params is not None and hasattr(params, "items"):
            filtered = [(name, value) for name, value in params.items() if not _is_internal(name)]
            if len(filtered) != len(params):
                try:
                    command.params = type(params)(filtered)
                except Exception:
                    command.params = dict(filtered)
                cleaned += 1

        usage = getattr(command, "usage", None)
        if usage:
            safe_usage = sanitize_usage_text(str(usage))
            if safe_usage != str(usage):
                command.usage = safe_usage
                cleaned += 1

    if cleaned:
        logger.warning("%s signature(s) de commande nettoyée(s) : paramètres internes retirés.", cleaned)


def visible_usage(command: commands.Command, prefix: str = "+") -> str:
    """Construit une syntaxe utilisateur sans aucun paramètre interne discord.py."""
    parts = [f"{prefix}{command.qualified_name}"]
    for name, parameter in getattr(command, "clean_params", {}).items():
        if _is_internal(name):
            continue
        display = str(name).replace("_", " ")
        parts.append(f"<{display}>" if getattr(parameter, "required", False) else f"[{display}]")
    return " ".join(parts)


def _repair_help_categories() -> None:
    """Synchronise CATEGORIES et CATEGORY_BY_KEY, notamment après l'ajout dynamique de V2."""
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
        language_runtime.CATEGORY_I18N.setdefault(
            "v2", ("SentriX V2", "SentriX V2")
        )
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
    """Nettoie les anciennes couches qui pourraient encore réinjecter <ctx>/[ctx]."""
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


def _patch_raw_technical_errors() -> None:
    """Les traces Python restent dans les logs, jamais dans Discord, même pour le créateur."""
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


def apply(bot: commands.Bot) -> None:
    _sanitize_registered_commands(bot)
    _repair_help_categories()
    _patch_main_usage()
    _patch_help_renderers()
    _patch_raw_technical_errors()
    bot._sentrix_user_facing_hygiene = True


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_user_facing_hygiene_listener", False):
        apply(bot)
        return

    apply(bot)

    async def reapply_on_ready():
        # Les finaliseurs et SentriX V2 peuvent être chargés après Stats. on_ready est la
        # dernière barrière : on resynchronise alors les signatures et renderers finaux.
        apply(bot)

    bot.add_listener(reapply_on_ready, "on_ready")
    bot._sentrix_user_facing_hygiene_listener = True
    logger.info("Hygiène utilisateur active : ctx supprimé des signatures, erreurs techniques privées, aide V2 sécurisée.")
