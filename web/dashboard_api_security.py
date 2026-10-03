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
    "antilink_strict",
    "antiinvite",
    "antimention",
    "anticaps",
    "antiemoji",
    "antiraid",
    "antibot",
    "antiaccount",
    "antiscam",
    "antiinsult",
    "antinuke",
    "security_vanity",
    "security_prune",
    "security_permissions",
    "join_gate",
    "risk_engine",
    "escalation",
)

# Catalogue unique utilisé par le dashboard. L'objectif est d'avoir un vrai
# centre de sécurité : toutes les protections sont visibles et configurables,
# pas uniquement l'anti-spam ou les filtres de messages.
_PROTECTION_CATALOG = {
    "antispam": {
        "label": "Anti-spam",
        "group": "Messages",
        "description": "Bloque le flood, les rafales et les répétitions de messages.",
        "supports_policy": True,
    },
    "antilink": {
        "label": "Anti-liens",
        "group": "Messages",
        "description": "Bloque les liens non autorisés selon la politique du serveur.",
        "supports_policy": True,
    },
    "antilink_strict": {
        "label": "Blocage total des liens",
        "group": "Messages",
        "description": "Renforce l'anti-liens et refuse tout lien hors exceptions explicites.",
        "supports_policy": False,
    },
    "antiinvite": {
        "label": "Anti-invitations",
        "group": "Messages",
        "description": "Bloque les invitations Discord non autorisées.",
        "supports_policy": True,
    },
    "antimention": {
        "label": "Anti-mentions",
        "group": "Messages",
        "description": "Bloque les abus de mentions et les pings massifs.",
        "supports_policy": True,
    },
    "anticaps": {
        "label": "Anti-majuscules",
        "group": "Messages",
        "description": "Réduit les messages abusivement écrits en majuscules.",
        "supports_policy": True,
    },
    "antiemoji": {
        "label": "Anti-émojis",
        "group": "Messages",
        "description": "Bloque le flood massif d'émojis.",
        "supports_policy": True,
    },
    "antiscam": {
        "label": "Anti-scam",
        "group": "Messages",
        "description": "Détecte phishing, faux Nitro, crypto et pièces jointes dangereuses.",
        "supports_policy": True,
    },
    "antiinsult": {
        "label": "Anti-insultes / mots interdits",
        "group": "Messages",
        "description": "Bloque les insultes et les mots interdits configurés.",
        "supports_policy": True,
    },
    "antiraid": {
        "label": "Anti-raid",
        "group": "Arrivées",
        "description": "Détecte les arrivées massives et déclenche les protections anti-raid.",
        "supports_policy": False,
    },
    "antibot": {
        "label": "Anti-bots",
        "group": "Arrivées",
        "description": "Bloque ou contrôle les ajouts de bots suspects.",
        "supports_policy": False,
    },
    "antiaccount": {
        "label": "Anti-comptes récents",
        "group": "Arrivées",
        "description": "Filtre les comptes Discord trop récents.",
        "supports_policy": False,
    },
    "join_gate": {
        "label": "Join Gate",
        "group": "Arrivées",
        "description": "Combine âge du compte, avatar et vitesse d'arrivée avant d'accorder la confiance.",
        "supports_policy": False,
    },
    "risk_engine": {
        "label": "Moteur de risque",
        "group": "Arrivées",
        "description": "Combine plusieurs signaux de risque et déclenche des alertes graduées.",
        "supports_policy": False,
    },
    "antinuke": {
        "label": "Anti-nuke",
        "group": "Serveur",
        "description": "Protège les rôles, salons, webhooks et actions critiques.",
        "supports_policy": False,
    },
    "security_vanity": {
        "label": "Protection Vanity URL",
        "group": "Serveur",
        "description": "Détecte et restaure les changements suspects du lien personnalisé.",
        "supports_policy": False,
    },
    "security_prune": {
        "label": "Protection Prune",
        "group": "Serveur",
        "description": "Détecte les suppressions massives de membres via le journal d'audit.",
        "supports_policy": False,
    },
    "security_permissions": {
        "label": "Permissions dangereuses",
        "group": "Serveur",
        "description": "Bloque les élévations critiques de permissions sur les rôles et salons.",
        "supports_policy": False,
    },
    "escalation": {
        "label": "Escalade AutoMod",
        "group": "Réponse",
        "description": "Augmente progressivement les sanctions lors des récidives.",
        "supports_policy": False,
    },
}

_POLICY_FILTERS = {
    key: meta["label"]
    for key, meta in _PROTECTION_CATALOG.items()
    if meta["supports_policy"]
}

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
            "events_24h": len(last_24h),
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

    async def _policy_payload(guild: discord.Guild, filter_name: str) -> dict:
        meta = _PROTECTION_CATALOG[filter_name]
        conf = await bot.db.get_automod(guild.id)
        policy = {"role_ids": [], "strict_channel_ids": []}
        if meta["supports_policy"]:
            reader = getattr(bot.db, "get_security_filter_policy", None)
            if callable(reader):
                policy = await reader(guild.id, filter_name)
            else:
                role_rows = await bot.db.fetchall(
                    "SELECT role_id FROM security_filter_bypass_roles "
                    "WHERE guild_id=? AND filter_name=? ORDER BY role_id",
                    (guild.id, filter_name),
                )
                channel_rows = await bot.db.fetchall(
                    "SELECT channel_id FROM security_filter_strict_channels "
                    "WHERE guild_id=? AND filter_name=? ORDER BY channel_id",
                    (guild.id, filter_name),
                )
                policy = {
                    "role_ids": [int(row["role_id"]) for row in role_rows],
                    "strict_channel_ids": [int(row["channel_id"]) for row in channel_rows],
                }
        try:
            enabled = bool(conf and conf[filter_name])
        except (KeyError, IndexError, TypeError):
            enabled = False
        return {
            "key": filter_name,
            "label": meta["label"],
            "group": meta["group"],
            "description": meta["description"],
            "supports_policy": bool(meta["supports_policy"]),
            "enabled": enabled,
            "role_ids": [str(value) for value in policy.get("role_ids", [])],
            "strict_channel_ids": [
                str(value) for value in policy.get("strict_channel_ids", [])
            ],
        }

    async def _sync_policy_runtime(guild: discord.Guild, filter_name: str) -> None:
        automod = bot.get_cog("Automod") if hasattr(bot, "get_cog") else None
        if automod is None:
            return
        invalidate = getattr(automod, "invalidate_security_filter_policy", None)
        if callable(invalidate):
            invalidate(guild.id, filter_name)
        else:
            getattr(automod, "antispam_policy_cache", {}).pop(guild.id, None)

        try:
            if filter_name == "antilink":
                await automod._sync_native_antilink_rule(guild)
                await automod._sync_native_target_links_rule(guild)
            elif filter_name == "antiinvite":
                await automod._sync_native_antiinvite_rule(guild)
            elif filter_name == "antiscam":
                await automod._sync_native_antiscam_rule(guild)
            elif filter_name == "antimention":
                await automod._sync_native_antimention_rule(guild)
            elif filter_name == "antiinsult":
                await automod._sync_native_blacklist_rule(guild)
        except Exception:
            # Le moteur local reste autoritaire même si Discord AutoMod natif
            # est indisponible ou n'a pas la permission Gérer le serveur.
            pass

    async def _save_policy(
        guild: discord.Guild,
        filter_name: str,
        payload: dict,
        *,
        legacy_channel_key: bool = False,
    ):
        if filter_name not in _PROTECTION_CATALOG:
            return dashboard._json_error("Protection de sécurité inconnue.", 400)
        if not _PROTECTION_CATALOG[filter_name]["supports_policy"]:
            return dashboard._json_error(
                "Cette protection est globale au serveur et n'utilise pas de rôles bypass / salons stricts.",
                400,
            )

        raw_roles = (payload or {}).get("role_ids") or []
        raw_channels = (payload or {}).get("strict_channel_ids")
        if raw_channels is None and legacy_channel_key:
            raw_channels = (payload or {}).get("channel_ids") or []
        raw_channels = raw_channels or []
        try:
            role_ids = list(dict.fromkeys(int(value) for value in raw_roles))[:25]
            strict_channel_ids = list(
                dict.fromkeys(int(value) for value in raw_channels)
            )[:25]
        except (TypeError, ValueError):
            return dashboard._json_error("Rôle ou salon invalide.", 400)

        valid_roles = {
            int(role.id)
            for role in guild.roles
            if role != guild.default_role
        }
        valid_channels = {
            int(channel.id)
            for channel in guild.channels
            if isinstance(channel, (discord.TextChannel, discord.ForumChannel))
        }
        if any(role_id not in valid_roles for role_id in role_ids):
            return dashboard._json_error("Un rôle sélectionné n'existe plus.", 409)
        if any(channel_id not in valid_channels for channel_id in strict_channel_ids):
            return dashboard._json_error("Un salon sélectionné n'existe plus.", 409)

        writer = getattr(bot.db, "set_security_filter_policy", None)
        if callable(writer):
            await writer(
                guild.id,
                filter_name,
                role_ids=role_ids,
                strict_channel_ids=strict_channel_ids,
            )
        else:
            await bot.db.execute(
                "DELETE FROM security_filter_bypass_roles "
                "WHERE guild_id=? AND filter_name=?",
                (guild.id, filter_name),
            )
            for role_id in role_ids:
                await bot.db.execute(
                    "INSERT OR IGNORE INTO security_filter_bypass_roles "
                    "(guild_id,filter_name,role_id) VALUES (?,?,?)",
                    (guild.id, filter_name, role_id),
                )
            await bot.db.execute(
                "DELETE FROM security_filter_strict_channels "
                "WHERE guild_id=? AND filter_name=?",
                (guild.id, filter_name),
            )
            for channel_id in strict_channel_ids:
                await bot.db.execute(
                    "INSERT OR IGNORE INTO security_filter_strict_channels "
                    "(guild_id,filter_name,channel_id) VALUES (?,?,?)",
                    (guild.id, filter_name, channel_id),
                )

        await _sync_policy_runtime(guild, filter_name)
        return None

    async def filter_policies(request: web.Request):
        write = request.method == "POST"
        _session, guild, error = await _guard(request, write=write)
        if error:
            return error

        saved_filter = None
        if write:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            saved_filter = str((payload or {}).get("filter_name") or "").strip().casefold()
            save_error = await _save_policy(guild, saved_filter, payload or {})
            if save_error:
                return save_error

        filters = {
            key: await _policy_payload(guild, key)
            for key in _PROTECTION_CATALOG
        }
        return web.json_response({
            "ok": True,
            "filters": filters,
            "message": (
                f"Exceptions {_POLICY_FILTERS[saved_filter]} enregistrées."
                if saved_filter else None
            ),
        })

    async def antispam_policy(request: web.Request):
        """Compatibilité de l'ancien endpoint V1.

        L'ancien champ channel_ids est désormais interprété comme salons STRICTS,
        pas comme un périmètre où l'anti-spam serait le seul à s'appliquer.
        """
        write = request.method == "POST"
        _session, guild, error = await _guard(request, write=write)
        if error:
            return error

        if write:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            save_error = await _save_policy(
                guild,
                "antispam",
                payload or {},
                legacy_channel_key=True,
            )
            if save_error:
                return save_error

        policy = await _policy_payload(guild, "antispam")
        strict = policy["strict_channel_ids"]
        return web.json_response({
            "ok": True,
            "enabled": policy["enabled"],
            "scope_mode": "all",
            "role_ids": policy["role_ids"],
            "channel_ids": strict,
            "strict_channel_ids": strict,
            "message": "Exceptions anti-spam enregistrées." if write else None,
        })

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
    app.router.add_get("/api/guilds/{guild_id}/security/filter-policies", filter_policies)
    app.router.add_post("/api/guilds/{guild_id}/security/filter-policies", filter_policies)
    app.router.add_get("/api/guilds/{guild_id}/security/antispam-policy", antispam_policy)
    app.router.add_post("/api/guilds/{guild_id}/security/antispam-policy", antispam_policy)
    app.router.add_post("/api/guilds/{guild_id}/security/panic", panic)


__all__ = ["register"]
