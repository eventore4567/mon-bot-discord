"""Dernière garde de stabilité SentriX.

Cette extension est volontairement petite et non destructive. Elle est chargée après
``cogs.slash_error_completion_guard`` sur Railway et réaffirme uniquement quatre invariants
qui avaient encore des chemins historiques concurrents :

- aucune limite locale cooldown/par-minute ne doit bloquer +ai/+chat ;
- l'autorité ``no_cooldown_final`` doit rester active après tous les cogs ;
- un archivage de pièces jointes partiellement téléchargé ne doit jamais associer le
  mauvais fichier à la mauvaise pièce jointe dans les logs ;
- la personnalité IA adaptative doit être installée après tous les wrappers IA historiques.

Les quotas journaliers IA, permissions, modération de contenu et restrictions de salons/
rôles ne sont pas modifiés. Les réglages cooldown historiques restent en base pour assurer
la compatibilité avec les configurations existantes, mais ils ne throttlent plus le runtime.
"""
from __future__ import annotations

import logging
import types
from typing import Any

from discord.ext import commands

logger = logging.getLogger("bot.final-stability-guard")
_MARKER = "_sentrix_final_stability_guard"


def _disable_ai_local_throttle(bot: commands.Bot) -> bool:
    """Neutralise les deux limites mémoire propres au cog Ai, sans toucher aux quotas DB."""
    cog = bot.get_cog("Ai")
    if cog is None:
        return False

    def no_local_cooldown(_self, _guild_id: int, _user_id: int, _seconds: int):
        return None

    def no_minute_limit(_self, _guild_id: int, _user_id: int, _limit: int) -> bool:
        return False

    no_local_cooldown._sentrix_zero_ai_throttle = True
    no_minute_limit._sentrix_zero_ai_throttle = True
    cog._check_cooldown = types.MethodType(no_local_cooldown, cog)
    cog._check_minute_limit = types.MethodType(no_minute_limit, cog)

    last_used = getattr(cog, "_last_used", None)
    if isinstance(last_used, dict):
        last_used.clear()
    minute_bucket = getattr(cog, "_minute_bucket", None)
    if isinstance(minute_bucket, dict):
        minute_bucket.clear()
    return True


def _install_safe_attachment_archive() -> bool:
    """Évite le décalage attachment/file lorsqu'un téléchargement Discord échoue.

    ``logs_unified_v6`` construit ensuite sa preview avec ``zip(attachments, files)``. Si
    Discord refuse uniquement le premier fichier, une liste compacte des seuls succès
    décalerait toutes les associations. Le comportement sûr est donc tout-ou-rien : si un
    seul des fichiers demandés manque, le log textuel est conservé mais aucun binaire n'est
    joint. Cela préfère une archive partielle sans fichier à une archive factuellement
    fausse.
    """
    try:
        from . import logs_unified_v6 as logs_v6
    except Exception:
        logger.exception("Impossible d'importer logs_unified_v6 pour la garde fichiers.")
        return False

    current = logs_v6._best_effort_files
    if getattr(current, _MARKER, False):
        return True

    async def all_or_none_files(attachments):
        selected = list(attachments or [])[:10]
        files = list(await current(selected))
        if len(files) == len(selected):
            return files

        # Empêche aussi de garder ouverts des fichiers temporaires qui ne seront pas envoyés.
        for file in files:
            close = getattr(file, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        logger.warning(
            "Archive fichiers partielle ignorée pour éviter une mauvaise association (%s/%s).",
            len(files),
            len(selected),
        )
        return []

    setattr(all_or_none_files, _MARKER, True)
    all_or_none_files._sentrix_original = current
    logs_v6._best_effort_files = all_or_none_files
    return True


def _reassert_zero_cooldown(bot: commands.Bot) -> bool:
    """Réinstalle l'autorité finale après tous les autres wrappers runtime."""
    try:
        from . import no_cooldown_final

        no_cooldown_final.install(bot)
        return bool(getattr(bot, "no_cooldown_final_state", {}).get("installed"))
    except Exception:
        logger.exception("Réaffirmation zéro cooldown impossible.")
        return False


def _install_ai_personality(bot: commands.Bot) -> bool:
    """Installe la personnalité adaptative après les anciens wrappers IA."""
    try:
        from . import ai_personality_final

        return bool(ai_personality_final.install(bot))
    except Exception:
        logger.exception("Installation de la personnalité IA dynamique impossible.")
        return False


def _state(bot: commands.Bot) -> dict[str, Any]:
    value = getattr(bot, "final_stability_guard_state", None)
    if isinstance(value, dict):
        return value
    value = {}
    bot.final_stability_guard_state = value
    return value


def install(bot: commands.Bot) -> dict[str, Any]:
    """Applique les réparations idempotentes et expose leur état pour le diagnostic."""
    zero_cooldown = _reassert_zero_cooldown(bot)
    ai_throttle_disabled = _disable_ai_local_throttle(bot)
    safe_attachment_archive = _install_safe_attachment_archive()
    ai_personality = _install_ai_personality(bot)

    state = _state(bot)
    state.update(
        {
            "installed": True,
            "zero_cooldown": zero_cooldown,
            "ai_local_throttle_disabled": ai_throttle_disabled,
            "safe_attachment_archive": safe_attachment_archive,
            "ai_dynamic_personality": ai_personality,
        }
    )
    setattr(bot, _MARKER, True)

    if not zero_cooldown:
        logger.error("Garde finale active mais l'autorité zéro cooldown n'a pas pu être confirmée.")
    if not ai_throttle_disabled:
        logger.warning("Garde finale : cog Ai absent au moment de l'installation.")
    if not safe_attachment_archive:
        logger.warning("Garde finale : protection archive fichiers non installée.")
    if not ai_personality:
        logger.warning("Garde finale : personnalité IA dynamique non installée.")

    logger.warning(
        "Garde stabilité finale active : zéro cooldown=%s, throttle IA=%s, fichiers sûrs=%s, personnalité IA=%s.",
        zero_cooldown,
        ai_throttle_disabled,
        safe_attachment_archive,
        ai_personality,
    )
    return state


async def setup(bot: commands.Bot) -> None:
    install(bot)


__all__ = [
    "install",
    "_disable_ai_local_throttle",
    "_install_safe_attachment_archive",
    "_reassert_zero_cooldown",
    "_install_ai_personality",
]
