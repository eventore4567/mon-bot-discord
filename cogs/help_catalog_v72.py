"""Catalogue complet pour l'aide V70.

Ce module ne dessine rien. Il fournit uniquement à V70 la liste complète des commandes
réellement enregistrées, y compris les sous-commandes de groupes + et /, afin que
« simplifier le design » ne masque pas des commandes utiles.
"""
from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands


def _slash_commands(bot: commands.Bot) -> dict[str, Any]:
    try:
        roots = bot.tree.get_commands(guild=None, type=discord.AppCommandType.chat_input)
    except Exception:
        roots = bot.tree.get_commands(guild=None)

    result: dict[str, Any] = {}

    def visit(item, parent: str = "") -> None:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            return
        qualified = f"{parent} {name}".strip().casefold()
        result[qualified] = item
        for child in getattr(item, "commands", ()) or ():
            visit(child, qualified)

    for root in roots:
        visit(root)
    return result


def complete_help_entries(bot: commands.Bot, prefix: str, is_staff: bool):
    from . import sentrix_visual_refactor_v70 as v70

    slash = _slash_commands(bot)
    rows: list[tuple[str, str, str, str]] = []
    seen_prefix: set[str] = set()
    matched_slash: set[str] = set()

    for command in bot.walk_commands():
        qualified = str(getattr(command, "qualified_name", "") or "").strip()
        if not qualified or qualified.casefold() in seen_prefix or getattr(command, "hidden", False):
            continue
        if not is_staff and v70._is_staff_command(command):
            continue
        seen_prefix.add(qualified.casefold())

        slash_key = qualified.casefold()
        if slash_key == "nickname" and "nick" in slash:
            slash_key = "nick"
        slash_item = slash.get(slash_key)
        if slash_item is not None:
            matched_slash.add(slash_key)
            slash_display = str(getattr(slash_item, "qualified_name", "") or slash_key)
            access = f"`/{slash_display}`  `{prefix}{qualified}`"
            app_description = str(getattr(slash_item, "description", "") or "")
        else:
            access = f"`{prefix}{qualified}`"
            app_description = ""

        rows.append((
            v70._category_key(command),
            v70._command_category(command),
            access,
            v70._short_description(command, app_description),
        ))

    # Les commandes réellement slash-only doivent aussi être trouvables.
    for qualified, item in slash.items():
        if qualified in matched_slash:
            continue
        root_name = qualified.split(" ", 1)[0]
        command = bot.get_command(qualified) or bot.get_command(root_name)
        if command is not None and not is_staff and v70._is_staff_command(command):
            continue
        rows.append((
            v70._category_key(command),
            v70._command_category(command),
            f"`/{qualified}`",
            v70._short_description(command, str(getattr(item, "description", "") or "")),
        ))

    # Déduplication visuelle sans supprimer une commande du registre.
    unique: list[tuple[str, str, str, str]] = []
    seen_rows: set[tuple[str, str]] = set()
    for row in rows:
        key = (row[0], row[2].casefold())
        if key in seen_rows:
            continue
        seen_rows.add(key)
        unique.append(row)

    unique.sort(key=lambda row: (row[1].casefold(), row[2].casefold()))
    return unique


def install(bot: commands.Bot) -> None:
    del bot
    from . import sentrix_visual_refactor_v70 as v70
    v70._help_entries = complete_help_entries


__all__ = ["install", "complete_help_entries"]
