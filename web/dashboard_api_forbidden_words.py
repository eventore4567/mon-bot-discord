"""API dashboard pour gérer les mots interdits SentriX."""
from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard.forbidden-words")


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

    async def list_words(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        rows = await bot.db.fetchall(
            "SELECT word FROM blacklist_words WHERE guild_id=? ORDER BY word",
            (guild.id,),
        )
        return web.json_response({
            "ok": True,
            "words": [str(row["word"]) for row in rows],
        })

    async def update_words(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        try:
            payload = await request.json()
        except Exception:
            return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

        action = str(payload.get("action") or "").strip().lower()
        word = str(payload.get("word") or "").strip().casefold()
        if action not in {"add", "remove"}:
            return dashboard._json_error("Action mots interdits invalide.", 400)
        if not word or len(word) > 80 or "\n" in word or "\r" in word:
            return dashboard._json_error(
                "Le mot ou l’expression doit contenir entre 1 et 80 caractères.",
                400,
            )

        if action == "add":
            exists = await bot.db.fetchone(
                "SELECT 1 FROM blacklist_words WHERE guild_id=? AND lower(word)=lower(?) LIMIT 1",
                (guild.id, word),
            )
            if not exists:
                await bot.db.execute(
                    "INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)",
                    (guild.id, word),
                )
            message = f"« {word} » ajouté aux mots interdits."
        else:
            await bot.db.execute(
                "DELETE FROM blacklist_words WHERE guild_id=? AND lower(word)=lower(?)",
                (guild.id, word),
            )
            message = f"« {word} » retiré des mots interdits."

        automod = bot.get_cog("Automod")
        if automod is not None:
            cache = getattr(automod, "blacklist_words_cache", None)
            if isinstance(cache, dict):
                cache.pop(guild.id, None)
            sync = getattr(automod, "_sync_native_blacklist_rule", None)
            if callable(sync):
                try:
                    await sync(guild)
                except Exception:
                    logger.exception("Synchronisation native mots interdits impossible guild=%s", guild.id)

        rows = await bot.db.fetchall(
            "SELECT word FROM blacklist_words WHERE guild_id=? ORDER BY word",
            (guild.id,),
        )
        return web.json_response({
            "ok": True,
            "message": message,
            "words": [str(row["word"]) for row in rows],
        })

    app.router.add_get("/api/guilds/{guild_id}/forbidden-words", list_words)
    app.router.add_post("/api/guilds/{guild_id}/forbidden-words", update_words)


__all__ = ["register"]
