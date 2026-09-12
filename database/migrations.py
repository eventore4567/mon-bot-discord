"""Système de migrations DB pour SentriX — Milestone 1 (SentriX Core Reliability).

Deux mécanismes complémentaires, jamais un seul :

1. Réconciliation additive automatique (`reconcile_additive_columns`) : compare le
   schéma que produirait un install neuf (les mêmes chaînes SCHEMA/
   GAME_TRANSACTIONS_SCHEMA/LOG_CONFIG_SCHEMA que database/db.py exécute déjà à
   chaque boot pour une base neuve — la source unique de vérité existante, pas une
   copie) contre le schéma réel de la connexion courante, et ajoute les colonnes
   manquantes. Couvre nativement les ~79 tables du bot, pas seulement les 7 que
   l'ancien `Database._migrate()` connaissait à la main — et couvre automatiquement
   toute future colonne ajoutée dans SCHEMA sans qu'il faille se souvenir d'éditer
   un dict `*_NEW_COLUMNS` séparé. Ne fait jamais de DROP ni de RENAME : uniquement
   des ALTER TABLE ADD COLUMN, l'opération qui causait
   `sqlite3.OperationalError: no such column` après une restauration HA d'un
   snapshot plus ancien que le code qui tourne.

2. Migrations numérotées (`MIGRATIONS`) : pour tout ce que la réconciliation ne
   peut pas faire seule (renommage de colonne, transformation de données, backfill,
   suppression). Journalisées dans `schema_migrations`, appliquées une seule fois,
   dans l'ordre. Vide au démarrage de ce système : la réconciliation additive
   absorbe déjà tout le retard connu sans qu'aucune migration numérotée ne soit
   nécessaire pour l'existant. Ajoute une entrée ici uniquement quand un futur
   changement de schéma a besoin de plus qu'un ALTER TABLE ADD COLUMN.

Les deux tournent à CHAQUE appel de `Database.connect()` — boot normal ET reprise
HA après restauration d'un snapshot PostgreSQL (railway_ha_boot.py::
_restore_for_takeover appelle explicitement la méthode `connect()` réelle de la
classe pour rouvrir la connexion après restauration, donc ce module s'exécute là
aussi automatiquement, sans câblage séparé).
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Awaitable, Callable

logger = logging.getLogger("bot.migrations")

MigrationFunc = Callable[[object], Awaitable[None]]


class Migration:
    __slots__ = ("version", "name", "apply")

    def __init__(self, version: int, name: str, apply: MigrationFunc):
        self.version = version
        self.name = name
        self.apply = apply


MIGRATIONS: list[Migration] = []


async def ensure_schema_migrations_table(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
        """
    )


async def current_version(conn) -> int:
    cur = await conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
    row = await cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


async def reconcile_additive_columns(conn, schema_scripts: list[str]) -> list[str]:
    """Ajoute, sur la connexion réelle `conn`, toute colonne présente dans les
    scripts de schéma cible mais absente de la table réelle. Ne touche jamais une
    table qui n'existe pas encore côté réel (les CREATE TABLE IF NOT EXISTS
    exécutés juste avant, dans Database.connect(), s'en chargent déjà)."""
    reference = sqlite3.connect(":memory:")
    try:
        for script in schema_scripts:
            reference.executescript(script)
        reference.commit()

        added: list[str] = []
        tables = [
            row[0]
            for row in reference.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table in tables:
            target_rows = reference.execute(f"PRAGMA table_info({table})").fetchall()
            if not target_rows:
                continue
            target_columns = {row[1]: row for row in target_rows}

            cur = await conn.execute(f"PRAGMA table_info({table})")
            real_columns = {row[1] for row in await cur.fetchall()}
            if not real_columns:
                continue

            for column, definition in target_columns.items():
                if column in real_columns:
                    continue
                col_type = str(definition[2] or "TEXT")
                default = definition[4]
                notnull = definition[3]
                clause = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                if default is not None:
                    clause += f" DEFAULT {default}"
                elif notnull:
                    clause += " DEFAULT 0" if col_type.upper() in ("INTEGER", "REAL") else " DEFAULT ''"
                await conn.execute(clause)
                added.append(f"{table}.{column}")
        return added
    finally:
        reference.close()


async def run(conn, schema_scripts: list[str]) -> None:
    """Point d'entrée unique. Ne commit pas elle-même : Database.connect() fait un
    seul commit englobant à la fin, comme pour le reste de l'initialisation."""
    await ensure_schema_migrations_table(conn)

    added = await reconcile_additive_columns(conn, schema_scripts)
    if added:
        logger.warning(
            "Migrations DB : %d colonne(s) manquante(s) réconciliée(s) automatiquement (%s).",
            len(added), ", ".join(added),
        )

    version = await current_version(conn)
    for migration in sorted(MIGRATIONS, key=lambda m: m.version):
        if migration.version <= version:
            continue
        logger.info("Migration %s (%s) en cours...", migration.version, migration.name)
        await migration.apply(conn)
        await conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (migration.version, migration.name),
        )
        logger.info("Migration %s (%s) appliquée.", migration.version, migration.name)
