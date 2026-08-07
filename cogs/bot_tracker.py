"""Panneau de suivi automatique de SentriX."""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands, tasks

logger = logging.getLogger("bot.tracker")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_tracker_panels (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
)
"""

_INSTALLED = False
_COG_NAME = "BotTracker"


def _duration(seconds: int) -> str:
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}j {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class BotTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.started_at = int(time.time())
        self.refresh_panels.start()

    async def cog_unload(self):
        self.refresh_panels.cancel()

    def build_embed(self, guild: discord.Guild | None = None) -> discord.Embed:
        online = self.bot.is_ready()
        latency = round(self.bot.latency * 1000) if online else None
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        command_count = sum(1 for _ in self.bot.walk_commands())
        uptime = _duration(int(time.time()) - self.started_at)
        now = int(time.time())

        embed = discord.Embed(
            title="Suivi de SentriX",
            description="État automatique du bot et de ses services Discord.",
            color=0x57F287 if online else 0xED4245,
        )
        embed.add_field(name="État", value="● En ligne" if online else "● Indisponible", inline=True)
        embed.add_field(name="Latence", value=f"{latency} ms" if latency is not None else "Indisponible", inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=True)
        embed.add_field(name="Serveurs", value=f"{len(self.bot.guilds):,}".replace(",", " "), inline=True)
        embed.add_field(name="Membres", value=f"{total_members:,}".replace(",", " "), inline=True)
        embed.add_field(name="Commandes", value=str(command_count), inline=True)
        if guild is not None:
            embed.add_field(
                name="Serveur actuel",
                value=f"{guild.name} • {guild.member_count or 0} membre(s)",
                inline=False,
            )
        embed.add_field(name="Dernière actualisation", value=f"<t:{now}:R>", inline=False)
        embed.set_footer(text="SentriX • Suivi automatique • actualisation chaque minute")
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        return embed

    async def _save_panel(self, guild_id: int, channel_id: int, message_id: int, creator_id: int):
        await self.bot.db.execute(
            "INSERT INTO bot_tracker_panels (guild_id, channel_id, message_id, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "channel_id=excluded.channel_id, message_id=excluded.message_id, created_by=excluded.created_by",
            (guild_id, channel_id, message_id, creator_id, int(time.time())),
        )

    @commands.command(
        name="suivi-bot",
        aliases=["suivibot", "bot-tracker", "bot-suivi"],
        help="Créer un panneau de suivi automatique de SentriX.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def suivi_bot(self, ctx: commands.Context):
        row = await self.bot.db.fetchone(
            "SELECT * FROM bot_tracker_panels WHERE guild_id = ?",
            (ctx.guild.id,),
        )
        if row:
            old_channel = ctx.guild.get_channel(int(row["channel_id"]))
            if isinstance(old_channel, discord.TextChannel):
                try:
                    old_message = await old_channel.fetch_message(int(row["message_id"]))
                    if old_channel.id == ctx.channel.id:
                        await old_message.edit(embed=self.build_embed(ctx.guild))
                        return await ctx.send("Le panneau de suivi SentriX a été actualisé.")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        message = await ctx.send(embed=self.build_embed(ctx.guild))
        await self._save_panel(ctx.guild.id, ctx.channel.id, message.id, ctx.author.id)

    @tasks.loop(minutes=1)
    async def refresh_panels(self):
        try:
            rows = await self.bot.db.fetchall("SELECT * FROM bot_tracker_panels")
        except Exception:
            logger.exception("Lecture des panneaux de suivi impossible.")
            return

        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                continue
            channel = guild.get_channel(int(row["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                message = await channel.fetch_message(int(row["message_id"]))
                await message.edit(embed=self.build_embed(guild))
            except discord.NotFound:
                await self.bot.db.execute(
                    "DELETE FROM bot_tracker_panels WHERE guild_id = ?",
                    (guild.id,),
                )
            except (discord.Forbidden, discord.HTTPException):
                continue

    @refresh_panels.before_loop
    async def before_refresh_panels(self):
        await self.bot.wait_until_ready()


async def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    await bot.db.execute(_SCHEMA)
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(BotTracker(bot))
    _INSTALLED = True
    logger.info("Panneau de suivi SentriX activé.")
