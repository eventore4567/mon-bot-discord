"""Whitelist globale de commandes SentriX.

Le nom de fichier est conservé pour compatibilité avec le chargeur runtime existant,
mais cette couche remplace l'ancienne whitelist limitée au ban.

Contrat :
- ``+whitelist @membre`` accorde à ce membre les accès staff/admin de SentriX sans lui
  donner de permission Discord native ;
- ``+unwhitelist @membre`` retire cet accès ;
- sans argument, ``+whitelist`` affiche la liste ;
- seuls le propriétaire du serveur et le propriétaire global SentriX peuvent modifier
  la whitelist ;
- les commandes owner-global et guild-owner restent NON délégables ;
- blacklist globale, module désactivé, fonctions IA désactivées et contexte invalide ne
  sont jamais contournés ;
- les validations métier (hiérarchie des rôles, cible interdite, permissions du bot)
  restent actives.

La whitelist est une exception d'AUTORISATION SentriX, pas une modification des rôles
Discord du membre.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord.ext import commands

import config
from database.db import PRIMARY_CREATOR_ID
from utils import access_matrix as matrix
from utils import checks, embeds
from utils import sentrix_panels as panels
from . import permission_guard
from . import setup_v2_core as core

logger = logging.getLogger("bot.global-whitelist")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS global_command_whitelist (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    added_by INTEGER,
    added_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
)
"""

_HARD_DENY_PREFIXES = (
    "global-blacklist",
    "owner-global",
    "guild-owner",
    "module:",
    "ai:",
    "guild-required",
    "invalid",
)

_DELEGABLE_DENY_PREFIXES = (
    "discord:",
    "categorie:",
    "setup:",
    "fail-closed",
)


async def _ensure_schema(bot: commands.Bot) -> None:
    await bot.db.execute(_SCHEMA)


def _cache(bot: commands.Bot) -> set[tuple[int, int]]:
    current = getattr(bot, "_sentrix_global_whitelist_cache", None)
    if isinstance(current, set):
        return current
    current = set()
    bot._sentrix_global_whitelist_cache = current
    return current


async def _load_cache(bot: commands.Bot) -> None:
    await _ensure_schema(bot)
    rows = await bot.db.fetchall("SELECT guild_id,user_id FROM global_command_whitelist")
    cache = _cache(bot)
    cache.clear()
    cache.update((int(row["guild_id"]), int(row["user_id"])) for row in rows)


async def _is_whitelisted(bot: commands.Bot, guild_id: int, user_id: int) -> bool:
    key = (int(guild_id), int(user_id))
    if key in _cache(bot):
        return True
    try:
        row = await bot.db.fetchone(
            "SELECT 1 FROM global_command_whitelist WHERE guild_id=? AND user_id=?",
            key,
        )
    except Exception:
        logger.exception("Lecture whitelist globale impossible guild=%s user=%s", guild_id, user_id)
        return False
    if row is not None:
        _cache(bot).add(key)
        return True
    return False


async def _is_global_owner(bot: commands.Bot, user_id: int) -> bool:
    if int(user_id) == PRIMARY_CREATOR_ID or int(user_id) in config.OWNER_IDS:
        return True
    try:
        return bool(await bot.db.is_bot_creator(int(user_id)))
    except Exception:
        return False


async def _can_manage(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.error("Cette commande doit être utilisée dans un serveur.")),
        )
        return False
    if ctx.author.id == ctx.guild.owner_id or await _is_global_owner(ctx.bot, ctx.author.id):
        return True
    await panels.envoyer(
        ctx,
        panels.depuis_embed(
            embeds.error(
                "Seul le **propriétaire du serveur** ou le propriétaire global de SentriX "
                "peut modifier la whitelist globale."
            )
        ),
    )
    return False


async def _add_member(bot: commands.Bot, guild_id: int, user_id: int, actor_id: int) -> None:
    await _ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO global_command_whitelist (guild_id,user_id,added_by,added_at) "
        "VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
        "added_by=excluded.added_by,added_at=excluded.added_at",
        (int(guild_id), int(user_id), int(actor_id), int(time.time())),
    )
    _cache(bot).add((int(guild_id), int(user_id)))
    try:
        await core.add_trusted(bot, guild_id, user_id, actor_id)
    except Exception:
        logger.exception("Ajout à la whitelist protections impossible ; accès commandes conservé.")


async def _remove_member(bot: commands.Bot, guild_id: int, user_id: int) -> None:
    await _ensure_schema(bot)
    await bot.db.execute(
        "DELETE FROM global_command_whitelist WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )
    _cache(bot).discard((int(guild_id), int(user_id)))
    try:
        await core.remove_trusted(bot, guild_id, user_id)
    except Exception:
        logger.exception("Retrait de la whitelist protections impossible.")


def _delegable_denial(decision: matrix.AccessDecision) -> bool:
    policy = str(getattr(decision, "policy", "") or "")
    if any(policy.startswith(prefix) for prefix in _HARD_DENY_PREFIXES):
        return False
    return any(policy.startswith(prefix) for prefix in _DELEGABLE_DENY_PREFIXES)


def _patch_permission_runtime(bot: commands.Bot) -> None:
    current = matrix.evaluate
    if getattr(current, "_sentrix_global_whitelist", False):
        return

    async def evaluate_with_global_whitelist(
        runtime_bot,
        *,
        command_name: Any,
        author: Any,
        guild: Any,
    ) -> matrix.AccessDecision:
        decision = await current(
            runtime_bot,
            command_name=command_name,
            author=author,
            guild=guild,
        )
        if decision.allowed:
            return decision

        name = matrix.resolve_name(matrix.normalise(command_name))
        if name in matrix.OWNER_ONLY_COMMANDS or name in matrix.GUILD_OWNER_COMMANDS:
            return decision
        if not _delegable_denial(decision):
            return decision

        guild_id = getattr(guild, "id", None)
        user_id = getattr(author, "id", None)
        if guild_id is None or user_id is None:
            return decision

        if await _is_whitelisted(runtime_bot, int(guild_id), int(user_id)):
            return matrix.AccessDecision(True, policy="global-whitelist")
        return decision

    evaluate_with_global_whitelist._sentrix_global_whitelist = True
    evaluate_with_global_whitelist._sentrix_previous = current
    matrix.evaluate = evaluate_with_global_whitelist
    permission_guard.evaluate = evaluate_with_global_whitelist
    permission_guard.access_matrix.evaluate = evaluate_with_global_whitelist
    bot._sentrix_global_whitelist_evaluate = evaluate_with_global_whitelist


def _patch_runtime_permission_helpers(bot: commands.Bot) -> None:
    if getattr(checks, "_sentrix_global_whitelist_helpers", False):
        return

    original_is_mod = checks.is_mod_or_permission
    original_channel_target = checks.check_channel_target

    async def is_mod_or_permission_whitelist(ctx: commands.Context, permission: str) -> bool:
        if ctx.guild is not None and await _is_whitelisted(bot, ctx.guild.id, ctx.author.id):
            return True
        return await original_is_mod(ctx, permission)

    def check_channel_target_whitelist(author: discord.Member, channel) -> str | None:
        guild = author.guild
        if (guild.id, author.id) in _cache(bot):
            me = guild.me
            if me is not None and not channel.permissions_for(me).manage_channels:
                return "SentriX n'a pas la permission **Gérer les salons** dans ce salon."
            return None
        return original_channel_target(author, channel)

    checks.is_mod_or_permission = is_mod_or_permission_whitelist
    checks.check_channel_target = check_channel_target_whitelist
    checks._sentrix_global_whitelist_helpers = True


def _remove_old_management_commands(bot: commands.Bot) -> None:
    for name in (
        "whitelist",
        "unwhitelist",
        "whitelist-ban",
        "unwhitelist-ban",
        "whitelist-ban-list",
    ):
        if bot.get_command(name) is not None:
            bot.remove_command(name)


def _install_commands(bot: commands.Bot) -> None:
    _remove_old_management_commands(bot)

    @commands.command(name="whitelist", aliases=["wl"])
    async def whitelist_command(ctx: commands.Context, membre: discord.Member | None = None):
        if not await _can_manage(ctx):
            return
        await _ensure_schema(bot)
        if membre is None:
            rows = await bot.db.fetchall(
                "SELECT user_id,added_by,added_at FROM global_command_whitelist "
                "WHERE guild_id=? ORDER BY added_at DESC LIMIT 50",
                (ctx.guild.id,),
            )
            if not rows:
                return await panels.envoyer(
                    ctx,
                    panels.depuis_embed(embeds.info("Aucun membre n'est dans la whitelist globale SentriX.")),
                )
            lines = []
            for row in rows:
                actor = f"<@{row['added_by']}>" if row["added_by"] else "inconnu"
                lines.append(
                    f"<@{row['user_id']}> — ajouté par {actor} • <t:{int(row['added_at'])}:R>"
                )
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.info("\n".join(lines), title="Whitelist globale SentriX")
                ),
            )

        if membre.id == ctx.guild.owner_id:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.info("Le propriétaire du serveur possède déjà tous les accès autorisés.")),
            )
        await _add_member(bot, ctx.guild.id, membre.id, ctx.author.id)
        await panels.envoyer(
            ctx,
            panels.depuis_embed(
                embeds.success(
                    f"{membre.mention} est maintenant dans la **whitelist globale SentriX**.\n"
                    "Il peut utiliser les commandes staff/admin du bot sans permission Discord native.\n"
                    "Les commandes réservées au propriétaire et les validations de hiérarchie restent protégées."
                )
            ),
        )

    @commands.command(name="unwhitelist", aliases=["unwl"])
    async def unwhitelist_command(ctx: commands.Context, membre: discord.Member):
        if not await _can_manage(ctx):
            return
        await _remove_member(bot, ctx.guild.id, membre.id)
        await panels.envoyer(
            ctx,
            panels.depuis_embed(
                embeds.success(
                    f"{membre.mention} a été retiré de la **whitelist globale SentriX**."
                )
            ),
        )

    bot.add_command(whitelist_command)
    bot.add_command(unwhitelist_command)


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_global_whitelist_installed", False):
        return
    try:
        await _load_cache(bot)
    except Exception:
        logger.exception("Initialisation whitelist globale impossible ; système en fail-closed.")
    _patch_permission_runtime(bot)
    _patch_runtime_permission_helpers(bot)
    _install_commands(bot)
    bot._sentrix_global_whitelist_installed = True
    bot._sentrix_ban_whitelist_installed = True
    logger.info(
        "Whitelist globale active : +whitelist/+unwhitelist, commandes owner non délégables."
    )


__all__ = ["install"]
