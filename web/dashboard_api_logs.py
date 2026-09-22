"""Configuration des journaux du dashboard SentriX.

La source de vérité est utils.log_service/log_config. Les colonnes legacy de guild_config
ne sont jamais écrites ici. Les événements fins réutilisent v17_log_event_settings.
"""
from __future__ import annotations

from aiohttp import web

from utils import log_service
from utils.log_categories import CATEGORIES, CATEGORY_ORDER


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
            value = await request.json()
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    async def config_get(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        settings = await log_service.get_all_log_settings(bot, guild.id)
        routes = []
        for key in CATEGORY_ORDER:
            item = settings.get(key) or {}
            channel_id = item.get("channel_id")
            ok, problem = log_service.validate_channel(guild, channel_id) if channel_id else (False, "aucun salon configuré")
            routes.append({
                "key": key,
                "label": CATEGORIES[key],
                "channel_id": str(channel_id) if channel_id else None,
                "enabled": bool(item.get("enabled", True)),
                "valid": bool(ok),
                "problem": None if ok else problem,
            })

        # Les événements V17 sont actifs par défaut lorsqu'aucune ligne n'existe.
        from cogs.v17_shared import ensure_schema
        from cogs.v17_tickets_logs import EVENT_LABELS
        await ensure_schema(bot)
        rows = await bot.db.fetchall(
            "SELECT event_key,enabled FROM v17_log_event_settings WHERE guild_id=?",
            (guild.id,),
        )
        saved = {str(r["event_key"]): bool(r["enabled"]) for r in rows}
        events = [
            {"key": key, "label": label, "enabled": saved.get(key, True)}
            for key, label in EVENT_LABELS.items()
        ]
        return web.json_response({"ok": True, "routes": routes, "events": events})

    async def config_put(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        key = str(payload.get("category") or "").strip()
        if key not in CATEGORIES:
            return dashboard._json_error("Catégorie de logs inconnue.", 400)

        raw_channel = payload.get("channel_id")
        channel_id = None
        if raw_channel not in (None, "", 0, "0"):
            try:
                channel_id = int(raw_channel)
            except (TypeError, ValueError):
                return dashboard._json_error("Salon invalide.", 400)
            ok, problem = log_service.validate_channel(guild, channel_id)
            if not ok:
                return dashboard._json_error(f"Ce salon ne peut pas recevoir les logs : {problem}.", 409)

        enabled = bool(payload.get("enabled", channel_id is not None))
        if enabled and channel_id is None:
            return dashboard._json_error("Choisissez un salon avant d’activer cette catégorie.", 409)

        saved = await log_service.set_log_config(
            bot,
            guild.id,
            key,
            channel_id=channel_id,
            enabled=enabled,
        )
        return web.json_response({
            "ok": True,
            "message": f"Logs {CATEGORIES[key]} enregistrés.",
            "route": {
                "key": key,
                "label": CATEGORIES[key],
                "channel_id": str(saved["channel_id"]) if saved.get("channel_id") else None,
                "enabled": bool(saved.get("enabled")),
            },
        })

    async def event_put(request: web.Request):
        _session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        from cogs.v17_shared import ensure_schema, state
        from cogs.v17_tickets_logs import EVENT_LABELS
        await ensure_schema(bot)
        key = str(payload.get("event_key") or "").strip()
        if key not in EVENT_LABELS:
            return dashboard._json_error("Événement de log inconnu.", 400)
        enabled = bool(payload.get("enabled"))
        await bot.db.execute(
            "INSERT INTO v17_log_event_settings (guild_id,event_key,enabled) VALUES (?,?,?) "
            "ON CONFLICT(guild_id,event_key) DO UPDATE SET enabled=excluded.enabled",
            (guild.id, key, 1 if enabled else 0),
        )
        cache = state(bot).setdefault("v17_log_event_cache", {})
        cache.pop((guild.id, key), None)
        return web.json_response({
            "ok": True,
            "message": f"{EVENT_LABELS[key]} : {'activé' if enabled else 'désactivé'}.",
        })

    app.router.add_get("/api/guilds/{guild_id}/logs/config", config_get)
    app.router.add_put("/api/guilds/{guild_id}/logs/config", config_put)
    app.router.add_put("/api/guilds/{guild_id}/logs/events", event_put)


__all__ = ["register"]
