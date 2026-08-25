"""Transport officiel et unique des journaux Discord SentriX.

Ce module centralise la configuration, la migration historique, la déduplication,
le rendu et l'envoi des logs. Une migration de secours est exécutée une seule fois par
serveur pour réparer le cas où les anciens salons existent mais ``log_settings`` est
resté entièrement désactivé après une ancienne version.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict

import discord

logger = logging.getLogger("bot")

LOG_TYPES = {
    "messages": {"label": "Messages (suppression/modification)", "category": "Messages", "legacy_column": "log_messages", "emits": True},
    "members": {"label": "Membres (arrivées/départs/pseudo/rôles)", "category": "Membres", "legacy_column": "log_members", "emits": True},
    "roles": {"label": "Rôles (création/suppression/attribution)", "category": "Rôles", "legacy_column": "log_roles", "emits": True},
    "server": {"label": "Salons et serveur", "category": "Salons", "legacy_column": "log_server", "emits": True},
    "voice": {"label": "Vocal (connexion/déconnexion/changement)", "category": "Vocal", "legacy_column": "log_voice", "emits": True},
    "moderation": {"label": "Modération (warns, mutes, kicks, bans)", "category": "Modération", "legacy_column": "log_moderation", "emits": True},
    "tickets": {"label": "Tickets (ouverture, claim, fermeture)", "category": "Tickets", "legacy_column": "ticket_log_channel", "emits": True},
    "automod": {"label": "Sécurité (AutoMod / anti-raid / anti-nuke)", "category": "Sécurité", "legacy_column": "log_automod", "emits": True},
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

LOG_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=False,
    users=False,
    roles=False,
    replied_user=False,
)

_DEDUP_TTL = 8.0
_DEDUP_MAX = 4096
_recent_event_keys: OrderedDict[str, float] = OrderedDict()
_bootstrap_locks: dict[int, asyncio.Lock] = {}

_BOOTSTRAP_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_log_migration_state (
    guild_id INTEGER PRIMARY KEY,
    legacy_bootstrap_done INTEGER NOT NULL DEFAULT 0,
    repaired_at INTEGER
)
"""


def is_primary_process() -> bool:
    """Les logs ne doivent jamais être coupés par une variable d'hébergement obsolète.

    Les anciennes versions utilisaient un UUID Railway ou ``SENTRIX_LOG_PRODUCER`` et
    pouvaient donc désactiver tous les journaux après un redéploiement. La déduplication
    est maintenant gérée dans le logger lui-même ; le processus actif peut toujours
    produire ses logs.
    """
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
    return ":".join(
        str(part)
        for part in (
            guild_id,
            event_type,
            target_id or 0,
            executor_id or 0,
            audit_log_id or 0,
            message_id or 0,
            discriminator or "",
        )
    )


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
    elif "kick" in sample or "expuls" in sample:
        action = "kick"
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
        await interaction.response.send_message(
            f"`{self.entity_id}`",
            ephemeral=True,
            allowed_mentions=LOG_ALLOWED_MENTIONS,
        )


class LogActionsView(discord.ui.View):
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


def log_actions(*, jump_url: str | None = None, ids: list[tuple[str, int]] | None = None) -> LogActionsView | None:
    return LogActionsView(jump_url=jump_url, ids=ids) if jump_url or ids else None


async def _legacy_channel_id(bot, guild_id: int, log_type: str) -> int | None:
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


async def _ensure_bootstrap_table(bot) -> None:
    await bot.db.execute(_BOOTSTRAP_SCHEMA)


async def _ensure_legacy_bootstrap(bot, guild_id: int) -> None:
    """Répare une seule fois la migration ancienne -> nouvelle configuration.

    Le bug historique était le suivant : ``/create-logs`` enregistrait les salons dans
    ``guild_config`` alors qu'une ligne ``log_settings`` déjà créée pouvait rester à
    ``enabled=0``. Si aucun type de log actif n'existe encore, on considère que cette
    configuration est une migration cassée et on reprend les vrais salons historiques.
    Une ligne d'état empêche ensuite toute réactivation automatique future : les choix
    manuels de l'administrateur redeviennent totalement prioritaires.
    """
    await _ensure_bootstrap_table(bot)
    marker = await bot.db.fetchone(
        "SELECT legacy_bootstrap_done FROM sentrix_log_migration_state WHERE guild_id = ?",
        (guild_id,),
    )
    if marker and marker["legacy_bootstrap_done"]:
        return

    lock = _bootstrap_locks.setdefault(guild_id, asyncio.Lock())
    async with lock:
        marker = await bot.db.fetchone(
            "SELECT legacy_bootstrap_done FROM sentrix_log_migration_state WHERE guild_id = ?",
            (guild_id,),
        )
        if marker and marker["legacy_bootstrap_done"]:
            return

        rows = await bot.db.fetchall(
            "SELECT log_type, enabled, channel_id FROM log_settings WHERE guild_id = ?",
            (guild_id,),
        )
        enabled_any = any(bool(row["enabled"]) for row in rows)
        repaired = 0

        if not enabled_any:
            for log_type, meta in LOG_TYPES.items():
                if not meta.get("emits"):
                    continue
                legacy_channel = await _legacy_channel_id(bot, guild_id, log_type)
                if not legacy_channel:
                    continue
                now_ts = _now()
                await bot.db.execute(
                    "INSERT INTO log_settings "
                    "(guild_id, log_type, enabled, channel_id, created_at, updated_at) "
                    "VALUES (?, ?, 1, ?, ?, ?) "
                    "ON CONFLICT(guild_id, log_type) DO UPDATE SET "
                    "enabled = 1, channel_id = excluded.channel_id, updated_at = excluded.updated_at",
                    (guild_id, log_type, legacy_channel, now_ts, now_ts),
                )
                repaired += 1

        await bot.db.execute(
            "INSERT INTO sentrix_log_migration_state (guild_id, legacy_bootstrap_done, repaired_at) "
            "VALUES (?, 1, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET legacy_bootstrap_done = 1, repaired_at = excluded.repaired_at",
            (guild_id, _now()),
        )
        if repaired:
            logger.warning(
                "Réparation automatique des logs guild=%s : %s catégorie(s) réactivée(s) depuis guild_config.",
                guild_id,
                repaired,
            )


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
    if log_type not in LOG_TYPES:
        raise KeyError(log_type)
    await _ensure_legacy_bootstrap(bot, guild_id)
    row = await bot.db.fetchone(
        "SELECT * FROM log_settings WHERE guild_id = ? AND log_type = ?",
        (guild_id, log_type),
    )
    if row is None:
        return await _migrate_from_legacy(bot, guild_id, log_type)
    return {
        "enabled": bool(row["enabled"]),
        "channel_id": int(row["channel_id"]) if row["channel_id"] else None,
        "include_content": bool(row["include_content"]),
        "include_attachments": bool(row["include_attachments"]),
        "include_actor": bool(row["include_actor"]),
        "include_reason": bool(row["include_reason"]),
    }


async def get_all_log_settings(bot, guild_id: int) -> dict[str, dict]:
    await _ensure_legacy_bootstrap(bot, guild_id)
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
    current["enabled"] = bool(enabled)
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
    channel = guild.get_channel(int(channel_id))
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
    from utils import embeds as embeds_mod

    rendered = (
        embed
        if getattr(getattr(embed, "image", None), "url", None) == embeds_mod.SENTRIX_BANNER_URL
        else embeds_mod.normalize_log(embed)
    )

    semantic_key = semantic_event_key(guild.id, log_type, rendered)
    if _is_duplicate(event_key) or _is_duplicate(semantic_key):
        logger.debug("Log dupliqué ignoré guild=%s type=%s", guild.id, log_type)
        return False

    try:
        setting = await get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.exception("Impossible de lire/réparer la configuration du log %s sur %s.", log_type, guild.id)
        return False

    if not setting["enabled"]:
        logger.info("Log désactivé guild=%s type=%s", guild.id, log_type)
        return False

    ok, reason = validate_channel(guild, setting["channel_id"], needs_file=file is not None)
    if not ok:
        logger.warning("Log %s non envoyé sur guild=%s : %s", log_type, guild.id, reason)
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
        logger.info("Log envoyé guild=%s type=%s channel=%s", guild.id, log_type, channel.id)
        return True
    except (discord.Forbidden, discord.HTTPException):
        logger.exception("Échec d'envoi du log %s dans %s.", log_type, setting["channel_id"])
        return False


async def send_test_log(bot, guild: discord.Guild, log_type: str, author: discord.abc.User) -> tuple[bool, str]:
    setting = await get_log_setting(bot, guild.id, log_type)
    if not setting["enabled"]:
        return False, "Ce type de log est désactivé. Activez-le avant le test."
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
        await channel.send(embed=test_embed, allowed_mentions=LOG_ALLOWED_MENTIONS)
        return True, f"Test envoyé dans {channel.mention}."
    except discord.HTTPException as exc:
        return False, f"Échec de l'envoi du test : {exc}."
