"""Finitions du serveur officiel SentriX.

Ajoute deux comportements sans créer de nouvelle commande :
- ordre déterministe des rôles officiels juste sous le rôle de SentriX ;
- journal public d'ajout/retrait de serveurs dans #serveurs-sentrix, sans exposer
  le nom ou les informations privées des autres communautés.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from .official_server import ROLE_NAMES


logger = logging.getLogger("bot.official-server-polish")

ROLE_ORDER = [
    ROLE_NAMES["founder"],
    ROLE_NAMES["cofounder"],
    ROLE_NAMES["developer"],
    ROLE_NAMES["staff_manager"],
    ROLE_NAMES["admin"],
    ROLE_NAMES["moderator"],
    ROLE_NAMES["trial_moderator"],
    ROLE_NAMES["support"],
    ROLE_NAMES["animator"],
    ROLE_NAMES["vip"],
    ROLE_NAMES["booster"],
    ROLE_NAMES["partner"],
    ROLE_NAMES["active"],
    ROLE_NAMES["member"],
    ROLE_NAMES["updates"],
    ROLE_NAMES["giveaways"],
    ROLE_NAMES["events"],
    ROLE_NAMES["bots"],
    ROLE_NAMES["muted"],
]


async def _reorder_roles(runtime, guild: discord.Guild) -> None:
    """Place les rôles officiels dans l'ordre prévu, tous sous le rôle du bot."""
    me = guild.me
    if me is None:
        return

    targets: list[discord.Role] = []
    for name in ROLE_ORDER:
        role = discord.utils.get(guild.roles, name=name)
        if role is not None and not role.managed:
            targets.append(role)

    if not targets:
        return

    # Discord numérote @everyone à 0 et augmente la position vers le haut. Le rôle
    # le plus élevé de SentriX doit rester strictement sous le rôle le plus haut du bot.
    top_available = me.top_role.position - 1
    if top_available < len(targets):
        logger.warning(
            "Hiérarchie officielle non réordonnée : rôle SentriX trop bas (%s positions disponibles pour %s rôles).",
            top_available,
            len(targets),
        )
        return

    positions = {
        role: top_available - index
        for index, role in enumerate(targets)
    }
    try:
        await guild.edit_role_positions(
            positions=positions,
            reason="Ordre officiel des rôles SentriX",
        )
        logger.info("Hiérarchie officielle SentriX réordonnée : %s rôles.", len(targets))
    except discord.Forbidden:
        logger.warning("Discord a refusé le réordonnancement des rôles SentriX.")
    except discord.HTTPException:
        logger.exception("Erreur Discord pendant le réordonnancement des rôles SentriX.")


async def _publish_server_event(runtime, *, joined: bool) -> None:
    """Publie un événement agrégé sans divulguer l'identité du serveur tiers."""
    guild_id = await runtime.official_guild_id()
    if not guild_id:
        return
    official = runtime.bot.get_guild(guild_id)
    if official is None:
        return
    channel = runtime._find_text(official, "serveurs-sentrix")
    if channel is None:
        return

    total = len(runtime.bot.guilds)
    if joined:
        title = "✦ Nouveau serveur connecté"
        description = (
            "Un nouveau serveur vient d'ajouter **SentriX**. 💜\n"
            f"SentriX est maintenant présent sur **{total} serveur(s)**."
        )
        colour = discord.Color.from_rgb(34, 197, 94)
    else:
        title = "✦ Serveur déconnecté"
        description = (
            "Un serveur vient de retirer **SentriX**.\n"
            f"SentriX reste présent sur **{total} serveur(s)**."
        )
        colour = discord.Color.from_rgb(107, 114, 128)

    embed = runtime._base_embed(title, description, colour=colour)
    embed.add_field(
        name="Confidentialité",
        value="Le nom du serveur tiers n'est pas publié automatiquement.",
        inline=False,
    )
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        logger.exception("Impossible de publier l'événement de serveur SentriX.")


def install(bot: commands.Bot) -> None:
    runtime = getattr(bot, "_sentrix_official_server_runtime", None)
    if runtime is None or getattr(bot, "_sentrix_official_server_polish", False):
        return

    original_build = runtime.build_official_server

    async def build_with_role_order(guild, author, builder):
        result = await original_build(guild, author, builder)
        try:
            if await runtime.is_official_guild(guild):
                await _reorder_roles(runtime, guild)
        except Exception:
            logger.exception("Impossible de finaliser l'ordre des rôles officiels.")
        return result

    runtime.build_official_server = build_with_role_order

    async def on_join_feed(guild: discord.Guild) -> None:
        try:
            official_id = await runtime.official_guild_id()
            if official_id and guild.id != official_id:
                # L'événement gateway arrive parfois avant la stabilisation complète de
                # bot.guilds ; une courte attente garantit un compteur cohérent.
                await asyncio.sleep(1)
                await _publish_server_event(runtime, joined=True)
        except Exception:
            logger.exception("Échec du journal d'ajout d'un serveur SentriX.")

    async def on_remove_feed(guild: discord.Guild) -> None:
        try:
            official_id = await runtime.official_guild_id()
            if official_id and guild.id != official_id:
                await _publish_server_event(runtime, joined=False)
        except Exception:
            logger.exception("Échec du journal de retrait d'un serveur SentriX.")

    bot.add_listener(on_join_feed, "on_guild_join")
    bot.add_listener(on_remove_feed, "on_guild_remove")
    bot._sentrix_official_server_polish = True
    logger.info("Finitions serveur officiel actives : hiérarchie rôles + journal des ajouts/retraits.")
