"""V90 — garde-fou final Tickets et ordre réel du Setup Logs.

Un ticket déjà créé et annoncé au membre ne doit jamais produire ensuite une seconde
réponse rouge uniquement parce que le journal de ticket est indisponible. V90 garantit
aussi que le correctif du panneau Logs est réappliqué APRÈS V75/V83, donc sur la classe
réellement utilisée par Discord.
"""
from __future__ import annotations

import logging
import sys

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
            # La SEULE destination fonctionnelle est la catégorie canonique Tickets du
            # Setup. Un ancien log_channel_id ne doit jamais renvoyer le journal dans
            # Modération, ni réactiver un log volontairement désactivé.
            try:
                setting = await log_service.get_log_setting(self.bot, guild.id, "tickets")
                if not setting.get("enabled"):
                    return False
                return await log_service.send_log(self.bot, guild, "tickets", embed)
            except Exception:
                # L'action ticket est déjà réussie : une panne de journal ne remonte jamais
                # vers start_ticket_flow(), donc aucune seconde réponse rouge n'est envoyée.
                logger.exception(
                    "Journal ticket canonique ignoré après action réussie guild=%s legacy_channel=%s",
                    getattr(guild, "id", None),
                    log_channel_id,
                )
                return False

        safe_ticket_log._sentrix_v90_safe_ticket_log = True
        safe_ticket_log._sentrix_previous = current
        cls.log_action = safe_ticket_log
        patched = True

    if patched:
        logger.info("Tickets V90 : logs canoniques non bloquants branchés sur la classe active.")
    return patched


def _install_post_v83_hook(bot: commands.Bot) -> bool:
    """Accroche V89/V90 au DERNIER installateur réellement appelé par cogs.__init__.

    shop_default_prices/V90 est installé tôt dans finalize_runtime. À ce moment, V75 n'a
    pas encore remplacé SentriXSetupV74._build_page. Modifier la classe trop tôt serait donc
    annulé quelques lignes plus tard. Le chargeur ``cogs`` résout son global
    ``install_logs_runtime_v83`` au moment de l'appel : on enveloppe ce global afin de
    réappliquer les correctifs juste après V83, dernière couche officielle du Setup/logs.
    """
    package = sys.modules.get(__package__)
    if package is None:
        return False

    current = getattr(package, "install_logs_runtime_v83", None)
    if not callable(current):
        logger.warning("V90 : install_logs_runtime_v83 introuvable dans le chargeur cogs.")
        return False
    if getattr(current, "_sentrix_v90_post_v83", False):
        return True

    def install_v83_then_v90(active_bot: commands.Bot):
        result = current(active_bot)
        # V75/V83 ont désormais terminé leurs remplacements : cette fois le patch touche
        # exactement la méthode du panneau que l'utilisateur voit.
        v89._patch_setup_logs_final()
        _patch_ticket_class(active_bot)
        logger.info("V90 post-V83 : Setup Logs final + Tickets canoniques réappliqués.")
        return result

    install_v83_then_v90._sentrix_v90_post_v83 = True
    install_v83_then_v90._sentrix_previous = current
    setattr(package, "install_logs_runtime_v83", install_v83_then_v90)
    logger.info("V90 : hook post-V83 installé dans le chargeur runtime.")
    return True


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v90", False):
        return
    await v89.install(bot)
    _patch_ticket_class(bot)
    _install_post_v83_hook(bot)
    bot._sentrix_runtime_finish_v90 = True
    logger.info(
        "Runtime Finish V90 actif : ticket créé sans fausse erreur + Setup Logs final post-V83."
    )


__all__ = ["install", "_patch_ticket_class"]
