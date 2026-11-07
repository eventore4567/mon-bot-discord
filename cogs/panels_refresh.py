"""Owner-only commands to refresh saved ticket panels without resetting settings.

+panels restart      refresh saved published ticket panels in the current guild
+panels restart all  refresh published ticket panels in every accessible guild
Other panel systems are deliberately excluded until they can be safely rebuilt.
"""

import asyncio
import logging

import discord
from discord.ext import commands

from cogs.setup_v2_core import module_enabled
from utils import checks, embeds, sentrix_panels as sx_panels

logger = logging.getLogger("bot.panel-refresh")


class PanelsRefresh(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._running_guilds: set[int] = set()
        self._global_running = False

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

        # The production cog owns language and emoji rendering; never rebuild options
        # from a different server or a hardcoded fallback.
        layout = await cog.build_public_panel(panel, types)
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
                # Commit the new message reference BEFORE deleting the old one.
                # On DB failure, the existing panel stays untouched.
                await self.bot.db.execute(
                    "UPDATE ticket_panels_v2 SET message_id=? WHERE id=? AND guild_id=?",
                    (replacement.id, panel["id"], guild.id),
                )
            except Exception:
                try:
                    await replacement.delete()
                except discord.HTTPException:
                    logger.warning("Rollback du panneau temporaire impossible.", exc_info=True)
                raise
            try:
                await old.delete()
            except discord.HTTPException:
                # Keeping an old duplicate is safer than losing the saved panel.
                logger.warning("Ancien panneau #%s non supprimé (nouveau panneau enregistré).", old.id)
            return "migrated", replacement

        replacement = await sx_panels.envoyer(channel, layout)
        try:
            await self.bot.db.execute(
                "UPDATE ticket_panels_v2 SET message_id=? WHERE id=? AND guild_id=?",
                (replacement.id, panel["id"], guild.id),
            )
        except Exception:
            try:
                await replacement.delete()
            except discord.HTTPException:
                logger.warning("Rollback du panneau non enregistré impossible.", exc_info=True)
            raise
        return "recreated", replacement

    @staticmethod
    def _new_stats() -> dict[str, int]:
        return {
            "updated": 0, "migrated": 0, "recreated": 0, "disabled": 0,
            "no-channel": 0, "no-types": 0, "not-published": 0, "errors": 0,
        }

    async def refresh_guild(self, guild: discord.Guild, *, published_only: bool = False):
        """Refresh a single guild without copying another guild's config.

        The SELECT is scoped to this guild. Each message is rebuilt from its
        own saved panel settings and related ticket_types rows.
        """
        where = " AND message_id IS NOT NULL" if published_only else ""
        rows = await self.bot.db.fetchall(
            "SELECT * FROM ticket_panels_v2 WHERE guild_id=?" + where + " ORDER BY id",
            (guild.id,),
        )
        stats = self._new_stats()
        errors = []
        for panel in rows:
            try:
                result, _message = await self.refresh_one(guild, panel)
                stats[result] += 1
            except (discord.HTTPException, RuntimeError, ValueError) as exc:
                stats["errors"] += 1
                logger.warning("Panel %s on guild %s: %s", panel["id"], guild.id, exc)
                errors.append(f"Panel #{panel['id']}: {str(exc)[:80]}")
            except Exception:
                stats["errors"] += 1
                logger.exception("Unexpected refresh error for panel %s / guild %s", panel["id"], guild.id)
                errors.append(f"Panel #{panel['id']}: erreur technique")
            # The Discord library obeys rate limits; space out global edits.
            if published_only:
                await asyncio.sleep(0.20)
        return stats, errors, len(rows)

    @commands.group(name="panels", invoke_without_command=True)
    @checks.is_bot_owner()
    async def panels(self, ctx: commands.Context):
        await sx_panels.envoyer(
            ctx, sx_panels.depuis_embed(
                embeds.neutral(
                    "Panneaux SentriX",
                    "Utilisez +panels restart pour le serveur actuel ou "
                    "+panels restart all pour tous les serveurs accessibles. "
                    "Les catégories, réglages et tickets existants sont conservés.",
                )
            ),
        )

    @panels.command(name="restart")
    @checks.is_bot_owner()
    async def restart(self, ctx: commands.Context, scope: str = "server"):
        """Owner-only, opt-in global refresh; 'all' never runs implicitly."""
        scope = scope.strip().casefold()
        if scope not in {"server", "all"}:
            return await ctx.send("Syntaxe : +panels restart ou +panels restart all.")
        if scope == "server" and ctx.guild is None:
            return await ctx.send("Utilisez cette commande dans un serveur.")
        if self._global_running:
            return await ctx.send("Une actualisation globale est déjà en cours.")
        if scope == "server" and ctx.guild.id in self._running_guilds:
            return await ctx.send("Une actualisation est déjà en cours sur ce serveur.")
        if scope == "all" and self._running_guilds:
            return await ctx.send(
                "Une actualisation locale est en cours. Réessayez lorsqu'elle sera terminée."
            )

        global_mode = scope == "all"
        if global_mode:
            self._global_running = True
        else:
            self._running_guilds.add(ctx.guild.id)

        totals = self._new_stats()
        errors: list[str] = []
        guilds_seen = 0
        guilds_with_panels = 0
        inaccessible = 0

        try:
            if global_mode:
                # All persisted published guilds, not just the invoking server.
                published = await self.bot.db.fetchall(
                    "SELECT DISTINCT guild_id FROM ticket_panels_v2 "
                    "WHERE message_id IS NOT NULL ORDER BY guild_id"
                )
                guilds = []
                for row in published:
                    guild = self.bot.get_guild(int(row["guild_id"]))
                    if guild is None:
                        inaccessible += 1
                    else:
                        guilds.append(guild)
                await ctx.send(
                    f"Actualisation lancée pour {len(guilds)} serveur(s) accessibles "
                    "avec des panneaux de tickets publiés. Aucun réglage ne sera réinitialisé."
                )
            else:
                guilds = [ctx.guild]

            for guild in guilds:
                guilds_seen += 1
                try:
                    partial, guild_errors, count = await self.refresh_guild(
                        guild, published_only=global_mode
                    )
                except Exception:
                    logger.exception("Unable to read ticket panel config for guild %s", guild.id)
                    totals["errors"] += 1
                    errors.append(f"Serveur {guild.id}: erreur de lecture")
                    continue
                if count:
                    guilds_with_panels += 1
                for key, value in partial.items():
                    totals[key] += value
                errors.extend(guild_errors[:3])
                if global_mode:
                    await asyncio.sleep(0.30)
        finally:
            if global_mode:
                self._global_running = False
            else:
                self._running_guilds.discard(ctx.guild.id)

        details = (
            f"Portée : **{'tous les serveurs accessibles' if global_mode else 'ce serveur'}**\n"
            f"Serveurs examinés : **{guilds_seen}**\n"
            f"Serveurs avec panneaux : **{guilds_with_panels}**\n"
            f"Panneaux actualisés : **{totals['updated']}**\n"
            f"Anciens panneaux migrés : **{totals['migrated']}**\n"
            f"Panneaux publiés recréés : **{totals['recreated']}**\n"
            f"Ignorés (désactivés) : **{totals['disabled']}**\n"
            f"Non publiés / configuration incomplète : "
            f"**{totals['not-published'] + totals['no-channel'] + totals['no-types']}**\n"
            f"Erreurs : **{totals['errors']}**"
        )
        if inaccessible:
            details += f"\nServeurs absents de cette instance : **{inaccessible}** (non modifiés)"
        if errors:
            details += "\n\nDétails dans les logs SentriX (aucune configuration supprimée)."
        details += (
            "\n\n**Conservé :** titres, descriptions, menus, types, couleurs, salons, "
            "rôles, emojis, formulaires, états ON/OFF et tickets existants."
            "\n**Périmètre sûr :** panneaux de tickets publiés uniquement. "
            "Suggestions, vérification et rôles ne sont pas modifiés."
        )
        await sx_panels.envoyer(
            ctx, sx_panels.depuis_embed(embeds.neutral("Actualisation terminée", details))
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PanelsRefresh(bot))
