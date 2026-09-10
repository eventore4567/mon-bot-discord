"""Budget et sélection canonique des commandes slash SentriX.

Discord limite une application à 100 racines CHAT_INPUT globales. SentriX possède plus
d'actions que cela : les commandes fusionnées/dupliquées ne doivent donc jamais consommer
le budget et une commande utile écartée pendant le chargement doit pouvoir être retentée
juste avant ``tree.sync()``.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.slash-budget")
GLOBAL_CHAT_INPUT_BUDGET = 100

# Le système proof doit rester disponible en slash. Ces quatre racines sont de vraies
# entrées utilisateur et non d'anciens alias.
PROOF_SLASH_PREFERRED = frozenset({"proof", "proofsetup", "proofexample", "proofstatus"})

# Le catalogue normal + proof dépasse de quatre racines la limite Discord. On rend donc
# quatre réglages XP administratifs volontairement +/dashboard-only au lieu de laisser
# l'ordre de chargement choisir AU HASARD quatre commandes slash à faire disparaître.
# Les commandes préfixées restent intactes.
SLASH_PREFIX_ONLY = frozenset({"set-xp", "add-xp", "set-level-role", "remove-level-role"})


def _preferred_names() -> set[str]:
    from .command_catalog_cleanup import NORMAL_DIRECT_COMMANDS

    return (set(NORMAL_DIRECT_COMMANDS) | set(PROOF_SLASH_PREFERRED)) - set(SLASH_PREFIX_ONLY)


def _excluded_names() -> set[str]:
    from .command_catalog_cleanup import (
        ADMIN_DIRECT_COMMANDS,
        MERGED_COMMANDS,
        PURE_DUPLICATE_COMMANDS,
    )

    # IMPORTANT : PURE_DUPLICATE_COMMANDS manquait ici. Ces racines occupaient des places
    # pendant le chargement, étaient supprimées ensuite par main._prune_redundant_commands,
    # mais les commandes utiles refusées entre-temps n'étaient jamais restaurées.
    return (
        set(ADMIN_DIRECT_COMMANDS)
        | set(MERGED_COMMANDS)
        | set(PURE_DUPLICATE_COMMANDS)
        | set(SLASH_PREFIX_ONLY)
    )


def _global_roots(tree) -> list:
    try:
        return list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    except Exception:
        return [
            item for item in tree.get_commands(guild=None)
            if isinstance(item, (app_commands.Command, app_commands.Group))
        ]


def _name(command) -> str:
    return str(getattr(command, "name", "") or "").casefold()


def _remove_root(tree, name: str) -> None:
    try:
        tree.remove_command(name, type=discord.AppCommandType.chat_input)
    except TypeError:
        tree.remove_command(name)


def _remember_deferred(bot: commands.Bot, command) -> None:
    """Garde une racine refusée afin de pouvoir la retenter après le nettoyage final."""
    name = _name(command)
    if not name:
        return
    queue = getattr(bot, "_sentrix_deferred_global_slash", None)
    if queue is None:
        queue = []
        bot._sentrix_deferred_global_slash = queue
    if any(_name(item) == name for item in queue):
        return
    queue.append(command)


def finalize(bot: commands.Bot) -> dict[str, object]:
    """Nettoie, retente les racines différées et garantit au maximum 100 racines /.

    Cette passe doit être appelée après le chargement/pruning de tous les cogs et juste
    avant ``tree.sync()``. Elle ne dépasse jamais la limite Discord.
    """
    tree = bot.tree
    preferred = _preferred_names()
    excluded = _excluded_names()

    removed: list[str] = []
    for item in list(_global_roots(tree)):
        name = _name(item)
        if name in excluded:
            _remove_root(tree, name)
            removed.append(name)

    # Si un ancien état a malgré tout dépassé 100, garder d'abord la surface canonique.
    roots = _global_roots(tree)
    if len(roots) > GLOBAL_CHAT_INPUT_BUDGET:
        keep: set[str] = set()
        for item in roots:
            name = _name(item)
            if name in preferred and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
                keep.add(name)
        for item in roots:
            name = _name(item)
            if name not in keep and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
                keep.add(name)
        for item in list(roots):
            name = _name(item)
            if name not in keep:
                _remove_root(tree, name)
                removed.append(name)

    original_add = getattr(bot, "_sentrix_slash_original_add", None)
    deferred = list(getattr(bot, "_sentrix_deferred_global_slash", []) or [])
    restored: list[str] = []
    remaining: list = []

    # Les commandes canonique/prioritaires passent avant les éventuelles commandes
    # secondaires différées. L'ordre dans chaque groupe reste celui du chargement.
    deferred.sort(key=lambda item: (0 if _name(item) in preferred else 1))
    for command in deferred:
        name = _name(command)
        if not name or name in excluded:
            continue
        roots = _global_roots(tree)
        if any(_name(item) == name for item in roots):
            continue
        if len(roots) >= GLOBAL_CHAT_INPUT_BUDGET or original_add is None:
            remaining.append(command)
            continue
        try:
            original_add(command, override=False)
            restored.append(name)
        except app_commands.CommandLimitReached:
            # Le compteur interne de discord.py reste la source finale de vérité. On garde
            # l'objet pour le diagnostic mais on ne fait surtout pas échouer le démarrage.
            remaining.append(command)
        except Exception:
            logger.exception("Impossible de restaurer la racine slash différée « %s ».", name)
            remaining.append(command)

    bot._sentrix_deferred_global_slash = remaining
    roots = _global_roots(tree)
    stats = {
        "roots": len(roots),
        "removed": tuple(removed),
        "restored": tuple(restored),
        "deferred": tuple(_name(item) for item in remaining),
    }
    logger.info(
        "Budget slash final : %s/%s racines, restaurées=%s, encore différées=%s.",
        len(roots),
        GLOBAL_CHAT_INPUT_BUDGET,
        ",".join(restored) or "aucune",
        ",".join(stats["deferred"]) or "aucune",
    )
    return stats


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_slash_budget_installed", False):
        return
    bot._sentrix_slash_budget_installed = True

    tree = bot.tree
    original_add = tree.add_command
    bot._sentrix_slash_original_add = original_add
    skipped: list[str] = []
    bot._sentrix_skipped_global_slash = skipped
    bot._sentrix_deferred_global_slash = []

    def _skip(command, *, defer: bool) -> None:
        name = _name(command)
        if name and name not in skipped:
            skipped.append(name)
        if defer:
            _remember_deferred(bot, command)

    def _call_original(command, *, guild=None, guilds=None, override: bool = False, defer_on_limit: bool = False):
        kwargs = {"override": override}
        if guild is not None:
            kwargs["guild"] = guild
        if guilds is not None:
            kwargs["guilds"] = guilds
        try:
            return original_add(command, **kwargs)
        except app_commands.CommandLimitReached:
            name = _name(command)
            _skip(command, defer=defer_on_limit)
            logger.warning(
                "Budget slash : « %s » différée après refus réel de discord.py "
                "(limite globale de 100 atteinte).",
                name,
            )
            return None

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
            name = _name(command)
            if name in _excluded_names():
                _skip(command, defer=False)
                return None

            roots = _global_roots(tree)
            existing = next((item for item in roots if _name(item) == name), None)
            if existing is None and len(roots) >= GLOBAL_CHAT_INPUT_BUDGET:
                preferred = _preferred_names()
                if name in preferred:
                    victim = next((item for item in roots if _name(item) not in preferred), None)
                    if victim is not None:
                        _remove_root(tree, _name(victim))
                    else:
                        _skip(command, defer=True)
                        return None
                else:
                    _skip(command, defer=True)
                    return None

        return _call_original(command, override=override, defer_on_limit=True)

    tree.add_command = MethodType(budgeted_add, tree)
    logger.info(
        "Budget slash SentriX actif : maximum %s racines ; %s réglages XP restent +/dashboard-only.",
        GLOBAL_CHAT_INPUT_BUDGET,
        len(SLASH_PREFIX_ONLY),
    )
