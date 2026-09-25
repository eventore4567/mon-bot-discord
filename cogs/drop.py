"""Commande +drop : drop d'argent interactif dans un salon Discord.

Usage : +drop 1000
Le premier membre qui clique sur le bouton récupère le montant dans son portefeuille.
La création d'un drop est réservée aux administrateurs / gestionnaires économie.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

import discord
from discord.ext import commands, tasks

from discord import app_commands

from utils import checks, design_system, embeds, stats_service
from utils.game_context import pictogrammes_porteurs
from utils import sentrix_panels as panels

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
                    "Le drop n'a pas pu être crédité. Réessayez dans quelques secondes.",
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

            await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(result), self))

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
                await panels.editer(self.message, panels.avec_composants(panels.depuis_embed(expired), self))
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
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Le montant du drop doit être compris entre **1** et **{stats_service.format_number(MAX_DROP_AMOUNT)}**.')))

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
        message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), view))
        view.message = message


    # ---- Drop automatique ---------------------------------------------------

    def cog_load(self) -> None:
        self._boucle_auto_drop.start()

    def cog_unload(self) -> None:
        self._boucle_auto_drop.cancel()

    @tasks.loop(minutes=1)
    async def _boucle_auto_drop(self) -> None:
        """Fait apparaître un drop dans les salons configurés dont l'heure est venue.

        Les serveurs dus sont filtrés EN SQL : parcourir les 28 serveurs en
        Python chaque minute ferait un aller-retour par serveur pour n'en
        retenir presque jamais aucun.
        """
        try:
            maintenant = int(time.time())
            dus = await self.bot.db.auto_drops_a_lancer(maintenant)
        except Exception:
            logger.warning("Lecture des drops automatiques impossible.", exc_info=True)
            return

        for reglage in dus:
            guild_id = int(reglage["guild_id"])
            # L'horodatage est posé AVANT l'envoi : si Discord refuse le message,
            # la boucle ne doit pas réessayer toutes les minutes indéfiniment.
            try:
                await self.bot.db.set_auto_drop_config(guild_id, {"last_drop_at": maintenant})
            except Exception:
                logger.warning("Horodatage du drop automatique impossible (%s).", guild_id, exc_info=True)
                continue
            try:
                await self._lancer_drop_automatique(reglage)
            except Exception:
                logger.warning("Drop automatique impossible sur %s.", guild_id, exc_info=True)

    @_boucle_auto_drop.before_loop
    async def _avant_boucle(self) -> None:
        await self.bot.wait_until_ready()

    async def _lancer_drop_automatique(self, reglage) -> None:
        guild = self.bot.get_guild(int(reglage["guild_id"]))
        if guild is None:
            return
        salon = guild.get_channel(int(reglage["channel_id"] or 0))
        if salon is None or not isinstance(salon, discord.abc.Messageable):
            logger.info("Drop automatique ignoré : salon introuvable sur %s.", guild.id)
            return
        permissions = salon.permissions_for(guild.me) if guild.me else None
        if permissions is not None and not (permissions.send_messages and permissions.view_channel):
            logger.info("Drop automatique ignoré : SentriX ne peut pas écrire dans %s.", salon.id)
            return

        bas = max(1, int(reglage["min_amount"] or 1))
        haut = max(bas, int(reglage["max_amount"] or bas))
        montant = random.randint(bas, haut)

        settings = await self.bot.db.get_stats_settings(guild.id)
        design = await self.bot.db.get_design_settings(guild.id)
        emoji = settings.get("economy_emoji", "🪙")
        style = design_system.CATEGORY_STYLES["economy"]

        # Tout le bloc, pas seulement l'envoi : le nettoyage a lieu à la
        # CONSTRUCTION de l'embed. Sans contexte de commande — on est dans une
        # tâche de fond — la couche sobre mangeait le symbole monétaire, qui est
        # l'unité du montant, et laissait « **128 ** viennent d'apparaître ».
        with pictogrammes_porteurs():
            embed = design_system.create_embed(
                title="💸 Drop surprise !",
                description=(
                    f"**{stats_service.format_number(montant)} {emoji}** viennent d'apparaître.\n\n"
                    "Le **premier** qui clique repart avec tout.\n"
                    f"Le bouton expire dans **{DROP_TIMEOUT_SECONDS // 60} minutes**."
                ),
                colour=design.get("primary_color", style["colour"]),
                footer=design.get("footer"),
            )
            vue = MoneyDropView(self.bot, guild.id, montant, self.bot.user.id, emoji)
            message = await panels.envoyer(salon, panels.avec_composants(panels.depuis_embed(embed), vue))
        vue.message = message

    @commands.hybrid_command(
        name="autodrop",
        description="Configurer les drops d'argent automatiques dans un salon.",
        with_app_command=False,
    )
    @commands.guild_only()
    @checks.is_owner_or_admin_for("economie")
    @app_commands.describe(
        salon="Le salon où les drops apparaissent (omettre pour voir les réglages)",
        minimum="Montant minimum d'un drop",
        maximum="Montant maximum d'un drop",
        minutes="Délai entre deux drops, en minutes (5 à 1440)",
    )
    async def autodrop(
        self,
        ctx: commands.Context,
        salon: discord.TextChannel = None,
        minimum: int = None,
        maximum: int = None,
        minutes: int = None,
    ):
        """Sans argument, affiche les réglages. `+autodrop off` les désactive."""
        db = self.bot.db
        reglage = await db.get_auto_drop_config(ctx.guild.id)
        emoji = (await db.get_stats_settings(ctx.guild.id)).get("economy_emoji", "🪙")

        if salon is None and minimum is None and maximum is None and minutes is None:
            return await self._afficher_autodrop(ctx, reglage, emoji)

        maj: dict = {}
        if salon is not None:
            permissions = salon.permissions_for(ctx.guild.me) if ctx.guild.me else None
            if permissions is not None and not (permissions.send_messages and permissions.view_channel):
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(
                    f"SentriX ne peut pas écrire dans {salon.mention}. "
                    "Donnez-lui **Voir le salon** et **Envoyer des messages**, puis réessayez."
                )))
            maj["channel_id"] = salon.id
            maj["enabled"] = 1
        if minimum is not None:
            maj["min_amount"] = max(1, min(int(minimum), MAX_DROP_AMOUNT))
        if maximum is not None:
            maj["max_amount"] = max(1, min(int(maximum), MAX_DROP_AMOUNT))
        if minutes is not None:
            maj["interval_minutes"] = max(5, min(int(minutes), 1440))

        bas = maj.get("min_amount", reglage["min_amount"])
        haut = maj.get("max_amount", reglage["max_amount"])
        if bas > haut:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(
                f"Le minimum (**{stats_service.format_number(bas)}**) dépasse le maximum "
                f"(**{stats_service.format_number(haut)}**)."
            )))

        reglage = await db.set_auto_drop_config(ctx.guild.id, maj, actor_id=ctx.author.id)
        await self._afficher_autodrop(ctx, reglage, emoji, titre="Drops automatiques enregistrés")

    @commands.hybrid_command(name="autodrop-off", description="Arrêter les drops automatiques.", with_app_command=False)
    @commands.guild_only()
    @checks.is_owner_or_admin_for("economie")
    async def autodrop_off(self, ctx: commands.Context):
        await self.bot.db.set_auto_drop_config(ctx.guild.id, {"enabled": 0}, actor_id=ctx.author.id)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(
            "Drops automatiques arrêtés. Les réglages sont conservés : `+autodrop #salon` les relance."
        )))

    async def _afficher_autodrop(self, ctx, reglage, emoji: str, titre: str = "Drops automatiques") -> None:
        actif = bool(reglage["enabled"]) and reglage["channel_id"]
        salon = ctx.guild.get_channel(int(reglage["channel_id"] or 0))
        prefixe = ctx.clean_prefix if isinstance(getattr(ctx, "clean_prefix", None), str) else "+"
        lignes = [
            panels.Ligne("État", "**● ACTIF**" if actif else "**○ INACTIF**",
                         indice=None if actif else f"`{prefixe}autodrop #salon` pour démarrer"),
            panels.Ligne("Salon", salon.mention if salon else "**Aucun**",
                         indice=None if salon else "Choisissez un salon visible par tout le monde."),
            panels.Ligne(
                "Montant",
                f"entre **{stats_service.format_number(reglage['min_amount'])}** et "
                f"**{stats_service.format_number(reglage['max_amount'])}** {emoji}",
            ),
            panels.Ligne("Fréquence", f"toutes les **{reglage['interval_minutes']} min**"),
        ]
        if actif and reglage["last_drop_at"]:
            prochain = int(reglage["last_drop_at"]) + int(reglage["interval_minutes"]) * 60
            lignes.append(panels.Ligne("Prochain drop", f"<t:{prochain}:R>"))
        await panels.envoyer(ctx, panels.Panneau(
            titre=titre,
            sous_titre="Le premier qui clique repart avec tout",
            sections=[
                panels.Section("Réglages", lignes),
                panels.Section("Commandes", texte=(
                    f"`{prefixe}autodrop #salon` — choisir le salon et démarrer\n"
                    f"`{prefixe}autodrop #salon 50 500 30` — salon, min, max, délai en minutes\n"
                    f"`{prefixe}autodrop-off` — arrêter sans perdre les réglages\n"
                    f"`{prefixe}drop 1000` — lancer un drop tout de suite"
                )),
            ],
            kind="economie",
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(MoneyDrops(bot))
