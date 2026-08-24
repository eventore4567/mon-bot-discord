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


def _minimal_command(command):
    name = str(getattr(command, "name", "") or "").strip().lower()
    description = str(getattr(command, "description", "") or "Commande SentriX").strip()
    return {
        "name": name[:32],
        "description": (description or "Commande SentriX")[:100],
        "type": 1,
    }


def _serialize_full_discord(commands):
    """Renvoie le payload Discord complet attendu par l'import manuel Top.gg.

    tree.fetch_commands() renvoie les commandes réellement enregistrées chez Discord.
    Le parseur manuel de Top.gg est plus strict que son endpoint API, donc on conserve
    les champs Discord (id, application_id, version, options, permissions, contexts, etc.)
    quand discord.py les expose via AppCommand.to_dict().
    """
    payload = []
    seen = set()

    for command in commands:
        if _type_value(command) != 1:
            continue

        name = str(getattr(command, "name", "") or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)

        try:
            item = command.to_dict()
        except Exception:
            item = _minimal_command(command)

        if not isinstance(item, dict):
            item = _minimal_command(command)

        # Garanties minimales Discord Application Command.
        item["name"] = name[:32]
        item["description"] = str(
            item.get("description") or getattr(command, "description", "") or "Commande SentriX"
        )[:100]
        item["type"] = 1

        payload.append(item)

    return payload


async def topgg_import_commands(request):
    bot = request.app["bot"]
    tree = getattr(bot, "tree", None)
    if tree is None:
        return web.json_response({"error": "command_tree_unavailable"}, status=503)

    # L'import Top.gg doit recevoir le payload Discord réel, pas seulement l'arbre local.
    try:
        commands = list(await tree.fetch_commands())
    except Exception:
        try:
            commands = list(tree.get_commands())
        except Exception:
            commands = []

    payload = _serialize_full_discord(commands)
    if not payload:
        return web.json_response({"error": "no_commands_found"}, status=503)

    return web.json_response(
        payload,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "Content-Disposition": 'inline; filename="sentrix-discord-commands.json"',
        },
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
