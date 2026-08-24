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


def _snowflake(value):
    if value is None:
        return None
    raw = getattr(value, "id", value)
    try:
        return str(int(raw))
    except (TypeError, ValueError):
        text = str(raw or "").strip()
        return text or None


def _clean_choice(choice):
    if hasattr(choice, "to_dict"):
        try:
            choice = choice.to_dict()
        except Exception:
            return None
    if not isinstance(choice, dict):
        return None
    name = str(choice.get("name") or "").strip()
    if not name or "value" not in choice:
        return None
    return {"name": name[:100], "value": choice.get("value")}


def _clean_option(option):
    if hasattr(option, "to_dict"):
        try:
            option = option.to_dict()
        except Exception:
            return None
    if not isinstance(option, dict):
        return None

    result = {}
    for key in (
        "type", "name", "description", "required", "channel_types",
        "min_value", "max_value", "min_length", "max_length", "autocomplete",
    ):
        if key in option and option[key] is not None:
            result[key] = option[key]

    choices = [_clean_choice(x) for x in (option.get("choices") or [])]
    choices = [x for x in choices if x is not None]
    if choices:
        result["choices"] = choices

    nested = [_clean_option(x) for x in (option.get("options") or [])]
    nested = [x for x in nested if x is not None]
    if nested:
        result["options"] = nested

    if not result.get("name") or "type" not in result:
        return None
    return result


def _legacy_command(command):
    """Schéma Discord classique accepté par les anciens importeurs de slash commands.

    Top.gg possède un import manuel distinct de son API v1. On retire volontairement
    les champs Discord récents (contexts, integration_types, handlers, localizations, etc.)
    qui peuvent faire échouer un parseur plus ancien, tout en conservant les champs de
    réponse Discord historiques : ids, version, permissions et options.
    """
    try:
        raw = command.to_dict()
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}

    name = str(raw.get("name") or getattr(command, "name", "") or "").strip().lower()
    description = str(
        raw.get("description") or getattr(command, "description", "") or "Commande SentriX"
    ).strip()

    item = {
        "type": 1,
        "name": name[:32],
        "description": (description or "Commande SentriX")[:100],
    }

    command_id = _snowflake(raw.get("id") or getattr(command, "id", None))
    application_id = _snowflake(raw.get("application_id") or getattr(command, "application_id", None))
    version = _snowflake(raw.get("version") or getattr(command, "version", None))
    if command_id:
        item["id"] = command_id
    if application_id:
        item["application_id"] = application_id
    if version:
        item["version"] = version

    options = [_clean_option(x) for x in (raw.get("options") or [])]
    options = [x for x in options if x is not None]
    if options:
        item["options"] = options

    # Champs historiques de Discord. Les valeurs nulles sont valides pour
    # default_member_permissions dans la réponse REST Discord.
    if "default_member_permissions" in raw:
        perms = raw.get("default_member_permissions")
        item["default_member_permissions"] = None if perms is None else str(perms)
    else:
        item["default_member_permissions"] = None

    item["dm_permission"] = bool(raw.get("dm_permission", True))
    item["default_permission"] = bool(raw.get("default_permission", True))
    item["nsfw"] = bool(raw.get("nsfw", False))
    return item


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

    payload = []
    seen = set()
    for command in commands:
        if _type_value(command) != 1:
            continue
        item = _legacy_command(command)
        name = item.get("name", "")
        if not name or name in seen:
            continue
        seen.add(name)
        payload.append(item)

    if not payload:
        return web.json_response({"error": "no_commands_found"}, status=503)

    # Diagnostic pratique : ?limit=1 permet de vérifier le parseur Top.gg avec
    # une seule commande avant d'importer les 100 commandes globales.
    try:
        limit = int(request.query.get("limit", "0") or 0)
    except ValueError:
        limit = 0
    if limit > 0:
        payload = payload[: min(limit, 100)]

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
