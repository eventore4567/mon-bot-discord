"""Budget global de commandes slash SentriX.

Discord impose une limite stricte au nombre de commandes application globales. SentriX
possède beaucoup plus de commandes texte que cette limite ; sans garde, charger un cog tardif
peut lever CommandLimitReached et empêcher AUSSI ses commandes + de se charger.

Cette couche conserve les commandes slash enregistrées en premier et, une fois un budget sûr
atteint, ignore uniquement les nouvelles racines slash globales. Les commandes préfixées +
continuent donc toutes de se charger. Les commandes guild-scoped et context menus ne sont pas
concernés par ce budget chat-input global.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.slash-budget")
GLOBAL_CHAT_INPUT_BUDGET = 95


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_slash_budget_installed", False):
        return
    bot._sentrix_slash_budget_installed = True

    tree = bot.tree
    original_add = tree.add_command
    skipped: list[str] = []
    bot._sentrix_skipped_global_slash = skipped

    def _call_original(command, *, guild=None, guilds=None, override: bool = False):
        # discord.py utilise un sentinel interne pour distinguer « argument absent » de
        # « argument explicitement None ». Ne jamais transmettre guild=None ET guilds=None,
        # sinon _retrieve_guild_ids considère que les deux options ont été fournies.
        kwargs = {"override": override}
        if guild is not None:
            kwargs["guild"] = guild
        if guilds is not None:
            kwargs["guilds"] = guilds
        return original_add(command, **kwargs)

    def budgeted_add(
        _tree,
        command,
        *,
        guild=None,
        guilds=None,
        override: bool = False,
    ):
        # Les limites de commandes de serveur sont indépendantes. On ne touche donc jamais
        # aux commandes explicitement guild-scoped.
        if guild is not None or guilds is not None:
            return _call_original(command, guild=guild, guilds=guilds, override=override)

        # ContextMenu a ses propres quotas. Le budget ici vise uniquement les commandes /
        # de type chat-input (Command et Group).
        if isinstance(command, (app_commands.Command, app_commands.Group)):
            try:
                roots = tree.get_commands(guild=None, type=discord.AppCommandType.chat_input)
                root_count = len(roots)
            except Exception:
                roots = tree.get_commands(guild=None)
                root_count = sum(
                    1 for item in roots
                    if isinstance(item, (app_commands.Command, app_commands.Group))
                )

            # override d'une commande existante ne consomme pas une nouvelle racine.
            name = str(getattr(command, "name", "") or "")
            existing = next((item for item in roots if getattr(item, "name", None) == name), None)
            if existing is None and root_count >= GLOBAL_CHAT_INPUT_BUDGET:
                skipped.append(name or repr(command))
                logger.warning(
                    "Budget slash SentriX atteint (%s racines) : /%s non enregistré ; "
                    "la commande + reste disponible.",
                    GLOBAL_CHAT_INPUT_BUDGET,
                    name or "inconnue",
                )
                return None

        return _call_original(command, override=override)

    tree.add_command = MethodType(budgeted_add, tree)
    logger.info("Budget slash SentriX actif : maximum %s commandes chat-input globales.", GLOBAL_CHAT_INPUT_BUDGET)
