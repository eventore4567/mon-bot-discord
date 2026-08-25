"""Registre slash canonique et volontairement court de SentriX.

Le garde est installé sur ``CommandTree`` dès l'import du package ``cogs``. Il agit donc
AVANT le premier Cog : les anciennes commandes continuent d'exister en `+`, mais seules
les racines de la surface facile sont autorisées dans Discord `/`. Cela évite à la fois la
limite des 100 commandes et le catalogue intimidant pour les membres.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.slash-registry")
GLOBAL_CHAT_INPUT_BUDGET = 100  # garde technique Discord ; la surface produit est bien plus petite.
_ORIGINAL_ADD = app_commands.CommandTree.add_command


def _preferred_names() -> set[str]:
    from .command_catalog_cleanup import slash_surface_names
    return set(slash_surface_names())


def _global_roots(tree) -> list:
    try:
        return list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    except Exception:
        return [
            item for item in tree.get_commands(guild=None)
            if isinstance(item, (app_commands.Command, app_commands.Group))
        ]


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
    if name and name not in skipped:
        skipped.append(name)


def install_class_guard() -> None:
    """Refuse immédiatement toute ancienne racine slash hors surface produit."""
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
            allowed = _preferred_names()
            if name not in allowed:
                _record_skip(self, name)
                return None

            roots = _global_roots(self)
            existing = next(
                (item for item in roots if str(getattr(item, "name", "")).casefold() == name),
                None,
            )
            if existing is None and len(roots) >= min(GLOBAL_CHAT_INPUT_BUDGET, len(allowed)):
                # Ce cas ne devrait arriver qu'avec une incohérence de registre. On échoue
                # proprement au lieu de faire tomber l'ajout du Cog entier.
                _record_skip(self, name)
                return None
        return base(self, command, **kwargs)

    guarded_add._sentrix_canonical_budget_guard = True
    guarded_add._sentrix_original = base
    app_commands.CommandTree.add_command = guarded_add
    logger.info(
        "Garde slash facile installé avant chargement : %s racines produit autorisées.",
        len(_preferred_names()),
    )


def finalize(bot: commands.Bot) -> None:
    """Supprime toute racine historique qui aurait échappé au garde initial."""
    tree = bot.tree
    allowed = _preferred_names()
    for item in list(_global_roots(tree)):
        name = str(getattr(item, "name", "") or "").casefold()
        if name not in allowed:
            _remove_root(tree, name)
            _record_skip(tree, name)

    roots = _global_roots(tree)
    if len(roots) > GLOBAL_CHAT_INPUT_BUDGET:
        for item in roots[GLOBAL_CHAT_INPUT_BUDGET:]:
            _remove_root(tree, str(getattr(item, "name", "") or "").casefold())

    bot._sentrix_slash_registry_count = len(_global_roots(tree))
    bot._sentrix_slash_surface_expected = len(allowed)
    bot._sentrix_slash_budget_installed = True
    logger.info(
        "Registre slash finalisé : %s/%s racines faciles présentes.",
        bot._sentrix_slash_registry_count,
        len(allowed),
    )


def install(bot: commands.Bot) -> None:
    install_class_guard()
    finalize(bot)


# cogs.__init__ importe ce module avant le chargement des extensions.
install_class_guard()


__all__ = ["GLOBAL_CHAT_INPUT_BUDGET", "install_class_guard", "install", "finalize"]
