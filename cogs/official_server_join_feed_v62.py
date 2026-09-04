"""SentriX V62 — salon serveurs-sentrix en journal d'ajouts uniquement.

Le panneau compteur historique ne doit plus être réécrit au READY, au heartbeat ou lors
d'un retrait de serveur. Le salon ``serveurs-sentrix`` reçoit désormais un nouveau message
uniquement lorsque Discord émet ``on_guild_join`` pour SentriX.

Le statut live reste actualisé normalement dans ``statut-sentrix``.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.official-server-join-feed-v62")

_INSTALLED = False


def _join_embed(bot: commands.Bot) -> discord.Embed:
    guild_count = len(bot.guilds)
    members = sum(int(guild.member_count or 0) for guild in bot.guilds)
    embed = discord.Embed(
        title="✦ Nouveau serveur SentriX",
        description=(
            "Un nouveau serveur vient d'ajouter **SentriX**.\n"
            "Le compteur ci-dessous correspond à l'état global après cet ajout."
        ),
        colour=discord.Color.from_rgb(87, 242, 135),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="🌐 Serveurs", value=f"**{guild_count}**", inline=True)
    embed.add_field(name="👥 Membres desservis", value=f"**{members}**", inline=True)
    embed.add_field(name="📈 Variation", value="**+1 serveur**", inline=True)
    embed.add_field(
        name="🔒 Confidentialité",
        value=(
            "Seuls les totaux sont affichés ici. Le nom et les informations privées "
            "du serveur qui vient d'ajouter SentriX ne sont pas publiés."
        ),
        inline=False,
    )
    if bot.user is not None:
        embed.set_author(name="SentriX", icon_url=bot.user.display_avatar.url)
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(text="SentriX • Nouveau serveur détecté")
    return embed


async def _cleanup_old_counter(runtime) -> None:
    """Supprime uniquement l'ancien panneau fixe généré par SentriX, jamais les events V62."""
    try:
        await runtime.bot.wait_until_ready()
        guild_id = await runtime.official_guild_id()
        guild = runtime.bot.get_guild(guild_id) if guild_id else None
        if guild is None:
            return
        channel = runtime._find_text(guild, "serveurs-sentrix")
        if channel is None:
            return
        async for message in channel.history(limit=50):
            if runtime.bot.user is None or message.author.id != runtime.bot.user.id:
                continue
            titles = {str(embed.title or "").casefold() for embed in message.embeds}
            if any("sentrix sur discord" in title for title in titles):
                try:
                    # discord.py 2.7 peut retourner un PartialMessage ici. Sa méthode
                    # delete() n'accepte pas le paramètre audit-log ``reason``.
                    await message.delete()
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass
    except RuntimeError:
        return
    except Exception:
        logger.exception("V62: nettoyage de l'ancien compteur impossible.")


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    runtime = getattr(bot, "_sentrix_official_server_runtime", None)
    if runtime is None:
        return

    # Le heartbeat et l'ancien on_guild_join/on_guild_remove continuent d'appeler cette
    # méthode. On la réduit donc au SEUL panneau qui doit rester live : statut-sentrix.
    if not getattr(runtime, "_sentrix_join_feed_refresh_v62", False):
        async def refresh_status_only() -> None:
            guild_id = await runtime.official_guild_id()
            if not guild_id:
                return
            guild = bot.get_guild(guild_id)
            if guild is None:
                return
            status_channel = runtime._find_text(guild, "statut-sentrix")
            if status_channel is not None:
                await runtime._upsert_message(status_channel, "live_status", runtime._status_embed())

        runtime.refresh_live_panels = refresh_status_only
        runtime._sentrix_join_feed_refresh_v62 = True

    if not getattr(bot, "_sentrix_join_feed_listener_v62", False):
        async def announce_new_guild(joined_guild: discord.Guild) -> None:
            # Ne publie pas l'ajout du serveur officiel lui-même dans son propre feed.
            official_id = await runtime.official_guild_id()
            if official_id and joined_guild.id == int(official_id):
                return
            official = bot.get_guild(int(official_id)) if official_id else None
            if official is None:
                return
            channel = runtime._find_text(official, "serveurs-sentrix")
            if channel is None:
                return
            try:
                await panels.envoyer(channel, panels.depuis_embed(_join_embed(bot)), allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("V62: annonce d'ajout impossible guild=%s.", joined_guild.id)

        bot.add_listener(announce_new_guild, "on_guild_join")
        bot._sentrix_join_feed_listener_v62 = True

    if not _INSTALLED:
        _INSTALLED = True
        try:
            asyncio.create_task(_cleanup_old_counter(runtime), name="sentrix-v62-clean-old-server-counter")
        except RuntimeError:
            pass
        logger.info("V62: serveurs-sentrix publie uniquement lors d'un nouvel ajout.")


__all__ = ["install"]
