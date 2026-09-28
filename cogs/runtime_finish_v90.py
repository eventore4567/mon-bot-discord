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


def _type_depuis_titre(embed) -> str:
    """Type d'événement de ticket déduit du titre canonique de l'embed.

    Correspondance EXACTE, jamais une sous-chaîne : « 🔒 Ticket fermé » et
    « ⏱️ Ticket fermé automatiquement » sont deux événements distincts, et un
    ``in`` les confondrait — c'est exactement l'erreur que faisait l'ancien
    ``log_type = "ticket_close" if "ferm" in title else "ticket_open"``.
    """
    try:
        from services.tickets import EVENEMENTS_TICKET
    except Exception:  # pragma: no cover - import circulaire improbable
        return "ticket_open"
    titre = str(getattr(embed, "title", "") or "").strip()
    for evenement, (titre_canonique, _libelle) in EVENEMENTS_TICKET.items():
        if titre == titre_canonique:
            return evenement
    # Repli : un type d'événement RÉEL, pas le nom de la catégorie. La
    # différence est visible — bannière Tickets contre bannière info, emoji 📬
    # contre 📋 générique.
    return "ticket_open"


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

        async def safe_ticket_log(self, guild, embed, log_channel_id=None, *,
                                  _previous=current, log_type=None):
            # La SEULE destination fonctionnelle est la catégorie canonique Tickets du
            # Setup. Un ancien log_channel_id ne doit jamais renvoyer le journal dans
            # Modération, ni réactiver un log volontairement désactivé.
            #
            # CORRIGÉ le 28/09/2026. Cette fonction passait ``"tickets"`` à
            # send_log — le nom de la CATÉGORIE, pas un type d'événement. Le
            # routage tombait juste par chance (« tickets » est aussi une clé de
            # CATEGORIES), mais tout le reste se perdait :
            # ``resolve("tickets")`` rend ``('tickets', '📋', 'info')``, donc
            # emoji générique, bannière `info` au lieu de la bannière Tickets, et
            # aucune phrase narrative puisque wide_logs cherche un ``ticket_*``.
            # Chaque journal passé par log_action arrivait ainsi plat, quel que
            # soit l'événement qu'il décrivait.
            #
            # Mesuré sur le bot booté : c'est bien CETTE fonction qui est
            # branchée sur Tickets.log_action — elle remplace sans jamais
            # appeler ``_previous``, donc le classement par titre de
            # cogs/ticket_claim_security n'a jamais tourné en production.
            try:
                setting = await log_service.get_log_setting(self.bot, guild.id, "tickets")
                if not setting.get("enabled"):
                    return False
                return await log_service.send_log(
                    self.bot, guild, log_type or _type_depuis_titre(embed), embed
                )
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
    ``run_late_runtime_hooks`` au moment de l'appel : on enveloppe ce global afin de
    réappliquer les correctifs juste après V83, dernière couche officielle du Setup/logs.
    """
    package = sys.modules.get(__package__)
    if package is None:
        return False

    current = getattr(package, "run_late_runtime_hooks", None)
    if not callable(current):
        logger.warning("V90 : run_late_runtime_hooks introuvable dans le chargeur cogs.")
        return False
    if getattr(current, "_sentrix_v90_late_hook", False):
        return True

    def install_late_then_v90(active_bot: commands.Bot):
        result = current(active_bot)
        # V75/V83 ont désormais terminé leurs remplacements : cette fois le patch touche
        # exactement la méthode du panneau que l'utilisateur voit.
        v89._patch_setup_logs_final()
        _patch_ticket_class(active_bot)
        logger.info("V90 post-V83 : Setup Logs final + Tickets canoniques réappliqués.")
        return result

    install_late_then_v90._sentrix_v90_late_hook = True
    install_late_then_v90._sentrix_previous = current
    setattr(package, "run_late_runtime_hooks", install_late_then_v90)
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
