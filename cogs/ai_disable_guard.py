"""Autorité unique du bouton IA activée/désactivée.

Le pipeline moderne +ai vérifiait déjà ai_settings.enabled, mais plusieurs routes legacy
(/sentrix, /ask, summarize, explain, rewrite, fact-check et la conversation naturelle
"SentriX ...") appelaient directement Ai.ask_ai() et contournaient donc le réglage.

Cette couche ne change aucune commande publique. Elle rend le switch serveur réellement
autoritaire pour toute génération IA, tout en laissant +aisetup et +aidiag accessibles
aux administrateurs afin qu'ils puissent réactiver ou diagnostiquer le service.
"""
from __future__ import annotations

import logging
import types

import discord
from discord.ext import commands

from utils import ai_service, embeds

logger = logging.getLogger("bot.ai-disable-guard")

AI_DISABLED_CODE = "__AI_DISABLED__"
AI_DISABLED_MESSAGE = "L'intelligence artificielle est désactivée sur ce serveur. Un administrateur peut la réactiver avec `+aisetup`."


def _install_error_code() -> None:
    if getattr(ai_service, "_sentrix_ai_disabled_code", False):
        return

    original_is_error_code = ai_service.is_error_code
    original_error_title = ai_service.error_title
    original_error_message = ai_service.error_message

    def is_error_code(value: str | None) -> bool:
        return value == AI_DISABLED_CODE or original_is_error_code(value)

    def error_title(value: str | None) -> str:
        if value == AI_DISABLED_CODE:
            return "IA désactivée"
        return original_error_title(value)

    def error_message(value: str | None) -> str:
        if value == AI_DISABLED_CODE:
            return AI_DISABLED_MESSAGE
        return original_error_message(value)

    ai_service.is_error_code = is_error_code
    ai_service.error_title = error_title
    ai_service.error_message = error_message
    ai_service.ERROR_DISABLED = AI_DISABLED_CODE
    ai_service._sentrix_ai_disabled_code = True


async def _ai_enabled(bot: commands.Bot, guild_id: int | None) -> bool:
    if not guild_id:
        return True
    settings = await ai_service.get_settings(bot, int(guild_id))
    return bool(settings.get("enabled", True))


def _guild_id_from_destination(destination, reply_to: discord.Message | None) -> int | None:
    if reply_to is not None and reply_to.guild is not None:
        return int(reply_to.guild.id)
    guild = getattr(destination, "guild", None)
    if guild is not None:
        return int(guild.id)
    channel = getattr(destination, "channel", None)
    guild = getattr(channel, "guild", None)
    return int(guild.id) if guild is not None else None


def install(bot: commands.Bot) -> None:
    """Installe le garde après le chargement du Cog Ai. Idempotent."""
    _install_error_code()

    cog = bot.get_cog("Ai")
    if cog is None or getattr(cog, "_sentrix_ai_disable_guard", False):
        return

    original_ask = cog.ask_ai
    original_confidence = cog.ask_ai_with_confidence
    original_send = cog.send_sentrix_reply

    async def guarded_ask_ai(
        self,
        prompt,
        history: list | None = None,
        author_name: str | None = None,
        *,
        guild_id: int | None = None,
        channel_id: int | None = None,
        user_id: int | None = None,
        command: str | None = None,
    ) -> str:
        if guild_id and not await _ai_enabled(self.bot, guild_id):
            return AI_DISABLED_CODE
        return await original_ask(
            prompt,
            history,
            author_name,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            command=command,
        )

    async def guarded_confidence(
        self,
        prompt: str,
        history: list | None = None,
        *,
        guild_id: int | None = None,
        channel_id: int | None = None,
        user_id: int | None = None,
        command: str | None = None,
    ) -> tuple[str, int]:
        if guild_id and not await _ai_enabled(self.bot, guild_id):
            return AI_DISABLED_CODE, 0
        return await original_confidence(
            prompt,
            history,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            command=command,
        )

    async def guarded_send_sentrix_reply(
        self,
        destination,
        author,
        question: str,
        *,
        reply_to: discord.Message | None = None,
    ):
        guild_id = _guild_id_from_destination(destination, reply_to)
        if guild_id and not await _ai_enabled(self.bot, guild_id):
            # Message naturel/mention : silence total lorsque l'IA est coupée. Cela évite
            # que le bot semble encore "discuter" alors que l'admin vient de la désactiver.
            if reply_to is not None:
                return None
            # Commande explicite /sentrix ou +sentrix : informer l'utilisateur au lieu de
            # laisser la commande sans réponse.
            return await destination.send(embed=embeds.info(AI_DISABLED_MESSAGE))
        return await original_send(destination, author, question, reply_to=reply_to)

    guarded_ask_ai._sentrix_ai_disable_guard = True
    guarded_confidence._sentrix_ai_disable_guard = True
    guarded_send_sentrix_reply._sentrix_ai_disable_guard = True

    cog.ask_ai = types.MethodType(guarded_ask_ai, cog)
    cog.ask_ai_with_confidence = types.MethodType(guarded_confidence, cog)
    cog.send_sentrix_reply = types.MethodType(guarded_send_sentrix_reply, cog)
    cog._sentrix_ai_disable_guard = True

    logger.info("IA : le réglage enabled bloque désormais toutes les générations legacy et naturelles.")


__all__ = ["install", "AI_DISABLED_CODE"]
