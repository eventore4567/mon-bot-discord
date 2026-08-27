"""Autorité runtime finale SentriX : aucune recharge sur les commandes normales.

Neutralise les mécanismes génériques discord.py qui ont historiquement bloqué SentriX :
- CooldownMapping global ;
- cooldown isolé par commande de #234 ;
- décorateurs commands.cooldown / dynamic_cooldown ;
- commands.max_concurrency ;
- app_commands.checks.cooldown / dynamic_cooldown pour les vraies commandes slash ;
- garde V41 personnalisé (anti-doublon, rate-limit slash, concurrence user/guild/heavy).

Les checks de permissions, rôles et sécurité restent intacts. Le garde V41 continue donc
à chaîner les checks existants et à refuser les appels provenant de bots, mais toutes ses
fonctions de throttling sont transformées en no-op par cette autorité finale.
"""
from __future__ import annotations

import logging
import types

from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.no-cooldown-final")
_MARKER = "_sentrix_no_cooldown_final_v2"


def _empty_buckets() -> commands.CooldownMapping:
    return commands.CooldownMapping(None, commands.BucketType.default)


def _strip_command(command: commands.Command) -> None:
    """Retire définitivement cooldown + max_concurrency d'une commande discord.py."""
    try:
        command._buckets = _empty_buckets()
    except Exception:
        logger.debug("Impossible de vider les buckets de %r", command, exc_info=True)
    try:
        command._max_concurrency = None
    except Exception:
        logger.debug("Impossible de vider la concurrence de %r", command, exc_info=True)

    for child in list(getattr(command, "commands", ()) or ()):
        _strip_command(child)


def _strip_all(bot: commands.Bot) -> None:
    for command in list(bot.commands):
        _strip_command(command)


def _is_app_cooldown_check(predicate) -> bool:
    """Reconnaît uniquement les predicates produits par app_commands.checks cooldown."""
    function = getattr(predicate, "__func__", predicate)
    module = str(getattr(function, "__module__", ""))
    qualname = str(getattr(function, "__qualname__", ""))
    return (
        module == "discord.app_commands.checks"
        and "_create_cooldown_decorator.<locals>.predicate" in qualname
    )


def _strip_app_command(command) -> int:
    removed = 0
    checks = getattr(command, "checks", None)
    if isinstance(checks, list):
        kept = [check for check in checks if not _is_app_cooldown_check(check)]
        removed += len(checks) - len(kept)
        if len(kept) != len(checks):
            command.checks[:] = kept
    for child in list(getattr(command, "commands", ()) or ()):
        removed += _strip_app_command(child)
    return removed


def _strip_all_app(bot: commands.Bot) -> int:
    removed = 0
    try:
        roots = list(bot.tree.get_commands())
    except Exception:
        roots = []
    for command in roots:
        removed += _strip_app_command(command)
    return removed


def _remove_sentrix_global_checks(bot: commands.Bot) -> int:
    """Retire les anciens checks globaux de cooldown s'ils sont présents."""
    removed = 0
    legacy = getattr(bot, "global_cooldown_check", None)
    isolated = getattr(bot, "_sentrix_isolated_global_cooldown_check", None)

    for check in list(getattr(bot, "_checks", ()) or ()):
        function = getattr(check, "__func__", check)
        module_name = str(getattr(function, "__module__", "")).casefold()
        function_name = str(getattr(function, "__name__", "")).casefold()
        is_known = (
            check == legacy
            or check == isolated
            or bool(getattr(check, "_sentrix_cooldown_isolated", False))
            or bool(getattr(function, "_sentrix_cooldown_isolated", False))
            or ("cooldown" in function_name and ("sentrix" in module_name or module_name == "main"))
        )
        if not is_known:
            continue
        try:
            bot.remove_check(check)
            removed += 1
        except (ValueError, TypeError):
            pass

    try:
        bot._cooldown_bucket = _empty_buckets()
    except Exception:
        pass
    state = getattr(bot, "cooldown_isolation_state", None)
    if isinstance(state, dict):
        state["mappings"] = {}
        state["installed"] = False
        state["disabled_by_no_cooldown_final"] = True
    return removed


def _disable_v41_throttling(bot: commands.Bot) -> dict:
    """Neutralise le vrai garde V41 sans contourner ses checks de sécurité.

    Les fonctions imbriquées ``prefix_guard`` et ``slash_guard`` résolvent ces helpers via
    les globals du module à chaque invocation. Les remplacer ici suffit donc à désactiver
    immédiatement les faux cooldowns, la fenêtre anti-doublon et toute concurrence V41,
    même si les gardes ont déjà été installés plus tôt pendant le bootstrap.
    """
    result = {
        "patched": False,
        "state_cleared": False,
        "error": None,
    }
    try:
        from . import command_hardening_v41 as v41

        def no_duplicate_retry(*_args, **_kwargs) -> float:
            return 0.0

        def no_slash_rate_retry(*_args, **_kwargs) -> float:
            return 0.0

        def no_acquire(*_args, **_kwargs):
            return None

        def no_release_prefix(*_args, **_kwargs) -> None:
            return None

        def no_release_slash(*_args, **_kwargs) -> None:
            return None

        v41._duplicate_retry = no_duplicate_retry
        v41._slash_rate_retry = no_slash_rate_retry
        v41._acquire = no_acquire
        v41.release_prefix = no_release_prefix
        v41.release_slash = no_release_slash

        state = getattr(bot, "_sentrix_command_hardening_state", None)
        if state is not None:
            for name in (
                "slash_buckets",
                "same_command_last",
                "active_user",
                "active_guild",
                "active_heavy_user",
                "active_heavy_guild",
                "prefix_tokens",
                "slash_tokens",
            ):
                value = getattr(state, name, None)
                clear = getattr(value, "clear", None)
                if callable(clear):
                    clear()
            result["state_cleared"] = True

        bot._sentrix_v41_throttling_disabled = True
        result["patched"] = True
    except Exception as exc:
        result["error"] = type(exc).__name__
        logger.exception("Impossible de neutraliser le throttling V41.")
    return result


def _patch_prepare_globally() -> None:
    """Dernier filet pour les commands.Command créées après le setup."""
    current = commands.Command.prepare
    if not getattr(current, _MARKER, False):
        async def prepare_without_limits(self: commands.Command, ctx: commands.Context):
            _strip_command(self)
            return await current(self, ctx)

        setattr(prepare_without_limits, _MARKER, True)
        prepare_without_limits._sentrix_original = current
        commands.Command.prepare = prepare_without_limits

    current_cooldowns = commands.Command._prepare_cooldowns
    if not getattr(current_cooldowns, _MARKER, False):
        def prepare_no_cooldowns(self: commands.Command, ctx: commands.Context) -> None:
            # Ne consomme aucun token et ne peut jamais lever CommandOnCooldown.
            return None

        setattr(prepare_no_cooldowns, _MARKER, True)
        prepare_no_cooldowns._sentrix_original = current_cooldowns
        commands.Command._prepare_cooldowns = prepare_no_cooldowns


def _patch_add_command(bot: commands.Bot) -> None:
    current = bot.add_command
    function = getattr(current, "__func__", current)
    if getattr(function, _MARKER, False):
        return

    def add_command_without_limits(_bot, command, /):
        _strip_command(command)
        result = current(command)
        _strip_command(command)
        return result

    setattr(add_command_without_limits, _MARKER, True)
    add_command_without_limits._sentrix_original = function
    bot.add_command = types.MethodType(add_command_without_limits, bot)


def _patch_app_checks_globally() -> None:
    """Retire le cooldown juste avant les checks slash, sans contourner les permissions."""
    for cls in (app_commands.Command, app_commands.ContextMenu):
        current = cls._check_can_run
        if getattr(current, _MARKER, False):
            continue

        async def check_without_cooldown(self, interaction, _current=current):
            _strip_app_command(self)
            return await _current(self, interaction)

        setattr(check_without_cooldown, _MARKER, True)
        check_without_cooldown._sentrix_original = current
        cls._check_can_run = check_without_cooldown


def install(bot: commands.Bot) -> None:
    """Désactive tous les cooldowns/concurrences des commandes + et /."""
    v41_state = _disable_v41_throttling(bot)
    removed_global = _remove_sentrix_global_checks(bot)
    _strip_all(bot)
    removed_app = _strip_all_app(bot)
    _patch_prepare_globally()
    _patch_add_command(bot)
    _patch_app_checks_globally()
    _strip_all(bot)
    removed_app += _strip_all_app(bot)

    bot.no_cooldown_final_state = {
        "installed": True,
        "removed_global_checks": removed_global,
        "removed_app_cooldown_checks": removed_app,
        "commands_checked": len(list(bot.walk_commands())),
        "v41_throttling_disabled": bool(v41_state.get("patched")),
        "v41_state_cleared": bool(v41_state.get("state_cleared")),
        "v41_error": v41_state.get("error"),
        "heavy_rate_limit": False,
    }
    setattr(bot, _MARKER, True)
    logger.warning(
        "SentriX zéro cooldown V2 actif : V41=%s, état V41 vidé=%s, %s check(s) globaux, %s check(s) slash retirés, %s commandes sans cooldown/max_concurrency.",
        bot.no_cooldown_final_state["v41_throttling_disabled"],
        bot.no_cooldown_final_state["v41_state_cleared"],
        removed_global,
        removed_app,
        bot.no_cooldown_final_state["commands_checked"],
    )


__all__ = [
    "install",
    "_strip_command",
    "_strip_all",
    "_strip_app_command",
    "_is_app_cooldown_check",
    "_disable_v41_throttling",
]
