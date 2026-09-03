"""Whitelist ciblée pour les commandes de bannissement SentriX.

Cette couche est volontairement étroite : un propriétaire peut déléguer les commandes
SentriX ``ban``, ``tempban`` et ``unban`` à un membre sans lui donner Administrateur ni
la permission Discord native ``ban_members``.

La whitelist ne contourne jamais :
- la blacklist globale SentriX ;
- un module Modération désactivé ;
- un deny explicite de Setup ;
- les commandes owner-only ;
- les validations métier/hierarchie de la commande de modération.

Elle n'intervient que lorsque la décision finale aurait été refusée UNIQUEMENT parce que
la permission Discord ``ban_members`` manque.
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
from utils import embeds
from utils import sentrix_panels as panels
from . import permission_guard

logger = logging.getLogger("bot.ban-whitelist")

BAN_COMMANDS = frozenset({"ban", "tempban", "unban"})
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ban_command_whitelist (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    added_by INTEGER,
    added_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
)
"""


async def _ensure_schema(bot: commands.Bot) -> None:
    await bot.db.execute(_SCHEMA)


async def _is_whitelisted(bot: commands.Bot, guild_id: int, user_id: int) -> bool:
    try:
        row = await bot.db.fetchone(
            "SELECT 1 FROM ban_command_whitelist WHERE guild_id=? AND user_id=?",
            (int(guild_id), int(user_id)),
        )
    except Exception:
        logger.exception("Lecture whitelist ban impossible guild=%s user=%s", guild_id, user_id)
        return False
    return row is not None


async def _is_global_owner(bot: commands.Bot, user_id: int) -> bool:
    if int(user_id) == PRIMARY_CREATOR_ID or int(user_id) in config.OWNER_IDS:
        return True
    try:
        return bool(await bot.db.is_bot_creator(int(user_id)))
    except Exception:
        return False


async def _can_manage(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Cette commande doit être utilisée dans un serveur.")))
        return False
    if ctx.author.id == ctx.guild.owner_id or await _is_global_owner(ctx.bot, ctx.author.id):
        return True
    await panels.envoyer(
        ctx,
        panels.depuis_embed(
            embeds.error(
                "Seul le **propriétaire du serveur** (ou le propriétaire global de SentriX) "
                "peut modifier la whitelist des commandes de bannissement."
            )
        ),
    )
    return False


async def _add_member(bot: commands.Bot, guild_id: int, user_id: int, actor_id: int) -> None:
    await _ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO ban_command_whitelist (guild_id,user_id,added_by,added_at) VALUES (?,?,?,?) "
        "ON CONFLICT(guild_id,user_id) DO UPDATE SET added_by=excluded.added_by, added_at=excluded.added_at",
        (int(guild_id), int(user_id), int(actor_id), int(time.time())),
    )


async def _remove_member(bot: commands.Bot, guild_id: int, user_id: int) -> None:
    await _ensure_schema(bot)
    await bot.db.execute(
        "DELETE FROM ban_command_whitelist WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )


def _patch_permission_runtime(bot: commands.Bot) -> None:
    current = matrix.evaluate
    if getattr(current, "_sentrix_ban_whitelist", False):
        return

    async def evaluate_with_ban_whitelist(
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
        if name not in BAN_COMMANDS:
            return decision

        # Exception ultra-ciblée : si le refus vient d'un deny Setup, d'un module OFF,
        # de la blacklist, etc., on ne le contourne JAMAIS. Seul le manque de la
        # permission Discord ban_members peut être remplacé par cette whitelist.
        if decision.policy != "discord:ban_members":
            return decision

        guild_id = getattr(guild, "id", None)
        user_id = getattr(author, "id", None)
        if guild_id is None or user_id is None:
            return decision

        if await _is_whitelisted(runtime_bot, int(guild_id), int(user_id)):
            return matrix.AccessDecision(True, policy="user-whitelist:ban")
        return decision

    evaluate_with_ban_whitelist._sentrix_ban_whitelist = True
    evaluate_with_ban_whitelist._sentrix_previous = current

    # Les deux transports d'exécution (+ et /) lisent ces mêmes points d'entrée.
    # Les trois commandes de GESTION de la whitelist restent préfixées uniquement afin
    # de ne pas consommer le budget slash global ni exposer des outils sensibles au menu.
    matrix.evaluate = evaluate_with_ban_whitelist
    permission_guard.evaluate = evaluate_with_ban_whitelist
    permission_guard.access_matrix.evaluate = evaluate_with_ban_whitelist
    bot._sentrix_ban_whitelist_evaluate = evaluate_with_ban_whitelist


def _install_commands(bot: commands.Bot) -> None:
    if bot.get_command("whitelist-ban") is None:

        async def whitelist_ban(ctx: commands.Context, membre: discord.Member):
            if not await _can_manage(ctx):
                return
            if membre.bot:
                return await panels.envoyer(
                    ctx,
                    panels.depuis_embed(embeds.error("Un bot n'a pas besoin d'être ajouté à cette whitelist.")),
                )
            await _add_member(bot, ctx.guild.id, membre.id, ctx.author.id)
            await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.success(
                        f"{membre.mention} peut maintenant utiliser **+ban**, **+tempban** et **+unban** "
                        "via SentriX sans permission Administrateur/Bannir des membres.\n"
                        "Les protections de hiérarchie et les blocages Setup restent actifs."
                    )
                ),
            )

        command = commands.command(
            name="whitelist-ban",
            aliases=["wlban"],
            description="Autoriser un membre non-admin à utiliser les commandes de bannissement SentriX.",
        )(whitelist_ban)
        bot.add_command(command)

    if bot.get_command("unwhitelist-ban") is None:

        async def unwhitelist_ban(ctx: commands.Context, membre: discord.Member):
            if not await _can_manage(ctx):
                return
            await _remove_member(bot, ctx.guild.id, membre.id)
            await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.success(
                        f"{membre.mention} a été retiré de la whitelist ban. "
                        "Sans permission Discord native, **+ban**, **+tempban** et **+unban** lui seront de nouveau refusées."
                    )
                ),
            )

        command = commands.command(
            name="unwhitelist-ban",
            aliases=["unwlban"],
            description="Retirer un membre de la whitelist des commandes de bannissement.",
        )(unwhitelist_ban)
        bot.add_command(command)

    if bot.get_command("whitelist-ban-list") is None:

        async def whitelist_ban_list(ctx: commands.Context):
            if not await _can_manage(ctx):
                return
            await _ensure_schema(bot)
            rows = await bot.db.fetchall(
                "SELECT user_id,added_by,added_at FROM ban_command_whitelist "
                "WHERE guild_id=? ORDER BY added_at DESC LIMIT 50",
                (ctx.guild.id,),
            )
            if not rows:
                return await panels.envoyer(
                    ctx,
                    panels.depuis_embed(embeds.info("Aucun membre n'est dans la whitelist des commandes de bannissement.")),
                )
            lines = []
            for row in rows:
                actor = f"<@{row['added_by']}>" if row["added_by"] else "inconnu"
                lines.append(f"<@{row['user_id']}> — ajouté par {actor} • <t:{int(row['added_at'])}:R>")
            await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.info(
                        "\n".join(lines),
                        title="Whitelist ban SentriX",
                    )
                ),
            )

        command = commands.command(
            name="whitelist-ban-list",
            description="Afficher les membres autorisés à utiliser les commandes de bannissement SentriX.",
        )(whitelist_ban_list)
        bot.add_command(command)


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_ban_whitelist_installed", False):
        return
    try:
        await _ensure_schema(bot)
    except Exception:
        # La couche de permission reste installable même si SQLite est momentanément
        # occupée ; les lectures échoueront alors en refus (fail-closed), jamais en allow.
        logger.exception("Création du schéma whitelist ban impossible au démarrage.")
    _patch_permission_runtime(bot)
    _install_commands(bot)
    bot._sentrix_ban_whitelist_installed = True
    logger.info("Whitelist ban active : +ban/+tempban/+unban délégables par membre, fail-closed.")


__all__ = ["BAN_COMMANDS", "install"]
