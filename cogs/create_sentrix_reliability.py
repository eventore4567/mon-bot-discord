"""Fiabilise +create sentrix sur les bases déjà utilisées par d'anciennes versions.

Le constructeur SentriX a évolué avec une colonne ``template_key``. SQLite ne modifie pas
une table existante avec ``CREATE TABLE IF NOT EXISTS`` ; cette couche applique donc la
migration manquante avant toute lecture de l'installation.
"""
from __future__ import annotations

import asyncio
import logging

from discord.ext import commands

logger = logging.getLogger("bot.create-sentrix-reliability")

_PATCHED = False
_MIGRATION_LOCK = asyncio.Lock()


def _column_name(row) -> str:
    try:
        return str(row["name"])
    except (TypeError, KeyError, IndexError):
        try:
            return str(row[1])
        except (TypeError, IndexError):
            return ""


async def _migrate_installation_table(db) -> None:
    if getattr(db, "_sentrix_create_install_schema_v4", False):
        return

    async with _MIGRATION_LOCK:
        if getattr(db, "_sentrix_create_install_schema_v4", False):
            return

        await db.execute(
            "CREATE TABLE IF NOT EXISTS sentrix_server_installations ("
            "guild_id INTEGER PRIMARY KEY,"
            "installed_at INTEGER NOT NULL DEFAULT 0,"
            "installed_by INTEGER NOT NULL DEFAULT 0,"
            "template_key TEXT NOT NULL DEFAULT 'sentrix-official-v3'"
            ")"
        )

        rows = await db.fetchall("PRAGMA table_info(sentrix_server_installations)")
        columns = {_column_name(row) for row in rows}
        additions = {
            "installed_at": "INTEGER NOT NULL DEFAULT 0",
            "installed_by": "INTEGER NOT NULL DEFAULT 0",
            "template_key": "TEXT NOT NULL DEFAULT 'sentrix-official-v3'",
        }
        for name, definition in additions.items():
            if name in columns:
                continue
            logger.warning("Migration SentriX : ajout de la colonne %s", name)
            await db.execute(
                f"ALTER TABLE sentrix_server_installations ADD COLUMN {name} {definition}"
            )

        rows = await db.fetchall("PRAGMA table_info(sentrix_server_installations)")
        columns = {_column_name(row) for row in rows}
        required = {"guild_id", "installed_at", "installed_by", "template_key"}
        missing = required - columns
        if missing:
            raise RuntimeError(
                "Schéma sentrix_server_installations incomplet après migration : "
                + ", ".join(sorted(missing))
            )

        setattr(db, "_sentrix_create_install_schema_v4", True)
        logger.info("Schéma +create sentrix vérifié/migré avec succès.")


def install(bot: commands.Bot, extension_name: str = "") -> None:
    """Patche uniquement les accès DB internes, jamais le callback de la commande."""
    del bot, extension_name
    global _PATCHED
    if _PATCHED:
        return

    from .create_sentrix import CreateSentrix

    original_ensure = CreateSentrix._ensure_table
    original_installation = CreateSentrix._installation
    if getattr(original_ensure, "_sentrix_schema_reliability_v4", False):
        _PATCHED = True
        return

    async def ensure_table_reliable(self) -> None:
        await original_ensure(self)
        await _migrate_installation_table(self.bot.db)

    async def installation_reliable(self, guild_id: int):
        """Une ancienne métadonnée cassée ne doit jamais empêcher la reconstruction."""
        try:
            return await original_installation(self, guild_id)
        except Exception:
            logger.exception(
                "Lecture de l'ancienne installation SentriX impossible guild=%s ; "
                "la commande repart en mode réparation.",
                guild_id,
            )
            try:
                await _migrate_installation_table(self.bot.db)
                return await self.bot.db.fetchone(
                    "SELECT guild_id,installed_at,installed_by,template_key "
                    "FROM sentrix_server_installations WHERE guild_id=?",
                    (guild_id,),
                )
            except Exception:
                logger.exception(
                    "Métadonnées SentriX toujours illisibles guild=%s ; état ignoré pour permettre la réparation.",
                    guild_id,
                )
                return None

    ensure_table_reliable._sentrix_schema_reliability_v4 = True
    ensure_table_reliable._sentrix_original = original_ensure
    installation_reliable._sentrix_installation_reliability_v4 = True
    installation_reliable._sentrix_original = original_installation
    CreateSentrix._ensure_table = ensure_table_reliable
    CreateSentrix._installation = installation_reliable
    _PATCHED = True


__all__ = ["install"]
