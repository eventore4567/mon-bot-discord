"""Notification propriétaire lors de l'ajout de SentriX à un serveur.

Aucune action n'est effectuée sur le serveur rejoint. Le module envoie uniquement au
créateur principal du bot un résumé technique non sensible de la nouvelle guilde et le
nombre total de serveurs actuellement connectés.
"""
from __future__ import annotations

import logging

import discord

from database.db import PRIMARY_CREATOR_ID

logger = logging.getLogger("bot.guild-join-notify-v46")


async def _creator(bot: discord.Client) -> discord.User | None:
    user = bot.get_user(PRIMARY_CREATOR_ID)
    if user is not None:
        return user
    try:
        return await bot.fetch_user(PRIMARY_CREATOR_ID)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _notify_join(bot: discord.Client, guild: discord.Guild) -> None:
    creator = await _creator(bot)
    if creator is None:
        logger.warning(
            "Notification ajout serveur impossible : créateur %s introuvable.",
            PRIMARY_CREATOR_ID,
        )
        return

    bot_name = getattr(getattr(bot, "user", None), "name", None) or "SentriX"
    owner = guild.owner
    owner_text = f"{owner} — {guild.owner_id}" if owner is not None else str(guild.owner_id)
    members = int(guild.member_count or 0)
    total_guilds = len(getattr(bot, "guilds", []) or [])

    text = (
        f"{bot_name} vient d'être ajouté à un nouveau serveur.\n\n"
        f"Serveur : {guild.name}\n"
        f"ID : {guild.id}\n"
        f"Propriétaire : {owner_text}\n"
        f"Membres : {members}\n"
        f"Total de serveurs avec {bot_name} : {total_guilds}"
    )

    try:
        await creator.send(text, allowed_mentions=discord.AllowedMentions.none())
        logger.info(
            "Notification ajout serveur envoyée au créateur : %s (%s), total=%s.",
            guild.name,
            guild.id,
            total_guilds,
        )
    except (discord.Forbidden, discord.HTTPException):
        # Un MP fermé ne doit jamais perturber l'arrivée du bot dans la guilde.
        logger.warning(
            "Impossible d'envoyer le MP d'ajout serveur au créateur pour %s (%s).",
            guild.name,
            guild.id,
            exc_info=True,
        )


def install(bot: discord.Client) -> None:
    """Enregistre une seule fois le listener on_guild_join sur l'instance du bot."""
    if getattr(bot, "_sentrix_guild_join_notify_v46", False):
        return

    async def on_guild_join(guild: discord.Guild) -> None:
        await _notify_join(bot, guild)

    bot.add_listener(on_guild_join, "on_guild_join")
    bot._sentrix_guild_join_notify_v46 = True
    logger.info("Notification MP des nouveaux serveurs active.")
