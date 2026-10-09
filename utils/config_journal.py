"""Le journal des réglages : chaque changement de guild_config, d'où qu'il vienne.

Toutes les écritures — /setup, dashboard, commandes — aboutissent à
``Database.set_guild_config`` : c'est là qu'il est tenu, avec la valeur d'avant,
la valeur d'après, l'auteur et le canal (posés par ``sentrix_trace.ACTOR``).
``/config history`` le relit, et chaque ligne peut être annulée — sauf si le
réglage a changé depuis : on n'écrase jamais un changement plus récent.
"""
from __future__ import annotations

import time
from typing import Any

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS config_journal ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, field TEXT NOT NULL, "
    "old_value TEXT, new_value TEXT, actor_id INTEGER, source TEXT, created_at INTEGER NOT NULL, "
    "undone_by INTEGER)"
)
UNDO_PREFIX = "sx:undo:"

SOURCES = {
    "prefix": "commande +", "slash": "commande /", "bouton": "bouton", "menu": "/setup",
    "formulaire": "formulaire", "dashboard": "dashboard", "annulation": "annulation",
}
SOURCES_EN = {
    "prefix": "+ command", "slash": "/ command", "bouton": "button", "menu": "/setup",
    "formulaire": "form", "dashboard": "dashboard", "annulation": "undo",
}

#: Libellés lisibles : un nom de colonne ne dit rien à un administrateur.
LABELS = {
    "prefix": "Préfixe des commandes", "mod_role": "Rôle staff", "admin_role": "Rôle administrateur",
    "mute_role": "Rôle mute", "warn_role": "Rôle d'avertissement", "member_role": "Rôle membre",
    "verify_role": "Rôle vérifié", "verification_role": "Rôle vérifié", "booster_role": "Rôle booster",
    "autorole": "Rôle d'arrivée", "log_channel": "Salon des logs", "welcome_channel": "Salon de bienvenue",
    "goodbye_channel": "Salon de départ", "welcome_message": "Message de bienvenue",
    "goodbye_message": "Message de départ", "ticket_log_channel": "Salon des logs de tickets",
    "ticket_category": "Catégorie des tickets", "level_channel": "Salon des niveaux",
    "rules_channel": "Salon du règlement", "verification_channel": "Salon de vérification",
    "suggest_channel": "Salon des suggestions", "announce_channel": "Salon des annonces",
    "giveaway_channel": "Salon des giveaways", "warn_ban_threshold": "Seuil de bannissement",
    "welcome_image_url": "Fond de bienvenue", "goodbye_image_url": "Fond de départ",
    "language": "Langue", "security_level": "Niveau de sécurité",
    "log_server": "Logs — serveur", "log_messages": "Logs — messages", "log_members": "Logs — membres",
    "log_voice": "Logs — vocal", "log_roles": "Logs — rôles", "log_moderation": "Logs — modération",
    "log_automod": "Logs — AutoMod",
}


def label(field: str) -> str:
    return LABELS.get(field, field.replace("_", " ").capitalize())


def _stored(value: Any) -> str | None:
    return None if value is None else str(value)


def restore_value(stored: str | None) -> Any:
    """Une valeur journalisée redevient ce que guild_config attend (entier si c'en était un)."""
    if stored is None:
        return None
    text = str(stored)
    return int(text) if text.lstrip("-").isdigit() else text


def render(guild: Any, field: str, stored: str | None) -> str:
    """Une valeur lisible : un salon se montre comme un salon, un texte comme un extrait."""
    if stored in (None, "", "0"):
        return "Aucun"
    text = str(stored)
    if text.isdigit() and len(text) >= 15:
        # Ce que l'identifiant EST sur le serveur, plutôt qu'une supposition sur le nom du champ.
        if getattr(guild, "get_channel", None) and guild.get_channel(int(text)) is not None:
            return f"<#{text}>"
        if getattr(guild, "get_role", None) and guild.get_role(int(text)) is not None:
            return f"<@&{text}>"
        if field.endswith(("_channel", "_category")) or field.startswith("log_"):
            return f"Salon supprimé (`{text}`)"
        if field.endswith("_role") or field == "autorole":
            return f"Rôle supprimé (`{text}`)"
    if len(text) > 60:
        text = text[:57].rstrip() + "…"
    return f"`{text}`"


async def ensure_schema(db: Any) -> None:
    await db.execute(SCHEMA)


async def record(db: Any, guild_id: int, field: str, old: Any, new: Any, *, now: int | None = None) -> int | None:
    """Journalise un changement réel (rien si la valeur ne change pas). Rend l'identifiant."""
    if _stored(old) == _stored(new):
        return None
    from utils import sentrix_trace

    actor = sentrix_trace.ACTOR.get()
    await ensure_schema(db)
    cursor = await db.execute(
        "INSERT INTO config_journal (guild_id, field, old_value, new_value, actor_id, source, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (int(guild_id), field, _stored(old), _stored(new), actor[0] if actor else None,
         actor[1] if actor else None, int(now or time.time())),
    )
    return getattr(cursor, "lastrowid", None)


async def recent(db: Any, guild_id: int, limit: int = 10) -> list[Any]:
    await ensure_schema(db)
    return await db.fetchall(
        "SELECT * FROM config_journal WHERE guild_id = ? ORDER BY id DESC LIMIT ?", (int(guild_id), int(limit)),
    )


async def get(db: Any, guild_id: int, entry_id: int) -> Any:
    await ensure_schema(db)
    return await db.fetchone(
        "SELECT * FROM config_journal WHERE guild_id = ? AND id = ?", (int(guild_id), int(entry_id)),
    )


async def undo(db: Any, guild_id: int, entry_id: int) -> tuple[bool, str, Any]:
    """Remet la valeur d'avant. (fait, motif de refus, ligne) — jamais d'écrasement silencieux."""
    entry = await get(db, guild_id, entry_id)
    if entry is None:
        return False, "missing", None
    if entry["undone_by"]:
        return False, "already", entry
    conf = await db.get_guild_config(int(guild_id))
    try:
        current = conf[entry["field"]] if conf is not None else None
    except (KeyError, IndexError):
        current = None
    if _stored(current) != entry["new_value"]:
        return False, "changed", entry
    from utils import sentrix_trace

    actor_id = (sentrix_trace.ACTOR.get() or (None, ""))[0]
    token = sentrix_trace.ACTOR.set((actor_id, "annulation"))
    try:
        await db.set_guild_config(int(guild_id), entry["field"], restore_value(entry["old_value"]))
    finally:
        sentrix_trace.ACTOR.reset(token)
    latest = await db.fetchone(
        "SELECT id FROM config_journal WHERE guild_id = ? ORDER BY id DESC LIMIT 1", (int(guild_id),),
    )
    await db.execute(
        "UPDATE config_journal SET undone_by = ? WHERE id = ?", (latest["id"] if latest else -1, int(entry_id)),
    )
    return True, "", entry


def undo_buttons(entries: list[Any], *, english: bool = False) -> list[Any]:
    """Un bouton « Annuler n°… » par changement encore annulable (5 au plus)."""
    import discord

    from utils import sentrix_panels as panels

    return [
        panels.Bouton(
            f"Undo #{entry['id']}" if english else f"Annuler n°{entry['id']}",
            custom_id=f"{UNDO_PREFIX}{int(entry['id'])}",
            style=discord.ButtonStyle.secondary,
        )
        for entry in [e for e in entries if not e["undone_by"]][:5]
    ]
