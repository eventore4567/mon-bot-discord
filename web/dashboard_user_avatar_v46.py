from __future__ import annotations

import logging

from aiohttp import ClientSession, ClientTimeout, web

_INSTALLED = False
logger = logging.getLogger("bot.dashboard.user-avatar-v46")
_AVATAR_PATH = "/api/me/avatar"


async def _discord_avatar_url(request: web.Request, session: dict) -> str | None:
    user = session.get("user") or {}
    stored = str(user.get("avatar_url") or "").strip()
    if stored.startswith("https://cdn.discordapp.com/"):
        return stored

    try:
        user_id = int(user.get("id") or 0)
    except (TypeError, ValueError):
        user_id = 0

    bot = request.app.get("bot")
    if bot is not None and user_id:
        discord_user = bot.get_user(user_id)
        if discord_user is None:
            try:
                discord_user = await bot.fetch_user(user_id)
            except Exception:
                discord_user = None
        if discord_user is not None:
            avatar = getattr(discord_user, "display_avatar", None)
            if avatar is not None:
                try:
                    avatar = avatar.replace(size=128, static_format="png")
                except Exception:
                    try:
                        avatar = avatar.with_size(128)
                    except Exception:
                        pass
                value = str(getattr(avatar, "url", avatar) or "").strip()
                if value:
                    return value

    if user_id:
        return f"https://cdn.discordapp.com/embed/avatars/{(user_id >> 22) % 6}.png"
    return None


async def user_avatar(request: web.Request) -> web.Response:
    dashboard = request.app.get("dashboard_module")
    if dashboard is None:
        raise web.HTTPNotFound()

    session = dashboard._session(request)
    if not session:
        raise web.HTTPUnauthorized(text="Connexion Discord requise")

    url = await _discord_avatar_url(request, session)
    if not url:
        raise web.HTTPNotFound(text="Avatar Discord indisponible")

    try:
        timeout = ClientTimeout(total=10)
        headers = {"User-Agent": "SentriX-Dashboard/1.0"}
        async with ClientSession(timeout=timeout, headers=headers) as client:
            async with client.get(url) as upstream:
                if upstream.status != 200:
                    logger.warning("CDN Discord avatar HTTP %s pour %s", upstream.status, url)
                    raise web.HTTPBadGateway(text="Avatar Discord temporairement indisponible")
                body = await upstream.read()
                content_type = upstream.headers.get("Content-Type", "image/png").split(";", 1)[0]
    except web.HTTPException:
        raise
    except Exception as exc:
        logger.warning("Impossible de charger la PP Discord du dashboard: %s", exc)
        raise web.HTTPBadGateway(text="Avatar Discord temporairement indisponible") from exc

    return web.Response(
        body=body,
        content_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300, stale-while-revalidate=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def handle_me_with_local_avatar(request: web.Request) -> web.Response:
    dashboard = request.app.get("dashboard_module")
    if dashboard is None:
        raise web.HTTPInternalServerError(text="Dashboard indisponible")

    session, error = dashboard._require_session(request)
    if error:
        return error

    user = dict(session.get("user") or {})
    user["avatar_url"] = _AVATAR_PATH + "?v=discord-v46"
    return web.json_response({"user": user, "csrf": session["csrf"]})


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    dashboard.handle_me = handle_me_with_local_avatar

    # Une ancienne couche dashboard_profile_images forçait encore une image locale "T"
    # après loadSession(). On la remplace ici, en dernier, par la vraie PP Discord.
    dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace(
        "/assets/user-avatar?v=t3d",
        _AVATAR_PATH + "?v=discord-v46",
    )
    dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace(
        "Photo de profil T",
        "Photo de profil Discord",
    )

    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_get(_AVATAR_PATH, user_avatar)
        return app

    dashboard.build_app = build_app
