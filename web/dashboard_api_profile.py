"""Profil communautaire SentriX éditable depuis le dashboard.

Les données restent dans la table historique `profiles` utilisée par +profile :
bio, anniversaire et fond de carte. Les statistiques sont lues depuis ProfileService.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import discord
from aiohttp import web

from services import profile as profile_service


_BIRTHDAY = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{4})?)$")


def _https_url(value: str) -> bool:
    if not value:
        return True
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None


def register(app: web.Application, dashboard) -> None:
    bot = app["bot"]

    async def _guard(request: web.Request, *, write: bool = False):
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return None, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return None, None, None, error
        if write:
            csrf_error = dashboard._require_csrf(request, session)
            if csrf_error:
                return None, None, None, csrf_error
        user_id = int(session["user"]["id"])
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None, None, None, dashboard._json_error(
                    "Votre compte Discord n'est plus présent sur ce serveur.", 403
                )
        return session, guild, member, None

    async def _payload(request: web.Request) -> dict:
        try:
            value = await request.json()
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    async def profile_get(request: web.Request):
        _session, guild, member, error = await _guard(request)
        if error:
            return error
        await bot.db.ensure_profile(guild.id, member.id)
        row = await bot.db.fetchone(
            "SELECT bio,background,reputation,birthday,married_to "
            "FROM profiles WHERE guild_id=? AND user_id=?",
            (guild.id, member.id),
        )
        data = dict(row) if row else {}
        snapshot = await profile_service.build_snapshot(bot, guild, member)
        stats = snapshot.get("stats") or {}
        progression = snapshot.get("progression") or {}
        badges = profile_service.compute_badges(member, stats, progression)
        return web.json_response({
            "ok": True,
            "member": {
                "id": str(member.id),
                "display_name": member.display_name,
                "username": member.name,
                "avatar_url": str(member.display_avatar.url),
            },
            "profile": {
                "bio": data.get("bio") or "",
                "birthday": data.get("birthday") or "",
                "background": data.get("background") or "",
                "reputation": int(data.get("reputation") or 0),
                "married_to": str(data["married_to"]) if data.get("married_to") else None,
            },
            "stats": {
                "level": int(stats.get("current_level") or 0),
                "xp": int(stats.get("total_xp") or 0),
                "messages": int(stats.get("message_count") or 0),
                "voice_time": int(stats.get("voice_time") or 0),
                "wallet": int(stats.get("wallet") or 0),
                "bank": int(stats.get("bank") or 0),
                "season_level": int(progression.get("season_level") or 0),
                "season_xp": int(progression.get("season_xp") or 0),
                "daily_streak": int(progression.get("daily_streak") or 0),
            },
            "badges": badges,
        })

    async def profile_put(request: web.Request):
        _session, guild, member, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        bio = str(payload.get("bio") or "").strip()
        birthday = str(payload.get("birthday") or "").strip()
        background = str(payload.get("background") or "").strip()

        if len(bio) > 500:
            return dashboard._json_error("La bio ne peut pas dépasser 500 caractères.", 400)
        if birthday and (len(birthday) > 20 or not _BIRTHDAY.fullmatch(birthday)):
            return dashboard._json_error(
                "Anniversaire invalide. Utilisez AAAA-MM-JJ ou JJ/MM.", 400
            )
        if len(background) > 500 or not _https_url(background):
            return dashboard._json_error(
                "Le fond doit être vide ou utiliser une URL HTTPS valide.", 400
            )

        await bot.db.ensure_profile(guild.id, member.id)
        await bot.db.execute(
            "UPDATE profiles SET bio=?,birthday=?,background=? WHERE guild_id=? AND user_id=?",
            (bio or None, birthday or None, background or None, guild.id, member.id),
        )
        return web.json_response({
            "ok": True,
            "message": "Profil SentriX enregistré.",
            "profile": {"bio": bio, "birthday": birthday, "background": background},
        })

    app.router.add_get("/api/guilds/{guild_id}/profile/me", profile_get)
    app.router.add_put("/api/guilds/{guild_id}/profile/me", profile_put)


__all__ = ["register"]
