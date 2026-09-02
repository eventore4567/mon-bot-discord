"""Fonctions SentriX Plus : starboard, vocaux temporaires, sticky, annonces planifiées et diagnostic serveur.

Cette extension est volontairement isolée : elle n'altère aucun moteur global de commandes,
aucun transport Discord et aucune couche de style existante.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import discord

from utils import embeds
from discord.ext import commands, tasks

logger = logging.getLogger("bot.sentrix-plus")

STAR_EMOJI = "⭐"
VOICE_CATEGORY_NAME = "SENTRIX — VOCAUX"
VOICE_LOBBY_NAME = "➕・Créer ton vocal"
MAX_SCHEDULE_SECONDS = 30 * 24 * 3600
MIN_SCHEDULE_SECONDS = 60
_DELAY_RE = re.compile(r"^(\d+)(s|m|h|d|w)$", re.I)


def _parse_delay(value: str) -> int | None:
    match = _DELAY_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    factor = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    seconds = amount * factor
    if seconds < MIN_SCHEDULE_SECONDS or seconds > MAX_SCHEDULE_SECONDS:
        return None
    return seconds


def _human_delay(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 86400:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days} j {hours} h" if hours else f"{days} j"
    if seconds >= 3600:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    minutes = max(1, seconds // 60)
    return f"{minutes} min"



def _reponse(titre: str, description: str, *, kind: str = "brand") -> discord.Embed:
    """Reponse SentriX Plus au format canonique.

    Ce module repondait en texte brut : ses 17 commandes etaient les seules du bot
    a ne porter ni couleur d'intention, ni pied de page, ni barre d'identite.
    """
    return embeds._base(titre, description, kind=kind)


class SentriXPlus(commands.Cog, name="SentriXPlus"):
    def __init__(self, bot: commands.Bot):
        # Cache negatif : la plupart des salons n'ont aucun sticky.
        self._no_sticky: dict[int, bool] = {}
        self.bot = bot
        self._sticky_cooldowns: dict[int, float] = {}

    async def cog_load(self) -> None:
        await self._ensure_tables()
        if not self.scheduled_worker.is_running():
            self.scheduled_worker.start()
        try:
            from . import utility
            utility.CATEGORY_LABELS.setdefault("SentriXPlus", "Extensions SentriX")
        except Exception:
            logger.debug("Impossible d'ajouter SentriXPlus à l'aide.", exc_info=True)

    async def cog_unload(self) -> None:
        if self.scheduled_worker.is_running():
            self.scheduled_worker.cancel()

    async def _ensure_tables(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS sentrix_starboard_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                threshold INTEGER NOT NULL DEFAULT 3
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sentrix_starboard_items (
                source_message_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                source_channel_id INTEGER NOT NULL,
                starboard_message_id INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sentrix_voicehub_config (
                guild_id INTEGER PRIMARY KEY,
                lobby_channel_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sentrix_temp_voice (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sentrix_sticky (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                message_id INTEGER,
                every_messages INTEGER NOT NULL DEFAULT 5,
                counter INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sentrix_scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                due_at INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
            """,
        ]
        for statement in statements:
            await self.bot.db.execute(statement)

    # ------------------------------------------------------------------
    # STARBOARD
    # ------------------------------------------------------------------

    @commands.command(name="starboard-setup", aliases=["starboardsetup"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def starboard_setup(self, ctx: commands.Context, channel: discord.TextChannel, threshold: int = 3):
        """Configure le Starboard : +starboard-setup #best-of 3"""
        threshold = max(2, min(25, int(threshold)))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO sentrix_starboard_config(guild_id,channel_id,threshold) VALUES(?,?,?)",
            (ctx.guild.id, channel.id, threshold),
        )
        await ctx.send(embed=_reponse("Starboard", f'Starboard activé dans {channel.mention}. Un message y apparaîtra à partir de {threshold} réactions {STAR_EMOJI}.', kind="success"))

    @commands.command(name="starboard-off")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def starboard_off(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM sentrix_starboard_config WHERE guild_id=?", (ctx.guild.id,))
        await ctx.send(embed=_reponse("Starboard", 'Starboard désactivé sur ce serveur.', kind="success"))

    async def _refresh_starboard(self, guild_id: int | None, channel_id: int, message_id: int, emoji: str) -> None:
        if guild_id is None or emoji != STAR_EMOJI:
            return
        config = await self.bot.db.fetchone(
            "SELECT channel_id,threshold FROM sentrix_starboard_config WHERE guild_id=?",
            (guild_id,),
        )
        if not config or int(config["channel_id"]) == int(channel_id):
            return

        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return
        source_channel = guild.get_channel(int(channel_id))
        board_channel = guild.get_channel(int(config["channel_id"]))
        if not isinstance(source_channel, (discord.TextChannel, discord.Thread)):
            return
        if not isinstance(board_channel, discord.TextChannel):
            return

        try:
            message = await source_channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

        count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == STAR_EMOJI:
                count = int(reaction.count)
                break

        existing = await self.bot.db.fetchone(
            "SELECT starboard_message_id FROM sentrix_starboard_items WHERE source_message_id=?",
            (message.id,),
        )
        threshold = int(config["threshold"])

        if count < threshold:
            if existing:
                try:
                    board_message = await board_channel.fetch_message(int(existing["starboard_message_id"]))
                    await board_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                await self.bot.db.execute(
                    "DELETE FROM sentrix_starboard_items WHERE source_message_id=?",
                    (message.id,),
                )
            return

        embed = discord.Embed(
            description=(message.content[:3500] if message.content else "Message sans texte."),
            colour=discord.Colour.gold(),
            timestamp=message.created_at,
        )
        embed.set_author(
            name=getattr(message.author, "display_name", str(message.author)),
            icon_url=message.author.display_avatar.url,
        )
        embed.add_field(name="Message", value=f"[Ouvrir le message]({message.jump_url})", inline=False)
        embed.set_footer(text=f"{count} étoile(s) • #{getattr(source_channel, 'name', 'salon')}")

        for attachment in message.attachments:
            if str(attachment.content_type or "").startswith("image/"):
                embed.set_image(url=attachment.url)
                break

        content = f"{STAR_EMOJI} **{count}** • {source_channel.mention}"
        if existing:
            try:
                board_message = await board_channel.fetch_message(int(existing["starboard_message_id"]))
                await board_message.edit(content=content, embed=embed)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await self.bot.db.execute(
                    "DELETE FROM sentrix_starboard_items WHERE source_message_id=?",
                    (message.id,),
                )

        try:
            sent = await board_channel.send(content, embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            return
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO sentrix_starboard_items(source_message_id,guild_id,source_channel_id,starboard_message_id) VALUES(?,?,?,?)",
            (message.id, guild.id, source_channel.id, sent.id),
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._refresh_starboard(payload.guild_id, payload.channel_id, payload.message_id, str(payload.emoji))

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._refresh_starboard(payload.guild_id, payload.channel_id, payload.message_id, str(payload.emoji))

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        row = await self.bot.db.fetchone(
            "SELECT guild_id,starboard_message_id FROM sentrix_starboard_items WHERE source_message_id=?",
            (payload.message_id,),
        )
        if not row:
            return
        config = await self.bot.db.fetchone(
            "SELECT channel_id FROM sentrix_starboard_config WHERE guild_id=?",
            (row["guild_id"],),
        )
        if config:
            guild = self.bot.get_guild(int(row["guild_id"]))
            channel = guild.get_channel(int(config["channel_id"])) if guild else None
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(int(row["starboard_message_id"]))
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
        await self.bot.db.execute(
            "DELETE FROM sentrix_starboard_items WHERE source_message_id=?",
            (payload.message_id,),
        )

    # ------------------------------------------------------------------
    # VOICE HUB
    # ------------------------------------------------------------------

    @commands.command(name="voicehub-setup")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def voicehub_setup(self, ctx: commands.Context):
        """Crée un salon vocal qui génère automatiquement des vocaux privés."""
        guild = ctx.guild
        me = guild.me
        if me is None or not me.guild_permissions.manage_channels or not me.guild_permissions.move_members:
            return await ctx.send(embed=_reponse("VoiceHub", 'SentriX a besoin de Gérer les salons et Déplacer des membres pour activer VoiceHub.', kind="danger"))

        category = discord.utils.get(guild.categories, name=VOICE_CATEGORY_NAME)
        if category is None:
            category = await guild.create_category(VOICE_CATEGORY_NAME, reason="SentriX VoiceHub")

        lobby = discord.utils.get(category.voice_channels, name=VOICE_LOBBY_NAME)
        if lobby is None:
            lobby = await guild.create_voice_channel(VOICE_LOBBY_NAME, category=category, reason="SentriX VoiceHub")

        await self.bot.db.execute(
            "INSERT OR REPLACE INTO sentrix_voicehub_config(guild_id,lobby_channel_id,category_id) VALUES(?,?,?)",
            (guild.id, lobby.id, category.id),
        )
        await ctx.send(embed=_reponse("VoiceHub", f'VoiceHub activé : rejoignez {lobby.mention} pour créer automatiquement votre propre salon vocal.', kind="success"))

    @commands.command(name="voicehub-off")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def voicehub_off(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM sentrix_voicehub_config WHERE guild_id=?", (ctx.guild.id,))
        await ctx.send(embed=_reponse("VoiceHub", "VoiceHub désactivé. Les vocaux temporaires existants restent actifs jusqu'à ce qu'ils soient vides.", kind="success"))

    async def _owned_voice(self, ctx: commands.Context) -> tuple[discord.VoiceChannel | None, Any | None]:
        voice = getattr(ctx.author, "voice", None)
        channel = getattr(voice, "channel", None)
        if not isinstance(channel, discord.VoiceChannel):
            return None, None
        row = await self.bot.db.fetchone(
            "SELECT owner_id FROM sentrix_temp_voice WHERE channel_id=?",
            (channel.id,),
        )
        if not row or int(row["owner_id"]) != int(ctx.author.id):
            return channel, None
        return channel, row

    @commands.command(name="voice-name")
    @commands.guild_only()
    async def voice_name(self, ctx: commands.Context, *, name: str):
        channel, row = await self._owned_voice(ctx)
        if channel is None or row is None:
            return await ctx.send(embed=_reponse("Salon vocal", "Vous devez être propriétaire d'un vocal temporaire SentriX.", kind="danger"))
        name = str(name).strip()[:90]
        if len(name) < 2:
            return await ctx.send(embed=_reponse("Salon vocal", 'Choisissez un nom de salon plus long.', kind="danger"))
        await channel.edit(name=name, reason=f"VoiceHub : renommage par {ctx.author}")
        await ctx.send(embed=_reponse("Salon vocal", f"Votre vocal s'appelle maintenant « {name} ».", kind="success"))

    @commands.command(name="voice-limit")
    @commands.guild_only()
    async def voice_limit(self, ctx: commands.Context, limit: int):
        channel, row = await self._owned_voice(ctx)
        if channel is None or row is None:
            return await ctx.send(embed=_reponse("Salon vocal", "Vous devez être propriétaire d'un vocal temporaire SentriX.", kind="danger"))
        if limit < 0 or limit > 99:
            return await ctx.send(embed=_reponse("Salon vocal", 'La limite doit être comprise entre 0 et 99. 0 signifie illimité.', kind="danger"))
        await channel.edit(user_limit=limit, reason=f"VoiceHub : limite par {ctx.author}")
        await ctx.send(embed=_reponse("Salon vocal", f"Limite du vocal : {('illimitée' if limit == 0 else limit)}.", kind="success"))

    @commands.command(name="voice-lock")
    @commands.guild_only()
    async def voice_lock(self, ctx: commands.Context):
        channel, row = await self._owned_voice(ctx)
        if channel is None or row is None:
            return await ctx.send(embed=_reponse("Salon vocal", "Vous devez être propriétaire d'un vocal temporaire SentriX.", kind="danger"))
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.connect = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason="VoiceHub : verrouillage")
        owner_overwrite = channel.overwrites_for(ctx.author)
        owner_overwrite.connect = True
        owner_overwrite.manage_channels = True
        owner_overwrite.move_members = True
        await channel.set_permissions(ctx.author, overwrite=owner_overwrite, reason="VoiceHub : propriétaire")
        await ctx.send(embed=_reponse("Salon vocal", 'Votre vocal est maintenant verrouillé.', kind="success"))

    @commands.command(name="voice-unlock")
    @commands.guild_only()
    async def voice_unlock(self, ctx: commands.Context):
        channel, row = await self._owned_voice(ctx)
        if channel is None or row is None:
            return await ctx.send(embed=_reponse("Salon vocal", "Vous devez être propriétaire d'un vocal temporaire SentriX.", kind="danger"))
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.connect = None
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason="VoiceHub : déverrouillage")
        await ctx.send(embed=_reponse("Salon vocal", 'Votre vocal est de nouveau ouvert.', kind="success"))

    @commands.command(name="voice-transfer")
    @commands.guild_only()
    async def voice_transfer(self, ctx: commands.Context, member: discord.Member):
        channel, row = await self._owned_voice(ctx)
        if channel is None or row is None:
            return await ctx.send(embed=_reponse("Salon vocal", "Vous devez être propriétaire d'un vocal temporaire SentriX.", kind="danger"))
        if member.bot or member not in channel.members:
            return await ctx.send(embed=_reponse("Salon vocal", 'Le nouveau propriétaire doit être un membre présent dans votre vocal.', kind="danger"))
        await self.bot.db.execute(
            "UPDATE sentrix_temp_voice SET owner_id=? WHERE channel_id=?",
            (member.id, channel.id),
        )
        old_overwrite = channel.overwrites_for(ctx.author)
        old_overwrite.manage_channels = None
        old_overwrite.move_members = None
        await channel.set_permissions(ctx.author, overwrite=old_overwrite, reason="VoiceHub : transfert")
        new_overwrite = channel.overwrites_for(member)
        new_overwrite.connect = True
        new_overwrite.manage_channels = True
        new_overwrite.move_members = True
        await channel.set_permissions(member, overwrite=new_overwrite, reason="VoiceHub : nouveau propriétaire")
        # La mention etait dans le texte du message et notifiait donc le nouveau
        # proprietaire. Une mention placee dans un embed ne notifie personne : on la
        # garde dans le contenu pour ne pas perdre l'avertissement.
        await ctx.send(
            content=member.mention,
            embed=_reponse("Salon vocal", f"{member.mention} est maintenant propriétaire du vocal.", kind="success"),
            allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False),
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return

        if after.channel is not None:
            config = await self.bot.db.fetchone(
                "SELECT lobby_channel_id,category_id FROM sentrix_voicehub_config WHERE guild_id=?",
                (member.guild.id,),
            )
            if config and int(config["lobby_channel_id"]) == int(after.channel.id):
                existing = await self.bot.db.fetchone(
                    "SELECT channel_id FROM sentrix_temp_voice WHERE guild_id=? AND owner_id=?",
                    (member.guild.id, member.id),
                )
                if existing:
                    current = member.guild.get_channel(int(existing["channel_id"]))
                    if isinstance(current, discord.VoiceChannel):
                        try:
                            await member.move_to(current)
                            return
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                    await self.bot.db.execute(
                        "DELETE FROM sentrix_temp_voice WHERE channel_id=?",
                        (existing["channel_id"],),
                    )

                category = member.guild.get_channel(int(config["category_id"]))
                if not isinstance(category, discord.CategoryChannel):
                    return
                try:
                    channel = await member.guild.create_voice_channel(
                        f"{member.display_name} • vocal"[:100],
                        category=category,
                        reason="SentriX VoiceHub",
                    )
                    owner_overwrite = channel.overwrites_for(member)
                    owner_overwrite.connect = True
                    owner_overwrite.manage_channels = True
                    owner_overwrite.move_members = True
                    await channel.set_permissions(member, overwrite=owner_overwrite, reason="SentriX VoiceHub")
                    await self.bot.db.execute(
                        "INSERT OR REPLACE INTO sentrix_temp_voice(channel_id,guild_id,owner_id) VALUES(?,?,?)",
                        (channel.id, member.guild.id, member.id),
                    )
                    await member.move_to(channel)
                except (discord.Forbidden, discord.HTTPException):
                    logger.warning("Création VoiceHub impossible dans %s", member.guild.id, exc_info=True)

        if before.channel is not None:
            row = await self.bot.db.fetchone(
                "SELECT channel_id FROM sentrix_temp_voice WHERE channel_id=?",
                (before.channel.id,),
            )
            if row and len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="SentriX VoiceHub : salon vide")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                await self.bot.db.execute(
                    "DELETE FROM sentrix_temp_voice WHERE channel_id=?",
                    (before.channel.id,),
                )

    # ------------------------------------------------------------------
    # STICKY MESSAGES
    # ------------------------------------------------------------------

    @commands.command(name="sticky-set")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_messages=True)
    async def sticky_set(self, ctx: commands.Context, channel: discord.TextChannel, *, message: str):
        """Crée un message sticky : +sticky-set #annonces texte"""
        content = str(message).strip()
        if not content or len(content) > 1700:
            return await ctx.send(embed=_reponse("Message sticky", 'Le message sticky doit contenir entre 1 et 1700 caractères.', kind="danger"))
        old = await self.bot.db.fetchone("SELECT message_id FROM sentrix_sticky WHERE channel_id=?", (channel.id,))
        if old and old["message_id"]:
            try:
                previous = await channel.fetch_message(int(old["message_id"]))
                await previous.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        sent = await channel.send(f"📌 **Information**\n{content}")
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO sentrix_sticky(channel_id,guild_id,content,message_id,every_messages,counter) VALUES(?,?,?,?,5,0)",
            (channel.id, ctx.guild.id, content, sent.id),
        )
        self._no_sticky.pop(int(channel.id), None)
        await ctx.send(embed=_reponse("Message sticky", f'Message sticky activé dans {channel.mention}. Il remontera automatiquement tous les 5 messages.', kind="success"))

    @commands.command(name="sticky-every")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_messages=True)
    async def sticky_every(self, ctx: commands.Context, channel: discord.TextChannel, every: int):
        every = max(2, min(50, int(every)))
        row = await self.bot.db.fetchone("SELECT channel_id FROM sentrix_sticky WHERE channel_id=?", (channel.id,))
        if not row:
            return await ctx.send(embed=_reponse("Message sticky", "Aucun sticky n'est configuré dans ce salon.", kind="warning"))
        await self.bot.db.execute(
            "UPDATE sentrix_sticky SET every_messages=?,counter=0 WHERE channel_id=?",
            (every, channel.id),
        )
        await ctx.send(embed=_reponse("Message sticky", f'Le sticky de {channel.mention} remontera maintenant tous les {every} messages.', kind="success"))

    @commands.command(name="sticky-off")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_messages=True)
    async def sticky_off(self, ctx: commands.Context, channel: discord.TextChannel):
        row = await self.bot.db.fetchone("SELECT message_id FROM sentrix_sticky WHERE channel_id=?", (channel.id,))
        if row and row["message_id"]:
            try:
                previous = await channel.fetch_message(int(row["message_id"]))
                await previous.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        await self.bot.db.execute("DELETE FROM sentrix_sticky WHERE channel_id=?", (channel.id,))
        self._no_sticky[int(channel.id)] = True
        await ctx.send(embed=_reponse("Message sticky", f'Sticky désactivé dans {channel.mention}.', kind="success"))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot:
            return
        # Cache NEGATIF : un sticky n'existe que dans quelques salons. Sans ce cache,
        # CHAQUE message de CHAQUE salon interrogeait la table. Seul le cas « aucun
        # sticky ici » est cache ; des qu'un sticky existe on relit a chaque fois, car
        # le compteur doit rester exact.
        channel_id = int(message.channel.id)
        if self._no_sticky.get(channel_id) is True:
            return
        row = await self.bot.db.fetchone(
            "SELECT content,message_id,every_messages,counter FROM sentrix_sticky WHERE channel_id=?",
            (channel_id,),
        )
        if not row:
            # Borne memoire : ce cache est indexe par SALON, pas par serveur. Sur un bot
            # present sur beaucoup de serveurs il grossirait sans limite.
            if len(self._no_sticky) > 20000:
                self._no_sticky.clear()
            self._no_sticky[channel_id] = True
            return
        if row["message_id"] and int(row["message_id"]) == int(message.id):
            return

        counter = int(row["counter"]) + 1
        every = max(2, int(row["every_messages"]))
        if counter < every:
            await self.bot.db.execute(
                "UPDATE sentrix_sticky SET counter=? WHERE channel_id=?",
                (counter, message.channel.id),
            )
            return

        now = time.monotonic()
        if now - self._sticky_cooldowns.get(message.channel.id, 0.0) < 8.0:
            return
        self._sticky_cooldowns[message.channel.id] = now

        if row["message_id"]:
            try:
                previous = await message.channel.fetch_message(int(row["message_id"]))
                await previous.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        try:
            sticky = await message.channel.send(f"📌 **Information**\n{row['content']}")
        except (discord.Forbidden, discord.HTTPException):
            return
        await self.bot.db.execute(
            "UPDATE sentrix_sticky SET message_id=?,counter=0 WHERE channel_id=?",
            (sticky.id, message.channel.id),
        )

    # ------------------------------------------------------------------
    # SCHEDULED ANNOUNCEMENTS
    # ------------------------------------------------------------------

    @commands.command(name="schedule-send")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_messages=True)
    async def schedule_send(self, ctx: commands.Context, delay: str, channel: discord.TextChannel, *, message: str):
        seconds = _parse_delay(delay)
        if seconds is None:
            return await ctx.send(embed=_reponse("Annonce programmée", 'Durée invalide. Exemples : 10m, 2h, 1d. Minimum 1 minute, maximum 30 jours.', kind="danger"))
        content = str(message).strip()
        if not content or len(content) > 1900:
            return await ctx.send(embed=_reponse("Annonce programmée", 'Le message planifié doit contenir entre 1 et 1900 caractères.', kind="danger"))
        now_ts = int(time.time())
        due_at = now_ts + seconds
        await self.bot.db.execute(
            "INSERT INTO sentrix_scheduled_messages(guild_id,channel_id,author_id,due_at,content,created_at,status) VALUES(?,?,?,?,?,?,'pending')",
            (ctx.guild.id, channel.id, ctx.author.id, due_at, content, now_ts),
        )
        row = await self.bot.db.fetchone(
            "SELECT id FROM sentrix_scheduled_messages WHERE guild_id=? AND author_id=? AND created_at=? ORDER BY id DESC LIMIT 1",
            (ctx.guild.id, ctx.author.id, now_ts),
        )
        ident = int(row["id"]) if row else 0
        await ctx.send(embed=_reponse("Annonce programmée", f'Annonce #{ident} programmée dans {channel.mention} dans {_human_delay(seconds)}.', kind="success"))

    @commands.command(name="schedule-list")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_messages=True)
    async def schedule_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT id,channel_id,due_at,content FROM sentrix_scheduled_messages WHERE guild_id=? AND status='pending' ORDER BY due_at ASC LIMIT 15",
            (ctx.guild.id,),
        )
        if not rows:
            return await ctx.send(embed=_reponse("Annonces programmées", 'Aucune annonce programmée.', kind="warning"))
        now_ts = int(time.time())
        lines = []
        for row in rows:
            channel = ctx.guild.get_channel(int(row["channel_id"]))
            destination = channel.mention if isinstance(channel, discord.TextChannel) else f"salon {row['channel_id']}"
            preview = str(row["content"]).replace("\n", " ")[:70]
            lines.append(f"#{row['id']} • {destination} • dans {_human_delay(int(row['due_at']) - now_ts)} • {preview}")
        await ctx.send(embed=_reponse("Annonces programmées", 'Annonces programmées :\n' + '\n'.join(lines), kind="brand"))

    @commands.command(name="schedule-cancel")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_messages=True)
    async def schedule_cancel(self, ctx: commands.Context, ident: int):
        row = await self.bot.db.fetchone(
            "SELECT id FROM sentrix_scheduled_messages WHERE id=? AND guild_id=? AND status='pending'",
            (ident, ctx.guild.id),
        )
        if not row:
            return await ctx.send(embed=_reponse("Annonce programmée", 'Annonce programmée introuvable.', kind="warning"))
        await self.bot.db.execute(
            "DELETE FROM sentrix_scheduled_messages WHERE id=? AND guild_id=?",
            (ident, ctx.guild.id),
        )
        await ctx.send(embed=_reponse("Annonce programmée", f'Annonce #{ident} annulée.', kind="success"))

    @tasks.loop(seconds=15)
    async def scheduled_worker(self):
        now_ts = int(time.time())
        rows = await self.bot.db.fetchall(
            "SELECT id,guild_id,channel_id,author_id,content FROM sentrix_scheduled_messages WHERE status='pending' AND due_at<=? ORDER BY due_at ASC LIMIT 25",
            (now_ts,),
        )
        for row in rows:
            ident = int(row["id"])
            await self.bot.db.execute(
                "UPDATE sentrix_scheduled_messages SET status='sending' WHERE id=? AND status='pending'",
                (ident,),
            )
            check = await self.bot.db.fetchone(
                "SELECT status FROM sentrix_scheduled_messages WHERE id=?",
                (ident,),
            )
            if not check or check["status"] != "sending":
                continue
            channel = self.bot.get_channel(int(row["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                await self.bot.db.execute(
                    "UPDATE sentrix_scheduled_messages SET status='failed' WHERE id=?",
                    (ident,),
                )
                continue
            try:
                await channel.send(
                    str(row["content"]),
                    allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True),
                )
            except (discord.Forbidden, discord.HTTPException):
                await self.bot.db.execute(
                    "UPDATE sentrix_scheduled_messages SET status='failed' WHERE id=?",
                    (ident,),
                )
                continue
            await self.bot.db.execute("DELETE FROM sentrix_scheduled_messages WHERE id=?", (ident,))

    @scheduled_worker.before_loop
    async def before_scheduled_worker(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # SERVER HEALTH
    # ------------------------------------------------------------------

    @commands.command(name="server-health", aliases=["serverhealth"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def server_health(self, ctx: commands.Context):
        guild = ctx.guild
        me = guild.me
        if me is None:
            return await ctx.send(embed=_reponse("Diagnostic du serveur", 'Impossible de lire les permissions de SentriX sur ce serveur.', kind="danger"))

        permission_checks = {
            "Gérer les salons": me.guild_permissions.manage_channels,
            "Gérer les rôles": me.guild_permissions.manage_roles,
            "Gérer les messages": me.guild_permissions.manage_messages,
            "Modérer les membres": me.guild_permissions.moderate_members,
            "Bannir": me.guild_permissions.ban_members,
            "Expulser": me.guild_permissions.kick_members,
            "Voir l'audit log": me.guild_permissions.view_audit_log,
            "Déplacer en vocal": me.guild_permissions.move_members,
        }
        passed = sum(1 for value in permission_checks.values() if value)
        total = len(permission_checks)
        score = round((passed / total) * 100)

        starboard = await self.bot.db.fetchone(
            "SELECT channel_id FROM sentrix_starboard_config WHERE guild_id=?",
            (guild.id,),
        )
        voicehub = await self.bot.db.fetchone(
            "SELECT lobby_channel_id FROM sentrix_voicehub_config WHERE guild_id=?",
            (guild.id,),
        )
        sticky_count_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM sentrix_sticky WHERE guild_id=?",
            (guild.id,),
        )
        scheduled_count_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM sentrix_scheduled_messages WHERE guild_id=? AND status='pending'",
            (guild.id,),
        )

        missing = [name for name, enabled in permission_checks.items() if not enabled]
        security = str(getattr(guild.verification_level, "name", guild.verification_level)).replace("_", " ")
        sticky_count = int(sticky_count_row["n"] if sticky_count_row else 0)
        scheduled_count = int(scheduled_count_row["n"] if scheduled_count_row else 0)

        lines = [
            f"Santé SentriX : {score}%",
            f"Permissions essentielles : {passed}/{total}",
            f"Vérification Discord : {security}",
            f"Starboard : {'actif' if starboard else 'non configuré'}",
            f"VoiceHub : {'actif' if voicehub else 'non configuré'}",
            f"Stickies actifs : {sticky_count}",
            f"Annonces programmées : {scheduled_count}",
        ]
        if missing:
            lines.append("Permissions manquantes : " + ", ".join(missing[:5]))
        else:
            lines.append("Aucune permission essentielle manquante.")
        await ctx.send(embed=_reponse("Diagnostic du serveur", '\n'.join(lines), kind="brand"))

    @commands.command(name="sentrix-plus", aliases=["plus-features", "newfeatures"])
    @commands.guild_only()
    async def sentrix_plus(self, ctx: commands.Context):
        await ctx.send(embed=_reponse("SentriX Plus", 'Nouveautés SentriX Plus :\n• Starboard : +starboard-setup #salon 3\n• VoiceHub : +voicehub-setup, puis +voice-name / +voice-limit / +voice-lock\n• Sticky : +sticky-set #salon message\n• Annonces programmées : +schedule-send 2h #annonces message\n• Diagnostic : +server-health', kind="brand"))


async def setup(bot: commands.Bot):
    await bot.add_cog(SentriXPlus(bot))
