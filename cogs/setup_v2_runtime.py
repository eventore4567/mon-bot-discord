"""Installateur final de la refonte Setup/Permissions V2."""
from __future__ import annotations

import logging
from types import MethodType

from . import permission_guard
from . import setup_v2_core as core
from . import setup_v2_ui as ui

logger = logging.getLogger("bot.setup-v2-runtime")


def _patch_ai_features(bot) -> None:
    current = permission_guard.evaluate_command_access
    if not getattr(current, "_sentrix_ai_features_v2", False):
        async def evaluate_ai_features(target_bot, *, command_name, author, guild):
            decision = await current(
                target_bot,
                command_name=command_name,
                author=author,
                guild=guild,
            )
            if not decision.allowed or guild is None:
                return decision
            name = str(command_name or "").casefold()
            if name not in core.AI_COMMANDS:
                return decision
            features = await ui.get_ai_features(target_bot, guild.id)
            if not features["commands_enabled"]:
                return permission_guard.AccessDecision(
                    False,
                    "Les **commandes IA** sont désactivées sur ce serveur.",
                    "ai-feature:commands-disabled",
                )
            if name == "image" and not features["image_generation_enabled"]:
                return permission_guard.AccessDecision(
                    False,
                    "La **génération d’images IA** est désactivée sur ce serveur.",
                    "ai-feature:image-generation-disabled",
                )
            return decision

        evaluate_ai_features._sentrix_ai_features_v2 = True
        evaluate_ai_features._sentrix_previous = current
        permission_guard.evaluate_command_access = evaluate_ai_features

    ai_cog = bot.get_cog("Ai")
    if ai_cog is not None and not getattr(ai_cog, "_sentrix_ai_features_v2", False):
        original_reply = ai_cog.send_sentrix_reply

        async def send_sentrix_reply_v2(_self, destination, author, question, *, reply_to=None):
            # reply_to != None correspond au déclenchement naturel depuis on_message.
            if reply_to is not None and reply_to.guild is not None:
                features = await ui.get_ai_features(bot, reply_to.guild.id)
                if not features["natural_enabled"]:
                    return None
            return await original_reply(destination, author, question, reply_to=reply_to)

        ai_cog.send_sentrix_reply = MethodType(send_sentrix_reply_v2, ai_cog)
        ai_cog._sentrix_ai_features_v2 = True


def install(bot) -> None:
    if getattr(bot, "_sentrix_setup_v2_runtime", False):
        return
    core.install(bot)
    ui.install(bot)
    _patch_ai_features(bot)
    # Le wrapper IA a été posé après l'alignement initial des checks. Les checks locaux
    # utilisent evaluate_command_access à l'exécution et voient donc aussi ces sous-règles.
    bot._sentrix_setup_v2_runtime = True
    logger.info("SentriX Setup V2 final installé.")


__all__ = ["install"]
