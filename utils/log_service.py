"""Service officiel et unique d'envoi des logs SentriX.

Ce module conserve la configuration historique des catégories de logs, mais possède
maintenant aussi les règles de transport obligatoires des journaux : aucune mention
utilisateur/rôle/everyone ne peut notifier, les boutons d'ID répondent en éphémère et
la déduplication ne s'applique qu'aux événements portant une clé explicite.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

import discord

logger = logging.getLogger("bot")

LOG_TYPES = {
    "messages": {"label": "Messages (suppression/modification)", "category": "Messages", "legacy_column": "log_messages", "emits": True},
    "members": {"label": "Membres (arrivées/départs/pseudo/rôles)", "category": "Membres", "legacy_column": "log_members", "emits": True},
    "roles": {"label": "Rôles (création/suppression/attribution)", "category": "Rôles", "legacy_column": "log_roles", "emits": True},
    "server": {"label": "Salons (création/suppression/modification)", "category": "Salons", "legacy_column": "log_server", "emits": True},
    "voice": {"label": "Vocal (connexion/déconnexion/changement de salon)", "category": "Vocal", "legacy_column": "log_voice", "emits": True},
    "moderation": {"label": "Modération (avertissements, mutes, kicks, bans)", "category": "Modération", "legacy_column": "log_moderation", "emits": True},
    "tickets": {"label": "Tickets (ouverture, fermeture, transcript)", "category": "Tickets", "legacy_column": "ticket_log_channel", "emits": True},
    "automod": {"label": "Sécurité (anti-spam, anti-raid, anti-nuke, AutoMod)", "category": "Sécurité", "legacy_column": "log_automod", "emits": True},
    "economy": {"label": "Économie (gains, transferts, achats)", "category": "Économie", "legacy_column": None, "emits": False},
    "levels": {"label": "Niveaux", "category": "Niveaux", "legacy_column": None, "emits": False},
    "ai": {"label": "Intelligence artificielle", "category": "IA", "legacy_column": None, "emits": False},
    "games": {"label": "Jeux", "category": "Jeux", "legacy_column": None, "emits": False},
    "system": {"label": "Système", "category": "Système", "legacy_column": None, "emits": False},
}

CATEGORY_ORDER = ["Messages", "Membres", "Rôles", "Salons", "Vocal", "Modération", "Tickets", "Sécurité", "Économie", "Niveaux", "IA", "Jeux", "Système"]
DEFAULT_LOG_SETTING = {
    "enabled": False,
    "channel_id": None,
    "include_content": True,
    "include_attachments": True,
    "include_actor": True,
    "include_reason": True,
}

# Equivalent discord.py de allowedMentions {parse: [], users: [], roles: [], repliedUser: false}.
LOG_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=False,
    users=False,
    roles=False,
    replied_user=False,
)

_DEDUP_TTL = 6.0
_DEDUP_MAX = 4096
_recent_event_keys: OrderedDict[str, float] = OrderedDict()


def categories_with_types() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {category: [] for category in CATEGORY_ORDER}
    for log_type, meta in LOG_TYPES.items():
        result.setdefault(meta["category"], []).append(log_type)
    return {category: types for category, types in result.items() if types}


def _now() -> int:
    return int(time.time())


def make_event_key(
    guild_id: int,
    event_type: str,
    *,
    target_id: int | None = None,
    executor_id: int | None = None,
    audit_log_id: int | None = None,
    message_id: int | None = None,
    discriminator: str | int | None = None,
) -> str:
    """Clé déterministe. Deux vraies actions proches restent distinctes via leur ID/audit/message."""
    parts = [guild_id, event_type, target_id or 0, executor_id or 0, audit_log_id or 0, message_id or 0, discriminator or ""]
    return ":".join(str(part) for part in parts)


def _is_duplicate(event_key: str | None) -> bool:
    if not event_key:
        return False
    now = time.monotonic()
    while _recent_event_keys:
        first_key, first_at = next(iter(_recent_event_keys.items()))
        if now - first_at <= _DEDUP_TTL and len(_recent_event_keys) <= _DEDUP_MAX:
            break
        _recent_event_keys.pop(first_key, None)
    previous = _recent_event_keys.get(event_key)
    if previous is not None and now - previous <= _DEDUP_TTL:
        return True
    _recent_event_keys[event_key] = now
    _recent_event_keys.move_to_end(event_key)
    return False


class RevealIdButton(discord.ui.Button):
    def __init__(self, label: str, entity_id: int, *, row: int = 0):
        self.entity_id = int(entity_id)
        # Le custom_id reste court et ne contient aucune donnée administrative dangereuse.
        super().__init__(label=label[:80], style=discord.ButtonStyle.secondary, custom_id=f"sxid:{self.entity_id}", row=row)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"`{self.entity_id}`", ephemeral=True, allowed_mentions=LOG_ALLOWED_MENTIONS)


class LogActionsView(discord.ui.View):
    """Actions de consultation uniquement, toujours rendues sous le log par Discord."""

    def __init__(self, *, jump_url: str | None = None, ids: list[tuple[str, int]] | None = None):
        super().__init__(timeout=None)
        if jump_url:
            self.add_item(discord.ui.Button(label="Voir le message", style=discord.ButtonStyle.link, url=jump_url, row=0))
        for label, entity_id in (ids or [])[:4]:
            self.add_item(RevealIdButton(label, entity_id, row=0))


def log_actions(*, jump_url: str | None = None, ids: list[tuple[str, int]] | None = None) -> LogActionsView | None:
    if not jump_url and not ids:
        return None
    return LogActionsView(jump_url=jump_url, ids=ids)


async def _migrate_from_legacy(bot, guild_id: int, log_type: str) -> dict:
    meta = LOG_TYPES.get(log_type, {})
    legacy_column = meta.get("legacy_column")
    channel_id = None
    if legacy_column:
        conf = await bot.db.get_guild_config(guild_id)
        if conf:
            try:
                channel_id = conf[legacy_column]
            except (KeyError, IndexError, TypeError):
                channel_id = None
            if not channel_id and legacy_column != "ticket_log_channel":
                try:
                    channel_id = conf["log_channel"]
                except (KeyError, IndexError, TypeError):
                    channel_id = None
    enabled = 1 if channel_id else 0
    now_ts = _now()
    await bot.db.execute(
        "INSERT INTO log_settings (guild_id, log_type, enabled, channel_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, log_type) DO NOTHING",
        (guild_id, log_type, enabled, channel_id, now_ts, now_ts),
    )
    return {"enabled": bool(enabled), "channel_id": channel_id, "include_content": True, "include_attachments": True, "include_actor": True, "include_reason": True}


async def get_log_setting(bot, guild_id: int, log_type: str) -> dict:
    row = await bot.db.fetchone("SELECT * FROM log_settings WHERE guild_id = ? AND log_type = ?", (guild_id, log_type))
    if row is None:
        return await _migrate_from_legacy(bot, guild_id, log_type)
    return {
        "enabled": bool(row["enabled"]),
        "channel_id": row["channel_id"],
        "include_content": bool(row["include_content"]),
        "include_attachments": bool(row["include_attachments"]),
        "include_actor": bool(row["include_actor"]),
        "include_reason": bool(row["include_reason"]),
    }


async def get_all_log_settings(bot, guild_id: int) -> dict[str, dict]:
    return {log_type: await get_log_setting(bot, guild_id, log_type) for log_type in LOG_TYPES}


async def set_log_enabled(bot, guild_id: int, log_type: str, enabled: bool) -> dict:
    current = await get_log_setting(bot, guild_id, log_type)
    if enabled and not current["channel_id"]:
        raise ValueError("channel_required")
    await bot.db.execute(
        "UPDATE log_settings SET enabled = ?, updated_at = ? WHERE guild_id = ? AND log_type = ?",
        (1 if enabled else 0, _now(), guild_id, log_type),
    )
    current["enabled"] = enabled
    return current


async def set_log_channel(bot, guild_id: int, log_type: str, channel_id: int | None) -> dict:
    await get_log_setting(bot, guild_id, log_type)
    await bot.db.execute(
        "UPDATE log_settings SET channel_id = ?, updated_at = ? WHERE guild_id = ? AND log_type = ?",
        (channel_id, _now(), guild_id, log_type),
    )
    setting = await get_log_setting(bot, guild_id, log_type)
    setting["channel_id"] = channel_id
    return setting


def validate_channel(guild: discord.Guild, channel_id: int | None, *, needs_file: bool = False):
    if not channel_id:
        return False, "aucun salon configuré"
    channel = guild.get_channel(channel_id)
    if channel is None:
        return False, "salon introuvable"
    perms = channel.permissions_for(guild.me)
    if not perms.view_channel:
        return False, "le bot ne peut pas voir ce salon"
    if not perms.send_messages:
        return False, "le bot ne peut pas envoyer de messages dans ce salon"
    if not perms.embed_links:
        return False, "le bot ne peut pas intégrer d'embed dans ce salon"
    if needs_file and not perms.attach_files:
        return False, "le bot ne peut pas joindre de fichiers dans ce salon"
    return True, "ok"


async def send_log(
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    file: discord.File | None = None,
    *,
    view: discord.ui.View | None = None,
    event_key: str | None = None,
) -> bool:
    """SEUL point de sortie des logs. Les mentions restent visuelles mais ne notifient jamais."""
    if _is_duplicate(event_key):
        logger.debug("Log dupliqué ignoré: %s", event_key)
        return False
    try:
        setting = await get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.warning("Impossible de lire la configuration du log %s sur %s.", log_type, guild.id, exc_info=True)
        return False
    if not setting["enabled"]:
        return False
    ok, reason = validate_channel(guild, setting["channel_id"], needs_file=file is not None)
    if not ok:
        logger.warning("Log %s non envoyé sur %s: %s", log_type, guild.id, reason)
        return False
    channel = guild.get_channel(setting["channel_id"])
    kwargs = {
        "embed": embed,
        "allowed_mentions": LOG_ALLOWED_MENTIONS,
    }
    if view is not None:
        kwargs["view"] = view
    if file is not None:
        kwargs["file"] = file
    try:
        await channel.send(**kwargs)
        return True
    except (discord.Forbidden, discord.HTTPException):
        logger.warning("Échec d'envoi du log %s dans %s.", log_type, setting["channel_id"], exc_info=True)
        return False


async def send_test_log(bot, guild: discord.Guild, log_type: str, author: discord.abc.User) -> tuple[bool, str]:
    setting = await get_log_setting(bot, guild.id, log_type)
    ok, reason = validate_channel(guild, setting["channel_id"])
    if not ok:
        return False, f"Impossible d'envoyer un test : {reason}."
    from utils import embeds as embeds_mod
    meta = LOG_TYPES.get(log_type, {})
    test_embed = embeds_mod.log_embed(
        "Test de log",
        fields=(("Catégorie", meta.get("label", log_type), False), ("Déclenché par", f"<@{author.id}>", True)),
    )
    channel = guild.get_channel(setting["channel_id"])
    try:
        await channel.send(embed=test_embed, allowed_mentions=LOG_ALLOWED_MENTIONS)
        return True, f"Test envoyé dans {channel.mention}."
    except discord.HTTPException as exc:
        return False, f"Échec de l'envoi du test : {exc}."
