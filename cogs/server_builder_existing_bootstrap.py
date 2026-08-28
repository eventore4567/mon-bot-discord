"""Maintenance optionnelle des structures créées par SentriX.

Aucun serveur n'est désormais modifié au redémarrage simplement parce que des salons
portent des noms ressemblant à une ancienne structure SentriX. La maintenance continue
est strictement opt-in via ``server_builder_managed_v2``.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

logger = logging.getLogger("bot.server-builder.bootstrap")


async def ensure_managed_schema(bot: commands.Bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS server_builder_managed_v2 (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            profile TEXT,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL
        )
        """
    )


async def is_managed(bot: commands.Bot, guild_id: int) -> bool:
    await ensure_managed_schema(bot)
    row = await bot.db.fetchone(
        "SELECT enabled FROM server_builder_managed_v2 WHERE guild_id=?",
        (int(guild_id),),
    )
    return bool(row and row["enabled"])


async def set_managed(
    bot: commands.Bot,
    guild_id: int,
    enabled: bool,
    *,
    actor_id: int | None = None,
    profile: str | None = None,
) -> None:
    await ensure_managed_schema(bot)
    await bot.db.execute(
        "INSERT INTO server_builder_managed_v2 (guild_id,enabled,profile,updated_by,updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
        "enabled=excluded.enabled, profile=COALESCE(excluded.profile,server_builder_managed_v2.profile), "
        "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (int(guild_id), 1 if enabled else 0, profile, actor_id, int(time.time())),
    )


async def _bootstrap(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return
    await asyncio.sleep(3)

    from . import server_builder
    from . import server_builder_ready_setup as ready
    from .security_runtime_hardening import apply_recommended_security

    builder = bot.get_cog("ServerBuilder")
    if builder is None:
        return

    await ensure_managed_schema(bot)
    for guild in list(bot.guilds):
        # CRITIQUE : aucune détection par nom de salon. Seul un opt-in enregistré autorise
        # une mutation automatique au redémarrage.
        if not await is_managed(bot, guild.id):
            continue

        choice = ready._find_text_channel(server_builder, guild, "ACCUEIL", "choix-des-rôles")
        shop = ready._find_text_channel(server_builder, guild, "ÉCONOMIE", "boutique")
        announcements = ready._find_text_channel(server_builder, guild, "ACCUEIL", "annonces")
        if choice is None or shop is None or announcements is None:
            logger.warning(
                "Mode géré actif sur %s mais structure incomplète : aucune reconstruction automatique.",
                guild.id,
            )
            continue

        try:
            current = choice.overwrites_for(guild.default_role)
            current.send_messages = False
            current.add_reactions = False
            current.create_public_threads = False
            current.create_private_threads = False
            current.send_messages_in_threads = False
            await choice.set_permissions(
                guild.default_role,
                overwrite=current,
                reason="SentriX : maintenance explicite du salon choix-des-rôles",
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible de verrouiller choix-des-rôles sur %s", guild.id)

        author = guild.owner
        if author is None:
            try:
                author = await guild.fetch_member(guild.owner_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                author = None
        if author is None:
            continue

        try:
            await ready._ensure_role_panels(bot, guild, choice, author.id)
        except Exception:
            logger.exception("Maintenance des panneaux de rôles impossible sur %s", guild.id)
        try:
            await ready._ensure_shop(bot, guild, shop, author.id)
        except Exception:
            logger.exception("Maintenance de la boutique impossible sur %s", guild.id)
        try:
            await apply_recommended_security(bot, guild)
        except Exception:
            logger.exception("Maintenance de la sécurité impossible sur %s", guild.id)
        try:
            await ready._cleanup_old_generated_channels(server_builder, guild)
        except Exception:
            logger.exception("Nettoyage de structure gérée impossible sur %s", guild.id)

        logger.info(
            "Structure SentriX gérée explicitement sur %s (%s), sans republication annonce/suivi.",
            guild.name,
            guild.id,
        )


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_existing_server_bootstrap_installed", False):
        return
    bot._sentrix_existing_server_bootstrap_installed = True
    asyncio.create_task(_bootstrap(bot), name="sentrix-existing-server-bootstrap")


__all__ = ["ensure_managed_schema", "is_managed", "set_managed", "install"]