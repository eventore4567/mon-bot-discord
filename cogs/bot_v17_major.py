"""Orchestrateur de la mise à jour majeure SentriX V17.

Les fonctions V17 restent actives, mais V17 ne possède plus le transport des logs.
Le logger unique et autoritaire est ``utils.log_service.send_log``.
"""
from __future__ import annotations

import inspect
import logging
import re

from discord.ext import commands

from .v17_shared import (
    ensure_schema,
    install_config_invalidation,
    install_permission_cache,
    register_command_policy,
    state,
)

logger = logging.getLogger("bot.v17-major")


def _install_rate_limit_compatibility() -> None:
    """Accepte aussi le message détaillé produit par l'anti-farm V17."""
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
        result = installer(bot, extension_name)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.exception(
            "V17 : le module %s n'a pas pu être appliqué ; poursuite du démarrage.",
            label,
        )


async def _install_extras_deterministic(bot: commands.Bot, extension_name: str) -> None:
    """Ajoute le Cog final en l'attendant vraiment, puis réapplique ses patches ciblés."""
    del extension_name
    from . import v17_extras

    register_command_policy(economy={"shopwindow", "shopwindowclear"})
    if bot.get_cog("V17Extras") is None:
        await bot.add_cog(v17_extras.V17Extras(bot))
    v17_extras.install_image_role_quota(bot)
    v17_extras.install_autocomplete(bot)


async def _install_tickets_without_log_wrapper(
    bot: commands.Bot,
    extension_name: str,
) -> None:
    """Conserve les commandes/patches tickets V17 sans monkey-patcher send_log.

    L'ancienne fonction ``v17_tickets_logs.install()`` remplaçait
    ``utils.log_service.send_log`` puis V24/V25 le remplaçaient encore. C'est cette chaîne
    qui finissait par exposer ``send_compact_unique_log(..., file=None)`` sans ``view=``.
    """
    del extension_name
    from . import v17_tickets_logs

    await ensure_schema(bot)
    register_command_policy(
        configuration={"logevent"},
        moderation={"logsearch"},
        tickets={"ticketreopenwindow", "reopenticket", "ticketstaffstats"},
    )
    if bot.get_cog("V17TicketsLogs") is None:
        await bot.add_cog(v17_tickets_logs.V17TicketsLogs(bot))
    v17_tickets_logs.install_ticket_patches(bot)


def _fix_group_invocation(bot: commands.Bot) -> None:
    """Un sous-ordre ne doit pas exécuter aussi la page d'accueil de son groupe."""
    for name in (
        "protectmember",
        "staffnote",
        "sanctionpolicy",
        "serversnapshot",
        "nukewhitelist",
        "logevent",
        "airolequota",
        "aicontext",
        "season",
    ):
        command = bot.get_command(name)
        if isinstance(command, commands.Group):
            command.invoke_without_command = True


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    try:
        await ensure_schema(bot)
        install_config_invalidation(bot)
        install_permission_cache(bot)
        _install_rate_limit_compatibility()
    except Exception:
        logger.exception(
            "V17 : socle partagé partiellement indisponible ; poursuite du démarrage."
        )

    from .v17_moderation_security import install as install_moderation_security
    from .v17_ai_economy_games import install as install_ai_economy_games
    from .v17_health import install as install_health
    from .v17_user_facing_hotfix import install as install_user_facing_hotfix
    from .production_alert_noise_fix import install as install_production_alert_noise_fix
    from .command_runtime_hardening_v18 import install as install_command_runtime_hardening_v18
    from .command_integrity_v18 import install as install_command_integrity_v18
    from .send_argument_safety_v20 import install as install_send_argument_safety_v20
    from .interaction_defer_safety_v21 import install as install_interaction_defer_safety_v21
    from .direct_sentrix_slash_v22 import install as install_direct_sentrix_slash_v22
    from .ai_compatibility_v23 import install as install_ai_compatibility_v23

    await _install_one(
        "modération/sécurité",
        install_moderation_security,
        bot,
        extension_name,
    )
    await _install_one(
        "tickets sans transport de logs concurrent",
        _install_tickets_without_log_wrapper,
        bot,
        extension_name,
    )
    await _install_one(
        "IA/économie/jeux",
        install_ai_economy_games,
        bot,
        extension_name,
    )
    await _install_one(
        "diagnostic/santé",
        install_health,
        bot,
        extension_name,
    )
    await _install_one(
        "finitions boutique/image/autocomplete",
        _install_extras_deterministic,
        bot,
        extension_name,
    )
    await _install_one(
        "accueil/erreurs privées/create sentrix",
        install_user_facing_hotfix,
        bot,
        extension_name,
    )
    await _install_one(
        "alertes production anti-spam",
        install_production_alert_noise_fix,
        bot,
        extension_name,
    )
    _fix_group_invocation(bot)
    await _install_one(
        "durcissement moteur de commandes V18",
        install_command_runtime_hardening_v18,
        bot,
        extension_name,
    )
    await _install_one(
        "intégrité finale de toutes les commandes V18",
        install_command_integrity_v18,
        bot,
        extension_name,
    )
    await _install_one(
        "sécurité arguments send V20",
        install_send_argument_safety_v20,
        bot,
        extension_name,
    )
    await _install_one(
        "defer/typing slash idempotents V21",
        install_interaction_defer_safety_v21,
        bot,
        extension_name,
    )
    await _install_one(
        "callback slash /sentrix direct V22",
        install_direct_sentrix_slash_v22,
        bot,
        extension_name,
    )
    await _install_one(
        "compatibilité réglages/commandes IA V23",
        install_ai_compatibility_v23,
        bot,
        extension_name,
    )

    # IMPORTANT : V24/V25 ne sont plus installés ici. Ces couches remplaçaient
    # log_service.send_log après le logger officiel et étaient la cause du crash
    # ``unexpected keyword argument 'view'``. Le layout est maintenant construit par
    # utils.embeds/cogs.logs et envoyé uniquement par utils.log_service.

    runtime = state(bot)
    if not runtime.get("v17_announced"):
        runtime["v17_announced"] = True
        logger.info(
            "SentriX V17 majeure active : fonctionnalités V17 conservées, logger officiel unique."
        )


__all__ = ["install"]
