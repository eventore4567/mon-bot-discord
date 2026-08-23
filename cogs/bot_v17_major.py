"""Orchestrateur de la mise à jour majeure SentriX V17.

Appelé après chaque extension par stability_runtime. Chaque sous-module est isolé : une
fonctionnalité optionnelle en erreur ne doit jamais empêcher la modération, les tickets,
l'IA ou le cœur du bot de démarrer.
"""
from __future__ import annotations

import logging
import re

from discord.ext import commands

from .v17_shared import ensure_schema, install_config_invalidation, install_permission_cache, state

logger = logging.getLogger("bot.v17-major")


def _install_rate_limit_compatibility() -> None:
    """Accepte aussi le message détaillé produit par l'anti-farm V17.

    Excellence utilisait historiquement RuntimeRateLimitError(float). V17 peut fournir un
    texte contenant le délai afin de garder un diagnostic plus parlant ; on extrait alors
    le nombre de secondes sans casser le gestionnaire d'erreurs historique.
    """
    from .bot_excellence_runtime import RuntimeRateLimitError

    current = RuntimeRateLimitError.__init__
    if getattr(current, "_sentrix_v17_compatible", False):
        return

    def init_v17(self, retry_after):
        if isinstance(retry_after, str):
            match = re.search(r"(\d+)\s*s", retry_after)
            seconds = float(match.group(1)) if match else 30.0
            self.retry_after = max(1.0, seconds)
            commands.CheckFailure.__init__(self, retry_after)
            return
        current(self, retry_after)

    init_v17._sentrix_v17_compatible = True
    RuntimeRateLimitError.__init__ = init_v17


async def _install_one(label: str, installer, bot: commands.Bot, extension_name: str) -> None:
    try:
        await installer(bot, extension_name)
    except Exception:
        logger.exception("V17 : le module %s n'a pas pu être appliqué ; poursuite du démarrage.", label)


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    try:
        await ensure_schema(bot)
        install_config_invalidation(bot)
        install_permission_cache(bot)
        _install_rate_limit_compatibility()
    except Exception:
        logger.exception("V17 : socle partagé partiellement indisponible ; poursuite du démarrage.")

    from .v17_moderation_security import install as install_moderation_security
    from .v17_tickets_logs import install as install_tickets_logs
    from .v17_ai_economy_games import install as install_ai_economy_games
    from .v17_health import install as install_health

    await _install_one("modération/sécurité", install_moderation_security, bot, extension_name)
    await _install_one("tickets/logs", install_tickets_logs, bot, extension_name)
    await _install_one("IA/économie/jeux", install_ai_economy_games, bot, extension_name)
    await _install_one("diagnostic/santé", install_health, bot, extension_name)

    runtime = state(bot)
    if not runtime.get("v17_announced"):
        runtime["v17_announced"] = True
        logger.info(
            "SentriX V17 majeure active : résilience, modération, sécurité, tickets, logs, IA, économie, missions, saisons et santé."
        )


__all__ = ["install"]
