"""Centre `+giveaway` et groupe slash canonique `/giveaway`.

Le moteur historique `giveaway-*` reste chargé pour compatibilité. Les actions modernes
sont exposées sous une seule racine slash afin de ne pas gaspiller le budget global de
100 commandes Discord et d'éviter les anciennes commandes slash masquées sans remplaçant.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks, embeds
from utils import sentrix_panels as panels
from .giveaway_v2 import GiveawayV2
from .infinite_counter import InfiniteCounter
from .setup_invitations import install as install_invitation_setup
from .invite_tracker_runtime import install as install_invite_tracker
from .dashboard_runtime_patch import install as install_dashboard_patch

logger = logging.getLogger("bot.giveaway-center")
RUNTIME_MARKER = "Giveaway Center V2"

_CIBLES = {
    "create": "giveaway-create",
    "end": "giveaway-end",
    "reroll": "giveaway-reroll",
    "list": "giveaway-list",
    "cancel": "giveaway-cancel",
    "blacklist": "giveaway-blacklist",
    "unblacklist": "giveaway-unblacklist",
}


class GiveawayCenter(commands.Cog, name="GiveawayCenter"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _v2(self) -> GiveawayV2 | None:
        cog = self.bot.get_cog("GiveawayV2")
        return cog if isinstance(cog, GiveawayV2) else None

    async def _deleguer(self, ctx: commands.Context, cle: str, /, *args, **kwargs):
        commande = self.bot.get_command(_CIBLES[cle])
        if commande is None:
            logger.error("Giveaway : commande interne %s introuvable.", _CIBLES[cle])
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.error("Le moteur de giveaway n'est pas chargé sur cette instance.")),
            )
        return await ctx.invoke(commande, *args, **kwargs)

    async def _list_active(self, ctx: commands.Context):
        """Point unique pour `+giveaway`, `/giveaway list` et leurs variantes."""
        v2 = self._v2()
        if v2 is None:
            return await self._deleguer(ctx, "list")
        await v2.ensure_schema()
        rows_v2 = await self.bot.db.fetchall(
            "SELECT message_id,channel_id,prize,end_at FROM giveaways_v2 WHERE guild_id=? AND status='actif' ORDER BY end_at LIMIT 20",
            (ctx.guild.id,),
        )
        try:
            rows_old = await self.bot.db.fetchall(
                "SELECT message_id,channel_id,prize,end_at FROM giveaways WHERE guild_id=? AND status='actif' ORDER BY end_at LIMIT 20",
                (ctx.guild.id,),
            )
        except Exception:
            rows_old = []
        rows = [("V2", row) for row in rows_v2] + [("historique", row) for row in rows_old]
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun giveaway actif sur ce serveur.", title="Giveaways"))
        lines = []
        for engine, row in rows[:25]:
            lines.append(
                f"• **{row['prize']}** — <#{row['channel_id']}> — <t:{int(row['end_at'])}:R> "
                f"· `{row['message_id']}` · {engine}"
            )
        await ctx.send(embed=embeds.info("\n".join(lines), title="Giveaways actifs"))

    async def _slash_ctx(self, interaction: discord.Interaction) -> commands.Context | None:
        if interaction.guild is None:
            if interaction.response.is_done():
                await interaction.followup.send("Cette commande doit être utilisée sur un serveur.", ephemeral=True)
            else:
                await interaction.response.send_message("Cette commande doit être utilisée sur un serveur.", ephemeral=True)
            return None
        try:
            return await commands.Context.from_interaction(interaction)
        except Exception:
            logger.exception("Impossible de créer le contexte hybride pour /giveaway.")
            if interaction.response.is_done():
                await interaction.followup.send("Impossible d'exécuter cette commande pour le moment.", ephemeral=True)
            else:
                await interaction.response.send_message("Impossible d'exécuter cette commande pour le moment.", ephemeral=True)
            return None

    async def _slash_admin(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        guild = interaction.guild
        allowed = bool(
            guild
            and isinstance(member, discord.Member)
            and (member.id == guild.owner_id or member.guild_permissions.administrator)
        )
        if allowed:
            return True
        text = "Cette action est réservée au propriétaire du serveur ou aux administrateurs."
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        return False

    # ------------------------------------------------------------------ PREFIXE +

    @commands.group(name="giveaway", aliases=["giveaways", "concours"], invoke_without_command=True)
    @commands.guild_only()
    async def giveaway(self, ctx: commands.Context):
        """Centre des giveaways. Sans sous-commande, affiche ceux en cours."""
        await self._list_active(ctx)

    @giveaway.command(name="list", aliases=["liste", "en-cours"])
    async def giveaway_list(self, ctx: commands.Context):
        await self._list_active(ctx)

    @giveaway.command(name="create", aliases=["creer", "créer", "nouveau", "start"])
    @checks.is_owner_or_admin()
    async def giveaway_create(self, ctx: commands.Context):
        v2 = self._v2()
        if v2 is None:
            return await ctx.send(embed=embeds.error("Le builder giveaway V2 n’est pas chargé."))
        await v2.open_builder(ctx)

    @giveaway.command(name="end", aliases=["terminer", "fin", "stop"])
    @checks.is_owner_or_admin()
    async def giveaway_end(self, ctx: commands.Context, message_id: str):
        try:
            numeric_id = int(message_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("L’ID du message doit être un nombre."))
        v2 = self._v2()
        if v2 and await v2.handle_end(ctx, numeric_id):
            return
        await self._deleguer(ctx, "end", message_id=message_id)

    @giveaway.command(name="reroll", aliases=["relancer", "retirage"])
    @checks.is_owner_or_admin()
    async def giveaway_reroll(self, ctx: commands.Context, message_id: str):
        try:
            numeric_id = int(message_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("L’ID du message doit être un nombre."))
        v2 = self._v2()
        if v2 and await v2.handle_reroll(ctx, numeric_id):
            return
        await self._deleguer(ctx, "reroll", message_id=message_id)

    @giveaway.command(name="cancel", aliases=["annuler"])
    @checks.is_owner_or_admin()
    async def giveaway_cancel(self, ctx: commands.Context, message_id: str):
        try:
            numeric_id = int(message_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("L’ID du message doit être un nombre."))
        v2 = self._v2()
        if v2 and await v2.handle_cancel(ctx, numeric_id):
            return
        await self._deleguer(ctx, "cancel", message_id=message_id)

    @giveaway.command(name="blacklist", aliases=["liste-noire", "exclure"])
    @checks.is_owner_or_admin()
    async def giveaway_blacklist(self, ctx: commands.Context, membre: discord.Member):
        await self._deleguer(ctx, "blacklist", membre=membre)

    @giveaway.command(name="unblacklist", aliases=["reautoriser", "réautoriser"])
    @checks.is_owner_or_admin()
    async def giveaway_unblacklist(self, ctx: commands.Context, membre: discord.Member):
        await self._deleguer(ctx, "unblacklist", membre=membre)

    # ------------------------------------------------------------------ SLASH /
    # Un vrai app_commands.Group : toutes les actions ci-dessous consomment UNE seule
    # racine globale `/giveaway` au lieu de six anciennes racines séparées.
    giveaway_slash = app_commands.Group(
        name="giveaway",
        description="Créer et gérer les giveaways SentriX.",
    )

    @giveaway_slash.command(name="list", description="Lister les giveaways actifs.")
    async def slash_giveaway_list(self, interaction: discord.Interaction):
        ctx = await self._slash_ctx(interaction)
        if ctx is not None:
            await self._list_active(ctx)

    @giveaway_slash.command(name="create", description="Ouvrir le builder complet d'un giveaway.")
    @app_commands.default_permissions(administrator=True)
    async def slash_giveaway_create(self, interaction: discord.Interaction):
        if not await self._slash_admin(interaction):
            return
        ctx = await self._slash_ctx(interaction)
        if ctx is None:
            return
        v2 = self._v2()
        if v2 is None:
            return await interaction.response.send_message("Le builder giveaway V2 n'est pas chargé.", ephemeral=True)
        await v2.open_builder(ctx)

    @giveaway_slash.command(name="end", description="Terminer immédiatement un giveaway.")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(administrator=True)
    async def slash_giveaway_end(self, interaction: discord.Interaction, message_id: str):
        if not await self._slash_admin(interaction):
            return
        ctx = await self._slash_ctx(interaction)
        if ctx is None:
            return
        try:
            numeric_id = int(message_id)
        except ValueError:
            return await interaction.response.send_message("L'ID du message doit être un nombre.", ephemeral=True)
        v2 = self._v2()
        if v2 and await v2.handle_end(ctx, numeric_id):
            return
        await self._deleguer(ctx, "end", message_id=message_id)

    @giveaway_slash.command(name="reroll", description="Refaire le tirage d'un giveaway terminé.")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(administrator=True)
    async def slash_giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        if not await self._slash_admin(interaction):
            return
        ctx = await self._slash_ctx(interaction)
        if ctx is None:
            return
        try:
            numeric_id = int(message_id)
        except ValueError:
            return await interaction.response.send_message("L'ID du message doit être un nombre.", ephemeral=True)
        v2 = self._v2()
        if v2 and await v2.handle_reroll(ctx, numeric_id):
            return
        await self._deleguer(ctx, "reroll", message_id=message_id)

    @giveaway_slash.command(name="cancel", description="Annuler un giveaway sans tirer de gagnant.")
    @app_commands.describe(message_id="ID du message du giveaway")
    @app_commands.default_permissions(administrator=True)
    async def slash_giveaway_cancel(self, interaction: discord.Interaction, message_id: str):
        if not await self._slash_admin(interaction):
            return
        ctx = await self._slash_ctx(interaction)
        if ctx is None:
            return
        try:
            numeric_id = int(message_id)
        except ValueError:
            return await interaction.response.send_message("L'ID du message doit être un nombre.", ephemeral=True)
        v2 = self._v2()
        if v2 and await v2.handle_cancel(ctx, numeric_id):
            return
        await self._deleguer(ctx, "cancel", message_id=message_id)

    @giveaway_slash.command(name="blacklist", description="Interdire à un membre de participer aux giveaways.")
    @app_commands.describe(membre="Membre à exclure")
    @app_commands.default_permissions(administrator=True)
    async def slash_giveaway_blacklist(self, interaction: discord.Interaction, membre: discord.Member):
        if not await self._slash_admin(interaction):
            return
        ctx = await self._slash_ctx(interaction)
        if ctx is not None:
            await self._deleguer(ctx, "blacklist", membre=membre)

    @giveaway_slash.command(name="unblacklist", description="Réautoriser un membre dans les giveaways.")
    @app_commands.describe(membre="Membre à réautoriser")
    @app_commands.default_permissions(administrator=True)
    async def slash_giveaway_unblacklist(self, interaction: discord.Interaction, membre: discord.Member):
        if not await self._slash_admin(interaction):
            return
        ctx = await self._slash_ctx(interaction)
        if ctx is not None:
            await self._deleguer(ctx, "unblacklist", membre=membre)


async def setup(bot: commands.Bot) -> None:
    if bot.get_cog("GiveawayCenter") is not None:
        return
    if bot.get_command("giveaway") is not None:
        logger.info("Racine +giveaway déjà présente : centre V2 non installé.")
        return

    install_dashboard_patch()
    install_invitation_setup(bot)
    await install_invite_tracker(bot)

    if bot.get_cog("GiveawayV2") is None:
        await bot.add_cog(GiveawayV2(bot))
    if bot.get_cog("InfiniteCounter") is None:
        await bot.add_cog(InfiniteCounter(bot))
    await bot.add_cog(GiveawayCenter(bot))
    logger.info(
        "%s chargé : vrai groupe /giveaway, builder interactif, compteur infini, tracker invitations et dashboard actifs.",
        RUNTIME_MARKER,
    )
