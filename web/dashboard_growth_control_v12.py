"""SentriX Growth Control V12 — routes API des pages Croissance / Opérations.

Ce module installe les routes ``/api/guilds/{id}/growth/*`` et ``/automation/reactions``
(statistiques, invitations, webhooks, réactions automatiques) et le listener associé.

Historique : V12 injectait aussi ses propres boutons dans la navigation et rendait ces pages
via un routeur client (``ensureNav``, ``render``, MutationObserver sur ``document``, timer de
900 ms). Depuis V15 (``dashboard_live_response_v15``), ces 9 onglets font partie du NAV et du
``render()`` natifs du frontend V2. Les deux routeurs coexistaient : navigation « Statistiques »
en double, rendus concurrents dans ``#content`` (le rendu V15 réussi écrasé par un skeleton
V12), requêtes dupliquées, skeleton permanent si une requête V12 traînait. Mesuré en
navigateur réel sur le commit de production. Le routeur client est retiré ; les routes API,
dont V15 dépend, sont conservées à l'identique.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard-growth-control-v12")

CSS_MARKER = "sentrix-growth-v12-css"
JS_MARKER = "sentrix-growth-v12-js"

CSS = r'''
<style id="sentrix-growth-v12-css">
/* Growth Control V12 : les pages sont rendues nativement par V15 (dashboard_live_response_v15),
   qui n'emploie aucune classe sx12-*. Seul le marqueur exigé par sentrix_dashboard_finalizer_v7 subsiste. */
</style>
'''

JS = r'''
<script id="sentrix-growth-v12-js">
(() => {
"use strict";
if(window.__sentrixGrowthV12)return;window.__sentrixGrowthV12=true;
// Les pages Statistiques, Invitations, Réactions automatiques, Automatisations, Activité
// staff, Historique & audit, Sauvegardes, Maintenance et Webhooks sont rendues nativement
// par le routeur V2 depuis dashboard_live_response_v15, à partir des routes API que ce
// module installe côté serveur. L'ancien routeur client de V12 (boutons injectés dans la
// navigation, observation de tout le document, timers) rendait ces mêmes onglets en
// concurrence avec V15 : voir la docstring du module. Seul le marqueur d'API subsiste,
// exigé par sentrix_dashboard_finalizer_v7.
window.__sentrixGrowthV12Api={retired:true,renderer:"v15-native"};
})();
</script>
'''


def _row_dict(row: Any) -> dict:
    if not row:
        return {}
    try:
        return dict(row)
    except Exception:
        return {}


async def _ensure_tables(db) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_auto_reaction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            emojis_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            mode TEXT NOT NULL DEFAULT 'all',
            keyword TEXT NOT NULL DEFAULT '',
            ignore_bots INTEGER NOT NULL DEFAULT 1,
            created_by BIGINT,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL
        )
        """
    )
    try:
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sentrix_auto_reaction_guild_channel ON sentrix_dashboard_auto_reaction(guild_id, channel_id)"
        )
    except Exception:
        logger.warning("Étape non critique ignorée dans _ensure_tables", exc_info=True)


def _emoji_valid(token: str) -> bool:
    value = str(token or "").strip()
    if not value or len(value) > 100:
        return False
    if re.fullmatch(r"<a?:[A-Za-z0-9_]{2,32}:\d{5,25}>", value):
        return True
    # Unicode emoji/graphemes are deliberately permissive; Discord is the final validator.
    return not value.startswith("<") and not value.endswith(">")


async def _reaction_rows(db, guild: discord.Guild) -> list[dict]:
    await _ensure_tables(db)
    rows = await db.fetchall(
        "SELECT id,guild_id,channel_id,emojis_json,enabled,mode,keyword,ignore_bots,created_by,created_at,updated_at "
        "FROM sentrix_dashboard_auto_reaction WHERE guild_id = ? ORDER BY updated_at DESC, id DESC LIMIT 100",
        (guild.id,),
    )
    out: list[dict] = []
    for row in rows:
        item = _row_dict(row)
        try:
            emojis = json.loads(item.get("emojis_json") or "[]")
        except Exception:
            emojis = []
        channel = guild.get_channel(int(item.get("channel_id") or 0))
        out.append(
            {
                "id": int(item.get("id") or 0),
                "channel_id": str(item.get("channel_id") or ""),
                "channel_name": getattr(channel, "name", None),
                "emojis": [str(x) for x in emojis if str(x).strip()][:8],
                "enabled": bool(item.get("enabled")),
                "mode": item.get("mode") or "all",
                "keyword": item.get("keyword") or "",
                "ignore_bots": bool(item.get("ignore_bots")),
                "created_by": str(item.get("created_by") or ""),
                "created_at": int(item.get("created_at") or 0),
                "updated_at": int(item.get("updated_at") or 0),
            }
        )
    return out


def _install_listener(bot) -> None:
    if getattr(bot, "_sentrix_auto_reaction_v12", False):
        return
    bot._sentrix_auto_reaction_v12 = True
    cache: dict[tuple[int, int], tuple[float, list[dict]]] = {}

    async def rules(guild_id: int, channel_id: int) -> list[dict]:
        key = (guild_id, channel_id)
        now = time.monotonic()
        cached = cache.get(key)
        if cached and now - cached[0] < 2.5:
            return cached[1]
        try:
            await _ensure_tables(bot.db)
            rows = await bot.db.fetchall(
                "SELECT id,emojis_json,mode,keyword,ignore_bots FROM sentrix_dashboard_auto_reaction "
                "WHERE guild_id = ? AND channel_id = ? AND enabled = 1 ORDER BY id ASC LIMIT 20",
                (guild_id, channel_id),
            )
        except Exception:
            logger.exception("Unable to load automatic reaction rules.")
            return []
        values = [_row_dict(row) for row in rows]
        cache[key] = (now, values)
        return values

    async def on_message(message: discord.Message) -> None:
        if message.guild is None or message.author is None:
            return
        for rule in await rules(message.guild.id, message.channel.id):
            if bool(rule.get("ignore_bots")) and getattr(message.author, "bot", False):
                continue
            mode = str(rule.get("mode") or "all")
            keyword = str(rule.get("keyword") or "").strip().casefold()
            if mode == "keyword" and (not keyword or keyword not in str(message.content or "").casefold()):
                continue
            try:
                emojis = json.loads(rule.get("emojis_json") or "[]")
            except Exception:
                emojis = []
            for raw in emojis[:8]:
                token = str(raw).strip()
                if not token:
                    continue
                try:
                    emoji = discord.PartialEmoji.from_str(token) if token.startswith("<") else token
                    await message.add_reaction(emoji)
                except (discord.Forbidden, discord.NotFound):
                    break
                except discord.HTTPException:
                    continue
                except Exception:
                    logger.debug("Automatic reaction failed for guild=%s channel=%s", message.guild.id, message.channel.id, exc_info=True)

    bot.add_listener(on_message, "on_message")
    logger.info("Automatic reactions V12 listener installed.")


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False
    if f'id="{CSS_MARKER}"' not in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if f'id="{JS_MARKER}"' not in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html

    original_build = dashboard.build_app
    if not getattr(original_build, "_sentrix_growth_v12_routes", False):
        def build_app_with_growth(bot):
            app = original_build(bot)
            from web import dashboard_ops_suite as ops

            async def require(request: web.Request):
                return await ops._require_manageable(dashboard, request)

            async def stats(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                try:
                    staff = await ops._staff_activity(bot.db, guild_id)
                except Exception:
                    staff = []
                text_channels = len(getattr(guild, "text_channels", []) or [])
                voice_channels = len(getattr(guild, "voice_channels", []) or [])
                categories = len(getattr(guild, "categories", []) or [])
                return web.json_response(
                    {
                        "ok": True,
                        "members": int(getattr(guild, "member_count", 0) or 0),
                        "channels": len(getattr(guild, "channels", []) or []),
                        "text_channels": text_channels,
                        "voice_channels": voice_channels,
                        "categories": categories,
                        "roles": max(0, len(getattr(guild, "roles", []) or []) - 1),
                        "staff_actions_24h": sum(int(x.get("actions") or 0) for x in staff),
                        "discord_ready": bool(bot.is_ready()),
                        "latency_ms": round(bot.latency * 1000) if bot.is_ready() else None,
                    }
                )

            async def invitations(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                items = []
                try:
                    invites = await guild.invites()
                except (discord.Forbidden, discord.HTTPException):
                    invites = []
                for invite in invites[:100]:
                    items.append(
                        {
                            "code": invite.code,
                            "uses": int(invite.uses or 0),
                            "max_uses": int(invite.max_uses or 0),
                            "max_age": int(invite.max_age or 0),
                            "temporary": bool(invite.temporary),
                            "channel_id": str(getattr(invite.channel, "id", "") or ""),
                            "channel_name": getattr(invite.channel, "name", None),
                            "inviter_id": str(getattr(invite.inviter, "id", "") or ""),
                            "inviter_name": str(invite.inviter) if invite.inviter else None,
                        }
                    )
                return web.json_response({"ok": True, "items": items, "total_uses": sum(x["uses"] for x in items)})

            async def webhooks(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                items = []
                try:
                    hooks = await guild.webhooks()
                except (discord.Forbidden, discord.HTTPException):
                    hooks = []
                for hook in hooks[:100]:
                    channel = guild.get_channel(int(hook.channel_id or 0)) if hook.channel_id else None
                    items.append(
                        {
                            "id": str(hook.id),
                            "name": hook.name,
                            "channel_id": str(hook.channel_id or ""),
                            "channel_name": getattr(channel, "name", None),
                            "type": str(getattr(hook.type, "name", hook.type)),
                        }
                    )
                return web.json_response({"ok": True, "items": items})

            async def reactions_get(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                return web.json_response({"ok": True, "items": await _reaction_rows(bot.db, guild)})

            async def reactions_post(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                csrf_error = ops._csrf(dashboard, request, session)
                if csrf_error:
                    return csrf_error
                try:
                    payload = await request.json()
                except Exception:
                    return dashboard._json_error("Formulaire invalide.", 400)
                action = str(payload.get("action") or "create").lower()
                await _ensure_tables(bot.db)
                user_id = int(session["user"]["id"])
                now = int(time.time())

                if action == "create":
                    try:
                        channel_id = int(payload.get("channel_id") or 0)
                    except (TypeError, ValueError):
                        channel_id = 0
                    channel = guild.get_channel(channel_id)
                    if channel is None or not hasattr(channel, "send"):
                        return dashboard._json_error("Salon texte introuvable.", 400)
                    raw_emojis = payload.get("emojis") or []
                    if not isinstance(raw_emojis, list):
                        return dashboard._json_error("Liste d'emojis invalide.", 400)
                    emojis: list[str] = []
                    for value in raw_emojis:
                        token = str(value or "").strip()
                        if token and token not in emojis:
                            if not _emoji_valid(token):
                                return dashboard._json_error(f"Emoji invalide : {token[:30]}", 400)
                            emojis.append(token)
                    emojis = emojis[:8]
                    if not emojis:
                        return dashboard._json_error("Choisis au moins un emoji.", 400)
                    mode = str(payload.get("mode") or "all").lower()
                    if mode not in {"all", "keyword"}:
                        return dashboard._json_error("Mode de réaction invalide.", 400)
                    keyword = str(payload.get("keyword") or "").strip()[:80]
                    if mode == "keyword" and not keyword:
                        return dashboard._json_error("Indique le mot-clé à détecter.", 400)
                    ignore_bots = 1 if payload.get("ignore_bots", True) else 0
                    await bot.db.execute(
                        "INSERT INTO sentrix_dashboard_auto_reaction "
                        "(guild_id,channel_id,emojis_json,enabled,mode,keyword,ignore_bots,created_by,created_at,updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (guild_id, channel_id, json.dumps(emojis, ensure_ascii=False), 1, mode, keyword, ignore_bots, user_id, now, now),
                    )
                    return web.json_response({"ok": True, "message": "Réaction automatique créée."})

                try:
                    rule_id = int(payload.get("id") or 0)
                except (TypeError, ValueError):
                    rule_id = 0
                row = await bot.db.fetchone(
                    "SELECT id FROM sentrix_dashboard_auto_reaction WHERE id = ? AND guild_id = ?",
                    (rule_id, guild_id),
                )
                if not row:
                    return dashboard._json_error("Règle introuvable.", 404)
                if action == "delete":
                    await bot.db.execute("DELETE FROM sentrix_dashboard_auto_reaction WHERE id = ? AND guild_id = ?", (rule_id, guild_id))
                    return web.json_response({"ok": True})
                if action == "toggle":
                    enabled = 1 if payload.get("enabled") else 0
                    await bot.db.execute(
                        "UPDATE sentrix_dashboard_auto_reaction SET enabled = ?, updated_at = ? WHERE id = ? AND guild_id = ?",
                        (enabled, now, rule_id, guild_id),
                    )
                    return web.json_response({"ok": True, "enabled": bool(enabled)})
                return dashboard._json_error("Action inconnue.", 400)

            app.router.add_get("/api/guilds/{guild_id}/growth/stats", stats)
            app.router.add_get("/api/guilds/{guild_id}/growth/invitations", invitations)
            app.router.add_get("/api/guilds/{guild_id}/growth/webhooks", webhooks)
            app.router.add_get("/api/guilds/{guild_id}/automation/reactions", reactions_get)
            app.router.add_post("/api/guilds/{guild_id}/automation/reactions", reactions_post)
            _install_listener(bot)
            return app

        build_app_with_growth._sentrix_growth_v12_routes = True
        dashboard.build_app = build_app_with_growth

    ok = CSS_MARKER in dashboard.INDEX_HTML and JS_MARKER in dashboard.INDEX_HTML
    logger.info("Dashboard Growth Control V12 installed=%s: stats/invites/auto-reactions/ops/audit/backups/maintenance/webhooks.", ok)
    return ok


__all__ = ["install", "CSS_MARKER", "JS_MARKER"]
