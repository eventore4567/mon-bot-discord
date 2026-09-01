"""Fiabilite des interactions slash SentriX.

Cette couche ne gere ni le catalogue ni les permissions. Elle ajoute seulement :
- un auto-defer pour les commandes slash lentes ;
- la fermeture des placeholders de defer restes vides apres une commande terminee ;
- une telemetrie minimale pour verifier le chemin reel en production ;
- un relais inter-instance secret-free pour distinguer SentriX de Bot'Odboug.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import discord
from aiohttp import ClientSession, ClientTimeout
from discord.ext import commands

from . import permission_guard
from utils import instance_identity

logger = logging.getLogger("bot.slash-reliability-v7")
_ROOT_ALIASES = {"nick": "nickname"}
_DEFER_DELAY_SECONDS = 1.8
_AUTO_DEFER_TTL_SECONDS = 300.0
_RUNTIME_RELAY_INTERVAL_SECONDS = 30.0
_RUNTIME_RELAY_URL = (
    os.getenv("SENTRIX_RUNTIME_RELAY_URL")
    or "https://mon-bot-discord-production-8944.up.railway.app/api/runtime/slash-heartbeat"
).strip()


def _runtime_state(bot: commands.Bot) -> dict:
    state = getattr(bot, "slash_reliability_v7_state", None)
    if not isinstance(state, dict):
        state = {
            "installed_at": None,
            "watchdog_listener_registered": False,
            "completion_guard_registered": False,
            "relay_loop_registered": False,
            "last_interaction_seen_at": None,
            "last_command_name": None,
            "last_completion_at": None,
            "last_response_type": None,
            "last_response_done": None,
            "last_original_had_payload": None,
            "last_result": None,
            "last_error": None,
            "last_publish_at": None,
            "last_publish_error": None,
        }
        bot.slash_reliability_v7_state = state
    return state


def _mark_state(bot: commands.Bot, **values) -> None:
    _runtime_state(bot).update(values)


def _response_type_name(interaction: discord.Interaction) -> str | None:
    response_type = getattr(interaction.response, "type", None)
    return getattr(response_type, "name", None) or (str(response_type) if response_type is not None else None)


def _interaction_command_name(interaction: discord.Interaction) -> str | None:
    command = getattr(interaction, "command", None)
    name = getattr(command, "qualified_name", None) or getattr(command, "name", None)
    if name:
        return str(name)[:120]
    data = getattr(interaction, "data", None)
    if isinstance(data, dict) and data.get("name"):
        return str(data.get("name"))[:120]
    return None


def _relay_payload(bot: commands.Bot) -> dict:
    state = _runtime_state(bot)
    bot_user = getattr(bot, "user", None)
    return {
        "service": instance_identity.railway_service_name() or "unknown",
        "service_id": (os.getenv("RAILWAY_SERVICE_ID") or "").strip() or None,
        "brand": instance_identity.brand_label(),
        "bot_user_id": str(getattr(bot_user, "id", "")) or None,
        "bot_user_name": str(bot_user)[:120] if bot_user is not None else None,
        "runtime_installed": bool(getattr(bot, "_sentrix_slash_reliability_v7_installed", False)),
        "watchdog_listener_registered": bool(state.get("watchdog_listener_registered")),
        "completion_guard_registered": bool(state.get("completion_guard_registered")),
        "last_interaction_seen_at": state.get("last_interaction_seen_at"),
        "last_command_name": state.get("last_command_name"),
        "last_completion_at": state.get("last_completion_at"),
        "last_response_type": state.get("last_response_type"),
        "last_response_done": state.get("last_response_done"),
        "last_original_had_payload": state.get("last_original_had_payload"),
        "last_result": state.get("last_result"),
        "last_error": state.get("last_error"),
        "updated_at": int(time.time()),
    }


async def _publish_runtime_relay(bot: commands.Bot) -> None:
    if not _RUNTIME_RELAY_URL:
        return
    try:
        timeout = ClientTimeout(total=5)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(
                _RUNTIME_RELAY_URL,
                json=_relay_payload(bot),
                headers={"User-Agent": "sentrix-slash-runtime-relay/1"},
            ) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP_{response.status}")
        _mark_state(bot, last_publish_at=int(time.time()), last_publish_error=None)
    except Exception as exc:
        _mark_state(bot, last_publish_error=type(exc).__name__)
        logger.debug("Publication du relais slash inter-instance impossible.", exc_info=True)


def _schedule_runtime_relay(bot: commands.Bot) -> None:
    try:
        asyncio.create_task(_publish_runtime_relay(bot))
    except RuntimeError:
        return


def _install_runtime_relay_loop(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_slash_relay_loop_registered", False):
        return

    async def relay_loop() -> None:
        await bot.wait_until_ready()
        await asyncio.sleep(2)
        while not bot.is_closed():
            await _publish_runtime_relay(bot)
            await asyncio.sleep(_RUNTIME_RELAY_INTERVAL_SECONDS)

    bot._sentrix_slash_relay_loop_registered = True
    bot._sentrix_slash_relay_task = asyncio.create_task(relay_loop())
    _mark_state(bot, relay_loop_registered=True)


def _auto_deferred(bot: commands.Bot) -> dict[int, float]:
    tracker = getattr(bot, "_sentrix_auto_deferred_slash", None)
    if not isinstance(tracker, dict):
        tracker = {}
        bot._sentrix_auto_deferred_slash = tracker
    return tracker


def _prune_auto_deferred(bot: commands.Bot) -> None:
    tracker = _auto_deferred(bot)
    if not tracker:
        return
    now = time.monotonic()
    stale = [interaction_id for interaction_id, stamp in tracker.items() if now - stamp > _AUTO_DEFER_TTL_SECONDS]
    for interaction_id in stale:
        tracker.pop(interaction_id, None)


def _mark_auto_deferred(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if not isinstance(bot, commands.Bot):
        return
    tracker = _auto_deferred(bot)
    tracker[int(interaction.id)] = time.monotonic()
    if len(tracker) > 5000:
        _prune_auto_deferred(bot)


def _take_auto_deferred(interaction: discord.Interaction) -> bool:
    bot = interaction.client
    if not isinstance(bot, commands.Bot):
        return False
    return _auto_deferred(bot).pop(int(interaction.id), None) is not None


def _original_response_has_payload(message: discord.InteractionMessage) -> bool:
    """Vrai si la reponse originale contient deja un vrai resultat de commande."""
    return bool(
        (getattr(message, "content", "") or "").strip()
        or getattr(message, "embeds", None)
        or getattr(message, "attachments", None)
        or getattr(message, "components", None)
        or getattr(message, "stickers", None)
        or getattr(message, "poll", None)
    )


def _interaction_is_deferred(interaction: discord.Interaction) -> bool:
    """Couvre le defer watchdog et les defer faits directement par une commande."""
    response_type = getattr(interaction.response, "type", None)
    return response_type in {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }


async def _settle_deferred(interaction: discord.Interaction, command_name: str) -> bool:
    """Ferme un placeholder slash differe reste vide apres succes.

    Si la commande a deja remplace le defer par du texte, un embed, un fichier ou un
    composant, cette reponse est conservee telle quelle.
    """
    bot = interaction.client
    tracked_by_watchdog = _take_auto_deferred(interaction)
    response_done = bool(interaction.response.is_done())
    if isinstance(bot, commands.Bot):
        _mark_state(
            bot,
            last_completion_at=int(time.time()),
            last_command_name=command_name[:120],
            last_response_type=_response_type_name(interaction),
            last_response_done=response_done,
            last_original_had_payload=None,
            last_result="completion_seen",
            last_error=None,
        )

    if not response_done:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="response_not_done")
        return tracked_by_watchdog

    if not tracked_by_watchdog and not _interaction_is_deferred(interaction):
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="not_deferred")
        return False

    try:
        original = await interaction.original_response()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException) as exc:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="original_unavailable", last_error=type(exc).__name__)
        return tracked_by_watchdog

    has_payload = _original_response_has_payload(original)
    if isinstance(bot, commands.Bot):
        _mark_state(bot, last_original_had_payload=has_payload)
    if has_payload:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="payload_present")
        return tracked_by_watchdog

    try:
        await interaction.edit_original_response(
            content="Commande exécutée avec succès.",
            embeds=[],
            attachments=[],
            view=None,
        )
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="settled", last_error=None)
        logger.info(
            "Defer slash resolu apres completion : /%s (user=%s, guild=%s, watchdog=%s).",
            command_name,
            getattr(interaction.user, "id", None),
            interaction.guild_id,
            tracked_by_watchdog,
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="edit_failed", last_error=type(exc).__name__)
        logger.debug("Impossible de cloturer le defer pour /%s.", command_name, exc_info=True)
        return tracked_by_watchdog
    return True


def _install_canonical_root_mapping() -> None:
    current = permission_guard.interaction_root_name
    if getattr(current, "_sentrix_slash_v7_canonical", False):
        return

    def canonical_root(interaction: discord.Interaction) -> str:
        root = current(interaction)
        return _ROOT_ALIASES.get(root, root)

    canonical_root._sentrix_slash_v7_canonical = True
    permission_guard.interaction_root_name = canonical_root


async def _defer_watchdog(interaction: discord.Interaction) -> None:
    await asyncio.sleep(_DEFER_DELAY_SECONDS)
    bot = interaction.client
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
            _mark_auto_deferred(interaction)
            if isinstance(bot, commands.Bot):
                _mark_state(
                    bot,
                    last_response_type=_response_type_name(interaction),
                    last_response_done=True,
                    last_result="watchdog_deferred",
                    last_error=None,
                )
                _schedule_runtime_relay(bot)
    except (discord.InteractionResponded, discord.NotFound):
        return
    except discord.HTTPException as exc:
        if isinstance(bot, commands.Bot):
            _mark_state(bot, last_result="watchdog_defer_failed", last_error=type(exc).__name__)
            _schedule_runtime_relay(bot)
        logger.debug("Auto-defer slash impossible.", exc_info=True)


def _install_watchdog_listener(bot: commands.Bot) -> None:
    """Observe les interactions sans remplacer tree.interaction_check.

    Le garde central de permissions/blacklist reste donc exactement celui installe par
    permission_guard.py ; V7 ne fait que lancer son watchdog en parallele.
    """
    if getattr(bot, "_sentrix_slash_watchdog_listener_registered", False):
        return

    async def watch_interaction(interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.application_command:
            return
        _mark_state(
            bot,
            last_interaction_seen_at=int(time.time()),
            last_command_name=_interaction_command_name(interaction),
            last_response_type=_response_type_name(interaction),
            last_response_done=bool(interaction.response.is_done()),
            last_result="interaction_seen",
            last_error=None,
        )
        _schedule_runtime_relay(bot)
        asyncio.create_task(_defer_watchdog(interaction))

    bot.add_listener(watch_interaction, "on_interaction")
    bot._sentrix_slash_watchdog_listener = watch_interaction
    bot._sentrix_slash_watchdog_listener_registered = True
    _mark_state(bot, watchdog_listener_registered=True)


def _install_completion_guard(bot: commands.Bot) -> None:
    """Termine les placeholders defer apres succes, natifs comme hybrides."""
    if getattr(bot, "_sentrix_slash_auto_defer_completion_guard", False):
        return

    async def settle_app_command(
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        name = str(getattr(command, "qualified_name", getattr(command, "name", "commande")))
        await _settle_deferred(interaction, name)
        await _publish_runtime_relay(bot)

    async def settle_hybrid_command(ctx: commands.Context) -> None:
        interaction = getattr(ctx, "interaction", None)
        if interaction is None or interaction.type != discord.InteractionType.application_command:
            return
        command = getattr(ctx, "command", None)
        name = str(getattr(command, "qualified_name", getattr(command, "name", "commande")))
        await _settle_deferred(interaction, name)
        await _publish_runtime_relay(bot)

    bot.add_listener(settle_app_command, "on_app_command_completion")
    bot.add_listener(settle_hybrid_command, "on_command_completion")
    bot._sentrix_slash_auto_defer_completion_guard = True
    _mark_state(bot, completion_guard_registered=True)


def install(bot: commands.Bot) -> None:
    """Installe uniquement la fiabilite interactionnelle, sans toucher au catalogue."""
    if getattr(bot, "_sentrix_slash_reliability_v7_installed", False):
        return
    _runtime_state(bot)
    _install_canonical_root_mapping()
    _install_watchdog_listener(bot)
    _install_completion_guard(bot)
    bot._sentrix_slash_reliability_v7_installed = True
    _mark_state(bot, installed_at=int(time.time()), last_error=None)
    _install_runtime_relay_loop(bot)
    logger.info("Slash Reliability V7 actif : watchdog + completion + relais inter-instance, garde permissions intacte.")


async def _install_production_v9(bot: commands.Bot) -> None:
    """Compatibilite historique si ce module est charge comme extension complete."""
    from . import ai_context_v9, game_seasons_v9, moderation_advisor_v9, production_observability_v9

    # Idempotent : command_runtime_hardening_v18 rejoue load_extension une fois apres une
    # collision d'enregistrement, mais discord.py ne retire que les cogs declares DANS ce
    # module. Sans ces gardes, le retry echouait sur "Cog already loaded" et masquait
    # l'erreur d'origine.
    if bot.get_cog("ProductionObservabilityV9") is None:
        await production_observability_v9.setup(bot)
    await ai_context_v9.setup(bot)
    if bot.get_cog("GameSeasonsV9") is None:
        await game_seasons_v9.setup(bot)
    await moderation_advisor_v9.setup(bot)


async def _install_bot_v10(bot: commands.Bot) -> None:
    """Compatibilite historique du bootstrap V10 ; non utilisee par install()."""
    from . import bot_v10

    if bot.get_cog("BotV10") is not None:
        return

    # BotV10 expose un +health complet. security_v2_runtime enregistre un +health
    # autonome (hors cog) plus tot : la collision faisait echouer bot_v10.setup(), donc
    # tout le chargement de slash_reliability_v7, et BotV10 n'existait jamais. On laisse
    # la place a la version riche, comme le routeur +create le fait pour sa racine.
    existing = bot.get_command("health")
    if existing is not None and getattr(existing, "cog", None) is None:
        bot.remove_command("health")
        logger.warning(
            "+health autonome retire au profit du diagnostic complet de BotV10."
        )

    await bot_v10.setup(bot)


async def setup(bot: commands.Bot) -> None:
    install(bot)
    await _install_production_v9(bot)
    await _install_bot_v10(bot)
