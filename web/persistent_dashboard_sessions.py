"""Sessions navigateur du dashboard SentriX.

La connexion n'est volontairement plus persistée en base. Le cookie disparaît à la
fermeture du navigateur et les permissions Discord sont revérifiées en direct par les
verrous du dashboard avant toute page/API d'administration.
"""
from __future__ import annotations

import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.browser-session")
_INSTALLED = False
SESSION_TTL_SECONDS = 2 * 60 * 60


async def _clear_legacy_sessions(app: web.Application) -> None:
    """Invalide les anciennes sessions 30 jours créées par les versions précédentes."""
    try:
        await app["bot"].db.execute("DELETE FROM dashboard_sessions")
    except Exception:
        # La table peut ne pas exister sur une nouvelle installation.
        pass


def _make_browser_session_cookie(
    response: web.StreamResponse,
    request: web.Request,
    dashboard,
    session_id: str,
) -> None:
    """Cookie de session uniquement : aucun Max-Age et aucun Expires."""
    response.set_cookie(
        dashboard.SESSION_COOKIE,
        session_id,
        path="/",
        httponly=True,
        secure=dashboard._public_url(request).startswith("https://"),
        samesite="Lax",
    )
    morsel = response.cookies.get(dashboard.SESSION_COOKIE)
    if morsel is not None:
        # aiohttp peut conserver des attributs posés par le callback d'origine.
        morsel["max-age"] = ""
        morsel["expires"] = ""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Même si le navigateur reste ouvert longtemps, une nouvelle authentification est
    # exigée au bout de 2 h. La perte de permission Administrateur, elle, est détectée
    # immédiatement par admin_only_dashboard et _manageable_guild à chaque action.
    dashboard.SESSION_TTL = SESSION_TTL_SECONDS
    original_callback = dashboard.handle_callback
    original_build_app = dashboard.build_app

    async def handle_callback(request: web.Request):
        try:
            return await original_callback(request)
        except web.HTTPFound as redirect:
            morsel = redirect.cookies.get(dashboard.SESSION_COOKIE)
            if morsel is not None:
                session_id = morsel.value
                session = request.app["sessions"].get(session_id)
                if session:
                    session["expires_at"] = time.time() + SESSION_TTL_SECONDS
                    _make_browser_session_cookie(redirect, request, dashboard, session_id)
            raise

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.on_startup.append(_clear_legacy_sessions)
        return app

    dashboard.handle_callback = handle_callback
    dashboard.build_app = build_app
    logger.info("Sessions dashboard limitées au navigateur + 2 h maximum.")
