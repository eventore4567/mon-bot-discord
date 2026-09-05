"""Centre `+giveaway` et point d'installation des ajouts interactifs de fin de chantier.

Le moteur historique `giveaway-*` reste chargé pour compatibilité. La nouvelle racine
`+giveaway create` ouvre toutefois le builder V2 sans argument, avec ses propres données
persistantes et ses conditions avancées.
"""
from __future__ import annotations

import logging

import discord
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
        """Point unique pour `+giveaway` et `+giveaway list`.

        Une sous-commande décorée est un objet Command discord.py, pas une coroutine
        métier à rappeler directement depuis la racine. Cette méthode évite donc un
        faux appel `self.giveaway_list(ctx)` et garde les deux entrées strictement
        identiques.
        """
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

    @commands.group(name="giveaway", aliases=["giveaways", "concours"], invoke_without_command=True)
    @commands.guild_only()
    async def giveaway(self, ctx: commands.Context):
        """Centre des giveaways. Sans sous-commande, affiche ceux en cours."""
        await self._list_active(ctx)

    @giveaway.command(name="list", aliases=["liste", "en-cours"])
    async def giveaway_list(self, ctx: commands.Context):
        """Lister ensemble les giveaways V2 et historiques actifs."""
        await self._list_active(ctx)

    @giveaway.command(name="create", aliases=["creer", "créer", "nouveau", "start"])
    @checks.is_owner_or_admin()
    async def giveaway_create(self, ctx: commands.Context):
        """Ouvrir le setup interactif complet. Aucun argument n'est requis."""
        v2 = self._v2()
        if v2 is None:
            return await ctx.send(embed=embeds.error("Le builder giveaway V2 n’est pas chargé."))
        await v2.open_builder(ctx)

    @giveaway.command(name="end", aliases=["terminer", "fin", "stop"])
    @checks.is_owner_or_admin()
    async def giveaway_end(self, ctx: commands.Context, message_id: str):
        """Terminer immédiatement un giveaway V2 ou historique."""
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
        """Refaire un tirage sans doublonner un ancien gagnant si possible."""
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
        """Annuler un giveaway V2 ou historique."""
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
        """Empêcher un membre de participer aux giveaways, V2 inclus."""
        await self._deleguer(ctx, "blacklist", membre=membre)

    @giveaway.command(name="unblacklist", aliases=["reautoriser", "réautoriser"])
    @checks.is_owner_or_admin()
    async def giveaway_unblacklist(self, ctx: commands.Context, membre: discord.Member):
        """Autoriser à nouveau un membre à participer aux giveaways."""
        await self._deleguer(ctx, "unblacklist", membre=membre)


async def setup(bot: commands.Bot) -> None:
    # Invariant historique : si une autre extension fournit déjà la racine +giveaway,
    # ce centre ne doit ajouter AUCUN cog auxiliaire. Cela évite les doubles commandes et
    # garde les tests de registre déterministes.
    if bot.get_cog("GiveawayCenter") is not None:
        return
    if bot.get_command("giveaway") is not None:
        logger.info("Racine +giveaway déjà présente : centre V2 non installé.")
        return

    # Ces patchs doivent être en place avant le démarrage aiohttp et avant le chargement
    # du cog Invites, qui utilisera ainsi directement la catégorie dédiée.
    install_dashboard_patch()
    install_invitation_setup(bot)
    await install_invite_tracker(bot)

    if bot.get_cog("GiveawayV2") is None:
        await bot.add_cog(GiveawayV2(bot))
    if bot.get_cog("InfiniteCounter") is None:
        await bot.add_cog(InfiniteCounter(bot))
    await bot.add_cog(GiveawayCenter(bot))
    logger.info(
        "%s chargé : builder interactif, compteur infini, tracker invitations et dashboard actifs.",
        RUNTIME_MARKER,
    )
