"""Diagnostics réels pour le dashboard SentriX V60 MAX.

Expose un état synthétique calculé depuis Discord + la base, sans recopier la logique de
configuration dans le navigateur. Les états sont volontairement textuels : ACTIF, INACTIF,
NON CONFIGURÉ ou ERREUR DE CONFIGURATION. Une ressource existante mais inutilisable par le
bot (permissions de salon ou hiérarchie de rôle) est également considérée en erreur.
"""
from __future__ import annotations

import logging

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


def install(dashboard) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    _INSTALLED = True

    async def handle_diagnostics(request: web.Request) -> web.Response:
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de serveur invalide.", 400)

        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error

        db = request.app["bot"].db
        conf_row = await db.get_guild_config(guild_id)
        conf = dict(conf_row) if conf_row else {}
        automod_row = await db.get_automod(guild_id)
        automod = dict(automod_row) if automod_row else {}
        ai_row = await db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,))
        ai = dict(ai_row) if ai_row else {}
        social_rows = await db.fetchall(
            "SELECT discord_channel_id, role_id, enabled FROM social_notifications WHERE guild_id = ?",
            (guild_id,),
        )

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
        # Ces destinations doivent pouvoir recevoir un message du bot. AFK peut être vocal.
        message_channel_fields = channel_fields - {"afk_channel"}
        role_fields = {
            "mod_role", "admin_role", "mute_role", "verification_role", "verify_role",
            "autorole", "warn_role", "member_role", "booster_role",
        }
        # Ces rôles peuvent être attribués/retirés par SentriX et doivent donc être sous son rôle.
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

        modules: dict[str, dict] = {}
        modules["welcome"] = channel_module(
            "welcome_channel", "Le message de bienvenue a un salon valide.", "Aucun salon de bienvenue n'est choisi."
        )
        modules["levels"] = channel_module(
            "level_channel", "Les annonces de niveau ont un salon valide.", "Aucun salon de niveaux n'est choisi."
        )
        modules["suggestions"] = channel_module(
            "suggest_channel", "Les suggestions ont un salon valide.", "Aucun salon de suggestions n'est choisi."
        )
        modules["reports"] = channel_module(
            "report_channel", "Les signalements ont un salon valide.", "Aucun salon de signalements n'est choisi."
        )

        log_fields = [
            "log_channel", "log_messages", "log_members", "log_voice", "log_roles",
            "log_server", "log_automod", "log_moderation",
        ]
        configured_logs = [field for field in log_fields if _optional_id(conf.get(field)) is not None]
        if any(field in invalid_by_field for field in configured_logs):
            modules["logs"] = _status("error", "Au moins un salon de logs est supprimé ou inutilisable par SentriX.", configured=True)
        elif configured_logs:
            modules["logs"] = _status("active", f"{len(configured_logs)} type(s) de logs ont un salon valide.", configured=True)
        else:
            modules["logs"] = _status("missing", "Aucun salon de logs n'est configuré.")

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

        automod_values = [bool(automod.get(name)) for name in dashboard.AUTOMOD_FIELDS]
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

        total = len(modules)
        active = sum(1 for item in modules.values() if item["code"] == "active")
        valid_inactive = sum(1 for item in modules.values() if item["code"] == "inactive")
        errors = sum(1 for item in modules.values() if item["code"] == "error")
        score = round(((active + valid_inactive * 0.5) / total) * 100) if total else 0

        return web.json_response({
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
        })

    original_build_app = dashboard.build_app

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/diagnostics", handle_diagnostics)
        return app

    dashboard.build_app = build_app
    logger.info("Dashboard V60 : API diagnostics installée avec validation des permissions et de la hiérarchie.")
    return True


__all__ = ["install"]
