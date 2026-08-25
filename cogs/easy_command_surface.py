"""Surface slash canonique de SentriX.

Les anciennes commandes `+` restent intactes. Discord `/` conserve jusqu'à 100 racines
utiles : les HybridCommand saines sont restaurées nativement et les deux anciennes
signatures incompatibles (`image`, `unmute`) reçoivent un adaptateur direct minimal.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.hybrid import HybridAppCommand

from utils import embeds
from . import command_catalog_cleanup, slash_command_budget

logger = logging.getLogger("bot.easy-command-surface")


async def _install_centers(bot: commands.Bot) -> None:
    try:
        from . import command_ticket_center_v3
        command_ticket_center_v3.install(bot)
    except Exception:
        logger.exception("Centre Ticket impossible à installer.")
    try:
        from . import command_giveaway_center_v3
        command_giveaway_center_v3.install(bot)
    except Exception:
        logger.exception("Centre Giveaway impossible à installer.")


def _restore_slash_hybrids(bot: commands.Bot) -> int:
    """Restaure les HybridCommand autorisées dont la signature est native."""
    restored = 0
    adapters = {"nickname", "security", "ticket", "giveaway", "image", "unmute"}
    for direct_name in sorted(command_catalog_cleanup.SLASH_COMMANDS):
        if direct_name in adapters:
            continue
        command = bot.get_command(direct_name)
        if command is None or command.parent is not None or not isinstance(command, commands.HybridCommand):
            continue
        slash_name = str(command.name).casefold()
        if slash_name not in command_catalog_cleanup.slash_surface_names():
            continue
        if bot.tree.get_command(slash_name) is not None:
            continue
        try:
            if command.app_command is None:
                command.with_app_command = True
                command.app_command = HybridAppCommand(command)
            bot.tree.add_command(command.app_command, override=True)
            restored += 1
        except (TypeError, ValueError, app_commands.CommandAlreadyRegistered) as exc:
            logger.warning("/%s ne peut pas être restaurée nativement : %s", slash_name, exc)
    return restored


async def _configured_mod_allowed(bot: commands.Bot, interaction: discord.Interaction, permission: str) -> bool:
    member = interaction.user
    guild = interaction.guild
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator or bool(getattr(member.guild_permissions, permission, False)):
        return True
    # Les permissions quotidiennes de modération peuvent être accordées par le rôle modo.
    if permission not in {"moderate_members", "ban_members", "kick_members", "manage_messages", "manage_nicknames", "move_members"}:
        return False
    try:
        conf = await bot.db.get_guild_config(guild.id)
    except Exception:
        conf = None
    if conf and conf["mod_role"]:
        role = guild.get_role(conf["mod_role"])
        if role and role in member.roles:
            return True
    return False


def _install_nick(bot: commands.Bot) -> None:
    if bot.tree.get_command("nick") is not None:
        return

    async def nick_check(interaction: discord.Interaction) -> bool:
        if await _configured_mod_allowed(bot, interaction, "manage_nicknames"):
            return True
        raise app_commands.MissingPermissions(["manage_nicknames"])

    @app_commands.command(name="nick", description="Changer rapidement le pseudo d'un membre.")
    @app_commands.describe(membre="Membre à renommer", pseudo="Nouveau pseudo")
    @app_commands.check(nick_check)
    async def nick(interaction: discord.Interaction, membre: discord.Member, pseudo: str):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(embed=embeds.error("Cette commande doit être utilisée dans un serveur."), ephemeral=True)
        from utils import checks
        hierarchy_error = checks.check_hierarchy(interaction.user, membre)
        if hierarchy_error:
            return await interaction.response.send_message(embed=embeds.error(hierarchy_error), ephemeral=True)
        bot_error = checks.check_bot_hierarchy(interaction.guild, membre)
        if bot_error:
            return await interaction.response.send_message(embed=embeds.error(bot_error), ephemeral=True)
        try:
            await membre.edit(nick=pseudo[:32], reason=f"/nick par {interaction.user}")
        except discord.Forbidden:
            return await interaction.response.send_message(embed=embeds.error("Je n'ai pas la permission de modifier ce pseudo."), ephemeral=True)
        await interaction.response.send_message(embed=embeds.success(f"Pseudo de {membre.mention} modifié en **{pseudo[:32]}**."))

    bot.tree.add_command(nick, override=True)


def _install_unmute(bot: commands.Bot) -> None:
    """Adaptateur slash propre pour l'ancienne HybridCommand dont le callback a été wrappé."""
    if bot.tree.get_command("unmute") is not None:
        return
    legacy = bot.get_command("unmute")
    if legacy is None:
        return

    async def unmute_check(interaction: discord.Interaction) -> bool:
        if await _configured_mod_allowed(bot, interaction, "moderate_members"):
            return True
        raise app_commands.MissingPermissions(["moderate_members"])

    @app_commands.command(name="unmute", description="Retirer le mute d'un membre.")
    @app_commands.describe(membre="Membre à démuter", raison="Raison de l'action")
    @app_commands.guild_only()
    @app_commands.check(unmute_check)
    async def unmute(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison fournie"):
        from utils import checks
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            return await interaction.response.send_message(embed=embeds.error("Cette commande doit être utilisée dans un serveur."), ephemeral=True)
        hierarchy_error = checks.check_hierarchy(interaction.user, membre)
        if hierarchy_error:
            return await interaction.response.send_message(embed=embeds.error(hierarchy_error), ephemeral=True)
        bot_error = checks.check_bot_hierarchy(interaction.guild, membre)
        if bot_error:
            return await interaction.response.send_message(embed=embeds.error(bot_error), ephemeral=True)
        ctx = await commands.Context.from_interaction(interaction)
        await ctx.invoke(legacy, membre, raison=raison)

    bot.tree.add_command(unmute, override=True)


def _install_image(bot: commands.Bot) -> None:
    """Adaptateur slash qui réutilise entièrement le moteur +image existant."""
    if bot.tree.get_command("image") is not None:
        return
    legacy = bot.get_command("image")
    if legacy is None:
        return

    @app_commands.command(name="image", description="Générer une image 4K à partir d'une description.")
    @app_commands.describe(description="Décris précisément l'image à créer")
    async def image(interaction: discord.Interaction, description: str):
        try:
            ctx = await commands.Context.from_interaction(interaction)
            # Context.invoke n'applique pas les cooldowns automatiquement : on conserve
            # explicitement le cooldown historique de +image avant d'appeler son moteur.
            prepare = getattr(legacy, "_prepare_cooldowns", None)
            if callable(prepare):
                prepare(ctx)
            await ctx.invoke(legacy, description=description)
        except commands.CommandOnCooldown as exc:
            message = f"Réessaie dans **{max(1, round(exc.retry_after))} s**."
            if interaction.response.is_done():
                await interaction.followup.send(embed=embeds.warning(message), ephemeral=True)
            else:
                await interaction.response.send_message(embed=embeds.warning(message), ephemeral=True)

    bot.tree.add_command(image, override=True)


def _install_security_entry(bot: commands.Bot) -> None:
    if bot.tree.get_command("security") is not None:
        return

    @app_commands.command(name="security", description="Voir l'état de la sécurité du serveur.")
    @app_commands.guild_only()
    async def security(interaction: discord.Interaction):
        try:
            row = await bot.db.get_automod(interaction.guild_id)
            conf = dict(row) if row else {}
        except Exception:
            conf = {}
        filters = (
            "antispam", "antilink", "antiinvite", "antimention", "anticaps",
            "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke", "escalation",
        )
        active = sum(1 for key in filters if bool(conf.get(key, 0)))
        embed = discord.Embed(
            title="Sécurité",
            description=(
                f"**{active}/{len(filters)}** protections sont actives.\n"
                "Pour les modifier : **`/setup` → Sécurité**."
            ),
            colour=discord.Colour(0x6C5CE7),
        )
        await interaction.response.send_message(embed=embed)

    bot.tree.add_command(security, override=True)


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_easy_command_surface", False):
        command_catalog_cleanup.apply_surface(bot)
        slash_command_budget.finalize(bot)
        return

    command_catalog_cleanup.install(bot)
    await _install_centers(bot)
    restored = _restore_slash_hybrids(bot)
    _install_nick(bot)
    _install_unmute(bot)
    _install_image(bot)
    _install_security_entry(bot)
    command_catalog_cleanup.apply_surface(bot)
    slash_command_budget.finalize(bot)

    bot._sentrix_easy_command_surface = True
    bot._sentrix_command_surface_owner = "cogs.easy_command_surface"
    logger.info(
        "Surface slash finalisée : %s/100 racines, %s hybride(s) restaurée(s), anciens + conservés.",
        getattr(bot, "_sentrix_slash_registry_count", "?"), restored,
    )


__all__ = ["install"]
