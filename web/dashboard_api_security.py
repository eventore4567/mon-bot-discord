"""API d'observabilité et de réponse aux incidents pour le dashboard SentriX.

Cette couche ne remplace aucun moteur de sécurité. Elle expose l'état réel des
protections existantes, une simulation non destructive et le mode PANIC déjà utilisé
par SecurityHardening.
"""
from __future__ import annotations

import json
import time

import discord
from aiohttp import web

import config
from cogs.security_runtime_hardening import apply_recommended_security
from database.db import PRIMARY_CREATOR_ID


_FILTERS = (
    "antispam",
    "antilink",
    "antiinvite",
    "antimention",
    "anticaps",
    "antiemoji",
    "antiraid",
    "antiscam",
    "antinuke",
    "escalation",
)

_PERMISSION_META = (
    ("manage_messages", "Gérer les messages", 8),
    ("view_audit_log", "Voir le journal d'audit", 12),
    ("kick_members", "Expulser des membres", 4),
    ("ban_members", "Bannir des membres", 4),
    ("moderate_members", "Exclure temporairement des membres", 4),
    ("manage_roles", "Gérer les rôles", 8),
    ("manage_channels", "Gérer les salons", 8),
)

_SCENARIOS = (
    ("spam", "Spam / flood", "antispam", ("manage_messages",)),
    ("link", "Lien non autorisé", "antilink", ("manage_messages",)),
    ("invite", "Invitation Discord", "antiinvite", ("manage_messages",)),
    ("scam", "Arnaque / phishing", "antiscam", ("manage_messages",)),
    ("raid", "Arrivées en rafale", "antiraid", ("kick_members",)),
    ("nuke", "Suppression/création massive", "antinuke", ("view_audit_log", "manage_roles", "manage_channels")),
)

_EVENT_LABELS = {
    "dangerous_attachment": "Pièce jointe dangereuse bloquée",
    "panic_on": "Mode PANIC activé",
    "panic_off": "Mode PANIC restauré",
    "panic_restore_partial": "Restauration PANIC partielle",
}


def register(app: web.Application, dashboard) -> None:
    bot = app["bot"]

    async def _guard(request: web.Request, *, write: bool = False):
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return None, None, error
        if write:
            csrf_error = dashboard._require_csrf(request, session)
            if csrf_error:
                return None, None, csrf_error
        return session, guild, None

    async def _is_critical_owner(session: dict, guild: discord.Guild) -> bool:
        user_id = int(session["user"]["id"])
        if user_id == guild.owner_id or user_id == PRIMARY_CREATOR_ID or user_id in config.OWNER_IDS:
            return True
        try:
            return bool(await bot.db.is_bot_creator(user_id))
        except Exception:
            return False

    def _permissions(guild: discord.Guild):
        me = guild.me
        perms = getattr(me, "guild_permissions", None)
        rows = []
        missing_weight = 0
        for key, label, weight in _PERMISSION_META:
            granted = bool(perms and getattr(perms, key, False))
            rows.append({"key": key, "name": label, "granted": granted})
            if not granted:
                missing_weight += weight
        return rows, missing_weight

    async def _timeline(guild_id: int, limit: int = 30) -> list[dict]:
        items: list[dict] = []
        try:
            rows = await bot.db.fetchall(
                "SELECT actor_id,event_type,detail,created_at FROM security_events "
                "WHERE guild_id=? ORDER BY created_at DESC,id DESC LIMIT ?",
                (guild_id, limit),
            )
            for row in rows:
                event_type = str(row["event_type"] or "security")
                items.append({
                    "source": "security",
                    "type": event_type,
                    "label": _EVENT_LABELS.get(event_type, event_type.replace("_", " ").title()),
                    "actor_id": str(row["actor_id"]) if row["actor_id"] else None,
                    "detail": str(row["detail"] or ""),
                    "created_at": int(row["created_at"] or 0),
                })
        except Exception:
            pass

        try:
            rows = await bot.db.fetchall(
                "SELECT actor_id,reason,summary_json,created_at FROM security_incidents "
                "WHERE guild_id=? ORDER BY created_at DESC,id DESC LIMIT ?",
                (guild_id, limit),
            )
            for row in rows:
                detail = str(row["reason"] or "Incident anti-nuke")
                try:
                    summary = json.loads(row["summary_json"] or "{}")
                except Exception:
                    summary = {}
                if summary:
                    compact = ", ".join(f"{k}: {v}" for k, v in list(summary.items())[:4])
                    if compact:
                        detail = f"{detail} · {compact}"
                items.append({
                    "source": "incident",
                    "type": "antinuke_incident",
                    "label": "Incident anti-nuke",
                    "actor_id": str(row["actor_id"]) if row["actor_id"] else None,
                    "detail": detail,
                    "created_at": int(row["created_at"] or 0),
                })
        except Exception:
            pass

        try:
            rows = await bot.db.automod_recent(guild_id, limit=limit)
            for row in rows:
                items.append({
                    "source": "automod",
                    "type": str(row["filter_name"] or "automod"),
                    "label": f"AutoMod · {row['filter_name']}",
                    "actor_id": str(row["user_id"]) if row["user_id"] else None,
                    "detail": str(row["reason"] or row["action"] or ""),
                    "created_at": int(row["timestamp"] or 0),
                })
        except Exception:
            pass

        items.sort(key=lambda item: int(item["created_at"]), reverse=True)
        return items[:limit]

    async def _overview_payload(guild: discord.Guild, *, owner_controls: bool) -> dict:
        conf_row = await bot.db.get_automod(guild.id)
        conf = dict(conf_row) if conf_row else {}
        active = sum(1 for key in _FILTERS if bool(conf.get(key, 0)))
        coverage_penalty = (len(_FILTERS) - active) * 4

        permissions, permission_penalty = _permissions(guild)
        hardening = bot.get_cog("SecurityHardening") if hasattr(bot, "get_cog") else None
        panic_row = await hardening._panic_row(guild.id) if hardening is not None else None

        now_ts = int(time.time())
        recent = await _timeline(guild.id, 40)
        last_24h = [item for item in recent if now_ts - int(item["created_at"] or 0) <= 86400]
        severe = sum(1 for item in last_24h if item["source"] == "incident")
        dangerous = sum(1 for item in last_24h if item["type"] == "dangerous_attachment")
        incident_penalty = min(18, severe * 6) + min(12, dangerous * 4)
        panic_penalty = 20 if panic_row else 0
        risk = max(0, min(100, coverage_penalty + permission_penalty + incident_penalty + panic_penalty))
        protection_score = 100 - risk
        risk_level = "faible" if risk < 25 else "moyen" if risk < 55 else "eleve"

        scenarios = []
        me = guild.me
        perms = getattr(me, "guild_permissions", None)
        for key, label, filter_name, required in _SCENARIOS:
            detected = bool(conf.get(filter_name, 0))
            missing = [
                next((name for pkey, name, _w in _PERMISSION_META if pkey == perm), perm)
                for perm in required
                if not bool(perms and getattr(perms, perm, False))
            ]
            scenarios.append({
                "key": key,
                "label": label,
                "filter": filter_name,
                "detected": detected,
                "enforceable": detected and not missing,
                "missing_permissions": missing,
                "result": "bloque" if detected and not missing else "detecte_sans_action" if detected else "non_couvert",
            })

        return {
            "ok": True,
            "risk": {"score": risk, "protection_score": protection_score, "level": risk_level},
            "coverage": {"active": active, "total": len(_FILTERS)},
            "permissions": permissions,
            "incidents_24h": len(last_24h),
            "severe_incidents_24h": severe,
            "panic": {
                "active": bool(panic_row),
                "created_at": int(panic_row["created_at"]) if panic_row else None,
                "created_by": str(panic_row["created_by"]) if panic_row else None,
                "owner_controls": bool(owner_controls),
            },
            "scenarios": scenarios,
            "timeline": recent[:25],
        }

    async def overview(request: web.Request):
        session, guild, error = await _guard(request)
        if error:
            return error
        return web.json_response(
            await _overview_payload(
                guild,
                owner_controls=await _is_critical_owner(session, guild),
            )
        )

    async def simulate(request: web.Request):
        session, guild, error = await _guard(request)
        if error:
            return error
        data = await _overview_payload(
            guild,
            owner_controls=await _is_critical_owner(session, guild),
        )
        return web.json_response({
            "ok": True,
            "dry_run": True,
            "scenarios": data["scenarios"],
            "note": "Simulation de configuration uniquement : aucune action Discord n'a été exécutée.",
        })

    async def panic(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        if not await _is_critical_owner(session, guild):
            return dashboard._json_error(
                "Le mode PANIC est réservé au propriétaire du serveur ou du bot.",
                403,
            )
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        action = str((payload or {}).get("action") or "").strip().lower()
        if action not in {"on", "off"}:
            return dashboard._json_error("Action PANIC invalide.", 400)

        hardening = bot.get_cog("SecurityHardening") if hasattr(bot, "get_cog") else None
        if hardening is None:
            return dashboard._json_error("Le moteur d'urgence n'est pas chargé.", 503)

        rate_key = (request.cookies.get(dashboard.SESSION_COOKIE), guild.id, "dashboard-security-panic")
        previous = request.app["write_limits"].get(rate_key, 0)
        if time.time() - previous < 8:
            return dashboard._json_error("Attendez quelques secondes avant une nouvelle action PANIC.", 429)

        actor_id = int(session["user"]["id"])
        lock = hardening._panic_locks[guild.id]
        async with lock:
            row = await hardening._panic_row(guild.id)
            if action == "on":
                if row:
                    return web.json_response({"ok": True, "active": True, "message": "Le mode PANIC est déjà actif."})

                state = {}
                for channel in guild.text_channels:
                    overwrite = channel.overwrites_for(guild.default_role)
                    state[str(channel.id)] = overwrite.send_messages

                now_ts = int(time.time())
                await bot.db.execute(
                    "INSERT INTO panic_snapshots (guild_id,created_by,created_at,state_json,active) "
                    "VALUES (?,?,?,?,1) ON CONFLICT(guild_id) DO UPDATE SET "
                    "created_by=excluded.created_by,created_at=excluded.created_at,"
                    "state_json=excluded.state_json,active=1",
                    (guild.id, actor_id, now_ts, json.dumps(state, separators=(",", ":"))),
                )

                recommended = await apply_recommended_security(bot, guild)
                locked = 0
                failed = []
                for channel in guild.text_channels:
                    if await hardening._lock_text_channel(
                        channel,
                        f"Mode PANIC activé depuis le dashboard par {actor_id}",
                    ):
                        locked += 1
                    else:
                        failed.append(str(channel.id))
                await hardening._security_event(
                    guild.id,
                    "panic_on",
                    actor_id=actor_id,
                    detail=f"{locked} salon(s) verrouillé(s); {len(failed)} échec(s)",
                )
                request.app["write_limits"][rate_key] = time.time()
                return web.json_response({
                    "ok": True,
                    "active": True,
                    "message": f"Mode PANIC activé : {locked} salon(s) verrouillé(s).",
                    "locked": locked,
                    "failed": failed,
                    "missing_permissions": recommended.get("missing_permissions", []),
                })

            if not row:
                return web.json_response({"ok": True, "active": False, "message": "Le mode PANIC est déjà inactif."})

            try:
                state = json.loads(row["state_json"] or "{}")
            except (TypeError, ValueError):
                return dashboard._json_error(
                    "Le snapshot PANIC est illisible. Aucune permission n'a été modifiée.",
                    409,
                )

            restored = 0
            failed = []
            for channel_id, previous_value in state.items():
                try:
                    channel = guild.get_channel(int(channel_id))
                except (TypeError, ValueError):
                    channel = None
                if channel is None or not isinstance(channel, discord.TextChannel):
                    continue
                overwrite = channel.overwrites_for(guild.default_role)
                overwrite.send_messages = previous_value if previous_value in (True, False, None) else None
                try:
                    await channel.set_permissions(
                        guild.default_role,
                        overwrite=overwrite,
                        reason=f"Fin du mode PANIC depuis le dashboard par {actor_id}",
                    )
                    restored += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed.append(str(channel.id))

            if not failed:
                await bot.db.execute(
                    "UPDATE panic_snapshots SET active=0 WHERE guild_id=?",
                    (guild.id,),
                )
            await hardening._security_event(
                guild.id,
                "panic_off" if not failed else "panic_restore_partial",
                actor_id=actor_id,
                detail=f"{restored} restauré(s); {len(failed)} échec(s)",
            )
            request.app["write_limits"][rate_key] = time.time()
            return web.json_response({
                "ok": True,
                "active": bool(failed),
                "partial": bool(failed),
                "message": (
                    f"Mode PANIC restauré : {restored} salon(s)."
                    if not failed
                    else f"Restauration partielle : {restored} salon(s), {len(failed)} échec(s)."
                ),
                "restored": restored,
                "failed": failed,
            })

    app.router.add_get("/api/guilds/{guild_id}/security/overview", overview)
    app.router.add_get("/api/guilds/{guild_id}/security/simulate", simulate)
    app.router.add_post("/api/guilds/{guild_id}/security/panic", panic)


__all__ = ["register"]
