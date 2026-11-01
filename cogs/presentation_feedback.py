"""Public feedback form for the SentriX presentation panel.

The button is persistent across restarts. Only a user who opens the form
explicitly sends an opinion to the verified primary creator.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

from database.db import PRIMARY_CREATOR_ID

logger = logging.getLogger("bot.presentation-feedback")
BUTTON_ID = "sentrix:presentation:feedback:v1"
COOLDOWN_SECONDS = 900
FEEDBACK_LOCKS: dict[tuple[int, int], asyncio.Lock] = {}


async def ensure_schema(bot: commands.Bot) -> None:
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS sentrix_presentation_feedback ("
        "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, sent_at INTEGER NOT NULL, "
        "PRIMARY KEY(guild_id,user_id))"
    )
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS sentrix_presentation_posts ("
        "guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
        "message_id INTEGER NOT NULL, PRIMARY KEY(guild_id,channel_id))"
    )


class FeedbackModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, english: bool):
        super().__init__(
            title="Send feedback about SentriX" if english else "Votre avis sur SentriX",
            timeout=300,
        )
        self.bot = bot
        self.english = english
        self.feedback = discord.ui.TextInput(
            label="Your feedback" if english else "Votre avis",
            placeholder="What would you like us to improve?" if english
                        else "Que devrions-nous améliorer ?",
            style=discord.TextStyle.paragraph,
            min_length=10,
            max_length=1200,
            required=True,
        )
        self.add_item(self.feedback)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Send your feedback from a server." if self.english
                else "Envoyez votre avis depuis un serveur.",
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        key = (interaction.guild.id, interaction.user.id)
        lock = FEEDBACK_LOCKS.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                row = await self.bot.db.fetchone(
                    "SELECT sent_at FROM sentrix_presentation_feedback "
                    "WHERE guild_id=? AND user_id=?",
                    key,
                )
            except Exception:
                logger.exception("Feedback rate-limit lookup failed")
                return await interaction.followup.send(
                    "Feedback is unavailable right now." if self.english
                    else "Les avis sont indisponibles pour le moment.",
                    ephemeral=True,
                )
            elapsed = int(time.time()) - int(row["sent_at"] or 0) if row else COOLDOWN_SECONDS
            if elapsed < COOLDOWN_SECONDS:
                minutes = max(1, (COOLDOWN_SECONDS - elapsed + 59) // 60)
                return await interaction.followup.send(
                    f"Try again in {minutes} minute(s)." if self.english
                    else f"Vous pourrez donner un nouvel avis dans {minutes} minute(s).",
                    ephemeral=True,
                )

            content = str(self.feedback.value).strip()
            if len(content) < 10:
                return await interaction.followup.send(
                    "Please write at least 10 characters." if self.english
                    else "Veuillez écrire au moins 10 caractères.",
                    ephemeral=True,
                )
            message = discord.Embed(
                title="SentriX · Nouvel avis",
                description=discord.utils.escape_markdown(content),
                colour=discord.Colour.blurple(),
                timestamp=discord.utils.utcnow(),
            )
            message.add_field(
                name="Auteur",
                value=f"{discord.utils.escape_markdown(interaction.user.display_name)} (ID : {interaction.user.id})",
                inline=False,
            )
            message.add_field(
                name="Serveur",
                value=f"{discord.utils.escape_markdown(interaction.guild.name)} (ID : {interaction.guild.id})",
                inline=False,
            )
            try:
                creator = self.bot.get_user(PRIMARY_CREATOR_ID)
                if creator is None:
                    creator = await self.bot.fetch_user(PRIMARY_CREATOR_ID)
                await creator.send(embed=message, allowed_mentions=discord.AllowedMentions.none())
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logger.warning("Presentation feedback DM failed: guild=%s", interaction.guild.id)
                return await interaction.followup.send(
                    "Could not deliver your feedback. Try again later." if self.english
                    else "Votre avis n'a pas pu être transmis. Réessayez plus tard.",
                    ephemeral=True,
                )
            try:
                await self.bot.db.execute(
                    "INSERT INTO sentrix_presentation_feedback (guild_id,user_id,sent_at) "
                    "VALUES (?,?,?) ON CONFLICT(guild_id,user_id) "
                    "DO UPDATE SET sent_at=excluded.sent_at",
                    (interaction.guild.id, interaction.user.id, int(time.time())),
                )
            except Exception:
                logger.exception("Failed to store sent feedback timestamp")
            await interaction.followup.send(
                "Thank you! Your feedback was sent privately to the creator."
                if self.english else
                "Merci ! Votre avis a été envoyé en privé au créateur de SentriX.",
                ephemeral=True,
            )


class FeedbackButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, english: bool = False):
        super().__init__(
            custom_id=BUTTON_ID,
            style=discord.ButtonStyle.secondary,
            label="Give feedback" if english else "Donner un avis",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction) -> None:
        from . import language_runtime
        english = (
            interaction.guild_id is not None
            and await language_runtime.get_language(self.bot, interaction.guild_id)
            == language_runtime.LANG_EN
        )
        await interaction.response.send_modal(FeedbackModal(self.bot, english))


class FeedbackPersistentView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.add_item(FeedbackButton(bot))
