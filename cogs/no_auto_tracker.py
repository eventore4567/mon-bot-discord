"""Empêche +create-server et sa migration de publier +suivi-bot automatiquement.

Le cog BotTracker et la commande +suivi-bot restent disponibles. Seule la publication
automatique dans #annonces est désactivée. Une migration unique retire les anciens panneaux
de suivi qui avaient été insérés automatiquement dans #annonces ; les futurs panneaux
créés manuellement avec +suivi-bot ne seront pas supprimés.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

logger = logging.getLogger("bot.no-auto-tracker")
_MIGRATION_KEY = "remove_auto_announcement_tracker_v1"


def _plain(value: str) -> str:
    value = (value or "").strip()
    if "・" in value:
        value = value.split("・", 1)[1]
    return value.strip().casefold()


async def _cleanup_previous_automatic_trackers(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        # Audit/CI : les extensions sont chargées sans authentifier le client Discord.
        return
    await asyncio.sleep(5)
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS sentrix_runtime_migrations "
        "(name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    done = await bot.db.fetchone(
        "SELECT 1 FROM sentrix_runtime_migrations WHERE name = ?",
        (_MIGRATION_KEY,),
    )
    if done:
        return

    try:
        rows = await bot.db.fetchall("SELECT * FROM bot_tracker_panels")
    except Exception:
        rows = []

    for row in rows:
        guild = bot.get_guild(int(row["guild_id"]))
        if guild is None:
            continue
        channel = guild.get_channel(int(row["channel_id"]))
        if not isinstance(channel, discord.TextChannel) or _plain(channel.name) != "annonces":
            continue
        try:
            message = await channel.fetch_message(int(row["message_id"]))
            if message.author.id == (guild.me.id if guild.me else 0):
                if message.embeds and (message.embeds[0].title or "").casefold() == "suivi de sentrix":
                    await message.delete(reason="Retrait du suivi SentriX publié automatiquement")
                    await bot.db.execute(
                        "DELETE FROM bot_tracker_panels WHERE guild_id = ?",
                        (guild.id,),
                    )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    await bot.db.execute(
        "INSERT OR REPLACE INTO sentrix_runtime_migrations (name, applied_at) VALUES (?, ?)",
        (_MIGRATION_KEY, int(time.time())),
    )


def install(bot: commands.Bot) -> None:
    """Installation idempotente par bot afin de rester correcte après un reload."""
    from . import server_builder_ready_setup as ready

    original = ready._ensure_announcements
    if not getattr(original, "_sentrix_no_auto_tracker", False):
        async def ensure_announcements_without_tracker(bot_obj, builder_cog, guild, channel, creator_id):
            # Conserve uniquement la présentation SentriX. Aucun panneau de suivi n'est créé,
            # enregistré ou déplacé automatiquement.
            await builder_cog._publish_once(
                channel,
                "SentriX • Présentation automatique v1",
                ready._bot_ready_embed(guild),
            )
            return "présentation SentriX installée • suivi-bot uniquement sur commande"

        ensure_announcements_without_tracker._sentrix_no_auto_tracker = True
        ready._ensure_announcements = ensure_announcements_without_tracker

    if getattr(bot, "_sentrix_no_auto_tracker_installed", False):
        return
    bot._sentrix_no_auto_tracker_installed = True
    asyncio.create_task(
        _cleanup_previous_automatic_trackers(bot),
        name="sentrix-remove-old-auto-tracker",
    )
    logger.info("Publication automatique de +suivi-bot désactivée ; commande manuelle conservée.")
