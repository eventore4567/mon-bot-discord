"""Bot V13 — production hardening for SentriX.

Bot-only layer that finishes the V12 production work without changing the dashboard:
- routes security notices to the real AutoMod/moderation log channels;
- replaces duplicate V12 ticket watchers with one localized/legacy-compatible SLA loop;
- exposes V12 game streak/form statistics next to existing player commands;
- runs live canaries through Discord API, SQLite and OpenAI when configured;
- reconnects optional PostgreSQL/Redis infrastructure after transient failures;
- creates transactionally consistent SQLite backups and verifies restores before swap;
- supervises these integrations so transient failures do not permanently stop them.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import os
import secrets
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

import discord

from utils import sentrix_panels as panels
from discord.ext import commands, tasks

logger = logging.getLogger("bot.v13-production")

TICKET_CHECK_SECONDS = 120
TICKET_UNCLAIMED_SECONDS = 15 * 60
TICKET_REMINDER_COOLDOWN = 30 * 60
CANARY_INTERVAL_MINUTES = 15
AI_CANARY_INTERVAL_SECONDS = 60 * 60
INFRA_CHECK_MINUTES = 2
INFRA_RECONNECT_COOLDOWN = 5 * 60
SUPERVISOR_SECONDS = 60

V13_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS v13_canary_probe (
        probe_id TEXT PRIMARY KEY,
        created_at INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_v13_canary_probe_time
    ON v13_canary_probe (created_at)
    """,
)


def _row_value(row: Any, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _sqlite_integrity(path: Path) -> str:
    """Return SQLite integrity result for an offline snapshot/candidate file."""
    with sqlite3.connect(str(path), timeout=30) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "missing").strip().casefold()


def _sqlite_snapshot(source: Path, target: Path) -> None:
    """Create a consistent snapshot using SQLite's online backup API."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with sqlite3.connect(str(source), timeout=30) as src, sqlite3.connect(str(target), timeout=30) as dst:
        src.backup(dst, pages=256, sleep=0.05)
        dst.commit()
    result = _sqlite_integrity(target)
    if result != "ok":
        raise RuntimeError(f"SQLite integrity_check failed: {result[:120]}")


def _gzip_file(source: Path, target: Path) -> None:
    with source.open("rb") as src, gzip.open(target, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)


def _gunzip_file(source: Path, target: Path) -> None:
    with gzip.open(source, "rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class BotV13Production(commands.Cog, name="BotV13Production"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_ai_probe_at = 0.0
        self._last_ai_probe: dict[str, Any] | None = None
        self._last_infra_reconnect = 0.0
        self._last_infra_state: tuple[bool, bool] | None = None
        self._security_patch_done = False
        self._backup_patch_done = False

    async def cog_load(self) -> None:
        await self._ensure_schema()
        await self.ensure_integrations()
        for loop in (self.ticket_sla_loop, self.live_canary_loop, self.infra_watch_loop, self.supervisor_loop):
            if not loop.is_running():
                loop.start()

    def cog_unload(self) -> None:
        for loop in (self.ticket_sla_loop, self.live_canary_loop, self.infra_watch_loop, self.supervisor_loop):
            loop.cancel()

    async def _ensure_schema(self) -> None:
        for statement in V13_SCHEMA:
            try:
                await self.bot.db.execute(statement)
            except Exception:
                logger.warning("V13: schema probe unavailable.", exc_info=True)

    # ------------------------------------------------------------ integration
    async def ensure_integrations(self) -> None:
        await self._disable_duplicate_ticket_watchers()
        self._patch_security_notice_route()
        self._patch_game_stat_commands()
        self._patch_enterprise_backup_recovery()

    async def _disable_duplicate_ticket_watchers(self) -> None:
        machine = self.bot.get_cog("BotV12Machine")
        if machine is not None:
            try:
                if machine.ticket_watch_loop.is_running():
                    machine.ticket_watch_loop.cancel()
            except Exception:
                logger.debug("V13: unable to stop V12 ticket loop.", exc_info=True)

        legacy = self.bot.get_cog("BotV12TicketSLA")
        if legacy is not None:
            try:
                legacy.ticket_watch_loop.cancel()
            except Exception:
                pass
            try:
                await self.bot.remove_cog("BotV12TicketSLA")
            except Exception:
                logger.debug("V13: unable to remove legacy ticket SLA cog.", exc_info=True)

    def _patch_security_notice_route(self) -> None:
        machine = self.bot.get_cog("BotV12Machine")
        if machine is None:
            return
        cls = type(machine)
        current = cls._send_security_notice
        if getattr(current, "_sentrix_v13_log_route", False):
            self._security_patch_done = True
            return

        async def send_security_notice(instance, guild: discord.Guild, title: str, description: str) -> None:
            try:
                conf = await instance.bot.db.get_guild_config(guild.id)
            except Exception:
                conf = None
            if not conf:
                return

            # Real guild_config fields, ordered from the most specific security log to fallback.
            candidate_ids: list[int] = []
            for field in ("log_automod", "log_moderation", "error_channel", "log_channel", "ticket_log_channel"):
                try:
                    value = conf[field]
                except Exception:
                    value = None
                if value:
                    try:
                        candidate_ids.append(int(value))
                    except (TypeError, ValueError):
                        pass

            me = guild.me
            for channel_id in dict.fromkeys(candidate_ids):
                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue
                if me is not None:
                    perms = channel.permissions_for(me)
                    if not perms.send_messages or not perms.embed_links:
                        continue
                try:
                    await panels.envoyer(channel, panels.depuis_embed(discord.Embed(title=title[:256], description=description[:1800], color=discord.Color.orange())), allowed_mentions=discord.AllowedMentions.none())
                    return
                except discord.HTTPException:
                    logger.debug("V13 security notice delivery failed channel=%s", channel_id, exc_info=True)

        send_security_notice._sentrix_v13_log_route = True
        send_security_notice._sentrix_original = current
        cls._send_security_notice = send_security_notice
        self._security_patch_done = True
        logger.info("V13: security alerts now use log_automod/log_moderation fallbacks.")

    def _patch_game_stat_commands(self) -> None:
        for command_name in ("gameprofile", "gamestats"):
            command = self.bot.get_command(command_name)
            if command is None:
                continue
            current = command.callback
            if getattr(current, "_sentrix_v13_form_stats", False):
                continue

            async def enriched(cog, ctx: commands.Context, membre: discord.Member = None, _original=current):
                result = await _original(cog, ctx, membre)
                if ctx.guild is None:
                    return result
                target = membre or ctx.author
                try:
                    form = await cog.bot.db.fetchone(
                        "SELECT wins,losses,current_streak,longest_streak,total_reward,last_game,last_result,updated_at "
                        "FROM v12_game_form WHERE guild_id=? AND user_id=?",
                        (ctx.guild.id, target.id),
                    )
                except Exception:
                    form = None
                if not form:
                    return result

                current_streak = int(_row_value(form, "current_streak", 0) or 0)
                longest_streak = int(_row_value(form, "longest_streak", 0) or 0)
                tracked_reward = int(_row_value(form, "total_reward", 0) or 0)
                last_game = str(_row_value(form, "last_game", "-") or "-")
                last_result = str(_row_value(form, "last_result", "-") or "-")
                try:
                    from .games_economy import GAME_CATALOG, _embed
                    label = GAME_CATALOG.get(last_game, (last_game, ""))[0]
                    description = (
                        f"**Série actuelle :** {current_streak}\n"
                        f"**Meilleure série :** {longest_streak}\n"
                        f"**Gains suivis V12+ :** {tracked_reward} pièces\n"
                        f"**Dernier jeu :** {label}\n"
                        f"**Dernier résultat :** {last_result}"
                    )
                    embed = await _embed(
                        cog.bot,
                        ctx.guild.id,
                        title=f"Forme de jeu — {target.display_name}",
                        description=description,
                    )
                    await panels.envoyer(ctx, panels.depuis_embed(embed))
                except Exception:
                    logger.debug("V13: unable to display game form stats.", exc_info=True)
                return result

            enriched._sentrix_v13_form_stats = True
            enriched._sentrix_original = current
            command.callback = enriched
        
    # ------------------------------------------------------------ tickets SLA
    @tasks.loop(seconds=TICKET_CHECK_SECONDS)
    async def ticket_sla_loop(self) -> None:
        try:
            rows = await self.bot.db.fetchall(
                "SELECT id,guild_id,channel_id,claimed_by,status,created_at "
                "FROM tickets WHERE status IN ('ouvert','open') ORDER BY created_at ASC LIMIT 500"
            )
        except Exception:
            logger.debug("V13 ticket SLA: database read unavailable.", exc_info=True)
            return

        now_ts = int(time.time())
        machine = self.bot.get_cog("BotV12Machine")
        for row in rows:
            try:
                ticket_id = int(_row_value(row, "id", 0) or 0)
                guild_id = int(_row_value(row, "guild_id", 0) or 0)
                channel_id = int(_row_value(row, "channel_id", 0) or 0)
                created_at = int(_row_value(row, "created_at", now_ts) or now_ts)
                claimed_by = _row_value(row, "claimed_by")
            except (TypeError, ValueError):
                continue
            if not ticket_id or not guild_id or not channel_id:
                continue

            guild = self.bot.get_guild(guild_id)
            channel = guild.get_channel(channel_id) if guild else None
            if channel is None:
                if machine is not None and hasattr(machine, "_record_event"):
                    try:
                        await machine._record_event(
                            guild_id,
                            "ticket_channel_missing",
                            "medium",
                            target_id=ticket_id,
                            details={"channel_id": channel_id},
                            score=45,
                        )
                    except Exception:
                        pass
                continue

            try:
                await self.bot.db.execute(
                    "INSERT INTO v12_ticket_watch (ticket_id,guild_id,channel_id,last_reminder_at,last_seen_at) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(ticket_id) DO UPDATE SET "
                    "guild_id=excluded.guild_id,channel_id=excluded.channel_id,last_seen_at=excluded.last_seen_at",
                    (ticket_id, guild_id, channel_id, 0, now_ts),
                )
            except Exception:
                continue

            if claimed_by or now_ts - created_at < TICKET_UNCLAIMED_SECONDS:
                continue
            try:
                watch = await self.bot.db.fetchone(
                    "SELECT last_reminder_at FROM v12_ticket_watch WHERE ticket_id=?",
                    (ticket_id,),
                )
                last_reminder = int(_row_value(watch, "last_reminder_at", 0) or 0)
            except Exception:
                last_reminder = 0
            if now_ts - last_reminder < TICKET_REMINDER_COOLDOWN:
                continue

            try:
                await panels.envoyer(channel, panels.depuis_embed(discord.Embed(title='Ticket en attente', description="Ce ticket est toujours **non pris en charge** depuis plus de 15 minutes. Un membre du staff peut le claim dès qu'il est disponible.", color=discord.Color.orange())), allowed_mentions=discord.AllowedMentions.none())
                await self.bot.db.execute(
                    "UPDATE v12_ticket_watch SET last_reminder_at=?,last_seen_at=? WHERE ticket_id=?",
                    (now_ts, now_ts, ticket_id),
                )
                if machine is not None and hasattr(machine, "_record_event"):
                    try:
                        await machine._record_event(
                            guild_id,
                            "ticket_unclaimed_sla",
                            "medium",
                            target_id=ticket_id,
                            details={"channel_id": channel_id, "age_seconds": now_ts - created_at},
                            score=40,
                        )
                    except Exception:
                        pass
            except discord.HTTPException:
                logger.debug("V13 ticket reminder failed ticket=%s", ticket_id, exc_info=True)
            except Exception:
                logger.debug("V13 ticket reminder processing failed ticket=%s", ticket_id, exc_info=True)

        # Remove state for tickets that are no longer open; this keeps the watcher table bounded.
        try:
            await self.bot.db.execute(
                "DELETE FROM v12_ticket_watch WHERE ticket_id NOT IN "
                "(SELECT id FROM tickets WHERE status IN ('ouvert','open'))"
            )
        except Exception:
            pass

    @ticket_sla_loop.before_loop
    async def before_ticket_sla_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------ live canary
    async def _probe_database(self) -> dict[str, Any]:
        probe_id = secrets.token_hex(12)
        start = time.monotonic()
        try:
            await self.bot.db.execute(
                "INSERT INTO v13_canary_probe (probe_id,created_at) VALUES (?,?)",
                (probe_id, int(time.time())),
            )
            row = await self.bot.db.fetchone(
                "SELECT probe_id FROM v13_canary_probe WHERE probe_id=?",
                (probe_id,),
            )
            ok = bool(row and _row_value(row, "probe_id") == probe_id)
            return {"name": "database_crud", "status": "ok" if ok else "error", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
        except Exception as exc:
            return {"name": "database_crud", "status": "error", "error": type(exc).__name__}
        finally:
            try:
                await self.bot.db.execute("DELETE FROM v13_canary_probe WHERE probe_id=?", (probe_id,))
            except Exception:
                pass

    async def _probe_discord(self) -> dict[str, Any]:
        if not self.bot.is_ready() or self.bot.user is None:
            return {"name": "discord_api", "status": "error", "details": "bot_not_ready"}
        start = time.monotonic()
        try:
            user = await asyncio.wait_for(self.bot.fetch_user(self.bot.user.id), timeout=10)
            ok = bool(user and user.id == self.bot.user.id)
            return {"name": "discord_api", "status": "ok" if ok else "error", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
        except Exception as exc:
            return {"name": "discord_api", "status": "error", "error": type(exc).__name__}

    async def _probe_ai(self) -> dict[str, Any]:
        try:
            import config
            from utils import ai_service
        except Exception as exc:
            return {"name": "openai", "status": "error", "error": type(exc).__name__}
        if not getattr(config, "OPENAI_API_KEY", None):
            return {"name": "openai", "status": "skipped", "details": "not_configured"}
        now_m = time.monotonic()
        if self._last_ai_probe is not None and now_m - self._last_ai_probe_at < AI_CANARY_INTERVAL_SECONDS:
            return dict(self._last_ai_probe)
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(ai_service.test_connection(model_key=ai_service.MODEL_LUNA), timeout=20)
            probe = {
                "name": "openai",
                "status": "ok" if result.get("ok") else "error",
                "latency_ms": int(result.get("latency_ms") or round((time.monotonic() - start) * 1000)),
            }
            if not result.get("ok"):
                probe["error"] = result.get("error_type") or "unknown"
        except Exception as exc:
            probe = {"name": "openai", "status": "error", "error": type(exc).__name__}
        self._last_ai_probe_at = now_m
        self._last_ai_probe = dict(probe)
        return probe

    async def run_live_canary(self) -> dict[str, Any]:
        checks = [await self._probe_discord(), await self._probe_database()]
        service = self.bot.get_cog("EnterpriseSuite")
        infra_health: dict[str, Any] = {}
        if service is not None and getattr(service, "infra", None) is not None:
            try:
                infra_health = await asyncio.wait_for(service.infra.health(), timeout=12)
            except Exception as exc:
                infra_health = {"error": type(exc).__name__}
            pg_bad = bool(infra_health.get("postgres_configured")) and not bool(infra_health.get("postgres_online"))
            redis_bad = bool(infra_health.get("redis_configured")) and not bool(infra_health.get("redis_online"))
            checks.append({"name": "postgres", "status": "error" if pg_bad else ("ok" if infra_health.get("postgres_configured") else "skipped")})
            checks.append({"name": "redis", "status": "error" if redis_bad else ("ok" if infra_health.get("redis_configured") else "skipped")})

        checks.append(await self._probe_ai())
        hard_fail = any(item.get("status") == "error" for item in checks if item.get("name") in {"discord_api", "database_crud"})
        degraded = any(item.get("status") == "error" for item in checks if item.get("name") not in {"discord_api", "database_crud"})
        status = "error" if hard_fail else ("degraded" if degraded else "ok")
        ts = int(time.time())
        result = {"status": status, "created_at": ts, "checks": checks, "infra": infra_health}
        self.bot.sentrix_canary_status = result
        try:
            await self.bot.db.execute(
                "INSERT INTO canary_checks_v2 (guild_id,status,details_json,created_at) VALUES (?,?,?,?)",
                (None, status, json.dumps(result, ensure_ascii=False)[:12000], ts),
            )
            await self.bot.db.execute("DELETE FROM canary_checks_v2 WHERE created_at < ?", (ts - 30 * 86400,))
        except Exception:
            logger.debug("V13 canary history unavailable.", exc_info=True)

        if status != "ok":
            machine = self.bot.get_cog("BotV12Machine")
            if machine is not None and hasattr(machine, "_record_event"):
                try:
                    await machine._record_event(
                        None,
                        "v13_live_canary",
                        "critical" if status == "error" else "warning",
                        details={"checks": checks},
                        score=95 if status == "error" else 65,
                    )
                except Exception:
                    pass
        return result

    @tasks.loop(minutes=CANARY_INTERVAL_MINUTES)
    async def live_canary_loop(self) -> None:
        try:
            service = self.bot.get_cog("EnterpriseSuite")
            infra = getattr(service, "infra", None) if service else None
            lease = secrets.token_hex(8)
            if infra is not None and not await infra.acquire_lease("v13-live-canary", lease, ttl=180):
                return
            try:
                await self.run_live_canary()
            finally:
                if infra is not None:
                    await infra.release_lease("v13-live-canary", lease)
        except Exception:
            logger.warning("V13 live canary cycle failed.", exc_info=True)

    @live_canary_loop.before_loop
    async def before_live_canary_loop(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(12)

    # ------------------------------------------------------------ infra health
    @tasks.loop(minutes=INFRA_CHECK_MINUTES)
    async def infra_watch_loop(self) -> None:
        service = self.bot.get_cog("EnterpriseSuite")
        infra = getattr(service, "infra", None) if service else None
        if infra is None:
            return
        try:
            health = await asyncio.wait_for(infra.health(), timeout=12)
        except Exception:
            logger.debug("V13 infra health probe failed.", exc_info=True)
            return

        pg_bad = bool(health.get("postgres_configured")) and not bool(health.get("postgres_online"))
        redis_bad = bool(health.get("redis_configured")) and not bool(health.get("redis_online"))
        state = (not pg_bad, not redis_bad)
        if (pg_bad or redis_bad) and time.monotonic() - self._last_infra_reconnect >= INFRA_RECONNECT_COOLDOWN:
            self._last_infra_reconnect = time.monotonic()
            try:
                await asyncio.wait_for(infra.reconnect(), timeout=30)
                health = await asyncio.wait_for(infra.health(), timeout=12)
                pg_bad = bool(health.get("postgres_configured")) and not bool(health.get("postgres_online"))
                redis_bad = bool(health.get("redis_configured")) and not bool(health.get("redis_online"))
                state = (not pg_bad, not redis_bad)
            except Exception:
                logger.warning("V13 infra reconnect failed.", exc_info=True)

        if self._last_infra_state is not None and state != self._last_infra_state:
            machine = self.bot.get_cog("BotV12Machine")
            if machine is not None and hasattr(machine, "_record_event"):
                try:
                    await machine._record_event(
                        None,
                        "enterprise_infra_transition",
                        "info" if all(state) else "warning",
                        details={"postgres_ok": state[0], "redis_ok": state[1]},
                        score=10 if all(state) else 60,
                    )
                except Exception:
                    pass
        self._last_infra_state = state

    @infra_watch_loop.before_loop
    async def before_infra_watch_loop(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(20)

    # ------------------------------------------------------------ safe backups
    def _patch_enterprise_backup_recovery(self) -> None:
        service = self.bot.get_cog("EnterpriseSuite")
        if service is None:
            return
        cls = type(service)
        if getattr(cls.create_external_backup, "_sentrix_v13_consistent_backup", False):
            self._backup_patch_done = True
            return

        current_create = cls.create_external_backup
        current_restore = cls.restore_external_backup
        owner = self

        async def create_consistent_backup(instance, actor_id: int | None = None) -> dict[str, Any]:
            async with instance._backup_lock:
                path = Path(getattr(instance.bot.db, "path", ""))
                if not path.exists():
                    raise ValueError("La base SQLite active est introuvable.")
                ts = int(time.time())
                backup_dir = instance._backup_directory()
                snapshot = backup_dir / f"sentrix-{ts}.snapshot.db"
                archive = backup_dir / f"sentrix-{ts}.db.gz"
                try:
                    await asyncio.to_thread(_sqlite_snapshot, path, snapshot)
                    await asyncio.to_thread(_gzip_file, snapshot, archive)
                    checksum = await asyncio.to_thread(_sha256_file, archive)
                    storage, location = "local", str(archive)
                    client, bucket = instance._s3_client()
                    if client and bucket:
                        key = f"sentrix/backups/{archive.name}"
                        try:
                            await asyncio.to_thread(client.upload_file, str(archive), bucket, key)
                            storage, location = "s3", key
                        except Exception as exc:
                            await instance._record_error(None, "backup:s3-upload", exc)
                    cur = await instance.bot.db.execute(
                        "INSERT INTO external_backups_v2 (storage,location,checksum,size_bytes,status,created_by,created_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (storage, location, checksum, archive.stat().st_size, "ready", actor_id, ts),
                    )
                    local = sorted(backup_dir.glob("sentrix-*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
                    for old in local[12:]:
                        try:
                            old.unlink()
                        except OSError:
                            pass
                    result = {
                        "id": int(cur.lastrowid),
                        "storage": storage,
                        "location": location,
                        "checksum": checksum,
                        "size_bytes": archive.stat().st_size,
                        "created_at": ts,
                        "integrity": "ok",
                    }
                    await instance.infra.mirror_event(
                        "external_backup_v13",
                        None,
                        {"id": result["id"], "storage": storage, "size_bytes": result["size_bytes"], "integrity": "ok"},
                        ts,
                    )
                    return result
                finally:
                    try:
                        snapshot.unlink()
                    except OSError:
                        pass

        async def restore_verified_backup(instance, backup_id: int, actor_id: int) -> None:
            async with instance._backup_lock:
                row = await instance.bot.db.fetchone(
                    "SELECT * FROM external_backups_v2 WHERE id=? AND status='ready'",
                    (backup_id,),
                )
                if not row:
                    raise ValueError("Sauvegarde introuvable.")
                item = dict(row)
                backup_dir = instance._backup_directory()
                temp_gz = backup_dir / f"restore-{backup_id}.db.gz"
                candidate = backup_dir / f"restore-{backup_id}.candidate.db"
                db_path = Path(instance.bot.db.path)
                rollback = db_path.with_suffix(db_path.suffix + ".pre-restore-v13")
                try:
                    if item["storage"] == "local":
                        source = Path(item["location"])
                        if not source.exists():
                            raise ValueError("Le fichier de sauvegarde local n'existe plus.")
                        await asyncio.to_thread(shutil.copy2, source, temp_gz)
                    elif item["storage"] == "s3":
                        client, bucket = instance._s3_client()
                        if not client or not bucket:
                            raise ValueError("Le stockage S3 n'est pas configuré sur ce déploiement.")
                        await asyncio.to_thread(client.download_file, bucket, item["location"], str(temp_gz))
                    else:
                        raise ValueError("Type de stockage non supporté.")

                    digest = await asyncio.to_thread(_sha256_file, temp_gz)
                    if digest != item["checksum"]:
                        raise ValueError("Checksum invalide : restauration annulée.")
                    await asyncio.to_thread(_gunzip_file, temp_gz, candidate)
                    integrity = await asyncio.to_thread(_sqlite_integrity, candidate)
                    if integrity != "ok":
                        raise ValueError(f"Base restaurée invalide ({integrity[:100]}).")

                    # Keep a verified pre-restore snapshot for rollback instead of a raw live-file copy.
                    await asyncio.to_thread(_sqlite_snapshot, db_path, rollback)
                    await instance.bot.db.close()
                    try:
                        for suffix in ("-wal", "-shm"):
                            sidecar = Path(str(db_path) + suffix)
                            try:
                                sidecar.unlink()
                            except OSError:
                                pass
                        os.replace(candidate, db_path)
                        await instance.bot.db.connect()
                        check = await instance.bot.db.fetchone("PRAGMA quick_check")
                        if check is not None and str(check[0]).strip().casefold() != "ok":
                            raise RuntimeError("Post-restore quick_check failed")
                        cache = getattr(instance.bot.db, "_guild_config_cache", None)
                        if isinstance(cache, dict):
                            cache.clear()
                        prefix_cache = getattr(instance.bot, "prefix_cache", None)
                        if isinstance(prefix_cache, dict):
                            prefix_cache.clear()
                    except Exception:
                        try:
                            await instance.bot.db.close()
                        except Exception:
                            pass
                        await asyncio.to_thread(shutil.copy2, rollback, db_path)
                        await instance.bot.db.connect()
                        raise

                    try:
                        await instance.bot.db.execute(
                            "UPDATE external_backups_v2 SET restored_at=? WHERE id=?",
                            (int(time.time()), backup_id),
                        )
                    except Exception:
                        pass
                    await instance.infra.mirror_event(
                        "external_backup_restored_v13",
                        None,
                        {"id": backup_id, "actor_id": actor_id, "integrity": "ok"},
                        int(time.time()),
                    )
                finally:
                    for temp in (temp_gz, candidate):
                        try:
                            temp.unlink()
                        except OSError:
                            pass

        create_consistent_backup._sentrix_v13_consistent_backup = True
        create_consistent_backup._sentrix_original = current_create
        restore_verified_backup._sentrix_v13_verified_restore = True
        restore_verified_backup._sentrix_original = current_restore
        cls.create_external_backup = create_consistent_backup
        cls.restore_external_backup = restore_verified_backup
        self._backup_patch_done = True
        logger.info("V13: consistent SQLite backup + verified recovery enabled.")

    # ------------------------------------------------------------ supervisor
    @tasks.loop(seconds=SUPERVISOR_SECONDS)
    async def supervisor_loop(self) -> None:
        try:
            await self.ensure_integrations()
            for loop in (self.ticket_sla_loop, self.live_canary_loop, self.infra_watch_loop):
                if not loop.is_running():
                    try:
                        loop.start()
                    except RuntimeError:
                        pass
        except Exception:
            logger.warning("V13 supervisor cycle failed.", exc_info=True)

    @supervisor_loop.before_loop
    async def before_supervisor_loop(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        try:
            await self.ensure_integrations()
        except Exception:
            logger.debug("V13 ready integration pass failed.", exc_info=True)


async def setup(bot: commands.Bot) -> None:
    if bot.get_cog("BotV13Production") is None:
        await bot.add_cog(BotV13Production(bot))
