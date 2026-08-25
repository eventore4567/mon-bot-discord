"""Correctifs runtime pour +sentrix-server.

Cette couche conserve l'alias texte sur la commande hybride ``create-server`` sans ajouter
de nouvelle commande slash. Elle applique aussi la réparation d'identification du serveur
officiel avant d'exécuter l'alias.
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

    # Répare d'abord la détection du serveur officiel. L'invitation officielle devient
    # prioritaire sur les anciens IDs persistants éventuellement obsolètes.
    try:
        from .official_server_binding_fix import install as install_binding_fix
        install_binding_fix(bot)
    except Exception:
        logger.exception("Impossible d'installer le correctif d'identification du serveur officiel.")

    # V62 transforme #serveurs-sentrix en journal d'ajouts uniquement. Il doit être
    # installé même lorsque le callback create-server est déjà corrigé/idempotent.
    try:
        from .official_server_join_feed_v62 import install as install_join_feed_v62
        install_join_feed_v62(bot)
    except Exception:
        logger.exception("Impossible d'installer le journal d'ajouts serveurs V62.")

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

    logger.info("Alias +sentrix-server corrigé : signature sûre + serveur officiel auto-réparé.")


__all__ = ["install"]
