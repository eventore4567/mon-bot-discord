"""Contrôle musique du dashboard SentriX.

Cette API pilote le Cog Music réellement chargé : aucun lecteur parallèle et aucune
file secondaire. Les actions du dashboard utilisent donc exactement la même voix,
la même file, le même moteur multi-provider et les mêmes playlists persistantes que
/music sur Discord.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any

import discord
from aiohttp import web

from sentrix_music_playlists_v108 import (
    decode_playlist_items,
    normalize_playlist_name,
)
from utils.music import MusicEngineError

_LOCKS: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_MAX_PLAYLISTS = 20
_MAX_TRACKS = 1000


def _track_payload(track, *, position: int | None = None) -> dict[str, Any]:
    if track is None:
        return {}
    data = {
        "title": str(getattr(track, "title", "") or "Titre inconnu"),
        "artist": getattr(track, "artist", None),
        "album": getattr(track, "album", None),
        "duration": getattr(track, "duration", None),
        "thumbnail": getattr(track, "thumbnail", None),
        "original_url": getattr(track, "original_url", None),
        "provider": str(getattr(track, "provider", "") or "unknown"),
        "playback_provider": getattr(track, "playback_provider", None),
        "is_live": bool(getattr(track, "is_live", False)),
        "requested_by": str(getattr(track, "requested_by", "") or "") or None,
    }
    if position is not None:
        data["position"] = position
    return data


def _playlist_item(track, query: str) -> dict[str, Any]:
    return {
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "duration": track.duration,
        "thumbnail": track.thumbnail,
        "original_url": track.original_url,
        "provider": track.provider,
        "playback_provider": track.playback_provider,
        "is_live": bool(track.is_live),
        "query": str(query or "")[:1000],
    }


def _item_track(item: dict[str, Any], requested_by: int):
    from utils.music import Track

    return Track(
        title=str(item.get("title") or "Titre inconnu"),
        artist=item.get("artist"),
        album=item.get("album"),
        duration=item.get("duration"),
        thumbnail=item.get("thumbnail"),
        original_url=item.get("original_url"),
        provider=str(item.get("provider") or "unknown"),
        playable_url=None,
        playback_provider=item.get("playback_provider"),
        is_live=bool(item.get("is_live")),
        requested_by=requested_by,
    )


async def _ensure_playlist_schema(bot) -> None:
    await bot.db.execute(
        "CREATE TABLE IF NOT EXISTS music_playlists ("
        "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, name_key TEXT NOT NULL, "
        "name TEXT NOT NULL, items_json TEXT NOT NULL DEFAULT '[]', "
        "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, "
        "PRIMARY KEY (guild_id, user_id, name_key))"
    )
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_music_playlists_owner "
        "ON music_playlists (guild_id, user_id, updated_at DESC)"
    )


async def _playlist_rows(bot, guild_id: int, user_id: int):
    await _ensure_playlist_schema(bot)
    return await bot.db.fetchall(
        "SELECT name_key,name,items_json,created_at,updated_at "
        "FROM music_playlists WHERE guild_id=? AND user_id=? ORDER BY updated_at DESC",
        (guild_id, user_id),
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
        return session, guild, None

    async def _payload(request: web.Request) -> dict:
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _music():
        return bot.get_cog("Music") if hasattr(bot, "get_cog") else None

    def _voice_channel(guild: discord.Guild, value) -> discord.VoiceChannel | discord.StageChannel | None:
        try:
            channel = guild.get_channel(int(value))
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) else None

    async def _connect_to(guild: discord.Guild, channel, *, text_channel=None):
        music = _music()
        if music is None:
            raise RuntimeError("Le module Musique n’est pas chargé sur cette instance.")
        me = guild.me
        if me is None:
            raise RuntimeError("SentriX n’est pas encore prêt sur ce serveur.")
        perms = channel.permissions_for(me)
        if not perms.view_channel or not perms.connect:
            raise PermissionError("SentriX n’a pas la permission de voir ou rejoindre ce salon vocal.")
        if isinstance(channel, discord.VoiceChannel) and not perms.speak:
            raise PermissionError("SentriX n’a pas la permission de parler dans ce salon vocal.")

        queue = music.get_queue(guild.id)
        voice = queue.voice_client or guild.voice_client
        if voice and voice.is_connected():
            if voice.channel.id != channel.id:
                await voice.move_to(channel)
        else:
            voice = await channel.connect()
        queue.voice_client = voice
        if text_channel is not None:
            queue.text_channel = text_channel
        cancel = getattr(music, "_cancel_disconnect", None)
        if callable(cancel):
            cancel(queue)
        return queue

    async def status(request: web.Request):
        session, guild, error = await _guard(request)
        if error:
            return error
        music = _music()
        if music is None:
            return dashboard._json_error("Le module Musique n’est pas chargé.", 503)
        queue = music.get_queue(guild.id)
        voice = queue.voice_client or guild.voice_client
        connected = bool(voice and voice.is_connected())
        current = _track_payload(queue.current)
        if current:
            current["position_seconds"] = max(0, int(queue.position_seconds()))
        user_id = int(session["user"]["id"])
        rows = await _playlist_rows(bot, guild.id, user_id)
        playlists = []
        for row in rows:
            items = decode_playlist_items(row["items_json"])
            playlists.append({
                "key": str(row["name_key"]),
                "name": str(row["name"]),
                "count": len(items),
                "updated_at": int(row["updated_at"] or 0),
                "tracks": [
                    {
                        "position": i,
                        "title": str(item.get("title") or "Titre inconnu"),
                        "artist": item.get("artist"),
                        "duration": item.get("duration"),
                        "thumbnail": item.get("thumbnail"),
                        "original_url": item.get("original_url"),
                    }
                    for i, item in enumerate(items[:100], 1)
                ],
                "truncated": max(0, len(items) - 100),
            })

        voice_channels = []
        me = guild.me
        for channel in sorted(
            [c for c in guild.channels if isinstance(c, (discord.VoiceChannel, discord.StageChannel))],
            key=lambda c: (getattr(c.category, "position", -1), c.position),
        ):
            perms = channel.permissions_for(me) if me else None
            voice_channels.append({
                "id": str(channel.id),
                "name": channel.name,
                "category": channel.category.name if channel.category else None,
                "members": len(channel.members),
                "can_connect": bool(perms and perms.view_channel and perms.connect),
                "can_speak": bool(perms and (not isinstance(channel, discord.VoiceChannel) or perms.speak)),
            })

        return web.json_response({
            "ok": True,
            "connected": connected,
            "voice_channel_id": str(voice.channel.id) if connected else None,
            "voice_channel_name": voice.channel.name if connected else None,
            "playing": bool(voice and voice.is_playing()),
            "paused": bool(voice and voice.is_paused()),
            "volume": round(queue.volume * 100),
            "loop": "track" if queue.loop_track else ("queue" if queue.loop_queue else "off"),
            "autoplay": bool(queue.autoplay),
            "current": current or None,
            "queue": [_track_payload(track, position=i) for i, track in enumerate(queue.tracks[:100], 1)],
            "queue_total": len(queue.tracks),
            "queue_truncated": max(0, len(queue.tracks) - 100),
            "history_count": len(queue.history),
            "voice_channels": voice_channels,
            "playlists": playlists,
        })

    async def connect(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        channel = _voice_channel(guild, payload.get("channel_id"))
        if channel is None:
            return dashboard._json_error("Choisissez un salon vocal valide.", 400)
        try:
            queue = await _connect_to(guild, channel)
        except PermissionError as exc:
            return dashboard._json_error(str(exc), 403)
        except (RuntimeError, discord.Forbidden, discord.HTTPException) as exc:
            return dashboard._json_error(str(exc) or "Connexion vocale impossible.", 409)
        return web.json_response({
            "ok": True,
            "message": f"SentriX a rejoint {channel.name}.",
            "channel_id": str(channel.id),
            "volume": round(queue.volume * 100),
        })

    async def play(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        query = str(payload.get("query") or "").strip()
        if not query:
            return dashboard._json_error("Entrez un titre, un artiste ou un lien.", 400)
        if len(query) > 1000:
            return dashboard._json_error("La recherche est trop longue.", 400)

        music = _music()
        if music is None:
            return dashboard._json_error("Le module Musique n’est pas chargé.", 503)

        async with _LOCKS[guild.id]:
            queue = music.get_queue(guild.id)
            requested_channel = payload.get("channel_id")
            if requested_channel:
                channel = _voice_channel(guild, requested_channel)
                if channel is None:
                    return dashboard._json_error("Le salon vocal sélectionné n’existe plus.", 400)
                try:
                    queue = await _connect_to(guild, channel)
                except PermissionError as exc:
                    return dashboard._json_error(str(exc), 403)
                except (RuntimeError, discord.Forbidden, discord.HTTPException) as exc:
                    return dashboard._json_error(str(exc) or "Connexion vocale impossible.", 409)
            elif not (queue.voice_client and queue.voice_client.is_connected()):
                return dashboard._json_error("Choisissez d’abord le salon vocal que SentriX doit rejoindre.", 409)

            try:
                resolved = await music.manager.resolve(query, requested_by=int(session["user"]["id"]))
            except MusicEngineError as exc:
                title, description = music._classify_engine_error(exc) if hasattr(music, "_classify_engine_error") else ("Lecture impossible", str(exc))
                return dashboard._json_error(description or title, 404)
            except Exception:
                return dashboard._json_error("SentriX n’a pas pu résoudre cette musique.", 502)

            if not resolved.tracks:
                return dashboard._json_error("Aucun titre jouable n’a été trouvé.", 404)
            queue.tracks.extend(resolved.tracks)
            started_now = False
            voice = queue.voice_client
            if voice and not (voice.is_playing() or voice.is_paused()) and not queue.current:
                await music._advance(queue)
                started_now = queue.current is not None

        return web.json_response({
            "ok": True,
            "message": (
                f"Lecture démarrée : {queue.current.display_title()}."
                if started_now and queue.current
                else f"{len(resolved.tracks)} titre(s) ajouté(s) à la file."
            ),
            "added": len(resolved.tracks),
            "playlist": bool(resolved.is_playlist),
            "skipped": len(resolved.skipped),
        })

    async def control(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        action = str(payload.get("action") or "").strip().lower()
        music = _music()
        if music is None:
            return dashboard._json_error("Le module Musique n’est pas chargé.", 503)

        async with _LOCKS[guild.id]:
            queue = music.get_queue(guild.id)
            voice = queue.voice_client or guild.voice_client
            if voice is not None:
                queue.voice_client = voice

            if action == "pause":
                if not voice or not voice.is_playing():
                    return dashboard._json_error("Aucune musique n’est en lecture.", 409)
                voice.pause()
                message = "Musique mise en pause."
            elif action == "resume":
                if not voice or not voice.is_paused():
                    return dashboard._json_error("La musique n’est pas en pause.", 409)
                voice.resume()
                message = "Lecture reprise."
            elif action == "skip":
                if not voice or not (voice.is_playing() or voice.is_paused()):
                    return dashboard._json_error("Aucune musique à passer.", 409)
                queue.loop_track = False
                voice.stop()
                message = "Passage au titre suivant."
            elif action == "previous":
                if not queue.history:
                    return dashboard._json_error("Aucun titre précédent dans cette session.", 409)
                previous = queue.history.pop()
                if queue.current:
                    queue.tracks.insert(0, queue.current)
                queue.tracks.insert(0, previous)
                queue.loop_track = False
                if voice and (voice.is_playing() or voice.is_paused()):
                    voice.stop()
                else:
                    await music._advance(queue)
                message = f"Retour vers {previous.display_title()}."
            elif action == "stop":
                queue.tracks.clear()
                queue.loop_track = False
                queue.loop_queue = False
                queue.autoplay = False
                if voice and (voice.is_playing() or voice.is_paused()):
                    voice.stop()
                queue.current = None
                message = "Lecture arrêtée et file vidée."
            elif action == "clear":
                queue.tracks.clear()
                message = "File d’attente vidée."
            elif action == "shuffle":
                import random
                random.shuffle(queue.tracks)
                message = "File d’attente mélangée."
            elif action == "leave":
                if not voice or not voice.is_connected():
                    return dashboard._json_error("SentriX n’est dans aucun salon vocal.", 409)
                cancel = getattr(music, "_cancel_disconnect", None)
                if callable(cancel):
                    cancel(queue)
                await voice.disconnect()
                queue.voice_client = None
                queue.current = None
                queue.tracks.clear()
                queue.history.clear()
                message = "SentriX a quitté le salon vocal."
            elif action == "volume":
                try:
                    level = max(0, min(100, int(payload.get("value"))))
                except (TypeError, ValueError):
                    return dashboard._json_error("Le volume doit être compris entre 0 et 100.", 400)
                queue.volume = level / 100
                if voice and getattr(voice, "source", None) is not None and hasattr(voice.source, "volume"):
                    voice.source.volume = queue.volume
                message = f"Volume réglé sur {level}%."
            elif action == "loop":
                mode = str(payload.get("value") or "off").lower()
                if mode not in {"off", "track", "queue"}:
                    return dashboard._json_error("Mode de répétition invalide.", 400)
                queue.loop_track = mode == "track"
                queue.loop_queue = mode == "queue"
                message = "Répétition mise à jour."
            elif action == "autoplay":
                queue.autoplay = bool(payload.get("value"))
                message = f"Autoplay {'activé' if queue.autoplay else 'désactivé'}."
            elif action == "remove":
                try:
                    position = int(payload.get("position"))
                except (TypeError, ValueError):
                    return dashboard._json_error("Position invalide.", 400)
                if position < 1 or position > len(queue.tracks):
                    return dashboard._json_error("Ce titre n’est plus dans la file.", 409)
                removed = queue.tracks.pop(position - 1)
                message = f"{removed.display_title()} retiré de la file."
            elif action == "seek":
                try:
                    seconds = max(0, min(36000, int(payload.get("value"))))
                except (TypeError, ValueError):
                    return dashboard._json_error("Position invalide.", 400)
                if not queue.current or not voice:
                    return dashboard._json_error("Aucune musique en cours.", 409)
                if queue.current.duration and seconds > queue.current.duration:
                    return dashboard._json_error("Cette position dépasse la durée du titre.", 409)
                track = queue.current
                if voice.is_playing() or voice.is_paused():
                    voice.stop()
                started = await music._play_track(queue, track, seek_seconds=float(seconds))
                if not started:
                    return dashboard._json_error("La source de cette piste n’est plus disponible.", 409)
                message = f"Lecture déplacée à {seconds} s."
            else:
                return dashboard._json_error("Action du lecteur inconnue.", 400)

        return web.json_response({"ok": True, "message": message})

    async def playlist_create(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        try:
            display, key = normalize_playlist_name(str(payload.get("name") or ""))
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)
        user_id = int(session["user"]["id"])
        await _ensure_playlist_schema(bot)
        rows = await bot.db.fetchall(
            "SELECT name_key FROM music_playlists WHERE guild_id=? AND user_id=?",
            (guild.id, user_id),
        )
        if any(str(row["name_key"]) == key for row in rows):
            return dashboard._json_error("Vous avez déjà une playlist avec ce nom.", 409)
        if len(rows) >= _MAX_PLAYLISTS:
            return dashboard._json_error(f"Limite atteinte : {_MAX_PLAYLISTS} playlists par serveur.", 409)
        now = int(time.time())
        await bot.db.execute(
            "INSERT INTO music_playlists (guild_id,user_id,name_key,name,items_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (guild.id, user_id, key, display, "[]", now, now),
        )
        return web.json_response({"ok": True, "message": f"Playlist {display} créée."})

    async def playlist_add(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        try:
            _display, key = normalize_playlist_name(str(payload.get("name") or ""))
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)
        query = str(payload.get("query") or "").strip()
        if not query:
            return dashboard._json_error("Entrez un titre ou un lien à ajouter.", 400)
        music = _music()
        if music is None:
            return dashboard._json_error("Le module Musique n’est pas chargé.", 503)
        user_id = int(session["user"]["id"])
        await _ensure_playlist_schema(bot)
        row = await bot.db.fetchone(
            "SELECT name,items_json FROM music_playlists WHERE guild_id=? AND user_id=? AND name_key=?",
            (guild.id, user_id, key),
        )
        if row is None:
            return dashboard._json_error("Cette playlist n’existe plus.", 404)
        try:
            resolved = await music.manager.resolve(query, requested_by=user_id)
        except MusicEngineError:
            return dashboard._json_error("Impossible de trouver ce titre ou cette playlist.", 404)
        items = decode_playlist_items(row["items_json"])
        room = max(0, _MAX_TRACKS - len(items))
        if room <= 0:
            return dashboard._json_error("Cette playlist contient déjà 1000 titres.", 409)
        selected = resolved.tracks[:room]
        items.extend(_playlist_item(track, query) for track in selected)
        await bot.db.execute(
            "UPDATE music_playlists SET items_json=?,updated_at=? "
            "WHERE guild_id=? AND user_id=? AND name_key=?",
            (json.dumps(items, ensure_ascii=False, separators=(",", ":")), int(time.time()), guild.id, user_id, key),
        )
        return web.json_response({
            "ok": True,
            "message": f"{len(selected)} titre(s) ajouté(s) à {row['name']}.",
            "added": len(selected),
        })

    async def playlist_play(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        try:
            _display, key = normalize_playlist_name(str(payload.get("name") or ""))
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)
        user_id = int(session["user"]["id"])
        await _ensure_playlist_schema(bot)
        row = await bot.db.fetchone(
            "SELECT name,items_json FROM music_playlists WHERE guild_id=? AND user_id=? AND name_key=?",
            (guild.id, user_id, key),
        )
        if row is None:
            return dashboard._json_error("Cette playlist n’existe plus.", 404)
        items = decode_playlist_items(row["items_json"])
        if not items:
            return dashboard._json_error("Cette playlist est vide.", 409)

        music = _music()
        if music is None:
            return dashboard._json_error("Le module Musique n’est pas chargé.", 503)
        async with _LOCKS[guild.id]:
            queue = music.get_queue(guild.id)
            requested_channel = payload.get("channel_id")
            if requested_channel:
                channel = _voice_channel(guild, requested_channel)
                if channel is None:
                    return dashboard._json_error("Le salon vocal sélectionné n’existe plus.", 400)
                try:
                    queue = await _connect_to(guild, channel)
                except PermissionError as exc:
                    return dashboard._json_error(str(exc), 403)
                except (RuntimeError, discord.Forbidden, discord.HTTPException) as exc:
                    return dashboard._json_error(str(exc) or "Connexion vocale impossible.", 409)
            elif not (queue.voice_client and queue.voice_client.is_connected()):
                return dashboard._json_error("Choisissez le salon vocal avant de lancer la playlist.", 409)
            tracks = [_item_track(item, user_id) for item in items]
            queue.tracks.extend(tracks)
            voice = queue.voice_client
            started = False
            if voice and not (voice.is_playing() or voice.is_paused()) and not queue.current:
                await music._advance(queue)
                started = queue.current is not None
        return web.json_response({
            "ok": True,
            "message": (
                f"Playlist {row['name']} lancée ({len(tracks)} titres)."
                if started else f"Playlist {row['name']} ajoutée à la file ({len(tracks)} titres)."
            ),
        })

    async def playlist_delete(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        try:
            display, key = normalize_playlist_name(str(payload.get("name") or ""))
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)
        user_id = int(session["user"]["id"])
        await _ensure_playlist_schema(bot)
        row = await bot.db.fetchone(
            "SELECT name FROM music_playlists WHERE guild_id=? AND user_id=? AND name_key=?",
            (guild.id, user_id, key),
        )
        if row is None:
            return dashboard._json_error("Cette playlist n’existe plus.", 404)
        await bot.db.execute(
            "DELETE FROM music_playlists WHERE guild_id=? AND user_id=? AND name_key=?",
            (guild.id, user_id, key),
        )
        return web.json_response({"ok": True, "message": f"Playlist {display} supprimée."})

    app.router.add_get("/api/guilds/{guild_id}/music", status)
    app.router.add_post("/api/guilds/{guild_id}/music/connect", connect)
    app.router.add_post("/api/guilds/{guild_id}/music/play", play)
    app.router.add_post("/api/guilds/{guild_id}/music/control", control)
    app.router.add_post("/api/guilds/{guild_id}/music/playlists/create", playlist_create)
    app.router.add_post("/api/guilds/{guild_id}/music/playlists/add", playlist_add)
    app.router.add_post("/api/guilds/{guild_id}/music/playlists/play", playlist_play)
    app.router.add_delete("/api/guilds/{guild_id}/music/playlists", playlist_delete)


__all__ = ["register"]
