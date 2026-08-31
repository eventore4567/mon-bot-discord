"""SentriX V3 — correctifs finaux création, logs, sécurité et emojis.

Cette couche est volontairement additive : railway_boot charge déjà
``cogs.create_sentrix_v3`` en fin de chaîne de création. Elle répare les anciens
runtimes sans dupliquer les commandes ni effacer les configurations existantes.

Points garantis :
- aucun fallback silencieux des catégories de logs vers ``logs-serveur`` ;
- routage séparé salons / rôles / membres / dossiers / protection / vocal ;
- salons de logs dédiés créés et reliés par ``+create <nom>`` (dont ``+create manox``) ;
- création idempotente des ressources honeypot / vérification ;
- ``+addemoji <a:...>`` refuse de convertir silencieusement un GIF en emoji statique.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import re
import time
import unicodedata
from typing import Any

import aiohttp
import discord
from discord.ext import commands

from utils import checks, embeds, log_categories, log_service

logger = logging.getLogger("bot.create-sentrix-v3")

RUNTIME_MARKER = "Create SentriX V3"
_CREATE_LOCKS: dict[int, asyncio.Lock] = {}
_VOICE_JOINED_AT: dict[tuple[int, int], tuple[int, float]] = {}

LOG_CHANNEL_SPECS: dict[str, tuple[str, tuple[str, ...]]] = {
    "tickets": ("💾・logs-tickets", ("logs-tickets",)),
    "dossiers": ("💾・logs-dossiers", ("logs-dossiers", "logs-invitations")),
    "server": ("💾・logs-serveur", ("logs-serveur", "logs-server")),
    "members": ("💾・logs-membre", ("logs-membre", "logs-membres")),
    "messages": ("💾・logs-messages", ("logs-messages",)),
    "voice": ("💾・logs-vocal", ("logs-vocal", "logs-vocaux")),
    "roles": ("💾・logs-rôles", ("logs-rôles", "logs-roles")),
    "moderation": ("💾・logs-modération", ("logs-modération", "logs-moderation")),
    "spam": (
        "💾・logs-protect-spam-logs",
        ("logs-protect-spam-logs", "logs-spam", "protect-spam-logs"),
    ),
    "automod": ("💾・automod", ("automod", "logs-automod", "logs-sécurité")),
    "raid": ("💾・raidprotect-logs", ("raidprotect-logs", "logs-raid", "raid-protect-logs")),
    "channels": ("💾・logs-salons", ("logs-salons", "logs-channels")),
}

CUSTOM_EMOJI_RE = re.compile(r"<(a?):([A-Za-z0-9_]{2,32}):([0-9]+)>")
USER_MENTION_RE = re.compile(r"<@!?(\d{15,22})>")
ROLE_MENTION_RE = re.compile(r"<@&(\d{15,22})>")
CHANNEL_MENTION_RE = re.compile(r"<#(\d{15,22})>")


def _plain_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _find_category(guild: discord.Guild) -> discord.CategoryChannel | None:
    preferred = ("logs", "journal", "journaux")
    for category in guild.categories:
        cleaned = _plain_name(category.name)
        if cleaned in preferred or cleaned.endswith("logs") or "logs" in cleaned:
            return category
    return None


def _find_text_channel(
    guild: discord.Guild,
    names: tuple[str, ...],
) -> discord.TextChannel | None:
    wanted = {_plain_name(name) for name in names}
    for channel in guild.text_channels:
        cleaned = _plain_name(channel.name)
        if cleaned in wanted:
            return channel
    return None


def _bot_channel_overwrite(guild: discord.Guild) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        embed_links=True,
        attach_files=True,
        manage_messages=True,
        manage_channels=True,
    )


def _log_overwrites(guild: discord.Guild) -> dict[Any, discord.PermissionOverwrite]:
    overwrites: dict[Any, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    if guild.me is not None:
        overwrites[guild.me] = _bot_channel_overwrite(guild)

    # Les journaux restent privés, mais les rôles qui administrent réellement le serveur
    # peuvent les consulter. Ils ne reçoivent pas de nouvelles permissions de modération.
    for role in guild.roles:
        perms = role.permissions
        if role.is_default() or role.managed:
            continue
        if perms.administrator or perms.manage_guild or perms.view_audit_log:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
            )
    return overwrites


def _install_log_catalog() -> None:
    """Étend le registre canonique sans casser les anciennes clés."""
    extra_categories = {
        "dossiers": "Dossiers",
        "automod": "AutoMod",
        "spam": "Protection spam",
        "raid": "Protection raid",
    }
    log_categories.CATEGORIES.update(extra_categories)
    log_categories.CATEGORY_ORDER = tuple(log_categories.CATEGORIES)

    # ``protection`` reste accepté pour les anciens modules, mais disparaît du Setup :
    # les trois destinations explicites ci-dessous le remplacent.
    if "protection" in log_service.LOG_TYPES:
        log_service.LOG_TYPES["protection"]["emits"] = False

    log_service.LOG_TYPES.update(
        {
            "dossiers": {
                "label": "Dossiers",
                "category": "Dossiers",
                "legacy_column": None,
                "emits": True,
            },
            "automod": {
                "label": "AutoMod",
                "category": "AutoMod",
                "legacy_column": "log_automod",
                "emits": True,
            },
            "spam": {
                "label": "Protection spam",
                "category": "Protection spam",
                "legacy_column": None,
                "emits": True,
            },
            "raid": {
                "label": "Protection raid",
                "category": "Protection raid",
                "legacy_column": None,
                "emits": True,
            },
        }
    )
    log_service.CATEGORY_ORDER = [
        log_categories.CATEGORIES[key]
        for key in log_categories.CATEGORY_ORDER
        if key in log_categories.CATEGORIES
    ]

    # Les invitations appartiennent aux dossiers. Les protections sont réparties par
    # fonction, au lieu de finir toutes dans un seul salon AutoMod.
    registry = log_categories.LOG_REGISTRY
    registry["invite_create"] = ("dossiers", "🔗", "success")
    registry["invite_delete"] = ("dossiers", "🔗", "error")
    registry["automod_spam"] = ("spam", "🚫", "error")
    registry["antiraid"] = ("raid", "🛡️", "error")
    registry["automod_link"] = ("automod", "🔗", "error")
    registry["automod_word"] = ("automod", "🛑", "error")


def _patch_no_log_fallback() -> None:
    current = log_service.get_log_setting
    if getattr(current, "_sentrix_v3_no_fallback", False):
        return

    @functools.wraps(current)
    async def get_log_setting_no_fallback(bot, guild_id: int, log_type: str) -> dict:
        setting = dict(await current(bot, guild_id, log_type))
        dedicated = setting.get("dedicated_channel_id")
        # Un ID supprimé reste visible comme "introuvable" dans le Setup, mais aucune
        # autre catégorie ne détourne silencieusement ses événements vers logs-serveur.
        setting["channel_id"] = dedicated
        setting["fallback_channel_id"] = None
        return setting

    get_log_setting_no_fallback._sentrix_v3_no_fallback = True
    get_log_setting_no_fallback._sentrix_previous = current
    log_service.get_log_setting = get_log_setting_no_fallback


def _security_log_type(embed: discord.Embed) -> str:
    text = f"{embed.title or ''} {embed.description or ''}".casefold()
    if "raid" in text or "nuke" in text:
        return "raid"
    if "spam" in text or "flood" in text:
        return "spam"
    return "automod"


def _server_log_type(embed: discord.Embed) -> str:
    text = f"{embed.title or ''} {embed.description or ''}".casefold()
    if "invitation" in text or "invite" in text:
        return "dossiers"
    if "rôle" in text or "role" in text:
        # Une attribution/retrait de rôle concerne le membre. La création/modification
        # de l'objet rôle reste dans logs-rôles.
        if any(word in text for word in ("ajouté", "ajoute", "retiré", "retire", "attribué", "attribue")):
            return "members"
        return "roles"
    if "salon" in text or "channel" in text or "catégorie" in text or "categorie" in text:
        return "channels"
    return "server"


def _message_mentions_warning(embed: discord.Embed) -> None:
    title = (embed.title or "").casefold()
    if "message supprim" not in title:
        return
    if any((field.name or "").casefold().startswith("attention") for field in embed.fields):
        return
    content = ""
    for field in embed.fields:
        if (field.name or "").casefold() == "contenu":
            content = str(field.value or "")
            break
    if not content:
        return
    users = len(USER_MENTION_RE.findall(content))
    roles = len(ROLE_MENTION_RE.findall(content))
    everyone = content.count("@everyone") + content.count("@here")
    lines = []
    if users:
        lines.append(f"- {users} mention(s) utilisateur")
    if roles:
        lines.append(f"- {roles} mention(s) rôle")
    if everyone:
        lines.append(f"- {everyone} mention(s) @everyone/@here")
    if lines:
        embed.add_field(name="⚠️ ATTENTION !", value="\n".join(lines)[:1024], inline=False)


def _field_map(embed: discord.Embed) -> dict[str, str]:
    return {
        str(field.name or "").strip().casefold(): str(field.value or "").strip()
        for field in embed.fields
    }


def _first_user_id(value: str) -> int | None:
    match = USER_MENTION_RE.search(value or "")
    return int(match.group(1)) if match else None


def _first_channel_id(value: str) -> int | None:
    match = CHANNEL_MENTION_RE.search(value or "")
    return int(match.group(1)) if match else None


def _duration_text(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, total = divmod(total, 3600)
    minutes, secs = divmod(total, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}min")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


async def _polish_voice_log(self, guild: discord.Guild, embed: discord.Embed) -> None:
    fields = _field_map(embed)
    member_id = _first_user_id(fields.get("membre", "") or (embed.description or ""))
    if member_id is None:
        return

    before = fields.get("avant", "")
    after = fields.get("après", "") or fields.get("apres", "")
    before_id = _first_channel_id(before)
    after_id = _first_channel_id(after)
    key = (guild.id, member_id)
    now_mono = time.monotonic()

    if before_id is None and after_id is not None:
        _VOICE_JOINED_AT[key] = (after_id, now_mono)
        embed.title = "Salon vocal rejoint"
        return

    if before_id is not None and after_id is None:
        embed.title = "Salon vocal quitté"
        joined = _VOICE_JOINED_AT.pop(key, None)
        if joined is not None:
            embed.add_field(
                name="Durée",
                value=_duration_text(now_mono - joined[1]),
                inline=True,
            )
        return

    if before_id is not None and after_id is not None and before_id != after_id:
        embed.title = "Membre déplacé"
        _VOICE_JOINED_AT[key] = (after_id, now_mono)
        action = getattr(discord.AuditLogAction, "member_move", None)
        if action is not None and hasattr(self, "_audit_actor"):
            try:
                actor, _entry = await self._audit_actor(guild, action, member_id, max_age_seconds=8)
            except Exception:
                actor = None
            if actor is not None and not any(
                (field.name or "").casefold() in {"modérateur", "moderateur"}
                for field in embed.fields
            ):
                embed.add_field(name="Modérateur", value=f"<@{actor.id}>", inline=True)
        return

    embed.title = "Statut du salon vocal modifié"


def _install_log_transport(bot: commands.Bot) -> None:
    """Réaffirme le routage après V83, qui remplace encore ``Logs._send``."""
    _install_log_catalog()
    _patch_no_log_fallback()

    current_global = log_service.send_log
    if not getattr(current_global, "_sentrix_v3_router", False):

        @functools.wraps(current_global)
        async def routed_global(
            bot_obj,
            guild: discord.Guild,
            log_type: str,
            embed: discord.Embed,
            file: discord.File | None = None,
            **kwargs,
        ) -> bool:
            routed = log_type
            if log_type in {"protection", "automod"}:
                routed = _security_log_type(embed)
            elif log_type == "server":
                routed = _server_log_type(embed)
            return await current_global(
                bot_obj,
                guild,
                routed,
                embed,
                file,
                **kwargs,
            )

        routed_global._sentrix_v3_router = True
        routed_global._sentrix_previous = current_global
        log_service.send_log = routed_global

    try:
        from cogs import logs as logs_cog
    except Exception:
        logger.exception("V3: impossible d'importer cogs.logs")
        return

    current_send = getattr(logs_cog.Logs, "_send", None)
    if getattr(current_send, "_sentrix_v3_router", False):
        return

    async def final_send(
        self,
        guild: discord.Guild,
        config_key: str,
        embed: discord.Embed,
        *,
        view: discord.ui.View | None = None,
        event_key: str | None = None,
    ) -> bool:
        mapping = {
            "log_messages": "messages",
            "log_members": "members",
            "log_voice": "voice",
            "log_roles": "roles",
            "log_moderation": "moderation",
            "ticket_log_channel": "tickets",
        }
        if config_key == "log_server":
            log_type = _server_log_type(embed)
        elif config_key == "log_automod":
            log_type = _security_log_type(embed)
        else:
            log_type = mapping.get(config_key, "server")

        # Attribution/retrait d'un rôle à un membre => logs-membre.
        if log_type == "roles":
            text = f"{embed.title or ''} {embed.description or ''}".casefold()
            if any(word in text for word in ("rôle ajouté", "role ajoute", "rôle retiré", "role retire")):
                log_type = "members"

        _message_mentions_warning(embed)
        if log_type == "voice":
            await _polish_voice_log(self, guild, embed)

        return await log_service.send_log(
            self.bot,
            guild,
            log_type,
            embed,
            view=view,
            event_key=event_key,
        )

    final_send._sentrix_v3_router = True
    final_send._sentrix_previous = current_send
    logs_cog.Logs._send = final_send
    logger.info("V3: routage final des logs réaffirmé après V83.")


async def _ensure_standard_log_channels(
    bot: commands.Bot,
    guild: discord.Guild,
) -> dict[str, discord.TextChannel]:
    category = _find_category(guild)
    overwrites = _log_overwrites(guild)
    reason = "SentriX V3 : configuration idempotente des journaux"

    if category is None:
        category = await guild.create_category(
            "💾・Logs",
            overwrites=overwrites,
            reason=reason,
        )
    else:
        try:
            merged = dict(category.overwrites)
            merged.update(overwrites)
            if merged != category.overwrites:
                await category.edit(overwrites=merged, reason=reason)
        except discord.HTTPException:
            logger.debug("V3: permissions de la catégorie logs non modifiées", exc_info=True)

    result: dict[str, discord.TextChannel] = {}
    for log_type, (canonical_name, aliases) in LOG_CHANNEL_SPECS.items():
        channel = _find_text_channel(guild, (canonical_name, *aliases))
        if channel is None:
            channel = await guild.create_text_channel(
                canonical_name,
                category=category,
                topic=f"Journaux SentriX — {log_type}.",
                overwrites=overwrites,
                reason=reason,
            )
            await asyncio.sleep(0.08)
        else:
            try:
                # On ne force pas le renommage d'un salon existant du serveur ; on répare
                # uniquement sa catégorie si nécessaire.
                if channel.category_id != category.id:
                    await channel.edit(category=category, reason=reason)
            except discord.HTTPException:
                logger.debug("V3: déplacement de %s impossible", channel.id, exc_info=True)

        await log_service.set_log_channel(bot, guild.id, log_type, channel.id)
        await log_service.set_log_enabled(bot, guild.id, log_type, True)
        result[log_type] = channel

    return result


async def _find_or_create_role(
    guild: discord.Guild,
    name: str,
    *,
    aliases: tuple[str, ...] = (),
) -> discord.Role:
    wanted = {_plain_name(item) for item in (name, *aliases)}
    for role in guild.roles:
        if _plain_name(role.name) in wanted:
            return role
    return await guild.create_role(
        name=name,
        permissions=discord.Permissions.none(),
        colour=discord.Colour.default(),
        hoist=False,
        mentionable=False,
        reason="SentriX V3 : passerelle de sécurité",
    )


async def _ensure_honeypot_resources(
    bot: commands.Bot,
    guild: discord.Guild,
) -> dict[str, int]:
    from cogs import security_verification_v71 as security_v71

    await security_v71.ensure_schema(bot)
    row = await bot.db.fetchone(
        "SELECT * FROM honeypot_verification WHERE guild_id = ?",
        (guild.id,),
    )

    def row_value(key: str) -> int | None:
        if row is None:
            return None
        try:
            value = row[key]
        except (KeyError, IndexError, TypeError):
            return None
        return int(value) if value else None

    unverified = guild.get_role(row_value("unverified_role_id") or 0)
    if unverified is None:
        unverified = await _find_or_create_role(
            guild,
            "Non vérifié",
            aliases=("Non verifie", "Non-vérifié", "Unverified"),
        )

    verified = guild.get_role(row_value("verified_role_id") or 0)
    if verified is None:
        verified = await _find_or_create_role(
            guild,
            "Vérifié",
            aliases=("Verifie", "Membre vérifié", "Verified"),
        )

    category = guild.get_channel(row_value("category_id") or 0)
    if not isinstance(category, discord.CategoryChannel):
        category = next(
            (
                item for item in guild.categories
                if _plain_name(item.name) in {
                    _plain_name("🛡️・Sécurité SentriX"),
                    _plain_name("SentriX Sécurité"),
                    _plain_name("Sécurité"),
                }
            ),
            None,
        )

    bot_overwrite = _bot_channel_overwrite(guild)
    category_overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        unverified: discord.PermissionOverwrite(view_channel=True),
        verified: discord.PermissionOverwrite(view_channel=False),
    }
    if guild.me is not None:
        category_overwrites[guild.me] = bot_overwrite

    if category is None:
        category = await guild.create_category(
            "🛡️・Sécurité SentriX",
            overwrites=category_overwrites,
            reason="SentriX V3 : honeypot automatique",
        )
    else:
        try:
            merged = dict(category.overwrites)
            merged.update(category_overwrites)
            await category.edit(overwrites=merged, reason="SentriX V3 : honeypot automatique")
        except discord.HTTPException:
            logger.debug("V3: permissions catégorie sécurité non modifiées", exc_info=True)

    verify = guild.get_channel(row_value("verify_channel_id") or 0)
    if not isinstance(verify, discord.TextChannel):
        verify = _find_text_channel(
            guild,
            ("✅・verification", "verification", "vérification", "verify"),
        )
    verify_overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
        ),
        unverified: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
        ),
        verified: discord.PermissionOverwrite(view_channel=False),
    }
    if guild.me is not None:
        verify_overwrites[guild.me] = bot_overwrite

    if verify is None:
        verify = await guild.create_text_channel(
            "✅・verification",
            category=category,
            topic="Passerelle de vérification SentriX.",
            overwrites=verify_overwrites,
            reason="SentriX V3 : vérification automatique",
        )
    else:
        try:
            await verify.edit(
                category=category,
                overwrites=verify_overwrites,
                reason="SentriX V3 : vérification automatique",
            )
        except discord.HTTPException:
            logger.debug("V3: salon vérification non modifié", exc_info=True)

    trap = guild.get_channel(row_value("trap_channel_id") or 0)
    if not isinstance(trap, discord.TextChannel):
        trap = _find_text_channel(
            guild,
            ("🚨・stay-muted", "stay-muted", "honeypot", "salon-piège", "salon-piege"),
        )
    trap_overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        unverified: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
        verified: discord.PermissionOverwrite(view_channel=False),
    }
    if guild.me is not None:
        trap_overwrites[guild.me] = bot_overwrite

    if trap is None:
        trap = await guild.create_text_channel(
            "🚨・stay-muted",
            category=category,
            topic="Honeypot SentriX — ne pas écrire dans ce salon.",
            overwrites=trap_overwrites,
            reason="SentriX V3 : honeypot automatique",
        )
    else:
        try:
            await trap.edit(
                category=category,
                overwrites=trap_overwrites,
                reason="SentriX V3 : honeypot automatique",
            )
        except discord.HTTPException:
            logger.debug("V3: salon honeypot non modifié", exc_info=True)

    await bot.db.execute(
        "INSERT INTO honeypot_verification("
        "guild_id,enabled,category_id,trap_channel_id,verify_channel_id,"
        "unverified_role_id,verified_role_id,created_at"
        ") VALUES(?,?,?,?,?,?,?,strftime('%s','now')) "
        "ON CONFLICT(guild_id) DO UPDATE SET "
        "category_id=excluded.category_id,"
        "trap_channel_id=excluded.trap_channel_id,"
        "verify_channel_id=excluded.verify_channel_id,"
        "unverified_role_id=excluded.unverified_role_id,"
        "verified_role_id=excluded.verified_role_id",
        (
            guild.id,
            1,
            category.id,
            trap.id,
            verify.id,
            unverified.id,
            verified.id,
        ),
    )

    # Les modules historiques qui lisent guild_config retrouvent eux aussi le rôle.
    for field in ("verify_role", "verification_role"):
        try:
            await bot.db.set_guild_config(guild.id, field, verified.id)
        except Exception:
            logger.debug("V3: miroir %s indisponible", field, exc_info=True)

    runtime = getattr(bot, "_sentrix_security_v71_runtime", None)
    if runtime is not None:
        try:
            await runtime.refresh_gateway_panels(guild)
        except Exception:
            logger.exception("V3: panneaux honeypot impossibles à rafraîchir")

    return {
        "category_id": category.id,
        "trap_channel_id": trap.id,
        "verify_channel_id": verify.id,
        "unverified_role_id": unverified.id,
        "verified_role_id": verified.id,
    }


async def _enable_security_stack(
    bot: commands.Bot,
    guild: discord.Guild,
    actor_id: int,
) -> dict[str, int]:
    from cogs import security_verification_v71 as security_v71
    from cogs import setup_control_center as setup_ui
    from cogs import setup_v2_core as core

    await bot.db.execute(
        "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
        (guild.id,),
    )
    columns = ", ".join(f"{field} = ?" for field, _label in setup_ui.AUTOMOD)
    await bot.db.execute(
        f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
        (*tuple(1 for _ in setup_ui.AUTOMOD), guild.id),
    )

    await security_v71.ensure_schema(bot)
    await security_v71.update_setting(bot, guild.id, "honeypot_enabled", 1, actor_id)
    await security_v71.update_setting(bot, guild.id, "verification_enabled", 1, actor_id)
    await security_v71.update_setting(bot, guild.id, "raid_intensity", "normal", actor_id)
    await core.set_module_enabled(
        bot,
        guild.id,
        "security",
        True,
        actor_id=actor_id,
    )
    security_v71._invalidate_automod(bot, guild.id)
    return await _ensure_honeypot_resources(bot, guild)


def _patch_security_setup() -> None:
    try:
        from cogs import setup_security_choice_v75 as v75
    except Exception:
        logger.exception("V3: Setup sécurité V75 indisponible")
        return

    current = v75._save_protections
    if getattr(current, "_sentrix_v3_honeypot_create", False):
        return

    @functools.wraps(current)
    async def save_with_resources(view, chosen: set[str], *, actor_id: int) -> None:
        await current(view, chosen, actor_id=actor_id)
        if {"honeypot", "verification"} & set(chosen):
            try:
                await _ensure_honeypot_resources(view.bot, view.guild)
            except discord.Forbidden:
                logger.exception("V3: Discord refuse la création automatique du honeypot")
                raise
            except Exception:
                logger.exception("V3: création automatique du honeypot échouée")
                raise

    save_with_resources._sentrix_v3_honeypot_create = True
    save_with_resources._sentrix_previous = current
    v75._save_protections = save_with_resources


async def _audit_actor_for(
    guild: discord.Guild,
    action: discord.AuditLogAction | None,
    *,
    target_id: int | None = None,
    invite_code: str | None = None,
) -> discord.abc.User | None:
    if action is None or guild.me is None or not guild.me.guild_permissions.view_audit_log:
        return None
    now = discord.utils.utcnow()
    try:
        async for entry in guild.audit_logs(limit=8, action=action):
            if abs((now - entry.created_at).total_seconds()) > 10:
                continue
            target = entry.target
            if target_id is not None and getattr(target, "id", None) != target_id:
                continue
            if invite_code is not None and getattr(target, "code", None) not in {None, invite_code}:
                continue
            return entry.user
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


def _invite_expiry(invite: discord.Invite) -> str:
    if invite.expires_at is not None:
        return discord.utils.format_dt(invite.expires_at, "R")
    max_age = int(getattr(invite, "max_age", 0) or 0)
    if max_age <= 0:
        return "Jamais"
    return f"dans {_duration_text(max_age)}"


def _invite_url(invite: discord.Invite) -> str:
    return f"https://discord.gg/{invite.code}"


def _strict_emoji_kind(data: bytes) -> str | None:
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def _patch_addemoji_direct_copy(bot: commands.Bot) -> None:
    """Évite le chemin CDN qui pouvait ramener une image fixe pour un `<a:...>`."""
    try:
        from cogs import emoji_name_lookup as lookup
    except Exception:
        logger.exception("V3: emoji_name_lookup indisponible")
        return

    current = lookup._copy_custom_emoji_direct
    if getattr(current, "_sentrix_v3_keep_animation", False):
        return

    async def strict_copy(cog_self, ctx: commands.Context, markup: str):
        match = CUSTOM_EMOJI_RE.fullmatch((markup or "").strip())
        if match is None:
            return None
        if ctx.guild is None:
            return await ctx.send(embed=await cog_self._embed(
                None,
                title="Commande indisponible",
                description="Cette commande doit être utilisée sur un serveur.",
                kind="danger",
            ))

        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_emojis_and_stickers:
            return await ctx.send(embed=await cog_self._embed(
                ctx.guild.id,
                title="Permission manquante",
                description="Le bot doit avoir la permission **Gérer les emojis et stickers**.",
                kind="danger",
            ))

        animated = bool(match.group(1))
        emoji_name = lookup._discord_name(match.group(2), fallback="emoji")
        emoji_id = match.group(3)

        existing = discord.utils.find(
            lambda item: item.name.casefold() == emoji_name.casefold(),
            ctx.guild.emojis,
        )
        if existing is not None:
            return await ctx.send(embed=await cog_self._embed(
                ctx.guild.id,
                title="Emoji déjà présent",
                description=f"{existing} existe déjà sous le nom `:{existing.name}:`.",
                kind="warning",
            ))

        used = sum(1 for item in ctx.guild.emojis if bool(item.animated) == animated)
        if used >= ctx.guild.emoji_limit:
            kind_label = "animés" if animated else "statiques"
            return await ctx.send(embed=await cog_self._embed(
                ctx.guild.id,
                title="Limite atteinte",
                description=f"Le serveur n'a plus de place pour les emojis {kind_label}.",
                kind="danger",
            ))

        extension = "gif" if animated else "png"
        # Le fichier brut est prioritaire. Les URLs avec paramètres passent ensuite.
        candidates = [
            f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}",
            f"https://media.discordapp.net/emojis/{emoji_id}.{extension}",
            f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}?quality=lossless",
            f"https://media.discordapp.net/emojis/{emoji_id}.{extension}?quality=lossless",
        ]
        accept = "image/gif,*/*;q=0.5" if animated else "image/png,image/webp,image/*;q=0.8"
        data: bytes | None = None
        last_status: int | None = None

        timeout = aiohttp.ClientTimeout(total=12, connect=5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for candidate in candidates:
                    try:
                        async with session.get(
                            candidate,
                            headers={
                                "User-Agent": "SentriX-EmojiImporter/3.0",
                                "Accept": accept,
                            },
                            allow_redirects=True,
                        ) as response:
                            last_status = response.status
                            if response.status != 200:
                                continue
                            payload = await response.content.read(1024 * 1024 + 1)
                    except (aiohttp.ClientError, asyncio.TimeoutError):
                        continue
                    if not payload or len(payload) > 1024 * 1024:
                        continue
                    detected = _strict_emoji_kind(payload)
                    if animated and detected != "gif":
                        # Surtout ne pas créer l'emoji : ce serait exactement le bug
                        # "emoji animé ajouté en statique".
                        continue
                    if not animated and detected not in {"png", "jpeg", "webp"}:
                        continue
                    data = payload
                    break
        except (aiohttp.ClientError, asyncio.TimeoutError):
            data = None

        if data is None:
            detail = f" (HTTP {last_status})" if last_status else ""
            expected = "GIF animé" if animated else "image statique"
            return await ctx.send(embed=await cog_self._embed(
                ctx.guild.id,
                title="Emoji inaccessible",
                description=(
                    f"SentriX n'a pas pu récupérer le vrai {expected} depuis Discord{detail}. "
                    "Aucun emoji statique de remplacement n'a été créé."
                ),
                kind="danger",
            ))

        try:
            created = await ctx.guild.create_custom_emoji(
                name=emoji_name,
                image=data,
                reason=f"Emoji copié par {ctx.author} avec +addemoji",
            )
        except discord.Forbidden:
            return await ctx.send(embed=await cog_self._embed(
                ctx.guild.id,
                title="Création refusée",
                description="Vérifiez la permission **Gérer les emojis et stickers** du bot.",
                kind="danger",
            ))
        except discord.HTTPException as exc:
            return await ctx.send(embed=await cog_self._embed(
                ctx.guild.id,
                title="Création impossible",
                description=f"Discord a refusé cet emoji (`{exc.code}`).",
                kind="danger",
            ))

        if bool(created.animated) != animated:
            # Garde-fou final : ne jamais laisser un mauvais emoji créé par erreur.
            try:
                await created.delete(reason="SentriX V3 : type animé/statique incorrect")
            except discord.HTTPException:
                pass
            return await ctx.send(embed=await cog_self._embed(
                ctx.guild.id,
                title="Type d'emoji incorrect",
                description=(
                    "Discord n'a pas conservé le type de l'emoji. "
                    "L'emoji incorrect a été retiré au lieu de rester en statique."
                ),
                kind="danger",
            ))

        return await ctx.send(embed=await cog_self._embed(
            ctx.guild.id,
            title="Emoji ajouté",
            description=(
                f"{created} a été copié sous le nom `:{created.name}:`.\n"
                f"Type vérifié : **{'animé' if created.animated else 'statique'}**."
            ),
            kind="success",
        ))

    strict_copy._sentrix_v3_keep_animation = True
    strict_copy._sentrix_previous = current
    lookup._copy_custom_emoji_direct = strict_copy
    logger.info("V3: +addemoji conserve strictement GIF animé / image statique.")


async def _can_create(ctx: commands.Context) -> bool:
    if not isinstance(ctx.author, discord.Member) or ctx.guild is None:
        return False
    if ctx.author.guild_permissions.administrator:
        return True
    try:
        return bool(await checks.is_verified_bot_owner(ctx))
    except Exception:
        return False


async def _verify_installation(
    bot: commands.Bot,
    guild: discord.Guild,
) -> list[str]:
    problems: list[str] = []
    for log_type in LOG_CHANNEL_SPECS:
        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
        except Exception:
            problems.append(f"{log_type}: configuration illisible")
            continue
        channel_id = setting.get("channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            problems.append(f"{log_type}: salon manquant")
            continue
        valid, reason = log_service.validate_channel(
            guild,
            channel.id,
            needs_file=(log_type == "tickets"),
        )
        if not valid:
            problems.append(f"{log_type}: {reason}")

    try:
        row = await bot.db.fetchone(
            "SELECT category_id,trap_channel_id,verify_channel_id,unverified_role_id,verified_role_id "
            "FROM honeypot_verification WHERE guild_id = ?",
            (guild.id,),
        )
        if row is None:
            problems.append("sécurité: configuration honeypot absente")
        else:
            for key in ("category_id", "trap_channel_id", "verify_channel_id"):
                value = row[key]
                if not value or guild.get_channel(int(value)) is None:
                    problems.append(f"sécurité: {key} introuvable")
            for key in ("unverified_role_id", "verified_role_id"):
                value = row[key]
                if not value or guild.get_role(int(value)) is None:
                    problems.append(f"sécurité: {key} introuvable")
    except Exception:
        problems.append("sécurité: vérification DB impossible")

    return problems


async def _run_manox_builder(
    bot: commands.Bot,
    ctx: commands.Context,
    requested_name: str,
) -> None:
    guild = ctx.guild
    assert guild is not None

    if not await _can_create(ctx):
        await ctx.send("Cette commande est réservée aux administrateurs du serveur.")
        return

    me = guild.me
    if me is None or not me.guild_permissions.administrator:
        await ctx.send(
            "Donne temporairement la permission **Administrateur** à SentriX puis relance "
            f"`+create {requested_name}`."
        )
        return

    builder = bot.get_cog("ServerBuilder")
    if builder is None or not hasattr(builder, "build_server"):
        await ctx.send("Le constructeur de serveur SentriX n'est pas chargé.")
        return

    lock = _CREATE_LOCKS.setdefault(guild.id, asyncio.Lock())
    if lock.locked():
        await ctx.send("Une création/réparation est déjà en cours sur ce serveur.")
        return

    async with lock:
        progress = await ctx.send(
            f"Création/réparation **{requested_name}** en cours… "
            "rôles, permissions, salons, tickets, logs et sécurité."
        )
        stage = "structure du serveur"
        try:
            result = await builder.build_server(guild, "communaute", ctx.author)
            if (result.title or "").casefold() != "configuration terminée":
                await progress.edit(content=None, embed=result)
                return

            stage = "routage complet des logs"
            channels = await _ensure_standard_log_channels(bot, guild)

            stage = "sécurité et honeypot"
            security = await _enable_security_stack(bot, guild, ctx.author.id)

            stage = "vérification finale"
            problems = await _verify_installation(bot, guild)

            result.add_field(
                name="Logs configurés",
                value=(
                    f"{len(channels)}/{len(LOG_CHANNEL_SPECS)} catégories reliées à un salon dédié. "
                    "Aucun fallback forcé vers logs-serveur."
                ),
                inline=False,
            )
            result.add_field(
                name="Sécurité",
                value=(
                    f"Honeypot <#{security['trap_channel_id']}> et vérification "
                    f"<#{security['verify_channel_id']}> créés/réparés automatiquement."
                ),
                inline=False,
            )
            result.add_field(
                name="Vérification finale",
                value=(
                    "Tout est prêt."
                    if not problems
                    else "À vérifier : " + " • ".join(problems[:8])
                )[:1024],
                inline=False,
            )
            result.set_footer(
                text=(
                    f"SentriX V3 • +create {requested_name} est relançable : "
                    "les ressources existantes sont réutilisées."
                )
            )
            await progress.edit(content=None, embed=result)
        except discord.Forbidden:
            logger.exception("V3: +create %s interdit guild=%s étape=%s", requested_name, guild.id, stage)
            await progress.edit(
                content=(
                    f"Création arrêtée pendant **{stage}** : Discord a refusé une permission. "
                    f"Corrige le rôle de SentriX puis relance `+create {requested_name}` ; "
                    "les éléments déjà créés seront réutilisés."
                )
            )
        except Exception as exc:
            logger.exception("V3: +create %s erreur guild=%s étape=%s", requested_name, guild.id, stage)
            detail = str(exc).replace("\n", " ")[:180]
            await progress.edit(
                content=(
                    f"Erreur pendant **{stage}**. La création reste relançable et ne repart pas de zéro. "
                    f"Relance `+create {requested_name}` après correction. "
                    f"`{type(exc).__name__}: {detail}`"
                )
            )


def _patch_create_command(bot: commands.Bot) -> None:
    command = bot.get_command("create")
    if command is None:
        logger.warning("V3: commande +create introuvable")
        return
    current = command.callback
    if getattr(current, "_sentrix_create_v3", False):
        return

    params = command.params.copy()

    @functools.wraps(current)
    async def create_v3(cog_self, ctx: commands.Context, *, template: str = ""):
        requested = (template or "").strip()
        if requested.casefold() == "sentrix":
            return await current(cog_self, ctx, template=template)
        if not requested:
            return await ctx.send(
                "Utilise `+create sentrix` pour le serveur officiel, "
                "ou `+create <nom>` (ex. `+create manox`) pour installer/réparer "
                "le modèle communauté complet."
            )
        return await _run_manox_builder(bot, ctx, requested[:100])

    create_v3._sentrix_create_v3 = True
    create_v3._sentrix_previous = current
    command.callback = create_v3
    command.params = params
    command.help = (
        "Crée ou répare une configuration complète et relançable. "
        "Exemples : +create sentrix, +create manox."
    )
    logger.info("V3: +create accepte désormais les modèles nommés comme +create manox.")


class CreateSentriXV3(commands.Cog, name="CreateSentriXV3"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._runtime_ready = False

    async def cog_load(self) -> None:
        _install_log_catalog()
        _patch_no_log_fallback()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # V83 et les couches finales sont déjà installées quand READY arrive. On applique
        # donc ici la dernière autorité, puis on vérifie à chaque reconnexion qu'aucune
        # ancienne couche n'a repris la main.
        _install_log_transport(self.bot)
        _patch_security_setup()
        _patch_addemoji_direct_copy(self.bot)
        _patch_create_command(self.bot)
        self._runtime_ready = True

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        guild = invite.guild
        if guild is None:
            return
        actor = await _audit_actor_for(
            guild,
            getattr(discord.AuditLogAction, "invite_create", None),
            invite_code=invite.code,
        )
        fields: list[tuple[str, str, bool]] = [
            ("Salon", invite.channel.mention if invite.channel else "Inconnu", True),
            ("Lien", _invite_url(invite), False),
            ("Expire", _invite_expiry(invite), True),
            (
                "Utilisations max",
                "Illimité" if not getattr(invite, "max_uses", 0) else str(invite.max_uses),
                True,
            ),
        ]
        if actor is not None:
            fields.insert(0, ("Créateur", f"<@{actor.id}>", True))
        panel = embeds.log_embed("Invitation créée", fields=fields)
        view = log_service.log_actions(
            ids=[("Copier l'ID créateur", actor.id)] if actor is not None else None
        )
        await log_service.send_log(
            self.bot,
            guild,
            "dossiers",
            panel,
            view=view,
            event_key=f"invite-create:{guild.id}:{invite.code}",
        )

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        guild = invite.guild
        if guild is None:
            return
        actor = await _audit_actor_for(
            guild,
            getattr(discord.AuditLogAction, "invite_delete", None),
            invite_code=invite.code,
        )
        fields: list[tuple[str, str, bool]] = [
            ("Salon", invite.channel.mention if invite.channel else "Inconnu", True),
            ("Code", f"`{invite.code}`", True),
        ]
        if actor is not None:
            fields.insert(0, ("Responsable", f"<@{actor.id}>", True))
        panel = embeds.log_embed("Invitation supprimée", fields=fields)
        await log_service.send_log(
            self.bot,
            guild,
            "dossiers",
            panel,
            event_key=f"invite-delete:{guild.id}:{invite.code}",
        )

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        # Discord inclut "pinned" uniquement lors d'un changement de l'état épinglé.
        if payload.guild_id is None or "pinned" not in payload.data:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        pinned = bool(payload.data.get("pinned"))
        channel = guild.get_channel(payload.channel_id)
        author_id = None
        author_data = payload.data.get("author")
        if isinstance(author_data, dict):
            try:
                author_id = int(author_data.get("id") or 0) or None
            except (TypeError, ValueError):
                author_id = None
        fields = [
            ("Salon", f"<#{payload.channel_id}>", True),
            ("ID du message", f"`{payload.message_id}`", True),
        ]
        if author_id:
            fields.insert(0, ("Auteur", f"<@{author_id}>", True))
        panel = embeds.log_embed(
            "Message épinglé" if pinned else "Message désépinglé",
            fields=fields,
        )
        view = log_service.log_actions(
            jump_url=(
                f"https://discord.com/channels/{guild.id}/{payload.channel_id}/{payload.message_id}"
                if channel is not None
                else None
            ),
            ids=[("Copier l'ID du message", payload.message_id)],
        )
        await log_service.send_log(
            self.bot,
            guild,
            "messages",
            panel,
            view=view,
            event_key=f"message-pin:{guild.id}:{payload.message_id}:{int(pinned)}",
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        # Le logger officiel couvre nom/couleur/permissions mais ignorait les déplacements.
        if before.position == after.position:
            return
        actor = await _audit_actor_for(
            after.guild,
            getattr(discord.AuditLogAction, "role_update", None),
            target_id=after.id,
        )
        fields = [
            ("Rôle", after.mention, True),
            ("Position modifiée", f"`{before.position}` → `{after.position}`", False),
        ]
        if actor is not None:
            fields.append(("Modérateur", f"<@{actor.id}>", True))
        panel = embeds.log_embed("Rôle modifié", fields=fields)
        ids = [("Copier l'ID du rôle", after.id)]
        if actor is not None:
            ids.append(("Copier l'ID du modérateur", actor.id))
        await log_service.send_log(
            self.bot,
            after.guild,
            "roles",
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=f"role-position:{after.guild.id}:{after.id}:{after.position}",
        )


async def setup(bot: commands.Bot) -> None:
    if bot.get_cog("CreateSentriXV3") is not None:
        return
    await bot.add_cog(CreateSentriXV3(bot))
    _install_log_catalog()
    _patch_no_log_fallback()
    logger.info("%s chargé.", RUNTIME_MARKER)
