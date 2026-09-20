"""Harnais E2E : SentriX booté EXACTEMENT comme en production (chaîne v8), sans
gateway, avec l'API Discord remplacée par un faux serveur qui journalise chaque appel.

Ce que ce harnais attrape et qu'un test unitaire ne verra jamais : les ~20 enveloppes
qui réassignent callbacks / `Context.send` / `log_sanction` au boot, les conversions
d'arguments réelles (`commands.Range`, mentions), les limites Discord appliquées par
discord.py lui-même (ex. bulk-delete > 100 → ClientException, SXR-CMD-0001 de
``+clear 100``).

Utilisé par ``tools/command_sweep.py`` (balayage de toutes les commandes) et
utilisable à la main :

    python3 tools/sentrix_e2e_harness.py "+clear 100" "/clear nombre=100"

Aucune connexion réseau : Discord, OpenAI et toute session aiohttp sortante sont
coupés. Base SQLite temporaire, Redis/Postgres désactivés.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import pathlib
import re
import sys
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Environnement AVANT tout import du dépôt (config.DATABASE_PATH est figé au 1er import).
_TMP = tempfile.mkdtemp(prefix="sentrix-e2e-")
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
os.environ["DATABASE_PATH"] = str(pathlib.Path(_TMP) / "sentrix-e2e.db")
for _var in ("POSTGRES_URL", "DATABASE_URL", "REDIS_URL", "OPENAI_API_KEY"):
    os.environ.pop(_var, None)
os.environ["SENTRIX_FAILOVER_ENABLED"] = "0"
os.environ.setdefault("SENTRIX_E2E_HARNESS", "1")

import discord  # noqa: E402
from discord.http import Route  # noqa: E402

# Snowflakes à 18+ chiffres : en dessous, MemberConverter ne résout pas les mentions.
GID = 100000000000000001
CID = 100000000000000007            # #general (texte)
LOGCID = 100000000000000008         # #logs (texte)
VOICE_CID = 100000000000000009      # #vocal
CATEGORY_ID = 100000000000000010
BOT_ID = 100000000000424242
AUTHOR_ID = 100000000000000042      # propriétaire du serveur + rôle Admin
TARGET_ID = 100000000000000077      # membre cible (rôle Membre)
SECOND_ID = 100000000000000078      # second membre (rôle Membre)
ADMIN_ROLE_ID = 100000000000000100
BOT_ROLE_ID = 100000000000000101
MEMBER_ROLE_ID = 100000000000000102
PING_ROLE_ID = 100000000000000103

CALLS: list[tuple[str, str, Any]] = []
STATE: dict[str, Any] = {
    "target_timeout": None, "target_nick": None, "target_roles": [MEMBER_ROLE_ID],
    "msg_seq": 5000, "cmd_seq": 800000000000000000, "last_cmd_id": None, "last_cmd_content": "",
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def user(uid: int, name: str) -> dict:
    return {"id": str(uid), "username": name, "discriminator": "0", "avatar": None,
            "bot": uid == BOT_ID, "global_name": name}


def member_payload(uid: int, name: str, roles, nick=None, timeout=None) -> dict:
    return {"user": user(uid, name), "roles": [str(r) for r in roles],
            "joined_at": "2026-01-01T00:00:00+00:00", "deaf": False, "mute": False, "flags": 0,
            "nick": nick, "communication_disabled_until": timeout, "pending": False}


def message_payload(mid: int, cid: int, content, author_id: int = BOT_ID, name: str = "SentriX") -> dict:
    return {"id": str(mid), "channel_id": str(cid), "guild_id": str(GID), "author": user(author_id, name),
            "content": content or "", "timestamp": _now(), "edited_timestamp": None, "tts": False,
            "mention_everyone": False, "mentions": [], "mention_roles": [], "attachments": [],
            "embeds": [], "pinned": False, "type": 0, "flags": 0, "components": []}


def _payload_from_form(form) -> Any:
    if not form:
        return None
    for part in form:
        if isinstance(part, dict) and part.get("name") == "payload_json":
            try:
                return json.loads(part["value"])
            except Exception:
                return None
    return None


async def fake_request(self, route, *, files=None, form=None, **kwargs):
    """Remplace discord.http.HTTPClient.request : journalise et répond de façon plausible."""
    method, path = route.method, route.url.replace(Route.BASE, "")
    js = kwargs.get("json")
    if js is None:
        js = _payload_from_form(form)
    CALLS.append((method, path, js))
    channel_id = int(path.split("/")[2]) if path.startswith("/channels/") and path.split("/")[2].isdigit() else CID

    m = re.match(r"/guilds/(\d+)/members/(\d+)$", path)
    if m and method == "PATCH":
        if "communication_disabled_until" in (js or {}):
            STATE["target_timeout"] = js["communication_disabled_until"]
        if "nick" in (js or {}):
            STATE["target_nick"] = js["nick"]
        if "roles" in (js or {}):
            STATE["target_roles"] = [int(r) for r in js["roles"]]
        return member_payload(int(m.group(2)), "cible", STATE["target_roles"], STATE["target_nick"], STATE["target_timeout"])
    if m and method == "GET":
        return member_payload(int(m.group(2)), "cible", STATE["target_roles"], STATE["target_nick"], STATE["target_timeout"])
    if m and method == "DELETE":
        return None
    if re.match(r"/guilds/\d+/members$", path):
        return []
    if re.match(r"/guilds/\d+/bans/\d+$", path):
        if method == "GET":
            return {"reason": None, "user": user(TARGET_ID, "cible")}
        return None
    if re.match(r"/guilds/\d+/bans$", path):
        return []
    if re.match(r"/guilds/\d+/members/\d+/roles/\d+$", path):
        return None
    if re.match(r"/guilds/\d+/roles$", path) and method == "POST":
        STATE["msg_seq"] += 1
        return {"id": str(STATE["msg_seq"]), "name": (js or {}).get("name") or "role", "permissions": "0",
                "position": 1, "color": (js or {}).get("color") or 0, "hoist": False, "managed": False, "mentionable": False}
    if re.match(r"/guilds/\d+/roles(/\d+)?$", path):
        return [] if method == "GET" else None
    if re.match(r"/guilds/\d+/channels$", path) and method == "POST":
        STATE["msg_seq"] += 1
        return {"id": str(STATE["msg_seq"]), "type": (js or {}).get("type", 0), "name": (js or {}).get("name") or "salon",
                "position": 9, "permission_overwrites": [], "nsfw": False, "parent_id": (js or {}).get("parent_id"), "guild_id": str(GID)}
    if re.match(r"/guilds/\d+/channels$", path):
        return None
    if re.match(r"/guilds/\d+/emojis", path):
        return [] if method == "GET" else None
    if re.match(r"/guilds/\d+/invites$", path) or re.match(r"/channels/\d+/invites$", path):
        if method == "POST":
            return {"code": "sentrix", "guild": {"id": str(GID), "name": "Serveur test"}, "channel": {"id": str(CID), "type": 0, "name": "general"},
                    "inviter": user(BOT_ID, "SentriX"), "uses": 0, "max_uses": 0, "max_age": 0, "temporary": False, "created_at": _now()}
        return []
    if re.match(r"/guilds/\d+/audit-logs$", path):
        return {"audit_log_entries": [], "users": [], "webhooks": [], "integrations": [], "threads": [],
                "application_commands": [], "auto_moderation_rules": [], "guild_scheduled_events": []}
    if re.match(r"/guilds/\d+/auto-moderation/rules", path):
        return [] if method == "GET" else {"id": "1", "guild_id": str(GID), "name": "regle", "creator_id": str(BOT_ID),
                                           "event_type": 1, "trigger_type": 1, "trigger_metadata": {}, "actions": [], "enabled": True,
                                           "exempt_roles": [], "exempt_channels": []}
    if re.match(r"/guilds/\d+/scheduled-events", path):
        return [] if method == "GET" else None
    if re.match(r"/guilds/\d+/prune", path):
        return {"pruned": 0}
    if re.match(r"/guilds/\d+/vanity-url$", path):
        return {"code": None, "uses": 0}
    if re.match(r"/guilds/\d+/webhooks$", path) or re.match(r"/channels/\d+/webhooks$", path):
        if method == "POST":
            return {"id": "100000000000000999", "type": 1, "guild_id": str(GID), "channel_id": str(channel_id),
                    "name": "SentriX", "token": "whtok", "application_id": None, "user": user(BOT_ID, "SentriX")}
        return []
    if re.match(r"/guilds/\d+$", path):
        return None
    if re.match(r"/channels/\d+/messages$", path) and method == "POST":
        STATE["msg_seq"] += 1
        return message_payload(STATE["msg_seq"], channel_id, (js or {}).get("content"))
    if re.match(r"/channels/\d+/messages$", path) and method == "GET":
        limit = int((kwargs.get("params") or {}).get("limit", 5))
        out = []
        if STATE.get("last_cmd_id") and not (kwargs.get("params") or {}).get("before"):
            out.append(message_payload(STATE["last_cmd_id"], channel_id, STATE["last_cmd_content"], AUTHOR_ID, "jayden"))
        # Snowflakes datés : discord.py déduit created_at de l'identifiant (pas du champ
        # timestamp) et bascule en suppression unitaire au-delà de 14 jours.
        base = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
        out += [message_payload(discord.utils.time_snowflake(base - dt.timedelta(seconds=i)), channel_id, f"msg {i}", TARGET_ID, "cible")
                for i in range(max(0, limit - len(out)))]
        return out
    if re.match(r"/channels/\d+/messages/bulk-delete$", path):
        return None
    if re.match(r"/channels/\d+/messages/\d+/reactions", path):
        return [] if method == "GET" else None
    if re.match(r"/channels/\d+/messages/\d+/threads$", path) or re.match(r"/channels/\d+/threads$", path):
        STATE["msg_seq"] += 1
        return {"id": str(STATE["msg_seq"]), "type": 11, "name": (js or {}).get("name") or "fil", "guild_id": str(GID),
                "parent_id": str(channel_id), "owner_id": str(BOT_ID), "message_count": 0, "member_count": 1,
                "thread_metadata": {"archived": False, "auto_archive_duration": 1440, "archive_timestamp": _now(), "locked": False}}
    if re.match(r"/channels/\d+/messages/\d+/crosspost$", path):
        return message_payload(int(path.split("/")[4]), channel_id, "")
    if re.match(r"/channels/\d+/messages/\d+$", path):
        if method == "DELETE":
            return None
        return message_payload(int(path.split("/")[-1]), channel_id, (js or {}).get("content"))
    if re.match(r"/channels/\d+/pins", path):
        return [] if method == "GET" else None
    if re.match(r"/channels/\d+/permissions/\d+$", path):
        return None
    if re.match(r"/channels/\d+/typing$", path):
        return None
    if re.match(r"/channels/\d+/thread-members", path):
        return None
    if re.match(r"/channels/\d+$", path):
        if method == "DELETE":
            return {"id": str(channel_id), "type": 0, "name": "supprime", "guild_id": str(GID)}
        if method == "PATCH":
            return {"id": str(channel_id), "type": 0, "name": (js or {}).get("name") or "general", "position": 0,
                    "permission_overwrites": [], "nsfw": False, "parent_id": None, "guild_id": str(GID)}
        return None
    if path == "/users/@me/channels":
        return {"id": "100000000000009001", "type": 1, "recipients": [user(TARGET_ID, "cible")], "last_message_id": None}
    if path.startswith("/users/@me/guilds"):
        return []
    m = re.match(r"/users/(\d+)$", path)
    if m:
        return user(int(m.group(1)), "cible")
    if path == "/users/@me":
        return user(BOT_ID, "SentriX")
    if re.match(r"/interactions/\d+/[^/]+/callback$", path):
        return {"interaction": {"id": path.split("/")[2], "type": 2, "activity_instance_id": None,
                                "response_message_id": None, "response_message_loading": True,
                                "response_message_ephemeral": False}, "resource": None}
    if re.match(r"/webhooks/\d+/[^/]+$", path) and method == "POST":
        STATE["msg_seq"] += 1
        return message_payload(STATE["msg_seq"], CID, (js or {}).get("content"))
    if re.match(r"/webhooks/\d+/[^/]+/messages/", path):
        return message_payload(9999, CID, (js or {}).get("content"))
    if re.match(r"/webhooks/\d+(/[^/]+)?$", path):
        return None
    if path.startswith("/applications/"):
        return []
    if path == "/oauth2/applications/@me":
        return {"id": str(BOT_ID), "name": "SentriX", "icon": None, "description": "", "bot_public": True,
                "bot_require_code_grant": False, "owner": user(AUTHOR_ID, "jayden"), "verify_key": "x", "flags": 0}
    if path.startswith("/gateway"):
        return {"url": "wss://gateway.discord.gg", "shards": 1, "session_start_limit": {"total": 1000, "remaining": 999, "reset_after": 0, "max_concurrency": 1}}
    if path.startswith("/stickers") or path.startswith("/sticker-packs"):
        return []
    if re.match(r"/invites/", path):
        return {"code": "sentrix", "guild": {"id": str(GID), "name": "Serveur test"}, "channel": {"id": str(CID), "type": 0, "name": "general"}}
    return {}


async def fake_webhook_request(self, route, session=None, *, payload=None, multipart=None, files=None,
                               reason=None, auth_token=None, params=None, **_kw):
    js = payload if payload is not None else _payload_from_form(multipart)
    path = route.url.replace(Route.BASE, "") if hasattr(route, "url") else route.path
    CALLS.append((route.method, path, js))
    if "/callback" in path:
        return {"interaction": {"id": path.split("/")[2], "type": 2, "activity_instance_id": None,
                                "response_message_id": None, "response_message_loading": True,
                                "response_message_ephemeral": False}, "resource": None}
    STATE["msg_seq"] += 1
    return message_payload(STATE["msg_seq"], CID, (js or {}).get("content") if isinstance(js, dict) else None)


def _cut_outbound_http() -> None:
    """Aucune requête sortante réelle (OpenAI, météo, traduction…) : échec immédiat et
    propre, comme une panne réseau — la commande doit se dégrader sans trace technique."""
    import aiohttp

    async def _no_network(self, method, url, **kwargs):
        raise aiohttp.ClientConnectionError(f"réseau coupé par le harnais E2E ({method} {url})")

    aiohttp.ClientSession._request = _no_network


async def boot(*, quiet: bool = True):
    """Boot identique à la prod : sentrix_v98_ha_product_boot_v8 puis BotAllInOne.setup_hook()."""
    if quiet:
        logging.disable(logging.WARNING)
    import sentrix_v98_ha_product_boot_v8  # noqa: F401  (chaîne d'installs identique à la prod)
    import main

    main.start_dashboard = lambda bot: asyncio.sleep(0)
    bot = main.BotAllInOne()

    async def _bulk(app_id, payload):
        return [dict(p, id=str(i + 1), application_id=str(BOT_ID), version="1", default_member_permissions=None)
                for i, p in enumerate(payload)]

    async def _bulk_guild(app_id, guild_id, payload):
        return [dict(p, id=str(i + 1), application_id=str(BOT_ID), version="1", default_member_permissions=None, guild_id=str(guild_id))
                for i, p in enumerate(payload)]

    bot.http.bulk_upsert_global_commands = _bulk
    bot.http.bulk_upsert_guild_commands = _bulk_guild
    bot._connection.application_id = BOT_ID
    bot._connection.user = discord.ClientUser(
        state=bot._connection,
        data={"id": str(BOT_ID), "username": "SentriX", "discriminator": "0", "avatar": None, "bot": True,
              "verified": True, "mfa_enabled": False},
    )
    await bot._async_setup_hook()
    await bot.setup_hook()
    await asyncio.sleep(0.5)

    discord.http.HTTPClient.request = fake_request
    from discord.webhook import async_ as _wh
    _wh.AsyncWebhookAdapter.request = fake_webhook_request
    _cut_outbound_http()
    return bot


async def setup_world(bot):
    """Un serveur réaliste en cache : rôles, salons texte/vocal, 3 membres, logs configurés."""
    state = bot._connection
    everything = str(discord.Permissions.all().value)
    roles = [
        {"id": str(GID), "name": "@everyone", "permissions": str(discord.Permissions.general().value), "position": 0, "color": 0, "hoist": False, "managed": False, "mentionable": False},
        {"id": str(ADMIN_ROLE_ID), "name": "Admin", "permissions": everything, "position": 5, "color": 0, "hoist": False, "managed": False, "mentionable": False},
        {"id": str(BOT_ROLE_ID), "name": "SentriX", "permissions": everything, "position": 4, "color": 0, "hoist": False, "managed": True, "mentionable": False},
        {"id": str(PING_ROLE_ID), "name": "Ping annonces", "permissions": "0", "position": 2, "color": 0, "hoist": False, "managed": False, "mentionable": True},
        {"id": str(MEMBER_ROLE_ID), "name": "Membre", "permissions": "0", "position": 1, "color": 0, "hoist": False, "managed": False, "mentionable": False},
    ]
    channels = [
        {"id": str(CATEGORY_ID), "type": 4, "name": "Serveur", "position": 0, "permission_overwrites": [], "nsfw": False, "parent_id": None},
        {"id": str(CID), "type": 0, "name": "general", "position": 0, "permission_overwrites": [], "nsfw": False, "parent_id": str(CATEGORY_ID)},
        {"id": str(LOGCID), "type": 0, "name": "logs", "position": 1, "permission_overwrites": [], "nsfw": False, "parent_id": str(CATEGORY_ID)},
        {"id": str(VOICE_CID), "type": 2, "name": "vocal", "position": 2, "permission_overwrites": [], "nsfw": False, "parent_id": str(CATEGORY_ID), "bitrate": 64000, "user_limit": 0},
    ]
    members = [
        member_payload(AUTHOR_ID, "jayden", [ADMIN_ROLE_ID]),
        member_payload(TARGET_ID, "cible", [MEMBER_ROLE_ID]),
        member_payload(SECOND_ID, "second", [MEMBER_ROLE_ID]),
        member_payload(BOT_ID, "SentriX", [BOT_ROLE_ID]),
    ]
    guild_data = {
        "id": str(GID), "name": "Serveur test", "owner_id": str(AUTHOR_ID), "roles": roles, "channels": channels,
        "members": members, "emojis": [], "features": ["COMMUNITY"], "afk_timeout": 300, "verification_level": 0,
        "default_message_notifications": 0, "explicit_content_filter": 0, "mfa_level": 0, "premium_tier": 0,
        "preferred_locale": "fr", "nsfw_level": 0, "stickers": [], "large": False, "member_count": len(members),
        "system_channel_flags": 0, "premium_progress_bar_enabled": False, "voice_states": [],
    }
    guild = discord.Guild(data=guild_data, state=state)
    state._add_guild(guild)
    for mp in members:
        if guild.get_member(int(mp["user"]["id"])) is None:
            guild._add_member(discord.Member(data=mp, guild=guild, state=state))
    state.shard_count = 1
    bot.shard_count = 1

    await bot.db.set_guild_config(GID, "log_channel", LOGCID)
    from utils import log_service
    for category in ("moderation", "messages", "members", "automod", "security", "tickets", "voice", "roles"):
        try:
            await log_service.set_log_config(bot, GID, category, channel_id=LOGCID, enabled=True)
        except Exception:
            pass
    from cogs import setup_v2_core
    for module in ("logs", "levels", "economy", "welcome", "tickets", "security", "automod", "notifications", "games"):
        try:
            await setup_v2_core.set_module_enabled(bot, GID, module, True)
        except Exception:
            pass
    return guild


def next_id() -> int:
    # Identifiant daté « maintenant » : cohérent avec ce que Discord enverrait.
    STATE["cmd_seq"] = max(STATE["cmd_seq"] + 1, discord.utils.time_snowflake(dt.datetime.now(dt.timezone.utc)))
    return STATE["cmd_seq"]


def build_message(bot, guild, content: str, *, author_id: int = AUTHOR_ID, author_name: str = "jayden",
                  author_roles=(ADMIN_ROLE_ID,)) -> discord.Message:
    channel = guild.get_channel(CID)
    mentions = [user(int(x), "cible") for x in re.findall(r"<@!?(\d+)>", content)]
    mid = next_id()
    data = message_payload(mid, CID, content, author_id, author_name)
    STATE["last_cmd_id"] = mid
    STATE["last_cmd_content"] = content
    data["mentions"] = [dict(u, member=member_payload(int(u["id"]), u["username"], [MEMBER_ROLE_ID])) for u in mentions]
    data["mention_roles"] = re.findall(r"<@&(\d+)>", content)
    data["member"] = member_payload(author_id, author_name, list(author_roles))
    return discord.Message(state=bot._connection, channel=channel, data=data)


async def run_prefix(bot, guild, content: str, **author) -> None:
    await bot.process_commands(build_message(bot, guild, content, **author))


def _resolved_payload() -> dict:
    resolved = {
        "users": {str(TARGET_ID): user(TARGET_ID, "cible"), str(SECOND_ID): user(SECOND_ID, "second"), str(AUTHOR_ID): user(AUTHOR_ID, "jayden")},
        "members": {str(TARGET_ID): member_payload(TARGET_ID, "cible", [MEMBER_ROLE_ID]),
                    str(SECOND_ID): member_payload(SECOND_ID, "second", [MEMBER_ROLE_ID]),
                    str(AUTHOR_ID): member_payload(AUTHOR_ID, "jayden", [ADMIN_ROLE_ID])},
        "roles": {str(MEMBER_ROLE_ID): {"id": str(MEMBER_ROLE_ID), "name": "Membre", "permissions": "0", "position": 1, "color": 0, "hoist": False, "managed": False, "mentionable": False},
                  str(PING_ROLE_ID): {"id": str(PING_ROLE_ID), "name": "Ping annonces", "permissions": "0", "position": 2, "color": 0, "hoist": False, "managed": False, "mentionable": True}},
        "channels": {str(CID): {"id": str(CID), "type": 0, "name": "general", "permissions": str(discord.Permissions.all().value)},
                     str(LOGCID): {"id": str(LOGCID), "type": 0, "name": "logs", "permissions": str(discord.Permissions.all().value)},
                     str(VOICE_CID): {"id": str(VOICE_CID), "type": 2, "name": "vocal", "permissions": str(discord.Permissions.all().value)}},
    }
    for payload in resolved["members"].values():
        payload.pop("user", None)
    return resolved


def build_interaction(bot, root_name: str, options: list, *, author_id: int = AUTHOR_ID,
                      author_roles=(ADMIN_ROLE_ID,)) -> discord.Interaction:
    everything = str(discord.Permissions.all().value)
    idata = {
        "id": str(next_id()), "application_id": str(BOT_ID), "type": 2, "token": "tok", "version": 1,
        "guild_id": str(GID), "channel_id": str(CID), "channel": {"id": str(CID), "type": 0}, "locale": "fr",
        "guild_locale": "fr", "app_permissions": everything, "entitlements": [], "attachment_size_limit": 26214400,
        "authorizing_integration_owners": {}, "context": 0,
        "member": dict(member_payload(author_id, "jayden", list(author_roles)), permissions=everything),
        "data": {"id": "1", "name": root_name, "type": 1, "options": options, "resolved": _resolved_payload()},
    }
    return discord.Interaction(data=idata, state=bot._connection)


def slash_options_from_spec(bot, spec: str) -> tuple[str, list]:
    """"clear nombre=100" / "moderation membres mute membre=…" → (racine, options imbriquées)."""
    names, opts = [], {}
    for part in spec.split():
        if "=" in part:
            key, value = part.split("=", 1)
            opts[key] = value
        else:
            names.append(part)
    root = bot.tree.get_command(names[0])

    def build(command, remaining):
        if remaining:
            child = command.get_command(remaining[0])
            kind = 2 if hasattr(child, "commands") else 1
            return [{"name": remaining[0], "type": kind, "options": build(child, remaining[1:])}]
        out = []
        for param in command.parameters:
            if param.name not in opts:
                continue
            raw = opts[param.name]
            kind = param.type.value
            if kind == 4:
                value = int(raw)
            elif kind == 5:
                value = raw.lower() == "true"
            elif kind == 10:
                value = float(raw)
            else:
                value = raw
            out.append({"name": param.name, "type": kind, "value": value})
        return out

    return names[0], build(root, names[1:])


async def run_slash(bot, guild, spec: str) -> None:
    root_name, options = slash_options_from_spec(bot, spec)
    await bot.tree._call(build_interaction(bot, root_name, options))


def _component_texts(components) -> list[str]:
    texts: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == 10 and node.get("content"):
                texts.append(str(node["content"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(components)
    return texts


def describe_call(method: str, path: str, js) -> str:
    short = (path.replace(str(LOGCID), "LOGS").replace(str(CID), "SALON").replace(str(GID), "G")
             .replace(str(TARGET_ID), "CIBLE").replace(str(AUTHOR_ID), "AUTEUR").replace(str(BOT_ID), "BOT"))
    short = re.sub(r"\d{6,}", "#", short)
    detail = ""
    if isinstance(js, dict):
        content, embeds, comps = js.get("content"), js.get("embeds"), js.get("components")
        data = js.get("data")
        if isinstance(data, dict):
            content = content or data.get("content")
            embeds = embeds or data.get("embeds")
            comps = comps or data.get("components")
            detail += f" type={js.get('type')}"
        if content:
            detail += f" content={str(content)[:110]!r}"
        if embeds:
            detail += f" embeds={len(embeds)}:" + "|".join(str(e.get('title') or e.get('description') or '')[:50] for e in embeds)
        if comps:
            texts = _component_texts(comps)
            detail += f" components={len(comps)} texte={' / '.join(t.replace(chr(10), ' ')[:200] for t in texts)[:600]!r}"
        for key in ("communication_disabled_until", "nick", "messages", "reason"):
            if key in js:
                detail += f" {key}={str(js[key])[:60]}"
    return f"   {method} {short}{detail}"


def visible_text(calls) -> str:
    """Texte réellement montré au membre (content + texte des composants + embeds)."""
    chunks: list[str] = []
    for method, path, js in calls:
        if method not in ("POST", "PATCH") or not isinstance(js, dict):
            continue
        data = js.get("data") if isinstance(js.get("data"), dict) else js
        if data.get("content"):
            chunks.append(str(data["content"]))
        for embed in data.get("embeds") or []:
            for key in ("title", "description"):
                if embed.get(key):
                    chunks.append(str(embed[key]))
            for field in embed.get("fields") or []:
                chunks.append(f"{field.get('name', '')} {field.get('value', '')}")
        chunks.extend(_component_texts(data.get("components")))
    return "\n".join(chunks)


def is_reply(method: str, path: str) -> bool:
    """Un appel qui produit une réponse visible (message, callback d'interaction, webhook)."""
    return (method == "POST" and (re.match(r"/channels/\d+/messages$", path) is not None
                                  or "/callback" in path or re.match(r"/webhooks/\d+/[^/]+$", path) is not None)) \
        or (method == "PATCH" and "/webhooks/" in path)


async def settle(*, idle: float = 0.4, maximum: float = 2.5) -> None:
    """Attend que le bot n'émette plus d'appels HTTP (tâches de fond comprises)."""
    waited = 0.0
    last = len(CALLS)
    while waited < maximum:
        await asyncio.sleep(idle)
        waited += idle
        if len(CALLS) == last:
            return
        last = len(CALLS)


async def _cli(specs: list[str]) -> None:
    bot = await boot()
    guild = await setup_world(bot)
    for spec in specs:
        since = len(CALLS)
        print(f"\n### {spec}")
        try:
            if spec.startswith("+"):
                await asyncio.wait_for(run_prefix(bot, guild, spec), 20)
            else:
                await asyncio.wait_for(run_slash(bot, guild, spec.lstrip("/")), 20)
        except Exception:
            import traceback
            traceback.print_exc()
        await settle()
        for method, path, js in CALLS[since:]:
            print(describe_call(method, path, js))
    sys.stdout.flush()
    os._exit(0)  # aiosqlite garde des threads vivants : sortie franche.


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    asyncio.run(_cli(sys.argv[1:]))
