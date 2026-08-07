"""Sessions persistantes du dashboard SentriX."""
from __future__ import annotations
import json, logging, time
from aiohttp import web

logger = logging.getLogger("bot.dashboard.persistent-session")
SESSION_TTL_SECONDS = 30 * 24 * 60 * 60
_INSTALLED = False
_SCHEMA = """
CREATE TABLE IF NOT EXISTS dashboard_sessions (
    session_id TEXT PRIMARY KEY,
    session_json TEXT NOT NULL,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
)
"""

async def _prepare_database(app: web.Application) -> None:
    db = app["bot"].db
    await db.execute(_SCHEMA)
    await db.execute("CREATE INDEX IF NOT EXISTS idx_dashboard_sessions_expires ON dashboard_sessions (expires_at)")
    await db.execute("DELETE FROM dashboard_sessions WHERE expires_at <= ?", (int(time.time()),))

async def _save_session(request: web.Request, session_id: str, session: dict) -> None:
    if not session_id or not session:
        return
    now_ts = int(time.time())
    expires_at = int(session.get("expires_at") or (now_ts + SESSION_TTL_SECONDS))
    payload = json.dumps(session, ensure_ascii=False, separators=(",", ":"))
    user_id = str(session.get("user", {}).get("id", ""))
    await request.app["bot"].db.execute(
        "INSERT INTO dashboard_sessions "
        "(session_id, session_json, user_id, expires_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(session_id) DO UPDATE SET "
        "session_json=excluded.session_json, user_id=excluded.user_id, "
        "expires_at=excluded.expires_at, updated_at=excluded.updated_at",
        (session_id, payload, user_id, expires_at, now_ts, now_ts),
    )

async def _restore_session(request: web.Request, dashboard) -> None:
    session_id = request.cookies.get(dashboard.SESSION_COOKIE)
    if not session_id or session_id in request.app["sessions"]:
        return
    try:
        row = await request.app["bot"].db.fetchone(
            "SELECT session_json, expires_at FROM dashboard_sessions WHERE session_id = ?",
            (session_id,),
        )
    except Exception:
        logger.exception("Lecture de session dashboard impossible.")
        return
    if not row:
        return
    expires_at = int(row["expires_at"])
    if expires_at <= int(time.time()):
        try:
            await request.app["bot"].db.execute(
                "DELETE FROM dashboard_sessions WHERE session_id = ?", (session_id,)
            )
        except Exception:
            pass
        return
    try:
        session = json.loads(row["session_json"])
        if not isinstance(session, dict):
            raise ValueError("session invalide")
    except Exception:
        try:
            await request.app["bot"].db.execute(
                "DELETE FROM dashboard_sessions WHERE session_id = ?", (session_id,)
            )
        except Exception:
            pass
        return
    # La date enregistrée en base reste l'autorité : un ancien JSON ne peut jamais
    # prolonger lui-même sa durée de vie.
    session["expires_at"] = float(expires_at)
    request.app["sessions"][session_id] = session

def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # 30 jours fixes depuis la connexion : fermer le navigateur ou redémarrer Railway
    # ne remet pas le compteur à zéro.
    dashboard.SESSION_TTL = SESSION_TTL_SECONDS
    original_callback = dashboard.handle_callback
    original_logout = dashboard.handle_logout
    original_build_app = dashboard.build_app

    async def handle_callback(request: web.Request):
        try:
            return await original_callback(request)
        except web.HTTPFound as redirect:
            # Une connexion OAuth réussie crée la session en mémoire et son cookie.
            # On persiste uniquement la session applicative ; jamais le token OAuth.
            morsel = redirect.cookies.get(dashboard.SESSION_COOKIE)
            if morsel is not None:
                session_id = morsel.value
                session = request.app["sessions"].get(session_id)
                if session:
                    try:
                        await _save_session(request, session_id, session)
                    except Exception:
                        logger.exception("Sauvegarde de session dashboard impossible.")
            raise

    async def handle_logout(request: web.Request):
        session_id = request.cookies.get(dashboard.SESSION_COOKIE, "")
        response = await original_logout(request)
        if session_id and response.status < 400:
            try:
                await request.app["bot"].db.execute(
                    "DELETE FROM dashboard_sessions WHERE session_id = ?", (session_id,)
                )
            except Exception:
                logger.exception("Suppression de session dashboard impossible.")
        return response

    @web.middleware
    async def persistent_session_middleware(request: web.Request, handler):
        # Restaure la session depuis SQLite avant que le verrou Administrateur ne la lise.
        await _restore_session(request, dashboard)
        response = await handler(request)

        # Les permissions Discord restent revérifiées à chaque accès par le middleware
        # Administrateur. On synchronise seulement le contenu de la session sans repousser
        # sa date d'expiration originale.
        session_id = request.cookies.get(dashboard.SESSION_COOKIE)
        if session_id:
            session = request.app["sessions"].get(session_id)
            if session and float(session.get("expires_at", 0)) > time.time():
                try:
                    await _save_session(request, session_id, session)
                except Exception:
                    logger.exception("Synchronisation de session dashboard impossible.")
        return response

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.on_startup.append(_prepare_database)
        app.middlewares.append(persistent_session_middleware)
        return app

    dashboard.handle_callback = handle_callback
    dashboard.handle_logout = handle_logout
    dashboard.build_app = build_app
    logger.info("Sessions dashboard persistantes activées (30 jours).")
