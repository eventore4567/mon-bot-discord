"""Diagnostics réels et flux live du dashboard SentriX.

Le diagnostic reste calculé depuis Discord + la base. V19 réduit les attentes DB en lançant
les lectures indépendantes ensemble, coalesce uniquement les requêtes simultanées du même
serveur (sans cache TTL), instrumente le temps de réponse et expose un flux SSE léger pour
les KPI opérationnels. Les permissions restent revérifiées côté serveur avant chaque accès.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard-v60-diagnostics")
_INSTALLED = False


def _status(code: str, detail: str, *, configured: bool = False) -> dict:
    labels = {
        "active": "ACTIF",
        "inactive": "INACTIF",
        "missing": "NON CONFIGURÉ",
        "error": "ERREUR DE CONFIGURATION",
    }
    return {"code": code, "status": labels[code], "detail": detail, "configured": configured}


def _optional_id(value) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _diagnostic_payload(dashboard, bot, guild: discord.Guild) -> dict:
    guild_id = guild.id
    db = bot.db
    conf_row, automod_row, ai_row, social_rows = await asyncio.gather(
        db.get_guild_config(guild_id),
        db.get_automod(guild_id),
        db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,)),
        db.fetchall(
            "SELECT discord_channel_id, role_id, enabled FROM social_notifications WHERE guild_id = ?",
            (guild_id,),
        ),
    )
    conf = dict(conf_row) if conf_row else {}
    automod = dict(automod_row) if automod_row else {}
    ai = dict(ai_row) if ai_row else {}

    bot_member = guild.me
    permissions = getattr(bot_member, "guild_permissions", None)
    permission_names = (
        ("administrator", "Administrateur"),
        ("manage_guild", "Gérer le serveur"),
        ("manage_roles", "Gérer les rôles"),
        ("manage_channels", "Gérer les salons"),
        ("manage_messages", "Gérer les messages"),
        ("moderate_members", "Exclure temporairement des membres"),
        ("kick_members", "Expulser des membres"),
        ("ban_members", "Bannir des membres"),
        ("view_audit_log", "Voir les logs d'audit"),
        ("manage_webhooks", "Gérer les webhooks"),
        ("send_messages", "Envoyer des messages"),
        ("embed_links", "Intégrer des liens"),
    )
    permission_payload = [
        {
            "key": key,
            "name": label,
            "granted": bool(getattr(permissions, key, False)) if permissions is not None else False,
        }
        for key, label in permission_names
    ]

    channel_fields = {
        "welcome_channel", "goodbye_channel", "log_channel", "level_channel",
        "ticket_log_channel", "verification_channel", "suggest_channel", "report_channel",
        "announce_channel", "giveaway_channel", "bot_commands_channel", "partner_channel",
        "stats_channel", "afk_channel", "error_channel", "log_messages", "log_members",
        "log_voice", "log_roles", "log_server", "log_automod", "log_moderation",
    }
    message_channel_fields = channel_fields - {"afk_channel"}
    role_fields = {
        "mod_role", "admin_role", "mute_role", "verification_role", "verify_role",
        "autorole", "warn_role", "member_role", "booster_role",
    }
    assignable_role_fields = {
        "mute_role", "verification_role", "verify_role", "autorole",
        "warn_role", "member_role", "booster_role",
    }
    invalid_resources: list[dict] = []

    def add_invalid(field: str, value: int, kind: str, reason: str) -> None:
        invalid_resources.append({"field": field, "id": str(value), "type": kind, "reason": reason})

    for field in sorted(channel_fields):
        value = _optional_id(conf.get(field))
        if value is None:
            continue
        channel = guild.get_channel(value)
        if channel is None:
            add_invalid(field, value, "channel", "deleted")
            continue
        if bot_member is not None and field in message_channel_fields and hasattr(channel, "permissions_for"):
            perms = channel.permissions_for(bot_member)
            if not getattr(perms, "view_channel", False) or not getattr(perms, "send_messages", False):
                add_invalid(field, value, "channel", "missing_send_permission")
                continue
            if field.startswith("log_") or field in {"log_channel", "ticket_log_channel"}:
                if not getattr(perms, "embed_links", False):
                    add_invalid(field, value, "channel", "missing_embed_permission")

    category_id = _optional_id(conf.get("ticket_category"))
    if category_id is not None:
        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            add_invalid("ticket_category", category_id, "category", "deleted_or_wrong_type")
        elif bot_member is not None:
            category_perms = category.permissions_for(bot_member)
            if not getattr(category_perms, "view_channel", False):
                add_invalid("ticket_category", category_id, "category", "missing_view_permission")

    for field in sorted(role_fields):
        value = _optional_id(conf.get(field))
        if value is None:
            continue
        role = guild.get_role(value)
        if role is None:
            add_invalid(field, value, "role", "deleted")
            continue
        if field in assignable_role_fields and bot_member is not None:
            if not getattr(permissions, "manage_roles", False):
                add_invalid(field, value, "role", "missing_manage_roles")
            elif role >= bot_member.top_role:
                add_invalid(field, value, "role", "above_bot_role")

    invalid_by_field = {item["field"] for item in invalid_resources}

    def channel_module(field: str, active_detail: str, missing_detail: str) -> dict:
        value = _optional_id(conf.get(field))
        if value is None:
            return _status("missing", missing_detail)
        if field in invalid_by_field:
            return _status(
                "error",
                "Le salon configuré n'existe plus ou SentriX n'a pas les permissions nécessaires.",
                configured=True,
            )
        return _status("active", active_detail, configured=True)

    modules: dict[str, dict] = {
        "welcome": channel_module("welcome_channel", "Salon choisi.", "Aucun salon choisi."),
        "levels": channel_module("level_channel", "Salon d'annonces choisi.", "Aucun salon d'annonces choisi."),
        "suggestions": channel_module("suggest_channel", "Salon choisi.", "Aucun salon choisi."),
        "reports": channel_module("report_channel", "Salon choisi.", "Aucun salon choisi."),
    }

    log_fields = ["log_channel", "log_messages", "log_members", "log_voice", "log_roles", "log_server", "log_automod", "log_moderation"]
    configured_logs = [field for field in log_fields if _optional_id(conf.get(field)) is not None]
    if any(field in invalid_by_field for field in configured_logs):
        modules["logs"] = _status("error", "Au moins un salon de logs est supprimé ou inutilisable par SentriX.", configured=True)
    elif configured_logs:
        modules["logs"] = _status("active", f"{len(configured_logs)} type(s) de logs ont un salon valide.", configured=True)
    else:
        modules["logs"] = _status("missing", "Aucun salon de logs choisi.")

    configured_roles = [field for field in role_fields if _optional_id(conf.get(field)) is not None]
    if any(field in invalid_by_field for field in configured_roles):
        modules["roles"] = _status("error", "Au moins un rôle est supprimé ou placé au-dessus de SentriX.", configured=True)
    elif configured_roles:
        modules["roles"] = _status("active", f"{len(configured_roles)} rôle(s) SentriX sont configurés.", configured=True)
    else:
        modules["roles"] = _status("missing", "Aucun rôle SentriX n'est configuré.")

    ticket_values = [conf.get("ticket_category"), conf.get("ticket_log_channel")]
    if "ticket_category" in invalid_by_field or "ticket_log_channel" in invalid_by_field:
        modules["tickets"] = _status("error", "Une ressource du système de tickets est supprimée ou inaccessible.", configured=True)
    elif any(_optional_id(value) is not None for value in ticket_values):
        modules["tickets"] = _status("active", "La base du système de tickets est configurée.", configured=True)
    else:
        modules["tickets"] = _status("missing", "Catégorie et logs tickets non configurés.")

    # L'escalade est un réglage par défaut, pas une protection : elle ne compte pas.
    automod_values = [bool(automod.get(name)) for name in dashboard.AUTOMOD_FIELDS if name != "escalation"]
    modules["automod"] = (
        _status("active", f"{sum(automod_values)} protection(s) AutoMod sont actives.", configured=True)
        if any(automod_values)
        else _status("inactive", "Les protections AutoMod sont actuellement désactivées.", configured=True)
    )
    modules["ai"] = (
        _status("active", "L'IA SentriX est autorisée sur ce serveur.", configured=True)
        if bool(ai.get("enabled"))
        else _status("inactive", "L'IA SentriX est désactivée sur ce serveur.", configured=True)
    )

    invalid_social = 0
    active_social = 0
    for row in social_rows:
        if not bool(row["enabled"]):
            continue
        active_social += 1
        try:
            social_channel = guild.get_channel(int(row["discord_channel_id"]))
            social_role = guild.get_role(int(row["role_id"]))
        except (TypeError, ValueError):
            social_channel = None
            social_role = None
        if social_channel is None or social_role is None:
            invalid_social += 1
            continue
        if bot_member is not None and hasattr(social_channel, "permissions_for"):
            social_perms = social_channel.permissions_for(bot_member)
            if not getattr(social_perms, "view_channel", False) or not getattr(social_perms, "send_messages", False):
                invalid_social += 1
    if invalid_social:
        modules["notifications"] = _status("error", f"{invalid_social} notification(s) pointent vers une ressource supprimée ou inaccessible.", configured=True)
    elif active_social:
        modules["notifications"] = _status("active", f"{active_social} source(s) sociales sont actives.", configured=True)
    else:
        modules["notifications"] = _status("missing", "Aucune notification sociale n'est configurée.")

    moderation_perms = bool(
        permissions
        and (
            getattr(permissions, "administrator", False)
            or getattr(permissions, "moderate_members", False)
            or getattr(permissions, "kick_members", False)
            or getattr(permissions, "ban_members", False)
        )
    )
    modules["moderation"] = (
        _status("active", "SentriX possède au moins une permission de modération.", configured=True)
        if moderation_perms
        else _status("error", "SentriX ne possède aucune permission de modération utile.", configured=True)
    )

    # Départ et économie : deux modules distincts de la bienvenue et des niveaux.
    modules["goodbye"] = channel_module("goodbye_channel", "Salon choisi.", "Aucun salon choisi.")
    modules["economy"] = _status("active", "Le système d'argent est disponible.", configured=True)

    # Source unique : l'interrupteur de module (module_settings, le même que /setup et
    # +level-system). Sans lui le Dashboard disait ACTIF pour un module coupé dans
    # Discord, ou pour un module jamais activé dont un salon traînait en base.
    try:
        from cogs import setup_v2_core as core

        module_for_key = {
            "welcome": "welcome", "goodbye": "goodbye", "levels": "levels", "economy": "economy",
            "logs": "logs", "roles": "roles", "tickets": "tickets", "notifications": "notifications",
            "moderation": "moderation", "automod": "security", "ai": "ai",
        }
        for key, module in module_for_key.items():
            if key not in modules:
                continue
            switch = await core.module_state(bot, guild.id, module)
            if switch == core.MODULE_STATE_DISABLED:
                modules[key] = _status("inactive", "Désactivé. Réglages conservés.", configured=True)
            elif switch == core.MODULE_STATE_NOT_CONFIGURED and modules[key]["code"] != "missing":
                modules[key] = _status("missing", "Pas encore activé.")
            elif switch == core.MODULE_STATE_ENABLED and key == "ai" and modules[key]["code"] == "inactive":
                modules[key] = _status("active", "Activée avec les réglages par défaut.", configured=True)
            elif switch == core.MODULE_STATE_ENABLED and modules[key]["code"] == "missing":
                # Activé dans la configuration mais sans ressource en base.
                if key in ("welcome", "goodbye"):
                    modules[key] = _status("error", "Activé, mais aucun salon choisi : rien ne sera envoyé.", configured=True)
                else:
                    modules[key] = _status("active", "Activé.", configured=True)
    except Exception:
        logger.exception("Lecture des interrupteurs de modules impossible guild=%s", guild.id)

    total = len(modules)
    active = sum(1 for item in modules.values() if item["code"] == "active")
    valid_inactive = sum(1 for item in modules.values() if item["code"] == "inactive")
    errors = sum(1 for item in modules.values() if item["code"] == "error")
    score = round(((active + valid_inactive * 0.5) / total) * 100) if total else 0
    return {
        "ok": True,
        "score": score,
        "summary": {
            "active": active,
            "inactive": valid_inactive,
            "missing": sum(1 for item in modules.values() if item["code"] == "missing"),
            "errors": errors,
        },
        "modules": modules,
        "permissions": permission_payload,
        "invalid_resources": invalid_resources,
        "bot": {
            "id": str(bot_member.id) if bot_member else None,
            "top_role_position": int(bot_member.top_role.position) if bot_member else None,
        },
    }


async def _live_metrics(dashboard, bot, guild: discord.Guild) -> dict:
    row = await bot.db.fetchone(
        """
        SELECT
            (SELECT COUNT(*) FROM warnings WHERE guild_id = ?) AS warnings,
            (SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'ouvert') AS open_tickets,
            (SELECT COUNT(*) FROM command_logs WHERE guild_id = ? AND timestamp >= ?) AS commands_24h,
            (SELECT COALESCE(MAX(id), 0) FROM sanctions WHERE guild_id = ?) AS sanctions_revision
        """,
        (guild.id, guild.id, guild.id, dashboard.now() - 86400, guild.id),
    )
    return {
        "online": bool(bot.is_ready()),
        "latency_ms": round(bot.latency * 1000) if bot.is_ready() else None,
        "members": int(guild.member_count or 0),
        "warnings": int(row["warnings"] or 0) if row else 0,
        "open_tickets": int(row["open_tickets"] or 0) if row else 0,
        "commands_24h": int(row["commands_24h"] or 0) if row else 0,
        "sanctions_revision": int(row["sanctions_revision"] or 0) if row else 0,
        "updated_at": int(time.time()),
    }


def install(dashboard) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    _INSTALLED = True
    inflight: dict[int, asyncio.Task] = {}

    async def handle_diagnostics(request: web.Request) -> web.Response:
        started = time.perf_counter()
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error

        task = inflight.get(guild_id)
        if task is None or task.done():
            task = asyncio.create_task(_diagnostic_payload(dashboard, request.app["bot"], guild))
            inflight[guild_id] = task

            def clear(done: asyncio.Task, key: int = guild_id) -> None:
                if inflight.get(key) is done:
                    inflight.pop(key, None)

            task.add_done_callback(clear)
        payload = await asyncio.shield(task)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms >= 1000:
            logger.warning("Dashboard lent : diagnostics %s en %.0f ms.", guild_id, elapsed_ms)
        response = web.json_response(payload)
        response.headers["Server-Timing"] = f"diagnostics;dur={elapsed_ms:.1f}"
        return response

    async def handle_live_stream(request: web.Request) -> web.StreamResponse | web.Response:
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error

        bot = request.app["bot"]
        user_id = int(session["user"]["id"])
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)
        last_permission_check = time.monotonic()
        try:
            while True:
                if time.monotonic() - last_permission_check >= 30:
                    member = await dashboard._administrator_member(guild, user_id)
                    if member is None:
                        payload = json.dumps({"reason": "permission_revoked"}, separators=(",", ":"))
                        await response.write(f"event: access\ndata: {payload}\n\n".encode())
                        break
                    last_permission_check = time.monotonic()
                metrics = await _live_metrics(dashboard, bot, guild)
                payload = json.dumps(metrics, separators=(",", ":"))
                await response.write(f"event: metrics\ndata: {payload}\n\n".encode())
                await asyncio.sleep(8)
        except (asyncio.CancelledError, ConnectionResetError, RuntimeError):
            pass
        except Exception:
            logger.exception("Flux live dashboard interrompu pour le serveur %s.", guild_id)
        finally:
            try:
                await response.write_eof()
            except Exception:
                logger.warning("Étape non critique ignorée dans handle_live_stream", exc_info=True)
        return response

    async def handle_live_metrics(request: web.Request) -> web.Response:
        """Instantané JSON unique des mêmes métriques que le flux SSE.

        Le dashboard interrogeait le flux ``/live/stream`` via un ``EventSource`` gardé
        ouvert en permanence : WebKit (Safari) laisse alors la barre de chargement de la
        page active indéfiniment, et le client rouvrait le flux à chaque mutation du rail
        des serveurs. Le frontend interroge désormais cet instantané par polling espacé ;
        le flux SSE reste disponible pour les clients qui l'utilisent encore.
        """
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        metrics = await _live_metrics(dashboard, request.app["bot"], guild)
        response = web.json_response(metrics)
        response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate, max-age=0"
        return response

    async def handle_modules_get(request: web.Request) -> web.Response:
        """État des modules depuis la source unique (module_settings), pour le Dashboard."""
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        from cogs import setup_v2_core as core

        items = {
            module: await core.module_state(request.app["bot"], guild.id, module)
            for module in core.MODULES
        }
        return web.json_response({"ok": True, "modules": items, "configurable": sorted(core.CONFIGURABLE_MODULES)})

    async def handle_modules_post(request: web.Request) -> web.Response:
        """Activer / désactiver / réinitialiser un module — même écriture que /setup."""
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        try:
            payload = await request.json()
        except Exception:
            return dashboard._json_error("Requête invalide.", 400)
        from cogs import setup_v2_core as core

        module = str(payload.get("module") or "").strip().lower()
        action = str(payload.get("action") or "").strip().lower()
        if module not in core.MODULES:
            return dashboard._json_error("Module inconnu.", 400)
        actor_id = int(session.get("user", {}).get("id") or 0) or None
        bot = request.app["bot"]
        if action == "enable":
            await core.set_module_enabled(bot, guild.id, module, True, actor_id=actor_id)
        elif action == "disable":
            await core.set_module_enabled(bot, guild.id, module, False, actor_id=actor_id)
        elif action == "reset":
            await core.reset_module(bot, guild.id, module)
        else:
            return dashboard._json_error("Action inconnue (enable, disable ou reset).", 400)
        return web.json_response({"ok": True, "module": module, "state": await core.module_state(bot, guild.id, module)})

    original_build_app = dashboard.build_app

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/modules", handle_modules_get)
        app.router.add_post("/api/guilds/{guild_id}/modules", handle_modules_post)
        app.router.add_get("/api/guilds/{guild_id}/diagnostics", handle_diagnostics)
        app.router.add_get("/api/guilds/{guild_id}/live/stream", handle_live_stream)
        app.router.add_get("/api/guilds/{guild_id}/live/metrics", handle_live_metrics)
        return app

    dashboard.build_app = build_app
    logger.info("Dashboard V60 : diagnostics parallélisés + flux SSE live installés.")
    return True


__all__ = ["install"]
