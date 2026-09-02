"""Finitions V17 : fenêtres boutique, quota image IA et autocomplete ciblé."""
from __future__ import annotations

import io
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
from database.db import now
from utils import ai_service, checks, embeds, helpers
from utils import sentrix_panels as panels
from .v17_shared import ensure_schema, register_command_policy, state

logger = logging.getLogger("bot.v17-extras")


class V17Extras(commands.Cog, name="V17Extras"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await ensure_schema(self.bot)

    @commands.hybrid_command(name="shopwindow", description="Définir une période de disponibilité pour un article.", with_app_command=False)
    @checks.is_owner_or_admin_for("economie")
    async def shopwindow(self, ctx: commands.Context, item_id: int, debut: str = "now", duree: str = "7j"):
        item = await self.bot.db.fetchone("SELECT name FROM shop_items WHERE guild_id=? AND id=?", (ctx.guild.id, item_id))
        if not item:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Article introuvable.')))
        start_at = now()
        if debut.casefold() not in {"now", "maintenant", "0"}:
            start_delay = helpers.parse_duration(debut)
            if start_delay is None or start_delay < 0:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Début invalide. Exemples : `now`, `1h`, `2j`.')))
            start_at += start_delay
        duration = helpers.parse_duration(duree)
        if duration is None or duration <= 0:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide. Exemples : `12h`, `7j`, `30j`.')))
        end_at = start_at + duration
        await self.bot.db.execute(
            "INSERT INTO v17_shop_rules (guild_id,item_id,stock,available_from,available_until,updated_at) VALUES (?,?,-1,?,?,?) "
            "ON CONFLICT(guild_id,item_id) DO UPDATE SET available_from=excluded.available_from,available_until=excluded.available_until,updated_at=excluded.updated_at",
            (ctx.guild.id, item_id, start_at, end_at, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"**{item['name']}** sera disponible de <t:{start_at}:F> à <t:{end_at}:F>.")))

    @commands.hybrid_command(name="shopwindowclear", description="Retirer la période de disponibilité d'un article.", with_app_command=False)
    @checks.is_owner_or_admin_for("economie")
    async def shopwindowclear(self, ctx: commands.Context, item_id: int):
        await self.bot.db.execute(
            "UPDATE v17_shop_rules SET available_from=NULL,available_until=NULL,updated_at=? WHERE guild_id=? AND item_id=?",
            (now(), ctx.guild.id, item_id),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success('Fenêtre de disponibilité supprimée pour cet article.')))


def install_image_role_quota(bot: commands.Bot) -> None:
    cog = bot.get_cog("Ai")
    command = bot.get_command("image")
    if cog is None or command is None or getattr(command.callback, "_sentrix_v17_image_quota", False):
        return
    from .v17_ai_economy_games import _ai_gate, _role_ai_policy

    original = command.callback

    async def image_v17(self, ctx: commands.Context, *, description: str):
        guild_id = ctx.guild.id if ctx.guild else None
        channel_id = ctx.channel.id
        priority = 0
        if guild_id:
            settings = await ai_service.get_settings(self.bot, guild_id)
            if not settings["enabled"]:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'IA est désactivée sur ce serveur.")))
            if not ai_service.is_channel_allowed(settings, channel_id):
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'IA n'est pas autorisée dans ce salon.")))
            role_ids = [role.id for role in getattr(ctx.author, "roles", ())]
            if not ai_service.is_role_allowed(settings, role_ids):
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Vous n'avez pas le rôle nécessaire pour utiliser l'IA dans ce serveur.")))
            problem = ai_service.moderate_input(description, max_length=settings["max_question_length"])
            if problem:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(problem)))
            role_policy = await _role_ai_policy(self.bot, guild_id, ctx.author.id)
            daily_limit = int(role_policy["daily_limit"] if role_policy else settings["daily_limit"])
            priority = int(role_policy["priority"] if role_policy else 0)
            used_today = await ai_service.get_daily_usage(self.bot, guild_id, ctx.author.id)
            if used_today >= daily_limit:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Limite IA quotidienne atteinte (**{daily_limit}/jour** pour votre niveau d'accès).")))

        thinking = None
        if ctx.interaction:
            await ctx.defer()
        else:
            thinking = await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Génération rapide de l'image 4K en cours…")))

        async with ctx.typing():
            async with _ai_gate(self.bot).slot(priority):
                result = await ai_service.generate_image(
                    description,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=ctx.author.id,
                )
        if thinking:
            try:
                await thinking.delete()
            except discord.HTTPException:
                pass
        if not result.ok:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title=ai_service.error_title(result.error), description=ai_service.error_message(result.error), kind='danger')))
        try:
            image_bytes = self._prepare_4k_discord_jpeg(result.data)
        except (OSError, ValueError):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'image a été générée mais son fichier est trop lourd pour Discord.")))
        if guild_id:
            await ai_service.record_usage(self.bot, guild_id, ctx.author.id, tokens_estimate=0)
        filename = "sentrix-image-4k.jpg"
        file = discord.File(io.BytesIO(image_bytes), filename=filename)
        e = await self._embed(guild_id, title="Image 4K générée", description=f"**Demande :** {description[:1000]}")
        e.add_field(name="Résolution", value="3840 × 2160", inline=True)
        e.add_field(name="Modèle", value=result.model or config.OPENAI_IMAGE_MODEL, inline=True)
        e.set_image(url=f"attachment://{filename}")
        await ctx.send(embed=e, file=file)

    image_v17._sentrix_v17_image_quota = True
    image_v17._sentrix_original = original
    command.callback = image_v17


async def _event_autocomplete(_interaction: discord.Interaction, current: str):
    from .v17_tickets_logs import EVENT_LABELS
    needle = current.casefold().strip()
    return [
        app_commands.Choice(name=label[:100], value=key)
        for key, label in EVENT_LABELS.items()
        if not needle or needle in key.casefold() or needle in label.casefold()
    ][:25]


async def _sanction_action_autocomplete(_interaction: discord.Interaction, current: str):
    values = ("mute", "tempban", "ban")
    needle = current.casefold().strip()
    return [app_commands.Choice(name=value, value=value) for value in values if not needle or needle in value][:25]


async def _nuke_action_autocomplete(_interaction: discord.Interaction, current: str):
    values = ("all", "channel_delete", "role_delete")
    needle = current.casefold().strip()
    return [app_commands.Choice(name=value, value=value) for value in values if not needle or needle in value][:25]


def _bind_autocomplete(command, parameter: str, callback, marker: tuple[str, str], bot: commands.Bot) -> None:
    installed = state(bot).setdefault("v17_autocomplete_installed", set())
    if marker in installed or command is None:
        return
    try:
        command.autocomplete(parameter)(callback)
        installed.add(marker)
    except (TypeError, ValueError, AttributeError):
        return


def install_autocomplete(bot: commands.Bot) -> None:
    """Complète les champs texte ; Member/Role/Channel utilisent déjà les sélecteurs natifs."""
    log_group = bot.tree.get_command("logevent")
    if isinstance(log_group, app_commands.Group):
        for sub_name in ("on", "off"):
            _bind_autocomplete(log_group.get_command(sub_name), "evenement", _event_autocomplete, (f"logevent {sub_name}", "evenement"), bot)

    sanction_group = bot.tree.get_command("sanctionpolicy")
    if isinstance(sanction_group, app_commands.Group):
        _bind_autocomplete(sanction_group.get_command("set"), "action", _sanction_action_autocomplete, ("sanctionpolicy set", "action"), bot)

    nuke_group = bot.tree.get_command("nukewhitelist")
    if isinstance(nuke_group, app_commands.Group):
        for sub_name in ("user", "role"):
            _bind_autocomplete(nuke_group.get_command(sub_name), "action", _nuke_action_autocomplete, (f"nukewhitelist {sub_name}", "action"), bot)


def install(bot: commands.Bot, extension_name: str = "") -> None:
    register_command_policy(economy={"shopwindow", "shopwindowclear"})
    if bot.get_cog("V17Extras") is None:
        try:
            import asyncio
            asyncio.get_running_loop().create_task(bot.add_cog(V17Extras(bot)), name="sentrix-v17-extras-cog")
        except RuntimeError:
            pass
    install_image_role_quota(bot)
    install_autocomplete(bot)


__all__ = ["install"]
