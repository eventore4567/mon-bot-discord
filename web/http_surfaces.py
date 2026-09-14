"""Public dashboard/API boundaries and authenticated HA HTTP transport.

The dashboard keeps its same-origin API facade so host-only browser sessions work
on Railway's separate public-suffix domains. The API origin exposes JSON routes;
it never gains OAuth, owner tools, or bot runtime endpoints.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import time
from urllib.parse import urlsplit

from aiohttp import web

logger = logging.getLogger("bot.http-surfaces")
SETTINGS_KEY = "sentrix_http_surfaces"
_CONTEXT_KEY = "sentrix_http_context"
_GUARDS_KEY = "sentrix_http_guards"
_SIGNATURE = "X-SentriX-Proxy-Signature"
_TIMESTAMP = "X-SentriX-Proxy-Timestamp"
_NONCE = "X-SentriX-Proxy-Nonce"
_HOST = "X-SentriX-Proxy-Host"
_CLIENT = "X-SentriX-Proxy-Client"
_HA = "X-SentriX-HA-Proxy"
_SIGNED_HEADERS = (_TIMESTAMP, _NONCE, _HOST, _CLIENT, "Origin", "Cookie", "Authorization", "Content-Type", "X-CSRF-Token")
_SAFE = frozenset({"GET", "HEAD", "OPTIONS"})
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
_CORS_HEADERS = frozenset({"accept", "authorization", "content-type", "x-csrf-token"})
_HEALTH = frozenset({"/health", "/ready"})
_FORBIDDEN_ROOTS = ("/internal", "/_internal", "/debug", "/_debug", "/metrics", "/admin", "/.env", "/.git", "/actuator")
_FORBIDDEN_API_ROOTS = ("/api/runtime", "/api/internal", "/api/debug", "/api/admin", "/api/metrics")
_MAX_CLIENTS = 4096
_HOP_TTL = 60


def _origin(value: str, name: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid HTTPS origin") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or any(char.isspace() for char in value)):
        raise ValueError(f"{name} must be an HTTPS origin without path, query or credentials")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}" + (f":{port}" if port not in {None, 443} else "")


def _positive_limit(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if not 1 <= value <= 100000:
        raise ValueError(f"{name} must be between 1 and 100000")
    return value


@dataclass(frozen=True)
class Settings:
    dashboard_origin: str
    api_origin: str
    secret: str
    rate_limit: int = 120
    write_rate_limit: int = 30
    trusted_proxy_cidrs: tuple = ()

    @property
    def enabled(self) -> bool:
        return bool(self.api_origin)

    @classmethod
    def from_env(cls):
        api = os.getenv("API_PUBLIC_URL", "").strip()
        dashboard = os.getenv("DASHBOARD_PUBLIC_URL", "").strip()
        secret = os.getenv("SENTRIX_HTTP_PROXY_SECRET", "").strip()
        if not api and not secret:
            return None
        if len(secret) < 32:
            raise ValueError("SENTRIX_HTTP_PROXY_SECRET must contain at least 32 characters")
        dashboard = _origin(dashboard, "DASHBOARD_PUBLIC_URL") if dashboard else ""
        api = _origin(api, "API_PUBLIC_URL") if api else ""
        if api and (not dashboard or dashboard == api):
            raise ValueError("DASHBOARD_PUBLIC_URL and API_PUBLIC_URL must be distinct HTTPS origins")
        networks = tuple(ipaddress.ip_network(value.strip()) for value in os.getenv(
            "SENTRIX_HTTP_TRUSTED_PROXY_CIDRS", "").split(",") if value.strip())
        if any(network.prefixlen == 0 for network in networks):
            raise ValueError("SENTRIX_HTTP_TRUSTED_PROXY_CIDRS cannot trust the whole Internet")
        return cls(dashboard, api, secret,
                   _positive_limit("SENTRIX_API_RATE_LIMIT", 120),
                   _positive_limit("SENTRIX_API_WRITE_RATE_LIMIT", 30), networks)


def _single(headers, name: str) -> str:
    values = headers.getall(name, []) if hasattr(headers, "getall") else ([headers[name]] if name in headers else [])
    if len(values) > 1:
        raise ValueError("Duplicate security header")
    return str(values[0]) if values else ""


def _authority(host: str) -> str:
    parsed = urlsplit("https://" + host)
    if not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Invalid Host")
    return _origin("https://" + host, "Host")[8:]


def _client_ip(request, settings: Settings) -> str:
    """Forwarded identity is opt-in and anchored to the actual TCP peer."""
    remote = request.remote or "unknown"
    try:
        peer = ipaddress.ip_address(remote)
        if any(peer in network for network in settings.trusted_proxy_cidrs):
            forwarded = _single(request.headers, "X-Real-IP")
            if forwarded:
                return str(ipaddress.ip_address(forwarded))
    except ValueError:
        pass
    return remote


def _signature(secret: str, method: str, path: str, body: bytes, headers) -> str:
    payload = ["sentrix-http-v1", method, path, hashlib.sha256(body).hexdigest()]
    payload.extend(_single(headers, name) for name in _SIGNED_HEADERS)
    return hmac.new(secret.encode(), json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode(), hashlib.sha256).hexdigest()


def sign_proxy_headers(request, headers, body: bytes | None):
    """Sign the already-read request for the existing private HA proxy hop."""
    settings = request.app.get(SETTINGS_KEY) or Settings.from_env()
    if settings is None:
        return headers
    clean = {name: value for name, value in headers.items()
             if not name.lower().startswith("x-sentrix-proxy-")
             and name.lower() not in {"host", "forwarded", "x-forwarded-for", "x-real-ip"}}
    context = request.get(_CONTEXT_KEY, {})
    original_host = context.get("host") or _authority(request.host)
    client = context.get("client") or _client_ip(request, settings)
    for name in ("Origin", "Cookie", "Authorization", "Content-Type", "X-CSRF-Token"):
        value = _single(request.headers, name)
        if value:
            clean[name] = value
    clean.update({_HA: "1", _TIMESTAMP: str(int(time.time())), _NONCE: secrets.token_hex(16),
                  _HOST: original_host, _CLIENT: client,
                  "X-Forwarded-Host": original_host, "X-Forwarded-Proto": "https"})
    clean[_SIGNATURE] = _signature(settings.secret, request.method, str(request.rel_url), body or b"", clean)
    return clean


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _blocked(path: str) -> bool:
    return any(_under(path, prefix) for prefix in (*_FORBIDDEN_ROOTS, *_FORBIDDEN_API_ROOTS))


def _public_api(request) -> bool:
    canonical = getattr(request.match_info.route.resource, "canonical", "")
    return (request.path == "/api/public" and request.method in {"GET", "HEAD"}
            or canonical == "/api/appeal/{token}" and request.method in {"GET", "HEAD", "POST"}
            or request.path == "/api/discordbotlist/vote" and request.method == "POST")


def _error(status: int, error: str) -> web.Response:
    return web.json_response({"ok": False, "error": error}, status=status)


def _health_payload(upstream, status: int, surface: str) -> dict:
    """Retain the companion's HA contract without publishing arbitrary errors."""
    payload = {"ok": 200 <= status < 400, "surface": surface}
    try:
        source = json.loads(upstream.body)
    except (AttributeError, TypeError, ValueError):
        return payload
    if not isinstance(source, dict):
        return payload
    if isinstance(source.get("ok"), bool):
        payload["ok"] = source["ok"] and payload["ok"]
    if isinstance(source.get("discord_ready"), bool):
        payload["discord_ready"] = source["discord_ready"]
    if "latency_ms" in source and (isinstance(source["latency_ms"], (int, float)) or source["latency_ms"] is None):
        payload["latency_ms"] = source.get("latency_ms")
    ha = source.get("failover")
    if isinstance(ha, dict):
        clean = {key: ha[key] for key in ("enabled", "leader") if isinstance(ha.get(key), bool)}
        for key, allowed in (("role", {"primary", "standby"}),
                             ("state", {"starting", "standby", "blocked", "leader", "disabled", "error", "yielding", "lost", "released"})):
            if ha.get(key) in allowed:
                clean[key] = ha[key]
        for key in ("ttl_seconds", "leader_for_seconds"):
            if isinstance(ha.get(key), (int, float)):
                clean[key] = ha[key]
        clean["error"] = "unavailable" if ha.get("error") else None
        payload["failover"] = clean
    return payload


def _finish(response, request, settings: Settings, surface: str):
    # Strip route-specific CORS (including the legacy directory webhook policy).
    for name in list(response.headers):
        if name.lower().startswith("access-control-"):
            response.headers.popall(name, None)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.path.startswith("/api/") or request.path in _HEALTH or response.status >= 400:
        response.headers["Cache-Control"] = "private, no-store"
    if request.path.startswith("/api/"):
        vary = [value.strip() for value in response.headers.get("Vary", "").split(",") if value.strip()]
        if "origin" not in {value.lower() for value in vary}:
            vary.append("Origin")
        response.headers["Vary"] = ", ".join(vary)
        if request.headers.get("Origin") == settings.dashboard_origin:
            response.headers["Access-Control-Allow-Origin"] = settings.dashboard_origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Expose-Headers"] = "Retry-After"
            if request.method == "OPTIONS" and response.status == 204:
                response.headers["Access-Control-Allow-Methods"] = request.headers["Access-Control-Request-Method"]
                response.headers["Access-Control-Allow-Headers"] = "Accept, Authorization, Content-Type, X-CSRF-Token"
                response.headers["Access-Control-Max-Age"] = "600"
    return response


def apply(app, dashboard):
    """Attach/reanchor guards after every final or recovery app construction."""
    existing = app.get(_GUARDS_KEY)
    if existing is not None:
        outer, auth = existing
        for guard in existing:
            if guard in app.middlewares:
                app.middlewares.remove(guard)
        _anchor(app, outer, auth)
        return app
    settings = Settings.from_env()
    if settings is None:
        return app
    app[SETTINGS_KEY] = settings
    nonces = OrderedDict()
    clients = OrderedDict()

    async def resolve_context(request):
        host = _authority(_single(request.headers, "Host") or request.host)
        signature = _single(request.headers, _SIGNATURE)
        markers = any(name.lower().startswith("x-sentrix-proxy-") for name in request.headers)
        public_hosts = {value[8:] for value in (settings.dashboard_origin, settings.api_origin) if value}
        if markers:
            if not signature or host in public_hosts or _single(request.headers, _HA) != "1":
                raise ValueError("Invalid proxy authentication")
            stamp = int(_single(request.headers, _TIMESTAMP))
            if abs(time.time() - stamp) > _HOP_TTL:
                raise ValueError("Expired proxy authentication")
            nonce = _single(request.headers, _NONCE)
            if len(nonce) != 32:
                raise ValueError("Invalid proxy nonce")
            body = await request.read()
            expected = _signature(settings.secret, request.method, str(request.rel_url), body, request.headers)
            if not hmac.compare_digest(signature, expected):
                raise ValueError("Invalid proxy authentication")
            now = time.time()
            while nonces and next(iter(nonces.values())) < now - _HOP_TTL * 2:
                nonces.popitem(last=False)
            if nonce in nonces or len(nonces) >= _MAX_CLIENTS:
                raise ValueError("Replayed proxy authentication")
            nonces[nonce] = now
            host = _authority(_single(request.headers, _HOST))
            client = _single(request.headers, _CLIENT)
            if not client or len(client) > 100:
                raise ValueError("Invalid proxy client")
            return {"host": host, "client": client, "proxied": True}
        if settings.enabled and _single(request.headers, _HA):
            raise ValueError("Unauthenticated proxy header")
        return {"host": host, "client": _client_ip(request, settings), "proxied": False}

    def rate_limit(request, session):
        context = request[_CONTEXT_KEY]
        if session is not None:
            # Only a session validated/hydrated by the application may identify a user.
            identity = "session:" + hashlib.sha256(str(request.cookies.get(dashboard.SESSION_COOKIE, "")).encode()).hexdigest()
        else:
            identity = "client:" + context["client"]
        now = time.monotonic()
        while clients and next(iter(clients.values()))[0] <= now - 60:
            clients.popitem(last=False)
        record = clients.get(identity)
        if record is None or record[0] <= now - 60:
            if len(clients) >= _MAX_CLIENTS:
                response = _error(429, "rate_limited")
                response.headers["Retry-After"] = "60"
                return response
            record = [now, 0, 0]
            clients[identity] = record
        writing = request.method not in _SAFE
        if record[1] >= settings.rate_limit or writing and record[2] >= settings.write_rate_limit:
            response = _error(429, "rate_limited")
            response.headers["Retry-After"] = str(max(1, int(61 - (now - record[0]))))
            return response
        record[1] += 1
        record[2] += int(writing)
        return None

    @web.middleware
    async def surface_auth(request, handler):
        if not settings.enabled or not (request.path.startswith("/api/") or request.path == "/logout"):
            return await handler(request)
        session = dashboard._session(request)
        limited = rate_limit(request, session)
        if limited is not None:
            return limited
        if not _public_api(request):
            session, error = dashboard._require_session(request)
            if error is not None:
                return error
            if request.method not in _SAFE:
                error = dashboard._require_csrf(request, session)
                if error is not None:
                    return error
        return await handler(request)

    @web.middleware
    async def surface_boundary(request, handler):
        surface = "unknown"
        try:
            try:
                context = await resolve_context(request)
            except (ValueError, TypeError):
                response = _error(403, "invalid_proxy")
                return _finish(response, request, settings, surface) if settings.enabled else response
            request[_CONTEXT_KEY] = context
            if not settings.enabled:
                return await handler(request)
            host = context["host"]
            surface = ("dashboard" if host == settings.dashboard_origin[8:] else
                       "api" if host == settings.api_origin[8:] else "unknown")
            path = request.path
            if path in _HEALTH:
                upstream = None
                try:
                    upstream = await handler(request)
                    status = upstream.status
                except web.HTTPException as exc:
                    status = exc.status
                except Exception:
                    logger.exception("HTTP health handler failed")
                    status = 500
                response = web.json_response(_health_payload(upstream, status, surface), status=status)
                return _finish(response, request, settings, surface)
            if surface == "unknown" or _blocked(path) or surface == "api" and _under(path, "/api/owner"):
                return _finish(_error(404, "not_found"), request, settings, surface)
            is_api = path.startswith("/api/")
            if surface == "api" and not is_api:
                return _finish(_error(404, "not_found"), request, settings, surface)
            origin = _single(request.headers, "Origin")
            if (is_api or request.method not in _SAFE) and origin and origin != settings.dashboard_origin:
                return _finish(_error(403, "origin_forbidden"), request, settings, surface)
            if is_api and request.method == "OPTIONS":
                method = _single(request.headers, "Access-Control-Request-Method")
                requested = {value.strip().lower() for value in _single(request.headers, "Access-Control-Request-Headers").split(",") if value.strip()}
                if origin != settings.dashboard_origin or method not in _METHODS or not requested <= _CORS_HEADERS:
                    return _finish(_error(403, "preflight_forbidden"), request, settings, surface)
                match = await app.router.resolve(request.clone(method=method))
                if match.http_exception is not None:
                    return _finish(_error(404, "not_found"), request, settings, surface)
                return _finish(web.Response(status=204), request, settings, surface)
            if is_api and request.match_info.http_exception is not None:
                return _finish(_error(404, "not_found"), request, settings, surface)
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc
        except Exception:
            logger.exception("Public HTTP request failed")
            response = _error(500, "internal_error")
        return _finish(response, request, settings, surface) if settings.enabled else response

    surface_boundary._sentrix_http_boundary = True
    surface_auth._sentrix_http_auth = True
    app[_GUARDS_KEY] = (surface_boundary, surface_auth)
    _anchor(app, surface_boundary, surface_auth)
    return app


def _anchor(app, outer, auth):
    app.middlewares.insert(0, outer)
    index = next((index + 1 for index, middleware in enumerate(app.middlewares)
                  if getattr(middleware, "_sentrix_session_hydrator", False)
                  or getattr(middleware, "__name__", "") == "ha_session_hydrator"), 1)
    app.middlewares.insert(index, auth)
