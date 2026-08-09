"""Dernier verrou propriétaire pour les protections SentriX.

Garantit deux règles globales :
1. seul le propriétaire RÉEL du serveur Discord peut modifier une whitelist/exemption ;
2. le propriétaire du serveur est aussi immunisé contre le runtime Anti-GIF.

Les checks s'ajoutent aux checks existants : ils ne les élargissent jamais.
"""
from __future__ import annotations

import asyncio
import logging
from types import MethodType

from discord.ext import commands

from utils import checks

logger = logging.getLogger("bot.security.owner-final")

_OWNER_ONLY_QUALIFIED = (
    "security whitelist user-add",
    "security whitelist user-remove",
    "security whitelist role-add",
    "security whitelist role-remove",
    "security whitelist domain-add",
    "security whitelist domain-remove",
    "antinuke-whitelist-add",
    "antinuke-whitelist-remove",
    "automod-exempt-role-add",
    "automod-exempt-role-remove",
    "whitelist-domain",
    "unwhitelist-domain",
)


async def _server_owner_only(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        raise checks.BotPermissionError("Cette commande doit être utilisée dans un serveur.")
    if ctx.author.id == ctx.guild.owner_id:
        return True
    raise checks.BotPermissionError(
        "Seul le **propriétaire réel du serveur Discord** peut modifier une whitelist ou une exemption."
    )


def _guard_whitelists(bot: commands.Bot) -> None:
    for qualified in _OWNER_ONLY_QUALIFIED:
        command = bot.get_command(qualified)
        if command is None or getattr(command, "_sentrix_real_owner_whitelist", False):
            continue
        command.add_check(_server_owner_only)
        command._sentrix_real_owner_whitelist = True
        logger.info("Whitelist owner-only : %s", qualified)


def _patch_antigif(bot: commands.Bot) -> None:
    runtime = getattr(bot, "_sentrix_antigif_runtime", None)
    if runtime is None:
        return
    current = runtime.handle_message
    func = getattr(current, "__func__", current)
    if getattr(func, "_sentrix_owner_antigif_immunity", False):
        return

    async def owner_safe_antigif(_self, message):
        if message.guild is not None and message.author.id == message.guild.owner_id:
            return None
        return await current(message)

    owner_safe_antigif._sentrix_owner_antigif_immunity = True
    runtime.handle_message = MethodType(owner_safe_antigif, runtime)
    logger.info("Immunité Anti-GIF du propriétaire réel activée.")


async def _late_reapply(bot: commands.Bot) -> None:
    # Utility charge le runtime Anti-GIF après certaines couches communes. On repasse
    # quelques fois pour garantir la règle même si l'ordre des extensions change.
    for _ in range(8):
        await asyncio.sleep(1)
        _guard_whitelists(bot)
        _patch_antigif(bot)
        if getattr(bot, "_sentrix_antigif_runtime", None) is not None:
            runtime = bot._sentrix_antigif_runtime
            func = getattr(runtime.handle_message, "__func__", runtime.handle_message)
            if getattr(func, "_sentrix_owner_antigif_immunity", False):
                break


def install(bot: commands.Bot) -> None:
    _guard_whitelists(bot)
    _patch_antigif(bot)
    if not getattr(bot, "_sentrix_owner_final_repatch", False):
        bot._sentrix_owner_final_repatch = True
        try:
            asyncio.create_task(_late_reapply(bot), name="sentrix-owner-security-repatch")
        except RuntimeError:
            pass
