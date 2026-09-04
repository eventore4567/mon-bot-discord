"""Racine `+giveaway`, cible de fusion annoncée par le catalogue.

``cogs/command_catalog_cleanup.py`` déclare depuis toujours que les six commandes
``giveaway-*`` sont *fusionnées* vers une racine ``giveaway`` (comme ``ticket``,
``security`` et ``setup``). Cette racine était fournie par
``cogs/command_giveaway_center_v3.py``, supprimé par le commit 2a130d7 en même
temps que d'authentiques modules morts. La destination annoncée n'existait donc
plus : le catalogue et l'aide renvoyaient vers ``+giveaway``, qui répondait
« commande inconnue ».

Ce module rétablit la racine **sur l'architecture actuelle**, en suivant le
patron de ``security_command_center`` : un groupe fin qui **délègue** aux
implémentations existantes de ``cogs/events.py``. Aucune logique métier n'est
dupliquée — il n'y a toujours qu'un seul moteur de giveaway.

Point de sécurité : ``ctx.invoke`` n'exécute PAS les checks de la commande
appelée. Chaque sous-commande porte donc explicitement le même contrôle
d'autorisation que sa cible, faute de quoi la racine deviendrait un contournement
de permissions.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import checks, embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.giveaway-center")

RUNTIME_MARKER = "Giveaway Center"

# Sous-commande -> commande historique réellement exécutée.
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

    async def _deleguer(self, ctx: commands.Context, cle: str, /, *args, **kwargs):
        """Exécute la commande historique correspondante."""
        commande = self.bot.get_command(_CIBLES[cle])
        if commande is None:
            logger.error("Giveaway : commande interne %s introuvable.", _CIBLES[cle])
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.error("Le moteur de giveaway n'est pas chargé sur cette instance.")
                ),
            )
        return await ctx.invoke(commande, *args, **kwargs)

    @commands.group(
        name="giveaway",
        aliases=["giveaways", "concours"],
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def giveaway(self, ctx: commands.Context):
        """Centre des giveaways. Sans sous-commande, affiche ceux en cours."""
        await self._deleguer(ctx, "list")

    @giveaway.command(name="list", aliases=["liste", "en-cours"])
    async def giveaway_list(self, ctx: commands.Context):
        """Lister les giveaways actifs."""
        await self._deleguer(ctx, "list")

    @giveaway.command(name="create", aliases=["creer", "créer", "nouveau", "start"])
    @checks.is_owner_or_admin()
    async def giveaway_create(
        self,
        ctx: commands.Context,
        prix: str,
        duree: str,
        gagnants: int = 1,
        image: str = None,
        role_requis: discord.Role = None,
        niveau_requis: int = None,
        role_exclu: discord.Role = None,
        role_bonus: discord.Role = None,
        entrees_bonus: int = 2,
    ):
        """Créer un giveaway."""
        await self._deleguer(
            ctx,
            "create",
            prix=prix,
            duree=duree,
            gagnants=gagnants,
            image=image,
            role_requis=role_requis,
            niveau_requis=niveau_requis,
            role_exclu=role_exclu,
            role_bonus=role_bonus,
            entrees_bonus=entrees_bonus,
        )

    @giveaway.command(name="end", aliases=["terminer", "fin", "stop"])
    @checks.is_owner_or_admin()
    async def giveaway_end(self, ctx: commands.Context, message_id: str):
        """Terminer un giveaway immédiatement."""
        await self._deleguer(ctx, "end", message_id=message_id)

    @giveaway.command(name="reroll", aliases=["relancer", "retirage"])
    @checks.is_owner_or_admin()
    async def giveaway_reroll(self, ctx: commands.Context, message_id: str):
        """Tirer un nouveau gagnant pour un giveaway terminé."""
        await self._deleguer(ctx, "reroll", message_id=message_id)

    @giveaway.command(name="cancel", aliases=["annuler"])
    @checks.is_owner_or_admin()
    async def giveaway_cancel(self, ctx: commands.Context, message_id: str):
        """Annuler un giveaway sans désigner de gagnant."""
        await self._deleguer(ctx, "cancel", message_id=message_id)

    @giveaway.command(name="blacklist", aliases=["liste-noire", "exclure"])
    @checks.is_owner_or_admin()
    async def giveaway_blacklist(self, ctx: commands.Context, membre: discord.Member):
        """Empêcher un membre de participer aux giveaways."""
        await self._deleguer(ctx, "blacklist", membre=membre)

    @giveaway.command(name="unblacklist", aliases=["reautoriser", "réautoriser"])
    @checks.is_owner_or_admin()
    async def giveaway_unblacklist(self, ctx: commands.Context, membre: discord.Member):
        """Autoriser à nouveau un membre à participer aux giveaways."""
        await self._deleguer(ctx, "unblacklist", membre=membre)


async def setup(bot: commands.Bot) -> None:
    if bot.get_cog("GiveawayCenter") is not None:
        return
    if bot.get_command("giveaway") is not None:
        # Une autre couche fournit déjà la racine : ne jamais la doubler.
        logger.info("Racine +giveaway déjà présente : centre non installé.")
        return
    await bot.add_cog(GiveawayCenter(bot))
    logger.info("%s chargé : racine +giveaway rétablie sur le moteur existant.", RUNTIME_MARKER)
