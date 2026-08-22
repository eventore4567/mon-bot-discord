"""SentriX V3.3 — correctifs UX visibles et routage professionnel.

Cette couche corrige les problèmes réellement observés en production :
- une réponse OpenAI vide n'est plus considérée comme un succès ; un second appel Terra est tenté ;
- les commandes slash personnelles répondent en privé quand Discord le permet ;
- les petites réponses sans champs/images sont rendues en texte natif Discord ;
- les logs hérités ne retombent plus dans un salon général faute de salon dédié ;
- les logs de messages du bot lui-même sont ignorés pour éviter le bruit et les boucles ;
- les alertes de production ne sont plus envoyées dans un salon Discord public ;
- une commande IA de quelques secondes n'est plus traitée comme une alerte de production.

Les commandes préfixées (+) sont des messages Discord classiques : Discord ne permet pas de
les rendre « ephemeral ». La confidentialité automatique ci-dessous concerne donc les slash.
"""
from __future__ import annotations

import logging
import os
import re
import types
import unicodedata
from typing import Any

import discord
from discord.ext import commands

from database.db import PRIMARY_CREATOR_ID
from utils import ai_service, log_service
from . import community_v32

logger = logging.getLogger("bot.community-v33")

PRIVATE_SLASH_ROOTS = frozenset({
    "help", "profile", "balance", "economy", "inventory", "shop",
    "daily", "weekly", "work", "level", "stats", "reputation", "voice-time",
    "reminder-list", "invites", "invited-by", "ai", "sentrix", "summarize",
    "explain", "rewrite", "fact-check", "improve", "correct", "ai-translate",
    "code", "ticket",
})

_LOG_HINTS: dict[str, tuple[str, ...]] = {
    "messages": ("message", "messages"),
    "members": ("membre", "membres", "member", "members"),
    "voice": ("vocal", "voice"),
    "roles": ("role", "roles"),
    "server": ("salon", "salons", "server", "serveur", "channel", "channels"),
    "moderation": ("moderation", "mod"),
    "automod": ("automod", "securite", "security"),
    "tickets": ("ticket", "tickets"),
    "economy": ("economy", "economie"),
    "levels": ("level", "levels", "niveau", "niveaux"),
    "ai": ("ai", "ia"),
    "games": ("games", "game", "jeux", "jeu"),
    "system": ("system", "systeme", "ops", "production"),
}

AI_COMMAND_ROOTS = frozenset({
    "ai", "chat", "sentrix", "ask", "summarize", "explain", "rewrite",
    "fact-check", "improve", "correct", "ai-translate", "code", "image-prompt",
})


def _root_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _row_get(row: Any, key: str, default=None):
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, default)


def _normalise_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _candidate_log_channel(guild: discord.Guild, log_type: str):
    hints = _LOG_HINTS.get(log_type, (log_type,))
    best = None
    best_score = -1
    bot_member = guild.me
    if bot_member is None:
        return None

    for channel in guild.text_channels:
        name = _normalise_name(channel.name)
        if "log" not in name:
            continue
        perms = channel.permissions_for(bot_member)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            continue

        score = 1
        for hint in hints:
            hint_norm = _normalise_name(hint)
            if hint_norm and hint_norm in name:
                score += 6
        if name.startswith("logs-") or name.startswith("log-"):
            score += 2
        if score > best_score:
            best = channel
            best_score = score

    # Un simple salon nommé « logs » ne doit pas être choisi automatiquement pour une
    # catégorie précise : on exige au moins un indice métier dans le nom.
    return best if best_score >= 7 else None


def _embed_source_channel_id(embed: discord.Embed) -> int | None:
    for field in embed.fields:
        if str(field.name or "").casefold() != "salon":
            continue
        match = re.search(r"<#(\d+)>", str(field.value or ""))
        if match:
            return int(match.group(1))
    return None


def _embed_mentions_bot_author(bot: commands.Bot, embed: discord.Embed) -> bool:
    user = bot.user
    if user is None:
        return False
    uid = str(user.id)
    for field in embed.fields:
        if str(field.name or "").casefold() == "auteur" and uid in str(field.value or ""):
            return True
    return False


def _clean_log_embed(embed: discord.Embed) -> discord.Embed:
    strip = community_v32.strip_decorative_emoji
    if embed.title:
        embed.title = strip(embed.title)[:256] or "Journal"
    if embed.description:
        embed.description = strip(embed.description)[:4096] or None
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=(strip(field.name)[:256] or "Information"),
            value=(strip(field.value)[:1024] or "—"),
            inline=field.inline,
        )
    footer = getattr(embed, "footer", None)
    if footer and getattr(footer, "text", None):
        icon = getattr(footer, "icon_url", None)
        text = strip(footer.text)[:2048] or "SentriX"
        if icon:
            embed.set_footer(text=text, icon_url=icon)
        else:
            embed.set_footer(text=text)
    return embed


def _simple_embed_to_text(embed: discord.Embed | None, *, has_view: bool) -> str | None:
    if not isinstance(embed, discord.Embed) or has_view:
        return None
    if embed.fields:
        return None
    image = getattr(embed, "image", None)
    thumbnail = getattr(embed, "thumbnail", None)
    if (image and getattr(image, "url", None)) or (thumbnail and getattr(thumbnail, "url", None)):
        return None
    description = community_v32.strip_decorative_emoji(embed.description or "").strip()
    title = community_v32.strip_decorative_emoji(embed.title or "").strip()
    if not description:
        return None
    generic = (
        not title
        or title.casefold().startswith("sentrix /")
        or title.casefold() in {
            "information", "action terminee", "action terminée", "action impossible",
            "a verifier", "à vérifier", "verification necessaire", "vérification nécessaire",
            "erreur", "succes", "succès", "avertissement",
        }
    )
    return description if generic else f"**{title}**\n{description}"


def _install_private_plain_context() -> None:
    current_send = commands.Context.send
    if getattr(current_send, "_sentrix_v33_private_plain", False):
        return

    # V3.2 forçait les commandes publiques à ne PAS être ephemeral. On remonte à son
    # implémentation précédente afin de pouvoir appliquer la politique inverse demandée.
    base_send = getattr(current_send, "_sentrix_original", current_send)

    async def send_v33(self: commands.Context, *args, **kwargs):
        root = _root_name(self)
        if self.interaction is not None and root in PRIVATE_SLASH_ROOTS:
            kwargs.setdefault("ephemeral", True)

        text = _simple_embed_to_text(kwargs.get("embed"), has_view=kwargs.get("view") is not None)
        if text:
            kwargs.pop("embed", None)
            if args:
                mutable = list(args)
                if mutable and mutable[0]:
                    mutable[0] = f"{mutable[0]}\n{text}"
                elif mutable:
                    mutable[0] = text
                args = tuple(mutable)
            else:
                existing = kwargs.get("content")
                kwargs["content"] = f"{existing}\n{text}" if existing else text
        return await base_send(self, *args, **kwargs)

    send_v33._sentrix_v33_private_plain = True
    send_v33._sentrix_original = base_send
    commands.Context.send = send_v33

    current_defer = getattr(commands.Context, "defer", None)
    if current_defer is not None and not getattr(current_defer, "_sentrix_v33_private", False):
        async def defer_v33(self: commands.Context, *args, **kwargs):
            if self.interaction is not None and _root_name(self) in PRIVATE_SLASH_ROOTS:
                kwargs.setdefault("ephemeral", True)
            return await current_defer(self, *args, **kwargs)

        defer_v33._sentrix_v33_private = True
        defer_v33._sentrix_original = current_defer
        commands.Context.defer = defer_v33


def _install_ai_empty_retry() -> None:
    current = ai_service.generate
    if getattr(current, "_sentrix_v33_empty_retry", False):
        return

    async def generate_v33(prompt, *args, **kwargs):
        result = await current(prompt, *args, **kwargs)
        if not result.ok or str(result.text or "").strip():
            return result

        logger.warning(
            "Réponse IA vide détectée (commande=%s, modèle=%s) : seconde tentative Terra.",
            kwargs.get("command"), kwargs.get("model_key"),
        )
        retry_kwargs = dict(kwargs)
        retry_kwargs["model_key"] = ai_service.MODEL_TERRA
        retry_kwargs["reasoning_effort"] = "low"
        # Une réponse précédente défectueuse ne doit pas contaminer la relance.
        retry_kwargs["previous_response_id"] = None
        command = str(retry_kwargs.get("command") or "ai")
        retry_kwargs["command"] = f"{command}-empty-retry"
        retry = await current(prompt, *args, **retry_kwargs)
        if retry.ok and str(retry.text or "").strip():
            return retry

        logger.error("Deux réponses IA vides successives — commande=%s.", command)
        return ai_service.AiResult(
            error=ai_service.ERROR_GENERIC,
            model_key=ai_service.MODEL_TERRA,
        )

    generate_v33._sentrix_v33_empty_retry = True
    generate_v33._sentrix_original = current
    ai_service.generate = generate_v33


def _install_log_policy(bot: commands.Bot) -> None:
    current = log_service.send_log
    if getattr(current, "_sentrix_v33_no_general", False):
        return

    async def send_log_v33(active_bot, guild: discord.Guild, log_type: str, embed: discord.Embed,
                           file: discord.File | None = None) -> bool:
        # Les propres messages de SentriX ne doivent pas remplir le journal Messages.
        if log_type == "messages" and _embed_mentions_bot_author(active_bot, embed):
            return False

        try:
            setting = await log_service.get_log_setting(active_bot, guild.id, log_type)
        except Exception:
            logger.exception("V3.3 : lecture du réglage de log impossible (%s).", log_type)
            return False

        if not setting.get("enabled"):
            return False

        channel_id = setting.get("channel_id")
        meta = log_service.LOG_TYPES.get(log_type, {})
        legacy_column = meta.get("legacy_column")
        inherited_global_fallback = False

        if legacy_column and legacy_column != "ticket_log_channel" and channel_id:
            try:
                conf = await active_bot.db.get_guild_config(guild.id)
                dedicated = _row_get(conf, legacy_column)
                global_log = _row_get(conf, "log_channel")
                inherited_global_fallback = bool(
                    not dedicated and global_log and int(global_log) == int(channel_id)
                )
            except Exception:
                inherited_global_fallback = False

        if inherited_global_fallback:
            candidate = _candidate_log_channel(guild, log_type)
            if candidate is not None:
                await log_service.set_log_channel(active_bot, guild.id, log_type, candidate.id)
                channel_id = candidate.id
                logger.info(
                    "V3.3 : log %s rerouté automatiquement vers #%s au lieu du salon global.",
                    log_type, candidate.name,
                )
            else:
                # Aucun salon dédié sûr : mieux vaut couper ce type de log que polluer général.
                await log_service.set_log_enabled(active_bot, guild.id, log_type, False)
                logger.warning(
                    "V3.3 : log %s désactivé car il héritait du salon global et aucun salon dédié n'existe.",
                    log_type,
                )
                return False

        source_channel_id = _embed_source_channel_id(embed)
        if source_channel_id and channel_id and int(source_channel_id) == int(channel_id) and log_type == "messages":
            # Évite les journaux récursifs lorsque quelqu'un modifie un message dans le salon de logs.
            return False

        return await current(active_bot, guild, log_type, _clean_log_embed(embed), file=file)

    send_log_v33._sentrix_v33_no_general = True
    send_log_v33._sentrix_original = current
    log_service.send_log = send_log_v33


def _install_ops_policy(bot: commands.Bot) -> None:
    try:
        from . import production_ops
    except Exception:
        return

    current_target = production_ops._resolve_alert_target
    if not getattr(current_target, "_sentrix_v33_private_ops", False):
        async def private_ops_target(active_bot: commands.Bot):
            # Les alertes techniques ne doivent jamais apparaître dans général. Elles vont
            # uniquement en DM au destinataire ops (ou au créateur principal par défaut).
            raw_user = (os.getenv("SENTRIX_OPS_ALERT_USER_ID") or "").strip()
            user_id = int(raw_user) if raw_user.isdigit() else PRIMARY_CREATOR_ID
            user = active_bot.get_user(user_id)
            if user is None:
                try:
                    user = await active_bot.fetch_user(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    return None
            return user

        private_ops_target._sentrix_v33_private_ops = True
        private_ops_target._sentrix_original = current_target
        production_ops._resolve_alert_target = private_ops_target

    current_health = production_ops._health_alert
    if not getattr(current_health, "_sentrix_v33_ai_latency", False):
        def health_v33(active_bot: commands.Bot):
            key, detail = current_health(active_bot)
            if not key or not str(key).startswith("slow-command:"):
                return key, detail
            command = str(key).split(":", 1)[1].casefold().strip()
            root = command.split(" ", 1)[0]
            if root not in AI_COMMAND_ROOTS:
                return key, detail
            state = getattr(active_bot, "_sentrix_observability_v26", {})
            latest = list(state.get("slow_commands") or [])[-1:] if isinstance(state, dict) else []
            ms = float(latest[0].get("ms") or 0) if latest else 0.0
            # Une génération IA entre 6 et 30 s peut être normale et ne mérite pas une
            # alerte Discord. Au-delà de 30 s on conserve l'alerte.
            if ms < 30_000:
                return None, None
            return key, detail

        health_v33._sentrix_v33_ai_latency = True
        health_v33._sentrix_original = current_health
        production_ops._health_alert = health_v33


def install(bot: commands.Bot) -> None:
    _install_ai_empty_retry()
    _install_private_plain_context()
    _install_log_policy(bot)
    _install_ops_policy(bot)

    if getattr(bot, "_sentrix_community_v33_installed", False):
        return

    async def ready_listener():
        _install_ai_empty_retry()
        _install_private_plain_context()
        _install_log_policy(bot)
        _install_ops_policy(bot)

    bot.add_listener(ready_listener, "on_ready")
    bot._sentrix_community_v33_installed = True
    bot._sentrix_community_v33_state = {
        "ready": True,
        "features": (
            "ai_empty_retry",
            "private_slash_personal_commands",
            "plain_simple_responses",
            "no_general_log_fallback",
            "bot_message_log_suppression",
            "private_ops_alerts",
        ),
    }
    logger.info("SentriX V3.3 actif : IA vide corrigée, réponses privées, texte libre et logs hors général.")
