"""Garde de livraison des logs SentriX.

Ce module ne touche jamais au routage ni aux tables de configuration. Il ajoute
uniquement deux sécurités de transport :
- réparation ciblée des permissions du bot dans le salon configuré avant l'envoi ;
- fallback embed classique si le renderer Components V2 échoue réellement.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import log_categories, log_service

logger = logging.getLogger("bot.logs-delivery-v86")

_REQUIRED_PERMISSIONS = (
    "view_channel",
    "send_messages",
    "embed_links",
    "attach_files",
    "read_message_history",
)


async def _ensure_delivery_permissions(
    guild: discord.Guild,
    channel_id: int | None,
) -> tuple[bool, str]:
    if not channel_id:
        return False, "no_channel"
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False, "channel_missing"
    me = guild.me
    if me is None:
        return False, "bot_member_missing"

    perms = channel.permissions_for(me)
    missing = [name for name in _REQUIRED_PERMISSIONS if not getattr(perms, name, False)]
    if not missing:
        return True, "ok"

    # Un administrateur contourne les overwrites Discord. Si discord.py rapporte malgré
    # tout une permission manquante, on ne modifie rien inutilement.
    if me.guild_permissions.administrator:
        return True, "administrator"

    if not me.guild_permissions.manage_channels:
        return False, "missing:" + ",".join(missing)

    overwrite = channel.overwrites_for(me)
    for name in _REQUIRED_PERMISSIONS:
        setattr(overwrite, name, True)
    try:
        await channel.set_permissions(
            me,
            overwrite=overwrite,
            reason="SentriX : permissions nécessaires aux journaux",
        )
    except discord.Forbidden:
        return False, "forbidden_repair"
    except discord.HTTPException as exc:
        return False, f"http_repair:{getattr(exc, 'status', '?')}"

    perms = channel.permissions_for(me)
    remaining = [name for name in _REQUIRED_PERMISSIONS if not getattr(perms, name, False)]
    if remaining:
        return False, "still_missing:" + ",".join(remaining)

    logger.warning(
        "Permissions logs réparées guild=%s channel=%s",
        guild.id,
        channel.id,
    )
    return True, "repaired"


def _event_type_from_key(event_key: str | None, fallback: str) -> str:
    if event_key:
        parts = str(event_key).split(":")
        if len(parts) >= 2 and parts[0].isdigit():
            candidate = log_categories.canonical_event_type(parts[1])
            if candidate:
                return candidate
    return log_categories.canonical_event_type(fallback)


def _install_send_preflight() -> None:
    current = log_service.send_log
    if getattr(current, "_sentrix_delivery_preflight_v86", False):
        return

    async def send_with_preflight(
        bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
        *,
        view: discord.ui.View | None = None,
        event_key: str | None = None,
        identity_name: str | None = None,
        identity_id: int | None = None,
        identity_icon: str | None = None,
    ) -> bool:
        try:
            event_type = _event_type_from_key(event_key, log_type)
            category = log_categories.category_for(
                event_type,
                embed.title or "",
                embed.description or "",
            )
            config = await log_service.get_log_config(bot, guild.id, category)
            channel_id = config.get("channel_id") if config else None
            if config and config.get("enabled") and channel_id:
                ok, reason = await _ensure_delivery_permissions(guild, channel_id)
                if not ok:
                    logger.warning(
                        "SENTRIX DELIVERY PRECHECK guild=%s category=%s channel=%s failed=%s",
                        guild.id,
                        category,
                        channel_id,
                        reason,
                    )
        except Exception:
            # Le préflight ne doit jamais empêcher le pipeline canonique d'essayer.
            logger.exception("Préflight permissions logs ignoré après erreur.")

        return await current(
            bot,
            guild,
            log_type,
            embed,
            file,
            view=view,
            event_key=event_key,
            identity_name=identity_name,
            identity_id=identity_id,
            identity_icon=identity_icon,
        )

    send_with_preflight._sentrix_delivery_preflight_v86 = True
    send_with_preflight._sentrix_previous = current
    log_service.send_log = send_with_preflight


def _install_renderer_fallback() -> None:
    current = log_service.send_wide_log
    if getattr(current, "_sentrix_renderer_fallback_v86", False):
        return

    async def wide_with_fallback(
        channel,
        embed: discord.Embed,
        *,
        log_type: str,
        old_view: discord.ui.View | None = None,
        extra_file: discord.File | None = None,
        identity_name: str | None = None,
        identity_id: int | None = None,
        identity_icon: str | None = None,
    ) -> bool:
        sent = await current(
            channel,
            embed,
            log_type=log_type,
            old_view=old_view,
            extra_file=extra_file,
            identity_name=identity_name,
            identity_id=identity_id,
            identity_icon=identity_icon,
        )
        if sent:
            return True

        # Ici seulement le renderer V2 a échoué. Le pipeline canonique a déjà validé
        # route, activation et déduplication : un fallback classique ne crée donc pas de
        # doublon fonctionnel.
        try:
            await channel.send(
                embed=embed,
                view=old_view,
                allowed_mentions=log_service.LOG_ALLOWED_MENTIONS,
            )
            logger.warning(
                "SENTRIX LOG FALLBACK SUCCESS channel=%s type=%s",
                getattr(channel, "id", "?"),
                log_type,
            )
            return True
        except discord.HTTPException as exc:
            logger.error(
                "SENTRIX LOG FALLBACK FAILED channel=%s type=%s status=%s code=%s",
                getattr(channel, "id", "?"),
                log_type,
                getattr(exc, "status", None),
                getattr(exc, "code", None),
            )
        except Exception:
            logger.exception(
                "SENTRIX LOG FALLBACK FAILED channel=%s type=%s",
                getattr(channel, "id", "?"),
                log_type,
            )
        return False

    wide_with_fallback._sentrix_renderer_fallback_v86 = True
    wide_with_fallback._sentrix_previous = current
    log_service.send_wide_log = wide_with_fallback


async def _repair_existing(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return
    for guild in list(bot.guilds):
        for category in tuple(log_service.LOG_TYPES):
            try:
                config = await log_service.get_log_config(bot, guild.id, category)
                if not config or not config.get("enabled") or not config.get("channel_id"):
                    continue
                await _ensure_delivery_permissions(guild, int(config["channel_id"]))
            except Exception:
                logger.debug(
                    "Réparation permissions ignorée guild=%s category=%s",
                    guild.id,
                    category,
                    exc_info=True,
                )


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_logs_delivery_v86", False):
        return
    bot._sentrix_logs_delivery_v86 = True
    _install_renderer_fallback()
    _install_send_preflight()
    try:
        bot.loop.create_task(_repair_existing(bot))
    except Exception:
        logger.debug("Tâche de réparation initiale non planifiée.", exc_info=True)
    logger.info("Garde de livraison logs V86 active (permissions + fallback renderer).")


__all__ = ["install"]
