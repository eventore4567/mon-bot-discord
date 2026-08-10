"""Centre canonique +giveaway ; le reroll reste une commande directe séparée."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import checks

logger = logging.getLogger("bot.giveaway-center-v3")


async def _call(command: commands.Command, ctx: commands.Context, *args):
    cog = getattr(command, "cog", None)
    if cog is None:
        return await command.callback(ctx, *args)
    return await command.callback(cog, ctx, *args)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_giveaway_center_v3", False):
        return
    if bot.get_cog("Events") is None:
        return

    legacy_list = bot.get_command("giveaway-list")
    legacy_create = bot.get_command("giveaway-create")
    legacy_end = bot.get_command("giveaway-end")
    legacy_cancel = bot.get_command("giveaway-cancel")
    legacy_restrict = bot.get_command("giveaway-blacklist")
    legacy_allow = bot.get_command("giveaway-unblacklist")
    if legacy_list is None:
        return

    @commands.hybrid_group(
        name="giveaway",
        description="Voir ou gérer les giveaways du serveur.",
        fallback="list",
        invoke_without_command=True,
    )
    async def giveaway(ctx: commands.Context):
        await _call(legacy_list, ctx)

    if legacy_create is not None:
        @giveaway.command(name="create", description="Créer un giveaway.")
        @checks.is_owner_or_admin()
        async def create(
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
            await _call(
                legacy_create, ctx, prix, duree, gagnants, image, role_requis,
                niveau_requis, role_exclu, role_bonus, entrees_bonus,
            )

    if legacy_end is not None:
        @giveaway.command(name="end", description="Terminer un giveaway immédiatement.")
        @checks.is_owner_or_admin()
        async def end(ctx: commands.Context, message_id: str):
            await _call(legacy_end, ctx, message_id)

    if legacy_cancel is not None:
        @giveaway.command(name="cancel", description="Annuler un giveaway.")
        @checks.is_owner_or_admin()
        async def cancel(ctx: commands.Context, message_id: str):
            await _call(legacy_cancel, ctx, message_id)

    if legacy_restrict is not None:
        @giveaway.command(name="restrict", description="Retirer l'accès aux giveaways à un membre.")
        @checks.is_owner_or_admin()
        async def restrict(ctx: commands.Context, membre: discord.Member):
            await _call(legacy_restrict, ctx, membre)

    if legacy_allow is not None:
        @giveaway.command(name="allow", description="Rendre l'accès aux giveaways à un membre.")
        @checks.is_owner_or_admin()
        async def allow(ctx: commands.Context, membre: discord.Member):
            await _call(legacy_allow, ctx, membre)

    bot.add_command(giveaway)
    if giveaway.app_command is not None:
        bot.tree.add_command(giveaway.app_command, override=True)
    bot._sentrix_giveaway_center_v3 = True
    logger.info("Centre +giveaway V3 installé ; +giveaway-reroll reste direct.")
