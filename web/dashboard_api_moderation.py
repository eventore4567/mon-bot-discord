"""Centre de modération du dashboard SentriX.

Les sanctions sont exécutées par services.moderation : même hiérarchie, même persistance
et mêmes garde-fous que les commandes Discord. Cette couche ne duplique pas le moteur.
"""
from __future__ import annotations

import time

import discord
from aiohttp import web

from services import moderation as moderation_service
from utils import helpers, log_service


_ACTION_META = {
    "warn": ("member_warn", "Avertissement", "moderate_members"),
    "mute": ("member_timeout", "Mute", "moderate_members"),
    "kick": ("member_kick", "Expulsion", "kick_members"),
    "ban": ("member_ban", "Bannissement", "ban_members"),
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

    async def _payload(request: web.Request) -> dict:
        try:
            value = await request.json()
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    async def _actor(session: dict, guild: discord.Guild) -> discord.Member | None:
        user_id = int(session["user"]["id"])
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _target(guild: discord.Guild, user_id: int) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    def _member_json(member: discord.abc.User) -> dict:
        roles = getattr(member, "roles", ())
        return {
            "id": str(member.id),
            "username": member.name,
            "display_name": getattr(member, "display_name", member.name),
            "avatar_url": str(member.display_avatar.url),
            "bot": bool(member.bot),
            "present": isinstance(member, discord.Member),
            "roles": [
                {"id": str(role.id), "name": role.name}
                for role in roles
                if not role.is_default()
            ][-8:],
        }

    async def members_get(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        raw_query = str(request.query.get("q") or "").strip()
        query = raw_query.casefold()
        if not query:
            return web.json_response({"ok": True, "members": []})
        exact_id = int(query) if query.isdigit() and len(query) <= 22 else None
        found: dict[int, discord.Member] = {}
        for member in guild.members:
            if exact_id is not None:
                if member.id != exact_id:
                    continue
            else:
                haystack = f"{member.display_name} {member.name} {member.id}".casefold()
                if query not in haystack:
                    continue
            found[member.id] = member
            if len(found) >= 25:
                break

        # Sur les gros serveurs, le cache local de membres peut être partiel. Discord
        # peut compléter une recherche par pseudo ; échec = on garde simplement le cache.
        if exact_id is not None and exact_id not in found:
            member = await _target(guild, exact_id)
            if member is not None:
                found[member.id] = member
        elif len(found) < 25 and len(raw_query) >= 2:
            try:
                queried = await guild.query_members(query=raw_query, limit=25, cache=True)
                for member in queried:
                    found.setdefault(member.id, member)
                    if len(found) >= 25:
                        break
            except (discord.HTTPException, discord.Forbidden):
                pass

        return web.json_response({
            "ok": True,
            "members": [_member_json(member) for member in list(found.values())[:25]],
        })

    async def member_get(request: web.Request):
        _session, guild, error = await _guard(request)
        if error:
            return error
        try:
            user_id = int(request.match_info["user_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Identifiant de membre invalide.", 400)
        member = await _target(guild, user_id)
        present = member is not None
        if member is None:
            try:
                member = await bot.fetch_user(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return dashboard._json_error("Utilisateur introuvable.", 404)

        db = bot.db
        warnings_row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?",
            (guild.id, member.id),
        )
        sanctions_row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND user_id=?",
            (guild.id, member.id),
        )
        recent = await db.fetchall(
            "SELECT case_number,action,reason,duration_seconds,created_at "
            "FROM sanctions WHERE guild_id=? AND user_id=? "
            "ORDER BY case_number DESC,id DESC LIMIT 8",
            (guild.id, member.id),
        )
        timed_out_until = getattr(member, "timed_out_until", None)
        currently_banned = False
        if not present:
            try:
                await guild.fetch_ban(discord.Object(id=user_id))
                currently_banned = True
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                currently_banned = False
        return web.json_response({
            "ok": True,
            "member": _member_json(member),
            "warnings": int(warnings_row["n"] if warnings_row else 0),
            "sanctions": int(sanctions_row["n"] if sanctions_row else 0),
            "timed_out_until": timed_out_until.isoformat() if timed_out_until else None,
            "currently_banned": currently_banned,
            "recent": [dict(row) for row in recent],
        })

    async def _template(action: str, guild: discord.Guild, actor: discord.Member, target: discord.Member, reason: str):
        cog = bot.get_cog("Moderation") if hasattr(bot, "get_cog") else None
        if cog is None or not hasattr(cog, "_get_sanction_dm_template"):
            return None, None
        try:
            template = await cog._get_sanction_dm_template(guild.id, action)
        except Exception:
            return cog, None
        return cog, template

    def _render_template(cog, template, *, action: str, guild, actor, target, reason, duration_seconds):
        if cog is None or template is None:
            return None
        try:
            return cog._render_sanction_dm_text(
                template,
                target=target,
                guild=guild,
                reason=reason,
                duration_seconds=duration_seconds,
                actor=actor,
                action_label=cog.DM_ACTION_LABELS.get(action, action),
            )
        except Exception:
            return None

    async def _emit_log(guild: discord.Guild, actor: discord.Member, target: discord.Member, action: str, reason: str, outcome) -> None:
        event_type, label, _permission = _ACTION_META[action]
        case = getattr(outcome, "case_number", None)
        title = f"Dossier #{case} — {label}" if case is not None else label
        embed = discord.Embed(
            title=title,
            description=f"Action appliquée depuis le dashboard SentriX.",
            colour=discord.Colour.red() if action in {"ban", "kick"} else discord.Colour.orange(),
        )
        embed.add_field(name="Membre", value=f"{target.mention}\nID: {target.id}", inline=True)
        embed.add_field(name="Modérateur", value=f"{actor.mention}\nID: {actor.id}", inline=True)
        duration = getattr(outcome, "duration_seconds", None)
        if duration:
            embed.add_field(name="Durée", value=helpers.format_duration(int(duration)), inline=True)
        embed.add_field(name="Raison", value=reason, inline=False)
        await log_service.send_log(
            bot,
            guild,
            event_type,
            embed,
            event_key=log_service.make_event_key(
                guild.id,
                event_type,
                target_id=target.id,
                executor_id=actor.id,
                discriminator=case or int(time.time()),
            ),
            identity_name=target.display_name,
            identity_id=target.id,
            identity_icon=str(target.display_avatar.url),
        )

    async def action_post(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        action = str(payload.get("action") or "").strip().lower()
        if action not in _ACTION_META:
            return dashboard._json_error("Action de modération inconnue.", 400)
        try:
            user_id = int(payload.get("user_id"))
        except (TypeError, ValueError):
            return dashboard._json_error("Choisissez un membre valide.", 400)

        reason = str(payload.get("reason") or "").strip()
        if not reason or len(reason) > 500:
            return dashboard._json_error("La raison doit contenir entre 1 et 500 caractères.", 400)

        actor = await _actor(session, guild)
        target = await _target(guild, user_id)
        if actor is None:
            return dashboard._json_error("Votre compte Discord n'est plus présent sur ce serveur.", 403)
        if target is None:
            return dashboard._json_error("Ce membre n'est plus présent sur le serveur.", 404)
        if target.bot:
            return dashboard._json_error("Le centre de modération ne sanctionne pas les bots depuis le dashboard.", 400)

        _event, _label, bot_permission = _ACTION_META[action]
        actor_permissions = actor.guild_permissions
        if guild.owner_id != actor.id and not actor_permissions.administrator and not getattr(actor_permissions, bot_permission, False):
            pretty = {
                "ban_members": "Bannir des membres",
                "kick_members": "Expulser des membres",
                "moderate_members": "Exclure temporairement des membres",
            }.get(bot_permission, bot_permission)
            return dashboard._json_error(
                f"Vous n'avez pas la permission Discord « {pretty} » requise pour cette action.",
                403,
            )
        me = guild.me
        if me is None or not getattr(me.guild_permissions, bot_permission, False):
            return dashboard._json_error(
                f"SentriX n'a pas la permission Discord requise pour cette action ({bot_permission}).",
                403,
            )

        rate_key = (request.cookies.get(dashboard.SESSION_COOKIE), guild.id, "dashboard-moderation")
        previous = request.app["write_limits"].get(rate_key, 0)
        if time.time() - previous < 1.5:
            return dashboard._json_error("Attendez un instant avant d'appliquer une autre sanction.", 429)

        cog, template = await _template(action, guild, actor, target, reason)
        try:
            if action == "ban":
                dm_text = _render_template(
                    cog, template, action=action, guild=guild, actor=actor,
                    target=target, reason=reason, duration_seconds=None,
                )
                outcome = await moderation_service.ban(
                    bot, guild=guild, actor=actor, target=target, reason=reason, dm_text=dm_text,
                )
            elif action == "kick":
                dm_text = _render_template(
                    cog, template, action=action, guild=guild, actor=actor,
                    target=target, reason=reason, duration_seconds=None,
                )
                outcome = await moderation_service.kick(
                    bot, guild=guild, actor=actor, target=target, reason=reason, dm_text=dm_text,
                )
            elif action == "mute":
                duration = str(payload.get("duration") or "10m").strip()
                parsed = helpers.parse_duration(duration)
                if parsed is None:
                    return dashboard._json_error("Durée invalide. Exemples : 10m, 1h, 1j.", 400)

                def render_dm(seconds: int):
                    return _render_template(
                        cog, template, action=action, guild=guild, actor=actor,
                        target=target, reason=reason, duration_seconds=seconds,
                    )

                outcome = await moderation_service.mute(
                    bot, guild=guild, actor=actor, target=target, reason=reason,
                    duree=duration, render_dm_text=render_dm,
                )
            else:
                dm_text = _render_template(
                    cog, template, action=action, guild=guild, actor=actor,
                    target=target, reason=reason, duration_seconds=None,
                )
                conf = await bot.db.get_guild_config(guild.id)
                warn_role = guild.get_role(conf["warn_role"]) if conf and conf["warn_role"] else None
                threshold = int(conf["warn_ban_threshold"] or 0) if conf else 0
                ban_cog, ban_template = await _template("ban", guild, actor, target, reason)

                def render_ban_dm():
                    return _render_template(
                        ban_cog, ban_template, action="ban", guild=guild, actor=actor,
                        target=target, reason=f"Seuil de {threshold} avertissements atteint",
                        duration_seconds=None,
                    )

                outcome = await moderation_service.warn(
                    bot, guild=guild, actor=actor, target=target, reason=reason,
                    dm_text=dm_text, warn_role=warn_role, ban_threshold=threshold,
                    render_ban_dm_text=render_ban_dm,
                )
        except discord.Forbidden:
            return dashboard._json_error(
                "Discord a refusé la sanction : vérifiez la hiérarchie des rôles et les permissions de SentriX.",
                403,
            )
        except discord.HTTPException:
            return dashboard._json_error("Discord n'a pas pu appliquer cette sanction. Réessayez.", 502)

        if not getattr(outcome, "executed", False):
            message = (
                getattr(outcome, "hierarchy_error", None)
                or getattr(outcome, "rejection_reason", None)
                or getattr(outcome, "validation_error", None)
                or "La sanction n'a pas été appliquée."
            )
            return dashboard._json_error(str(message), 409)

        request.app["write_limits"][rate_key] = time.time()
        try:
            await _emit_log(guild, actor, target, action, reason, outcome)
        except Exception:
            # La sanction réelle ne doit jamais être transformée en échec si le salon
            # de logs est absent ou temporairement indisponible.
            pass

        response = {
            "ok": True,
            "message": f"{_ACTION_META[action][1]} appliqué à {target.display_name}.",
            "case_number": getattr(outcome, "case_number", None),
            "dm_sent": bool(getattr(outcome, "dm_sent", False)),
        }
        if action == "warn":
            response["total_warnings"] = getattr(outcome, "total_warnings", None)
            response["auto_ban_triggered"] = bool(getattr(outcome, "auto_ban_triggered", False))
            response["auto_ban_executed"] = bool(getattr(outcome, "auto_ban_executed", False))
        if action == "mute":
            response["duration_seconds"] = getattr(outcome, "duration_seconds", None)
        return web.json_response(response)

    app.router.add_get("/api/guilds/{guild_id}/moderation/members", members_get)
    app.router.add_get("/api/guilds/{guild_id}/moderation/members/{user_id}", member_get)
    app.router.add_post("/api/guilds/{guild_id}/moderation/actions", action_post)


__all__ = ["register"]
