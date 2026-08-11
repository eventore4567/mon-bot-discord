"""Panneau de suivi automatique de SentriX."""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands, tasks

from utils import embeds

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


def _member_message(text: str, member: discord.Member) -> str:
    """Résout les variables d'accueil/départ avec une vraie mention Discord.

    ``{member}`` reste la variable historique et ``{user}`` devient un alias simple.
    On accepte aussi les anciens placeholders visuels ``(user)`` et ``[user]`` afin
    qu'un message déjà enregistré n'affiche plus littéralement « user ».
    """
    replacements = (
        ("{member}", member.mention),
        ("{user}", member.mention),
        ("(user)", member.mention),
        ("[user]", member.mention),
        ("<user>", member.mention),
        ("{username}", member.display_name),
        ("{display_name}", member.display_name),
        ("{server}", member.guild.name),
        ("{member_count}", str(member.guild.member_count or 0)),
    )
    value = str(text or "")
    for placeholder, replacement in replacements:
        value = value.replace(placeholder, replacement)
    return value


def _install_member_presence_mentions(bot: commands.Bot) -> None:
    """Rend les messages d'arrivée/départ cohérents et pingue le vrai membre.

    Le handler principal historique envoyait la bienvenue uniquement dans un embed : une
    mention dans un embed n'est pas un ping fiable. Il utilisait aussi ``str(member)`` au
    départ, et ne connaissait pas ``{user}``. On remplace seulement les deux handlers du
    Bot ; les listeners des autres cogs (logs, invites, niveaux...) continuent d'être
    dispatchés normalement par discord.py.
    """
    if getattr(bot, "_sentrix_member_presence_mentions_installed", False):
        return

    bot._sentrix_original_on_member_join = getattr(bot, "on_member_join", None)
    bot._sentrix_original_on_member_remove = getattr(bot, "on_member_remove", None)

    async def on_member_join(member: discord.Member):
        conf = await bot.db.get_guild_config(member.guild.id)
        if not conf:
            return

        if conf["autorole"]:
            role = member.guild.get_role(conf["autorole"])
            if role:
                try:
                    await member.add_roles(role, reason="Rôle automatique à l'arrivée")
                except discord.Forbidden:
                    pass

        if not conf["welcome_channel"]:
            return
        channel = member.guild.get_channel(conf["welcome_channel"])
        if channel is None:
            return

        raw_text = conf["welcome_message"] or "Bienvenue {member} sur **{server}** !"
        text = _member_message(raw_text, member)
        try:
            welcome_embed = embeds.success(text, title=f"Bienvenue {member.display_name}")
            welcome_embed.set_thumbnail(url=member.display_avatar.url)
            if conf["welcome_image_url"]:
                welcome_embed.set_image(url=conf["welcome_image_url"])

            # Le ping est placé dans le contenu du message, pas seulement dans l'embed.
            # AllowedMentions limite strictement la notification à ce membre : un texte
            # personnalisé ne peut donc pas déclencher @everyone ou un rôle par accident.
            ping = None if member.bot else member.mention
            allowed = discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=[] if member.bot else [member],
                replied_user=False,
            )
            await channel.send(content=ping, embed=welcome_embed, allowed_mentions=allowed)
        except discord.HTTPException:
            pass

    async def on_member_remove(member: discord.Member):
        conf = await bot.db.get_guild_config(member.guild.id)
        if not conf or not conf["goodbye_channel"]:
            return
        channel = member.guild.get_channel(conf["goodbye_channel"])
        if channel is None:
            return

        raw_text = conf["goodbye_message"] or "{member} a quitté **{server}**."
        text = _member_message(raw_text, member)
        try:
            # La mention reste réelle/clickable dans le message de départ. Discord ne peut
            # toutefois pas garantir une notification à quelqu'un qui a déjà quitté le
            # serveur au moment où l'événement member_remove est reçu.
            ping = None if member.bot else member.mention
            allowed = discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=[] if member.bot else [member],
                replied_user=False,
            )
            await channel.send(
                content=ping,
                embed=embeds.neutral("Départ", text),
                allowed_mentions=allowed,
            )
        except discord.HTTPException:
            pass

    bot.on_member_join = on_member_join
    bot.on_member_remove = on_member_remove
    bot._sentrix_member_presence_mentions_installed = True
    logger.info("Accueil/départ : vraie mention membre et alias {user} activés.")


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
    _install_member_presence_mentions(bot)
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(BotTracker(bot))
    _INSTALLED = True
    logger.info("Panneau de suivi SentriX activé.")
