"""Automatisations SentriX Plus exposées au dashboard unique.

Ce module ne crée aucun nouveau moteur. Il adapte les tables et règles déjà utilisées par
cogs.sentrix_plus : Starboard, VoiceHub, sticky messages et annonces programmées.
"""
from __future__ import annotations

import time

import discord
from aiohttp import web

from cogs.sentrix_plus import (
    MAX_SCHEDULE_SECONDS,
    MIN_SCHEDULE_SECONDS,
    VOICE_CATEGORY_NAME,
    VOICE_LOBBY_NAME,
    _parse_delay,
)


async def _ensure_tables(bot) -> None:
    cog = bot.get_cog("SentriXPlus") if hasattr(bot, "get_cog") else None
    ensure = getattr(cog, "_ensure_tables", None)
    if callable(ensure):
        await ensure()
        return
    statements = [
        "CREATE TABLE IF NOT EXISTS sentrix_starboard_config (guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL, threshold INTEGER NOT NULL DEFAULT 3)",
        "CREATE TABLE IF NOT EXISTS sentrix_voicehub_config (guild_id INTEGER PRIMARY KEY, lobby_channel_id INTEGER NOT NULL, category_id INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS sentrix_sticky (channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, content TEXT NOT NULL, message_id INTEGER, every_messages INTEGER NOT NULL DEFAULT 5, counter INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS sentrix_scheduled_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, author_id INTEGER NOT NULL, due_at INTEGER NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending')",
    ]
    for statement in statements:
        await bot.db.execute(statement)


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
        await _ensure_tables(bot)
        return session, guild, None

    async def _payload(request: web.Request) -> dict:
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _text_channel(guild: discord.Guild, value):
        try:
            channel = guild.get_channel(int(value))
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def plus_get(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        star = await bot.db.fetchone(
            "SELECT channel_id,threshold FROM sentrix_starboard_config WHERE guild_id=?",
            (guild.id,),
        )
        voice = await bot.db.fetchone(
            "SELECT lobby_channel_id,category_id FROM sentrix_voicehub_config WHERE guild_id=?",
            (guild.id,),
        )
        sticky = await bot.db.fetchall(
            "SELECT channel_id,content,message_id,every_messages,counter FROM sentrix_sticky WHERE guild_id=? ORDER BY channel_id",
            (guild.id,),
        )
        scheduled = await bot.db.fetchall(
            "SELECT id,channel_id,author_id,due_at,content,created_at,status "
            "FROM sentrix_scheduled_messages WHERE guild_id=? AND status='pending' ORDER BY due_at ASC LIMIT 50",
            (guild.id,),
        )
        return web.json_response({
            "ok": True,
            "starboard": dict(star) if star else None,
            "voicehub": dict(voice) if voice else None,
            "sticky": [dict(row) for row in sticky],
            "scheduled": [dict(row) for row in scheduled],
            "limits": {
                "schedule_min_seconds": MIN_SCHEDULE_SECONDS,
                "schedule_max_seconds": MAX_SCHEDULE_SECONDS,
            },
        })

    async def starboard_put(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        enabled = bool(payload.get("enabled", True))
        if not enabled:
            await bot.db.execute("DELETE FROM sentrix_starboard_config WHERE guild_id=?", (guild.id,))
            return web.json_response({"ok": True, "message": "Starboard désactivé."})
        channel = _text_channel(guild, payload.get("channel_id"))
        if channel is None:
            return dashboard._json_error("Choisissez un salon textuel pour le Starboard.", 400)
        me = guild.me
        if me is not None:
            perms = channel.permissions_for(me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                return dashboard._json_error("SentriX ne peut pas envoyer d'embeds dans ce salon.", 409)
        try:
            threshold = int(payload.get("threshold", 3))
        except (TypeError, ValueError):
            threshold = 3
        threshold = max(2, min(25, threshold))
        await bot.db.execute(
            "INSERT INTO sentrix_starboard_config(guild_id,channel_id,threshold) VALUES(?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id,threshold=excluded.threshold",
            (guild.id, channel.id, threshold),
        )
        return web.json_response({"ok": True, "message": f"Starboard activé dans #{channel.name} à {threshold} étoiles."})

    async def sticky_post(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        action = str(payload.get("action") or "save").strip().lower()
        channel = _text_channel(guild, payload.get("channel_id"))
        if channel is None:
            return dashboard._json_error("Choisissez un salon textuel valide.", 400)

        cog = bot.get_cog("SentriXPlus") if hasattr(bot, "get_cog") else None
        if action in {"delete", "off", "disable"}:
            row = await bot.db.fetchone("SELECT message_id FROM sentrix_sticky WHERE channel_id=? AND guild_id=?", (channel.id, guild.id))
            if row and row["message_id"]:
                try:
                    old = await channel.fetch_message(int(row["message_id"]))
                    await old.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            await bot.db.execute("DELETE FROM sentrix_sticky WHERE channel_id=? AND guild_id=?", (channel.id, guild.id))
            if cog is not None and hasattr(cog, "_no_sticky"):
                cog._no_sticky[int(channel.id)] = True
            return web.json_response({"ok": True, "message": f"Sticky désactivé dans #{channel.name}."})

        content = str(payload.get("content") or "").strip()
        if not content or len(content) > 1700:
            return dashboard._json_error("Le sticky doit contenir entre 1 et 1700 caractères.", 400)
        try:
            every = int(payload.get("every_messages", 5))
        except (TypeError, ValueError):
            every = 5
        every = max(2, min(50, every))
        me = guild.me
        if me is not None:
            perms = channel.permissions_for(me)
            if not (perms.view_channel and perms.send_messages and perms.manage_messages):
                return dashboard._json_error("SentriX doit pouvoir voir, envoyer et gérer les messages dans ce salon.", 409)

        old = await bot.db.fetchone("SELECT message_id FROM sentrix_sticky WHERE channel_id=? AND guild_id=?", (channel.id, guild.id))
        if old and old["message_id"]:
            try:
                previous = await channel.fetch_message(int(old["message_id"]))
                await previous.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        try:
            sent = await channel.send(f"📌 **Information**\n{content}")
        except discord.Forbidden:
            return dashboard._json_error("Discord refuse l'envoi dans ce salon.", 403)
        except discord.HTTPException:
            return dashboard._json_error("Discord n'a pas pu publier le sticky.", 502)
        await bot.db.execute(
            "INSERT INTO sentrix_sticky(channel_id,guild_id,content,message_id,every_messages,counter) VALUES(?,?,?,?,?,0) "
            "ON CONFLICT(channel_id) DO UPDATE SET guild_id=excluded.guild_id,content=excluded.content,message_id=excluded.message_id,every_messages=excluded.every_messages,counter=0",
            (channel.id, guild.id, content, sent.id, every),
        )
        if cog is not None and hasattr(cog, "_no_sticky"):
            cog._no_sticky.pop(int(channel.id), None)
        return web.json_response({"ok": True, "message": f"Sticky actif dans #{channel.name}, tous les {every} messages."})

    async def scheduled_post(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        action = str(payload.get("action") or "create").strip().lower()
        if action in {"cancel", "delete"}:
            try:
                ident = int(payload.get("id"))
            except (TypeError, ValueError):
                return dashboard._json_error("Annonce programmée invalide.", 400)
            row = await bot.db.fetchone(
                "SELECT id FROM sentrix_scheduled_messages WHERE id=? AND guild_id=? AND status='pending'",
                (ident, guild.id),
            )
            if not row:
                return dashboard._json_error("Cette annonce n'est plus en attente.", 404)
            await bot.db.execute("DELETE FROM sentrix_scheduled_messages WHERE id=? AND guild_id=?", (ident, guild.id))
            return web.json_response({"ok": True, "message": f"Annonce #{ident} annulée."})

        channel = _text_channel(guild, payload.get("channel_id"))
        if channel is None:
            return dashboard._json_error("Choisissez un salon textuel valide.", 400)
        content = str(payload.get("content") or "").strip()
        if not content or len(content) > 1900:
            return dashboard._json_error("Le message doit contenir entre 1 et 1900 caractères.", 400)
        delay = str(payload.get("delay") or "").strip()
        seconds = _parse_delay(delay)
        if seconds is None:
            return dashboard._json_error("Durée invalide. Exemples : 10m, 2h, 1d (1 min à 30 jours).", 400)
        me = guild.me
        if me is not None:
            perms = channel.permissions_for(me)
            if not (perms.view_channel and perms.send_messages):
                return dashboard._json_error("SentriX ne peut pas envoyer de messages dans ce salon.", 409)
        now_ts = int(time.time())
        due_at = now_ts + seconds
        author_id = int(session["user"]["id"])
        cur = await bot.db.execute(
            "INSERT INTO sentrix_scheduled_messages(guild_id,channel_id,author_id,due_at,content,created_at,status) "
            "VALUES(?,?,?,?,?,?,'pending')",
            (guild.id, channel.id, author_id, due_at, content, now_ts),
        )
        return web.json_response({
            "ok": True,
            "message": f"Annonce #{int(cur.lastrowid)} programmée dans #{channel.name}.",
            "id": int(cur.lastrowid),
            "due_at": due_at,
        })

    async def voicehub_put(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        action = str(payload.get("action") or "configure").strip().lower()
        if action in {"off", "disable", "delete"}:
            await bot.db.execute("DELETE FROM sentrix_voicehub_config WHERE guild_id=?", (guild.id,))
            return web.json_response({"ok": True, "message": "VoiceHub désactivé. Les vocaux temporaires existants ne sont pas supprimés."})

        me = guild.me
        if me is None or not (me.guild_permissions.manage_channels and me.guild_permissions.move_members):
            return dashboard._json_error("SentriX a besoin de Gérer les salons et Déplacer des membres.", 403)

        if action == "create":
            category = discord.utils.get(guild.categories, name=VOICE_CATEGORY_NAME)
            if category is None:
                category = await guild.create_category(VOICE_CATEGORY_NAME, reason="SentriX VoiceHub via dashboard")
            lobby = discord.utils.get(category.voice_channels, name=VOICE_LOBBY_NAME)
            if lobby is None:
                lobby = await guild.create_voice_channel(VOICE_LOBBY_NAME, category=category, reason="SentriX VoiceHub via dashboard")
        else:
            try:
                lobby = guild.get_channel(int(payload.get("lobby_channel_id") or 0))
                category = guild.get_channel(int(payload.get("category_id") or 0))
            except (TypeError, ValueError):
                lobby = category = None
            if not isinstance(lobby, discord.VoiceChannel):
                return dashboard._json_error("Choisissez un salon vocal d'accueil valide.", 400)
            if not isinstance(category, discord.CategoryChannel):
                return dashboard._json_error("Choisissez une catégorie Discord valide.", 400)

        await bot.db.execute(
            "INSERT INTO sentrix_voicehub_config(guild_id,lobby_channel_id,category_id) VALUES(?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET lobby_channel_id=excluded.lobby_channel_id,category_id=excluded.category_id",
            (guild.id, lobby.id, category.id),
        )
        return web.json_response({
            "ok": True,
            "message": f"VoiceHub actif : rejoignez {lobby.name} pour créer un vocal temporaire.",
            "lobby_channel_id": str(lobby.id),
            "category_id": str(category.id),
        })

    app.router.add_get("/api/guilds/{guild_id}/automation/plus", plus_get)
    app.router.add_put("/api/guilds/{guild_id}/automation/starboard", starboard_put)
    app.router.add_post("/api/guilds/{guild_id}/automation/sticky", sticky_post)
    app.router.add_post("/api/guilds/{guild_id}/automation/scheduled", scheduled_post)
    app.router.add_put("/api/guilds/{guild_id}/automation/voicehub", voicehub_put)


__all__ = ["register"]
