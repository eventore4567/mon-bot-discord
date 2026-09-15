"""SentriX Dashboard V19 — final product polish backend.

V19 deliberately extends the stable V18 control plane instead of replacing it.  It adds only
high-use product features that have real backend behaviour:
- compact live health/activity feed;
- actionable onboarding checklist computed from current guild/config state;
- bounded bulk member actions (timeout / add role / remove role) with Discord hierarchy guards.

The module is fail-open by design.  No database migration or external service is required.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard-product-v19")
BUILD = "v19-final-polish"
MAX_BULK_TARGETS = 25


def _row_dict(row) -> dict:
    try:
        return dict(row or {})
    except Exception:
        return {}


def _truthy_config(settings: dict, *needles: str) -> bool:
    for key, value in (settings or {}).items():
        name = str(key).casefold()
        if all(needle.casefold() in name for needle in needles) and value not in (None, "", 0, False, "0"):
            return True
    return False


def _manageable_roles(guild: discord.Guild, actor: discord.Member) -> list[dict]:
    me = guild.me
    if me is None:
        return []
    out = []
    for role in reversed(guild.roles):
        if role.is_default() or role.managed or role >= me.top_role:
            continue
        if not actor.guild_permissions.administrator and role >= actor.top_role:
            continue
        out.append({"id": str(role.id), "name": role.name})
        if len(out) >= 100:
            break
    return out


async def _recent_activity(db, guild_id: int) -> list[dict]:
    items: list[dict] = []
    # Automation runs are guaranteed by V18 once the product backend is installed.
    try:
        rows = await db.fetchall(
            "SELECT automation_id,status,detail,created_at FROM sentrix_dashboard_automation_runs WHERE guild_id = ? ORDER BY id DESC LIMIT 8",
            (guild_id,),
        )
        for raw in rows:
            row = _row_dict(raw)
            items.append({
                "type": "automation",
                "title": f"Automation #{int(row.get('automation_id') or 0)}",
                "detail": str(row.get("detail") or row.get("status") or "Exécution"),
                "status": str(row.get("status") or "info"),
                "created_at": int(row.get("created_at") or 0),
            })
    except Exception:
        pass

    # command_logs has had more than one schema over SentriX's lifetime; try both common names.
    for command_column in ("command_name", "command"):
        try:
            rows = await db.fetchall(
                f"SELECT {command_column} AS name,timestamp FROM command_logs WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 8",
                (guild_id,),
            )
            for raw in rows:
                row = _row_dict(raw)
                items.append({
                    "type": "command",
                    "title": str(row.get("name") or "Commande"),
                    "detail": "Commande exécutée",
                    "status": "info",
                    "created_at": int(row.get("timestamp") or 0),
                })
            break
        except Exception:
            continue
    items.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    return items[:12]


def install(dashboard) -> bool:
    """Extend dashboard.build_app after V18.  Safe to call repeatedly."""
    from web import dashboard_product_v18 as v18

    v18.install(dashboard)
    current_build = dashboard.build_app
    if getattr(current_build, "_sentrix_product_v19", False):
        return True

    previous_build = current_build

    def build_app_with_v19(bot):
        app = previous_build(bot)

        async def live(request: web.Request):
            guild_id, session, guild, actor, error = await v18._require_access(dashboard, request, "view")
            if error:
                return error
            await v18._ensure_tables(bot.db)
            analytics = await v18._analytics(bot.db, guild_id)
            me = guild.me
            perms = me.guild_permissions if me else None
            critical = {
                "manage_roles": bool(perms and perms.manage_roles),
                "manage_channels": bool(perms and perms.manage_channels),
                "manage_messages": bool(perms and perms.manage_messages),
                "moderate_members": bool(perms and perms.moderate_members),
                "kick_members": bool(perms and perms.kick_members),
                "ban_members": bool(perms and perms.ban_members),
                "manage_webhooks": bool(perms and perms.manage_webhooks),
            }
            missing = [name for name, ok in critical.items() if not ok]
            return web.json_response({
                "ok": True,
                "updated_at": int(time.time()),
                "discord_ready": bool(bot.is_ready()),
                "latency_ms": round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000),
                "members": int(guild.member_count or len(guild.members)),
                "channels": len(guild.channels),
                "roles": len(guild.roles),
                "permissions": critical,
                "missing_permissions": missing,
                "analytics": analytics,
                "activity": await _recent_activity(bot.db, guild_id),
                "manageable_roles": _manageable_roles(guild, actor),
            })

        async def checklist(request: web.Request):
            guild_id, session, guild, actor, error = await v18._require_access(dashboard, request, "view")
            if error:
                return error
            snapshot = await v18._snapshot(dashboard, bot.db, guild_id)
            settings = snapshot.get("settings") or {}
            automod = snapshot.get("automod") or {}
            me = guild.me
            perms = me.guild_permissions if me else None
            permissions_ok = bool(perms and perms.manage_roles and perms.manage_channels and perms.manage_messages)
            verification_ok = (
                _truthy_config(settings, "verify", "role")
                or _truthy_config(settings, "verification", "role")
            ) and (
                _truthy_config(settings, "verify", "channel")
                or _truthy_config(settings, "verification", "channel")
            )
            logs_ok = any(
                value not in (None, "", 0, False, "0") and "log" in str(key).casefold() and "channel" in str(key).casefold()
                for key, value in settings.items()
            )
            tickets_ok = any(
                value not in (None, "", 0, False, "0") and "ticket" in str(key).casefold()
                for key, value in settings.items()
            )
            security_ok = any(bool(value) for value in automod.values())
            await v18._ensure_tables(bot.db)
            automation_row = await bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM sentrix_dashboard_automations WHERE guild_id = ? AND enabled = 1",
                (guild_id,),
            )
            automation_count = int(_row_dict(automation_row).get("n") or 0)
            items = [
                {"id": "permissions", "title": "Permissions Discord", "done": permissions_ok, "tab": "diagnostic", "detail": "SentriX peut gérer rôles, salons et messages."},
                {"id": "verification", "title": "Vérification Discord", "done": bool(verification_ok), "tab": "verification", "detail": "Rôle et salon de vérification configurés."},
                {"id": "logs", "title": "Logs", "done": logs_ok, "tab": "logs", "detail": "Au moins un salon de logs est configuré."},
                {"id": "security", "title": "Sécurité", "done": security_ok, "tab": "security", "detail": "Au moins une protection automatique est active."},
                {"id": "tickets", "title": "Tickets", "done": tickets_ok, "tab": "tickets", "detail": "Une configuration ticket est détectée."},
                {"id": "automation", "title": "Automation", "done": automation_count > 0, "tab": "product", "product_tab": "automations", "detail": f"{automation_count} automation(s) active(s)."},
            ]
            done = sum(1 for item in items if item["done"])
            return web.json_response({"ok": True, "items": items, "done": done, "total": len(items), "percent": round(done * 100 / len(items))})

        async def bulk_members(request: web.Request):
            guild_id, session, guild, actor, error = await v18._require_access(dashboard, request, "members")
            if error:
                return error
            csrf = v18._csrf(dashboard, request, session)
            if csrf:
                return csrf
            try:
                payload = await request.json()
            except Exception:
                return dashboard._json_error("Action groupée invalide.", 400)
            raw_ids = payload.get("member_ids") if isinstance(payload.get("member_ids"), list) else []
            member_ids = []
            for value in raw_ids:
                try:
                    member_id = int(value)
                except (TypeError, ValueError):
                    continue
                if member_id not in member_ids:
                    member_ids.append(member_id)
            if not member_ids:
                return dashboard._json_error("Sélectionne au moins un membre.", 400)
            if len(member_ids) > MAX_BULK_TARGETS:
                return dashboard._json_error(f"Maximum {MAX_BULK_TARGETS} membres par action.", 400)
            action = str(payload.get("action") or "")
            if action not in {"timeout", "add_role", "remove_role"}:
                return dashboard._json_error("Cette action groupée n’est pas autorisée.", 400)
            role = None
            if action in {"add_role", "remove_role"}:
                try:
                    role = guild.get_role(int(payload.get("role_id") or 0))
                except (TypeError, ValueError):
                    role = None
                me = guild.me
                if role is None or role.managed or role.is_default() or me is None or role >= me.top_role:
                    return dashboard._json_error("Rôle invalide ou trop haut pour SentriX.", 400)
                if not actor.guild_permissions.administrator and role >= actor.top_role:
                    return dashboard._json_error("Ce rôle est au-dessus de ton rôle Discord.", 403)
            minutes = 10
            if action == "timeout":
                try:
                    minutes = max(1, min(int(payload.get("minutes") or 10), 10080))
                except (TypeError, ValueError):
                    return dashboard._json_error("Durée invalide.", 400)
                if guild.me is None or not guild.me.guild_permissions.moderate_members:
                    return dashboard._json_error("SentriX n’a pas la permission Exclure temporairement.", 409)
            reason = str(payload.get("reason") or f"Action groupée dashboard par {actor}").strip()[:400]
            results = []
            for member_id in member_ids:
                target = await v18._member_for_user(guild, member_id)
                if target is None:
                    results.append({"id": str(member_id), "ok": False, "detail": "Membre introuvable"})
                    continue
                if not v18._target_allowed(actor, target) or not v18._bot_can_manage_member(guild, target):
                    results.append({"id": str(member_id), "ok": False, "detail": "Hiérarchie insuffisante"})
                    continue
                try:
                    if action == "timeout":
                        await target.timeout(datetime.now(UTC) + timedelta(minutes=minutes), reason=reason)
                    elif action == "add_role":
                        await target.add_roles(role, reason=reason)
                    else:
                        await target.remove_roles(role, reason=reason)
                    results.append({"id": str(member_id), "name": target.display_name, "ok": True, "detail": "Action appliquée"})
                except (discord.Forbidden, discord.HTTPException) as exc:
                    results.append({"id": str(member_id), "name": target.display_name, "ok": False, "detail": str(exc)[:160]})
            success = sum(1 for item in results if item["ok"])
            return web.json_response({"ok": True, "message": f"{success}/{len(results)} membre(s) traité(s).", "success": success, "total": len(results), "results": results})

        app.router.add_get("/api/guilds/{guild_id}/product/live", live)
        app.router.add_get("/api/guilds/{guild_id}/product/checklist", checklist)
        app.router.add_post("/api/guilds/{guild_id}/product/members/bulk", bulk_members)
        return app

    build_app_with_v19._sentrix_product_v19 = True
    build_app_with_v19._sentrix_previous = previous_build
    dashboard.build_app = build_app_with_v19
    logger.info("Dashboard Product V19 backend installed: live + checklist + safe bulk actions.")
    return True


__all__ = ["install", "BUILD", "MAX_BULK_TARGETS"]
