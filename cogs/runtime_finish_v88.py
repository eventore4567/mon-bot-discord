"""V88 — ajoute la sécurité recommandée au preset privé manox."""
from __future__ import annotations

import logging

from discord.ext import commands

from . import runtime_finish_v84 as v84
from . import runtime_finish_v87 as v87

logger = logging.getLogger("bot.runtime-finish-v88")


def _patch_manox_security() -> None:
    current = v84.build_manox_server
    if getattr(current, "_sentrix_v88_security", False):
        return

    async def build_manox_with_security(bot, guild, author):
        result = await current(bot, guild, author)
        warnings = list(result.get("warnings") or [])
        try:
            from .security_runtime_hardening import apply_recommended_security
            from . import setup_v2_core as core

            security = await apply_recommended_security(bot, guild)
            await core.set_module_enabled(
                bot,
                guild.id,
                "security",
                True,
                actor_id=author.id,
            )
            missing = list(security.get("missing_permissions") or [])
            if missing:
                warnings.append("permissions sécurité du rôle SentriX : " + ", ".join(missing))
            result["security_ready"] = not missing
        except Exception:
            logger.exception("Profil sécurité manox impossible sur %s", guild.id)
            warnings.append("sécurité")
            result["security_ready"] = False
        result["warnings"] = warnings
        return result

    build_manox_with_security._sentrix_v88_security = True
    build_manox_with_security._sentrix_previous = current
    v84.build_manox_server = build_manox_with_security


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v88", False):
        return
    await v87.install(bot)
    _patch_manox_security()
    bot._sentrix_runtime_finish_v88 = True
    logger.info("Runtime Finish V88 actif : preset manox + sécurité recommandée.")


__all__ = ["install"]
