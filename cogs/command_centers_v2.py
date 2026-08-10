"""Centres fusionnés Ticket et Giveaway sans supprimer la compatibilité des anciennes +."""
from __future__ import annotations

import logging
from dataclasses import replace

import discord
from discord.ext import commands

from utils import checks

logger = logging.getLogger("bot.command-centers-v2")


async def _call_legacy(command: commands.Command, ctx: commands.Context, *args, **kwargs):
    cog = getattr(command, "cog", None)
    if cog is None:
        return await command.callback(ctx, *args, **kwargs)
    return await command.callback(cog, ctx, *args, **kwargs)


def _register_hybrid_root(bot: commands.Bot, command: commands.Command) -> None:
    bot.add_command(command)
    app = getattr(command, "app_command", None)
    if app is not None:
        bot.tree.add_command(app, override=True)


def _patch_help_category(root_name: str, category_key: str) -> None:
    try:
        from . import help_complete
    except Exception:
        return

    updated = []
    changed = False
    for category in help_complete.CATEGORIES:
        if category.key == category_key and root_name not in category.roots:
            category = replace(category, roots=category.roots | {root_name})
            changed = True
        updated.append(category)
    if changed:
        help_complete.CATEGORIES = tuple(updated)
        help_complete.CATEGORY_BY_KEY = {
            category.key: category for category in help_complete.CATEGORIES
        }


def _install_ticket_center(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_ticket_center_v2", False):
        return
    tickets = bot.get_cog("Tickets")
    legacy_open = bot.get_command("ticket")
    legacy_setup = bot.get_command("ticketsetup")
    legacy_reopen = bot.get_command("ticket-reopen")
    legacy_transcript = bot.get_command("tickettranscript")
    legacy_stats = bot.get_command("ticketstats")
    if tickets is None or legacy_open is None or legacy_setup is None:
        return

    removed = bot.remove_command("ticket")
    old_app = getattr(removed, "app_command", None) if removed else None
    old_app_name = getattr(old_app, "name", None)
    if old_app_name and bot.tree.get_command(old_app_name):
        bot.tree.remove_command(old_app_name)

    @commands.hybrid_group(
        name="ticket",
        description="Centre tickets : ouvrir un ticket ou gérer le système.",
        fallback="open",
        invoke_without_command=True,
    )
    async def ticket_group(ctx: commands.Context):
        await _call_legacy(legacy_open, ctx)

    @ticket_group.command(name="setup", description="Ouvrir toute la configuration des tickets.")
    @checks.is_owner_or_admin_for("tickets")
    async def ticket_setup(ctx: commands.Context):
        await _call_legacy(legacy_setup, ctx)

    if legacy_reopen is not None:
        @ticket_group.command(name="reopen", description="Rouvrir le ticket actuel.")
        @checks.has_permission_or_modrole("manage_channels")
        async def ticket_reopen(ctx: commands.Context):
            await _call_legacy(legacy_reopen, ctx)

    if legacy_transcript is not None:
        @ticket_group.command(name="transcript", description="Exporter le transcript du ticket.")
        @checks.has_permission_or_modrole("manage_channels")
        async def ticket_transcript(ctx: commands.Context):
            await _call_legacy(legacy_transcript, ctx)

    if legacy_stats is not None:
        @ticket_group.command(name="stats", description="Afficher les statistiques des tickets.")
        @checks.has_permission_or_modrole("manage_channels")
        async def ticket_stats(ctx: commands.Context):
            await _call_legacy(legacy_stats, ctx)

    _register_hybrid_root(bot, ticket_group)
    bot._sentrix_ticket_center_v2 = True
    logger.info("Centre +ticket V2 installé.")


def _install_giveaway_center(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_giveaway_center_v2", False):
        return
    events = bot.get_cog("Events")
    if events is None:
        return

    legacy = {
        name: bot.get_command(name)
        for name in (
            "giveaway-create", "giveaway-end", "giveaway-list", "giveaway-cancel",
            "giveaway-blacklist", "giveaway-unblacklist",
        )
    }
    if legacy["giveaway-list"] is None:
        return

    @commands.hybrid_group(
        name="giveaway",
        description="Centre giveaways : voir et gérer les concours.",
        fallback="list",
        invoke_without_command=True,
    )
    async def giveaway_group(ctx: commands.Context):
        await _call_legacy(legacy["giveaway-list"], ctx)

    if legacy["giveaway-create"] is not None:
        @giveaway_group.command(name="create", description="Créer un giveaway.")
        @checks.is_owner_or_admin()
        async def giveaway_create(
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
            await _call_legacy(
                legacy["giveaway-create"], ctx, prix, duree, gagnants,
                image, role_requis, niveau_requis, role_exclu, role_bonus, entrees_bonus,
            )

    if legacy["giveaway-end"] is not None:
        @giveaway_group.command(name="end", description="Terminer un giveaway.")
        @checks.is_owner_or_admin()
        async def giveaway_end(ctx: commands.Context, message_id: str):
            await _call_legacy(legacy["giveaway-end"], ctx, message_id)

    @giveaway_group.command(name="list", description="Lister les giveaways actifs.")
    async def giveaway_list(ctx: commands.Context):
        await _call_legacy(legacy["giveaway-list"], ctx)

    if legacy["giveaway-cancel"] is not None:
        @giveaway_group.command(name="cancel", description="Annuler un giveaway.")
        @checks.is_owner_or_admin()
        async def giveaway_cancel(ctx: commands.Context, message_id: str):
            await _call_legacy(legacy["giveaway-cancel"], ctx, message_id)

    if legacy["giveaway-blacklist"] is not None:
        @giveaway_group.command(name="blacklist", description="Interdire les giveaways à un membre.")
        @checks.is_owner_or_admin()
        async def giveaway_blacklist(ctx: commands.Context, membre: discord.Member):
            await _call_legacy(legacy["giveaway-blacklist"], ctx, membre)

    if legacy["giveaway-unblacklist"] is not None:
        @giveaway_group.command(name="unblacklist", description="Retirer l'interdiction giveaway.")
        @checks.is_owner_or_admin()
        async def giveaway_unblacklist(ctx: commands.Context, membre: discord.Member):
            await _call_legacy(legacy["giveaway-unblacklist"], ctx, membre)

    _register_hybrid_root(bot, giveaway_group)
    _patch_help_category("giveaway", "events")
    bot._sentrix_giveaway_center_v2 = True
    logger.info("Centre +giveaway V2 installé ; +giveaway-reroll reste direct.")


def install(bot: commands.Bot) -> None:
    _install_ticket_center(bot)
    _install_giveaway_center(bot)
