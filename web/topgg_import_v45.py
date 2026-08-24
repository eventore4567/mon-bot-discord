from __future__ import annotations

from aiohttp import web

_INSTALLED = False


def _type_value(command):
    value = getattr(command, "type", 1)
    raw = getattr(value, "value", value)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 1


def _serialize(commands):
    payload = []
    seen = set()
    for command in commands:
        if _type_value(command) != 1:
            continue
        name = str(getattr(command, "name", "") or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        description = str(getattr(command, "description", "") or "Commande SentriX").strip()
        payload.append({
            "name": name[:32],
            "description": (description or "Commande SentriX")[:100],
            "type": 1,
        })
    return payload


async def topgg_import_commands(request):
    bot = request.app["bot"]
    tree = getattr(bot, "tree", None)
    if tree is None:
        return web.json_response({"error": "command_tree_unavailable"}, status=503)

    try:
        commands = list(await tree.fetch_commands())
    except Exception:
        try:
            commands = list(tree.get_commands())
        except Exception:
            commands = []

    payload = _serialize(commands)
    if not payload:
        return web.json_response({"error": "no_commands_found"}, status=503)

    return web.json_response(
        payload,
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


def install(dashboard):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app.router.add_get("/api/topgg-import.json", topgg_import_commands)
        return app

    dashboard.build_app = build_app
