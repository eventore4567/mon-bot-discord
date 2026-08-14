"""Rend l'identité publique du dashboard cohérente avec l'instance Railway.

Ce module installe aussi un petit relais de télémétrie slash inter-instance. Les services
SentriX et Bot'Odboug partagent le même code mais peuvent utiliser des stockages Redis
séparés ; le relais permet donc au dashboard principal de voir quelle instance reçoit
réellement une interaction Discord, sans exposer de contenu utilisateur ni de secret.
"""
from __future__ import annotations

import json
import time

from aiohttp import web

from utils.instance_identity import brand_label

_RUNTIME_RELAY_PATH = "/api/runtime/slash-heartbeat"
_RUNTIME_RELAY_MAX_AGE_SECONDS = 900
_RUNTIME_RELAY_MAX_ITEMS = 20


def _clean_text(value, *, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def _clean_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_bool(value):
    if value is None:
        return None
    return bool(value)


def _sanitize_runtime_payload(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None

    service = _clean_text(payload.get("service"), limit=120)
    service_id = _clean_text(payload.get("service_id"), limit=120)
    bot_user_id = _clean_text(payload.get("bot_user_id"), limit=40)
    if not service and not service_id and not bot_user_id:
        return None

    return {
        "service": service or "unknown",
        "service_id": service_id,
        "brand": _clean_text(payload.get("brand"), limit=48),
        "bot_user_id": bot_user_id,
        "bot_user_name": _clean_text(payload.get("bot_user_name"), limit=120),
        "runtime_installed": bool(payload.get("runtime_installed")),
        "watchdog_listener_registered": bool(payload.get("watchdog_listener_registered")),
        "completion_guard_registered": bool(payload.get("completion_guard_registered")),
        "last_interaction_seen_at": _clean_int(payload.get("last_interaction_seen_at")),
        "last_command_name": _clean_text(payload.get("last_command_name"), limit=120),
        "last_completion_at": _clean_int(payload.get("last_completion_at")),
        "last_response_type": _clean_text(payload.get("last_response_type"), limit=80),
        "last_response_done": _clean_bool(payload.get("last_response_done")),
        "last_original_had_payload": _clean_bool(payload.get("last_original_had_payload")),
        "last_result": _clean_text(payload.get("last_result"), limit=80),
        "last_error": _clean_text(payload.get("last_error"), limit=120),
        "updated_at": _clean_int(payload.get("updated_at")),
    }


async def _handle_runtime_slash_heartbeat(request: web.Request) -> web.Response:
    if request.content_length is not None and request.content_length > 16 * 1024:
        return web.json_response({"ok": False, "error": "payload_too_large"}, status=413)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

    clean = _sanitize_runtime_payload(payload)
    if clean is None:
        return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)

    now = int(time.time())
    clean["received_at"] = now
    relays = request.app.get("slash_runtime_relays")
    if not isinstance(relays, dict):
        relays = {}
        request.app["slash_runtime_relays"] = relays

    key = f"{clean.get('service_id') or clean.get('service')}:{clean.get('bot_user_id') or 'unknown'}"
    relays[key] = clean

    stale = [
        relay_key
        for relay_key, item in relays.items()
        if not isinstance(item, dict)
        or now - int(item.get("received_at") or 0) > _RUNTIME_RELAY_MAX_AGE_SECONDS
    ]
    for relay_key in stale:
        relays.pop(relay_key, None)

    if len(relays) > _RUNTIME_RELAY_MAX_ITEMS:
        oldest = sorted(
            relays,
            key=lambda relay_key: int((relays.get(relay_key) or {}).get("received_at") or 0),
        )
        for relay_key in oldest[: len(relays) - _RUNTIME_RELAY_MAX_ITEMS]:
            relays.pop(relay_key, None)

    return web.json_response({"ok": True})


def _install_runtime_relay_route(dashboard) -> None:
    if getattr(dashboard, "_sentrix_cross_instance_runtime_route", False):
        return

    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app["slash_runtime_relays"] = {}
        app.router.add_post(_RUNTIME_RELAY_PATH, _handle_runtime_slash_heartbeat)
        return app

    dashboard.build_app = build_app
    dashboard._sentrix_cross_instance_runtime_route = True


def install(dashboard) -> None:
    if getattr(dashboard, "_sentrix_instance_public_api", False):
        return

    _install_runtime_relay_route(dashboard)

    brand = brand_label()
    if brand.casefold() != "sentrix":
        original = dashboard.handle_public

        async def handle_public(request: web.Request):
            response = await original(request)
            try:
                payload = json.loads(response.text or "{}")
            except Exception:
                return response
            if isinstance(payload, dict):
                payload["bot_name"] = brand
                return web.json_response(payload, status=response.status, headers={"Cache-Control": "no-store"})
            return response

        dashboard.handle_public = handle_public

    dashboard._sentrix_instance_public_api = True
