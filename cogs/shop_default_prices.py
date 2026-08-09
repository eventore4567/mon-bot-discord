"""Prix par défaut des rôles boutique créés par SentriX."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from .antinuke_rollback import install as install_antinuke_rollback
from .feature_systems import install as install_feature_systems

logger = logging.getLogger("bot.shop-default-prices")

SHOP_DEFAULTS = (
    ("VIP", 500, "Rôle VIP permanent acheté avec la monnaie du serveur."),
    ("Premium", 2_000, "Rôle Premium permanent avec un statut supérieur au VIP."),
)


def _patch_create_server_defaults() -> None:
    """Applique les nouveaux prix au module +create-server sans dupliquer sa logique."""
    from . import server_builder_ready_setup

    server_builder_ready_setup.SHOP_DEFAULTS = SHOP_DEFAULTS


async def _update_existing_shops(bot: commands.Bot) -> None:
    # Les audits runtime chargent les extensions sans login Discord. Dans ce cas
    # wait_until_ready() lève RuntimeError : ce n'est pas une panne du bot et la tâche
    # doit simplement se terminer proprement au lieu de créer une exception orpheline.
    try:
        await bot.wait_until_ready()
    except RuntimeError:
        return

    for guild in bot.guilds:
        changed = False
        for role_name, price, description in SHOP_DEFAULTS:
            role = discord.utils.get(guild.roles, name=role_name)
            if role is None:
                continue
            row = await bot.db.fetchone(
                "SELECT id FROM shop_items WHERE guild_id = ? AND role_id = ?",
                (guild.id, role.id),
            )
            if row is None:
                continue
            await bot.db.execute(
                "UPDATE shop_items SET name = ?, price = ?, description = ? WHERE id = ?",
                (role.name, price, description, row["id"]),
            )
            changed = True

        if not changed:
            continue
        economy = bot.get_cog("Economy")
        if economy is not None:
            try:
                await economy._refresh_shop_panels(guild)
            except Exception:
                logger.exception("Impossible d'actualiser le panneau boutique sur %s", guild.id)


async def install(bot: commands.Bot) -> None:
    """Installation idempotente par instance de bot, compatible reload et CI.

    Les installateurs transversaux sont volontairement appelés AVANT le garde idempotent :
    ce fichier est repassé après chaque extension par cogs/__init__.py. Ainsi les protections
    anti-nuke sont branchées dès qu'AutoMod devient disponible, et Economy/Levels sont patchés
    exactement lorsqu'ils deviennent disponibles, sans modifier la liste principale des extensions.
    """
    await install_antinuke_rollback(bot)
    await install_feature_systems(bot)
    _patch_create_server_defaults()
    if getattr(bot, "_sentrix_shop_default_prices_installed", False):
        return
    bot._sentrix_shop_default_prices_installed = True
    asyncio.create_task(_update_existing_shops(bot), name="sentrix-shop-default-prices")
    logger.info("Prix boutique SentriX : VIP=500, Premium=2000.")
