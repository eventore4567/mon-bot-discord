"""Bot V12 — suivi SLA des tickets SentriX utilisant le statut français `ouvert`."""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands, tasks

logger = logging.getLogger("bot.v12-ticket-sla")
CHECK_SECONDS = 120
UNCLAIMED_SECONDS = 15 * 60
REMINDER_COOLDOWN = 30 * 60


class BotV12TicketSLA(commands.Cog, name="BotV12TicketSLA"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        if not self.ticket_watch_loop.is_running():
            self.ticket_watch_loop.start()

    def cog_unload(self) -> None:
        self.ticket_watch_loop.cancel()

    @tasks.loop(seconds=CHECK_SECONDS)
    async def ticket_watch_loop(self) -> None:
        try:
            rows = await self.bot.db.fetchall(
                "SELECT id,guild_id,channel_id,claimed_by,status,created_at "
                "FROM tickets WHERE status='ouvert' ORDER BY created_at ASC LIMIT 500"
            )
        except Exception:
            logger.debug("V12 ticket SLA: lecture tickets indisponible.", exc_info=True)
            return

        now_ts = int(time.time())
        for row in rows:
            try:
                ticket_id = int(row["id"] or 0)
                guild_id = int(row["guild_id"] or 0)
                channel_id = int(row["channel_id"] or 0)
                claimed_by = row["claimed_by"]
                created_at = int(row["created_at"] or now_ts)
            except (KeyError, TypeError, ValueError):
                continue
            if not ticket_id or not guild_id or not channel_id:
                continue

            guild = self.bot.get_guild(guild_id)
            channel = guild.get_channel(channel_id) if guild else None
            if channel is None or claimed_by or now_ts - created_at < UNCLAIMED_SECONDS:
                continue

            try:
                watch = await self.bot.db.fetchone(
                    "SELECT last_reminder_at FROM v12_ticket_watch WHERE ticket_id=?",
                    (ticket_id,),
                )
                last_reminder = int(watch["last_reminder_at"] or 0) if watch else 0
            except Exception:
                last_reminder = 0
            if now_ts - last_reminder < REMINDER_COOLDOWN:
                continue

            try:
                await channel.send(
                    embed=discord.Embed(
                        title="Ticket en attente",
                        description=(
                            "Ce ticket est toujours **non pris en charge** depuis plus de 15 minutes. "
                            "Un membre du staff peut le claim dès qu'il est disponible."
                        ),
                        color=discord.Color.orange(),
                    ),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await self.bot.db.execute(
                    "INSERT INTO v12_ticket_watch "
                    "(ticket_id,guild_id,channel_id,last_reminder_at,last_seen_at) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(ticket_id) DO UPDATE SET guild_id=excluded.guild_id,"
                    "channel_id=excluded.channel_id,last_reminder_at=excluded.last_reminder_at,"
                    "last_seen_at=excluded.last_seen_at",
                    (ticket_id, guild_id, channel_id, now_ts, now_ts),
                )
            except Exception:
                logger.debug("V12 ticket SLA: rappel non envoyé ticket=%s", ticket_id, exc_info=True)

    @ticket_watch_loop.before_loop
    async def before_ticket_watch_loop(self) -> None:
        await self.bot.wait_until_ready()

    @ticket_watch_loop.error
    async def ticket_watch_error(self, error: Exception) -> None:
        logger.warning(
            "V12 ticket SLA: boucle interrompue.",
            exc_info=(type(error), error, error.__traceback__),
        )


async def setup(bot: commands.Bot) -> None:
    if bot.get_cog("BotV12TicketSLA") is None:
        await bot.add_cog(BotV12TicketSLA(bot))
