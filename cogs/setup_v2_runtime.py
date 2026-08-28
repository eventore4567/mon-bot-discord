"""Installateur final de la refonte Setup/Permissions V2."""
from __future__ import annotations

import logging
import time
from types import MethodType

import discord

from utils import embeds, log_service
from . import permission_guard
from . import setup_v2_core as core
from . import setup_v2_ui as ui
from . import setup_v2_completion as completion

logger = logging.getLogger("bot.setup-v2-runtime")


def _patch_ai_features(bot) -> None:
    current = permission_guard.evaluate_command_access
    if not getattr(current, "_sentrix_ai_features_v2", False):
        async def evaluate_ai_features(target_bot, *, command_name, author, guild):
            decision = await current(target_bot, command_name=command_name, author=author, guild=guild)
            if not decision.allowed or guild is None:
                return decision
            name = str(command_name or "").casefold()
            if name not in core.AI_COMMANDS:
                return decision
            features = await ui.get_ai_features(target_bot, guild.id)
            if not features["commands_enabled"]:
                return permission_guard.AccessDecision(False, "Les **commandes IA** sont désactivées sur ce serveur.", "ai-feature:commands-disabled")
            if name == "image" and not features["image_generation_enabled"]:
                return permission_guard.AccessDecision(False, "La **génération d’images IA** est désactivée sur ce serveur.", "ai-feature:image-generation-disabled")
            return decision

        evaluate_ai_features._sentrix_ai_features_v2 = True
        evaluate_ai_features._sentrix_previous = current
        permission_guard.evaluate_command_access = evaluate_ai_features

    ai_cog = bot.get_cog("Ai")
    if ai_cog is not None and not getattr(ai_cog, "_sentrix_ai_features_v2", False):
        original_reply = ai_cog.send_sentrix_reply

        async def send_sentrix_reply_v2(_self, destination, author, question, *, reply_to=None):
            if reply_to is not None and reply_to.guild is not None:
                features = await ui.get_ai_features(bot, reply_to.guild.id)
                if not features["natural_enabled"]:
                    return None
            return await original_reply(destination, author, question, reply_to=reply_to)

        ai_cog.send_sentrix_reply = MethodType(send_sentrix_reply_v2, ai_cog)
        ai_cog._sentrix_ai_features_v2 = True


async def _send_resource_log(bot, guild, title: str, fields, event: str) -> None:
    panel = embeds.log_embed(title, fields=fields)
    await log_service.send_log(bot, guild, "resources", panel, event_key=log_service.make_event_key(guild.id, event, discriminator=time.time_ns()))


def _replace_resource_listeners(bot) -> None:
    for event_name in ("on_guild_emojis_update", "on_guild_stickers_update"):
        listeners = list(getattr(bot, "extra_events", {}).get(event_name, ()) or ())
        kept = []
        for listener in listeners:
            module = str(getattr(listener, "__module__", "") or "")
            name = str(getattr(listener, "__name__", "") or "")
            if module.endswith("setup_v2_core") and name == event_name:
                continue
            kept.append(listener)
        if kept:
            bot.extra_events[event_name] = kept
        else:
            bot.extra_events.pop(event_name, None)

    async def on_guild_emojis_update(guild, before, after):
        before_by_id = {emoji.id: emoji for emoji in before}
        after_by_id = {emoji.id: emoji for emoji in after}
        for emoji_id, emoji in after_by_id.items():
            if emoji_id not in before_by_id:
                await _send_resource_log(bot, guild, "Emoji créé", [("Emoji", str(emoji), True), ("Nom", emoji.name, True)], "emoji_create")
            elif before_by_id[emoji_id].name != emoji.name:
                await _send_resource_log(bot, guild, "Emoji modifié", [("Avant", before_by_id[emoji_id].name, True), ("Après", emoji.name, True)], "emoji_update")
        for emoji_id, emoji in before_by_id.items():
            if emoji_id not in after_by_id:
                await _send_resource_log(bot, guild, "Emoji supprimé", [("Nom", emoji.name, True), ("ID", f"`{emoji_id}`", True)], "emoji_delete")

    async def on_guild_stickers_update(guild, before, after):
        before_by_id = {sticker.id: sticker for sticker in before}
        after_by_id = {sticker.id: sticker for sticker in after}
        for sticker_id, sticker in after_by_id.items():
            if sticker_id not in before_by_id:
                await _send_resource_log(bot, guild, "Sticker créé", [("Nom", sticker.name, True)], "sticker_create")
        for sticker_id, sticker in before_by_id.items():
            if sticker_id not in after_by_id:
                await _send_resource_log(bot, guild, "Sticker supprimé", [("Nom", sticker.name, True)], "sticker_delete")

    bot.add_listener(on_guild_emojis_update, "on_guild_emojis_update")
    bot.add_listener(on_guild_stickers_update, "on_guild_stickers_update")


def _finalize_log_runtime(bot) -> None:
    if "members" in log_service.LOG_TYPES:
        log_service.LOG_TYPES["members"]["label"] = "Membres (arrivées/départs/pseudo/rôles attribués)"
    if "roles" in log_service.LOG_TYPES:
        log_service.LOG_TYPES["roles"]["label"] = "Rôles (création/suppression/modification/permissions)"

    logs_cog = bot.get_cog("Logs")
    if logs_cog is None or getattr(logs_cog, "_sentrix_setup_v2_cache_final", False):
        return
    current_cache = logs_cog._cache_message

    async def cache_only_when_needed(_self, message):
        if message.guild is None:
            return
        if not await core.module_enabled(bot, message.guild.id, "logs"):
            return
        setting = await log_service.get_log_setting(bot, message.guild.id, "messages")
        if not setting.get("enabled"):
            return
        await current_cache(message)
        try:
            await core.ensure_schema(bot)
            await bot.db.execute("DELETE FROM message_attachment_cache_v2 WHERE stored_at < ?", (int(time.time()) - 86400,))
        except Exception:
            pass

    logs_cog._cache_message = MethodType(cache_only_when_needed, logs_cog)
    logs_cog._sentrix_setup_v2_cache_final = True


def install(bot) -> None:
    if getattr(bot, "_sentrix_setup_v2_runtime", False):
        return
    core.install(bot)
    ui.install(bot)
    _patch_ai_features(bot)
    _replace_resource_listeners(bot)
    _finalize_log_runtime(bot)
    # Completion se pose en dernier : elle valide l'activation, ajoute le reset,
    # la pagination, le test de bienvenue et coupe toute maintenance serveur implicite.
    completion.install(bot)
    bot._sentrix_setup_v2_runtime = True
    logger.info("SentriX Setup V2 final installé.")


__all__ = ["install"]