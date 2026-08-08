"""Fiabilise TOUT le moteur de logs Discord de SentriX.

Ce patch est volontairement additif : il ne remplace pas les listeners existants de
cogs/logs.py. Il corrige leur routage et les enrichit avec l'audit Discord afin que les
actions effectuées par SentriX, un autre bot ou un membre du staff soient journalisées.

Principes :
- auto-réparation du salon pour toutes les catégories de logs activées ;
- détection des salons logs-* même s'ils ont un emoji/préfixe ou des accents ;
- attribution de l'acteur via l'Audit Log Discord quand c'est possible ;
- prise en charge explicite des kicks externes (Discord n'a pas d'événement on_member_kick) ;
- suppression des doublons ban/unban/timeout/kick quand SentriX a déjà créé une fiche de
  sanction détaillée ;
- un log volontairement désactivé reste désactivé.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from datetime import timedelta

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.universal-logs-fix")

_INSTALLED_ROUTING = False
_INSTALLED_DEDUPE = False
_INSTALLED_AUDIT = False
_INSTALLED_KICK = False
_BOOTSTRAP_STARTED = False

_GENERIC_ACTIONS = {
    "Membre banni": ("ban", "tempban"),
    "Membre débanni": ("unban",),
    "Membre expulsé (kick)": ("kick",),
}

# Noms normalisés. _plain_name retire accents, emojis et séparateurs décoratifs.
_LOG_CHANNEL_NAMES: dict[str, set[str]] = {
    "messages": {"logs-messages", "log-messages", "messages-logs"},
    "members": {"logs-membres", "logs-members", "log-membres", "members-logs"},
    "voice": {"logs-vocaux", "logs-vocal", "logs-voice", "voice-logs"},
    "roles": {"logs-roles", "log-roles", "roles-logs"},
    "server": {"logs-serveur", "logs-server", "log-serveur", "server-logs"},
    "moderation": {
        "logs-moderation", "log-moderation", "moderation-logs", "logs-sanctions",
    },
    "tickets": {"logs-tickets", "log-tickets", "tickets-logs"},
    "automod": {
        "logs-securite", "logs-security", "logs-automod", "security-logs", "automod-logs",
    },
    "economy": {"logs-economie", "logs-economy", "economy-logs"},
    "levels": {"logs-niveaux", "logs-levels", "levels-logs"},
    "ai": {"logs-ia", "logs-ai", "ai-logs"},
    "games": {"logs-jeux", "logs-games", "games-logs"},
    "system": {"logs-systeme", "logs-system", "system-logs"},
}

_AUDIT_BY_TITLE = {
    "Membre banni": discord.AuditLogAction.ban,
    "Membre débanni": discord.AuditLogAction.unban,
    "Timeout modifié": discord.AuditLogAction.member_update,
    "Surnom modifié": discord.AuditLogAction.member_update,
    "Rôles d'un membre modifiés": discord.AuditLogAction.member_role_update,
    "Salon créé": discord.AuditLogAction.channel_create,
    "Salon supprimé": discord.AuditLogAction.channel_delete,
    "Salon modifié": discord.AuditLogAction.channel_update,
    "Rôle créé": discord.AuditLogAction.role_create,
    "Rôle supprimé": discord.AuditLogAction.role_delete,
    "Rôle modifié": discord.AuditLogAction.role_update,
    "Serveur modifié": discord.AuditLogAction.guild_update,
    "Message supprimé": discord.AuditLogAction.message_delete,
}


def _plain_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", (value or "").strip())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("_", "-")
    # Les décorations Discord du type 🛡️・logs-modération deviennent logs-moderation.
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    # Si un emoji/label précède le vrai nom, on garde la partie à partir de logs/log.
    match = re.search(r"(?:^|-)(logs?-.+)$", text)
    return match.group(1) if match else text


def _valid_log_channel(
    guild: discord.Guild,
    channel_id: int | None,
    *,
    needs_file: bool = False,
) -> discord.TextChannel | None:
    if not channel_id:
        return None
    try:
        channel = guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return None
    if not isinstance(channel, discord.TextChannel):
        return None
    ok, _reason = log_service.validate_channel(guild, channel.id, needs_file=needs_file)
    return channel if ok else None


def _named_log_channel(guild: discord.Guild, log_type: str) -> discord.TextChannel | None:
    names = _LOG_CHANNEL_NAMES.get(log_type, set())
    if not names:
        return None
    # Priorité à une catégorie appelée LOGS, puis n'importe où dans le serveur.
    ordered = sorted(
        guild.text_channels,
        key=lambda c: 0 if c.category and _plain_name(c.category.name) in {"logs", "log"} else 1,
    )
    for channel in ordered:
        if _plain_name(channel.name) in names and _valid_log_channel(guild, channel.id):
            return channel
    return None


async def _legacy_candidates(bot: commands.Bot, guild_id: int, log_type: str) -> list[int]:
    candidates: list[int] = []
    try:
        conf = await bot.db.get_guild_config(guild_id)
    except Exception:
        return candidates
    if not conf:
        return candidates

    meta = log_service.LOG_TYPES.get(log_type, {})
    keys: list[str] = []
    legacy = meta.get("legacy_column")
    if legacy:
        keys.append(str(legacy))
    # L'ancien salon général servait de repli aux catégories historiques.
    if log_type in {"messages", "members", "voice", "roles", "server", "moderation", "automod"}:
        keys.append("log_channel")

    for key in keys:
        try:
            value = conf[key]
        except (KeyError, IndexError, TypeError):
            value = None
        if value:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value not in candidates:
                candidates.append(value)
    return candidates


async def _persist_target(bot: commands.Bot, guild: discord.Guild, log_type: str, channel_id: int) -> None:
    await log_service.set_log_channel(bot, guild.id, log_type, channel_id)
    meta = log_service.LOG_TYPES.get(log_type, {})
    legacy = meta.get("legacy_column")
    if legacy:
        try:
            await bot.db.set_guild_config(guild.id, str(legacy), channel_id)
        except Exception:
            logger.debug("Impossible de synchroniser la colonne legacy %s.", legacy, exc_info=True)
    if log_type == "moderation":
        try:
            await bot.db.set_guild_config(guild.id, "log_channel", channel_id)
        except Exception:
            pass


async def _repair_log_target(
    bot: commands.Bot,
    guild: discord.Guild,
    log_type: str,
    *,
    needs_file: bool = False,
) -> int | None:
    """Répare un log ACTIVÉ sans jamais réactiver un log volontairement désactivé."""
    setting = await log_service.get_log_setting(bot, guild.id, log_type)
    if not setting["enabled"]:
        return None

    current = _valid_log_channel(guild, setting["channel_id"], needs_file=needs_file)
    if current is not None:
        return current.id

    for channel_id in await _legacy_candidates(bot, guild.id, log_type):
        channel = _valid_log_channel(guild, channel_id, needs_file=needs_file)
        if channel is None:
            continue
        await _persist_target(bot, guild, log_type, channel.id)
        logger.info(
            "Log %s réparé sur %s (%s) via la configuration existante : #%s.",
            log_type, guild.name, guild.id, channel.name,
        )
        return channel.id

    channel = _named_log_channel(guild, log_type)
    if channel is not None:
        await _persist_target(bot, guild, log_type, channel.id)
        logger.info(
            "Log %s réparé sur %s (%s) via #%s.",
            log_type, guild.name, guild.id, channel.name,
        )
        return channel.id
    return None


async def _bootstrap_named_channels(bot: commands.Bot) -> None:
    """Initialise les salons logs-* reconnus sans écraser un réglage OFF déjà enregistré."""
    await bot.wait_until_ready()
    await asyncio.sleep(3)
    for guild in list(bot.guilds):
        for log_type in log_service.LOG_TYPES:
            try:
                row = await bot.db.fetchone(
                    "SELECT enabled, channel_id FROM log_settings WHERE guild_id = ? AND log_type = ?",
                    (guild.id, log_type),
                )
                if row is None:
                    channel = _named_log_channel(guild, log_type)
                    if channel is None:
                        continue
                    await log_service.get_log_setting(bot, guild.id, log_type)
                    await _persist_target(bot, guild, log_type, channel.id)
                    await log_service.set_log_enabled(bot, guild.id, log_type, True)
                    continue

                if bool(row["enabled"]) and _valid_log_channel(guild, row["channel_id"]) is None:
                    await _repair_log_target(bot, guild, log_type)
            except Exception:
                logger.exception(
                    "Bootstrap du log %s impossible sur %s (%s).",
                    log_type, guild.name, guild.id,
                )


def _target_id(embed: discord.Embed) -> int | None:
    footer = getattr(getattr(embed, "footer", None), "text", None) or ""
    match = re.search(r"(\d{10,24})", footer)
    return int(match.group(1)) if match else None


def _field_value(embed: discord.Embed, name: str) -> str:
    for field in embed.fields:
        if str(field.name) == name:
            return str(field.value)
    return ""


def _first_id(value: str) -> int | None:
    match = re.search(r"(\d{10,24})", value or "")
    return int(match.group(1)) if match else None


def _timeout_action(embed: discord.Embed) -> tuple[str, ...]:
    state = _field_value(embed, "Nouvel état")
    return ("unmute",) if "retir" in state.casefold() else ("mute",)


async def _recent_sanction_exists(
    bot: commands.Bot,
    guild_id: int,
    user_id: int,
    actions: tuple[str, ...],
    *,
    wait: float = 1.15,
) -> bool:
    if wait:
        await asyncio.sleep(wait)
    placeholders = ",".join("?" for _ in actions)
    row = await bot.db.fetchone(
        f"""
        SELECT 1
        FROM sanctions
        WHERE guild_id = ?
          AND user_id = ?
          AND action IN ({placeholders})
          AND created_at >= ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (guild_id, user_id, *actions, int(time.time()) - 10),
    )
    return row is not None


async def _find_audit_entry(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: int | None,
    *,
    channel_id: int | None = None,
) -> discord.AuditLogEntry | None:
    me = guild.me
    if me is None or not me.guild_permissions.view_audit_log:
        return None
    after = discord.utils.utcnow() - timedelta(seconds=15)
    try:
        async for entry in guild.audit_logs(limit=10, action=action, after=after):
            entry_target_id = getattr(getattr(entry, "target", None), "id", None)
            if target_id is not None and entry_target_id != target_id:
                continue
            if channel_id is not None:
                extra_channel_id = getattr(getattr(getattr(entry, "extra", None), "channel", None), "id", None)
                if extra_channel_id is not None and extra_channel_id != channel_id:
                    continue
            return entry
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


def _audit_lookup_target(embed: discord.Embed, title: str) -> tuple[int | None, int | None]:
    if title == "Message supprimé":
        # L'audit message_delete cible l'AUTEUR du message, pas l'ID du message supprimé.
        return _first_id(_field_value(embed, "Auteur")), _first_id(_field_value(embed, "Salon"))
    return _target_id(embed), None


def _actor_text(entry: discord.AuditLogEntry) -> str:
    actor = entry.user
    if actor is None:
        return "Inconnu"
    mention = getattr(actor, "mention", str(actor))
    kind = "🤖 Bot" if getattr(actor, "bot", False) else "👤 Membre/Staff"
    return f"{mention}\n`{actor.id}` • {kind}"


def _install_routing_repair(bot: commands.Bot) -> None:
    global _INSTALLED_ROUTING, _BOOTSTRAP_STARTED
    if not _INSTALLED_ROUTING:
        original_send_log = log_service.send_log
        if not getattr(original_send_log, "_sentrix_universal_log_repair", False):
            async def send_log_repaired(
                inner_bot,
                guild: discord.Guild,
                log_type: str,
                embed: discord.Embed,
                file: discord.File | None = None,
            ) -> bool:
                try:
                    setting = await log_service.get_log_setting(inner_bot, guild.id, log_type)
                    if setting["enabled"]:
                        ok, _reason = log_service.validate_channel(
                            guild,
                            setting["channel_id"],
                            needs_file=file is not None,
                        )
                        if not ok:
                            await _repair_log_target(
                                inner_bot,
                                guild,
                                log_type,
                                needs_file=file is not None,
                            )
                except Exception:
                    # Une panne de log ne doit jamais annuler la vraie action Discord.
                    logger.exception(
                        "Réparation du log %s impossible sur %s (%s).",
                        log_type, guild.name, guild.id,
                    )
                return await original_send_log(inner_bot, guild, log_type, embed, file=file)

            send_log_repaired._sentrix_universal_log_repair = True
            log_service.send_log = send_log_repaired
        _INSTALLED_ROUTING = True
        logger.info("Auto-réparation universelle des salons de logs activée.")

    if not _BOOTSTRAP_STARTED:
        asyncio.create_task(_bootstrap_named_channels(bot), name="sentrix-universal-logs-bootstrap")
        _BOOTSTRAP_STARTED = True


def _install_generic_dedupe(bot: commands.Bot) -> None:
    global _INSTALLED_DEDUPE
    if _INSTALLED_DEDUPE:
        return
    logs_cog = bot.get_cog("Logs")
    if logs_cog is None:
        return

    cls = type(logs_cog)
    original_send = cls._send
    if getattr(original_send, "_sentrix_moderation_log_dedupe", False):
        _INSTALLED_DEDUPE = True
        return

    async def send_without_duplicate(self, guild: discord.Guild, config_key: str, embed: discord.Embed):
        if config_key == "log_moderation":
            title = str(embed.title or "")
            actions = _GENERIC_ACTIONS.get(title)
            if title == "Timeout modifié":
                actions = _timeout_action(embed)
            target_id = _target_id(embed)
            if actions and target_id:
                try:
                    if await _recent_sanction_exists(self.bot, guild.id, target_id, actions):
                        return
                except Exception:
                    logger.exception(
                        "Déduplication du log modération impossible (guild=%s, user=%s).",
                        guild.id, target_id,
                    )
        return await original_send(self, guild, config_key, embed)

    send_without_duplicate._sentrix_moderation_log_dedupe = True
    cls._send = send_without_duplicate
    _INSTALLED_DEDUPE = True
    logger.info("Déduplication des sanctions Discord activée.")


def _install_audit_enrichment(bot: commands.Bot) -> None:
    global _INSTALLED_AUDIT
    if _INSTALLED_AUDIT:
        return
    logs_cog = bot.get_cog("Logs")
    if logs_cog is None:
        return

    cls = type(logs_cog)
    original_send = cls._send
    if getattr(original_send, "_sentrix_external_actor_audit", False):
        _INSTALLED_AUDIT = True
        return

    async def send_with_audit_actor(self, guild: discord.Guild, config_key: str, embed: discord.Embed):
        title = str(embed.title or "")
        action = _AUDIT_BY_TITLE.get(title)
        already_has_actor = any(str(field.name) in {"Effectué par", "Modérateur", "Acteur"} for field in embed.fields)
        if action is not None and not already_has_actor:
            target_id, channel_id = _audit_lookup_target(embed, title)
            # Petit délai : l'entrée d'audit arrive parfois après l'événement Gateway.
            await asyncio.sleep(0.35)
            entry = await _find_audit_entry(guild, action, target_id, channel_id=channel_id)
            if entry is not None:
                embed.add_field(name="Effectué par", value=_actor_text(entry), inline=False)
                if entry.reason:
                    embed.add_field(name="Raison Audit Log", value=str(entry.reason)[:1024], inline=False)
        return await original_send(self, guild, config_key, embed)

    send_with_audit_actor._sentrix_external_actor_audit = True
    cls._send = send_with_audit_actor
    _INSTALLED_AUDIT = True
    logger.info("Attribution Audit Log des actions staff/autres bots activée.")


def _install_external_kick_listener(bot: commands.Bot) -> None:
    global _INSTALLED_KICK
    if _INSTALLED_KICK:
        return

    async def on_member_remove_external_kick(member: discord.Member):
        # on_member_remove couvre aussi un départ volontaire. Seul un AuditLogAction.kick
        # récent et visant exactement ce membre transforme l'événement en log modération.
        await asyncio.sleep(0.7)
        entry = await _find_audit_entry(member.guild, discord.AuditLogAction.kick, member.id)
        if entry is None:
            return
        try:
            if await _recent_sanction_exists(
                bot, member.guild.id, member.id, ("kick",), wait=0.45
            ):
                return
        except Exception:
            logger.exception("Vérification du doublon kick impossible.")

        embed = discord.Embed(
            title="Membre expulsé (kick)",
            colour=0xEB459E,
            timestamp=discord.utils.utcnow(),
            description=f"{member} — <@{member.id}>",
        )
        embed.add_field(name="Effectué par", value=_actor_text(entry), inline=False)
        if entry.reason:
            embed.add_field(name="Raison", value=str(entry.reason)[:1024], inline=False)
        embed.set_footer(text=f"Identifiant : {member.id}")
        await log_service.send_log(bot, member.guild, "moderation", embed)

    bot.add_listener(on_member_remove_external_kick, "on_member_remove")
    _INSTALLED_KICK = True
    logger.info("Détection des kicks faits par le staff ou d'autres bots activée.")


def install(bot: commands.Bot) -> None:
    """Peut être appelé après chaque extension ; tous les patches sont idempotents."""
    _install_routing_repair(bot)
    _install_generic_dedupe(bot)
    _install_audit_enrichment(bot)
    _install_external_kick_listener(bot)
