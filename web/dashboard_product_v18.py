"""SentriX Dashboard V18 — product-grade control plane.

This module is intentionally backend-first. It adds a coherent API surface for the features
needed to move the dashboard from a collection of pages to a real control center:
- delegated dashboard access (RBAC foundation)
- visual audit/diff data
- reusable configuration templates
- event automations with real Discord actions
- member search + staff actions
- global search and analytics

It does not replace the visible dashboard by itself and is safe to install before the V18 UI.
All mutating routes are CSRF-protected and every Discord action is permission/hierarchy checked.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard-product-v18")
_INSTALLED = False

SCOPES = {
    "view",
    "configuration",
    "members",
    "moderation",
    "automations",
    "audit",
    "templates",
    "dangerous",
    "admin",
}

NAV_SEARCH = [
    ("overview", "Vue d’ensemble", "Résumé du serveur et état de SentriX"),
    ("welcome", "Arrivées & départs", "Messages de bienvenue, départs et autorôle"),
    ("levels", "Niveaux", "XP, niveaux et récompenses"),
    ("security", "Sécurité", "Anti-spam, anti-raid et protections"),
    ("moderation", "Modération", "Sanctions et outils staff"),
    ("logs", "Logs", "Salons de journalisation"),
    ("verification", "Vérification Discord", "Règlement, rôle et CAPTCHA"),
    ("roles", "Rôles", "Rôles et attribution"),
    ("economy", "Économie", "Monnaie, banque et boutique"),
    ("notifications", "Notifications", "Notifications sociales et serveur"),
    ("invites", "Invitations", "Suivi des invitations"),
    ("autoreact", "Réactions automatiques", "Réactions configurables"),
    ("tickets", "Tickets", "Support et panneaux de tickets"),
    ("ai", "Intelligence artificielle", "IA SentriX"),
    ("embeds", "Embeds & design", "Créateur d’embeds"),
    ("configuration", "Configuration", "Réglages généraux"),
    ("access", "Accès & commandes", "Commandes et permissions"),
    ("dm", "Messages privés", "Outils DM"),
    ("diagnostic", "Diagnostic", "Permissions et références cassées"),
    ("product", "Centre avancé", "Actions, automations, membres, audit et templates"),
]


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return {}


async def _ensure_tables(db) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_access (
            guild_id INTEGER NOT NULL,
            principal_type TEXT NOT NULL,
            principal_id INTEGER NOT NULL,
            scopes_json TEXT NOT NULL,
            granted_by INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, principal_type, principal_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_by INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_automations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_json TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_automation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            automation_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            detail TEXT,
            created_at INTEGER NOT NULL
        )
        """,
    ]
    for sql in statements:
        await db.execute(sql)


async def _member_for_user(guild: discord.Guild, user_id: int) -> discord.Member | None:
    """Membre courant, sans appel REST quand le cache membres est complet.

    ``guilds_with_delegation`` appelle cette fonction pour CHAQUE serveur du bot où
    l'utilisateur n'est pas déjà listé ; avec le ``fetch_member`` systématique c'était
    ~20 appels REST Discord (404) à chaque GET /api/guilds — 4 s au boot du dashboard,
    mesuré en production. Un serveur chunké (intent members + chunking au démarrage) a
    un cache autoritaire : absence = « pas membre ».
    """
    member = guild.get_member(user_id)
    if member is not None:
        return member
    if getattr(guild, "chunked", False):
        return None
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _scopes_for(db, guild: discord.Guild, member: discord.Member) -> set[str]:
    if member.guild_permissions.administrator:
        return set(SCOPES) | {"*"}
    await _ensure_tables(db)
    role_ids = {int(role.id) for role in member.roles}
    rows = await db.fetchall(
        "SELECT principal_type,principal_id,scopes_json FROM sentrix_dashboard_access WHERE guild_id = ?",
        (guild.id,),
    )
    scopes: set[str] = set()
    for row in rows:
        item = _row_dict(row)
        ptype = str(item.get("principal_type") or "")
        pid = int(item.get("principal_id") or 0)
        if not ((ptype == "user" and pid == member.id) or (ptype == "role" and pid in role_ids)):
            continue
        try:
            values = json.loads(item.get("scopes_json") or "[]")
        except Exception:
            values = []
        scopes.update(str(value) for value in values if str(value) in SCOPES)
    return scopes


async def _require_access(dashboard, request: web.Request, scope: str = "view", *, admin_only: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        return None, None, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
    session, error = dashboard._require_session(request)
    if error:
        return guild_id, None, None, None, error
    guild = request.app["bot"].get_guild(guild_id)
    if guild is None:
        return guild_id, session, None, None, dashboard._json_error("Serveur introuvable ou accès refusé.", 404)
    member = await _member_for_user(guild, int(session["user"]["id"]))
    if member is None:
        return guild_id, session, guild, None, dashboard._json_error("Serveur introuvable ou accès refusé.", 404)
    if admin_only and not member.guild_permissions.administrator:
        return guild_id, session, guild, member, dashboard._json_error("Cette action est réservée aux administrateurs du serveur.", 403)
    scopes = await _scopes_for(request.app["bot"].db, guild, member)
    if member.guild_permissions.administrator:
        return guild_id, session, guild, member, None
    if scope not in scopes and "admin" not in scopes and "*" not in scopes:
        return guild_id, session, guild, member, dashboard._json_error("Tu n’as pas la permission dashboard requise pour cette action.", 403)
    return guild_id, session, guild, member, None


def _csrf(dashboard, request: web.Request, session: dict):
    return dashboard._require_csrf(request, session)


async def _snapshot(dashboard, db, guild_id: int) -> dict:
    from web import dashboard_ops_suite
    return await dashboard_ops_suite._snapshot(dashboard, db, guild_id)


async def _record_history(dashboard, request: web.Request, guild_id: int, before: dict, changed: list[str]) -> None:
    from web import dashboard_ops_suite
    await dashboard_ops_suite._record_history(dashboard, request, guild_id, before, changed)


def _normalise_scopes(value) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({str(item) for item in value if str(item) in SCOPES})


def _json_load(value, default):
    try:
        loaded = json.loads(value or "")
    except Exception:
        return default
    return loaded if isinstance(loaded, type(default)) else default


def _flatten(value, prefix="") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten(item, path))
    else:
        out[prefix] = value
    return out


def _diff(before: dict, after: dict) -> list[dict]:
    left = _flatten(before)
    right = _flatten(after)
    keys = sorted(set(left) | set(right))
    result = []
    for key in keys:
        old = left.get(key)
        new = right.get(key)
        if old != new:
            result.append({"path": key, "before": old, "after": new})
        if len(result) >= 500:
            break
    return result


async def _apply_snapshot(dashboard, request: web.Request, guild: discord.Guild, snapshot: dict) -> tuple[bool, str]:
    db = request.app["bot"].db
    guild_id = guild.id
    settings = snapshot.get("settings") or {}
    automod = snapshot.get("automod") or {}
    ai = snapshot.get("ai") or {}
    clean_settings, message = dashboard._validate_settings(guild, settings)
    if message:
        return False, message
    clean_ai, message = dashboard._validate_ai({
        key: value for key, value in ai.items()
        if key in dashboard.AI_BOOL_FIELDS or key in dashboard.AI_INT_FIELDS or key in dashboard.AI_CHOICE_FIELDS
    })
    if message:
        return False, message
    before = await _snapshot(dashboard, db, guild_id)
    for key, value in clean_settings.items():
        await db.set_guild_config(guild_id, key, value)
    for key, value in automod.items():
        if key in dashboard.AUTOMOD_FIELDS and value in (True, False, 0, 1):
            await db.set_automod(guild_id, key, int(bool(value)))
    if clean_ai:
        await db.execute("INSERT OR IGNORE INTO ai_settings (guild_id, updated_at) VALUES (?, ?)", (guild_id, int(time.time())))
        for key, value in clean_ai.items():
            await db.execute(f"UPDATE ai_settings SET {key} = ?, updated_at = ? WHERE guild_id = ?", (value, int(time.time()), guild_id))
    await _record_history(dashboard, request, guild_id, before, ["template_apply"])
    return True, "Configuration appliquée."


def _render_text(template: str, *, guild: discord.Guild, member: discord.Member | None = None, message: discord.Message | None = None) -> str:
    values = {
        "guild": guild.name,
        "member": member.mention if member else "",
        "member_name": member.display_name if member else "",
        "message": message.content if message else "",
    }
    output = str(template or "")[:1800]
    for key, value in values.items():
        output = output.replace("{" + key + "}", str(value))
    return output


async def _log_automation_run(db, guild_id: int, automation_id: int, status: str, detail: str) -> None:
    await _ensure_tables(db)
    await db.execute(
        "INSERT INTO sentrix_dashboard_automation_runs (guild_id,automation_id,status,detail,created_at) VALUES (?,?,?,?,?)",
        (guild_id, automation_id, status[:30], detail[:500], int(time.time())),
    )


async def _execute_automation(bot, guild: discord.Guild, row: dict, *, member=None, message=None) -> None:
    action_type = str(row.get("action_type") or "")
    action = _json_load(row.get("action_json"), {})
    automation_id = int(row.get("id") or 0)
    try:
        if action_type == "send_message":
            channel = guild.get_channel(int(action.get("channel_id") or 0))
            if not isinstance(channel, discord.TextChannel):
                raise RuntimeError("Salon texte introuvable.")
            text = _render_text(str(action.get("text") or ""), guild=guild, member=member, message=message)
            if not text:
                raise RuntimeError("Message vide.")
            await channel.send(text, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        elif action_type in {"add_role", "remove_role"}:
            if member is None:
                raise RuntimeError("Cette action nécessite un membre.")
            role = guild.get_role(int(action.get("role_id") or 0))
            if role is None or role.managed or role.is_default():
                raise RuntimeError("Rôle introuvable ou non gérable.")
            me = guild.me
            if me is None or role >= me.top_role:
                raise RuntimeError("Le rôle est au-dessus de SentriX.")
            reason = "Automation SentriX dashboard"
            if action_type == "add_role":
                await member.add_roles(role, reason=reason)
            else:
                await member.remove_roles(role, reason=reason)
        else:
            raise RuntimeError("Action d’automation non supportée.")
        await _log_automation_run(bot.db, guild.id, automation_id, "success", "Action exécutée.")
    except Exception as exc:
        logger.warning("Automation V18 failed guild=%s id=%s: %s", guild.id, automation_id, exc)
        try:
            await _log_automation_run(bot.db, guild.id, automation_id, "error", str(exc))
        except Exception:
            pass


async def _run_automations(bot, guild: discord.Guild, trigger_type: str, *, member=None, message=None) -> None:
    try:
        await _ensure_tables(bot.db)
        rows = await bot.db.fetchall(
            "SELECT * FROM sentrix_dashboard_automations WHERE guild_id = ? AND enabled = 1 AND trigger_type = ? ORDER BY id ASC",
            (guild.id, trigger_type),
        )
    except Exception:
        return
    for raw in rows:
        row = _row_dict(raw)
        trigger = _json_load(row.get("trigger_json"), {})
        if trigger_type == "message_contains":
            if message is None or message.author.bot:
                continue
            needle = str(trigger.get("text") or "").casefold().strip()
            if not needle or needle not in message.content.casefold():
                continue
            channel_id = int(trigger.get("channel_id") or 0)
            if channel_id and message.channel.id != channel_id:
                continue
        elif trigger_type == "member_role_added":
            role_id = int(trigger.get("role_id") or 0)
            if not role_id or member is None or all(role.id != role_id for role in member.roles):
                continue
        await _execute_automation(bot, guild, row, member=member, message=message)


async def _analytics(db, guild_id: int) -> dict:
    now_ts = int(time.time())
    result = {
        "commands_24h": 0,
        "warnings_total": 0,
        "open_tickets": 0,
        "automation_runs_24h": 0,
        "top_commands": [],
    }
    scalar_queries = {
        "commands_24h": ("SELECT COUNT(*) AS n FROM command_logs WHERE guild_id = ? AND timestamp >= ?", (guild_id, now_ts - 86400)),
        "warnings_total": ("SELECT COUNT(*) AS n FROM warnings WHERE guild_id = ?", (guild_id,)),
        "open_tickets": ("SELECT COUNT(*) AS n FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (guild_id,)),
        "automation_runs_24h": ("SELECT COUNT(*) AS n FROM sentrix_dashboard_automation_runs WHERE guild_id = ? AND created_at >= ?", (guild_id, now_ts - 86400)),
    }
    for key, (sql, params) in scalar_queries.items():
        try:
            row = await db.fetchone(sql, params)
            result[key] = int((row or {}).get("n", 0) if isinstance(row, dict) else row["n"] if row else 0)
        except Exception:
            pass
    candidates = [
        "SELECT command_name AS name,COUNT(*) AS n FROM command_logs WHERE guild_id = ? AND timestamp >= ? GROUP BY command_name ORDER BY n DESC LIMIT 10",
        "SELECT command AS name,COUNT(*) AS n FROM command_logs WHERE guild_id = ? AND timestamp >= ? GROUP BY command ORDER BY n DESC LIMIT 10",
    ]
    for sql in candidates:
        try:
            rows = await db.fetchall(sql, (guild_id, now_ts - 7 * 86400))
            result["top_commands"] = [{"name": str(_row_dict(row).get("name") or "commande"), "count": int(_row_dict(row).get("n") or 0)} for row in rows]
            break
        except Exception:
            continue
    return result


def _target_allowed(actor: discord.Member, target: discord.Member) -> bool:
    if target.id == actor.guild.owner_id:
        return False
    if actor.guild_permissions.administrator:
        return True
    return actor.top_role > target.top_role


def _bot_can_manage_member(guild: discord.Guild, target: discord.Member) -> bool:
    me = guild.me
    return bool(me and target.id != guild.owner_id and me.top_role > target.top_role)


def install(dashboard) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    original_manageable = dashboard._manageable_guild
    if not getattr(original_manageable, "_sentrix_v18_rbac", False):
        async def manageable_with_delegation(request: web.Request, guild_id: int):
            session, guild, error = await original_manageable(request, guild_id)
            if error is None:
                return session, guild, None
            session, session_error = dashboard._require_session(request)
            if session_error:
                return None, None, session_error
            guild = request.app["bot"].get_guild(guild_id)
            if guild is None:
                return session, None, dashboard._json_error("Serveur introuvable ou accès refusé.", 404)
            member = await _member_for_user(guild, int(session["user"]["id"]))
            if member is None:
                return session, None, dashboard._json_error("Serveur introuvable ou accès refusé.", 404)
            scopes = await _scopes_for(request.app["bot"].db, guild, member)
            needed = "view" if request.method == "GET" else "configuration"
            if needed not in scopes and "admin" not in scopes and "*" not in scopes:
                return session, None, dashboard._json_error("Serveur introuvable ou accès refusé.", 404)
            return session, guild, None
        manageable_with_delegation._sentrix_v18_rbac = True
        manageable_with_delegation._sentrix_previous = original_manageable
        dashboard._manageable_guild = manageable_with_delegation

    original_guilds = dashboard.handle_guilds
    if not getattr(original_guilds, "_sentrix_v18_rbac", False):
        async def guilds_with_delegation(request: web.Request):
            response = await original_guilds(request)
            if getattr(response, "status", 500) >= 400:
                return response
            try:
                payload = json.loads(response.text)
            except Exception:
                payload = {"guilds": []}
            session = dashboard._session(request) or {}
            user_id = int((session.get("user") or {}).get("id") or 0)
            seen = {str(item.get("id")) for item in payload.get("guilds", [])}
            if user_id:
                for guild in request.app["bot"].guilds:
                    if str(guild.id) in seen:
                        continue
                    member = await _member_for_user(guild, user_id)
                    if member is None:
                        continue
                    scopes = await _scopes_for(request.app["bot"].db, guild, member)
                    if not scopes:
                        continue
                    payload.setdefault("guilds", []).append({
                        "id": str(guild.id),
                        "name": guild.name,
                        "icon_url": str(guild.icon.url) if guild.icon else None,
                        "owner": guild.owner_id == user_id,
                        "installed": True,
                        "invite_url": None,
                        "delegated": not member.guild_permissions.administrator,
                        "scopes": sorted(scopes),
                    })
            payload["guilds"].sort(key=lambda item: (not item.get("installed"), str(item.get("name") or "").casefold()))
            return web.json_response(payload)
        guilds_with_delegation._sentrix_v18_rbac = True
        guilds_with_delegation._sentrix_previous = original_guilds
        dashboard.handle_guilds = guilds_with_delegation

    original_build = dashboard.build_app
    if not getattr(original_build, "_sentrix_product_v18", False):
        def build_app_with_product(bot):
            app = original_build(bot)

            async def access_list(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "admin", admin_only=True)
                if error:
                    return error
                await _ensure_tables(bot.db)
                rows = await bot.db.fetchall(
                    "SELECT principal_type,principal_id,scopes_json,granted_by,updated_at FROM sentrix_dashboard_access WHERE guild_id = ? ORDER BY principal_type,principal_id",
                    (guild_id,),
                )
                grants = []
                for raw in rows:
                    item = _row_dict(raw)
                    item["scopes"] = _json_load(item.pop("scopes_json", "[]"), [])
                    if item.get("principal_type") == "role":
                        role = guild.get_role(int(item.get("principal_id") or 0))
                        item["name"] = role.name if role else "Rôle supprimé"
                    else:
                        target = guild.get_member(int(item.get("principal_id") or 0))
                        item["name"] = target.display_name if target else "Utilisateur"
                    grants.append(item)
                return web.json_response({"ok": True, "scopes": sorted(SCOPES), "grants": grants})

            async def access_save(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "admin", admin_only=True)
                if error:
                    return error
                csrf = _csrf(dashboard, request, session)
                if csrf:
                    return csrf
                try:
                    payload = await request.json()
                except Exception:
                    return dashboard._json_error("Formulaire invalide.", 400)
                principal_type = str(payload.get("principal_type") or "")
                if principal_type not in {"user", "role"}:
                    return dashboard._json_error("Type d’accès invalide.", 400)
                try:
                    principal_id = int(payload.get("principal_id") or 0)
                except (TypeError, ValueError):
                    return dashboard._json_error("Identifiant invalide.", 400)
                scopes = _normalise_scopes(payload.get("scopes"))
                if not scopes:
                    return dashboard._json_error("Choisis au moins une permission dashboard.", 400)
                if principal_type == "role":
                    role = guild.get_role(principal_id)
                    if role is None or role.is_default() or role.managed:
                        return dashboard._json_error("Rôle introuvable ou non utilisable.", 400)
                elif await _member_for_user(guild, principal_id) is None:
                    return dashboard._json_error("Membre introuvable.", 400)
                await _ensure_tables(bot.db)
                await bot.db.execute(
                    "INSERT INTO sentrix_dashboard_access (guild_id,principal_type,principal_id,scopes_json,granted_by,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id,principal_type,principal_id) DO UPDATE SET scopes_json=excluded.scopes_json,granted_by=excluded.granted_by,updated_at=excluded.updated_at",
                    (guild_id, principal_type, principal_id, json.dumps(scopes), int(member.id), int(time.time())),
                )
                return web.json_response({"ok": True, "message": "Accès dashboard mis à jour."})

            async def access_delete(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "admin", admin_only=True)
                if error:
                    return error
                csrf = _csrf(dashboard, request, session)
                if csrf:
                    return csrf
                ptype = str(request.match_info.get("principal_type") or "")
                try:
                    pid = int(request.match_info.get("principal_id") or 0)
                except ValueError:
                    return dashboard._json_error("Identifiant invalide.", 400)
                await _ensure_tables(bot.db)
                await bot.db.execute("DELETE FROM sentrix_dashboard_access WHERE guild_id = ? AND principal_type = ? AND principal_id = ?", (guild_id, ptype, pid))
                return web.json_response({"ok": True, "message": "Accès retiré."})

            async def search(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "view")
                if error:
                    return error
                query = str(request.query.get("q") or "").strip().casefold()
                if len(query) < 2:
                    return web.json_response({"ok": True, "results": []})
                results = []
                for tab, title, description in NAV_SEARCH:
                    if query in f"{title} {description} {tab}".casefold():
                        results.append({"type": "page", "id": tab, "title": title, "subtitle": description})
                for channel in guild.channels:
                    if query in channel.name.casefold():
                        results.append({"type": "channel", "id": str(channel.id), "title": f"# {channel.name}", "subtitle": str(channel.type)})
                    if len(results) >= 40:
                        break
                if len(results) < 40:
                    for role in reversed(guild.roles):
                        if role.is_default():
                            continue
                        if query in role.name.casefold():
                            results.append({"type": "role", "id": str(role.id), "title": role.name, "subtitle": "Rôle Discord"})
                        if len(results) >= 40:
                            break
                if len(results) < 40:
                    for target in guild.members:
                        hay = f"{target.display_name} {target.name} {target.id}".casefold()
                        if query in hay:
                            results.append({"type": "member", "id": str(target.id), "title": target.display_name, "subtitle": f"@{target.name}"})
                        if len(results) >= 40:
                            break
                return web.json_response({"ok": True, "results": results[:40]})

            async def analytics(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "view")
                if error:
                    return error
                await _ensure_tables(bot.db)
                data = await _analytics(bot.db, guild_id)
                data.update({"members": guild.member_count or 0, "channels": len(guild.channels), "roles": len(guild.roles)})
                return web.json_response({"ok": True, "analytics": data})

            async def audit_diff(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "audit")
                if error:
                    return error
                try:
                    history_id = int(request.match_info["history_id"])
                except ValueError:
                    return dashboard._json_error("Historique invalide.", 400)
                row = await bot.db.fetchone("SELECT snapshot_json,changed_json,created_at,username,user_id FROM sentrix_dashboard_history WHERE id = ? AND guild_id = ?", (history_id, guild_id))
                if not row:
                    return dashboard._json_error("Version introuvable.", 404)
                item = _row_dict(row)
                before = _json_load(item.get("snapshot_json"), {})
                current = await _snapshot(dashboard, bot.db, guild_id)
                return web.json_response({
                    "ok": True,
                    "history": {"id": history_id, "created_at": item.get("created_at"), "username": item.get("username"), "user_id": item.get("user_id"), "changed": _json_load(item.get("changed_json"), [])},
                    "diff": _diff(before, current),
                })

            async def templates_list(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "templates")
                if error:
                    return error
                await _ensure_tables(bot.db)
                rows = await bot.db.fetchall("SELECT id,name,created_by,created_at FROM sentrix_dashboard_templates WHERE guild_id = ? ORDER BY id DESC", (guild_id,))
                return web.json_response({"ok": True, "templates": [_row_dict(row) for row in rows]})

            async def templates_create(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "templates")
                if error:
                    return error
                csrf = _csrf(dashboard, request, session)
                if csrf:
                    return csrf
                try:
                    payload = await request.json()
                except Exception:
                    payload = {}
                name = str(payload.get("name") or "").strip()[:80]
                if not name:
                    return dashboard._json_error("Donne un nom au template.", 400)
                await _ensure_tables(bot.db)
                snap = await _snapshot(dashboard, bot.db, guild_id)
                await bot.db.execute("INSERT INTO sentrix_dashboard_templates (guild_id,name,snapshot_json,created_by,created_at) VALUES (?,?,?,?,?)", (guild_id, name, json.dumps(snap, ensure_ascii=False), int(member.id), int(time.time())))
                return web.json_response({"ok": True, "message": "Template enregistré."})

            async def templates_apply(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "templates")
                if error:
                    return error
                csrf = _csrf(dashboard, request, session)
                if csrf:
                    return csrf
                try:
                    template_id = int(request.match_info["template_id"])
                except ValueError:
                    return dashboard._json_error("Template invalide.", 400)
                row = await bot.db.fetchone("SELECT snapshot_json FROM sentrix_dashboard_templates WHERE id = ? AND guild_id = ?", (template_id, guild_id))
                if not row:
                    return dashboard._json_error("Template introuvable.", 404)
                snap = _json_load(_row_dict(row).get("snapshot_json"), {})
                ok, message = await _apply_snapshot(dashboard, request, guild, snap)
                if not ok:
                    return dashboard._json_error(message, 409)
                return web.json_response({"ok": True, "message": message})

            async def automations_list(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "automations")
                if error:
                    return error
                await _ensure_tables(bot.db)
                rows = await bot.db.fetchall("SELECT id,name,trigger_type,trigger_json,action_type,action_json,enabled,created_by,created_at,updated_at FROM sentrix_dashboard_automations WHERE guild_id = ? ORDER BY id DESC", (guild_id,))
                out = []
                for raw in rows:
                    item = _row_dict(raw)
                    item["trigger"] = _json_load(item.pop("trigger_json", "{}"), {})
                    item["action"] = _json_load(item.pop("action_json", "{}"), {})
                    item["enabled"] = bool(item.get("enabled"))
                    out.append(item)
                runs = await bot.db.fetchall("SELECT automation_id,status,detail,created_at FROM sentrix_dashboard_automation_runs WHERE guild_id = ? ORDER BY id DESC LIMIT 30", (guild_id,))
                return web.json_response({"ok": True, "automations": out, "runs": [_row_dict(row) for row in runs]})

            async def automations_save(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "automations")
                if error:
                    return error
                csrf = _csrf(dashboard, request, session)
                if csrf:
                    return csrf
                try:
                    payload = await request.json()
                except Exception:
                    return dashboard._json_error("Formulaire invalide.", 400)
                name = str(payload.get("name") or "Automation").strip()[:80]
                trigger_type = str(payload.get("trigger_type") or "")
                action_type = str(payload.get("action_type") or "")
                trigger = payload.get("trigger") if isinstance(payload.get("trigger"), dict) else {}
                action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
                if trigger_type not in {"member_join", "member_leave", "message_contains", "member_role_added"}:
                    return dashboard._json_error("Déclencheur non supporté.", 400)
                if action_type not in {"send_message", "add_role", "remove_role"}:
                    return dashboard._json_error("Action non supportée.", 400)
                if trigger_type == "message_contains" and not str(trigger.get("text") or "").strip():
                    return dashboard._json_error("Indique le texte à détecter.", 400)
                if action_type == "send_message":
                    channel = guild.get_channel(int(action.get("channel_id") or 0))
                    if not isinstance(channel, discord.TextChannel) or not str(action.get("text") or "").strip():
                        return dashboard._json_error("Salon ou message invalide.", 400)
                if action_type in {"add_role", "remove_role"}:
                    role = guild.get_role(int(action.get("role_id") or 0))
                    if role is None or role.managed or role.is_default() or guild.me is None or role >= guild.me.top_role:
                        return dashboard._json_error("Rôle invalide ou trop haut pour SentriX.", 400)
                enabled = 1 if payload.get("enabled", True) else 0
                now_ts = int(time.time())
                await _ensure_tables(bot.db)
                automation_id = int(payload.get("id") or 0)
                if automation_id:
                    await bot.db.execute("UPDATE sentrix_dashboard_automations SET name=?,trigger_type=?,trigger_json=?,action_type=?,action_json=?,enabled=?,updated_at=? WHERE id=? AND guild_id=?", (name, trigger_type, json.dumps(trigger), action_type, json.dumps(action), enabled, now_ts, automation_id, guild_id))
                else:
                    await bot.db.execute("INSERT INTO sentrix_dashboard_automations (guild_id,name,trigger_type,trigger_json,action_type,action_json,enabled,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (guild_id, name, trigger_type, json.dumps(trigger), action_type, json.dumps(action), enabled, int(member.id), now_ts, now_ts))
                return web.json_response({"ok": True, "message": "Automation enregistrée."})

            async def automations_delete(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "automations")
                if error:
                    return error
                csrf = _csrf(dashboard, request, session)
                if csrf:
                    return csrf
                try:
                    automation_id = int(request.match_info["automation_id"])
                except ValueError:
                    return dashboard._json_error("Automation invalide.", 400)
                await bot.db.execute("DELETE FROM sentrix_dashboard_automations WHERE id = ? AND guild_id = ?", (automation_id, guild_id))
                return web.json_response({"ok": True, "message": "Automation supprimée."})

            async def members_search(request):
                guild_id, session, guild, actor, error = await _require_access(dashboard, request, "members")
                if error:
                    return error
                query = str(request.query.get("q") or "").strip().casefold()
                out = []
                for target in guild.members:
                    if query and query not in f"{target.display_name} {target.name} {target.id}".casefold():
                        continue
                    out.append({
                        "id": str(target.id),
                        "name": target.name,
                        "display_name": target.display_name,
                        "bot": target.bot,
                        "avatar_url": str(target.display_avatar.url),
                        "roles": [{"id": str(role.id), "name": role.name} for role in target.roles if not role.is_default()][-12:],
                        "joined_at": target.joined_at.isoformat() if target.joined_at else None,
                        "manageable": _target_allowed(actor, target) and _bot_can_manage_member(guild, target),
                    })
                    if len(out) >= 30:
                        break
                return web.json_response({"ok": True, "members": out})

            async def member_action(request):
                guild_id, session, guild, actor, error = await _require_access(dashboard, request, "members")
                if error:
                    return error
                csrf = _csrf(dashboard, request, session)
                if csrf:
                    return csrf
                try:
                    target_id = int(request.match_info["member_id"])
                    payload = await request.json()
                except Exception:
                    return dashboard._json_error("Action invalide.", 400)
                target = await _member_for_user(guild, target_id)
                if target is None:
                    return dashboard._json_error("Membre introuvable.", 404)
                if not _target_allowed(actor, target) or not _bot_can_manage_member(guild, target):
                    return dashboard._json_error("Hiérarchie des rôles insuffisante pour agir sur ce membre.", 403)
                action = str(payload.get("action") or "")
                reason = str(payload.get("reason") or f"Action dashboard par {actor}").strip()[:400]
                if action in {"kick", "ban"}:
                    scopes = await _scopes_for(bot.db, guild, actor)
                    if not actor.guild_permissions.administrator and "dangerous" not in scopes and "admin" not in scopes:
                        return dashboard._json_error("Permission dashboard ‘dangerous’ requise.", 403)
                if action == "timeout":
                    minutes = max(1, min(int(payload.get("minutes") or 10), 40320))
                    if guild.me is None or not guild.me.guild_permissions.moderate_members:
                        return dashboard._json_error("SentriX n’a pas la permission Exclure temporairement.", 409)
                    await target.timeout(datetime.now(UTC) + timedelta(minutes=minutes), reason=reason)
                elif action == "kick":
                    if guild.me is None or not guild.me.guild_permissions.kick_members:
                        return dashboard._json_error("SentriX n’a pas la permission Expulser.", 409)
                    await target.kick(reason=reason)
                elif action == "ban":
                    if guild.me is None or not guild.me.guild_permissions.ban_members:
                        return dashboard._json_error("SentriX n’a pas la permission Bannir.", 409)
                    await guild.ban(target, reason=reason)
                elif action in {"add_role", "remove_role"}:
                    role = guild.get_role(int(payload.get("role_id") or 0))
                    if role is None or role.managed or role.is_default() or guild.me is None or role >= guild.me.top_role:
                        return dashboard._json_error("Rôle invalide ou trop haut pour SentriX.", 400)
                    if not actor.guild_permissions.administrator and role >= actor.top_role:
                        return dashboard._json_error("Ce rôle est au-dessus de ton rôle Discord.", 403)
                    if action == "add_role":
                        await target.add_roles(role, reason=reason)
                    else:
                        await target.remove_roles(role, reason=reason)
                else:
                    return dashboard._json_error("Action membre non supportée.", 400)
                return web.json_response({"ok": True, "message": "Action appliquée au membre."})

            async def live_metrics(request):
                guild_id, session, guild, member, error = await _require_access(dashboard, request, "view")
                if error:
                    return error
                await _ensure_tables(bot.db)
                data = await _analytics(bot.db, guild_id)
                revision = int(data.get("warnings_total") or 0)
                try:
                    row = await bot.db.fetchone(
                        "SELECT COALESCE(MAX(id), 0) AS n FROM warnings WHERE guild_id = ?",
                        (guild_id,),
                    )
                    item = _row_dict(row)
                    revision = max(revision, int(item.get("n") or 0))
                except Exception:
                    pass
                return web.json_response(
                    {
                        "ok": True,
                        "members": int(guild.member_count or 0),
                        "commands_24h": int(data.get("commands_24h") or 0),
                        "open_tickets": int(data.get("open_tickets") or 0),
                        "warnings": int(data.get("warnings_total") or 0),
                        "online": bool(bot.is_ready()),
                        "latency_ms": round(bot.latency * 1000) if bot.is_ready() else None,
                        "sanctions_revision": revision,
                    }
                )

            app.router.add_get("/api/guilds/{guild_id}/product/access", access_list)
            app.router.add_post("/api/guilds/{guild_id}/product/access", access_save)
            app.router.add_delete("/api/guilds/{guild_id}/product/access/{principal_type}/{principal_id}", access_delete)
            app.router.add_get("/api/guilds/{guild_id}/product/search", search)
            app.router.add_get("/api/guilds/{guild_id}/live/metrics", live_metrics)
            app.router.add_get("/api/guilds/{guild_id}/product/analytics", analytics)
            app.router.add_get("/api/guilds/{guild_id}/product/audit/{history_id}/diff", audit_diff)
            app.router.add_get("/api/guilds/{guild_id}/product/templates", templates_list)
            app.router.add_post("/api/guilds/{guild_id}/product/templates", templates_create)
            app.router.add_post("/api/guilds/{guild_id}/product/templates/{template_id}/apply", templates_apply)
            app.router.add_get("/api/guilds/{guild_id}/product/automations", automations_list)
            app.router.add_post("/api/guilds/{guild_id}/product/automations", automations_save)
            app.router.add_delete("/api/guilds/{guild_id}/product/automations/{automation_id}", automations_delete)
            app.router.add_get("/api/guilds/{guild_id}/product/members", members_search)
            app.router.add_post("/api/guilds/{guild_id}/product/members/{member_id}/action", member_action)
            return app

        build_app_with_product._sentrix_product_v18 = True
        build_app_with_product._sentrix_previous = original_build
        dashboard.build_app = build_app_with_product

    if not getattr(dashboard, "_sentrix_product_v18_listeners", False):
        dashboard._sentrix_product_v18_listeners = True

    _INSTALLED = True
    logger.info("Dashboard Product V18 backend installed.")
    return True


def install_runtime(bot) -> bool:
    if getattr(bot, "_sentrix_product_v18_runtime", False):
        return True
    bot._sentrix_product_v18_runtime = True

    async def on_member_join(member: discord.Member):
        await _run_automations(bot, member.guild, "member_join", member=member)

    async def on_member_remove(member: discord.Member):
        await _run_automations(bot, member.guild, "member_leave", member=member)

    async def on_message(message: discord.Message):
        if message.guild is not None and not message.author.bot:
            await _run_automations(bot, message.guild, "message_contains", member=message.author if isinstance(message.author, discord.Member) else None, message=message)

    async def on_member_update(before: discord.Member, after: discord.Member):
        before_ids = {role.id for role in before.roles}
        added = [role for role in after.roles if role.id not in before_ids]
        if added:
            await _run_automations(bot, after.guild, "member_role_added", member=after)

    bot.add_listener(on_member_join, "on_member_join")
    bot.add_listener(on_member_remove, "on_member_remove")
    bot.add_listener(on_message, "on_message")
    bot.add_listener(on_member_update, "on_member_update")
    logger.info("Dashboard Product V18 automation runtime installed.")
    return True


__all__ = ["install", "install_runtime", "SCOPES"]
