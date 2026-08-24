"""Correctif de signature pour l'alias texte +sentrix-server.

Le constructeur officiel réutilise la commande hybride ``create-server`` afin de ne pas
ajouter une nouvelle commande slash. L'ancien wrapper remplaçait directement
``Command.callback`` avec une fonction ``(cog, ctx, *args, **kwargs)``. discord.py et les
helpers UX pouvaient alors recalculer les paramètres de la commande et exposer ``ctx``
comme un argument utilisateur obligatoire.

Cette couche conserve l'alias mais remplace le callback par un wrapper dont la signature
publique est celle du callback original grâce à ``functools.wraps``. Pour Discord, la
commande reste donc exactement une commande sans argument utilisateur.
"""
from __future__ import annotations

import functools
import logging

from discord.ext import commands

from .official_server import OFFICIAL_ALIASES


logger = logging.getLogger("bot.official-server-command-fix")


def _unwrap_original(callback):
    """Retrouve le vrai callback create_server derrière les anciens wrappers SentriX."""
    seen: set[int] = set()
    current = callback
    while getattr(current, "_sentrix_official_original", None) is not None:
        marker = id(current)
        if marker in seen:
            break
        seen.add(marker)
        current = current._sentrix_official_original
    return current


def install(bot: commands.Bot) -> None:
    command = bot.get_command("create-server")
    runtime = getattr(bot, "_sentrix_official_server_runtime", None)
    if command is None or runtime is None:
        return

    # Les aliases restent rattachés au même objet Command. Cela n'ajoute donc aucune
    # commande slash/racine supplémentaire.
    for alias in OFFICIAL_ALIASES:
        if alias not in command.aliases:
            command.aliases.append(alias)
        bot.all_commands[alias] = command

    current = command.callback
    if getattr(current, "_sentrix_signature_safe", False):
        return

    original = _unwrap_original(current)

    @functools.wraps(original)
    async def signature_safe(builder_cog, ctx: commands.Context):
        invoked = str(getattr(ctx, "invoked_with", "") or "").casefold()
        if invoked in OFFICIAL_ALIASES:
            return await runtime.run_official_command(ctx)
        return await original(builder_cog, ctx)

    # Ces marqueurs empêchent official_server.patch_create_server_alias() de réempiler
    # l'ancien wrapper lors d'un on_ready ou d'un rechargement d'extension.
    signature_safe._sentrix_official_wrapper = True
    signature_safe._sentrix_official_original = original
    signature_safe._sentrix_signature_safe = True
    command.callback = signature_safe

    logger.info("Alias +sentrix-server corrigé : aucune saisie de ctx/args requise.")


__all__ = ["install"]
