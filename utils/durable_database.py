"""Durabilité du stockage principal SentriX via snapshots PostgreSQL.

Le runtime historique reste compatible SQLite (plusieurs centaines de requêtes et
migrations utilisent sa syntaxe). Cette couche rend néanmoins cette base durable :
- snapshot cohérent de la base SQLite avec l'API backup de sqlite3 ;
- compression gzip + SHA-256 ;
- stockage des snapshots dans PostgreSQL quand POSTGRES_URL/DATABASE_URL existe ;
- restauration automatique au boot si le fichier local a disparu ou est invalide ;
- rétention bornée des snapshots PostgreSQL.

Le stockage externe est volontairement fail-open : une panne PostgreSQL ne doit jamais
empêcher SentriX de démarrer avec une base locale saine.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import logging
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("bot.durable-db")

try:
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover - dépendance optionnelle
    asyncpg = None


PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_main_db_snapshots (
    id BIGSERIAL PRIMARY KEY,
    checksum TEXT NOT NULL,
    compressed_data BYTEA NOT NULL,
    compressed_size BIGINT NOT NULL,
    sqlite_size BIGINT NOT NULL,
    clean_shutdown BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT NOT NULL DEFAULT 'periodic',
    created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sentrix_main_db_snapshots_time
ON sentrix_main_db_snapshots (created_at DESC);
"""


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on", "oui"}


def _sqlite_healthy_sync(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 4096:
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            if not row or str(row[0]).casefold() != "ok":
                return False
            tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()
            return bool(tables and int(tables[0]) >= 5)
        finally:
            conn.close()
    except Exception:
        return False


def _backup_sqlite_sync(source_path: Path, target_path: Path) -> int:
    source = sqlite3.connect(str(source_path), timeout=20)
    target = sqlite3.connect(str(target_path), timeout=20)
    try:
        source.backup(target, pages=256, sleep=0.01)
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        target.commit()
    finally:
        target.close()
        source.close()
    if not _sqlite_healthy_sync(target_path):
        raise RuntimeError("Le snapshot SQLite généré n'est pas valide.")
    return target_path.stat().st_size


class DurableDatabaseReplica:
    """Réplication snapshot du fichier SQLite principal vers PostgreSQL."""

    def __init__(self, sqlite_path: str) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.postgres_url = (os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL") or "").strip()
        self.keep = _env_int("SENTRIX_PG_SNAPSHOT_KEEP", 12, 2, 96)
        self.interval_seconds = _env_int("SENTRIX_PG_SNAPSHOT_INTERVAL", 900, 300, 86400)
        self.force_restore = _truthy("SENTRIX_RESTORE_FROM_POSTGRES", False)
        self.pool = None
        self.error: str | None = None
        self.last_snapshot_at: int | None = None
        self.last_restore_at: int | None = None
        self.last_snapshot_id: int | None = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.postgres_url)

    @property
    def online(self) -> bool:
        return self.pool is not None

    async def connect(self) -> bool:
        if not self.postgres_url:
            self.error = "POSTGRES_URL non configuré"
            return False
        if asyncpg is None:
            self.error = "asyncpg indisponible"
            return False
        if self.pool is not None:
            return True
        try:
            self.pool = await asyncpg.create_pool(
                self.postgres_url,
                min_size=1,
                max_size=2,
                command_timeout=45,
            )
            async with self.pool.acquire() as conn:
                await conn.execute(PG_SCHEMA)
                await conn.fetchval("SELECT 1")
            self.error = None
            logger.info("Stockage durable PostgreSQL connecté.")
            return True
        except Exception as exc:
            self.pool = None
            self.error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning("PostgreSQL durable indisponible ; SentriX conserve le stockage local.")
            return False

    async def close(self) -> None:
        pool, self.pool = self.pool, None
        if pool is not None:
            try:
                await pool.close()
            except Exception:
                pass

    async def _local_healthy(self) -> bool:
        return await asyncio.to_thread(_sqlite_healthy_sync, self.sqlite_path)

    async def restore_latest_if_needed(self) -> dict[str, Any]:
        """Restaure seulement si le stockage local est absent/invalide, sauf option force."""
        local_ok = await self._local_healthy()
        if local_ok and not self.force_restore:
            return {"restored": False, "reason": "local_healthy"}
        if self.pool is None and not await self.connect():
            return {"restored": False, "reason": "postgres_unavailable", "error": self.error}

        async with self._lock:
            try:
                row = await self.pool.fetchrow(
                    "SELECT id,checksum,compressed_data,sqlite_size,created_at "
                    "FROM sentrix_main_db_snapshots ORDER BY created_at DESC,id DESC LIMIT 1"
                )
                if not row:
                    return {"restored": False, "reason": "no_snapshot"}
                compressed = bytes(row["compressed_data"])
                digest = hashlib.sha256(compressed).hexdigest()
                if digest != str(row["checksum"]):
                    raise RuntimeError("Checksum du snapshot PostgreSQL invalide.")
                raw = await asyncio.to_thread(gzip.decompress, compressed)
                self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
                fd, temp_name = tempfile.mkstemp(
                    prefix="sentrix-restore-", suffix=".db", dir=str(self.sqlite_path.parent)
                )
                os.close(fd)
                temp_path = Path(temp_name)
                try:
                    await asyncio.to_thread(temp_path.write_bytes, raw)
                    if not await asyncio.to_thread(_sqlite_healthy_sync, temp_path):
                        raise RuntimeError("Snapshot restauré invalide selon PRAGMA quick_check.")
                    if self.sqlite_path.exists():
                        backup = self.sqlite_path.with_suffix(self.sqlite_path.suffix + ".pre-pg-restore")
                        try:
                            await asyncio.to_thread(self.sqlite_path.replace, backup)
                        except OSError:
                            pass
                    await asyncio.to_thread(os.replace, temp_path, self.sqlite_path)
                finally:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self.last_restore_at = int(time.time())
                logger.warning("Base principale restaurée depuis le snapshot PostgreSQL #%s.", row["id"])
                return {
                    "restored": True,
                    "snapshot_id": int(row["id"]),
                    "created_at": int(row["created_at"]),
                    "sqlite_size": int(row["sqlite_size"]),
                }
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:500]
                logger.exception("Restauration PostgreSQL impossible.")
                return {"restored": False, "reason": "restore_error", "error": self.error}

    async def snapshot(self, *, reason: str = "periodic", clean_shutdown: bool = False) -> dict[str, Any]:
        if self.pool is None and not await self.connect():
            return {"stored": False, "reason": "postgres_unavailable", "error": self.error}
        if not await self._local_healthy():
            return {"stored": False, "reason": "local_invalid"}

        async with self._lock:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix="sentrix-snapshot-", suffix=".db")
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                sqlite_size = await asyncio.to_thread(_backup_sqlite_sync, self.sqlite_path, temp_path)
                raw = await asyncio.to_thread(temp_path.read_bytes)
                compressed = await asyncio.to_thread(gzip.compress, raw, 6)
                checksum = hashlib.sha256(compressed).hexdigest()
                ts = int(time.time())
                row = await self.pool.fetchrow(
                    "INSERT INTO sentrix_main_db_snapshots "
                    "(checksum,compressed_data,compressed_size,sqlite_size,clean_shutdown,reason,created_at) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id",
                    checksum,
                    compressed,
                    len(compressed),
                    sqlite_size,
                    bool(clean_shutdown),
                    str(reason or "periodic")[:80],
                    ts,
                )
                await self.pool.execute(
                    "DELETE FROM sentrix_main_db_snapshots WHERE id IN ("
                    "SELECT id FROM sentrix_main_db_snapshots ORDER BY created_at DESC,id DESC OFFSET $1)",
                    self.keep,
                )
                self.last_snapshot_at = ts
                self.last_snapshot_id = int(row["id"])
                self.error = None
                return {
                    "stored": True,
                    "snapshot_id": self.last_snapshot_id,
                    "created_at": ts,
                    "sqlite_size": sqlite_size,
                    "compressed_size": len(compressed),
                }
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:500]
                logger.exception("Snapshot PostgreSQL de la base principale impossible.")
                return {"stored": False, "reason": "snapshot_error", "error": self.error}
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    async def health(self) -> dict[str, Any]:
        local_ok = await self._local_healthy()
        pg_ok = False
        if self.pool is not None:
            try:
                pg_ok = bool(await self.pool.fetchval("SELECT 1"))
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"[:500]
        return {
            "configured": self.configured,
            "postgres_online": pg_ok,
            "local_sqlite_ok": local_ok,
            "last_snapshot_at": self.last_snapshot_at,
            "last_snapshot_id": self.last_snapshot_id,
            "last_restore_at": self.last_restore_at,
            "snapshot_interval_seconds": self.interval_seconds,
            "snapshots_kept": self.keep,
            "error": self.error if not pg_ok and self.configured else None,
        }
