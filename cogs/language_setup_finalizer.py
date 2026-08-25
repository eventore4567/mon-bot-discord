"""Compatibilité du finaliseur de langue historique.

Le choix de langue appartient maintenant directement à ``setup_oxyde_style``. Ce module
ne remplace plus ``Configuration.SetupView`` et ne réécrit plus l'ouverture du panneau.
Il conserve seulement le nettoyage des anciens slash locaux et la commande owner
``syncguild`` associée à cette maintenance.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.slash-local-maintenance")


async def _purge_local_slash_for_guild(bot: commands.Bot, guild: discord.Guild) -> int:
    try:
        remote = await bot.tree.fetch_commands(guild=guild)
    except discord.HTTPException:
        logger.warning("Lecture des slash locaux impossible guild=%s.", guild.id)
        return 0
    if not remote:
        return 0
    try:
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
    except discord.HTTPException:
        logger.exception("Suppression des anciens slash locaux impossible guild=%s.", guild.id)
        return 0
    logger.info("%s ancien(s) slash local(aux) supprimé(s) guild=%s.", len(remote), guild.id)
    return len(remote)


def _install_local_cleanup(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_local_slash_cleanup_canonical", False):
        return

    async def cleanup_once():
        if getattr(bot, "_sentrix_local_slash_cleanup_running", False):
            return
        bot._sentrix_local_slash_cleanup_running = True
        try:
            await asyncio.sleep(2)
            for guild in list(bot.guilds):
                await _purge_local_slash_for_guild(bot, guild)
        finally:
            bot._sentrix_local_slash_cleanup_running = False

    bot.add_listener(cleanup_once, "on_ready")
    bot._sentrix_local_slash_cleanup_canonical = True


def _patch_syncguild(bot: commands.Bot) -> None:
    command = bot.get_command("syncguild")
    if command is None or getattr(command, "_sentrix_global_only_sync", False):
        return

    async def safe_syncguild(cog, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send(embed=embeds.error("Cette commande doit être utilisée dans un serveur."))
        removed = await _purge_local_slash_for_guild(bot, ctx.guild)
        try:
            synced = await bot.tree.sync()
        except discord.HTTPException as exc:
            return await ctx.send(embed=embeds.error(f"Discord a refusé la synchronisation globale : `{exc}`"))
        await ctx.send(embed=embeds.success(
            f"Synchronisation globale terminée : **{len(synced)}** racine(s), **{removed}** ancien(s) slash local(aux) supprimé(s)."
        ))

    command.callback = safe_syncguild
    command._sentrix_global_only_sync = True


def install(bot: commands.Bot) -> None:
    _install_local_cleanup(bot)
    _patch_syncguild(bot)
    bot._sentrix_language_setup_finalizer_is_compat = True


__all__ = ["install", "_purge_local_slash_for_guild"]
