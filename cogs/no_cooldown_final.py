"""Autorité runtime finale SentriX : aucune recharge sur les commandes normales.

Le bot a historiquement empilé plusieurs systèmes : CooldownMapping global, cooldown
isolé par commande, décorateurs commands.cooldown et max_concurrency. Pour l'UX finale,
les commandes utilisateur ne doivent plus être bloquées par ces mécanismes génériques.

Les verrous métier explicites à l'intérieur d'une commande destructive (par exemple une
reconstruction globale) ne sont pas touchés : seuls les mécanismes discord.py attachés
aux Command sont neutralisés.
"""
from __future__ import annotations

import logging
import types

from discord.ext import commands

logger = logging.getLogger("bot.no-cooldown-final")
_MARKER = "_sentrix_no_cooldown_final_v1"


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


def _remove_sentrix_global_checks(bot: commands.Bot) -> int:
    """Retire le vieux check global et le check isolé de #234 s'ils sont présents."""
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

    # Jette aussi tout état de l'ancien compteur partagé/isolé.
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


def _patch_prepare_globally() -> None:
    """Garantit aussi zéro limite pour les Command créées après le setup.

    Command.prepare est le dernier endroit commun aux commandes préfixées et au côté
    commands.Command des HybridCommand. Les permissions et checks métier restent intacts.
    """
    current = commands.Command.prepare
    if getattr(current, _MARKER, False):
        return

    async def prepare_without_limits(self: commands.Command, ctx: commands.Context):
        _strip_command(self)
        return await current(self, ctx)

    setattr(prepare_without_limits, _MARKER, True)
    prepare_without_limits._sentrix_original = current
    commands.Command.prepare = prepare_without_limits


def _patch_add_command(bot: commands.Bot) -> None:
    """Nettoie immédiatement toute commande ajoutée dynamiquement après le démarrage."""
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


def install(bot: commands.Bot) -> None:
    """Désactive les cooldowns/concurrences génériques de toutes les commandes normales."""
    removed = _remove_sentrix_global_checks(bot)
    _strip_all(bot)
    _patch_prepare_globally()
    _patch_add_command(bot)
    _strip_all(bot)

    bot.no_cooldown_final_state = {
        "installed": True,
        "removed_global_checks": removed,
        "commands_checked": len(list(bot.walk_commands())),
    }
    setattr(bot, _MARKER, True)
    logger.warning(
        "SentriX zéro cooldown actif : %s check(s) globaux retirés, %s commandes sans cooldown/max_concurrency.",
        removed,
        bot.no_cooldown_final_state["commands_checked"],
    )


__all__ = ["install", "_strip_command", "_strip_all"]
