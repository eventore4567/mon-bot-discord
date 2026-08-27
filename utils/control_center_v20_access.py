"""Politique d’accès centralisée SentriX V20."""
from __future__ import annotations

from types import MethodType

import discord
from discord.ext import commands

import config
import main as bot_main
from database.db import PRIMARY_CREATOR_ID
from utils import checks
from utils.control_center_v20_meta import _human_permission

async def _is_global_manager(bot: commands.Bot, user_id: int) -> bool:
    try:
        row = await bot.db.fetchone("SELECT user_id FROM global_bot_managers WHERE user_id = ?", (int(user_id),))
        return row is not None
    except Exception:
        return False


async def _is_global_owner(ctx_or_interaction) -> bool:
    user = getattr(ctx_or_interaction, "author", None) or getattr(ctx_or_interaction, "user", None)
    if user is None:
        return False
    if user.id == PRIMARY_CREATOR_ID or user.id in getattr(config, "OWNER_IDS", set()):
        return True
    bot = getattr(ctx_or_interaction, "bot", None) or getattr(ctx_or_interaction, "client", None)
    try:
        return bool(await bot.db.is_bot_creator(user.id))
    except Exception:
        return False


async def _can_open_setup(bot: commands.Bot, guild: discord.Guild | None, member) -> bool:
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member.id == PRIMARY_CREATOR_ID or member.id in getattr(config, "OWNER_IDS", set()):
        return True
    try:
        if await bot.db.is_bot_creator(member.id) or await _is_global_manager(bot, member.id):
            return True
    except Exception:
        pass
    return member.id == guild.owner_id or member.guild_permissions.administrator


async def _install_global_manager_table(bot: commands.Bot) -> None:
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS global_bot_managers ("
        "user_id INTEGER PRIMARY KEY, added_by INTEGER NOT NULL, added_at INTEGER NOT NULL)"
    )


def _install_strict_permission_policy(bot: commands.Bot) -> None:
    """Installe le second verrou central sans utiliser les anciens managers par serveur."""
    if getattr(bot, "_sentrix_permission_policy_v20", False):
        return

    async def strict_permission_check(self, ctx: commands.Context) -> bool:
        command = ctx.command
        if command is None:
            return True
        root = command.root_parent or command
        name = root.name.casefold()
        owner = await checks.is_verified_bot_owner(ctx)
        global_manager = await _is_global_manager(self, ctx.author.id)

        if name in bot_main.PUBLIC_COMMANDS:
            return True
        if name in bot_main.OWNER_ONLY_COMMANDS or name.startswith("sentrix-manager-"):
            if owner:
                return True
            raise checks.BotPermissionError("Cette commande est réservée au **propriétaire global de SentriX**.")
        if name in bot_main.CUSTOM_PERMISSION_COMMANDS:
            if owner or await checks.can_use_embed_builder(ctx):
                return True
            raise checks.BotPermissionError("Permission requise : **Gérer les messages** ou accès explicitement autorisé.")

        required = bot_main.DISCORD_PERMISSION_COMMANDS.get(name)
        if required:
            if owner:
                return True
            member = ctx.author if isinstance(ctx.author, discord.Member) else None
            if member is not None and getattr(member.guild_permissions, required, False):
                return True
            raise checks.BotPermissionError(f"Permission requise : **{_human_permission(required)}**.")

        for category, names in bot_main.CATEGORY_COMMANDS.items():
            if name not in names:
                continue
            if owner or global_manager:
                return True
            member = ctx.author if isinstance(ctx.author, discord.Member) else None
            if member is not None and ctx.guild is not None and (
                member.id == ctx.guild.owner_id or member.guild_permissions.administrator
            ):
                return True
            raise checks.BotPermissionError("Permission requise : **Administrateur**.")

        if owner or global_manager:
            return True
        member = ctx.author if isinstance(ctx.author, discord.Member) else None
        if member is not None and ctx.guild is not None and (
            member.id == ctx.guild.owner_id or member.guild_permissions.administrator
        ):
            return True
        raise checks.BotPermissionError(
            "Cette commande n'a pas encore de niveau public validé. Permission requise : **Administrateur**."
        )

    strict_permission_check._sentrix_permission_policy_v20 = True
    bot.global_permission_check = MethodType(strict_permission_check, bot)
    bot._sentrix_permission_policy_v20 = True
