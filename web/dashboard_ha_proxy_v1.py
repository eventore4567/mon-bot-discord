"""Proxy HA du dashboard SentriX.

Le domaine public officiel peut pointer vers une instance HA passive. Cette instance doit
continuer a exposer son /health local, mais les pages du dashboard, OAuth et API doivent
etre servies par l'instance qui possede le lease Redis et donc l'etat Discord vivant.

Le proxy reste interne a Railway (railway.internal), conserve les cookies/redirects et
ajoute une garde anti-boucle. Aucun secret n'est expose au navigateur.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web
from multidict import CIMultiDict

logger = logging.getLogger("bot.dashboard-ha-proxy")

_LOCAL_ONLY_PATHS = frozenset({"/health", "/ready"})
_HOP_BY_HOP = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})
_PROXY_HEADER = "X-SentriX-HA-Proxy"
_SESSION_KEY = "sentrix_ha_dashboard_proxy_session"
_INSTALLED = False


def _truthy_env(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _peer_base_url(role: str) -> str:
    role = (role or "").strip().lower()
    if role == "primary":
        configured = (os.getenv("SENTRIX_HA_STANDBY_INTERNAL_URL", "") or "").strip().rstrip("/")
        return configured or "http://sentrix-standby.railway.internal:8080"
    if role == "standby":
        configured = (os.getenv("SENTRIX_HA_PRIMARY_INTERNAL_URL", "") or "").strip().rstrip("/")
        return configured or "http://mon-bot-discord.railway.internal:8080"
    return ""


def _runtime_state(bot: Any, coordinator: Any | None) -> tuple[bool, bool, str, str]:
    live = coordinator or getattr(bot, "_sentrix_ha_coordinator", None)
    if live is not None:
        return (
            bool(getattr(live, "enabled", False)),
            bool(getattr(live, "is_leader", False)),
            str(getattr(live, "role", "") or "").strip().lower(),
            str(getattr(live, "state", "starting") or "starting").strip().lower(),
        )

    # Petite fenetre entre le demarrage HTTP et l'attachement du coordinateur au bot.
    # On garde un fallback environnemental sans inventer un leader : si Discord est deja
    # pret, cette instance est necessairement active ; sinon elle reste consideree passive.
    enabled = _truthy_env("SENTRIX_FAILOVER_ENABLED")
    role = (os.getenv("SENTRIX_FAILOVER_ROLE", "") or "").strip().lower()
    leader = bool(getattr(bot, "is_ready", lambda: False)()) if enabled else False
    return enabled, leader, role, "leader" if leader else "starting"


def _forward_headers(request: web.Request) -> CIMultiDict[str]:
    headers: CIMultiDict[str] = CIMultiDict()
    for name, value in request.headers.items():
        lowered = name.lower()
        if lowered in _HOP_BY_HOP or lowered in {"host", "content-length", _PROXY_HEADER.lower()}:
            continue
        headers.add(name, value)

    # Le leader doit reconstruire les URLs OAuth avec le domaine public vu par l'utilisateur,
    # pas avec son hostname railway.internal.
    forwarded_host = request.headers.get("X-Forwarded-Host") or request.host
    forwarded_proto = request.headers.get("X-Forwarded-Proto") or request.scheme
    headers["X-Forwarded-Host"] = forwarded_host.split(",")[0].strip()
    headers["X-Forwarded-Proto"] = forwarded_proto.split(",")[0].strip()
    headers[_PROXY_HEADER] = "1"
    return headers


def _response_headers(upstream) -> CIMultiDict[str]:
    headers: CIMultiDict[str] = CIMultiDict()
    for raw_name, raw_value in upstream.raw_headers:
        name = raw_name.decode("latin-1")
        value = raw_value.decode("latin-1")
        lowered = name.lower()
        if lowered in _HOP_BY_HOP or lowered == "content-length":
            continue
        headers.add(name, value)
    return headers


def install(dashboard_module: Any, coordinator: Any | None = None) -> None:
    """Installe le proxy avant la construction de l'application aiohttp."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard_module.build_app

    def build_app(bot):
        app = original_build_app(bot)

        @web.middleware
        async def leader_proxy(request: web.Request, handler):
            # Les sondes Railway doivent toujours decrire CETTE instance et ne jamais etre
            # masquees par le leader distant.
            if request.path in _LOCAL_ONLY_PATHS:
                return await handler(request)

            enabled, leader, role, state = _runtime_state(bot, coordinator)
            if not enabled or leader:
                return await handler(request)

            # Une requete deja proxifiee ne doit jamais rebondir entre les deux services.
            if request.headers.get(_PROXY_HEADER) == "1":
                return web.json_response(
                    {
                        "ok": False,
                        "error": "leader_unavailable",
                        "detail": "Aucune instance HA active ne peut servir le dashboard pour le moment.",
                        "ha_state": state,
                    },
                    status=503,
                )

            peer_base = _peer_base_url(role)
            if not peer_base:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "ha_peer_unknown",
                        "detail": "Le pair HA du dashboard n'est pas configure.",
                    },
                    status=503,
                )

            session: ClientSession = request.app[_SESSION_KEY]
            target = f"{peer_base}{request.rel_url}"
            try:
                body = await request.read()
                async with session.request(
                    request.method,
                    target,
                    headers=_forward_headers(request),
                    data=body if body else None,
                    allow_redirects=False,
                ) as upstream:
                    payload = await upstream.read()
                    return web.Response(
                        status=upstream.status,
                        body=payload,
                        headers=_response_headers(upstream),
                    )
            except Exception as exc:
                logger.warning(
                    "Proxy dashboard HA impossible role=%s state=%s target=%s: %s",
                    role,
                    state,
                    target,
                    exc,
                )
                return web.json_response(
                    {
                        "ok": False,
                        "error": "ha_leader_unreachable",
                        "detail": "Le dashboard actif est temporairement indisponible. Reessayez dans quelques secondes.",
                    },
                    status=503,
                )

        # Le proxy doit passer avant les middlewares applicatifs afin qu'une instance passive
        # ne tente jamais d'evaluer ses propres donnees Discord absentes.
        app.middlewares.insert(0, leader_proxy)

        async def start_proxy_session(_app):
            _app[_SESSION_KEY] = ClientSession(
                timeout=ClientTimeout(total=20, connect=5),
                auto_decompress=False,
            )

        async def stop_proxy_session(_app):
            session = _app.get(_SESSION_KEY)
            if session is not None and not session.closed:
                await session.close()

        app.on_startup.append(start_proxy_session)
        app.on_cleanup.append(stop_proxy_session)
        return app

    build_app._sentrix_ha_dashboard_proxy = True
    build_app._sentrix_original = original_build_app
    dashboard_module.build_app = build_app
    logger.info("Proxy dashboard HA leader-aware installe.")
