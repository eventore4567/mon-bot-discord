"""Prix par défaut des rôles boutique créés par SentriX."""
from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from .ai_bare_chat_v3 import install as install_ai_bare_chat_v3
from .antinuke_rollback import install as install_antinuke_rollback
from .command_policy_expansion import install as install_command_policy_expansion
from .content_filter_policy import install as install_content_filter_policy
from .feature_systems import install as install_feature_systems
from .help_v8_final_guard import install as install_help_v8_final_guard
from .security_owner_immunity_final import install as install_security_owner_immunity_final
from .security_v2_backup_schema_fix import install as install_security_v2_backup_schema_fix
from .security_v2_runtime import install as install_security_v2_runtime
from .security_verification_v3 import install as install_security_verification_v3
from .slash_command_budget import install as install_slash_command_budget
from .wipe_owner_only import install as install_wipe_owner_only

logger = logging.getLogger("bot.shop-default-prices")

SHOP_DEFAULTS = (
    ("VIP", 500, "Rôle VIP permanent acheté avec la monnaie du serveur."),
    ("Premium", 2_000, "Rôle Premium permanent avec un statut supérieur au VIP."),
)


def _patch_create_server_defaults() -> None:
    from . import server_builder_ready_setup
    server_builder_ready_setup.SHOP_DEFAULTS = SHOP_DEFAULTS


async def _update_existing_shops(bot: commands.Bot) -> None:
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
        if changed:
            economy = bot.get_cog("Economy")
            if economy is not None:
                try:
                    await economy._refresh_shop_panels(guild)
                except Exception:
                    logger.exception("Impossible d'actualiser le panneau boutique sur %s", guild.id)


async def install(bot: commands.Bot) -> None:
    """Installation idempotente des correctifs transversaux SentriX."""
    install_slash_command_budget(bot)
    install_command_policy_expansion()
    install_help_v8_final_guard(bot)

    install_security_v2_backup_schema_fix()
    await install_antinuke_rollback(bot)
    await install_security_v2_runtime(bot)
    install_content_filter_policy(bot)
    install_security_owner_immunity_final(bot)
    await install_feature_systems(bot)
    install_wipe_owner_only(bot)

    # Les deux fonctions ci-dessous sont chargées pendant la finalisation globale, après
    # les cogs IA/Sécurité/Setup. Elles restent dans des modules isolés afin de ne pas
    # recréer une couche concurrente dans main.py.
    await install_ai_bare_chat_v3(bot)
    await install_security_verification_v3(bot)

    _patch_create_server_defaults()
    if getattr(bot, "_sentrix_shop_default_prices_installed", False):
        return
    bot._sentrix_shop_default_prices_installed = True
    asyncio.create_task(_update_existing_shops(bot), name="sentrix-shop-default-prices")
    logger.info("Prix boutique SentriX : VIP=500, Premium=2000.")
