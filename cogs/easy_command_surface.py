"""Surface de commandes facile et canonique de SentriX.

Ce module est l'unique finaliseur du catalogue utilisateur :
- les anciennes commandes `+` restent intactes pour compatibilité ;
- les centres Ticket/Giveaway regroupent les actions rares sous une seule racine ;
- les HybridCommand utiles qui avaient historiquement `with_app_command=False` récupèrent
  leur variante `/` sans dupliquer la logique métier ;
- `/nick` et `/security` fournissent deux entrées courtes et évidentes ;
- le registre slash est ensuite retaillé exactement sur la surface produit.

Aucune couche V2/V3 ne réécrit ensuite le catalogue.
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
    """Regroupe les grosses familles sans exposer leurs anciennes racines dans `/`."""
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


def _restore_easy_hybrids(bot: commands.Bot) -> int:
    """Restaure uniquement les HybridCommand de la surface facile.

    Plusieurs cogs historiques ont volontairement créé leurs commandes avec
    ``with_app_command=False`` quand SentriX approchait 100 racines. On reconstruit ici
    l'Application Command native discord.py, seulement pour le petit catalogue actuel.
    """
    restored = 0
    for direct_name in sorted(command_catalog_cleanup.EASY_SLASH_COMMANDS):
        if direct_name in {"nickname", "security", "ticket", "giveaway"}:
            continue
        command = bot.get_command(direct_name)
        if command is None or command.parent is not None:
            continue
        if not isinstance(command, commands.HybridCommand):
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
            logger.warning("/%s ne peut pas être restaurée proprement : %s", slash_name, exc)
    return restored


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


def _install_nick(bot: commands.Bot) -> None:
    if bot.tree.get_command("nick") is not None:
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
            return await interaction.response.send_message(
                embed=embeds.error("Je n'ai pas la permission de modifier ce pseudo."),
                ephemeral=True,
            )
        await interaction.response.send_message(
            embed=embeds.success(f"Pseudo de {membre.mention} modifié en **{pseudo[:32]}**.")
        )

    bot.tree.add_command(nick, override=True)


def _install_security_entry(bot: commands.Bot) -> None:
    """Expose une seule entrée `/security` simple ; l'administration détaillée reste +security/setup."""
    if bot.tree.get_command("security") is not None:
        return

    @app_commands.command(
        name="security",
        description="Voir l'état de la sécurité et savoir où la configurer.",
    )
    @app_commands.guild_only()
    async def security(interaction: discord.Interaction):
        try:
            row = await bot.db.get_automod(interaction.guild_id)
            conf = dict(row) if row else {}
        except Exception:
            conf = {}

        filters = (
            "antispam", "antilink", "antiinvite", "antimention", "anticaps",
            "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
            "escalation",
        )
        active = sum(1 for key in filters if bool(conf.get(key, 0)))
        embed = discord.Embed(
            title="SentriX • Sécurité",
            description=(
                f"**{active}/{len(filters)}** protections sont actives.\n\n"
                "Pour modifier la sécurité, ouvre **`/setup` → Sécurité**. "
                "Les outils avancés restent disponibles avec **`+security`** pour le staff."
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
    restored = _restore_easy_hybrids(bot)
    _install_nick(bot)
    _install_security_entry(bot)
    command_catalog_cleanup.apply_surface(bot)
    slash_command_budget.finalize(bot)

    bot._sentrix_easy_command_surface = True
    bot._sentrix_command_surface_owner = "cogs.easy_command_surface"
    logger.info(
        "Surface facile finalisée : %s racines slash, %s hybride(s) restaurée(s), 5 jeux mis en avant.",
        getattr(bot, "_sentrix_slash_registry_count", "?"),
        restored,
    )


__all__ = ["install"]
