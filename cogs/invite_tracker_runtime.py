"""Tracker d'invitations public + page finale ``+setup invitation``.

Cette couche garde les logs techniques existants, mais ajoute le vrai usage attendu par
un serveur : un salon public configurable qui affiche les arrivées et les départs avec
l'invitant détecté et le nombre actuel d'invitations actives.
"""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.invite-tracker-runtime")
CATEGORY = "invitations"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invite_tracker_settings (
    guild_id INTEGER PRIMARY KEY,
    feed_channel_id INTEGER,
    feed_enabled INTEGER NOT NULL DEFAULT 0
)
"""


async def ensure_schema(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_invite_tracker_schema", False):
        return
    await bot.db.execute(_SCHEMA)
    bot._sentrix_invite_tracker_schema = True


async def get_feed_setting(bot: commands.Bot, guild_id: int) -> dict:
    await ensure_schema(bot)
    row = await bot.db.fetchone(
        "SELECT feed_channel_id, feed_enabled FROM invite_tracker_settings WHERE guild_id = ?",
        (guild_id,),
    )
    if not row:
        return {"feed_channel_id": None, "feed_enabled": False}
    return {
        "feed_channel_id": row["feed_channel_id"],
        "feed_enabled": bool(row["feed_enabled"]),
    }


async def set_feed_setting(
    bot: commands.Bot,
    guild_id: int,
    *,
    channel_id: int | None = None,
    enabled: bool | None = None,
) -> None:
    await ensure_schema(bot)
    current = await get_feed_setting(bot, guild_id)
    final_channel = current["feed_channel_id"] if channel_id is None else channel_id
    final_enabled = current["feed_enabled"] if enabled is None else bool(enabled)
    if final_channel is None:
        final_enabled = False
    await bot.db.execute(
        "INSERT INTO invite_tracker_settings(guild_id,feed_channel_id,feed_enabled) VALUES(?,?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET "
        "feed_channel_id=excluded.feed_channel_id, feed_enabled=excluded.feed_enabled",
        (guild_id, final_channel, 1 if final_enabled else 0),
    )


async def clear_feed_channel(bot: commands.Bot, guild_id: int) -> None:
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO invite_tracker_settings(guild_id,feed_channel_id,feed_enabled) VALUES(?,NULL,0) "
        "ON CONFLICT(guild_id) DO UPDATE SET feed_channel_id=NULL, feed_enabled=0",
        (guild_id,),
    )


def _channel_ok(guild: discord.Guild, channel_id: int | None) -> tuple[discord.TextChannel | None, str | None]:
    if not channel_id:
        return None, None
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return None, "Le salon configuré n'existe plus."
    ok, reason = log_service.validate_channel(guild, int(channel_id), needs_file=False)
    if not ok:
        return channel, reason or "Permissions insuffisantes."
    return channel, None


async def _tracker_state(bot: commands.Bot, guild: discord.Guild) -> str:
    feed = await get_feed_setting(bot, guild.id)
    channel, problem = _channel_ok(guild, feed["feed_channel_id"])
    if problem:
        return "! À CORRIGER"
    log_setting = await log_service.get_log_setting(bot, guild.id, CATEGORY)
    log_id = log_setting.get("channel_id")
    if log_id:
        _log_channel, log_problem = _channel_ok(guild, int(log_id))
        if log_problem:
            return "! À CORRIGER"
    if feed["feed_enabled"] and channel is not None:
        return "● ACTIF"
    return "— À CONFIGURER"


async def _build_invitation_page(view) -> None:
    from . import setup_components_v73 as v73

    await ensure_schema(view.bot)
    feed = await get_feed_setting(view.bot, view.guild.id)
    feed_channel, feed_problem = _channel_ok(view.guild, feed["feed_channel_id"])
    feed_enabled = bool(feed["feed_enabled"] and feed_channel and not feed_problem)

    logs = await log_service.get_log_setting(view.bot, view.guild.id, CATEGORY)
    log_id = logs.get("channel_id")
    log_channel = view.guild.get_channel(int(log_id)) if log_id else None
    logs_enabled = bool(logs.get("enabled") and log_channel)

    container = discord.ui.Container(accent_colour=v73.ACCENT)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# 🔗 Invitations\n"
                "Configurez le tracker d'invitations de **SentriX**.\n"
                "Vous pouvez garder un salon de logs techniques séparé et choisir, en dessous, "
                "le salon public où les arrivées et les départs seront affichés."
            ),
            accessory=v73._thumbnail(view.bot),
        )
    )

    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.TextDisplay(
            "### 1. Logs d'invitations\n"
            "Salon réservé aux informations techniques : invitation utilisée, code créé/supprimé et détails de détection.\n"
            f"**Salon :** {log_channel.mention if log_channel else 'Non configuré'} · "
            f"**État :** {'Activé' if logs_enabled else 'Inactif'}"
        )
    )

    log_select = discord.ui.ChannelSelect(
        placeholder="Choisir le salon des logs d'invitations",
        min_values=0,
        max_values=1,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
    )

    async def choose_log_channel(interaction: discord.Interaction):
        chosen = log_select.values[0] if log_select.values else None
        if chosen is not None:
            ok, reason = log_service.validate_channel(view.guild, chosen.id, needs_file=True)
            if not ok:
                return await panels.envoyer(
                    interaction.response,
                    panels.depuis_embed(embeds.error(f"Ce salon ne peut pas recevoir les logs : **{reason}**.")),
                    ephemere=True,
                )
        await log_service.set_log_config(
            view.bot,
            view.guild.id,
            CATEGORY,
            channel_id=chosen.id if chosen else None,
            enabled=chosen is not None,
        )
        await view.refresh(interaction)

    log_select.callback = choose_log_channel
    container.add_item(discord.ui.ActionRow(log_select))

    log_toggle = discord.ui.Button(
        label="Désactiver les logs" if logs_enabled else "Activer les logs",
        style=discord.ButtonStyle.danger if logs_enabled else discord.ButtonStyle.secondary,
    )

    async def toggle_logs(interaction: discord.Interaction):
        current = await log_service.get_log_setting(view.bot, view.guild.id, CATEGORY)
        current_id = current.get("channel_id")
        if not current_id:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.error("Choisissez d'abord un salon de logs.")),
                ephemere=True,
            )
        await log_service.set_log_config(
            view.bot,
            view.guild.id,
            CATEGORY,
            channel_id=current_id,
            enabled=not bool(current.get("enabled")),
        )
        await view.refresh(interaction)

    log_toggle.callback = toggle_logs
    container.add_item(discord.ui.ActionRow(log_toggle))

    container.add_item(discord.ui.Separator())
    problem_text = f"\n⚠️ {feed_problem}" if feed_problem else ""
    container.add_item(
        discord.ui.TextDisplay(
            "### 2. Salon où afficher les invitations\n"
            "C'est le salon visible par les membres, comme sur votre exemple. SentriX y envoie des messages texte simples.\n\n"
            "**Arrivée :** `@membre has been invited by @inviter and has now 10 invites.`\n"
            "**Départ :** `pseudo has left the server. They had been invited by @inviter.`\n\n"
            f"**Salon :** {feed_channel.mention if feed_channel else 'Non configuré'} · "
            f"**État :** {'Activé' if feed_enabled else 'Inactif'}{problem_text}"
        )
    )

    feed_select = discord.ui.ChannelSelect(
        placeholder="Choisir le salon où afficher les invitations",
        min_values=0,
        max_values=1,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
    )

    async def choose_feed_channel(interaction: discord.Interaction):
        chosen = feed_select.values[0] if feed_select.values else None
        if chosen is None:
            await clear_feed_channel(view.bot, view.guild.id)
            return await view.refresh(interaction)
        ok, reason = log_service.validate_channel(view.guild, chosen.id, needs_file=False)
        if not ok:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.error(f"SentriX ne peut pas écrire dans ce salon : **{reason}**.")),
                ephemere=True,
            )
        await set_feed_setting(
            view.bot,
            view.guild.id,
            channel_id=chosen.id,
            enabled=True,
        )
        await view.refresh(interaction)

    feed_select.callback = choose_feed_channel
    container.add_item(discord.ui.ActionRow(feed_select))

    feed_toggle = discord.ui.Button(
        label="Désactiver l'affichage" if feed_enabled else "Activer l'affichage",
        style=discord.ButtonStyle.danger if feed_enabled else discord.ButtonStyle.success,
    )
    feed_test = discord.ui.Button(label="Tester le tracker", style=discord.ButtonStyle.secondary)

    async def toggle_feed(interaction: discord.Interaction):
        current = await get_feed_setting(view.bot, view.guild.id)
        current_id = current.get("feed_channel_id")
        if not current_id:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.error("Choisissez d'abord le salon où afficher les invitations.")),
                ephemere=True,
            )
        await set_feed_setting(
            view.bot,
            view.guild.id,
            channel_id=int(current_id),
            enabled=not bool(current.get("feed_enabled")),
        )
        await view.refresh(interaction)

    async def test_feed(interaction: discord.Interaction):
        current = await get_feed_setting(view.bot, view.guild.id)
        current_id = current.get("feed_channel_id")
        destination, problem = _channel_ok(view.guild, current_id)
        if not current.get("feed_enabled") or destination is None or problem:
            return await panels.envoyer(
                interaction.response,
                panels.depuis_embed(embeds.error("Configurez et activez d'abord le salon d'affichage des invitations.")),
                ephemere=True,
            )
        await destination.send(
            "Invitation tracker test — `@member has been invited by @inviter and has now 1 invite.`",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await panels.envoyer(
            interaction.response,
            panels.depuis_embed(embeds.success("Message de test envoyé dans le salon d'invitations.")),
            ephemere=True,
        )

    feed_toggle.callback = toggle_feed
    feed_test.callback = test_feed
    container.add_item(discord.ui.ActionRow(feed_toggle, feed_test))
    view._add_navigation(container)
    view.add_item(container)


def _patch_setup_v74(bot: commands.Bot) -> None:
    try:
        from . import setup_experience_v74 as v74
    except Exception:
        return

    v74.CATEGORY_META[CATEGORY] = (
        "🔗",
        "Invitations",
        "Tracker d'invitations, salon d'affichage public et logs techniques séparés.",
    )
    if CATEGORY not in v74.CATEGORY_ORDER:
        order = list(v74.CATEGORY_ORDER)
        at = order.index("logs") + 1 if "logs" in order else len(order)
        order.insert(at, CATEGORY)
        v74.CATEGORY_ORDER = tuple(order)

    cls = v74.SentriXSetupV74
    if not getattr(cls, "_sentrix_invite_tracker_page", False):
        previous_page = cls._build_page
        previous_states = cls._effective_states

        async def build_page(self, page: str):
            if page == CATEGORY:
                self.backend.category = CATEGORY
                return await _build_invitation_page(self)
            return await previous_page(self, page)

        async def effective_states(self):
            states = await previous_states(self)
            states[CATEGORY] = await _tracker_state(self.bot, self.guild)
            return states

        build_page._sentrix_invite_tracker_page = True
        effective_states._sentrix_invite_tracker_page = True
        cls._build_page = build_page
        cls._effective_states = effective_states
        cls._sentrix_invite_tracker_page = True


async def _send_feed_message(
    bot: commands.Bot,
    guild: discord.Guild,
    text: str,
) -> None:
    setting = await get_feed_setting(bot, guild.id)
    if not setting.get("feed_enabled"):
        return
    channel, problem = _channel_ok(guild, setting.get("feed_channel_id"))
    if channel is None or problem:
        return
    try:
        await channel.send(
            text,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=True,
                replied_user=False,
            ),
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.warning("Impossible d'envoyer le tracker d'invitations dans guild=%s", guild.id, exc_info=True)


class InviteTrackerRuntime(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        await ensure_schema(self.bot)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        _patch_setup_v74(self.bot)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        # Le cog Invites enregistre d'abord l'invitation détectée. Un court délai rend ce
        # listener indépendant de l'ordre dans lequel discord.py a enregistré les cogs.
        await asyncio.sleep(0.8)
        row = await self.bot.db.get_invited_by(member.guild.id, member.id)
        inviter_id = row["inviter_id"] if row and row["inviter_id"] else None
        if inviter_id:
            stats = await self.bot.db.get_invite_stats(member.guild.id, int(inviter_id))
            count = int(stats.get("active", 0))
            suffix = "invite" if count == 1 else "invites"
            text = (
                f"{member.mention} has been invited by <@{int(inviter_id)}> "
                f"and has now **{count}** {suffix}."
            )
        else:
            text = f"{member.mention} joined the server, but SentriX couldn't determine who invited them."
        await _send_feed_message(self.bot, member.guild, text)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        await asyncio.sleep(0.5)
        row = await self.bot.db.get_invited_by(member.guild.id, member.id)
        inviter_id = row["inviter_id"] if row and row["inviter_id"] else None
        display = discord.utils.escape_markdown(member.display_name or member.name)
        if inviter_id:
            text = f"**{display}** has left the server. They had been invited by <@{int(inviter_id)}> ."
            # Retire l'espace avant le point tout en gardant le format lisible dans le code.
            text = text.replace("> .", ">.")
        else:
            text = f"**{display}** has left the server. Their inviter was unknown."
        await _send_feed_message(self.bot, member.guild, text)


def _register_final_patch(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_invite_tracker_final_listener", False):
        return

    async def final_patch_on_ready():
        _patch_setup_v74(bot)

    bot.add_listener(final_patch_on_ready, "on_ready")
    bot._sentrix_invite_tracker_final_listener = True


async def install(bot: commands.Bot) -> None:
    await ensure_schema(bot)
    _register_final_patch(bot)
    _patch_setup_v74(bot)
    if bot.get_cog("InviteTrackerRuntime") is None:
        await bot.add_cog(InviteTrackerRuntime(bot))
    logger.info("Tracker invitations actif : logs séparés + salon public arrivée/départ.")


__all__ = [
    "InviteTrackerRuntime",
    "ensure_schema",
    "get_feed_setting",
    "set_feed_setting",
    "install",
]
