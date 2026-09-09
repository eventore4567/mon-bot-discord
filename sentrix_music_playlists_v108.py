"""SentriX V108 — playlists personnelles persistantes + ping de fin de musique.

Le module se branche sur le Cog ``Music`` déjà chargé. Il n'ajoute aucune nouvelle
racine slash : les commandes sont attachées sous ``/music playlist`` afin de rester
sous la politique publique de la racine ``music``.

Les playlists sont stockées dans SQLite et suivent donc le même mécanisme de snapshot
PostgreSQL que le reste des données SentriX. Une playlist peut aussi importer en une
fois les pistes renvoyées par un lien de playlist pris en charge par le moteur
multi-provider.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import types
import unicodedata
from collections import defaultdict
from typing import Any

import discord
from discord.ext import commands

from utils import sentrix_panels as panels
from utils.music import MusicEngineError, Track

logger = logging.getLogger("bot.music-playlists-v108")

_MAX_PLAYLISTS = 20
_MAX_TRACKS = 100
_MAX_NAME = 40
_MAX_QUERY = 1000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS music_playlists (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    name_key TEXT NOT NULL,
    name TEXT NOT NULL,
    items_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, name_key)
);
CREATE INDEX IF NOT EXISTS idx_music_playlists_owner
ON music_playlists (guild_id, user_id, updated_at DESC);
"""

_LOCKS: dict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)


def normalize_playlist_name(value: str) -> tuple[str, str]:
    """Retourne ``(nom_affiché, clé)`` ou lève ValueError si le nom est invalide."""
    display = unicodedata.normalize("NFKC", str(value or ""))
    display = " ".join(display.replace("\n", " ").replace("\r", " ").split()).strip()
    if not display:
        raise ValueError("Le nom de la playlist ne peut pas être vide.")
    if len(display) > _MAX_NAME:
        raise ValueError(f"Le nom est trop long ({_MAX_NAME} caractères maximum).")
    if any(ord(ch) < 32 for ch in display):
        raise ValueError("Le nom contient un caractère non autorisé.")
    return display, display.casefold()


def decode_playlist_items(raw: str | None) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    clean: list[dict[str, Any]] = []
    for item in value[:_MAX_TRACKS]:
        if isinstance(item, dict) and item.get("title"):
            clean.append(item)
    return clean


def _track_to_item(track: Track, original_query: str) -> dict[str, Any]:
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
        "query": str(original_query or "")[:_MAX_QUERY],
    }


def _item_to_track(item: dict[str, Any], requested_by: int) -> Track:
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


def _display_item(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Titre inconnu")
    artist = str(item.get("artist") or "").strip()
    if artist and artist.casefold() not in title.casefold():
        return f"{artist} — {title}"
    return title


async def _send(music_cog, ctx: commands.Context, title: str, description: str, *, kind: str = "primary"):
    embed = await music_cog._embed(ctx.guild.id, title=title, description=description, kind=kind)
    return await panels.envoyer(ctx, panels.depuis_embed(embed))


async def _fetch_playlist(bot, guild_id: int, user_id: int, name_key: str):
    return await bot.db.fetchone(
        "SELECT * FROM music_playlists WHERE guild_id = ? AND user_id = ? AND name_key = ?",
        (guild_id, user_id, name_key),
    )


async def _save_items(bot, guild_id: int, user_id: int, name_key: str, items: list[dict[str, Any]]) -> None:
    await bot.db.execute(
        "UPDATE music_playlists SET items_json = ?, updated_at = ? "
        "WHERE guild_id = ? AND user_id = ? AND name_key = ?",
        (json.dumps(items, ensure_ascii=False, separators=(",", ":")), int(time.time()), guild_id, user_id, name_key),
    )


async def _install_schema(bot) -> None:
    # Database.execute() n'accepte qu'une instruction à la fois ; on garde les deux
    # requêtes explicites pour rester compatible avec la couche aiosqlite existante.
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


def _install_finish_ping(music_cog) -> None:
    if getattr(music_cog, "_sentrix_finish_ping_v108", False):
        return
    original = music_cog._on_track_finished

    async def on_track_finished_with_ping(self, queue):
        finished = queue.current
        requester_id = getattr(finished, "requested_by", None) if finished else None
        text_channel = queue.text_channel
        await original(queue)

        # On ping uniquement lorsque la file est réellement terminée. Tant qu'une
        # piste suivante a démarré (ou qu'autoplay en a trouvé une), aucun ping.
        if finished is None or queue.current is not None or not requester_id or text_channel is None:
            return
        try:
            await text_channel.send(
                f"<@{requester_id}> la musique est terminée et la file d'attente est vide.",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            logger.info("music finish ping -> guild=%s user=%s", queue.guild_id, requester_id)
        except (discord.HTTPException, discord.Forbidden):
            logger.warning("music finish ping impossible -> guild=%s user=%s", queue.guild_id, requester_id)

    music_cog._on_track_finished = types.MethodType(on_track_finished_with_ping, music_cog)
    music_cog._sentrix_finish_ping_v108 = True


def _install_playlist_group(bot, music_cog) -> None:
    if getattr(music_cog, "_sentrix_playlists_v108", False):
        return

    music_root = bot.get_command("music")
    if not isinstance(music_root, commands.Group):
        raise RuntimeError("La racine +music est introuvable ou n'est pas un groupe")
    if music_root.get_command("playlist") is not None:
        logger.warning("V108: sous-groupe music playlist déjà présent, installation ignorée.")
        music_cog._sentrix_playlists_v108 = True
        return

    @commands.hybrid_group(name="playlist", description="Créer et gérer vos playlists SentriX.")
    async def playlist(ctx: commands.Context):
        if ctx.guild is None:
            return
        if ctx.invoked_subcommand is None:
            await _send(
                music_cog,
                ctx,
                "Playlists",
                "Utilisez `/music playlist list` pour voir vos playlists ou "
                "`/music playlist create <nom>` pour en créer une.",
            )

    @playlist.command(name="create", description="Créer une playlist personnelle.")
    async def playlist_create(ctx: commands.Context, *, nom: str):
        if ctx.guild is None:
            return
        try:
            display, key = normalize_playlist_name(nom)
        except ValueError as exc:
            return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")
        lock = _LOCKS[(ctx.guild.id, ctx.author.id)]
        async with lock:
            existing = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
            if existing:
                return await _send(music_cog, ctx, "Playlist existante", f"Vous avez déjà une playlist **{display}**.", kind="danger")
            row = await bot.db.fetchone(
                "SELECT COUNT(*) AS c FROM music_playlists WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, ctx.author.id),
            )
            if row and int(row["c"]) >= _MAX_PLAYLISTS:
                return await _send(music_cog, ctx, "Limite atteinte", f"Vous pouvez avoir jusqu'à **{_MAX_PLAYLISTS} playlists** par serveur.", kind="danger")
            now = int(time.time())
            await bot.db.execute(
                "INSERT INTO music_playlists (guild_id, user_id, name_key, name, items_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '[]', ?, ?)",
                (ctx.guild.id, ctx.author.id, key, display, now, now),
            )
        await _send(music_cog, ctx, "Playlist créée", f"La playlist **{display}** est prête.", kind="success")

    @playlist.command(name="add", description="Ajouter un titre ou importer un lien de playlist.")
    async def playlist_add(ctx: commands.Context, nom: str, *, recherche: str):
        if ctx.guild is None:
            return
        try:
            display, key = normalize_playlist_name(nom)
        except ValueError as exc:
            return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.defer()
        try:
            resolved = await music_cog.manager.resolve(recherche, requested_by=ctx.author.id)
        except MusicEngineError as exc:
            return await panels.envoyer(ctx, panels.depuis_embed(await music_cog._error_embed(ctx.guild.id, exc)))

        lock = _LOCKS[(ctx.guild.id, ctx.author.id)]
        async with lock:
            row = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
            if not row:
                return await _send(music_cog, ctx, "Playlist introuvable", f"Aucune playlist **{display}**.", kind="danger")
            items = decode_playlist_items(row["items_json"])
            room = _MAX_TRACKS - len(items)
            if room <= 0:
                return await _send(music_cog, ctx, "Playlist pleine", f"Une playlist peut contenir jusqu'à **{_MAX_TRACKS} titres**.", kind="danger")
            selected = resolved.tracks[:room]
            items.extend(_track_to_item(track, recherche) for track in selected)
            await _save_items(bot, ctx.guild.id, ctx.author.id, key, items)

        imported = len(selected)
        suffix = ""
        ignored = max(0, len(resolved.tracks) - imported) + len(resolved.skipped)
        if ignored:
            suffix = f"\n**{ignored}** titre(s) ont été ignorés (introuvables ou limite atteinte)."
        await _send(
            music_cog,
            ctx,
            "Playlist mise à jour",
            f"**{imported}** titre(s) ajouté(s) à **{row['name']}**. Total : **{len(items)}**.{suffix}",
            kind="success",
        )

    @playlist.command(name="list", description="Afficher vos playlists.")
    async def playlist_list(ctx: commands.Context):
        if ctx.guild is None:
            return
        rows = await bot.db.fetchall(
            "SELECT name, items_json FROM music_playlists WHERE guild_id = ? AND user_id = ? ORDER BY updated_at DESC",
            (ctx.guild.id, ctx.author.id),
        )
        if not rows:
            return await _send(music_cog, ctx, "Playlists", "Vous n'avez encore aucune playlist sur ce serveur.")
        lines = []
        for index, row in enumerate(rows, 1):
            count = len(decode_playlist_items(row["items_json"]))
            lines.append(f"**{index}. {row['name']}** — {count} titre(s)")
        await _send(music_cog, ctx, "Vos playlists", "\n".join(lines))

    @playlist.command(name="show", description="Afficher les titres d'une playlist.")
    async def playlist_show(ctx: commands.Context, *, nom: str):
        if ctx.guild is None:
            return
        try:
            _, key = normalize_playlist_name(nom)
        except ValueError as exc:
            return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")
        row = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
        if not row:
            return await _send(music_cog, ctx, "Playlist introuvable", "Cette playlist n'existe pas.", kind="danger")
        items = decode_playlist_items(row["items_json"])
        if not items:
            return await _send(music_cog, ctx, row["name"], "Cette playlist est vide.")
        shown = [f"**{i}.** {_display_item(item)}" for i, item in enumerate(items[:20], 1)]
        if len(items) > 20:
            shown.append(f"\n… et **{len(items) - 20}** autre(s) titre(s).")
        await _send(music_cog, ctx, f"Playlist — {row['name']}", "\n".join(shown))

    @playlist.command(name="play", description="Lire une playlist dans votre salon vocal.")
    async def playlist_play(ctx: commands.Context, *, nom: str):
        if ctx.guild is None:
            return
        try:
            _, key = normalize_playlist_name(nom)
        except ValueError as exc:
            return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")
        row = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
        if not row:
            return await _send(music_cog, ctx, "Playlist introuvable", "Cette playlist n'existe pas.", kind="danger")
        items = decode_playlist_items(row["items_json"])
        if not items:
            return await _send(music_cog, ctx, "Playlist vide", f"**{row['name']}** ne contient aucun titre.", kind="danger")

        queue = await music_cog._ensure_voice(ctx)
        if queue is None:
            return
        if ctx.interaction and not ctx.interaction.response.is_done():
            await ctx.defer()

        tracks = [_item_to_track(item, ctx.author.id) for item in items]
        queue.tracks.extend(tracks)
        started_now = False
        if not (queue.voice_client.is_playing() or queue.voice_client.is_paused()) and not queue.current:
            await music_cog._advance(queue)
            started_now = queue.current is not None
        if started_now:
            description = f"Lecture de **{row['name']}** démarrée — **{len(tracks)}** titre(s) chargés."
        else:
            description = f"**{row['name']}** ajoutée à la file — **{len(tracks)}** titre(s)."
        await _send(music_cog, ctx, "Playlist chargée", description, kind="success")

    @playlist.command(name="remove", description="Retirer un titre d'une playlist par sa position.")
    async def playlist_remove(ctx: commands.Context, nom: str, position: int):
        if ctx.guild is None:
            return
        try:
            _, key = normalize_playlist_name(nom)
        except ValueError as exc:
            return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")
        lock = _LOCKS[(ctx.guild.id, ctx.author.id)]
        async with lock:
            row = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
            if not row:
                return await _send(music_cog, ctx, "Playlist introuvable", "Cette playlist n'existe pas.", kind="danger")
            items = decode_playlist_items(row["items_json"])
            if position < 1 or position > len(items):
                return await _send(music_cog, ctx, "Position invalide", f"Choisissez une position entre **1** et **{len(items)}**.", kind="danger")
            removed = items.pop(position - 1)
            await _save_items(bot, ctx.guild.id, ctx.author.id, key, items)
        await _send(music_cog, ctx, "Titre retiré", f"**{_display_item(removed)}** a été retiré de **{row['name']}**.", kind="success")

    @playlist.command(name="clear", description="Vider entièrement une playlist.")
    async def playlist_clear(ctx: commands.Context, *, nom: str):
        if ctx.guild is None:
            return
        try:
            _, key = normalize_playlist_name(nom)
        except ValueError as exc:
            return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")
        lock = _LOCKS[(ctx.guild.id, ctx.author.id)]
        async with lock:
            row = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
            if not row:
                return await _send(music_cog, ctx, "Playlist introuvable", "Cette playlist n'existe pas.", kind="danger")
            await _save_items(bot, ctx.guild.id, ctx.author.id, key, [])
        await _send(music_cog, ctx, "Playlist vidée", f"**{row['name']}** est maintenant vide.", kind="success")

    @playlist.command(name="rename", description="Renommer une playlist.")
    async def playlist_rename(ctx: commands.Context, ancien_nom: str, *, nouveau_nom: str):
        if ctx.guild is None:
            return
        try:
            _, old_key = normalize_playlist_name(ancien_nom)
            new_display, new_key = normalize_playlist_name(nouveau_nom)
        except ValueError as exc:
            return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")
        lock = _LOCKS[(ctx.guild.id, ctx.author.id)]
        async with lock:
            row = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, old_key)
            if not row:
                return await _send(music_cog, ctx, "Playlist introuvable", "La playlist à renommer n'existe pas.", kind="danger")
            if new_key != old_key and await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, new_key):
                return await _send(music_cog, ctx, "Nom déjà utilisé", f"Vous avez déjà une playlist **{new_display}**.", kind="danger")
            await bot.db.execute(
                "UPDATE music_playlists SET name_key = ?, name = ?, updated_at = ? "
                "WHERE guild_id = ? AND user_id = ? AND name_key = ?",
                (new_key, new_display, int(time.time()), ctx.guild.id, ctx.author.id, old_key),
            )
        await _send(music_cog, ctx, "Playlist renommée", f"**{row['name']}** devient **{new_display}**.", kind="success")

    @playlist.command(name="delete", description="Supprimer définitivement une playlist.")
    async def playlist_delete(ctx: commands.Context, *, nom: str):
        if ctx.guild is None:
            return
        try:
            _, key = normalize_playlist_name(nom)
        except ValueError as exc:
            return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")
        lock = _LOCKS[(ctx.guild.id, ctx.author.id)]
        async with lock:
            row = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
            if not row:
                return await _send(music_cog, ctx, "Playlist introuvable", "Cette playlist n'existe pas.", kind="danger")
            await bot.db.execute(
                "DELETE FROM music_playlists WHERE guild_id = ? AND user_id = ? AND name_key = ?",
                (ctx.guild.id, ctx.author.id, key),
            )
        await _send(music_cog, ctx, "Playlist supprimée", f"**{row['name']}** a été supprimée.", kind="success")

    music_root.add_command(playlist)
    music_cog._sentrix_playlists_v108 = True
    logger.warning(
        "Musique V108 playlists active : /music playlist create/add/list/show/play/remove/clear/rename/delete."
    )


async def install_on_music_cog(bot, music_cog) -> None:
    """Installe V108 une seule fois sur l'instance Music courante."""
    if getattr(music_cog, "_sentrix_music_v108_installed", False):
        return
    await _install_schema(bot)
    _install_finish_ping(music_cog)
    _install_playlist_group(bot, music_cog)
    music_cog._sentrix_music_v108_installed = True
    logger.warning("Musique V108 active : ping de fin + playlists persistantes.")


__all__ = [
    "decode_playlist_items",
    "install_on_music_cog",
    "normalize_playlist_name",
]
