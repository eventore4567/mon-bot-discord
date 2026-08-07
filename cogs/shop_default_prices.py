"""Prix par défaut des rôles boutique créés par SentriX."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.shop-default-prices")
_INSTALLED = False

SHOP_DEFAULTS = (
    ("VIP", 500, "Rôle VIP permanent acheté avec la monnaie du serveur."),
    ("Premium", 2_000, "Rôle Premium permanent avec un statut supérieur au VIP."),
)


def _patch_create_server_defaults() -> None:
    """Applique les nouveaux prix au module +create-server sans dupliquer sa logique."""
    from . import server_builder_ready_setup

    server_builder_ready_setup.SHOP_DEFAULTS = SHOP_DEFAULTS


async def _update_existing_shops(bot: commands.Bot) -> None:
    await bot.wait_until_ready()
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
    global _INSTALLED
    _patch_create_server_defaults()
    if _INSTALLED:
        return
    _INSTALLED = True
    asyncio.create_task(_update_existing_shops(bot))
    logger.info("Prix boutique SentriX : VIP=500, Premium=2000.")
