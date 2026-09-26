"""Analytics et gestion avancée des invitations dans le dashboard SentriX.

Le tracker historique reste la source de vérité pour l'attribution des arrivées.
Cette API ajoute uniquement de l'observabilité et des métadonnées staff :
labels de codes, masquage de membres du classement et synchronisation de
l'inventaire actuel Discord. La synchronisation n'invente jamais d'attribution
historique pour les membres déjà présents.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any

import discord
from aiohttp import web

from database.db import FAKE_INVITE_ACCOUNT_AGE_DAYS


_WINDOWS = {
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
    "all": None,
}


async def _ensure_schema(bot) -> None:
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS invite_code_meta ("
        "guild_id INTEGER NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', "
        "last_seen_uses INTEGER NOT NULL DEFAULT 0, last_seen_at INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY (guild_id, code))"
    )
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS invite_leaderboard_hidden ("
        "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, hidden_by INTEGER, hidden_at INTEGER NOT NULL, "
        "PRIMARY KEY (guild_id, user_id))"
    )


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
        await _ensure_schema(bot)
        return session, guild, None

    def _member_payload(guild: discord.Guild, user_id: int) -> dict[str, Any]:
        member = guild.get_member(int(user_id))
        user = member or (bot.get_user(int(user_id)) if hasattr(bot, "get_user") else None)
        return {
            "id": str(user_id),
            "name": getattr(user, "name", None),
            "display_name": getattr(user, "display_name", None) or getattr(user, "name", None),
            "avatar_url": str(user.display_avatar.url) if user is not None else None,
            "present": member is not None,
            "roles": [
                {"id": str(role.id), "name": role.name}
                for role in (getattr(member, "roles", ()) if member is not None else ())
                if not role.is_default()
            ][-20:],
        }

    async def _hidden_ids(guild_id: int) -> set[int]:
        rows = await bot.db.fetchall(
            "SELECT user_id FROM invite_leaderboard_hidden WHERE guild_id=?",
            (guild_id,),
        )
        return {int(r["user_id"]) for r in rows}

    async def _labels(guild_id: int) -> dict[str, dict]:
        rows = await bot.db.fetchall(
            "SELECT code,label,last_seen_uses,last_seen_at FROM invite_code_meta WHERE guild_id=?",
            (guild_id,),
        )
        return {
            str(r["code"]): {
                "label": str(r["label"] or ""),
                "last_seen_uses": int(r["last_seen_uses"] or 0),
                "last_seen_at": int(r["last_seen_at"] or 0),
            }
            for r in rows
        }

    async def _active_codes(guild: discord.Guild, labels: dict[str, dict]) -> tuple[list[dict], bool]:
        try:
            invites = await guild.invites()
            allowed = True
        except (discord.Forbidden, discord.HTTPException):
            invites = []
            allowed = False

        rows = await bot.db.fetchall(
            "SELECT invite_code,COUNT(*) AS joins,"
            "SUM(CASE WHEN left_at IS NULL THEN 1 ELSE 0 END) AS active "
            "FROM member_invites WHERE guild_id=? AND invite_code IS NOT NULL "
            "GROUP BY invite_code",
            (guild.id,),
        )
        tracked = {
            str(r["invite_code"]): {
                "joins": int(r["joins"] or 0),
                "active": int(r["active"] or 0),
            }
            for r in rows
        }

        items = []
        for inv in sorted(invites, key=lambda x: int(x.uses or 0), reverse=True):
            meta = labels.get(str(inv.code), {})
            items.append({
                "code": str(inv.code),
                "label": meta.get("label", ""),
                "uses": int(inv.uses or 0),
                "max_uses": int(inv.max_uses or 0),
                "temporary": bool(inv.temporary),
                "expires_at": int(inv.expires_at.timestamp()) if inv.expires_at else None,
                "channel_id": str(inv.channel.id) if inv.channel else None,
                "channel_name": getattr(inv.channel, "name", None),
                "inviter_id": str(inv.inviter.id) if inv.inviter else None,
                "inviter_name": getattr(inv.inviter, "display_name", None) or getattr(inv.inviter, "name", None),
                "tracked_joins": tracked.get(str(inv.code), {}).get("joins", 0),
                "tracked_active": tracked.get(str(inv.code), {}).get("active", 0),
                "last_synced_uses": int(meta.get("last_seen_uses", 0)),
                "last_synced_at": int(meta.get("last_seen_at", 0)),
            })
        return items, allowed

    async def _window_stats(guild_id: int, seconds: int | None) -> dict:
        cutoff = 0 if seconds is None else int(time.time()) - int(seconds)
        rows = await bot.db.fetchall(
            "SELECT member_id,inviter_id,invite_code,joined_at,left_at,account_age_days "
            "FROM member_invites WHERE guild_id=? AND joined_at>=? ORDER BY joined_at ASC",
            (guild_id, cutoff),
        )
        joins = len(rows)
        leaves = sum(1 for r in rows if r["left_at"] is not None)
        active = joins - leaves
        fake = sum(
            1 for r in rows
            if r["left_at"] is None
            and r["account_age_days"] is not None
            and int(r["account_age_days"]) < FAKE_INVITE_ACCOUNT_AGE_DAYS
        )
        attributed = sum(1 for r in rows if r["inviter_id"] is not None)
        retention = round((active / joins) * 100, 1) if joins else 0.0

        now_ts = int(time.time())
        if seconds is None:
            bucket_seconds = 86400
            max_points = 30
            first = max(cutoff, now_ts - max_points * bucket_seconds)
        elif seconds <= 86400:
            bucket_seconds = 3600
            max_points = 24
            first = now_ts - max_points * bucket_seconds
        else:
            bucket_seconds = 86400
            max_points = max(1, min(30, int(seconds // 86400)))
            first = now_ts - max_points * bucket_seconds

        buckets: dict[int, dict[str, int]] = defaultdict(lambda: {"joins": 0, "leaves": 0})
        for r in rows:
            joined_at = int(r["joined_at"] or 0)
            if joined_at >= first:
                bucket = (joined_at // bucket_seconds) * bucket_seconds
                buckets[bucket]["joins"] += 1
            left_at = int(r["left_at"] or 0)
            if left_at and left_at >= first:
                bucket = (left_at // bucket_seconds) * bucket_seconds
                buckets[bucket]["leaves"] += 1
        series = []
        for i in range(max_points):
            ts = ((first // bucket_seconds) + i) * bucket_seconds
            values = buckets.get(ts, {"joins": 0, "leaves": 0})
            series.append({"ts": ts, **values})

        sources = Counter()
        for r in rows:
            if r["inviter_id"] is not None and r["invite_code"]:
                sources["Invitation attribuée"] += 1
            elif r["invite_code"]:
                sources["Code sans invitant / vanity possible"] += 1
            else:
                sources["Source inconnue"] += 1

        return {
            "joins": joins,
            "leaves": leaves,
            "active": active,
            "fake_active": fake,
            "attributed": attributed,
            "retention": retention,
            "series": series,
            "sources": [{"name": name, "count": count} for name, count in sources.most_common()],
        }

    async def _leaderboard(guild: discord.Guild, hidden: set[int], limit: int = 50) -> list[dict]:
        rows = await bot.db.fetchall(
            "SELECT DISTINCT inviter_id FROM member_invites WHERE guild_id=? AND inviter_id IS NOT NULL "
            "UNION SELECT DISTINCT user_id AS inviter_id FROM invite_bonuses WHERE guild_id=?",
            (guild.id, guild.id),
        )
        output = []
        for row in rows:
            inviter_id = int(row["inviter_id"])
            breakdown = await bot.db.get_invite_breakdown(guild.id, inviter_id)
            total = int(breakdown["total"] or 0)
            active = max(0, total - int(breakdown["left"] or 0))
            latest = await bot.db.fetchone(
                "SELECT MAX(joined_at) AS ts FROM member_invites WHERE guild_id=? AND inviter_id=?",
                (guild.id, inviter_id),
            )
            output.append({
                "member": _member_payload(guild, inviter_id),
                "hidden": inviter_id in hidden,
                "retention": round((active / total) * 100, 1) if total else 0.0,
                "last_invite_at": int(latest["ts"] or 0) if latest else 0,
                **{k: int(v or 0) for k, v in breakdown.items()},
            })
        output.sort(key=lambda item: (item["credited"], item["real"], item["total"]), reverse=True)
        return output[:limit]

    async def analytics(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        hidden = await _hidden_ids(guild.id)
        labels = await _labels(guild.id)
        codes, can_manage_invites = await _active_codes(guild, labels)
        periods = {
            key: await _window_stats(guild.id, seconds)
            for key, seconds in _WINDOWS.items()
        }
        leaderboard = await _leaderboard(guild, hidden)
        return web.json_response({
            "ok": True,
            "periods": periods,
            "leaderboard": leaderboard,
            "codes": codes,
            "can_manage_invites": can_manage_invites,
            "hidden_count": len(hidden),
            "note": (
                "Les statistiques historiques viennent uniquement des arrivées réellement observées par SentriX. "
                "La synchronisation des codes ne reconstruit jamais rétroactivement qui a invité qui."
            ),
        })

    async def invited_list(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        try:
            inviter_id = int(request.match_info["user_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant d'invitant invalide.", 400)
        rows = await bot.db.fetchall(
            "SELECT member_id,invite_code,joined_at,left_at,account_age_days "
            "FROM member_invites WHERE guild_id=? AND inviter_id=? "
            "ORDER BY joined_at DESC LIMIT 250",
            (guild.id, inviter_id),
        )
        items = []
        for row in rows:
            member_id = int(row["member_id"])
            items.append({
                "member": _member_payload(guild, member_id),
                "invite_code": str(row["invite_code"] or ""),
                "joined_at": int(row["joined_at"] or 0),
                "left_at": int(row["left_at"] or 0) or None,
                "account_age_days": row["account_age_days"],
                "suspect_account": (
                    row["account_age_days"] is not None
                    and int(row["account_age_days"]) < FAKE_INVITE_ACCOUNT_AGE_DAYS
                ),
            })
        return web.json_response({"ok": True, "items": items, "total": len(items)})

    async def code_label_put(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        code = str(request.match_info["code"] or "").strip()
        if not code or len(code) > 64:
            return dashboard._json_error("Code d'invitation invalide.", 400)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        label = str((payload or {}).get("label") or "").strip()
        if len(label) > 80:
            return dashboard._json_error("Le label ne peut pas dépasser 80 caractères.", 400)
        await bot.db.execute(
            "INSERT INTO invite_code_meta(guild_id,code,label,last_seen_uses,last_seen_at) "
            "VALUES(?,?,?,0,0) ON CONFLICT(guild_id,code) DO UPDATE SET label=excluded.label",
            (guild.id, code, label),
        )
        return web.json_response({"ok": True, "message": "Label d'invitation enregistré.", "label": label})

    async def hidden_post(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        try:
            user_id = int((payload or {}).get("user_id"))
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de membre invalide.", 400)
        hidden = bool((payload or {}).get("hidden"))
        if hidden:
            await bot.db.execute(
                "INSERT INTO invite_leaderboard_hidden(guild_id,user_id,hidden_by,hidden_at) "
                "VALUES(?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
                "hidden_by=excluded.hidden_by,hidden_at=excluded.hidden_at",
                (guild.id, user_id, int(session["user"]["id"]), int(time.time())),
            )
            message = "Membre masqué du classement."
        else:
            await bot.db.execute(
                "DELETE FROM invite_leaderboard_hidden WHERE guild_id=? AND user_id=?",
                (guild.id, user_id),
            )
            message = "Membre réaffiché dans le classement."
        return web.json_response({"ok": True, "message": message, "hidden": hidden})

    async def sync_post(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return dashboard._json_error(
                "SentriX a besoin de la permission Gérer le serveur pour lire les invitations.",
                403,
            )
        except discord.HTTPException:
            return dashboard._json_error("Discord n'a pas pu fournir les invitations. Réessayez.", 502)

        now_ts = int(time.time())
        for inv in invites:
            await bot.db.execute(
                "INSERT INTO invite_code_meta(guild_id,code,label,last_seen_uses,last_seen_at) "
                "VALUES(?,?,COALESCE((SELECT label FROM invite_code_meta WHERE guild_id=? AND code=?),''),?,?) "
                "ON CONFLICT(guild_id,code) DO UPDATE SET "
                "last_seen_uses=excluded.last_seen_uses,last_seen_at=excluded.last_seen_at",
                (guild.id, str(inv.code), guild.id, str(inv.code), int(inv.uses or 0), now_ts),
            )

        cog = bot.get_cog("Invites") if hasattr(bot, "get_cog") else None
        if cog is not None and hasattr(cog, "cache_guild_invites"):
            await cog.cache_guild_invites(guild)

        return web.json_response({
            "ok": True,
            "message": (
                f"{len(invites)} code(s) synchronisé(s). "
                "Aucune attribution historique de membre n'a été inventée."
            ),
            "count": len(invites),
            "synced_at": now_ts,
        })

    app.router.add_get("/api/guilds/{guild_id}/invites/analytics", analytics)
    app.router.add_get("/api/guilds/{guild_id}/invites/inviters/{user_id}", invited_list)
    app.router.add_put("/api/guilds/{guild_id}/invites/codes/{code}", code_label_put)
    app.router.add_post("/api/guilds/{guild_id}/invites/leaderboard-hidden", hidden_post)
    app.router.add_post("/api/guilds/{guild_id}/invites/sync", sync_post)


__all__ = ["register"]
