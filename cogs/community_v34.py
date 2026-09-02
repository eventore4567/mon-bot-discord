"""SentriX V3.4 — slash stables, texte natif et IA à faible latence.

Cette couche corrige trois irritants visibles :
- les erreurs slash et les petites réponses ne sont plus enfermées dans des embeds ;
- les commandes slash personnelles sont privées par défaut, sauf actions réellement partagées ;
- le watchdog slash ne laisse plus de placeholder/générique en double ;
- +ai utilise Luna pour les demandes courantes et renvoie la réponse avant les écritures DB
  de télémétrie/mémoire, qui sont persistées en arrière-plan.
"""
from __future__ import annotations

import asyncio
import logging
import re
import types
from typing import Any

import discord
from discord.ext import commands

from utils import ai_service
from . import community_v3, community_v32

logger = logging.getLogger("bot.community-v34")

# Seules les commandes dont le résultat est naturellement communautaire restent publiques
# en slash. Les autres slash sont privées par défaut : Discord affiche « Toi seul(e) peux
# voir ceci », ce qui est adapté aux profils, réglages, IA, économie, erreurs, etc.
SHARED_SLASH_ROOTS = frozenset({
    "poll", "say", "announce", "suggest",
    "giveaway-create", "giveaway-list", "event-create", "event-join", "event-leave",
    "event-list", "tournament-create", "tournament-start", "tournament-join",
    "tournament-list", "rolepanel", "verify-panel",
    "play", "pause", "resume", "skip", "stop", "queue", "nowplaying", "volume",
    "loop", "shuffle", "remove-from-queue", "clear-queue",
    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz",
    "blackjack", "slots", "coinflip", "dice", "luckyroll", "highlow", "memory",
    "reaction", "scramble", "wordgame", "emojiquiz", "colorquiz", "fasttype",
    "duel", "connect4", "numberduel", "reactionduel", "quizduel", "triviastart",
    "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage", "emoji-race",
})

# Ces interfaces gagnent réellement à rester en carte/fiche. Tout le reste est aplati en
# texte Discord natif dès qu'il n'y a pas d'image/fichier à conserver.
RICH_ROOTS = frozenset({
    "help", "profile", "setup", "ticketsetup", "logsetup", "aisetup", "designsetup",
    "embed", "avatar", "info", "userinfo", "botinfo", "server-growth",
    "command-stats", "economyleaderboard", "leaderboard-levels", "repleaderboard",
    "shop", "shoppanel", "rolepanel", "verify-panel",
})

_GENERIC_TITLES = frozenset({
    "information", "action terminee", "action terminée", "action impossible",
    "a verifier", "à vérifier", "verification necessaire", "vérification nécessaire",
    "erreur", "succes", "succès", "avertissement", "termine", "terminé",
})


def _root_from_command(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _root_from_ctx(ctx: commands.Context) -> str:
    return _root_from_command(getattr(ctx, "command", None))


def _root_from_interaction(interaction: discord.Interaction | None) -> str:
    if interaction is None:
        return ""
    command = getattr(interaction, "command", None)
    if command is not None:
        return _root_from_command(command)
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        return str(data.get("name") or "").casefold()
    return ""


def _is_private_slash(root: str) -> bool:
    return bool(root and root not in SHARED_SLASH_ROOTS)


def _has_media(embed: discord.Embed) -> bool:
    image = getattr(embed, "image", None)
    thumb = getattr(embed, "thumbnail", None)
    return bool(
        (image and getattr(image, "url", None))
        or (thumb and getattr(thumb, "url", None))
    )


def _clean(value: Any) -> str:
    return community_v32.strip_decorative_emoji(value or "").strip()


def _embed_to_text(embed: discord.Embed | None, *, root: str = "") -> str | None:
    """Convertit une fiche légère en Markdown Discord sans perdre ses champs utiles."""
    if not isinstance(embed, discord.Embed) or root in RICH_ROOTS or _has_media(embed):
        return None

    title = _clean(embed.title)
    description = _clean(embed.description)
    lines: list[str] = []

    if title and not title.casefold().startswith("sentrix /") and title.casefold() not in _GENERIC_TITLES:
        lines.append(f"**{title}**")
    if description:
        lines.append(description)

    for field in list(embed.fields)[:18]:
        name = _clean(field.name)
        value = _clean(field.value)
        if not value:
            continue
        if name and name.casefold() not in {"information", "detail", "détail"}:
            lines.append(f"**{name} :** {value}")
        else:
            lines.append(value)

    text = "\n".join(line for line in lines if line).strip()
    return text[:4000] if text else None


def _merge_content(args: tuple, kwargs: dict, text: str) -> tuple[tuple, dict]:
    new_args = list(args)
    if new_args:
        current = str(new_args[0] or "").strip()
        new_args[0] = f"{current}\n{text}".strip() if current else text
        kwargs.pop("content", None)
    else:
        current = str(kwargs.get("content") or "").strip()
        kwargs["content"] = f"{current}\n{text}".strip() if current else text
    return tuple(new_args), kwargs


def _unwrap_original(callable_obj):
    seen = set()
    current = callable_obj
    while hasattr(current, "_sentrix_original") and id(current) not in seen:
        seen.add(id(current))
        current = getattr(current, "_sentrix_original")
    return current


def _install_context_policy() -> None:
    current_send = commands.Context.send
    if getattr(current_send, "_sentrix_v34_plain", False):
        return
    base_send = _unwrap_original(current_send)

    async def send_v34(self: commands.Context, *args, **kwargs):
        root = _root_from_ctx(self)
        if self.interaction is not None and _is_private_slash(root):
            kwargs["ephemeral"] = True

        embed = kwargs.get("embed")
        text = _embed_to_text(embed, root=root)
        if text:
            kwargs.pop("embed", None)
            args, kwargs = _merge_content(args, kwargs, text)

        embeds = kwargs.get("embeds")
        if isinstance(embeds, (list, tuple)) and len(embeds) == 1:
            text = _embed_to_text(embeds[0], root=root)
            if text:
                kwargs.pop("embeds", None)
                args, kwargs = _merge_content(args, kwargs, text)

        return await base_send(self, *args, **kwargs)

    send_v34._sentrix_v34_plain = True
    send_v34._sentrix_original = base_send
    commands.Context.send = send_v34

    current_defer = getattr(commands.Context, "defer", None)
    if current_defer is not None and not getattr(current_defer, "_sentrix_v34_private", False):
        base_defer = _unwrap_original(current_defer)

        async def defer_v34(self: commands.Context, *args, **kwargs):
            root = _root_from_ctx(self)
            if self.interaction is not None and _is_private_slash(root):
                kwargs["ephemeral"] = True
            return await base_defer(self, *args, **kwargs)

        defer_v34._sentrix_v34_private = True
        defer_v34._sentrix_original = base_defer
        commands.Context.defer = defer_v34


def _install_interaction_plain_responses() -> None:
    """Aplatit aussi les confirmations simples envoyées directement par des boutons/modals."""
    current = discord.InteractionResponse.send_message
    if getattr(current, "_sentrix_v34_plain", False):
        return

    async def send_message_v34(self, *args, **kwargs):
        interaction = getattr(self, "_parent", None)
        root = _root_from_interaction(interaction)
        embed = kwargs.get("embed")
        text = _embed_to_text(embed, root=root)
        if text:
            kwargs.pop("embed", None)
            args, kwargs = _merge_content(args, kwargs, text)
        embeds = kwargs.get("embeds")
        if isinstance(embeds, (list, tuple)) and len(embeds) == 1:
            text = _embed_to_text(embeds[0], root=root)
            if text:
                kwargs.pop("embeds", None)
                args, kwargs = _merge_content(args, kwargs, text)
        return await current(self, *args, **kwargs)

    send_message_v34._sentrix_v34_plain = True
    send_message_v34._sentrix_original = current
    discord.InteractionResponse.send_message = send_message_v34


def _slash_error_text(error: Exception) -> str:
    original = getattr(error, "original", error)
    name = type(original).__name__
    if name in {"BotPermissionError"}:
        return _clean(getattr(original, "message", None) or "Vous n'avez pas accès à cette commande.")
    if name == "BotBlacklistedError":
        reason = _clean(getattr(original, "reason", None) or "Aucune raison fournie")
        return f"Tu n'es pas autorisé à utiliser SentriX. Raison : {reason}"
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        return f"Cette commande est en recharge. Réessaie dans {max(1, round(error.retry_after))} s."
    if isinstance(error, discord.app_commands.MissingPermissions):
        return "Tu n'as pas les permissions nécessaires pour cette commande."
    if isinstance(error, discord.app_commands.BotMissingPermissions):
        return "SentriX n'a pas les permissions Discord nécessaires pour terminer cette action."
    if isinstance(error, (discord.app_commands.TransformerError, discord.app_commands.CommandSignatureMismatch)):
        return "Une valeur sélectionnée n'est plus valide. Rouvre la commande et choisis de nouveau les options."
    if isinstance(original, discord.Forbidden):
        return "Discord a refusé cette action. Vérifie les permissions et la position du rôle SentriX."
    if isinstance(error, discord.app_commands.CheckFailure):
        return "Tu n'as pas accès à cette commande."
    return "La commande a rencontré une erreur technique. Réessaie dans quelques instants."


def _install_slash_error_handler(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_v34_slash_errors", False):
        return

    async def slash_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        command_name = getattr(getattr(interaction, "command", None), "qualified_name", "inconnue")
        original = getattr(error, "original", error)
        if not isinstance(error, (
            discord.app_commands.CommandOnCooldown,
            discord.app_commands.MissingPermissions,
            discord.app_commands.BotMissingPermissions,
            discord.app_commands.TransformerError,
            discord.app_commands.CommandSignatureMismatch,
            discord.app_commands.CheckFailure,
        )) and type(original).__name__ not in {"BotPermissionError", "BotBlacklistedError"}:
            logger.exception("Erreur slash V3.4 dans /%s", command_name, exc_info=original)

        text = _slash_error_text(error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible d'envoyer l'erreur slash V3.4 pour /%s.", command_name)

    bot.tree.on_error = slash_error
    bot._sentrix_v34_slash_errors = True


def _install_slash_watchdog_policy(bot: commands.Bot) -> None:
    try:
        from . import slash_reliability_v7 as slash
    except Exception:
        return

    if not getattr(slash._defer_watchdog, "_sentrix_v34", False):
        async def defer_watchdog_v34(interaction: discord.Interaction) -> None:
            # Répond avant la limite Discord sans laisser attendre presque deux secondes.
            await asyncio.sleep(0.9)
            active_bot = interaction.client
            try:
                if not interaction.response.is_done():
                    root = _root_from_interaction(interaction)
                    await interaction.response.defer(
                        thinking=True,
                        ephemeral=_is_private_slash(root),
                    )
                    slash._mark_auto_deferred(interaction)
                    if isinstance(active_bot, commands.Bot):
                        slash._mark_state(
                            active_bot,
                            last_response_type=slash._response_type_name(interaction),
                            last_response_done=True,
                            last_result="watchdog_deferred_v34",
                            last_error=None,
                        )
            except (discord.InteractionResponded, discord.NotFound):
                return
            except discord.HTTPException as exc:
                if isinstance(active_bot, commands.Bot):
                    slash._mark_state(active_bot, last_result="watchdog_defer_failed", last_error=type(exc).__name__)

        defer_watchdog_v34._sentrix_v34 = True
        slash._defer_watchdog = defer_watchdog_v34

    if not getattr(slash._settle_deferred, "_sentrix_v34", False):
        async def settle_deferred_v34(interaction: discord.Interaction, command_name: str) -> bool:
            tracked = slash._take_auto_deferred(interaction)
            if not interaction.response.is_done():
                return tracked
            if not tracked and not slash._interaction_is_deferred(interaction):
                return False
            try:
                original = await interaction.original_response()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException):
                return tracked
            if slash._original_response_has_payload(original):
                return tracked
            try:
                # Si la vraie commande a répondu via followup, le placeholder ne sert plus à
                # rien. Le supprimer évite le faux « Commande exécutée avec succès » en double.
                await interaction.delete_original_response()
                slash._mark_state(bot, last_result="empty_defer_removed_v34", last_error=None)
                return True
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return tracked

        settle_deferred_v34._sentrix_v34 = True
        slash._settle_deferred = settle_deferred_v34


def _install_fast_ai(bot: commands.Bot) -> None:
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None or getattr(ai_cog, "_sentrix_v34_fast_prepare", False):
        return

    # Le client sera recréé avec les modèles/timeout courants au prochain appel.
    ai_service.REQUEST_TIMEOUT_SECONDS = 12.0
    ai_service._TEXT_CLIENT = None

    async def fast_prepare(this, *, guild_id, channel_id, user_id, author_name,
                           question, forced_advanced: bool = False, suffix: str = "",
                           command: str = "ai") -> dict:
        settings = await ai_service.get_settings(bot, guild_id) if guild_id else dict(ai_service.DEFAULT_AI_SETTINGS)
        if guild_id and not settings["enabled"]:
            return {"ok": False, "error": "L'IA est désactivée sur ce serveur."}

        problem = ai_service.moderate_input(question, max_length=settings["max_question_length"])
        if problem:
            return {"ok": False, "error": _clean(problem)}

        wait = this._check_cooldown(guild_id or 0, user_id, settings["cooldown_seconds"])
        if wait:
            return {"ok": False, "error": f"Attends encore {wait:.0f} s avant une nouvelle demande."}
        if this._check_minute_limit(guild_id or 0, user_id, settings["per_minute_limit"]):
            return {"ok": False, "error": "Trop de demandes en une minute. Patiente un peu."}

        if guild_id:
            used_today = await ai_service.get_daily_usage(bot, guild_id, user_id)
            if used_today >= settings["daily_limit"]:
                return {"ok": False, "error": f"Limite quotidienne atteinte ({settings['daily_limit']} demandes/jour)."}

        # Speed-first : Luna pour les demandes ordinaires, Terra seulement si la demande est
        # réellement complexe, Sol uniquement lorsqu'une route avancée le demande.
        if forced_advanced:
            model_key = ai_service.MODEL_SOL
        elif ai_service.is_complex_request(question):
            model_key = ai_service.MODEL_TERRA
        else:
            model_key = ai_service.MODEL_LUNA
        effort = "high" if model_key == ai_service.MODEL_SOL else ("low" if model_key == ai_service.MODEL_TERRA else "none")
        effort = ai_service.pick_reasoning_effort(model_key, effort)

        previous_response_id = None
        if guild_id and settings["memory_enabled"]:
            _, previous_response_id = await ai_service.get_conversation_history(
                bot, guild_id, channel_id, user_id, settings["memory_minutes"],
            )

        instructions = await this._build_system_instructions(user_id, author_name)
        try:
            # Si l'ancien wrapper de contexte n'est plus autour de cette méthode, on garde
            # tout de même le contexte public utile du serveur.
            server_context = await community_v3._server_context(bot, guild_id, channel_id)
            if server_context and "CONTEXTE PUBLIC DU SERVEUR DISCORD" not in instructions:
                instructions += server_context
        except Exception:
            pass

        prompt = question + suffix
        result = await ai_service.generate(
            prompt,
            model_key=model_key,
            reasoning_effort=effort,
            previous_response_id=previous_response_id,
            instructions=instructions,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            command=command,
            web_search=ai_service.needs_web_search(question),
        )
        if not result.ok:
            return {"ok": False, "error": _clean(ai_service.error_message(result.error))}
        if not str(result.text or "").strip():
            return {"ok": False, "error": "L'IA n'a pas renvoyé de texte. Réessaie."}

        async def persist_after_reply():
            if not guild_id:
                return
            try:
                tokens = ai_service.estimate_tokens(prompt) + ai_service.estimate_tokens(result.text)
                await ai_service.record_usage(bot, guild_id, user_id, tokens_estimate=tokens)
                if settings["memory_enabled"]:
                    await ai_service.append_conversation(bot, guild_id, channel_id, user_id, "user", question)
                    await ai_service.append_conversation(
                        bot, guild_id, channel_id, user_id, "assistant", result.text,
                        response_id=result.response_id,
                    )
            except Exception:
                logger.exception("V3.4 : persistance IA différée impossible.")

        asyncio.create_task(persist_after_reply())
        return {"ok": True, "text": result.text, "model_key": result.model_key or model_key}

    ai_cog._prepare_and_generate = types.MethodType(fast_prepare, ai_cog)
    ai_cog._sentrix_v34_fast_prepare = True


def install(bot: commands.Bot) -> None:
    _install_context_policy()
    _install_interaction_plain_responses()
    _install_slash_error_handler(bot)
    _install_slash_watchdog_policy(bot)
    _install_fast_ai(bot)

    if getattr(bot, "_sentrix_community_v34_installed", False):
        return

    async def ready_listener():
        _install_context_policy()
        _install_interaction_plain_responses()
        _install_slash_error_handler(bot)
        _install_slash_watchdog_policy(bot)
        _install_fast_ai(bot)

    bot.add_listener(ready_listener, "on_ready")
    bot._sentrix_community_v34_installed = True
    bot._sentrix_community_v34_state = {
        "ready": True,
        "features": (
            "plain_responses_default",
            "private_slash_default",
            "plain_slash_errors",
            "slash_placeholder_cleanup",
            "fast_gpt56_routing",
            "async_ai_persistence",
        ),
    }
    logger.info("SentriX V3.4 actif : slash stables, texte libre et IA speed-first.")
