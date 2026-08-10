"""Centre canonique +ticket avec compatibilité des anciennes commandes."""
from __future__ import annotations

import logging

from discord.ext import commands

from utils import checks

logger = logging.getLogger("bot.ticket-center-v3")


async def _call(command: commands.Command, ctx: commands.Context):
    cog = getattr(command, "cog", None)
    if cog is None:
        return await command.callback(ctx)
    return await command.callback(cog, ctx)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_ticket_center_v3", False):
        return
    if bot.get_cog("Tickets") is None:
        return

    legacy_open = bot.get_command("ticket")
    legacy_setup = bot.get_command("ticketsetup")
    legacy_reopen = bot.get_command("ticket-reopen")
    legacy_transcript = bot.get_command("tickettranscript")
    legacy_stats = bot.get_command("ticketstats")
    if legacy_open is None or legacy_setup is None:
        return

    removed = bot.remove_command("ticket")
    old_app = getattr(removed, "app_command", None) if removed else None
    old_app_name = getattr(old_app, "name", None)
    if old_app_name and bot.tree.get_command(old_app_name):
        bot.tree.remove_command(old_app_name)

    @commands.hybrid_group(
        name="ticket",
        description="Ouvrir un ticket ou gérer tout le système de tickets.",
        fallback="open",
        invoke_without_command=True,
    )
    async def ticket(ctx: commands.Context):
        await _call(legacy_open, ctx)

    @ticket.command(name="setup", description="Ouvrir la configuration complète des tickets.")
    @checks.is_owner_or_admin_for("tickets")
    async def setup(ctx: commands.Context):
        await _call(legacy_setup, ctx)

    if legacy_reopen is not None:
        @ticket.command(name="reopen", description="Rouvrir le ticket actuel.")
        @checks.has_permission_or_modrole("manage_channels")
        async def reopen(ctx: commands.Context):
            await _call(legacy_reopen, ctx)

    if legacy_transcript is not None:
        @ticket.command(name="transcript", description="Exporter le transcript du ticket.")
        @checks.has_permission_or_modrole("manage_channels")
        async def transcript(ctx: commands.Context):
            await _call(legacy_transcript, ctx)

    if legacy_stats is not None:
        @ticket.command(name="stats", description="Afficher les statistiques des tickets.")
        @checks.has_permission_or_modrole("manage_channels")
        async def stats(ctx: commands.Context):
            await _call(legacy_stats, ctx)

    bot.add_command(ticket)
    if ticket.app_command is not None:
        bot.tree.add_command(ticket.app_command, override=True)
    bot._sentrix_ticket_center_v3 = True
    logger.info("Centre +ticket V3 installé.")
