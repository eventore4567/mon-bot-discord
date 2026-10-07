"""Service Suggestions — logique pure, sans aucun type discord.py.

Le cog (cogs/suggestions.py) affiche et écoute ; ce module décide et stocke.
Toutes les fonctions prennent l'objet base de données de SentriX (`bot.db`),
donc elles se testent sur une base SQLite en mémoire, sans bot.

Choix de conception
-------------------
- **Les votes ne sont jamais des compteurs.** Une ligne par (suggestion, membre)
  avec une clé primaire : un membre ne peut pas voter deux fois, et les totaux
  sont DÉRIVÉS des lignes. Incrémenter un compteur aurait permis le double vote
  sur deux clics rapprochés.
- **La numérotation est par serveur** (#1, #2…) et attribuée dans la même
  instruction que l'insertion : deux suggestions simultanées ne peuvent pas
  recevoir le même numéro.
- **On étend la table existante** `suggestions` au lieu d'en créer une seconde.
  Les anciennes lignes gardent leur contenu ; leur statut « en_attente » devient
  « pending » et elles reçoivent un numéro, dans l'ordre de création.
- **Le salon vient de `suggestion_settings`.** L'ancienne colonne
  `guild_config.suggest_channel` y est recopiée une fois, puis n'est plus lue :
  une seule source pour la configuration.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: Statuts possibles, dans l'ordre où le staff les parcourt.
STATUSES: tuple[str, ...] = ("pending", "planned", "accepted", "implemented", "rejected")

#: Anciennes valeurs de la colonne `status`, écrites par la version précédente.
LEGACY_STATUSES: dict[str, str] = {
    "en_attente": "pending",
    "attente": "pending",
    "acceptee": "accepted",
    "acceptée": "accepted",
    "refusee": "rejected",
    "refusée": "rejected",
}

DEFAULT_COOLDOWN_SECONDS = 300
MAX_TITLE = 100
MAX_CONTENT = 1500
MAX_RESPONSE = 500


class SuggestionError(ValueError):
    """Refus métier, avec un code stable que l'interface traduit en message."""

    def __init__(self, code: str, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class Settings:
    guild_id: int
    channel_id: int | None
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    anonymous: bool = False
    threads: bool = False

    @property
    def configured(self) -> bool:
        return self.channel_id is not None


@dataclass(frozen=True)
class Suggestion:
    id: int
    guild_id: int
    number: int
    author_id: int
    title: str
    content: str
    status: str
    channel_id: int | None
    message_id: int | None
    thread_id: int | None
    staff_id: int | None
    staff_response: str | None
    anonymous: bool
    attachment_url: str | None
    created_at: int
    updated_at: int | None


# --------------------------------------------------------------------------
# Schéma et migration
# --------------------------------------------------------------------------

_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("number", "INTEGER"),
    ("title", "TEXT"),
    ("channel_id", "INTEGER"),
    ("thread_id", "INTEGER"),
    ("staff_id", "INTEGER"),
    ("staff_response", "TEXT"),
    ("anonymous", "INTEGER NOT NULL DEFAULT 0"),
    ("attachment_url", "TEXT"),
    ("updated_at", "INTEGER"),
)


async def ensure_schema(db: Any) -> None:
    """Crée ce qui manque et migre les données existantes. Idempotent."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            message_id INTEGER,
            content TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER
        )
        """
    )
    existing = {row[1] for row in await db.fetchall("PRAGMA table_info(suggestions)")}
    for name, kind in _NEW_COLUMNS:
        if name not in existing:
            await db.execute(f"ALTER TABLE suggestions ADD COLUMN {name} {kind}")

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS suggestion_votes (
            suggestion_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            vote INTEGER NOT NULL CHECK (vote IN (-1, 1)),
            created_at INTEGER NOT NULL,
            PRIMARY KEY (suggestion_id, user_id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS suggestion_settings (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER,
            cooldown_seconds INTEGER NOT NULL DEFAULT 300,
            anonymous INTEGER NOT NULL DEFAULT 0,
            threads INTEGER NOT NULL DEFAULT 0,
            updated_by INTEGER,
            updated_at INTEGER
        )
        """
    )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_suggestions_guild_number "
        "ON suggestions (guild_id, number) WHERE number IS NOT NULL"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_suggestions_message ON suggestions (message_id)"
    )

    # Anciennes valeurs de statut -> valeurs canoniques.
    for old, new in LEGACY_STATUSES.items():
        await db.execute("UPDATE suggestions SET status = ? WHERE status = ?", (new, old))
    await db.execute(
        "UPDATE suggestions SET status = 'pending' WHERE status IS NULL OR status = ''"
    )

    # Numéroter les anciennes suggestions, serveur par serveur, dans l'ordre.
    rows = await db.fetchall(
        "SELECT id, guild_id FROM suggestions WHERE number IS NULL ORDER BY guild_id, id"
    )
    for row in rows:
        await db.execute(
            "UPDATE suggestions SET number = "
            "(SELECT COALESCE(MAX(number), 0) + 1 FROM suggestions WHERE guild_id = ?) "
            "WHERE id = ?",
            (row[1], row[0]),
        )

    # L'ancien salon configuré devient la configuration du module, une seule fois.
    try:
        await db.execute(
            """
            INSERT INTO suggestion_settings (guild_id, channel_id, updated_at)
            SELECT guild_id, suggest_channel, strftime('%s', 'now')
            FROM guild_config
            WHERE suggest_channel IS NOT NULL
              AND guild_id NOT IN (SELECT guild_id FROM suggestion_settings)
            """
        )
    except Exception as exc:  # noqa: BLE001 — base sans guild_config (tests isolés)
        if "no such table" not in str(exc).lower():
            raise


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

async def get_settings(db: Any, guild_id: int) -> Settings:
    row = await db.fetchone(
        "SELECT channel_id, cooldown_seconds, anonymous, threads "
        "FROM suggestion_settings WHERE guild_id = ?",
        (int(guild_id),),
    )
    if row is None:
        return Settings(guild_id=int(guild_id), channel_id=None)
    return Settings(
        guild_id=int(guild_id),
        channel_id=int(row[0]) if row[0] else None,
        cooldown_seconds=max(0, int(row[1] if row[1] is not None else DEFAULT_COOLDOWN_SECONDS)),
        anonymous=bool(row[2]),
        threads=bool(row[3]),
    )


async def save_settings(
    db: Any,
    guild_id: int,
    *,
    actor_id: int | None,
    now: int,
    channel_id: int | None = None,
    cooldown_seconds: int | None = None,
    anonymous: bool | None = None,
    threads: bool | None = None,
) -> Settings:
    """Écrit uniquement les champs fournis ; les autres gardent leur valeur."""
    current = await get_settings(db, guild_id)
    if cooldown_seconds is not None and not 0 <= int(cooldown_seconds) <= 86_400:
        raise SuggestionError("invalid_cooldown")
    merged = Settings(
        guild_id=int(guild_id),
        channel_id=int(channel_id) if channel_id is not None else current.channel_id,
        cooldown_seconds=int(cooldown_seconds) if cooldown_seconds is not None else current.cooldown_seconds,
        anonymous=bool(anonymous) if anonymous is not None else current.anonymous,
        threads=bool(threads) if threads is not None else current.threads,
    )
    await db.execute(
        """
        INSERT INTO suggestion_settings
            (guild_id, channel_id, cooldown_seconds, anonymous, threads, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id = excluded.channel_id,
            cooldown_seconds = excluded.cooldown_seconds,
            anonymous = excluded.anonymous,
            threads = excluded.threads,
            updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (
            merged.guild_id, merged.channel_id, merged.cooldown_seconds,
            int(merged.anonymous), int(merged.threads), actor_id, int(now),
        ),
    )
    return merged


# --------------------------------------------------------------------------
# Suggestions
# --------------------------------------------------------------------------

_COLUMNS = (
    "id, guild_id, number, user_id, title, content, status, channel_id, message_id, "
    "thread_id, staff_id, staff_response, anonymous, attachment_url, created_at, updated_at"
)


def _row(row: Any) -> Suggestion | None:
    if row is None:
        return None
    return Suggestion(
        id=int(row[0]),
        guild_id=int(row[1]),
        number=int(row[2] or 0),
        author_id=int(row[3] or 0),
        title=str(row[4] or ""),
        content=str(row[5] or ""),
        status=LEGACY_STATUSES.get(str(row[6] or ""), str(row[6] or "pending")),
        channel_id=int(row[7]) if row[7] else None,
        message_id=int(row[8]) if row[8] else None,
        thread_id=int(row[9]) if row[9] else None,
        staff_id=int(row[10]) if row[10] else None,
        staff_response=str(row[11]) if row[11] else None,
        anonymous=bool(row[12]),
        attachment_url=str(row[13]) if row[13] else None,
        created_at=int(row[14] or 0),
        updated_at=int(row[15]) if row[15] else None,
    )


async def cooldown_remaining(db: Any, settings: Settings, author_id: int, now: int) -> int:
    """Secondes avant la prochaine suggestion autorisée (0 = maintenant).

    Calculé depuis la base, pas depuis la mémoire : un redémarrage ne remet pas
    le compteur à zéro.
    """
    if settings.cooldown_seconds <= 0:
        return 0
    row = await db.fetchone(
        "SELECT MAX(created_at) FROM suggestions WHERE guild_id = ? AND user_id = ?",
        (settings.guild_id, int(author_id)),
    )
    last = int(row[0]) if row and row[0] else None
    if last is None:
        return 0
    return max(0, last + settings.cooldown_seconds - int(now))


async def create(
    db: Any,
    settings: Settings,
    *,
    author_id: int,
    title: str,
    content: str,
    now: int,
    attachment_url: str | None = None,
) -> Suggestion:
    """Enregistre une suggestion. Le message Discord est rattaché ensuite."""
    if not settings.configured:
        raise SuggestionError("not_configured")
    title = " ".join(str(title or "").split())[:MAX_TITLE]
    content = str(content or "").strip()[:MAX_CONTENT]
    if not content:
        raise SuggestionError("empty")
    remaining = await cooldown_remaining(db, settings, author_id, now)
    if remaining:
        raise SuggestionError("cooldown", seconds=remaining)
    cursor = await db.execute(
        f"""
        INSERT INTO suggestions
            (guild_id, user_id, title, content, status, channel_id, anonymous,
             attachment_url, created_at, updated_at, number)
        SELECT ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?,
               COALESCE(MAX(number), 0) + 1
        FROM suggestions WHERE guild_id = ?
        """,
        (
            settings.guild_id, int(author_id), title, content, settings.channel_id,
            int(settings.anonymous), attachment_url, int(now), int(now), settings.guild_id,
        ),
    )
    created = await get(db, int(cursor.lastrowid))
    assert created is not None
    return created


async def attach_message(
    db: Any, suggestion_id: int, *, channel_id: int, message_id: int, thread_id: int | None = None
) -> None:
    await db.execute(
        "UPDATE suggestions SET channel_id = ?, message_id = ?, thread_id = ? WHERE id = ?",
        (int(channel_id), int(message_id), int(thread_id) if thread_id else None, int(suggestion_id)),
    )


async def discard(db: Any, suggestion_id: int) -> None:
    """Annule une suggestion dont le message n'a pas pu être publié."""
    await db.execute("DELETE FROM suggestion_votes WHERE suggestion_id = ?", (int(suggestion_id),))
    await db.execute("DELETE FROM suggestions WHERE id = ?", (int(suggestion_id),))


async def get(db: Any, suggestion_id: int) -> Suggestion | None:
    return _row(await db.fetchone(f"SELECT {_COLUMNS} FROM suggestions WHERE id = ?", (int(suggestion_id),)))


async def by_message(db: Any, message_id: int) -> Suggestion | None:
    return _row(await db.fetchone(
        f"SELECT {_COLUMNS} FROM suggestions WHERE message_id = ?", (int(message_id),)
    ))


async def by_number(db: Any, guild_id: int, number: int) -> Suggestion | None:
    return _row(await db.fetchone(
        f"SELECT {_COLUMNS} FROM suggestions WHERE guild_id = ? AND number = ?",
        (int(guild_id), int(number)),
    ))


# --------------------------------------------------------------------------
# Votes
# --------------------------------------------------------------------------

async def counts(db: Any, suggestion_id: int) -> tuple[int, int]:
    """(pour, contre), toujours dérivés des lignes de vote."""
    row = await db.fetchone(
        "SELECT COALESCE(SUM(vote = 1), 0), COALESCE(SUM(vote = -1), 0) "
        "FROM suggestion_votes WHERE suggestion_id = ?",
        (int(suggestion_id),),
    )
    return (int(row[0] or 0), int(row[1] or 0)) if row else (0, 0)


async def vote(db: Any, suggestion: Suggestion, user_id: int, value: int, now: int) -> int:
    """Enregistre un vote et rend le vote résultant du membre (1, -1 ou 0).

    Recliquer sur le même bouton retire le vote ; cliquer sur l'autre le
    bascule. On ne vote plus sur une suggestion close.
    """
    if value not in (1, -1):
        raise SuggestionError("invalid_vote")
    if suggestion.status in ("accepted", "implemented", "rejected"):
        raise SuggestionError("closed")
    row = await db.fetchone(
        "SELECT vote FROM suggestion_votes WHERE suggestion_id = ? AND user_id = ?",
        (suggestion.id, int(user_id)),
    )
    if row is not None and int(row[0]) == value:
        await db.execute(
            "DELETE FROM suggestion_votes WHERE suggestion_id = ? AND user_id = ?",
            (suggestion.id, int(user_id)),
        )
        return 0
    await db.execute(
        """
        INSERT INTO suggestion_votes (suggestion_id, user_id, vote, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(suggestion_id, user_id) DO UPDATE SET vote = excluded.vote
        """,
        (suggestion.id, int(user_id), value, int(now)),
    )
    return value


# --------------------------------------------------------------------------
# Décision du staff
# --------------------------------------------------------------------------

async def set_status(
    db: Any,
    suggestion: Suggestion,
    *,
    status: str,
    staff_id: int,
    response: str | None,
    now: int,
) -> Suggestion:
    if status not in STATUSES:
        raise SuggestionError("invalid_status")
    response = str(response or "").strip()[:MAX_RESPONSE] or None
    await db.execute(
        "UPDATE suggestions SET status = ?, staff_id = ?, staff_response = ?, updated_at = ? "
        "WHERE id = ?",
        (status, int(staff_id), response, int(now), suggestion.id),
    )
    updated = await get(db, suggestion.id)
    assert updated is not None
    return updated


def dumps_settings(settings: Settings) -> str:
    """Forme lisible pour les journaux d'audit."""
    return json.dumps(
        {
            "channel_id": settings.channel_id,
            "cooldown_seconds": settings.cooldown_seconds,
            "anonymous": settings.anonymous,
            "threads": settings.threads,
        },
        ensure_ascii=False,
    )


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS", "LEGACY_STATUSES", "STATUSES", "Settings", "Suggestion",
    "SuggestionError", "attach_message", "by_message", "by_number", "cooldown_remaining",
    "counts", "create", "discard", "ensure_schema", "get", "get_settings", "save_settings",
    "set_status", "vote",
]
