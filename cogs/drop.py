"""Commande +drop : drop d'argent interactif dans un salon Discord.

Usage : +drop 1000
Le premier membre qui clique sur le bouton récupère le montant dans son portefeuille.
La création d'un drop est réservée aux administrateurs / gestionnaires économie.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from utils import checks, design_system, embeds, stats_service

logger = logging.getLogger("bot.economy.drop")

MAX_DROP_AMOUNT = 1_000_000_000_000
DROP_TIMEOUT_SECONDS = 300


class MoneyDropView(discord.ui.View):
    """Vue mono-gagnant : un verrou empêche deux clics simultanés de gagner."""

    def __init__(
        self,
        bot: commands.Bot,
        guild_id: int,
        amount: int,
        creator_id: int,
        currency_emoji: str,
    ):
        super().__init__(timeout=DROP_TIMEOUT_SECONDS)
        self.bot = bot
        self.guild_id = guild_id
        self.amount = amount
        self.creator_id = creator_id
        self.currency_emoji = currency_emoji
        self.claimed_by: int | None = None
        self._claim_lock = asyncio.Lock()
        self.message: discord.Message | None = None

    def _disable_button(self, *, claimed: bool = False) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
                child.style = discord.ButtonStyle.success if claimed else discord.ButtonStyle.secondary
                child.label = "Récupéré !" if claimed else "Drop expiré"

    @discord.ui.button(
        label="Récupérer le drop",
        style=discord.ButtonStyle.success,
        emoji="💸",
        custom_id="sentrix:money-drop:claim",
    )
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        del button
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            return await interaction.response.send_message(
                "Ce drop n'est plus disponible sur ce serveur.",
                ephemeral=True,
            )
        if not isinstance(interaction.user, discord.Member) or interaction.user.bot:
            return await interaction.response.send_message(
                "Les bots ne peuvent pas récupérer un drop.",
                ephemeral=True,
            )

        async with self._claim_lock:
            if self.claimed_by is not None:
                return await interaction.response.send_message(
                    "Trop tard : ce drop a déjà été récupéré.",
                    ephemeral=True,
                )

            try:
                await self.bot.db.ensure_economy(self.guild_id, interaction.user.id)
                await self.bot.db.add_balance(self.guild_id, interaction.user.id, self.amount)
                message_id = interaction.message.id if interaction.message else 0
                await self.bot.db.log_transaction(
                    self.guild_id,
                    self.creator_id,
                    interaction.user.id,
                    "drop_claim",
                    self.amount,
                    f"Drop staff #{message_id}",
                )
            except Exception:
                logger.exception(
                    "Échec de récupération d'un drop — guild=%s user=%s amount=%s",
                    self.guild_id,
                    interaction.user.id,
                    self.amount,
                )
                return await interaction.response.send_message(
                    "Le drop n'a pas pu être crédité. Réessaie dans quelques secondes.",
                    ephemeral=True,
                )

            self.claimed_by = interaction.user.id
            self._disable_button(claimed=True)
            self.stop()

            original = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
            if original is not None:
                result = discord.Embed.from_dict(original.to_dict())
                result.title = "💸 Drop récupéré !"
                result.description = (
                    f"{interaction.user.mention} a été le plus rapide et récupère "
                    f"**{stats_service.format_number(self.amount)} {self.currency_emoji}** !"
                )
            else:
                result = embeds.success(
                    f"{interaction.user.mention} récupère "
                    f"**{stats_service.format_number(self.amount)} {self.currency_emoji}** !",
                    title="💸 Drop récupéré !",
                )

            await interaction.response.edit_message(embed=result, view=self)

    async def on_timeout(self) -> None:
        if self.claimed_by is not None:
            return
        self._disable_button(claimed=False)
        if self.message is None:
            return
        try:
            if self.message.embeds:
                expired = discord.Embed.from_dict(self.message.embeds[0].to_dict())
                expired.title = "⌛ Drop expiré"
                expired.description = (
                    f"Personne n'a récupéré les **{stats_service.format_number(self.amount)} "
                    f"{self.currency_emoji}** à temps."
                )
                await self.message.edit(embed=expired, view=self)
            else:
                await self.message.edit(view=self)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


class MoneyDrops(commands.Cog, name="MoneyDrops"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="drop", aliases=["moneydrop", "dropmoney"])
    @commands.guild_only()
    @checks.is_owner_or_admin_for("economie")
    async def drop(self, ctx: commands.Context, montant: int):
        """Drop de l'argent : +drop 1000. Le premier clic gagne le montant."""
        if montant < 1 or montant > MAX_DROP_AMOUNT:
            return await ctx.send(
                embed=embeds.error(
                    "Le montant du drop doit être compris entre **1** et "
                    f"**{stats_service.format_number(MAX_DROP_AMOUNT)}**."
                )
            )

        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        currency_emoji = settings.get("economy_emoji", "🪙")
        style = design_system.CATEGORY_STYLES["economy"]

        embed = design_system.create_embed(
            title="💸 Drop d'argent !",
            description=(
                f"**{stats_service.format_number(montant)} {currency_emoji}** viennent d'être drop !\n\n"
                "Le **premier membre** qui clique sur le bouton ci-dessous récupère tout le montant.\n"
                "Le bouton expire après **5 minutes**."
            ),
            colour=design.get("primary_color", style["colour"]),
            footer=design.get("footer"),
        )
        embed.add_field(name="Créé par", value=ctx.author.mention, inline=True)
        embed.add_field(name="Montant", value=f"{stats_service.format_number(montant)} {currency_emoji}", inline=True)

        view = MoneyDropView(
            self.bot,
            ctx.guild.id,
            montant,
            ctx.author.id,
            currency_emoji,
        )
        message = await ctx.send(embed=embed, view=view)
        view.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(MoneyDrops(bot))
