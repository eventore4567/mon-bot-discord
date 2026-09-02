"""Autorité unique du bouton IA activée/désactivée.

Le réglage ai_settings.enabled est vérifié à deux niveaux :
- avant la conversation naturelle, pour rester totalement silencieux quand l'IA est OFF ;
- dans utils.ai_service.generate()/generate_image(), afin qu'aucune ancienne commande,
  aucun runtime ou appel direct ne puisse contourner le réglage.

+aisetup et +aidiag restent disponibles aux administrateurs pour réactiver ou diagnostiquer.
Cette couche sert aussi de point de rattachement sûr aux runtimes bot-only V14/V15/V16, car
stability_runtime l'appelle après chaque extension chargée.
"""
from __future__ import annotations

import asyncio
import logging
import types

import discord
from discord.ext import commands

from utils import ai_service, embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.ai-disable-guard")

AI_DISABLED_CODE = "__AI_DISABLED__"
AI_DISABLED_MESSAGE = (
    "L'intelligence artificielle est désactivée sur ce serveur. "
    "Un administrateur peut la réactiver avec `+aisetup`."
)


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


def _install_service_guard(bot: commands.Bot) -> None:
    """Verrou final directement autour des appels OpenAI texte et image."""
    current_generate = ai_service.generate
    if not getattr(current_generate, "_sentrix_ai_enabled_engine_guard", False):
        async def guarded_generate(*args, **kwargs):
            guild_id = kwargs.get("guild_id")
            if guild_id and not await _ai_enabled(bot, int(guild_id)):
                return ai_service.AiResult(
                    error=AI_DISABLED_CODE,
                    model_key=kwargs.get("model_key"),
                )
            return await current_generate(*args, **kwargs)

        guarded_generate._sentrix_ai_enabled_engine_guard = True
        guarded_generate._sentrix_original = current_generate
        ai_service.generate = guarded_generate

    current_image = ai_service.generate_image
    if not getattr(current_image, "_sentrix_ai_enabled_engine_guard", False):
        async def guarded_generate_image(*args, **kwargs):
            guild_id = kwargs.get("guild_id")
            if guild_id and not await _ai_enabled(bot, int(guild_id)):
                return ai_service.ImageResult(
                    error=AI_DISABLED_CODE,
                    model=getattr(__import__("config"), "OPENAI_IMAGE_MODEL", None),
                )
            return await current_image(*args, **kwargs)

        guarded_generate_image._sentrix_ai_enabled_engine_guard = True
        guarded_generate_image._sentrix_original = current_image
        ai_service.generate_image = guarded_generate_image


def _install_core_runtimes(bot: commands.Bot) -> None:
    """V14/V15/V16 ne dépendent plus du chargement réussi d'une commande précise."""
    try:
        from .bot_v14_core import install as install_v14
        install_v14(bot)
    except Exception:
        logger.exception("V14 Core n'a pas pu être réappliqué ; le bot continue.")
    try:
        from .bot_v15_runtime import install as install_v15
        install_v15(bot)
    except Exception:
        logger.exception("V15 Runtime n'a pas pu être réappliqué ; le bot continue.")
    try:
        from .bot_v16_commands import install as install_v16
        install_v16(bot)
    except Exception:
        logger.exception("V16 Commandes n'a pas pu être réappliqué ; le bot continue.")


async def _wait_for_ai(bot: commands.Bot) -> None:
    """Attend le chargement du Cog Ai quand ce garde est installé plus tôt au boot."""
    try:
        for _ in range(300):
            if bot.get_cog("Ai") is not None:
                install(bot)
                return
            await asyncio.sleep(0.1)
    finally:
        setattr(bot, "_sentrix_ai_disable_waiter", None)


def install(bot: commands.Bot) -> None:
    """Installe tous les verrous de façon idempotente."""
    _install_error_code()
    _install_service_guard(bot)
    _install_core_runtimes(bot)

    cog = bot.get_cog("Ai")
    if cog is None:
        waiter = getattr(bot, "_sentrix_ai_disable_waiter", None)
        if waiter is None or waiter.done():
            try:
                waiter = asyncio.get_running_loop().create_task(
                    _wait_for_ai(bot), name="sentrix-ai-disable-guard-waiter"
                )
                bot._sentrix_ai_disable_waiter = waiter
            except RuntimeError:
                pass
        return
    if getattr(cog, "_sentrix_ai_disable_guard", False):
        return

    original_send = cog.send_sentrix_reply

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
            # Conversation naturelle/mention + texte : silence complet lorsque l'IA est OFF.
            if reply_to is not None:
                return None
            # Commande explicite +sentrix ou /sentrix : réponse explicative unique.
            return await panels.envoyer(destination, panels.depuis_embed(embeds.info(AI_DISABLED_MESSAGE)))
        return await original_send(destination, author, question, reply_to=reply_to)

    guarded_send_sentrix_reply._sentrix_ai_disable_guard = True
    guarded_send_sentrix_reply._sentrix_original = original_send
    cog.send_sentrix_reply = types.MethodType(guarded_send_sentrix_reply, cog)
    cog._sentrix_ai_disable_guard = True

    logger.info(
        "IA : switch enabled autoritaire au niveau conversation ET moteur OpenAI ; V14/V15/V16 actifs."
    )


__all__ = ["install", "AI_DISABLED_CODE"]
