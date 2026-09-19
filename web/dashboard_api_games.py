"""Routes Jeux du dashboard SentriX.

Ce module expose uniquement des adaptateurs vers les backends de jeu déjà présents.
Le compteur infini reste stocké dans `infinite_counter_config` et continue d'être traité
par `cogs.infinite_counter.InfiniteCounter` côté Discord.
"""
from __future__ import annotations

import time

import discord
from aiohttp import web

INFINITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS infinite_counter_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    next_number INTEGER NOT NULL DEFAULT 1,
    last_user_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL
)
"""


def _integer(value, minimum: int, maximum: int, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} doit être un nombre entier.")
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} doit être compris entre {minimum} et {maximum}.")
    return number


def register(app: web.Application, dashboard) -> None:
    bot = app["bot"]

    async def _guard(request: web.Request, *, write: bool = False):
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return None, None, error
        if write:
            csrf_error = dashboard._require_csrf(request, session)
            if csrf_error:
                return None, None, csrf_error
        return session, guild, None

    async def _payload(request: web.Request) -> dict:
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def _ensure_schema() -> None:
        await bot.db.execute(INFINITE_SCHEMA)

    def _invalidate(guild_id: int) -> None:
        cog = bot.get_cog("InfiniteCounter") if hasattr(bot, "get_cog") else None
        invalidate = getattr(cog, "_invalidate_enabled", None)
        if callable(invalidate):
            invalidate(guild_id)

    async def infinite_get(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        await _ensure_schema()
        row = await bot.db.fetchone(
            "SELECT channel_id,next_number,last_user_id,enabled,updated_at "
            "FROM infinite_counter_config WHERE guild_id=?",
            (guild.id,),
        )
        if row is None:
            return web.json_response({
                "ok": True,
                "configured": False,
                "enabled": False,
                "channel_id": None,
                "next_number": 1,
                "current_number": 0,
                "last_user_id": None,
                "last_user_name": None,
                "updated_at": None,
            })
        last_id = int(row["last_user_id"]) if row["last_user_id"] else None
        member = guild.get_member(last_id) if last_id else None
        next_number = int(row["next_number"])
        return web.json_response({
            "ok": True,
            "configured": True,
            "enabled": bool(row["enabled"]),
            "channel_id": str(row["channel_id"]),
            "next_number": next_number,
            "current_number": max(0, next_number - 1),
            "last_user_id": str(last_id) if last_id else None,
            "last_user_name": member.display_name if member else None,
            "updated_at": int(row["updated_at"] or 0),
        })

    async def infinite_put(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        await _ensure_schema()
        payload = await _payload(request)
        try:
            channel_id = int(payload.get("channel_id") or 0)
        except (TypeError, ValueError):
            channel_id = 0
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return dashboard._json_error("Choisissez un salon textuel valide.", 400)
        me = guild.me
        if me is not None:
            perms = channel.permissions_for(me)
            if not (perms.view_channel and perms.send_messages):
                return dashboard._json_error("SentriX ne peut pas lire et écrire dans ce salon.", 409)

        row = await bot.db.fetchone(
            "SELECT next_number,enabled FROM infinite_counter_config WHERE guild_id=?",
            (guild.id,),
        )
        reset = bool(payload.get("reset_progression"))
        if row is None or reset:
            try:
                start = _integer(payload.get("start_number", 1), 1, 10**18, "Le nombre de départ")
            except ValueError as exc:
                return dashboard._json_error(str(exc), 400)
            enabled = 1 if payload.get("enabled", True) else 0
            await bot.db.execute(
                "INSERT INTO infinite_counter_config "
                "(guild_id,channel_id,next_number,last_user_id,enabled,updated_at) "
                "VALUES (?,?,?,NULL,?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET "
                "channel_id=excluded.channel_id,next_number=excluded.next_number,"
                "last_user_id=NULL,enabled=excluded.enabled,updated_at=excluded.updated_at",
                (guild.id, channel.id, start, enabled, int(time.time())),
            )
            message = f"Compteur infini configuré dans #{channel.name} à partir de {start}."
        else:
            enabled = int(row["enabled"]) if "enabled" not in payload else (1 if payload["enabled"] else 0)
            await bot.db.execute(
                "UPDATE infinite_counter_config SET channel_id=?,enabled=?,updated_at=? WHERE guild_id=?",
                (channel.id, enabled, int(time.time()), guild.id),
            )
            message = f"Salon du compteur infini mis à jour : #{channel.name}."
        _invalidate(guild.id)
        return web.json_response({"ok": True, "message": message})

    async def infinite_action(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        await _ensure_schema()
        payload = await _payload(request)
        action = str(payload.get("action") or "").strip().lower()
        row = await bot.db.fetchone(
            "SELECT channel_id,next_number,enabled FROM infinite_counter_config WHERE guild_id=?",
            (guild.id,),
        )
        if row is None:
            return dashboard._json_error("Configurez d’abord le compteur infini.", 409)

        if action in {"pause", "stop", "disable"}:
            await bot.db.execute(
                "UPDATE infinite_counter_config SET enabled=0,updated_at=? WHERE guild_id=?",
                (int(time.time()), guild.id),
            )
            message = "Compteur infini suspendu. La progression est conservée."
        elif action in {"resume", "start", "enable"}:
            await bot.db.execute(
                "UPDATE infinite_counter_config SET enabled=1,updated_at=? WHERE guild_id=?",
                (int(time.time()), guild.id),
            )
            message = "Compteur infini repris avec la progression enregistrée."
        elif action == "reset":
            try:
                start = _integer(payload.get("start_number", 1), 1, 10**18, "Le nombre de départ")
            except ValueError as exc:
                return dashboard._json_error(str(exc), 400)
            await bot.db.execute(
                "UPDATE infinite_counter_config SET next_number=?,last_user_id=NULL,updated_at=? WHERE guild_id=?",
                (start, int(time.time()), guild.id),
            )
            message = f"Compteur infini réinitialisé : prochain nombre {start}."
        else:
            return dashboard._json_error("Action de compteur inconnue.", 400)

        _invalidate(guild.id)
        return web.json_response({"ok": True, "message": message})

    app.router.add_get("/api/guilds/{guild_id}/games/infinite", infinite_get)
    app.router.add_put("/api/guilds/{guild_id}/games/infinite", infinite_put)
    app.router.add_post("/api/guilds/{guild_id}/games/infinite/action", infinite_action)


__all__ = ["register", "INFINITE_SCHEMA"]
