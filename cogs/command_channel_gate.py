"""Blocage des commandes SentriX par salon, commun aux commandes + et /."""
from __future__ import annotations

import inspect
import logging

import discord
from discord.ext import commands

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.command-channel-gate")
BLOCKED_MESSAGE = "Les commandes sont désactivées dans ce salon."


class CommandChannelBlocked(commands.CheckFailure):
    """Le garde a déjà répondu en texte brut : aucun rendu d'erreur à ajouter."""


async def is_command_channel_blocked(
    bot: commands.Bot,
    guild_id: int | None,
    channel_id: int | None,
    command_name: str | None = None,
) -> bool:
    if guild_id is None or channel_id is None:
        return False
    try:
        row = await bot.db.fetchone(
            "SELECT 1 FROM command_blocked_channels "
            "WHERE guild_id = ? AND channel_id = ? LIMIT 1",
            (int(guild_id), int(channel_id)),
        )
        if row is not None:
            return True

        name = str(command_name or "").strip().lower()
        if not name:
            return False
        row = await bot.db.fetchone(
            "SELECT 1 FROM command_channel_blocks "
            "WHERE guild_id = ? AND channel_id = ? AND command_name = ? LIMIT 1",
            (int(guild_id), int(channel_id), name),
        )
        return row is not None
    except Exception:
        logger.exception("Lecture des restrictions de commandes par salon impossible.")
        return False


SCHEMA_SALONS_CATEGORIE = """
CREATE TABLE IF NOT EXISTS category_allowed_channels (
    guild_id   INTEGER NOT NULL,
    category   TEXT    NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, category, channel_id)
)
"""


async def salons_autorises(bot: commands.Bot, guild_id: int, categorie: str) -> set[int]:
    """Salons où une catégorie est autorisée. Vide = aucune restriction."""
    try:
        await bot.db.execute(SCHEMA_SALONS_CATEGORIE)
        lignes = await bot.db.fetchall(
            "SELECT channel_id FROM category_allowed_channels WHERE guild_id = ? AND category = ?",
            (int(guild_id), str(categorie)),
        )
    except Exception:
        # Une panne de lecture ne doit jamais bloquer une commande : sans
        # réponse, on considère qu'aucune restriction n'existe.
        logger.exception("Lecture des salons autorisés impossible (guild=%s).", guild_id)
        return set()
    return {int(l["channel_id"]) for l in (lignes or [])}


async def categorie_hors_salon(
    bot: commands.Bot, guild_id: int | None, channel_id: int | None,
    command_name: str | None, cog_name: str | None = None,
) -> tuple[bool, set[int]]:
    """La commande est-elle hors des salons autorisés pour sa catégorie ?

    Complète la liste de BLOCAGE existante par une liste d'AUTORISATION : un
    serveur peut confiner les jeux à #jeux sans bloquer salon par salon. Avec
    74 commandes de jeu, c'est le besoin le plus courant et il était
    impossible à exprimer.

    Sans aucune ligne pour la catégorie, rien ne change : les serveurs qui
    n'ont rien configuré gardent exactement le comportement d'aujourd'hui.
    """
    if guild_id is None or channel_id is None or not command_name:
        return False, set()
    try:
        from utils import command_categories
    except Exception:  # pragma: no cover
        return False, set()
    categorie = command_categories.resoudre(cog_name, command_name)
    autorises = await salons_autorises(bot, guild_id, categorie)
    if not autorises:
        return False, set()
    return int(channel_id) not in autorises, autorises


def message_hors_salon(autorises: set[int]) -> str:
    """Dit où aller, au lieu d'un refus sec."""
    if not autorises:
        return BLOCKED_MESSAGE
    salons = " ".join(f"<#{identifiant}>" for identifiant in sorted(autorises)[:5])
    if len(autorises) > 5:
        salons += f" et {len(autorises) - 5} autre(s)"
    return f"Cette commande s'utilise dans {salons}."


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_command_channel_gate", False):
        return

    async def prefix_gate(ctx: commands.Context) -> bool:
        if getattr(ctx, "command", None) is None or ctx.guild is None:
            return True
        channel_id = getattr(getattr(ctx, "channel", None), "id", None)
        command = getattr(ctx, "command", None)
        root = getattr(command, "root_parent", None) or command
        command_name = str(getattr(root, "name", "") or "").strip().lower()
        if await is_command_channel_blocked(
            bot, ctx.guild.id, channel_id, command_name
        ):
            await panels.texte_court(ctx, BLOCKED_MESSAGE)
            raise CommandChannelBlocked(BLOCKED_MESSAGE)

        hors, autorises = await categorie_hors_salon(
            bot, ctx.guild.id, channel_id, command_name,
            getattr(command, "cog_name", None),
        )
        if hors:
            message = message_hors_salon(autorises)
            await panels.texte_court(ctx, message)
            raise CommandChannelBlocked(message)
        return True

    prefix_gate._sentrix_command_channel_gate = True
    bot.add_check(prefix_gate)

    previous_tree_check = bot.tree.interaction_check

    async def slash_gate(interaction: discord.Interaction) -> bool:
        previous = previous_tree_check(interaction)
        if inspect.isawaitable(previous):
            previous = await previous
        if previous is False:
            return False
        if (
            interaction.type != discord.InteractionType.application_command
            or interaction.guild_id is None
        ):
            return True

        channel_id = (
            getattr(interaction, "channel_id", None)
            or getattr(getattr(interaction, "channel", None), "id", None)
        )
        data = getattr(interaction, "data", None)
        command_name = (
            str(data.get("name") or "").strip().lower()
            if isinstance(data, dict) else ""
        )
        if await is_command_channel_blocked(
            bot, interaction.guild_id, channel_id, command_name
        ):
            await panels.texte_court(interaction.response, BLOCKED_MESSAGE, ephemere=True)
            return False

        jumelle = bot.get_command(command_name) if command_name else None
        hors, autorises = await categorie_hors_salon(
            bot, interaction.guild_id, channel_id, command_name,
            getattr(jumelle, "cog_name", None),
        )
        if hors:
            await panels.texte_court(
                interaction.response, message_hors_salon(autorises), ephemere=True,
            )
            return False
        return True

    slash_gate._sentrix_command_channel_gate = True
    slash_gate._sentrix_previous_tree_check = previous_tree_check
    bot.tree.interaction_check = slash_gate
    bot._sentrix_command_channel_gate = True
    logger.info("Blocage des commandes par salon actif pour + et /.")


async def setup(bot: commands.Bot):
    install(bot)


__all__ = [
    "BLOCKED_MESSAGE", "CommandChannelBlocked",
    "is_command_channel_blocked", "install",
]
