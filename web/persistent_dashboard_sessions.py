"""Sessions HA du dashboard SentriX.

Le cookie reste une session de navigateur (pas de Max-Age persistant), mais l'état
serveur de la session et les states OAuth sont répliqués dans Redis. Ainsi un
redémarrage Railway ou une bascule primary <-> standby ne transforme plus un cookie
valide en série de 401.

Redis reste un accélérateur/stockage HA : si Redis est momentanément indisponible,
le dashboard retombe sur les dictionnaires mémoire historiques sans empêcher le bot
Discord ou le serveur HTTP de démarrer.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from aiohttp import web
from redis.asyncio import Redis

import config

logger = logging.getLogger("bot.dashboard.browser-session")

_INSTALLED = False
SESSION_TTL_SECONDS = 2 * 60 * 60
SYNC_INTERVAL_SECONDS = 20
_REDIS_APP_KEY = "sentrix_dashboard_session_redis"
_SYNC_APP_KEY = "sentrix_dashboard_session_sync"
_INSTANCE = (os.getenv("BOT_INSTANCE_KEY") or "sentrix").strip().casefold() or "sentrix"
_SESSION_PREFIX = f"sentrix:{_INSTANCE}:dashboard:session:"
_STATE_PREFIX = f"sentrix:{_INSTANCE}:dashboard:oauth-state:"


def _session_key(session_id: str) -> str:
    return _SESSION_PREFIX + session_id


def _state_key(state: str) -> str:
    return _STATE_PREFIX + state


def _redis(app: web.Application) -> Redis | None:
    client = app.get(_REDIS_APP_KEY)
    return client if isinstance(client, Redis) else None


async def _clear_legacy_sessions(app: web.Application) -> None:
    """Supprime uniquement les anciennes sessions SQL qui ne sont plus utilisées."""
    try:
        await app["bot"].db.execute("DELETE FROM dashboard_sessions")
    except Exception:
        # La table peut ne pas exister sur une nouvelle installation.
        pass


async def _start_redis(app: web.Application) -> None:
    app[_REDIS_APP_KEY] = None
    app[_SYNC_APP_KEY] = {}
    url = (getattr(config, "REDIS_URL", "") or "").strip()
    if not url:
        logger.warning("Sessions HA dashboard : REDIS_URL absent, fallback mémoire.")
        return
    try:
        client = Redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
        )
        await client.ping()
        app[_REDIS_APP_KEY] = client
        logger.info("Sessions dashboard HA Redis actives.")
    except Exception:
        logger.exception(
            "Redis des sessions dashboard indisponible ; fallback mémoire conservé."
        )


async def _stop_redis(app: web.Application) -> None:
    client = _redis(app)
    if client is None:
        return
    try:
        await client.aclose()
    except Exception:
        pass


async def _load_session(app: web.Application, session_id: str) -> dict[str, Any] | None:
    client = _redis(app)
    if client is None:
        return None
    try:
        raw = await client.get(_session_key(session_id))
        if not raw:
            return None
        session = json.loads(raw)
        if not isinstance(session, dict):
            return None
        expires_at = float(session.get("expires_at", 0) or 0)
        if expires_at <= time.time():
            await client.delete(_session_key(session_id))
            return None
        return session
    except Exception:
        logger.warning("Lecture session dashboard Redis impossible.", exc_info=True)
        return None


async def _store_session(
    app: web.Application,
    session_id: str,
    session: dict[str, Any],
    *,
    force: bool = False,
) -> None:
    client = _redis(app)
    if client is None:
        return

    now = time.time()
    expires_at = float(session.get("expires_at", 0) or 0)
    ttl = int(expires_at - now)
    if ttl <= 0:
        try:
            await client.delete(_session_key(session_id))
        except Exception:
            pass
        return

    sync_times: dict[str, float] = app[_SYNC_APP_KEY]
    if not force and now - sync_times.get(session_id, 0.0) < SYNC_INTERVAL_SECONDS:
        return

    try:
        payload = json.dumps(session, separators=(",", ":"), ensure_ascii=False)
        await client.set(_session_key(session_id), payload, ex=max(1, ttl))
        sync_times[session_id] = now
    except Exception:
        logger.warning("Écriture session dashboard Redis impossible.", exc_info=True)


async def _delete_session(app: web.Application, session_id: str) -> None:
    app.get(_SYNC_APP_KEY, {}).pop(session_id, None)
    client = _redis(app)
    if client is None:
        return
    try:
        await client.delete(_session_key(session_id))
    except Exception:
        logger.warning("Suppression session dashboard Redis impossible.", exc_info=True)


async def _store_oauth_state(app: web.Application, state: str, expires_at: float) -> None:
    client = _redis(app)
    if client is None or not state:
        return
    ttl = max(1, int(expires_at - time.time()))
    try:
        await client.set(_state_key(state), str(expires_at), ex=ttl)
    except Exception:
        logger.warning("Écriture state OAuth Redis impossible.", exc_info=True)


async def _hydrate_oauth_state(app: web.Application, state: str) -> None:
    if not state or state in app["oauth_states"]:
        return
    client = _redis(app)
    if client is None:
        return
    try:
        raw = await client.get(_state_key(state))
        if raw:
            expires_at = float(raw)
            if expires_at > time.time():
                app["oauth_states"][state] = expires_at
    except Exception:
        logger.warning("Lecture state OAuth Redis impossible.", exc_info=True)


async def _delete_oauth_state(app: web.Application, state: str) -> None:
    client = _redis(app)
    if client is None or not state:
        return
    try:
        await client.delete(_state_key(state))
    except Exception:
        pass


def _make_browser_session_cookie(
    response: web.StreamResponse,
    request: web.Request,
    dashboard,
    session_id: str,
) -> None:
    """Cookie de session navigateur : aucun Max-Age/Expires persistant."""
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
        morsel["max-age"] = ""
        morsel["expires"] = ""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    dashboard.SESSION_TTL = SESSION_TTL_SECONDS

    original_login = dashboard.handle_login
    original_callback = dashboard.handle_callback
    original_logout = dashboard.handle_logout
    original_build_app = dashboard.build_app

    async def handle_login(request: web.Request):
        try:
            return await original_login(request)
        except web.HTTPFound as redirect:
            morsel = redirect.cookies.get(dashboard.OAUTH_STATE_COOKIE)
            if morsel is not None:
                state = morsel.value
                expires_at = float(
                    request.app["oauth_states"].get(
                        state, time.time() + dashboard.OAUTH_STATE_TTL
                    )
                )
                await _store_oauth_state(request.app, state, expires_at)
            raise

    async def handle_callback(request: web.Request):
        state = request.query.get("state", "")
        await _hydrate_oauth_state(request.app, state)
        try:
            return await original_callback(request)
        except web.HTTPFound as redirect:
            morsel = redirect.cookies.get(dashboard.SESSION_COOKIE)
            if morsel is not None:
                session_id = morsel.value
                session = request.app["sessions"].get(session_id)
                if session:
                    session["expires_at"] = time.time() + SESSION_TTL_SECONDS
                    _make_browser_session_cookie(
                        redirect, request, dashboard, session_id
                    )
                    await _store_session(
                        request.app, session_id, session, force=True
                    )
            raise
        finally:
            await _delete_oauth_state(request.app, state)

    async def handle_logout(request: web.Request):
        session_id = request.cookies.get(dashboard.SESSION_COOKIE, "")
        response = await original_logout(request)
        if session_id:
            await _delete_session(request.app, session_id)
        return response

    @web.middleware
    async def ha_session_hydrator(request: web.Request, handler):
        session_id = request.cookies.get(dashboard.SESSION_COOKIE)
        sessions = request.app["sessions"]

        # Un nouveau leader HA peut avoir un dictionnaire mémoire vide alors que le
        # navigateur possède toujours un cookie valide. Redis reconstruit la session
        # avant les middlewares de permissions et les handlers API.
        if session_id and session_id not in sessions:
            restored = await _load_session(request.app, session_id)
            if restored is not None:
                sessions[session_id] = restored
                logger.info("Session dashboard restaurée depuis Redis après bascule HA.")

        try:
            response = await handler(request)
        except web.HTTPException:
            if session_id and session_id in sessions:
                await _store_session(
                    request.app, session_id, sessions[session_id]
                )
            raise

        if session_id and session_id in sessions:
            await _store_session(request.app, session_id, sessions[session_id])
        return response

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        # Doit être avant admin_only_dashboard : sinon le premier appel après failover
        # reçoit 401 avant d'avoir pu recharger la session Redis.
        app.middlewares.insert(0, ha_session_hydrator)
        app.on_startup.append(_clear_legacy_sessions)
        app.on_startup.append(_start_redis)
        app.on_cleanup.append(_stop_redis)
        return app

    dashboard.handle_login = handle_login
    dashboard.handle_callback = handle_callback
    dashboard.handle_logout = handle_logout
    dashboard.build_app = build_app

    logger.info(
        "Sessions dashboard : cookie navigateur + réplication Redis HA (TTL 2 h)."
    )
