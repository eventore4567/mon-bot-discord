"""Réduit le bruit des alertes de production SentriX.

Les métriques de lenteur restent visibles dans les logs/diagnostics, mais ne doivent pas
notifier le propriétaire à répétition : les gros constructeurs de serveur sont
volontairement longs et une ancienne entrée `slow_commands` pouvait rester en mémoire et
être renvoyée toutes les 15 minutes.

Les notifications Discord sont réservées aux incidents réellement actionnables :
- plusieurs erreurs techniques récentes ;
- échec du backup SQLite.

Sur Railway, un seul service est autorisé à envoyer ces alertes afin d'éviter les doublons
quand deux services exécutent le même dépôt.
"""
from __future__ import annotations

import logging
import os
import time

from discord.ext import commands

logger = logging.getLogger("bot.production-alert-noise-fix")
_PATCHED = False

DEFAULT_ALERT_COOLDOWN_SECONDS = 60 * 60
DEFAULT_BACKUP_ALERT_COOLDOWN_SECONDS = 6 * 60 * 60
DEFAULT_PRIMARY_SERVICE = "mon-bot-discord"


def _positive_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _is_primary_alert_service() -> bool:
    """Un seul service Railway envoie les notifications Discord d'exploitation."""
    service = (os.getenv("RAILWAY_SERVICE_NAME") or "").strip().casefold()
    if not service:
        # Local / autre hébergeur : ne pas désactiver les alertes par erreur.
        return True
    primary = (
        os.getenv("SENTRIX_ALERT_PRIMARY_SERVICE")
        or DEFAULT_PRIMARY_SERVICE
    ).strip().casefold()
    if not primary:
        return True
    return service == primary or primary in service


def install(bot: commands.Bot, extension_name: str = "") -> None:
    """Patch idempotent appliqué après le chargement de production_ops."""
    del bot, extension_name
    global _PATCHED
    if _PATCHED:
        return

    try:
        from . import production_ops
    except Exception:
        # production_ops n'est peut-être pas encore chargé ; stability_runtime rappellera
        # cet installateur après l'extension suivante.
        return

    current_health = getattr(production_ops, "_health_alert", None)
    current_send = getattr(production_ops, "_send_ops_alert", None)
    if current_health is None or current_send is None:
        return
    if getattr(current_health, "_sentrix_noise_fixed", False):
        _PATCHED = True
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
            # La clé ne contient volontairement PAS les compteurs : 5 puis 6 TypeError
            # restent le même incident et respectent donc le cooldown.
            fingerprint = ",".join(sorted(name for name, _count in top))
            return (
                f"errors:{fingerprint}",
                f"{len(errors)} erreurs techniques en 5 min ({detail}).",
            )

        ops = production_ops._ops_state(runtime_bot)
        if ops.get("last_backup_ok") is False:
            reason = str(ops.get("last_backup_error") or "erreur inconnue")[:100]
            return "backup-failed", f"Le dernier backup SQLite a échoué ({reason})."

        # IMPORTANT : les commandes lentes et requêtes DB lentes restent dans les logs et
        # +healthcheck, mais ne déclenchent plus de message Discord au propriétaire.
        return None, None

    async def send_actionable_alert(runtime_bot: commands.Bot, key: str, detail: str) -> None:
        if not _is_primary_alert_service():
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
    _PATCHED = True

    logger.info(
        "Alertes production anti-spam actives : lenteurs en logs uniquement, incidents réels avec cooldown et service primaire unique."
    )


__all__ = ["install"]
