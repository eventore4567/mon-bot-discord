"""Réduit le bruit et les doubles mutations de production SentriX.

Deux services Railway exécutent le même dépôt. Les actions qui modifient réellement
Discord ne doivent donc jamais être jouées deux fois :
- un seul service envoie les alertes d'exploitation ;
- un seul service exécute la sanction/rollback anti-nuke et recrée les salons ;
- le service secondaire peut rester connecté pour la disponibilité, sans dupliquer les
  restaurations.
"""
from __future__ import annotations

import logging
import os
import time
from types import MethodType

from discord.ext import commands

logger = logging.getLogger("bot.production-alert-noise-fix")
_ALERTS_PATCHED = False

DEFAULT_ALERT_COOLDOWN_SECONDS = 60 * 60
DEFAULT_BACKUP_ALERT_COOLDOWN_SECONDS = 6 * 60 * 60
DEFAULT_PRIMARY_SERVICE = "mon-bot-discord"


def _positive_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _primary_service_name() -> str:
    return (
        os.getenv("SENTRIX_MUTATION_PRIMARY_SERVICE")
        or os.getenv("SENTRIX_LOG_PRIMARY_SERVICE")
        or os.getenv("SENTRIX_ALERT_PRIMARY_SERVICE")
        or DEFAULT_PRIMARY_SERVICE
    ).strip().casefold()


def _is_primary_service() -> bool:
    """Vrai uniquement pour l'instance autorisée à faire les mutations uniques."""
    service = (os.getenv("RAILWAY_SERVICE_NAME") or "").strip().casefold()
    if not service:
        # En local / autre hébergeur, ne pas neutraliser les fonctions de sécurité.
        return True
    primary = _primary_service_name()
    if not primary:
        return True
    return service == primary or primary in service


def _patch_primary_mutations(bot: commands.Bot) -> None:
    """Empêche la deuxième instance Railway de restaurer/sanctionner en doublon.

    Cet installateur est rappelé après chaque extension. Si le rollback anti-nuke enveloppe
    ``punish_nuker`` plus tard pendant le boot, ce garde repasse donc au-dessus.
    """
    automod = bot.get_cog("Automod")
    if automod is not None:
        current_punish = getattr(automod, "punish_nuker", None)
        current_func = getattr(current_punish, "__func__", current_punish)
        if current_punish is not None and not getattr(
            current_func, "_sentrix_primary_mutation_guard", False
        ):
            async def primary_punish(_self, guild, actor_id, reason):
                if not _is_primary_service():
                    logger.warning(
                        "Anti-nuke observé mais mutation ignorée sur le service secondaire %s "
                        "(guild=%s, actor=%s).",
                        os.getenv("RAILWAY_SERVICE_NAME") or "inconnu",
                        getattr(guild, "id", "?"),
                        actor_id,
                    )
                    return None
                return await current_punish(guild, actor_id, reason)

            primary_punish._sentrix_primary_mutation_guard = True
            primary_punish._sentrix_original = current_punish
            automod.punish_nuker = MethodType(primary_punish, automod)

    rollback = bot.get_cog("AntiNukeRollback")
    if rollback is not None:
        current_context = getattr(rollback, "_antinuke_context", None)
        context_func = getattr(current_context, "__func__", current_context)
        if current_context is not None and not getattr(
            context_func, "_sentrix_primary_mutation_guard", False
        ):
            async def primary_context(_self, guild, action, target_id):
                if not _is_primary_service():
                    # Le secondaire ne remplit même pas son journal rollback : il ne peut
                    # donc jamais recréer un salon à partir de la même suppression.
                    return None, None
                return await current_context(guild, action, target_id)

            primary_context._sentrix_primary_mutation_guard = True
            primary_context._sentrix_original = current_context
            rollback._antinuke_context = MethodType(primary_context, rollback)

        current_rollback = getattr(rollback, "rollback_actor", None)
        rollback_func = getattr(current_rollback, "__func__", current_rollback)
        if current_rollback is not None and not getattr(
            rollback_func, "_sentrix_primary_mutation_guard", False
        ):
            async def primary_rollback(_self, guild, actor_id, reason):
                if not _is_primary_service():
                    return {"unbanned": 0, "restored": 0, "deleted": 0, "reverted": 0}
                return await current_rollback(guild, actor_id, reason)

            primary_rollback._sentrix_primary_mutation_guard = True
            primary_rollback._sentrix_original = current_rollback
            rollback.rollback_actor = MethodType(primary_rollback, rollback)


def install(bot: commands.Bot, extension_name: str = "") -> None:
    """Patch idempotent rappelé pendant le chargement de toutes les extensions."""
    del extension_name
    global _ALERTS_PATCHED

    # IMPORTANT : ceci doit repasser même après l'installation des alertes, car Automod et
    # AntiNukeRollback peuvent être chargés plus tard dans la séquence de démarrage.
    _patch_primary_mutations(bot)

    if _ALERTS_PATCHED:
        return

    try:
        from . import production_ops
    except Exception:
        return

    current_health = getattr(production_ops, "_health_alert", None)
    current_send = getattr(production_ops, "_send_ops_alert", None)
    if current_health is None or current_send is None:
        return
    if getattr(current_health, "_sentrix_noise_fixed", False):
        _ALERTS_PATCHED = True
        return

    def actionable_health_alert(runtime_bot: commands.Bot):
        """Ne remonte que les incidents nécessitant réellement une notification."""
        errors = production_ops._recent_technical_errors(runtime_bot)
        threshold = production_ops._positive_int_env(
            "SENTRIX_ALERT_ERROR_THRESHOLD", 5, minimum=2, maximum=100
        )
        if len(errors) >= threshold:
            kinds: dict[str, int] = {}
            for item in errors:
                name = str(item.get("type") or "Erreur")[:80]
                kinds[name] = kinds.get(name, 0) + 1
            top = sorted(kinds.items(), key=lambda pair: (-pair[1], pair[0]))[:4]
            detail = ", ".join(f"{name} ×{count}" for name, count in top)
            fingerprint = ",".join(sorted(name for name, _count in top))
            return (
                f"errors:{fingerprint}",
                f"{len(errors)} erreurs techniques en 5 min ({detail}).",
            )

        ops = production_ops._ops_state(runtime_bot)
        if ops.get("last_backup_ok") is False:
            reason = str(ops.get("last_backup_error") or "erreur inconnue")[:100]
            return "backup-failed", f"Le dernier backup SQLite a échoué ({reason})."

        return None, None

    async def send_actionable_alert(runtime_bot: commands.Bot, key: str, detail: str) -> None:
        if not _is_primary_service():
            logger.debug(
                "Alerte production ignorée sur le service secondaire %s : %s",
                os.getenv("RAILWAY_SERVICE_NAME") or "inconnu",
                key,
            )
            return

        state = production_ops._ops_state(runtime_bot)
        now_value = int(time.time())
        if key == "backup-failed":
            cooldown = _positive_int_env(
                "SENTRIX_BACKUP_ALERT_COOLDOWN_SECONDS",
                DEFAULT_BACKUP_ALERT_COOLDOWN_SECONDS,
                minimum=900,
                maximum=7 * 86400,
            )
        else:
            cooldown = _positive_int_env(
                "SENTRIX_ACTIONABLE_ALERT_COOLDOWN_SECONDS",
                DEFAULT_ALERT_COOLDOWN_SECONDS,
                minimum=900,
                maximum=7 * 86400,
            )

        if (
            state.get("last_alert_key") == key
            and now_value - int(state.get("last_alert_at") or 0) < cooldown
        ):
            return

        await current_send(runtime_bot, key, detail)

    actionable_health_alert._sentrix_noise_fixed = True
    actionable_health_alert._sentrix_original = current_health
    send_actionable_alert._sentrix_noise_fixed = True
    send_actionable_alert._sentrix_original = current_send
    production_ops._health_alert = actionable_health_alert
    production_ops._send_ops_alert = send_actionable_alert
    _ALERTS_PATCHED = True

    logger.info(
        "Production SentriX : alertes et mutations anti-nuke limitées au service primaire %s.",
        _primary_service_name() or DEFAULT_PRIMARY_SERVICE,
    )


__all__ = ["install"]
