from __future__ import annotations

import base64
import logging

from aiohttp import ClientSession, ClientTimeout, web

_INSTALLED = False
logger = logging.getLogger("bot.dashboard.user-avatar-v46")


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


async def _avatar_data_uri(request: web.Request, session: dict) -> str | None:
    """Charge la PP côté serveur puis l'embarque dans /api/me.

    Cela évite complètement les problèmes de CDN, CORS, cache ou middleware sur une
    deuxième requête image : le navigateur reçoit directement les octets de la vraie PP.
    """
    url = await _discord_avatar_url(request, session)
    if not url:
        return None

    try:
        timeout = ClientTimeout(total=10)
        headers = {"User-Agent": "SentriX-Dashboard/1.0"}
        async with ClientSession(timeout=timeout, headers=headers) as client:
            async with client.get(url) as upstream:
                if upstream.status != 200:
                    logger.warning("CDN Discord avatar HTTP %s", upstream.status)
                    return None
                body = await upstream.read()
                if not body or len(body) > 2_000_000:
                    return None
                content_type = upstream.headers.get("Content-Type", "image/png").split(";", 1)[0]
                if not content_type.startswith("image/"):
                    content_type = "image/png"
    except Exception as exc:
        logger.warning("Impossible de charger la PP Discord du dashboard: %s", exc)
        return None

    encoded = base64.b64encode(body).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


async def handle_me_with_embedded_avatar(request: web.Request) -> web.Response:
    dashboard = request.app.get("dashboard_module")
    if dashboard is None:
        raise web.HTTPInternalServerError(text="Dashboard indisponible")

    session, error = dashboard._require_session(request)
    if error:
        return error

    user = dict(session.get("user") or {})
    user["avatar_url"] = await _avatar_data_uri(request, session)
    return web.json_response(
        {"user": user, "csrf": session["csrf"]},
        headers={"Cache-Control": "private, no-store"},
    )


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # /api/me fournit la vraie PP sous forme data URI. Aucune route image séparée n'est
    # nécessaire et les contrôles Administrateur restent appliqués à /api/me.
    dashboard.handle_me = handle_me_with_embedded_avatar

    # dashboard_profile_images contenait encore un ancien avatar local "T" et le
    # réappliquait toutes les 500 ms. On garde son mécanisme de rafraîchissement mais on
    # lui fait utiliser l'avatar déjà reçu depuis /api/me.
    old_call = 'putImage("userAvatar", "/assets/user-avatar?v=t3d", "T", "Photo de profil T");'
    new_call = '''try {
      if (typeof state !== "undefined" && state.user && state.user.avatar_url) {
        putImage("userAvatar", state.user.avatar_url, "U", "Photo de profil Discord");
      }
    } catch (_) {}'''
    dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace(old_call, new_call)
    dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace(
        "Photo de profil T",
        "Photo de profil Discord",
    )
