"""Raccourcis slash indispensables qui n'existaient qu'en préfixe."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks, embeds

logger = logging.getLogger("bot.command-direct-aliases-v2")


async def _nick_allowed(bot: commands.Bot, interaction: discord.Interaction) -> bool:
    member = interaction.user
    guild = interaction.guild
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.manage_nicknames:
        return True
    try:
        conf = await bot.db.get_guild_config(guild.id)
    except Exception:
        conf = None
    if conf and conf["mod_role"]:
        role = guild.get_role(conf["mod_role"])
        if role and role in member.roles:
            return True
    return False


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_nick_slash_v2", False):
        return
    if bot.get_cog("Moderation") is None:
        return
    if bot.tree.get_command("nick") is not None:
        bot._sentrix_nick_slash_v2 = True
        return

    async def nick_check(interaction: discord.Interaction) -> bool:
        if await _nick_allowed(bot, interaction):
            return True
        raise app_commands.MissingPermissions(["manage_nicknames"])

    @app_commands.command(name="nick", description="Changer rapidement le pseudo d'un membre.")
    @app_commands.describe(membre="Membre à renommer", pseudo="Nouveau pseudo")
    @app_commands.check(nick_check)
    async def nick(interaction: discord.Interaction, membre: discord.Member, pseudo: str):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                embed=embeds.error("Cette commande doit être utilisée dans un serveur."),
                ephemeral=True,
            )

        hierarchy_error = checks.check_hierarchy(interaction.user, membre)
        if hierarchy_error:
            return await interaction.response.send_message(
                embed=embeds.error(hierarchy_error), ephemeral=True
            )
        bot_error = checks.check_bot_hierarchy(interaction.guild, membre)
        if bot_error:
            return await interaction.response.send_message(
                embed=embeds.error(bot_error), ephemeral=True
            )
        try:
            await membre.edit(nick=pseudo[:32], reason=f"/nick par {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message(
                embed=embeds.error("Je n'ai pas la permission de modifier ce pseudo."),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=embeds.success(f"Pseudo de {membre.mention} modifié en **{pseudo[:32]}**.")
        )

    bot.tree.add_command(nick)
    bot._sentrix_nick_slash_v2 = True
    logger.info("Commande /nick installée.")
