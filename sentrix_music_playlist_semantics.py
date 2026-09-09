"""Semantique produit pour les playlists SentriX.

V108 fournit le stockage et les operations historiques. Cette couche ne duplique pas
la base : elle remplace uniquement le comportement ambigu de ``create`` par une vraie
sauvegarde de la lecture/file courante et ajoute un import explicite de playlist
externe. La surface slash canonique traduit ensuite les noms visibles en francais.
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlparse

from discord.ext import commands

from utils import sentrix_panels as panels
from utils.music import MusicEngineError, ProviderUnavailable
from sentrix_music_playlists_v108 import (
    _LOCKS,
    _MAX_PLAYLISTS,
    _MAX_TRACKS,
    _fetch_playlist,
    _send,
    _track_to_item,
    normalize_playlist_name,
)

logger = logging.getLogger("bot.music-playlist-semantics")
_INSTALLED = False
_ORIGINAL_ADD_COG = None

_ALLOWED_IMPORT_HOSTS = {
    "open.spotify.com",
    "spotify.link",
    "youtube.com",
    "www.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "soundcloud.com",
    "www.soundcloud.com",
    "deezer.com",
    "www.deezer.com",
    "link.deezer.com",
    "deezer.page.link",
}


def _playlist_item(track) -> dict:
    query = str(getattr(track, "original_url", None) or getattr(track, "title", "") or "")
    return _track_to_item(track, query)


def _valid_external_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    return parsed.scheme in {"http", "https"} and (
        host in _ALLOWED_IMPORT_HOSTS
        or host.endswith(".youtube.com")
        or host.endswith(".soundcloud.com")
        or host.endswith(".spotify.com")
        or host.endswith(".deezer.com")
    )


async def _save_snapshot(bot, music_cog, ctx: commands.Context, nom: str):
    if ctx.guild is None:
        return
    try:
        display, key = normalize_playlist_name(nom)
    except ValueError as exc:
        return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")

    queue = music_cog.get_queue(ctx.guild.id)
    source = ([queue.current] if queue.current is not None else []) + list(queue.tracks)
    items = [_playlist_item(track) for track in source if track is not None][:_MAX_TRACKS]
    if not items:
        return await _send(
            music_cog,
            ctx,
            "Aucune musique a sauvegarder",
            "Lancez une musique ou ajoutez des titres a la file avant de sauvegarder la playlist.",
            kind="danger",
        )

    lock = _LOCKS[(ctx.guild.id, ctx.author.id)]
    async with lock:
        existing = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
        now = int(time.time())
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        if existing:
            await bot.db.execute(
                "UPDATE music_playlists SET name = ?, items_json = ?, updated_at = ? "
                "WHERE guild_id = ? AND user_id = ? AND name_key = ?",
                (display, payload, now, ctx.guild.id, ctx.author.id, key),
            )
            action = "mise a jour"
        else:
            row = await bot.db.fetchone(
                "SELECT COUNT(*) AS c FROM music_playlists WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, ctx.author.id),
            )
            if row and int(row["c"]) >= _MAX_PLAYLISTS:
                return await _send(
                    music_cog,
                    ctx,
                    "Limite atteinte",
                    f"Vous pouvez avoir jusqu'a **{_MAX_PLAYLISTS} playlists** par serveur.",
                    kind="danger",
                )
            await bot.db.execute(
                "INSERT INTO music_playlists "
                "(guild_id, user_id, name_key, name, items_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ctx.guild.id, ctx.author.id, key, display, payload, now, now),
            )
            action = "sauvegardee"

    return await _send(
        music_cog,
        ctx,
        "Playlist sauvegardee",
        f"**{display}** a ete {action} avec **{len(items)} titre(s)**. "
        "Utilisez `/musique playlist charger` pour la relancer.",
        kind="success",
    )


async def _import_external(bot, music_cog, ctx: commands.Context, nom: str, url: str):
    if ctx.guild is None:
        return
    try:
        display, key = normalize_playlist_name(nom)
    except ValueError as exc:
        return await _send(music_cog, ctx, "Nom invalide", str(exc), kind="danger")

    external_url = str(url or "").strip()
    if not _valid_external_url(external_url):
        return await _send(
            music_cog,
            ctx,
            "URL non reconnue",
            "Utilisez un lien Spotify, YouTube, SoundCloud ou Deezer pris en charge.",
            kind="danger",
        )

    if ctx.interaction and not ctx.interaction.response.is_done():
        await ctx.defer()

    try:
        resolved = await music_cog.manager.resolve(external_url, requested_by=ctx.author.id)
    except ProviderUnavailable as exc:
        reason = str(exc.reason or "")
        lowered = reason.casefold()
        if exc.provider.casefold() == "spotify" and "spotify_client_id" in lowered:
            return await _send(
                music_cog,
                ctx,
                "Spotify non configure",
                "L'import d'albums/playlists Spotify necessite les identifiants d'application Spotify "
                "dans les variables Railway. Aucun secret ne doit etre envoye dans Discord.",
                kind="danger",
            )
        if exc.provider.casefold() == "spotify" and "playlist-spotify-2026" in lowered:
            return await _send(
                music_cog,
                ctx,
                "Playlist Spotify non accessible",
                "Le lien est valide, mais Spotify renvoie 403 pour les elements de cette playlist. "
                "Depuis 2026, Spotify exige une autorisation utilisateur et limite les elements "
                "aux playlists possedees ou collaboratives de ce compte. SentriX utilise ici "
                "l'authentification d'application et ne contourne pas cette restriction. "
                "Utilisez YouTube, SoundCloud ou Deezer pour cette playlist, ou une piste/album Spotify.",
                kind="danger",
            )
        return await _send(
            music_cog,
            ctx,
            f"{exc.provider.title()} indisponible",
            f"Le fournisseur est temporairement indisponible : `{reason[:180]}`",
            kind="danger",
        )
    except MusicEngineError as exc:
        return await panels.envoyer(
            ctx,
            panels.depuis_embed(await music_cog._error_embed(ctx.guild.id, exc)),
        )

    selected = list(resolved.tracks[:_MAX_TRACKS])
    if not selected:
        return await _send(
            music_cog,
            ctx,
            "Aucun titre importe",
            "La playlist a ete reconnue mais aucun titre exploitable n'a ete trouve.",
            kind="danger",
        )
    items = [_track_to_item(track, external_url) for track in selected]

    lock = _LOCKS[(ctx.guild.id, ctx.author.id)]
    async with lock:
        existing = await _fetch_playlist(bot, ctx.guild.id, ctx.author.id, key)
        now = int(time.time())
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        if existing:
            await bot.db.execute(
                "UPDATE music_playlists SET name = ?, items_json = ?, updated_at = ? "
                "WHERE guild_id = ? AND user_id = ? AND name_key = ?",
                (display, payload, now, ctx.guild.id, ctx.author.id, key),
            )
        else:
            row = await bot.db.fetchone(
                "SELECT COUNT(*) AS c FROM music_playlists WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, ctx.author.id),
            )
            if row and int(row["c"]) >= _MAX_PLAYLISTS:
                return await _send(
                    music_cog,
                    ctx,
                    "Limite atteinte",
                    f"Vous pouvez avoir jusqu'a **{_MAX_PLAYLISTS} playlists** par serveur.",
                    kind="danger",
                )
            await bot.db.execute(
                "INSERT INTO music_playlists "
                "(guild_id, user_id, name_key, name, items_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ctx.guild.id, ctx.author.id, key, display, payload, now, now),
            )

    skipped = len(getattr(resolved, "skipped", []) or [])
    ignored_by_limit = max(0, len(resolved.tracks) - len(selected))
    suffix = ""
    if skipped or ignored_by_limit:
        suffix = f"\n**{skipped + ignored_by_limit}** titre(s) ignores."
    return await _send(
        music_cog,
        ctx,
        "Playlist importee",
        f"**{display}** contient maintenant **{len(items)} titre(s)**.{suffix}\n"
        "Utilisez `/musique playlist charger` pour lancer la lecture.",
        kind="success",
    )


def _patch_playlist_commands(bot, music_cog) -> None:
    if getattr(music_cog, "_sentrix_playlist_semantics", False):
        return
    music_root = bot.get_command("music")
    if not isinstance(music_root, commands.Group):
        return
    playlist = music_root.get_command("playlist")
    if not isinstance(playlist, commands.Group):
        return

    create = playlist.get_command("create")
    if create is not None:
        async def save_callback(ctx: commands.Context, *, nom: str):
            return await _save_snapshot(bot, music_cog, ctx, nom)

        create.callback = save_callback
        create.description = "Sauvegarder la musique en cours et la file dans une playlist personnelle."
        create.help = create.description
        create._sentrix_playlist_save_semantics = True

    if playlist.get_command("import") is None:
        @playlist.command(name="import", description="Importer une playlist Spotify, YouTube, SoundCloud ou Deezer.")
        async def playlist_import(ctx: commands.Context, nom: str, *, url: str):
            return await _import_external(bot, music_cog, ctx, nom, url)

    async def playlist_home(ctx: commands.Context):
        if ctx.guild is None:
            return
        if ctx.invoked_subcommand is None:
            return await _send(
                music_cog,
                ctx,
                "Playlists SentriX",
                "`/musique playlist sauvegarder` enregistre la lecture/file courante.\n"
                "`/musique playlist importer` importe un lien externe.\n"
                "`/musique playlist charger` relance une playlist sauvegardee.",
            )

    playlist.callback = playlist_home
    playlist.description = "Sauvegarder, importer et gerer vos playlists SentriX."
    playlist.help = playlist.description

    descriptions = {
        "add": "Ajouter un titre ou un lien a une playlist existante.",
        "list": "Afficher vos playlists personnelles.",
        "show": "Afficher les informations et titres d'une playlist.",
        "play": "Charger une playlist dans votre salon vocal.",
        "remove": "Retirer un titre d'une playlist par sa position.",
        "clear": "Vider entierement une playlist.",
        "rename": "Renommer une playlist.",
        "delete": "Supprimer definitivement une playlist.",
    }
    for name, description in descriptions.items():
        command = playlist.get_command(name)
        if command is not None:
            command.description = description
            command.help = description

    music_cog._sentrix_playlist_semantics = True
    logger.warning("Playlists canoniques actives : sauvegarder/importer/charger + gestion complete.")


def install() -> None:
    """Installe le patch apres la couche V102/V108 deja presente sur Bot.add_cog."""
    global _INSTALLED, _ORIGINAL_ADD_COG
    if _INSTALLED:
        return
    original = commands.Bot.add_cog
    if getattr(original, "_sentrix_playlist_semantics_loader", False):
        _INSTALLED = True
        return
    _ORIGINAL_ADD_COG = original

    async def add_cog_with_playlist_semantics(bot, cog, *args, **kwargs):
        result = await original(bot, cog, *args, **kwargs)
        if cog.__class__.__name__ == "Music" or getattr(cog, "qualified_name", None) == "Music":
            _patch_playlist_commands(bot, cog)
        return result

    add_cog_with_playlist_semantics._sentrix_playlist_semantics_loader = True
    add_cog_with_playlist_semantics.__wrapped__ = original
    commands.Bot.add_cog = add_cog_with_playlist_semantics
    _INSTALLED = True
    logger.info("Chargeur de semantique playlist prepare apres V108.")


__all__ = ["install"]
