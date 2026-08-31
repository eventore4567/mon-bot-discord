"""V90 — garde-fou final Tickets après V89.

Un ticket déjà créé et annoncé au membre ne doit jamais produire ensuite une seconde
réponse rouge uniquement parce que le journal de ticket est indisponible.
"""
from __future__ import annotations

import logging

from discord.ext import commands

from utils import log_service
from . import runtime_finish_v89 as v89

logger = logging.getLogger("bot.runtime-finish-v90")


def _patch_ticket_class(bot: commands.Bot) -> bool:
    classes = []
    cog = bot.get_cog("Tickets")
    if cog is not None:
        classes.append(cog.__class__)
    try:
        from . import tickets as ticket_runtime
        classes.append(ticket_runtime.Tickets)
    except Exception:
        logger.exception("Import Tickets V90 impossible")

    patched = False
    seen = set()
    for cls in classes:
        if cls in seen:
            continue
        seen.add(cls)
        current = getattr(cls, "log_action", None)
        if current is None or getattr(current, "_sentrix_v90_safe_ticket_log", False):
            continue

        async def safe_ticket_log(self, guild, embed, log_channel_id=None, *, _previous=current):
            try:
                # Le routeur officiel est prioritaire : la destination est celle choisie
                # dans Setup -> Logs -> Tickets. Le log_channel_id legacy ne doit pas
                # pouvoir renvoyer les tickets dans Modération ou faire échouer l'ouverture.
                sent = await log_service.send_log(self.bot, guild, "tickets", embed)
                if sent:
                    return sent
            except Exception:
                logger.exception("Routeur officiel ticket indisponible guild=%s", getattr(guild, "id", None))

            # Compatibilité best-effort uniquement. Toute exception est avalée car l'action
            # ticket est déjà réussie côté utilisateur.
            try:
                return await _previous(self, guild, embed, log_channel_id)
            except Exception:
                logger.exception(
                    "Journal ticket ignoré après action réussie guild=%s legacy_channel=%s",
                    getattr(guild, "id", None),
                    log_channel_id,
                )
                return None

        safe_ticket_log._sentrix_v90_safe_ticket_log = True
        safe_ticket_log._sentrix_previous = current
        cls.log_action = safe_ticket_log
        patched = True

    if patched:
        logger.info("Tickets V90 : log post-création rendu non bloquant sur la classe active.")
    return patched


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v90", False):
        return
    await v89.install(bot)
    _patch_ticket_class(bot)
    bot._sentrix_runtime_finish_v90 = True
    logger.info("Runtime Finish V90 actif : ticket créé = jamais de fausse Action impossible liée aux logs.")


__all__ = ["install"]
