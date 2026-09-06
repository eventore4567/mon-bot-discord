"""Bootstrap correctif V95.

Séparé du module métier afin de garder le branchement Python minuscule dans sitecustomize.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands

import sentrix_v95_runtime as v95

logger = logging.getLogger("bot.v95-bootstrap")


def _add_grouped_surface_fixed(bot):
    tree = bot.tree
    targets = v95._build_targets(bot)
    v95._remove_old_roots(tree)
    report: dict[str, dict] = {}

    by_root: dict[str, list[v95.SlashTarget]] = {}
    for target in targets:
        by_root.setdefault(target.root_name, []).append(target)

    for root_name, members in sorted(by_root.items()):
        root = app_commands.Group(
            name=v95._safe_name(root_name),
            description=v95.GROUP_DESCRIPTIONS.get(
                root_name, f"Commandes {root_name} de SentriX."
            )[:100],
        )
        chunks = [members[i:i + v95.MAX_CHILDREN] for i in range(0, len(members), v95.MAX_CHILDREN)]
        paged = len(chunks) > 1
        if len(chunks) > v95.MAX_CHILDREN:
            raise RuntimeError(
                f"V95 group too large: {root_name} requires {len(chunks)} subgroups"
            )

        for page_index, page_members in enumerate(chunks, start=1):
            if paged:
                # Le constructeur avec parent=root ajoute déjà le sous-groupe à root.
                parent = app_commands.Group(
                    name=f"page-{page_index}",
                    description=f"Page {page_index} des commandes {root_name}."[:100],
                    parent=root,
                )
                page_name = parent.name
            else:
                parent = root
                page_name = None

            for target in page_members:
                callback, native = v95._make_callback(bot, target.command)
                slash = app_commands.Command(
                    name=target.leaf_name,
                    description=v95._description(target.command),
                    callback=callback,
                )
                parent.add_command(slash)
                path = f"/{root.name}"
                if page_name:
                    path += f" {page_name}"
                path += f" {slash.name}"
                report[path] = {
                    "original": target.original_name,
                    "category": root.name,
                    "native_options": bool(native),
                }

        tree.add_command(root, override=True)

    roots = list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    if len(roots) > v95.MAX_ROOT_COMMANDS:
        raise RuntimeError(
            f"V95 slash root budget exceeded: {len(roots)}/{v95.MAX_ROOT_COMMANDS}"
        )
    bot._sentrix_v95_slash_mapping = report
    bot._sentrix_v95_slash_root_count = len(roots)
    return report


def install() -> None:
    v95._add_grouped_surface = _add_grouped_surface_fixed
    v95.install_global()
    logger.info("V95 bootstrap actif.")


__all__ = ["install"]
