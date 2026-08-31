"""SentriX V85 — routage final des journaux nouvellement configurés.

Cette couche corrige deux familles de régressions :
- les listeners officiels qui partageaient encore l'ancienne clé ``log_server`` ;
- les catégories avancées affichées dans +setup (AutoMod, spam, raid, ressources,
  fichiers) qui n'étaient pas toutes des catégories persistantes du routeur canonique.

Le correctif est volontairement installé après READY afin de gagner sur les anciens
monkey-patches chargés pendant le bootstrap.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

import discord
from discord.ext import commands

from utils import embeds, log_categories, log_service

logger = logging.getLogger("bot.logs-route-v85")

_EXTRA_LOG_TYPES: dict[str, dict[str, Any]] = {
    "automod": {
        "label": "AutoMod",
        "category": "AutoMod",
        "legacy_column": None,
        "emits": True,
    },
    "spam": {
        "label": "Protection spam",
        "category": "Protection spam",
        "legacy_column": None,
        "emits": True,
    },
    "raid": {
        "label": "Protection raid",
        "category": "Protection raid",
        "legacy_column": None,
        "emits": True,
    },
    "resources": {
        "label": "Ressources serveur",
        "category": "Ressources serveur",
        "legacy_column": None,
        "emits": True,
    },
    "files": {
        "label": "Fichiers supprimés",
        "category": "Fichiers supprimés",
        "legacy_column": None,
        "emits": True,
    },
}

_DIRECT_ALIASES = {
    "log_messages": "messages",
    "log_members": "members",
    "log_channels": "channels",
    "log_roles": "roles",
    "log_voice": "voice",
    "log_server": "server",
    "log_moderation": "moderation",
    "log_automod": "automod",
    "log_protection": "automod",
    "ticket_log_channel": "tickets",
    "automod": "automod",
    "spam": "spam",
    "raid": "raid",
    "resources": "resources",
    "dossiers": "resources",
    "files": "files",
}

_EVENT_CATEGORY = {
    "automod_link": "automod",
    "automod_word": "automod",
    "automod_spam": "spam",
    "antiraid": "raid",
    "emoji_update": "resources",
    "invite_create": "resources",
    "invite_delete": "resources",
    "sticker_update": "resources",
    "webhook_update": "resources",
    "file_delete": "files",
}


def _norm(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def _install_categories() -> None:
    """Rend les catégories avancées réellement persistantes dans log_config."""
    for key, meta in _EXTRA_LOG_TYPES.items():
        log_service.LOG_TYPES.setdefault(key, dict(meta))
        log_service.CATEGORIES[key] = str(meta["label"])

    log_service._LEGACY_SETTING_KEYS.update(
        {
            "automod": ("automod",),
            "spam": ("spam",),
            "raid": ("raid",),
            "resources": ("resources", "dossiers"),
            "files": ("files",),
        }
    )

    # Événements qui n'existaient pas encore dans le registre officiel.
    log_categories.LOG_REGISTRY.setdefault(
        "sticker_update", ("resources", "🧩", "info")
    )
    log_categories.LOG_REGISTRY.setdefault(
        "webhook_update", ("resources", "🔗", "warning")
    )
    log_categories.LOG_REGISTRY.setdefault(
        "file_delete", ("files", "📎", "error")
    )

    current_resolve = log_service.resolve
    if getattr(current_resolve, "_sentrix_v85_routes", False):
        return

    @functools.wraps(current_resolve)
    def resolve_v85(log_type: str, title: str = "", description: str = ""):
        key = _norm(log_type)

        # Les valeurs du +setup doivent garder exactement leur route. ``dossiers`` est
        # l'ancien nom de la route Ressources serveur.
        direct = _DIRECT_ALIASES.get(key)
        if direct is not None and not title and not description:
            _base_category, emoji, kind = current_resolve(
                "protection" if direct in {"automod", "spam", "raid"}
                else "server" if direct in {"resources", "files"}
                else direct
            )
            return direct, emoji, kind

        base_category, emoji, kind = current_resolve(log_type, title, description)
        override = _EVENT_CATEGORY.get(key)
        if override is not None:
            return override, emoji, kind
        return base_category, emoji, kind

    resolve_v85._sentrix_v85_routes = True
    resolve_v85._sentrix_previous = current_resolve
    log_service.resolve = resolve_v85
    logger.info("Catégories avancées V85 installées dans le routeur canonique.")


def _install_official_listener_router() -> None:
    """Sépare Salons / Rôles / Serveur malgré l'ancienne clé log_server."""
    from . import logs as logs_cog

    logs_cog.CONFIG_TO_LOG_TYPE.update(
        {
            "log_messages": "messages",
            "log_members": "members",
            "log_channels": "channels",
            "log_roles": "roles",
            "log_voice": "voice",
            "log_server": "server",
            "log_moderation": "moderation",
            "log_automod": "automod",
            "log_protection": "automod",
        }
    )

    current_send = logs_cog.Logs._send
    if getattr(current_send, "_sentrix_v85_routes", False):
        return

    @functools.wraps(current_send)
    async def routed_send(
        self,
        guild: discord.Guild,
        config_key: str,
        embed: discord.Embed,
        *,
        view: discord.ui.View | None = None,
        event_key: str | None = None,
    ) -> bool:
        event_type = ""
        if event_key:
            parts = str(event_key).split(":", 2)
            if len(parts) >= 2:
                event_type = parts[1]

        if event_type in {"channel_create", "channel_delete", "channel_update"}:
            config_key = "log_channels"
        elif event_type in {"role_create", "role_delete", "role_update"}:
            config_key = "log_roles"
        elif event_type in {"role_add", "role_remove", "member_roles"}:
            # Le +setup annonce explicitement les rôles attribués dans Membres.
            config_key = "log_members"
        elif event_type == "guild_update":
            config_key = "log_server"
        elif config_key == "log_automod":
            config_key = "log_automod"

        return await current_send(
            self,
            guild,
            config_key,
            embed,
            view=view,
            event_key=event_key,
        )

    routed_send._sentrix_v85_routes = True
    routed_send._sentrix_previous = current_send
    logs_cog.Logs._send = routed_send
    logger.info("Listeners Logs V85 séparés : salons / rôles / membres / serveur.")


async def _migrate_exact_extra_routes(bot: commands.Bot, guild: discord.Guild) -> int:
    """Récupère les choix faits dans +setup avant V85, même avec un nom de salon libre."""
    migrated = 0
    sources = {
        "automod": ("automod",),
        "spam": ("spam",),
        "raid": ("raid",),
        "resources": ("resources", "dossiers"),
        "files": ("files",),
    }
    for category, keys in sources.items():
        chosen = None
        chosen_enabled = None
        for key in keys:
            try:
                row = await bot.db.fetchone(
                    "SELECT channel_id,enabled FROM log_settings "
                    "WHERE guild_id=? AND log_type=?",
                    (guild.id, key),
                )
            except Exception:
                row = None
            if row is not None and row["channel_id"]:
                chosen = int(row["channel_id"])
                chosen_enabled = bool(row["enabled"])
                break
        if chosen is None or guild.get_channel(chosen) is None:
            continue
        try:
            await log_service.set_log_channel(bot, guild.id, category, chosen)
            if chosen_enabled is not False:
                await log_service.set_log_enabled(bot, guild.id, category, True)
            migrated += 1
        except Exception:
            logger.exception(
                "Migration V85 impossible guild=%s category=%s channel=%s",
                guild.id,
                category,
                chosen,
            )
    return migrated


class AdditionalLogEventsV85(commands.Cog, name="AdditionalLogEventsV85"):
    """Événements correspondant aux routes avancées visibles dans +setup."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send(self, guild: discord.Guild, event_type: str, embed: discord.Embed, *, event_key: str):
        await log_service.send_log(
            self.bot,
            guild,
            event_type,
            embed,
            event_key=event_key,
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None or not message.attachments:
            return
        files = "\n".join(
            f"`{attachment.filename}`" for attachment in message.attachments[:10]
        )
        panel = embeds.log_embed(
            "Fichier supprimé",
            fields=(
                ("Auteur", f"<@{message.author.id}>", True),
                ("Salon", f"<#{message.channel.id}>", True),
                ("Fichiers", files[:1024], False),
            ),
        )
        key = log_service.make_event_key(
            message.guild.id,
            "file_delete",
            target_id=message.author.id,
            message_id=message.id,
        )
        await self._send(message.guild, "file_delete", panel, event_key=key)

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        if before == after:
            return
        panel = embeds.log_embed(
            "Emojis du serveur modifiés",
            description=f"Avant : **{len(before)}** · Après : **{len(after)}**",
        )
        key = log_service.make_event_key(
            guild.id,
            "emoji_update",
            discriminator=f"{len(before)}:{len(after)}",
        )
        await self._send(guild, "emoji_update", panel, event_key=key)

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild, before, after):
        if before == after:
            return
        panel = embeds.log_embed(
            "Stickers du serveur modifiés",
            description=f"Avant : **{len(before)}** · Après : **{len(after)}**",
        )
        key = log_service.make_event_key(
            guild.id,
            "sticker_update",
            discriminator=f"{len(before)}:{len(after)}",
        )
        await self._send(guild, "sticker_update", panel, event_key=key)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        guild = invite.guild
        if not isinstance(guild, discord.Guild):
            return
        panel = embeds.log_embed(
            "Invitation créée",
            fields=(("Code", f"`{invite.code}`", True),),
        )
        key = log_service.make_event_key(
            guild.id,
            "invite_create",
            target_id=getattr(invite.inviter, "id", None),
            discriminator=invite.code,
        )
        await self._send(guild, "invite_create", panel, event_key=key)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        guild = invite.guild
        if not isinstance(guild, discord.Guild):
            return
        panel = embeds.log_embed(
            "Invitation supprimée",
            fields=(("Code", f"`{invite.code}`", True),),
        )
        key = log_service.make_event_key(
            guild.id,
            "invite_delete",
            discriminator=invite.code,
        )
        await self._send(guild, "invite_delete", panel, event_key=key)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        panel = embeds.log_embed(
            "Webhooks modifiés",
            fields=(("Salon", f"<#{channel.id}>", True),),
        )
        key = log_service.make_event_key(
            channel.guild.id,
            "webhook_update",
            target_id=channel.id,
            discriminator=discord.utils.utcnow().isoformat(),
        )
        await self._send(channel.guild, "webhook_update", panel, event_key=key)


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return

    # Toutes les couches V73/V74/V83 ont fini de remplacer leurs callbacks à ce stade.
    await asyncio.sleep(6)
    _install_categories()
    _install_official_listener_router()

    try:
        from . import generated_logs_sync as generated

        generated._install_legacy_route_repair()
        generated._install_atomic_log_route_save()
        generated._install_setup_log_callbacks()
        for guild in list(bot.guilds):
            await _migrate_exact_extra_routes(bot, guild)
            await generated.sync_generated_logs(bot, guild)
    except Exception:
        logger.exception("Réaffirmation V85 du +setup Logs impossible.")

    if bot.get_cog("AdditionalLogEventsV85") is None:
        await bot.add_cog(AdditionalLogEventsV85(bot))

    logger.warning("Logs Route Fix V85 actif sur %s serveur(s).", len(bot.guilds))


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_logs_route_v85", False):
        return
    bot._sentrix_logs_route_v85 = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-logs-route-v85")
