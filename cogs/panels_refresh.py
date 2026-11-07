"""Owner-only command to refresh published ticket panels without resetting their settings.

Usage: +panels restart
Only previously published panels in the invoking guild are touched.
"""

import logging

import discord
from discord.ext import commands

from cogs.setup_v2_core import module_enabled
from cogs.tickets import TicketPanelView
from utils import checks, embeds, sentrix_panels as sx_panels
from utils.ticket_panel_design import SlimTicketPanel

logger = logging.getLogger("bot.panel-refresh")


class PanelsRefresh(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def refresh_one(self, guild: discord.Guild, panel, *, allow_new: bool = False):
        """Return (status, message). Never changes enabled, title, types or other settings."""
        cog = self.bot.get_cog("Tickets")
        if not cog:
            raise RuntimeError("Le module Tickets n'est pas chargé.")
        if not bool(panel["enabled"]):
            return "disabled", None
        if not await module_enabled(self.bot, guild.id, "tickets"):
            return "disabled", None

        channel = guild.get_channel(panel["channel_id"]) if panel["channel_id"] else None
        if not isinstance(channel, discord.TextChannel):
            return "no-channel", None
        types = await cog.get_panel_types(panel["id"])
        if not types:
            return "no-types", None
        if not panel["message_id"] and not allow_new:
            return "not-published", None

        layout = sx_panels.avec_composants(SlimTicketPanel(panel), TicketPanelView(panel, types))
        old = None
        if panel["message_id"]:
            try:
                old = await channel.fetch_message(int(panel["message_id"]))
            except discord.NotFound:
                old = None  # A published message was deleted: recover it in the saved channel.
            # A permission or network error must NOT result in a duplicate message.

        if old is not None:
            if old.author.id != self.bot.user.id:
                raise RuntimeError("Le message enregistré n'appartient pas à SentriX.")
            # Discord cannot convert a legacy embed message into Components V2 by editing.
            if bool(old.flags.value & (1 << 15)):
                await sx_panels.editer(old, layout)
                return "updated", old

            replacement = await sx_panels.envoyer(channel, layout)
            try:
                await old.delete()
            except discord.HTTPException:
                try:
                    await replacement.delete()
                except discord.HTTPException:
                    logger.warning("Impossible de supprimer le remplacement après échec du nettoyage.")
                raise RuntimeError("Ancien panneau impossible à supprimer : remplacement annulé.")
            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET message_id=? WHERE id=? AND guild_id=?",
                (replacement.id, panel["id"], guild.id),
            )
            return "migrated", replacement

        replacement = await sx_panels.envoyer(channel, layout)
        await self.bot.db.execute(
            "UPDATE ticket_panels_v2 SET message_id=? WHERE id=? AND guild_id=?",
            (replacement.id, panel["id"], guild.id),
        )
        return "recreated", replacement

    @commands.group(name="panels", invoke_without_command=True)
    @checks.is_bot_owner()
    async def panels(self, ctx: commands.Context):
        await sx_panels.envoyer(
            ctx, sx_panels.depuis_embed(
                embeds.neutral(
                    "Panneaux SentriX",
                    "Utilise +panels restart pour mettre à jour les panneaux de tickets déjà publiés sur ce serveur sans réinitialiser leurs réglages.",
                )
            ),
        )

    @panels.command(name="restart")
    @checks.is_bot_owner()
    async def restart(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send("Utilise cette commande dans un serveur.")
        if getattr(self, "_running_guilds", None) is None:
            self._running_guilds = set()
        guild = ctx.guild
        if guild.id in self._running_guilds:
            return await ctx.send("Une actualisation est déjà en cours sur ce serveur.")

        self._running_guilds.add(guild.id)
        stats = {
            "updated": 0, "migrated": 0, "recreated": 0,
            "disabled": 0, "no-channel": 0, "no-types": 0,
            "not-published": 0, "errors": 0,
        }
        issues = []
        try:
            rows = await self.bot.db.fetchall(
                "SELECT * FROM ticket_panels_v2 WHERE guild_id=? ORDER BY id",
                (guild.id,),
            )
            for panel in rows:
                try:
                    status, _ = await self.refresh_one(guild, panel)
                    stats[status] += 1
                except (discord.HTTPException, RuntimeError, ValueError) as exc:
                    stats["errors"] += 1
                    logger.warning("Refresh panel %s / guild %s: %s", panel["id"], guild.id, exc)
                    issues.append(f"{panel['name']}: {str(exc)[:120]}")
                except Exception:
                    stats["errors"] += 1
                    logger.exception("Unexpected ticket panel refresh error: %s", panel["id"])
                    issues.append(f"{panel['name']}: erreur technique")
        finally:
            self._running_guilds.discard(guild.id)

        details = (
            f"Mis à jour : **{stats['updated']}**\n"
            f"Anciens panneaux migrés : **{stats['migrated']}**\n"
            f"Messages disparus recréés : **{stats['recreated']}**\n"
            f"Ignorés (désactivés) : **{stats['disabled']}**\n"
            f"Non publiés ou incomplets : **{stats['not-published'] + stats['no-channel'] + stats['no-types']}**\n"
            f"Erreurs : **{stats['errors']}**\n\n"
            "Aucun ticket, type, rôle, salon ou paramètre n'a été réinitialisé."
        )
        if issues:
            details += "\n\n" + "\n".join(f"- {item}" for item in issues[:5])
        details += "\n\nSeuls les panneaux de tickets enregistrés sont concernés ; les panneaux de suggestions, rôles et vérification restent inchangés."
        await sx_panels.envoyer(
            ctx, sx_panels.depuis_embed(embeds.neutral("Actualisation des panneaux", details))
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PanelsRefresh(bot))
