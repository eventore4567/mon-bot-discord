"""Configuration d'identité de l'instance SentriX.

Historique : ce module patchait Context.send, Messageable.send, les interactions, les
webhooks et les éditions de messages. Ces transports sont maintenant la responsabilité
exclusive de ``cogs.final_interaction_policy``. Ici on ne configure plus que la marque,
le pseudo d'instance et le mot de réveil d'une éventuelle instance secondaire.
"""
from __future__ import annotations

import logging
import os
import re

import discord
from discord.ext import commands

from utils import premium_style

logger = logging.getLogger("bot.instance-branding")
_BRANDING_CONFIGURED = False


def _railway_service_name() -> str:
    return (os.getenv("RAILWAY_SERVICE_NAME") or "").strip()


def _is_odboug_instance() -> bool:
    explicit = (os.getenv("BOT_BRAND_LABEL") or "").strip().casefold()
    if explicit:
        return explicit == "odboug"
    return "odboug" in _railway_service_name().casefold()


def _instance_brand() -> str:
    explicit = (os.getenv("BOT_BRAND_LABEL") or "").strip()
    if explicit:
        return explicit[:48]
    return "Odboug" if _is_odboug_instance() else "SentriX"


def _instance_display_name() -> str:
    explicit = (os.getenv("BOT_DISPLAY_NAME") or "").strip()
    if explicit:
        return explicit[:32]
    return "[+] Bot'Odboug |" if _is_odboug_instance() else ""


def _configure_instance_branding() -> None:
    """Configure les helpers de marque sans toucher aux transports Discord."""
    global _BRANDING_CONFIGURED
    if _BRANDING_CONFIGURED:
        return
    _BRANDING_CONFIGURED = True

    brand = _instance_brand()
    premium_style.CATEGORY_NAMES["brand"] = brand
    premium_style.SENTRIX_TITLE_RE = re.compile(
        rf"^(?:SENTRIX|{re.escape(brand)})\s*(?:/|•)\s*",
        re.IGNORECASE,
    )

    def canonical_title(category: str, *, log_type: str | None = None) -> str:
        label = premium_style.CATEGORY_NAMES.get(category, "Information")
        limit = premium_style.VISUAL_LIMITS["title"]
        if log_type:
            return premium_style.clip(f"{brand} • Journal {label}", limit)
        return premium_style.clip(f"{brand} • {label}", limit)

    def footer_text(*, guild: discord.Guild | None = None, requester=None) -> str:
        del requester
        parts = [brand]
        if guild is not None:
            parts.append(premium_style.clip(getattr(guild, "name", "Serveur"), 60))
        return " • ".join(parts)

    premium_style._canonical_title = canonical_title
    premium_style._footer_text = footer_text
    logger.info("Identité d'instance configurée : %s.", brand)


async def _apply_instance_display_name(bot: commands.Bot, guild: discord.Guild | None = None) -> None:
    display_name = _instance_display_name()
    if not display_name:
        return
    targets = [guild] if guild is not None else list(bot.guilds)
    for target in targets:
        member = getattr(target, "me", None)
        if member is None or member.display_name == display_name:
            continue
        try:
            await member.edit(nick=display_name, reason="Identité de cette instance du bot")
        except discord.Forbidden:
            logger.warning("Pseudo d'instance impossible sur guild=%s : permission manquante.", target.id)
        except discord.HTTPException:
            logger.exception("Discord a refusé le pseudo d'instance sur guild=%s.", target.id)


def _install_instance_display_name(bot: commands.Bot) -> None:
    if not _instance_display_name() or getattr(bot, "_sentrix_instance_display_name", False):
        return

    async def on_ready_name():
        await _apply_instance_display_name(bot)

    async def on_join_name(guild: discord.Guild):
        await _apply_instance_display_name(bot, guild)

    bot.add_listener(on_ready_name, "on_ready")
    bot.add_listener(on_join_name, "on_guild_join")
    bot._sentrix_instance_display_name = True


def _wake_word_pattern() -> re.Pattern[str]:
    configured = [item.strip() for item in (os.getenv("BOT_WAKE_WORDS") or "").split(",") if item.strip()]
    brand = _instance_brand()
    words = configured or [brand]
    if brand.casefold() == "odboug":
        words.extend(["odboug", "bot odboug", "bot'odboug", "bot’odboug"])
    unique: list[str] = []
    seen: set[str] = set()
    for word in words:
        key = word.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(word)
    alternatives = "|".join(re.escape(word).replace(r"\ ", r"\s+") for word in unique)
    return re.compile(rf"^(?:{alternatives})\b", re.IGNORECASE)


def _install_instance_wake_word(bot: commands.Bot) -> None:
    # Le bot SentriX principal possède déjà son listener naturel dans cogs.ai.
    if _instance_brand().casefold() == "sentrix" or getattr(bot, "_sentrix_instance_wake_word", False):
        return
    pattern = _wake_word_pattern()

    async def instance_wake_word(message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = (message.content or "").strip()
        if not content:
            return
        prefix = bot.prefix_cache.get(message.guild.id, "+") if hasattr(bot, "prefix_cache") else "+"
        if content.startswith(prefix):
            return
        match = pattern.match(content)
        if match is None:
            return
        ai_cog = bot.get_cog("Ai")
        if ai_cog is None:
            return
        question = content[match.end():].lstrip(" ,:-").strip() or "Salut, comment tu vas ?"
        invoke_natural = getattr(ai_cog, "_invoke_natural_command", None)
        if callable(invoke_natural):
            try:
                if await invoke_natural(message, question, prefix):
                    return
            except Exception:
                logger.exception("Commande naturelle d'instance impossible.")
        send_reply = getattr(ai_cog, "send_sentrix_reply", None)
        if callable(send_reply):
            try:
                async with message.channel.typing():
                    await send_reply(message.channel, message.author, question, reply_to=message)
            except Exception:
                logger.exception("Réponse naturelle d'instance impossible.")

    bot.add_listener(instance_wake_word, "on_message")
    bot._sentrix_instance_wake_word = True


def install(bot: commands.Bot) -> None:
    _configure_instance_branding()
    _install_instance_display_name(bot)
    _install_instance_wake_word(bot)
    bot._sentrix_premium_style_transport_owner = False
    logger.info("premium_style_runtime limité au branding : aucun transport Discord patché.")


__all__ = ["install"]
