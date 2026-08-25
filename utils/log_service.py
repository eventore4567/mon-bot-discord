"""Transport officiel et unique des journaux Discord SentriX.

Ce module est la seule sortie logique pour les journaux centralisés :
- renderer SentriX unique ;
- mentions Discord natives sans notification ;
- déduplication ciblée ;
- compatibilité avec les anciens salons de logs ;
- aucune dépendance à un ID Railway codé en dur.
"""
from __future__ import annotations

import logging
import os
import re
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
    "moderation": {"label": "Modération (warns, mutes, kicks, bans)", "category": "Modération", "legacy_column": "log_moderation", "emits": True},
    "tickets": {"label": "Tickets (ouverture, claim, fermeture)", "category": "Tickets", "legacy_column": "ticket_log_channel", "emits": True},
    "automod": {"label": "Sécurité (anti-spam, anti-raid, anti-nuke, AutoMod)", "category": "Sécurité", "legacy_column": "log_automod", "emits": True},
    "economy": {"label": "Économie", "category": "Économie", "legacy_column": None, "emits": False},
    "levels": {"label": "Niveaux", "category": "Niveaux", "legacy_column": None, "emits": False},
    "ai": {"label": "Intelligence artificielle", "category": "IA", "legacy_column": None, "emits": False},
    "games": {"label": "Jeux", "category": "Jeux", "legacy_column": None, "emits": False},
    "system": {"label": "Système", "category": "Système", "legacy_column": None, "emits": False},
}

CATEGORY_ORDER = [
    "Messages", "Membres", "Rôles", "Salons", "Vocal", "Modération", "Tickets",
    "Sécurité", "Économie", "Niveaux", "IA", "Jeux", "Système",
]

DEFAULT_LOG_SETTING = {
    "enabled": False,
    "channel_id": None,
    "include_content": True,
    "include_attachments": True,
    "include_actor": True,
    "include_reason": True,
}

# Équivalent discord.py de :
# allowedMentions: { parse: [], users: [], roles: [], repliedUser: false }
# Les chaînes <@id>, <@&id> et <#id> restent rendues nativement par Discord,
# mais aucun membre/rôle n'est notifié à cause d'un log.
LOG_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=False,
    users=False,
    roles=False,
    replied_user=False,
)

_DEDUP_TTL = 8.0
_DEDUP_MAX = 4096
_recent_event_keys: OrderedDict[str, float] = OrderedDict()


def is_primary_process() -> bool:
    """Autorise les logs par défaut.

    L'ancien code comparait RAILWAY_SERVICE_ID à un UUID codé en dur. Dès qu'un service
    Railway était recréé/renommé, TOUS les logs étaient silencieusement bloqués.

    Désormais un service secondaire n'est désactivé que si l'administrateur le demande
    explicitement avec SENTRIX_LOG_PRODUCER=0/false/no/off. Sans cette variable, le bot
    fonctionne normalement en local comme sur Railway.
    """
    raw = (os.getenv("SENTRIX_LOG_PRODUCER") or "").strip().casefold()
    if raw in {"0", "false", "no", "off", "disabled"}:
        return False
    return True


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
    parts = [
        guild_id,
        event_type,
        target_id or 0,
        executor_id or 0,
        audit_log_id or 0,
        message_id or 0,
        discriminator or "",
    ]
    return ":".join(str(part) for part in parts)


def _prune_recent(now: float) -> None:
    while _recent_event_keys:
        first_key, first_at = next(iter(_recent_event_keys.items()))
        if now - first_at <= _DEDUP_TTL and len(_recent_event_keys) <= _DEDUP_MAX:
            break
        _recent_event_keys.pop(first_key, None)


def _is_duplicate(event_key: str | None) -> bool:
    if not event_key:
        return False
    current = time.monotonic()
    _prune_recent(current)
    previous = _recent_event_keys.get(event_key)
    if previous is not None and current - previous <= _DEDUP_TTL:
        return True
    _recent_event_keys[event_key] = current
    _recent_event_keys.move_to_end(event_key)
    return False


def _first_snowflake(text: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", text or "")
    return int(match.group(1)) if match else None


def semantic_event_key(guild_id: int, log_type: str, embed: discord.Embed) -> str | None:
    """Filet de sécurité pour les sanctions qui peuvent arriver par commande + event Discord.

    On ne l'applique volontairement pas aux warns, kicks ou tickets : deux vraies actions
    rapprochées doivent toujours produire deux logs distincts.
    """
    if log_type != "moderation":
        return None
    sample = " ".join(
        [str(embed.title or ""), str(embed.description or "")]
        + [f"{field.name} {field.value}" for field in embed.fields]
    ).casefold()
    if "unban" in sample or "débann" in sample or "debann" in sample:
        action = "unban"
    elif "ban" in sample or "bann" in sample:
        action = "ban"
    elif "timeout" in sample or "mute" in sample:
        action = "timeout"
    else:
        return None
    target = _first_snowflake(sample)
    if target is None:
        return None
    return f"semantic:{guild_id}:{action}:{target}"


class RevealIdButton(discord.ui.Button):
    def __init__(self, label: str, entity_id: int, *, row: int = 0):
        self.entity_id = int(entity_id)
        super().__init__(
            label=label[:80],
            style=discord.ButtonStyle.secondary,
            custom_id=f"sxid:{self.entity_id}",
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # discord.py 2.6.x ne fournit pas un bouton standard de copie presse-papiers.
        # On affiche donc uniquement l'ID, en éphémère, sans polluer le salon de logs.
        await interaction.response.send_message(
            f"`{self.entity_id}`",
            ephemeral=True,
            allowed_mentions=LOG_ALLOWED_MENTIONS,
        )


class LogActionsView(discord.ui.View):
    """Actions de consultation affichées sous l'embed."""

    def __init__(self, *, jump_url: str | None = None, ids: list[tuple[str, int]] | None = None):
        super().__init__(timeout=None)
        if jump_url:
            self.add_item(
                discord.ui.Button(
                    label="Voir le message",
                    style=discord.ButtonStyle.link,
                    url=jump_url,
                    row=0,
                )
            )
        for label, entity_id in (ids or [])[:4]:
            self.add_item(RevealIdButton(label, entity_id, row=0))


def log_actions(
    *,
    jump_url: str | None = None,
    ids: list[tuple[str, int]] | None = None,
) -> LogActionsView | None:
    return LogActionsView(jump_url=jump_url, ids=ids) if jump_url or ids else None


async def _legacy_channel_id(bot, guild_id: int, log_type: str) -> int | None:
    """Lit le salon historique sans modifier la nouvelle configuration."""
    meta = LOG_TYPES.get(log_type, {})
    legacy_column = meta.get("legacy_column")
    if not legacy_column:
        return None
    conf = await bot.db.get_guild_config(guild_id)
    if not conf:
        return None
    try:
        channel_id = conf[legacy_column]
    except (KeyError, IndexError, TypeError):
        channel_id = None
    if not channel_id and legacy_column != "ticket_log_channel":
        try:
            channel_id = conf["log_channel"]
        except (KeyError, IndexError, TypeError):
            channel_id = None
    return int(channel_id) if channel_id else None


async def _migrate_from_legacy(bot, guild_id: int, log_type: str) -> dict:
    channel_id = await _legacy_channel_id(bot, guild_id, log_type)
    enabled = 1 if channel_id else 0
    now_ts = _now()
    await bot.db.execute(
        "INSERT INTO log_settings "
        "(guild_id, log_type, enabled, channel_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(guild_id, log_type) DO NOTHING",
        (guild_id, log_type, enabled, channel_id, now_ts, now_ts),
    )
    return {
        "enabled": bool(enabled),
        "channel_id": channel_id,
        "include_content": True,
        "include_attachments": True,
        "include_actor": True,
        "include_reason": True,
    }


async def get_log_setting(bot, guild_id: int, log_type: str) -> dict:
    """Retourne le réglage actif et répare les migrations historiques incomplètes.

    Cas corrigé : une ligne `log_settings` pouvait être créée AVANT `/create-logs`.
    Elle restait alors `enabled=0, channel_id=NULL` même après que l'ancien système ait
    créé et enregistré les salons. Si la ligne n'a jamais été explicitement modifiée
    (`created_at == updated_at`), on reprend automatiquement le salon historique.
    """
    row = await bot.db.fetchone(
        "SELECT * FROM log_settings WHERE guild_id = ? AND log_type = ?",
        (guild_id, log_type),
    )
    if row is None:
        return await _migrate_from_legacy(bot, guild_id, log_type)

    channel_id = row["channel_id"]
    enabled = bool(row["enabled"])
    created_at = row["created_at"]
    updated_at = row["updated_at"]

    untouched_migration = (
        not channel_id
        and not enabled
        and created_at is not None
        and updated_at is not None
        and int(created_at) == int(updated_at)
    )
    if untouched_migration:
        legacy_channel = await _legacy_channel_id(bot, guild_id, log_type)
        if legacy_channel:
            now_ts = _now()
            await bot.db.execute(
                "UPDATE log_settings SET enabled = 1, channel_id = ?, updated_at = ? "
                "WHERE guild_id = ? AND log_type = ?",
                (legacy_channel, now_ts, guild_id, log_type),
            )
            channel_id = legacy_channel
            enabled = True
            logger.info(
                "Réparation automatique du log %s sur guild=%s depuis la configuration historique.",
                log_type,
                guild_id,
            )

    return {
        "enabled": enabled,
        "channel_id": channel_id,
        "include_content": bool(row["include_content"]),
        "include_attachments": bool(row["include_attachments"]),
        "include_actor": bool(row["include_actor"]),
        "include_reason": bool(row["include_reason"]),
    }


async def get_all_log_settings(bot, guild_id: int) -> dict[str, dict]:
    return {
        log_type: await get_log_setting(bot, guild_id, log_type)
        for log_type in LOG_TYPES
    }


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


def validate_channel(
    guild: discord.Guild,
    channel_id: int | None,
    *,
    needs_file: bool = False,
):
    if not channel_id:
        return False, "aucun salon configuré"
    channel = guild.get_channel(channel_id)
    if channel is None:
        return False, "salon introuvable"
    me = guild.me
    if me is None:
        return False, "membre bot introuvable dans le cache du serveur"
    perms = channel.permissions_for(me)
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
    """Seul point de sortie central : renderer unique, zéro ping et déduplication."""
    if not is_primary_process():
        logger.info(
            "Log volontairement désactivé par SENTRIX_LOG_PRODUCER guild=%s type=%s",
            guild.id,
            log_type,
        )
        return False

    from utils import embeds as embeds_mod

    rendered = (
        embed
        if getattr(getattr(embed, "image", None), "url", None) == embeds_mod.SENTRIX_BANNER_URL
        else embeds_mod.normalize_log(embed)
    )

    semantic_key = semantic_event_key(guild.id, log_type, rendered)
    if _is_duplicate(event_key) or _is_duplicate(semantic_key):
        logger.debug(
            "Log dupliqué ignoré guild=%s type=%s key=%s",
            guild.id,
            log_type,
            event_key or semantic_key,
        )
        return False

    try:
        setting = await get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.warning(
            "Impossible de lire la configuration du log %s sur %s.",
            log_type,
            guild.id,
            exc_info=True,
        )
        return False

    if not setting["enabled"]:
        logger.debug("Log désactivé guild=%s type=%s", guild.id, log_type)
        return False

    ok, reason = validate_channel(
        guild,
        setting["channel_id"],
        needs_file=file is not None,
    )
    if not ok:
        logger.warning(
            "Log %s non envoyé sur %s : %s",
            log_type,
            guild.id,
            reason,
        )
        return False

    channel = guild.get_channel(setting["channel_id"])
    kwargs = {
        "embed": rendered,
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
        logger.warning(
            "Échec d'envoi du log %s dans %s.",
            log_type,
            setting["channel_id"],
            exc_info=True,
        )
        return False


async def send_test_log(
    bot,
    guild: discord.Guild,
    log_type: str,
    author: discord.abc.User,
) -> tuple[bool, str]:
    setting = await get_log_setting(bot, guild.id, log_type)
    ok, reason = validate_channel(guild, setting["channel_id"])
    if not ok:
        return False, f"Impossible d'envoyer un test : {reason}."

    from utils import embeds as embeds_mod

    test_embed = embeds_mod.log_embed(
        "Test de log",
        fields=(
            ("Catégorie", LOG_TYPES.get(log_type, {}).get("label", log_type), False),
            ("Déclenché par", f"<@{author.id}>", True),
        ),
    )
    channel = guild.get_channel(setting["channel_id"])
    try:
        await channel.send(
            embed=test_embed,
            allowed_mentions=LOG_ALLOWED_MENTIONS,
        )
        return True, f"Test envoyé dans {channel.mention}."
    except discord.HTTPException as exc:
        return False, f"Échec de l'envoi du test : {exc}."
