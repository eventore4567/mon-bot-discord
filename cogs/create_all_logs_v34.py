"""SentriX V34 — création/configuration complète de tous les salons de logs.

Commandes :
- +createalllogs / /createalllogs
- l'ancienne +create-logs réutilise également ce moteur.

Le moteur crée uniquement les salons manquants, réutilise ceux qui existent déjà,
configure log_settings + les colonnes legacy utiles, active chaque catégorie et garde
les salons privés au staff.
"""
from __future__ import annotations

import logging
import re
import types

import discord
from discord import app_commands
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.create-all-logs-v34")


# Ordre volontairement identique à l'organisation demandée dans le serveur.
ALL_LOG_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("tickets", "logs-tickets", "Ouverture, fermeture, claim et suivi des tickets SentriX."),
    ("cases", "logs-dossiers", "Dossiers de modération, avertissements et sanctions suivies."),
    ("server", "logs-serveur", "Modifications générales du serveur et de sa configuration."),
    ("messages", "logs-messages", "Messages modifiés ou supprimés."),
    ("members", "logs-membre", "Arrivées, départs et changements importants des membres."),
    ("voice", "logs-vocal", "Connexions, déconnexions et déplacements vocaux."),
    ("roles", "logs-roles", "Création, suppression, modification et attribution des rôles."),
    ("moderation", "logs-modération", "Warns, mutes, timeouts, kicks, bans et autres sanctions."),
    ("spam", "logs-protect-spam-logs", "Détections anti-spam, liens, mentions, caps et arnaques."),
    ("automod", "automod", "Actions générales AutoMod et protections automatiques SentriX."),
    ("staff", "moderator-only", "Commandes sensibles exécutées par le staff et les administrateurs."),
    ("raid", "raidprotect-logs", "Détections anti-raid, anti-nuke et actions massives suspectes."),
    ("channels", "logs-salons", "Création, suppression et modification des salons et catégories."),
)

# Compatibilité avec les anciens listeners/configurations encore présents dans SentriX.
LEGACY_COLUMNS = {
    "tickets": "ticket_log_channel",
    "server": "log_server",
    "messages": "log_messages",
    "members": "log_members",
    "voice": "log_voice",
    "roles": "log_roles",
    "moderation": "log_moderation",
    "automod": "log_automod",
}

# Noms historiques acceptés : on ne crée jamais un doublon juste pour une différence
# d'accent/pluriel utilisée par une ancienne version du bot.
ALIASES = {
    "tickets": ("logs-tickets",),
    "cases": ("logs-dossiers",),
    "server": ("logs-serveur",),
    "messages": ("logs-messages",),
    "members": ("logs-membre", "logs-membres"),
    "voice": ("logs-vocal", "logs-vocaux"),
    "roles": ("logs-roles", "logs-rôles"),
    "moderation": ("logs-modération", "logs-moderation"),
    "spam": ("logs-protect-spam-logs", "protect-spam-logs"),
    "automod": ("automod", "logs-securite", "logs-sécurité"),
    "staff": ("moderator-only", "logs-moderator-only"),
    "raid": ("raidprotect-logs", "logs-raidprotect"),
    "channels": ("logs-salons",),
}


def _norm(value: str) -> str:
    text = value.casefold()
    for old, new in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("ù", "u"), ("ô", "o"), ("î", "i"), ("ç", "c")):
        text = text.replace(old, new)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _find_channel(guild: discord.Guild, names: tuple[str, ...]) -> discord.TextChannel | None:
    wanted = {_norm(name) for name in names}
    for channel in guild.text_channels:
        if _norm(channel.name) in wanted:
            return channel
    return None


def _find_category(guild: discord.Guild) -> discord.CategoryChannel | None:
    # D'abord la catégorie officielle.
    for category in guild.categories:
        if "sentrix" in _norm(category.name) and "logs" in _norm(category.name):
            return category
    # Sinon on réutilise la catégorie d'un salon de logs existant.
    for _log_type, _name, _topic in ALL_LOG_CHANNELS:
        channel = _find_channel(guild, ALIASES.get(_log_type, (_name,)))
        if channel is not None and channel.category is not None:
            return channel.category
    return None


async def _overwrites(bot: commands.Bot, guild: discord.Guild, author: discord.Member):
    result: dict[object, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    if guild.me is not None:
        result[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            manage_channels=True,
        )

    try:
        conf = await bot.db.get_guild_config(guild.id)
    except Exception:
        conf = None
    mod_role_id = None
    if conf:
        try:
            mod_role_id = conf["mod_role"]
        except Exception:
            pass
    role = guild.get_role(int(mod_role_id)) if mod_role_id else None
    if role is not None:
        result[role] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )

    # L'admin qui lance la commande conserve toujours l'accès à ce qu'il vient de créer.
    result[author] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
    )
    return result


async def ensure_all_log_channels(
    bot: commands.Bot,
    guild: discord.Guild,
    author: discord.Member,
) -> tuple[list[discord.TextChannel], list[discord.TextChannel], discord.CategoryChannel]:
    """Crée les manquants, réutilise les existants et configure les 13 journaux."""
    category = _find_category(guild)
    overwrites = await _overwrites(bot, guild, author)
    if category is None:
        category = await guild.create_category(
            "📡 SentriX — Logs",
            overwrites=overwrites,
            reason=f"Installation complète des logs SentriX par {author}",
        )

    created: list[discord.TextChannel] = []
    reused: list[discord.TextChannel] = []
    resolved: dict[str, discord.TextChannel] = {}

    for log_type, channel_name, topic in ALL_LOG_CHANNELS:
        aliases = ALIASES.get(log_type, (channel_name,))
        channel = _find_channel(guild, aliases)
        if channel is None:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
                topic=topic,
                reason=f"Installation complète des logs SentriX par {author}",
            )
            created.append(channel)
        else:
            reused.append(channel)

        resolved[log_type] = channel

        # Source moderne utilisée par le dashboard et le moteur central.
        await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
        await log_service.set_log_enabled(bot, guild.id, log_type, True)

        # Source historique : évite qu'un ancien listener ou une ancienne page de config
        # continue de pointer ailleurs.
        legacy = LEGACY_COLUMNS.get(log_type)
        if legacy:
            try:
                await bot.db.set_guild_config(guild.id, legacy, channel.id)
            except Exception:
                logger.exception("V34 : impossible de synchroniser %s pour guild=%s", legacy, guild.id)

    # Le salon général historique ne doit pas écraser un choix existant. S'il n'existe pas,
    # logs-modération devient le repli logique des anciens modules.
    try:
        conf = await bot.db.get_guild_config(guild.id)
        general = conf["log_channel"] if conf else None
        if not general and "moderation" in resolved:
            await bot.db.set_guild_config(guild.id, "log_channel", resolved["moderation"].id)
    except Exception:
        logger.exception("V34 : impossible de configurer le salon de repli guild=%s", guild.id)

    return created, reused, category


def _patch_old_create_logs(bot: commands.Bot) -> None:
    """+create-logs utilise désormais exactement le même moteur que +createalllogs."""
    try:
        from . import configuration
    except Exception:
        return

    current = configuration.Configuration.create_log_channels
    if getattr(current, "_sentrix_all_logs_v34", False):
        return

    async def create_log_channels_v34(self, guild: discord.Guild, author: discord.Member):
        created, _reused, _category = await ensure_all_log_channels(self.bot, guild, author)
        return created

    create_log_channels_v34._sentrix_all_logs_v34 = True
    create_log_channels_v34._sentrix_original = current
    configuration.Configuration.create_log_channels = create_log_channels_v34

    # Si le Cog Configuration est déjà chargé, sa méthode liée utilise la méthode de classe
    # lors du prochain accès ; aucun remplacement de commande Discord n'est nécessaire.
    logger.info("V34 : +create-logs redirigé vers l'installation complète des 13 journaux.")


class CreateAllLogsV34(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="createalllogs",
        aliases=["create-all-logs", "alllogs"],
        description="Créer et configurer tous les salons de logs SentriX automatiquement.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.default_permissions(administrator=True)
    @commands.cooldown(1, 20, commands.BucketType.guild)
    async def createalllogs(self, ctx: commands.Context):
        if not isinstance(ctx.author, discord.Member):
            return
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        try:
            created, reused, category = await ensure_all_log_channels(
                self.bot, ctx.guild, ctx.author
            )
        except discord.Forbidden:
            return await ctx.send(
                "SentriX n'a pas les permissions nécessaires pour créer/configurer les salons de logs.",
                ephemeral=bool(ctx.interaction),
            )
        except discord.HTTPException as exc:
            return await ctx.send(
                f"Discord a refusé la création des logs : `{exc}`",
                ephemeral=bool(ctx.interaction),
            )
        except Exception:
            logger.exception("V34 : installation complète impossible guild=%s", ctx.guild.id)
            return await ctx.send(
                "Une erreur interne a empêché l'installation complète des logs.",
                ephemeral=bool(ctx.interaction),
            )

        names = "\n".join(f"• {channel.mention}" for channel in (created + reused))
        embed = discord.Embed(
            title="Logs SentriX configurés",
            description=(
                f"**13 catégories** sont maintenant reliées et activées dans {category.mention}.\n"
                f"**{len(created)}** salon(s) créé(s) • **{len(reused)}** salon(s) réutilisé(s)."
            ),
            colour=0x7C5CFC,
        )
        embed.add_field(name="Salons", value=names[:1024] or "Aucun salon disponible.", inline=False)
        embed.set_footer(text="SentriX • Configuration complète des logs")
        await ctx.send(embed=embed, ephemeral=bool(ctx.interaction))


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    _patch_old_create_logs(bot)
    if bot.get_cog("CreateAllLogsV34") is None:
        await bot.add_cog(CreateAllLogsV34(bot))


__all__ = ["install", "ensure_all_log_channels", "ALL_LOG_CHANNELS"]
