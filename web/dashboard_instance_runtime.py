"""Rend l'identité publique du dashboard cohérente avec l'instance Railway."""
from __future__ import annotations

import json
from aiohttp import web
from utils.instance_identity import brand_label


def install(dashboard) -> None:
    if getattr(dashboard, "_sentrix_instance_public_api", False):
        return
    brand = brand_label()
    if brand.casefold() == "sentrix":
        dashboard._sentrix_instance_public_api = True
        return

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
