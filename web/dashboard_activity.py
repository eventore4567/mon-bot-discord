"""Activité réelle d'un serveur pour la vue d'ensemble du dashboard.

Une seule requête agrégée par table, sur les 14 derniers jours, découpée en
tranches de 24 h glissantes (0 = les dernières 24 h). Rien n'est estimé : ce
sont les lignes que SentriX enregistre déjà (commandes, blocages AutoMod,
sanctions, arrivées, tickets). Le fil d'événements reprend les plus récentes,
avec le nom des membres résolu depuis le cache Discord.
"""
from __future__ import annotations

import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.activity")

DAYS = 14
FEED_LIMIT = 12

#: (clé, table, colonne d'horodatage, filtre SQL supplémentaire)
SERIES = (
    ("commands", "command_logs", "timestamp", ""),
    ("automod", "automod_logs", "timestamp", ""),
    ("sanctions", "sanctions", "created_at", ""),
    ("arrivals", "member_invites", "joined_at", ""),
    ("tickets", "tickets", "created_at", ""),
)

SANCTION_LABELS = {
    "ban": "Bannissement", "tempban": "Bannissement temporaire", "kick": "Expulsion",
    "mute": "Mise en sourdine", "timeout": "Exclusion temporaire", "warn": "Avertissement",
    "unban": "Débannissement", "unmute": "Fin de sourdine",
}


async def _daily(db, table: str, column: str, guild_id: int, now: int) -> list[int]:
    since = now - DAYS * 86400
    counts = [0] * DAYS
    rows = await db.fetchall(
        f"SELECT ({now} - {column}) / 86400 AS bucket, COUNT(*) AS n FROM {table} "
        f"WHERE guild_id = ? AND {column} >= ? AND {column} <= ? GROUP BY bucket",
        (guild_id, since, now),
    )
    for row in rows or ():
        bucket = int(row["bucket"] or 0)
        if 0 <= bucket < DAYS:
            counts[bucket] += int(row["n"] or 0)
    # Index 0 = il y a 13 jours … index 13 = les dernières 24 h.
    return list(reversed(counts))


def _who(guild, user_id) -> dict:
    try:
        member = guild.get_member(int(user_id)) if user_id else None
    except (TypeError, ValueError):
        member = None
    name = getattr(member, "display_name", None)
    avatar = getattr(getattr(member, "display_avatar", None), "url", None)
    return {"id": str(user_id) if user_id else None, "name": name, "avatar_url": str(avatar) if avatar else None}


async def _feed(db, guild) -> list[dict]:
    events: list[dict] = []
    queries = (
        ("sanction", "SELECT action, reason, user_id, moderator_id, created_at AS at FROM sanctions "
                     "WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?"),
        ("automod", "SELECT filter_name, action, reason, user_id, timestamp AS at FROM automod_logs "
                    "WHERE guild_id = ? ORDER BY timestamp DESC LIMIT ?"),
        ("arrival", "SELECT member_id AS user_id, inviter_id, joined_at AS at FROM member_invites "
                    "WHERE guild_id = ? AND joined_at IS NOT NULL ORDER BY joined_at DESC LIMIT ?"),
        ("ticket", "SELECT id, user_id, status, created_at AS at FROM tickets "
                   "WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?"),
    )
    for kind, sql in queries:
        try:
            rows = await db.fetchall(sql, (guild.id, FEED_LIMIT))
        except Exception:
            logger.debug("Fil d'activité : %s illisible guild=%s", kind, guild.id, exc_info=True)
            continue
        for row in rows or ():
            row = dict(row)
            at = int(row.get("at") or 0)
            if not at:
                continue
            item = {"kind": kind, "at": at, "member": _who(guild, row.get("user_id"))}
            if kind == "sanction":
                action = str(row.get("action") or "").casefold()
                item["title"] = SANCTION_LABELS.get(action, action.capitalize() or "Sanction")
                item["detail"] = str(row.get("reason") or "")[:140]
                item["actor"] = _who(guild, row.get("moderator_id"))
            elif kind == "automod":
                item["title"] = "Message bloqué"
                item["detail"] = str(row.get("reason") or row.get("filter_name") or "")[:140]
            elif kind == "arrival":
                item["title"] = "Arrivée"
                inviter = row.get("inviter_id")
                item["actor"] = _who(guild, inviter) if inviter else None
                item["detail"] = ""
            else:
                item["title"] = f"Ticket #{row.get('id')}"
                item["detail"] = "Ouvert" if str(row.get("status") or "") == "ouvert" else "Fermé"
            events.append(item)
    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:FEED_LIMIT]


async def activity_payload(bot, guild) -> dict:
    now = int(time.time())
    series: dict[str, list[int]] = {}
    for key, table, column, _extra in SERIES:
        try:
            series[key] = await _daily(bot.db, table, column, guild.id, now)
        except Exception:
            logger.debug("Activité : série %s illisible guild=%s", key, guild.id, exc_info=True)
            series[key] = [0] * DAYS
    return {
        "ok": True,
        "days": DAYS,
        "generated_at": now,
        "series": series,
        "feed": await _feed(bot.db, guild),
    }


def register(app: web.Application, dashboard) -> None:
    bot = app["bot"]

    async def handle_activity(request: web.Request) -> web.Response:
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        response = web.json_response(await activity_payload(bot, guild))
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return response

    app.router.add_get("/api/guilds/{guild_id}/activity", handle_activity)


__all__ = ["DAYS", "SERIES", "activity_payload", "register"]
