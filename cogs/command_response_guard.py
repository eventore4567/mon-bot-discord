"""Observabilité non intrusive des commandes SentriX.

Ce module ne patch plus aucun transport Discord et n'envoie aucune erreur. Le transport
canonique marque lui-même les réponses ; ici on conserve seulement les suggestions sûres
et les mesures de durée.
"""
from __future__ import annotations

import difflib
import logging
import sys
import time

import discord
from discord.ext import commands

logger = logging.getLogger("bot.command-observability")
_INSTALLED = False
_SLOW_COMMAND_SECONDS = 2.0
_SLASH_STARTS: dict[int, float] = {}


def _runtime_main():
    return sys.modules.get("main") or sys.modules.get("__main__")


def _command_policy_name(command: commands.Command) -> str:
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or getattr(command, "name", "") or "").casefold()


def _can_suggest_command(ctx: commands.Context, command: commands.Command) -> bool:
    if getattr(command, "hidden", False) or not getattr(command, "enabled", True):
        return False
    main = _runtime_main()
    if main is None:
        return _command_policy_name(command) == "help"
    name = _command_policy_name(command)
    public = set(getattr(main, "PUBLIC_COMMANDS", set()) or set())
    owner_only = set(getattr(main, "OWNER_ONLY_COMMANDS", set()) or set())
    permission_commands = dict(getattr(main, "DISCORD_PERMISSION_COMMANDS", {}) or {})
    categories = dict(getattr(main, "CATEGORY_COMMANDS", {}) or {})
    if name in owner_only:
        return False
    if name in public or name == "help":
        return True
    author = getattr(ctx, "author", None)
    perms = getattr(author, "guild_permissions", None)
    is_admin = bool(perms and (getattr(perms, "administrator", False) or getattr(perms, "manage_guild", False)))
    required = permission_commands.get(name)
    if required:
        return bool(perms and (is_admin or getattr(perms, required, False)))
    for names in categories.values():
        if name in set(names or ()):
            return is_admin
    return is_admin


def _command_suggestions(bot: commands.Bot, ctx: commands.Context, typed: str) -> list[str]:
    typed = (typed or "").casefold().strip()
    if not typed:
        return []
    lookup: dict[str, str] = {}
    for command in bot.walk_commands():
        if not _can_suggest_command(ctx, command):
            continue
        canonical = str(command.qualified_name).strip()
        if not canonical:
            continue
        lookup[canonical.casefold()] = canonical
        parent = getattr(command, "parent", None)
        parent_name = str(getattr(parent, "qualified_name", "") or "").strip()
        for alias in getattr(command, "aliases", ()):
            alias_name = str(alias).strip()
            if alias_name:
                lookup[(f"{parent_name} {alias_name}".strip()).casefold()] = canonical
    matches = difflib.get_close_matches(typed, list(lookup), n=8, cutoff=0.52)
    result: list[str] = []
    for match in matches:
        canonical = lookup[match]
        if canonical not in result:
            result.append(canonical)
        if len(result) >= 3:
            break
    return result


def _typed_command_path(bot: commands.Bot, ctx: commands.Context) -> str:
    invoked = str(getattr(ctx, "invoked_with", "") or "").strip()
    content = str(getattr(getattr(ctx, "message", None), "content", "") or "")
    prefix = str(getattr(ctx, "clean_prefix", None) or "+")
    if content.startswith(prefix):
        content = content[len(prefix):].strip()
    parts = content.split()
    if not parts:
        return invoked
    root = bot.get_command(parts[0])
    if not isinstance(root, commands.Group):
        return parts[0]
    depth = 1
    for child in root.walk_commands():
        depth = max(depth, len(str(child.qualified_name).split()))
    return " ".join(parts[:depth])


def _record_slash_start(interaction: discord.Interaction) -> None:
    _SLASH_STARTS[int(interaction.id)] = time.perf_counter()
    if len(_SLASH_STARTS) > 5000:
        now = time.perf_counter()
        for key, stamp in list(_SLASH_STARTS.items()):
            if now - stamp > 300.0:
                _SLASH_STARTS.pop(key, None)


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    async def mark_prefix_start(ctx: commands.Context) -> None:
        ctx._sentrix_command_started_at = time.perf_counter()

    async def mark_slash_start(interaction: discord.Interaction) -> None:
        if interaction.type is discord.InteractionType.application_command:
            _record_slash_start(interaction)

    def log_prefix(ctx: commands.Context, failed: bool) -> None:
        started = getattr(ctx, "_sentrix_command_started_at", None)
        if started is None:
            return
        elapsed = max(0.0, time.perf_counter() - started)
        if elapsed >= _SLOW_COMMAND_SECONDS:
            logger.warning(
                "Commande lente : +%s %.2fs user=%s guild=%s état=%s",
                getattr(getattr(ctx, "command", None), "qualified_name", "inconnue"),
                elapsed,
                getattr(getattr(ctx, "author", None), "id", None),
                getattr(getattr(ctx, "guild", None), "id", None),
                "erreur" if failed else "succès",
            )

    async def observe_prefix_error(ctx: commands.Context, error: commands.CommandError) -> None:
        del error
        log_prefix(ctx, True)

    async def observe_prefix_completion(ctx: commands.Context) -> None:
        log_prefix(ctx, False)

    async def observe_slash_completion(interaction: discord.Interaction, command) -> None:
        started = _SLASH_STARTS.pop(int(interaction.id), None)
        if started is None:
            return
        elapsed = max(0.0, time.perf_counter() - started)
        if elapsed >= _SLOW_COMMAND_SECONDS:
            logger.warning(
                "Commande lente : /%s %.2fs user=%s guild=%s",
                getattr(command, "qualified_name", getattr(command, "name", "inconnue")),
                elapsed,
                getattr(interaction.user, "id", None),
                interaction.guild_id,
            )

    bot.add_listener(mark_prefix_start, "on_command")
    bot.add_listener(mark_slash_start, "on_interaction")
    bot.add_listener(observe_prefix_error, "on_command_error")
    bot.add_listener(observe_prefix_completion, "on_command_completion")
    bot.add_listener(observe_slash_completion, "on_app_command_completion")
    _INSTALLED = True
    logger.info("Observabilité commandes active sans wrapper de transport.")


__all__ = ["install", "_can_suggest_command", "_command_suggestions", "_typed_command_path"]
