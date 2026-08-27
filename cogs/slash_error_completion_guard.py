"""Ferme les placeholders slash puis installe les autorités finales du runtime.

Cette extension est la dernière ajoutée par ``railway_boot.py``. V5/V5.1 sont installées
tout à la fin : livraison auto-réparée, garantie des listeners Logs indépendamment du
cache SQLite, puis erreurs via le transport Discord brut.
"""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.slash-error-completion")
_ERROR_FALLBACK = (
    "La commande est terminée, mais SentriX a rencontré une erreur pendant sa finalisation."
)


def _state(bot: commands.Bot) -> dict:
    state = getattr(bot, "slash_error_completion_guard_state", None)
    if not isinstance(state, dict):
        state = {
            "installed": False,
            "wrapped_at": None,
            "last_error_seen_at": None,
            "last_command_name": None,
            "last_error_type": None,
            "last_result": None,
            "last_settled_at": None,
            "last_cleanup_error": None,
        }
        bot.slash_error_completion_guard_state = state
    return state


def _safe_health(bot: commands.Bot) -> dict:
    state = _state(bot)
    return {
        "installed": bool(state.get("installed")),
        "wrapped_at": state.get("wrapped_at"),
        "last_error_seen_at": state.get("last_error_seen_at"),
        "last_command_name": state.get("last_command_name"),
        "last_error_type": state.get("last_error_type"),
        "last_result": state.get("last_result"),
        "last_settled_at": state.get("last_settled_at"),
        "last_cleanup_error": state.get("last_cleanup_error"),
    }


def _install_health_patch() -> None:
    try:
        from web import production_health
    except Exception:
        return

    current = production_health._safe_slash_health
    if getattr(current, "_sentrix_slash_error_completion_health", False):
        return

    def safe_slash_health_with_error_completion(bot):
        payload = current(bot)
        if not isinstance(payload, dict):
            payload = {}
        payload["error_completion_guard"] = _safe_health(bot)
        return payload

    safe_slash_health_with_error_completion._sentrix_slash_error_completion_health = True
    safe_slash_health_with_error_completion._sentrix_original = current
    production_health._safe_slash_health = safe_slash_health_with_error_completion


def _command_name(interaction: discord.Interaction) -> str:
    command = getattr(interaction, "command", None)
    name = getattr(command, "qualified_name", None) or getattr(command, "name", None)
    if name:
        return str(name)[:120]
    payload = interaction.data if isinstance(interaction.data, dict) else {}
    return str(payload.get("name") or "commande")[:120]


def _error_type(error) -> str:
    original = getattr(error, "original", error)
    return type(original).__name__[:120]


def _is_deferred(interaction: discord.Interaction) -> bool:
    response_type = getattr(interaction.response, "type", None)
    return response_type in {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }


def _has_payload(message: discord.InteractionMessage) -> bool:
    return bool(
        (getattr(message, "content", "") or "").strip()
        or getattr(message, "embeds", None)
        or getattr(message, "attachments", None)
        or getattr(message, "components", None)
        or getattr(message, "stickers", None)
        or getattr(message, "poll", None)
    )


async def _settle_error_defer(
    bot: commands.Bot,
    interaction: discord.Interaction,
    error,
) -> None:
    state = _state(bot)
    state.update(
        {
            "last_error_seen_at": int(time.time()),
            "last_command_name": _command_name(interaction),
            "last_error_type": _error_type(error),
            "last_cleanup_error": None,
        }
    )

    if not interaction.response.is_done() or not _is_deferred(interaction):
        state["last_result"] = "response_not_deferred"
        return

    try:
        original = await interaction.original_response()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException) as exc:
        state["last_result"] = "original_unavailable"
        state["last_cleanup_error"] = type(exc).__name__
        return

    if _has_payload(original):
        state["last_result"] = "payload_present"
        return

    try:
        await interaction.edit_original_response(
            content=None,
            embed=embeds.error(_ERROR_FALLBACK, title="Erreur de commande"),
            attachments=[],
            view=None,
        )
        state["last_result"] = "error_defer_settled_embed"
        state["last_settled_at"] = int(time.time())
        logger.info(
            "Placeholder slash fermé en embed sur erreur : /%s (%s).",
            state["last_command_name"],
            state["last_error_type"],
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        state["last_result"] = "edit_failed"
        state["last_cleanup_error"] = type(exc).__name__
        logger.debug("Impossible de fermer le defer slash sur erreur.", exc_info=True)


def install(bot: commands.Bot) -> None:
    current = bot.tree.on_error
    if getattr(current, "_sentrix_slash_error_completion", False):
        state = _state(bot)
        state["installed"] = True
        _install_health_patch()
        return

    async def error_with_defer_completion(interaction: discord.Interaction, error):
        try:
            return await current(interaction, error)
        finally:
            try:
                await _settle_error_defer(bot, interaction, error)
            except Exception as cleanup_exc:
                state = _state(bot)
                state["last_result"] = "cleanup_failed"
                state["last_cleanup_error"] = type(cleanup_exc).__name__
                logger.exception("Nettoyage final du defer slash impossible.")

    error_with_defer_completion._sentrix_slash_error_completion = True
    error_with_defer_completion._sentrix_original = current
    bot.tree.on_error = error_with_defer_completion

    state = _state(bot)
    state["installed"] = True
    state["wrapped_at"] = int(time.time())
    _install_health_patch()
    logger.info("Garde slash erreur active : tout defer vide est fermé même sur exception.")


async def setup(bot: commands.Bot) -> None:
    install(bot)

    from . import command_embed_invariant
    from . import production_embed_log_repair_v3

    command_embed_invariant.install(bot)
    await production_embed_log_repair_v3.setup(bot)

    from . import live_log_delivery_v5
    live_log_delivery_v5.install(bot)

    from . import log_listener_guarantee_v51
    await log_listener_guarantee_v51.install(bot)

    # Le critère strict est installé avant la commande V2 : seuls les salons issus du
    # rebuild officiel peuvent être considérés comme déjà sains.
    from . import owner_log_rebuild_v2_health
    owner_log_rebuild_v2_health.install()

    from . import owner_log_rebuild_v2
    await owner_log_rebuild_v2.install(bot)

    # Notification indépendante des logs : le créateur reçoit un MP quand SentriX quitte
    # ou est retiré d'un serveur.
    from . import guild_departure_notify
    await guild_departure_notify.install(bot)

    from . import final_error_embed_v5
    final_error_embed_v5.install(bot)

    # Autorité finale V6 : conserve le transport V5.3 qui fonctionne et unifie uniquement
    # la structure, les tickets, les références de salons et la neuvième route fichiers.
    from . import logs_unified_v6
    await logs_unified_v6.install(bot)

    # Compatibilité historique #234 : cette couche peut encore créer son ancien quota,
    # mais l'autorité juste après le supprime immédiatement et neutralise aussi les
    # decorators cooldown/max_concurrency attachés aux commandes.
    from . import cooldown_isolation_fix
    cooldown_isolation_fix.install(bot)

    # Autorité Railway : aucune commande normale ne reste en cooldown et aucun
    # max_concurrency discord.py générique ne peut produire « commande déjà en cours ».
    from . import no_cooldown_final
    no_cooldown_final.install(bot)

    # DERNIÈRE autorité pour le chat naturel : un seul service Railway et un seul listener
    # Ai.on_message peuvent répondre à un message Discord donné. Aucun cooldown n'est créé.
    from . import passive_ai_single_reply_final
    passive_ai_single_reply_final.install(bot)

    logger.info(
        "Runtime final V6 actif : logs V5.3/V6 + zéro cooldown + une seule réponse IA passive."
    )
