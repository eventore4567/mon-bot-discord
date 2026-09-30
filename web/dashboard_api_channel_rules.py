"""API dashboard des règles de contenu par salon."""
from __future__ import annotations

from aiohttp import web

from cogs import channel_message_rules


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
            csrf = dashboard._require_csrf(request, session)
            if csrf:
                return None, None, csrf
        return session, guild, None

    async def get_rules(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        return web.json_response({
            "ok": True,
            "items": await channel_message_rules.list_rules(bot, guild),
        })

    async def post_rules(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        try:
            payload = await request.json()
        except Exception:
            return dashboard._json_error("Formulaire invalide.", 400)
        if not isinstance(payload, dict):
            return dashboard._json_error("Formulaire invalide.", 400)

        action = str(payload.get("action") or "save").casefold()
        try:
            channel_id = int(payload.get("channel_id") or 0)
        except (TypeError, ValueError):
            channel_id = 0
        if not channel_id:
            return dashboard._json_error("Choisissez un salon.", 400)
        actor_id = int(session["user"]["id"])

        try:
            if action == "save":
                item = await channel_message_rules.save_rule(
                    bot,
                    guild,
                    channel_id,
                    str(payload.get("mode") or ""),
                    actor_id=actor_id,
                )
                return web.json_response({
                    "ok": True,
                    "item": item,
                    "message": "Règle de salon enregistrée.",
                })
            if action == "delete":
                await channel_message_rules.delete_rule(bot, guild.id, channel_id)
                return web.json_response({"ok": True, "message": "Règle supprimée."})
            if action == "toggle":
                await channel_message_rules.toggle_rule(
                    bot,
                    guild.id,
                    channel_id,
                    bool(payload.get("enabled")),
                    actor_id=actor_id,
                )
                return web.json_response({
                    "ok": True,
                    "enabled": bool(payload.get("enabled")),
                })
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)

        return dashboard._json_error("Action inconnue.", 400)

    app.router.add_get(
        "/api/guilds/{guild_id}/automation/channel-rules",
        get_rules,
    )
    app.router.add_post(
        "/api/guilds/{guild_id}/automation/channel-rules",
        post_rules,
    )
