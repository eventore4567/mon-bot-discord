"""Registre slash canonique de SentriX.

Le garde est installé au niveau ``CommandTree`` dès l'import du package ``cogs``. Il est
donc actif AVANT que la première extension ajoute ses commandes, contrairement à l'ancien
runtime qui arrivait après le chargement et laissait Discord.py lever CommandLimitReached.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.slash-registry")
GLOBAL_CHAT_INPUT_BUDGET = 100
_ORIGINAL_ADD = app_commands.CommandTree.add_command


def _preferred_names() -> set[str]:
    from .command_catalog_cleanup import NORMAL_DIRECT_COMMANDS
    return {("nick" if name == "nickname" else name) for name in NORMAL_DIRECT_COMMANDS}


def _excluded_names() -> set[str]:
    from .command_catalog_cleanup import ADMIN_DIRECT_COMMANDS, MERGED_COMMANDS
    return set(ADMIN_DIRECT_COMMANDS) | set(MERGED_COMMANDS)


def _global_roots(tree) -> list:
    try:
        return list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    except Exception:
        return [item for item in tree.get_commands(guild=None) if isinstance(item, (app_commands.Command, app_commands.Group))]


def _remove_root(tree, name: str) -> None:
    try:
        tree.remove_command(name, type=discord.AppCommandType.chat_input)
    except TypeError:
        tree.remove_command(name)


def _record_skip(tree, name: str) -> None:
    skipped = getattr(tree, "_sentrix_skipped_global_slash", None)
    if not isinstance(skipped, list):
        skipped = []
        tree._sentrix_skipped_global_slash = skipped
    if name not in skipped:
        skipped.append(name)


def install_class_guard() -> None:
    current = app_commands.CommandTree.add_command
    if getattr(current, "_sentrix_canonical_budget_guard", False):
        return
    base = _ORIGINAL_ADD

    def guarded_add(self, command, *, guild=None, guilds=None, override: bool = False):
        kwargs = {"override": override}
        if guild is not None:
            kwargs["guild"] = guild
        if guilds is not None:
            kwargs["guilds"] = guilds
        if guild is not None or guilds is not None:
            return base(self, command, **kwargs)

        if isinstance(command, (app_commands.Command, app_commands.Group)):
            name = str(getattr(command, "name", "") or "").casefold()
            if name in _excluded_names():
                _record_skip(self, name)
                return None

            roots = _global_roots(self)
            existing = next((item for item in roots if str(getattr(item, "name", "")).casefold() == name), None)
            if existing is None and len(roots) >= GLOBAL_CHAT_INPUT_BUDGET:
                preferred = _preferred_names()
                if name in preferred:
                    victim = next(
                        (item for item in roots if str(getattr(item, "name", "")).casefold() not in preferred),
                        None,
                    )
                    if victim is None:
                        _record_skip(self, name)
                        return None
                    _remove_root(self, str(getattr(victim, "name", "") or "").casefold())
                else:
                    _record_skip(self, name)
                    return None
        return base(self, command, **kwargs)

    guarded_add._sentrix_canonical_budget_guard = True
    guarded_add._sentrix_original = base
    app_commands.CommandTree.add_command = guarded_add
    logger.info("Garde du registre slash installé avant chargement : plafond=%s.", GLOBAL_CHAT_INPUT_BUDGET)


def finalize(bot: commands.Bot) -> None:
    tree = bot.tree
    excluded = _excluded_names()
    preferred = _preferred_names()
    for item in list(_global_roots(tree)):
        name = str(getattr(item, "name", "") or "").casefold()
        if name in excluded:
            _remove_root(tree, name)

    roots = _global_roots(tree)
    if len(roots) > GLOBAL_CHAT_INPUT_BUDGET:
        keep: set[str] = set()
        for item in roots:
            name = str(getattr(item, "name", "") or "").casefold()
            if name in preferred and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
                keep.add(name)
        for item in roots:
            name = str(getattr(item, "name", "") or "").casefold()
            if name not in keep and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
                keep.add(name)
        for item in roots:
            name = str(getattr(item, "name", "") or "").casefold()
            if name not in keep:
                _remove_root(tree, name)

    bot._sentrix_slash_registry_count = len(_global_roots(tree))
    bot._sentrix_slash_budget_installed = True


def install(bot: commands.Bot) -> None:
    install_class_guard()
    finalize(bot)


# cogs.__init__ importe final_runtime_polish pendant l'import du package, avant que le
# premier Cog n'enregistre ses commandes. Le garde doit donc être actif dès cet import.
install_class_guard()


__all__ = ["GLOBAL_CHAT_INPUT_BUDGET", "install_class_guard", "install", "finalize"]
