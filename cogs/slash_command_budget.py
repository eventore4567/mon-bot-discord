"""Budget et sélection canonique des commandes slash SentriX."""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.slash-budget")
GLOBAL_CHAT_INPUT_BUDGET = 100


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
        return [
            item for item in tree.get_commands(guild=None)
            if isinstance(item, (app_commands.Command, app_commands.Group))
        ]


def finalize(bot: commands.Bot) -> None:
    """Écarte les racines fusionnées/admin et garantit au maximum 100 racines /."""
    tree = bot.tree
    preferred = _preferred_names()
    excluded = _excluded_names()

    for item in list(_global_roots(tree)):
        name = str(getattr(item, "name", "") or "").casefold()
        if name in excluded:
            try:
                tree.remove_command(name, type=discord.AppCommandType.chat_input)
            except TypeError:
                tree.remove_command(name)

    roots = _global_roots(tree)
    if len(roots) <= GLOBAL_CHAT_INPUT_BUDGET:
        return

    keep: set[str] = set()
    for item in roots:
        name = str(getattr(item, "name", "") or "").casefold()
        if name in preferred and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
            keep.add(name)
    for item in roots:
        name = str(getattr(item, "name", "") or "").casefold()
        if name not in keep and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
            keep.add(name)

    for item in list(roots):
        name = str(getattr(item, "name", "") or "").casefold()
        if name not in keep:
            try:
                tree.remove_command(name, type=discord.AppCommandType.chat_input)
            except TypeError:
                tree.remove_command(name)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_slash_budget_installed", False):
        finalize(bot)
        return
    bot._sentrix_slash_budget_installed = True

    tree = bot.tree
    original_add = tree.add_command
    skipped: list[str] = []
    bot._sentrix_skipped_global_slash = skipped

    def _call_original(command, *, guild=None, guilds=None, override: bool = False):
        kwargs = {"override": override}
        if guild is not None:
            kwargs["guild"] = guild
        if guilds is not None:
            kwargs["guilds"] = guilds
        return original_add(command, **kwargs)

    def budgeted_add(
        _tree,
        command,
        *,
        guild=None,
        guilds=None,
        override: bool = False,
    ):
        if guild is not None or guilds is not None:
            return _call_original(command, guild=guild, guilds=guilds, override=override)

        if isinstance(command, (app_commands.Command, app_commands.Group)):
            name = str(getattr(command, "name", "") or "").casefold()
            if name in _excluded_names():
                skipped.append(name)
                return None

            roots = _global_roots(tree)
            existing = next(
                (item for item in roots if str(getattr(item, "name", "")).casefold() == name),
                None,
            )
            if existing is None and len(roots) >= GLOBAL_CHAT_INPUT_BUDGET:
                preferred = _preferred_names()
                if name in preferred:
                    victim = next(
                        (
                            item for item in roots
                            if str(getattr(item, "name", "")).casefold() not in preferred
                        ),
                        None,
                    )
                    if victim is not None:
                        victim_name = str(getattr(victim, "name", "")).casefold()
                        try:
                            tree.remove_command(victim_name, type=discord.AppCommandType.chat_input)
                        except TypeError:
                            tree.remove_command(victim_name)
                    else:
                        skipped.append(name)
                        return None
                else:
                    skipped.append(name)
                    return None

        return _call_original(command, override=override)

    tree.add_command = MethodType(budgeted_add, tree)
    finalize(bot)
    logger.info("Budget slash SentriX actif : maximum %s racines.", GLOBAL_CHAT_INPUT_BUDGET)
