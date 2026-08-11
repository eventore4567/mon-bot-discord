"""Dashboard Platform V4 : les 16 outils d'exploitation regroupés dans un seul centre."""
from __future__ import annotations

import html
import json
import logging

import discord
from aiohttp import web

from utils.instance_identity import brand_label

logger = logging.getLogger("bot.dashboard.platform-v4")
_INSTALLED = False


def _service(request: web.Request):
    bot = request.app.get("bot")
    getter = getattr(bot, "get_cog", None)
    return getter("PlatformV4") if callable(getter) else None


async def _payload(request: web.Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:
        raise ValueError("Requête invalide.") from exc
    if not isinstance(data, dict):
        raise ValueError("Requête invalide.")
    return data


async def _admin_ctx(dashboard, request: web.Request, *, write: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, ValueError):
        return None, None, None, dashboard._json_error("Serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return None, None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, csrf_error
    service = _service(request)
    if service is None:
        return None, None, None, dashboard._json_error("Platform V4 démarre. Réessaie dans quelques secondes.", 503)
    return session, guild, service, None


async def _member_ctx(dashboard, request: web.Request, guild_id: int, *, write: bool = False):
    session, error = dashboard._require_session(request)
    if error or not session:
        return None, None, None, None, error
    bot = request.app.get("bot")
    get_guild = getattr(bot, "get_guild", None)
    guild = get_guild(guild_id) if callable(get_guild) else None
    if guild is None:
        return None, None, None, None, dashboard._json_error("Serveur introuvable.", 404)
    user_id = int(session["user"]["id"])
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            member = None
    if member is None:
        return None, None, None, None, dashboard._json_error("Tu dois être membre de ce serveur.", 403)
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, None, csrf_error
    service = _service(request)
    if service is None:
        return None, None, None, None, dashboard._json_error("Platform V4 démarre.", 503)
    return session, guild, member, service, None


def _json_rows(rows):
    return [dict(r) for r in rows]


async def handle_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login?next=/platform-v4")
    return web.Response(text=PLATFORM_HTML, content_type="text/html", headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


async def handle_privacy_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound(f"/login?next={request.path}")
    return web.Response(text=PRIVACY_HTML, content_type="text/html", headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


async def api_options(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    settings = await service.get_settings(guild.id)
    return web.json_response({
        "ok": True,
        "brand": brand_label(),
        "settings": settings,
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default() and not r.managed],
        "prefix": str((await service.bot.db.get_guild_config(guild.id))["prefix"] or "+"),
    })


async def api_settings(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        settings = await service.update_settings(guild, int(session["user"]["id"]), await _payload(request))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "settings": settings})


async def api_live(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, "stats": await service.live_stats(guild)})


async def api_health(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, "health": await service.health(guild)})


async def api_announcements_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, "items": await service.list_announcements(guild.id)})


async def api_announcements_post(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        item = await service.save_announcement(guild, int(session["user"]["id"]), await _payload(request))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "item": item})


async def api_announcement_cancel(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        await service.cancel_announcement(guild.id, int(session["user"]["id"]), int(request.match_info["item_id"]))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True})


async def api_commands_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, "items": await service.list_custom_commands(guild.id)})


async def api_commands_post(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        item = await service.save_custom_command(guild, int(session["user"]["id"]), await _payload(request))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "item": item})


async def api_command_delete(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        await service.delete_custom_command(guild.id, int(session["user"]["id"]), int(request.match_info["item_id"]))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True})


async def api_role_menu(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        item = await service.create_role_menu(guild, int(session["user"]["id"]), await _payload(request))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    except (discord.Forbidden, discord.HTTPException):
        return dashboard._json_error("Le bot n'a pas la permission de publier ou gérer un rôle.", 403)
    return web.json_response({"ok": True, "item": item})


async def api_economy(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, **(await service.economy_history(guild.id))})


async def api_market_get(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    _session, guild, member, service, error = await _member_ctx(dashboard, request, guild_id)
    if error:
        return error
    inv = _json_rows(await service.bot.db.fetchall("SELECT item_name,quantity FROM inventory WHERE guild_id=? AND user_id=? ORDER BY item_name", (guild.id, member.id)))
    trades = _json_rows(await service.bot.db.fetchall("SELECT * FROM platform_trade_offers WHERE guild_id=? AND (creator_id=? OR target_id=?) AND status='pending' ORDER BY id DESC", (guild.id, member.id, member.id)))
    catalog = _json_rows(await service.bot.db.fetchall("SELECT * FROM platform_item_catalog WHERE guild_id=? AND enabled=1 ORDER BY item_name", (guild.id,)))
    return web.json_response({"ok": True, "items": await service.list_market(guild.id), "inventory": inv, "trades": trades, "catalog": catalog, "achievements": await service.economy_achievements(guild.id, member.id), "user_id": str(member.id)})


async def api_market_create(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    _session, _guild, member, service, error = await _member_ctx(dashboard, request, guild_id, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        item = await service.create_listing(guild_id, member.id, str(data.get("item_name") or ""), int(data.get("quantity") or 1), int(data.get("unit_price") or 0))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "item": item})


async def api_market_buy(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    _session, _guild, member, service, error = await _member_ctx(dashboard, request, guild_id, write=True)
    if error:
        return error
    try:
        result = await service.buy_listing(guild_id, member.id, int(request.match_info["listing_id"]))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


async def api_market_cancel(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    _session, _guild, member, service, error = await _member_ctx(dashboard, request, guild_id, write=True)
    if error:
        return error
    try:
        await service.cancel_listing(guild_id, member.id, int(request.match_info["listing_id"]))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True})


async def api_trade_create(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    _session, guild, member, service, error = await _member_ctx(dashboard, request, guild_id, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        target_id = int(data.get("target_id") or 0)
        target = guild.get_member(target_id)
        if target is None or target.bot:
            raise ValueError("Membre cible invalide.")
        item = await service.create_trade(guild_id, member.id, target_id, str(data.get("offer_item") or ""), int(data.get("offer_quantity") or 1), str(data.get("want_item") or ""), int(data.get("want_quantity") or 0), int(data.get("want_money") or 0))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "item": item})


async def api_trade_accept(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    _session, _guild, member, service, error = await _member_ctx(dashboard, request, guild_id, write=True)
    if error:
        return error
    try:
        result = await service.accept_trade(guild_id, member.id, int(request.match_info["trade_id"]))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


async def api_catalog(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        item = await service.configure_consumable(guild, int(session["user"]["id"]), await _payload(request))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "item": item})


async def api_use_item(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    _session, guild, member, service, error = await _member_ctx(dashboard, request, guild_id, write=True)
    if error:
        return error
    try:
        result = await service.use_item(guild, member, str((await _payload(request)).get("item_name") or ""))
    except (TypeError, ValueError, discord.HTTPException) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


async def api_events_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    rows = await service.bot.db.fetchall("SELECT e.*,COUNT(p.user_id) participants FROM events e LEFT JOIN event_participants p ON p.event_id=e.id WHERE e.guild_id=? GROUP BY e.id ORDER BY e.start_at DESC LIMIT 100", (guild.id,))
    return web.json_response({"ok": True, "items": _json_rows(rows)})


async def api_events_post(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        item = await service.create_event(guild, int(session["user"]["id"]), await _payload(request))
    except (TypeError, ValueError, discord.HTTPException) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "item": item})


async def api_giveaways_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    rows = await service.bot.db.fetchall(
        "SELECT g.*,r.min_account_age_days,r.min_member_age_days,(SELECT COUNT(*) FROM giveaway_entries e WHERE e.giveaway_id=g.id) entries FROM giveaways g LEFT JOIN platform_giveaway_rules r ON r.giveaway_id=g.id WHERE g.guild_id=? ORDER BY g.id DESC LIMIT 100",
        (guild.id,),
    )
    return web.json_response({"ok": True, "items": _json_rows(rows)})


async def api_giveaways_post(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        item = await service.create_giveaway(guild, int(session["user"]["id"]), await _payload(request))
    except (TypeError, ValueError, discord.HTTPException) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "item": item})


async def api_quick_setup(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        result = await service.quick_setup(guild, int(session["user"]["id"]), str((await _payload(request)).get("profile") or "community"))
    except (TypeError, ValueError, discord.HTTPException) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


async def api_backups_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, "items": await service.list_backups(guild.id)})


async def api_backups_post(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        result = await service.create_backup(guild, int(session["user"]["id"]), str((await _payload(request)).get("label") or ""))
    except (TypeError, ValueError, discord.HTTPException) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


async def api_backup_restore(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        if str(data.get("confirm") or "") != "RESTORE":
            raise ValueError("Écris RESTORE pour confirmer la restauration non destructive.")
        result = await service.restore_backup(guild, int(session["user"]["id"]), int(request.match_info["backup_id"]))
    except (TypeError, ValueError, discord.HTTPException) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


async def api_staff(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, "items": await service.staff_stats(guild)})


async def api_audit_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    legacy = _json_rows(await service.bot.db.fetchall("SELECT * FROM setup_history WHERE guild_id=? ORDER BY id DESC LIMIT 100", (guild.id,)))
    return web.json_response({"ok": True, "items": await service.list_audit(guild.id), "setup_history": legacy})


async def api_audit_rollback(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        result = await service.rollback(guild, int(session["user"]["id"]), int(request.match_info["audit_id"]))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


async def api_privacy_get(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    session, guild, member, service, error = await _member_ctx(dashboard, request, guild_id)
    if error:
        return error
    data = await service.privacy_export(guild.id, member.id)
    return web.json_response({"ok": True, "brand": brand_label(), "guild_name": guild.name, "user_id": str(member.id), "data": data})


async def api_privacy_delete(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    _session, guild, member, service, error = await _member_ctx(dashboard, request, guild_id, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        if str(data.get("confirm") or "") != "DELETE":
            raise ValueError("Écris DELETE pour confirmer.")
        result = await service.privacy_delete(guild.id, member.id)
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


PLATFORM_HTML = r'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Platform V4</title><style>
:root{--bg:#080a10;--panel:#10131b;--panel2:#151925;--line:#252b3a;--text:#f4f6fb;--muted:#949caf;--accent:#7d8cff;--danger:#ff7287;--ok:#55d89b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% -10%,#20284c 0,transparent 32%),var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}.shell{max-width:1440px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;gap:14px;align-items:center;margin-bottom:16px}.brand{font-size:25px;font-weight:900}.brand small{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.1em}.toolbar{display:flex;gap:8px;flex-wrap:wrap}.btn,.back{border:1px solid var(--line);background:#171b27;color:var(--text);border-radius:11px;padding:10px 13px;font-weight:760;text-decoration:none;cursor:pointer;transition:transform .15s ease,border-color .15s ease}.btn:hover,.back:hover{transform:scale(1.025);border-color:var(--accent)}.btn.primary{background:var(--accent);border-color:var(--accent)}.btn.danger{background:#251216;border-color:#6b2b36}.layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:15px}.side,.card{border:1px solid var(--line);background:rgba(16,19,27,.95);border-radius:17px}.side{padding:10px;height:max-content;position:sticky;top:12px}.nav{display:block;width:100%;border:0;background:transparent;color:var(--muted);padding:10px 11px;text-align:left;border-radius:9px;font-weight:740;cursor:pointer}.nav:hover,.nav.active{background:var(--panel2);color:var(--text)}.main{min-width:0;display:grid;gap:13px}.card{padding:18px;min-width:0}.card h2{margin:0 0 5px;font-size:18px}.card h3{margin:18px 0 8px;font-size:14px}.card p{margin:0 0 14px;color:var(--muted);line-height:1.5}.notice{border:1px solid #2a385d;background:#0d1422;padding:10px 12px;border-radius:11px;margin-bottom:14px;color:#d4dcff}.hidden{display:none!important}.row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.row3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.grid4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.metric,.item{border:1px solid var(--line);background:#0d1017;border-radius:12px;padding:12px;min-width:0}.metric b{display:block;font-size:20px}.metric span,.meta{color:var(--muted);font-size:11px}.field{display:grid;gap:6px;margin-bottom:10px}label{color:var(--muted);font-size:10px;font-weight:800;text-transform:uppercase}input,select,textarea{width:100%;min-width:0;border:1px solid var(--line);background:#0a0d14;color:var(--text);border-radius:10px;padding:10px 11px}textarea{min-height:90px;resize:vertical}.list{display:grid;gap:8px}.chips{display:flex;gap:6px;flex-wrap:wrap}.chip{border:1px solid var(--line);border-radius:999px;padding:4px 7px;color:var(--muted);font-size:10px}.ok{color:var(--ok)}.bad{color:var(--danger)}.scroll{overflow:auto;max-width:100%}table{width:100%;border-collapse:collapse;font-size:12px;min-width:700px}th,td{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--muted);font-size:10px;text-transform:uppercase}.danger-zone{border-color:#5b2931!important;background:#170e12!important}.section-title{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.badge{border:1px solid var(--line);border-radius:999px;padding:5px 8px;font-size:10px;color:var(--muted)}@media(max-width:980px){.shell{padding:14px}.layout{grid-template-columns:1fr}.side{position:static;display:flex;overflow:auto;gap:3px}.nav{white-space:nowrap;width:auto}.grid4{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.row,.row3,.grid4{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}.shell{padding:10px}.card{padding:14px}.toolbar{width:100%}.toolbar .btn,.toolbar .back{flex:1;text-align:center}.side{margin:0 -2px}.nav{padding:9px}.metric b{font-size:18px}table{min-width:560px}}
</style></head><body><div class="shell"><div class="top"><div class="brand" id="brand">Platform V4<small>Centre d'exploitation complet</small></div><div class="toolbar"><a class="back" href="/app">Dashboard</a><a class="back" href="/community">Communauté</a><a class="back" href="/engagement">Engagement V3</a></div></div><div id="notice" class="notice">Chargement...</div><div class="layout"><aside class="side">
<button class="nav active" data-tab="overview">Vue en direct</button><button class="nav" data-tab="setup">Configuration 1 clic</button><button class="nav" data-tab="health">Santé & sauvegardes</button><button class="nav" data-tab="economy">Économie & anti-abus</button><button class="nav" data-tab="market">Marketplace & échanges</button><button class="nav" data-tab="roles">Menus de rôles</button><button class="nav" data-tab="announcements">Annonces programmées</button><button class="nav" data-tab="custom">Commandes personnalisées</button><button class="nav" data-tab="events">Événements</button><button class="nav" data-tab="giveaways">Giveaways V2</button><button class="nav" data-tab="staff">Stats staff</button><button class="nav" data-tab="design">Personnalisation</button><button class="nav" data-tab="audit">Audit & rollback</button><button class="nav" data-tab="privacy">Confidentialité</button>
</aside><main class="main">
<section id="tab-overview" class="card"><div class="section-title"><div><h2>Dashboard en direct</h2><p>Actualisation automatique toutes les 5 secondes, sans F5.</p></div><span class="badge">LIVE</span></div><div class="field"><label>Serveur</label><select id="guild"></select></div><div class="grid4"><div class="metric"><b id="liveMembers">—</b><span>Membres</span></div><div class="metric"><b id="liveVoice">—</b><span>En vocal</span></div><div class="metric"><b id="liveMessages">—</b><span>Messages suivis</span></div><div class="metric"><b id="liveLatency">—</b><span>Latence</span></div><div class="metric"><b id="liveGiveaways">—</b><span>Giveaways</span></div><div class="metric"><b id="liveEvents">—</b><span>Événements</span></div></div><div class="chips" style="margin-top:12px"><span class="chip">Confidentialité</span><span class="chip">Économie V2</span><span class="chip">Rôles</span><span class="chip">Planification</span><span class="chip">Backups</span><span class="chip">Audit</span><span class="chip">Mobile</span></div></section>
<section id="tab-setup" class="card hidden"><h2>Assistant de configuration 1 clic</h2><p>Crée uniquement les salons essentiels manquants, relie les réglages principaux et active un profil de sécurité recommandé. L'opération est idempotente.</p><div class="field"><label>Profil</label><select id="setupProfile"><option value="community">Communauté</option><option value="gaming">Gaming</option><option value="support">Support</option><option value="creator">Créateur</option></select></div><button class="btn primary" id="runSetup">Configurer automatiquement</button><pre id="setupResult" class="item">Aucune exécution.</pre></section>
<section id="tab-health" class="card hidden"><h2>Centre santé du bot</h2><p>Discord, SQLite, services externes et état opérationnel.</p><div id="healthGrid" class="grid4"></div><h3>Sauvegarde / restauration serveur</h3><div class="row"><div class="field"><label>Nom de sauvegarde</label><input id="backupLabel" placeholder="Avant grosse modification"></div><div style="display:flex;align-items:end"><button class="btn primary" id="createBackup">Créer une sauvegarde</button></div></div><div id="backups" class="list"></div></section>
<section id="tab-economy" class="card hidden"><h2>Historique économie complet</h2><p>Chaque gain, perte, transfert, drop et ajustement enregistré peut être contrôlé. Les alertes sont heuristiques et ne sanctionnent personne automatiquement.</p><div id="ecoFlags" class="list"></div><div class="scroll"><table><thead><tr><th>ID</th><th>Type</th><th>De</th><th>Vers</th><th>Montant</th><th>Raison</th><th>Date</th></tr></thead><tbody id="ecoRows"></tbody></table></div></section>
<section id="tab-market" class="card hidden"><h2>Économie V2 — marketplace, échanges et objets utilisables</h2><p>Les objets mis en vente ou proposés en échange sont réservés immédiatement pour empêcher les doubles ventes.</p><div class="row3"><div class="field"><label>Objet à vendre</label><input id="marketItem"></div><div class="field"><label>Quantité</label><input id="marketQty" type="number" value="1" min="1"></div><div class="field"><label>Prix unitaire</label><input id="marketPrice" type="number" min="1"></div></div><button class="btn primary" id="marketCreate">Mettre en vente</button><h3>Marché actif</h3><div id="marketList" class="list"></div><h3>Échange sécurisé</h3><div class="row3"><div class="field"><label>ID du membre</label><input id="tradeTarget"></div><div class="field"><label>Je donne</label><input id="tradeOffer" placeholder="Nom de l'objet"></div><div class="field"><label>Quantité donnée</label><input id="tradeOfferQty" type="number" value="1"></div><div class="field"><label>Je demande (objet optionnel)</label><input id="tradeWant"></div><div class="field"><label>Quantité demandée</label><input id="tradeWantQty" type="number" value="0"></div><div class="field"><label>Argent demandé</label><input id="tradeMoney" type="number" value="0"></div></div><button class="btn" id="tradeCreate">Proposer l'échange</button><div id="tradeList" class="list" style="margin-top:10px"></div><h3>Objets utilisables</h3><div class="row3"><div class="field"><label>Objet</label><input id="catalogItem"></div><div class="field"><label>Effet</label><select id="catalogEffect"><option value="money">Argent</option><option value="engagement_points">Points d'engagement</option><option value="role">Rôle</option></select></div><div class="field"><label>Valeur / ID rôle</label><input id="catalogValue"></div></div><button class="btn" id="catalogSave">Configurer l'objet</button><div id="inventoryList" class="list" style="margin-top:10px"></div><div id="ecoAchievements" class="chips" style="margin-top:10px"></div></section>
<section id="tab-roles" class="card hidden"><h2>Menus de rôles ultra-complets</h2><p>Publie jusqu'à 20 rôles auto-attribuables. Les rôles administratifs ou trop hauts sont automatiquement refusés.</p><div class="field"><label>Salon</label><select id="roleChannel"></select></div><div class="row"><div class="field"><label>Titre</label><input id="roleTitle" value="Choisissez vos rôles"></div><div class="field"><label>Description</label><input id="roleDescription" value="Cliquez pour ajouter ou retirer un rôle."></div></div><div class="field"><label>Rôles (Ctrl/Cmd pour plusieurs)</label><select id="roleIds" multiple size="10"></select></div><button class="btn primary" id="publishRoles">Publier le menu</button></section>
<section id="tab-announcements" class="card hidden"><h2>Annonces programmées</h2><p>Envoi unique ou récurrent. Les mentions massives sont désactivées par sécurité.</p><div class="row"><div class="field"><label>Salon</label><select id="announcementChannel"></select></div><div class="field"><label>Date/heure locale</label><input id="announcementWhen" type="datetime-local"></div></div><div class="row"><div class="field"><label>Titre optionnel</label><input id="announcementTitle"></div><div class="field"><label>Répéter</label><select id="announcementRepeat"><option value="0">Une fois</option><option value="86400">Tous les jours</option><option value="604800">Toutes les semaines</option></select></div></div><div class="field"><label>Contenu</label><textarea id="announcementContent"></textarea></div><button class="btn primary" id="saveAnnouncement">Programmer</button><div id="announcementList" class="list" style="margin-top:12px"></div></section>
<section id="tab-custom" class="card hidden"><h2>Commandes personnalisées</h2><p>Crée des commandes comme <code>+regles</code>, <code>+site</code> ou <code>+staff</code> sans toucher au budget des commandes slash. Variables : {user}, {server}, {args}.</p><div class="row"><div class="field"><label>Nom</label><input id="customName" placeholder="regles"></div><div class="field"><label>Titre embed optionnel</label><input id="customTitle"></div></div><div class="field"><label>Réponse</label><textarea id="customResponse"></textarea></div><button class="btn primary" id="saveCustom">Créer</button><div id="customList" class="list" style="margin-top:12px"></div></section>
<section id="tab-events" class="card hidden"><h2>Événements dashboard</h2><p>Inscriptions par boutons, rappels automatiques et récompense économique optionnelle.</p><div class="row"><div class="field"><label>Salon</label><select id="eventChannel"></select></div><div class="field"><label>Nom</label><input id="eventName"></div></div><div class="field"><label>Description</label><textarea id="eventDescription"></textarea></div><div class="row3"><div class="field"><label>Début</label><input id="eventWhen" type="datetime-local"></div><div class="field"><label>Rappel (minutes)</label><input id="eventReminder" type="number" value="15" min="1"></div><div class="field"><label>Récompense par participant</label><input id="eventReward" type="number" value="0" min="0"></div></div><button class="btn primary" id="createEvent">Créer l'événement</button><div id="eventList" class="list" style="margin-top:12px"></div></section>
<section id="tab-giveaways" class="card hidden"><h2>Giveaways V2</h2><p>Plusieurs gagnants, rôle/niveau requis, rôle exclu, bonus d'entrées et ancienneté du compte/serveur.</p><div class="row"><div class="field"><label>Salon</label><select id="giveawayChannel"></select></div><div class="field"><label>Prix</label><input id="giveawayPrize"></div></div><div class="row3"><div class="field"><label>Fin</label><input id="giveawayWhen" type="datetime-local"></div><div class="field"><label>Gagnants</label><input id="giveawayWinners" type="number" value="1" min="1"></div><div class="field"><label>Niveau minimum</label><input id="giveawayLevel" type="number" value="0" min="0"></div></div><div class="row3"><div class="field"><label>Rôle requis</label><select id="giveawayRequired"></select></div><div class="field"><label>Rôle exclu</label><select id="giveawayExcluded"></select></div><div class="field"><label>Rôle bonus</label><select id="giveawayBonus"></select></div></div><div class="row3"><div class="field"><label>Multiplicateur bonus</label><input id="giveawayBonusEntries" type="number" value="2" min="1"></div><div class="field"><label>Âge compte (jours)</label><input id="giveawayAccountAge" type="number" value="0" min="0"></div><div class="field"><label>Ancienneté serveur (jours)</label><input id="giveawayMemberAge" type="number" value="0" min="0"></div></div><button class="btn primary" id="createGiveaway">Créer le giveaway</button><div id="giveawayList" class="list" style="margin-top:12px"></div></section>
<section id="tab-staff" class="card hidden"><h2>Statistiques staff</h2><p>Vue factuelle : tickets, temps moyen, sanctions, candidatures et changements de configuration. Aucun score global ni classement de personnes.</p><div class="scroll"><table><thead><tr><th>Staff</th><th>Tickets</th><th>Temps moyen</th><th>Sanctions</th><th>Candidatures</th><th>Config</th></tr></thead><tbody id="staffRows"></tbody></table></div></section>
<section id="tab-design" class="card hidden"><h2>Personnalisation serveur</h2><p>Identité économique et accent visuel propres à chaque serveur. Les réglages de design avancés existants restent disponibles dans Configuration complète.</p><div class="row3"><div class="field"><label>Nom de la monnaie</label><input id="currencyName"></div><div class="field"><label>Emoji monnaie</label><input id="currencyEmoji"></div><div class="field"><label>Couleur d'accent</label><input id="accentColor" type="color"></div></div><button class="btn primary" id="saveDesign">Enregistrer</button><div style="margin-top:12px"><a class="btn" href="/setup-center">Ouvrir la personnalisation complète</a></div></section>
<section id="tab-audit" class="card hidden"><h2>Journal d'audit & rollback</h2><p>Les modifications Platform V4 sont enregistrées avec l'auteur, l'avant/après et un rollback lorsque l'opération est réversible. L'historique historique de +setup est aussi affiché.</p><div id="auditList" class="list"></div><h3>Historique +setup</h3><div id="setupAuditList" class="list"></div></section>
<section id="tab-privacy" class="card hidden danger-zone"><h2>Centre de confidentialité</h2><p>Exporter ou supprimer les données personnelles du compte connecté sur ce serveur. Les sanctions, avertissements et journaux de sécurité/audit nécessaires à l'intégrité du serveur sont conservés ; le ledger économique est anonymisé.</p><div class="toolbar"><button class="btn" id="privacyExport">Voir / exporter mes données</button><a class="btn" id="privacyOpen" href="#">Page confidentialité dédiée</a></div><pre id="privacyData" class="item" style="white-space:pre-wrap;max-height:420px;overflow:auto">Aucune exportation chargée.</pre><div class="field"><label>Pour supprimer, écris DELETE</label><input id="privacyConfirm"></div><button class="btn danger" id="privacyDelete">Supprimer mes données personnelles</button></section>
</main></div></div><script>
const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let csrf='',guildId='',opts={},liveTimer=null;
async function api(url,opt={}){opt.credentials='same-origin';opt.headers={'Content-Type':'application/json',...(opt.headers||{})};if(opt.method&&opt.method!=='GET')opt.headers['X-CSRF-Token']=csrf;const r=await fetch(url,opt);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'Erreur serveur');return d}function notice(t,ok=true){$('notice').textContent=t;$('notice').style.borderColor=ok?'#294537':'#5b2931'}function fill(id,items,empty='Aucun'){const e=$(id);e.innerHTML=`<option value="">${esc(empty)}</option>`+items.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}function dtValueToTs(id){const v=$(id).value;if(!v)return 0;return Math.floor(new Date(v).getTime()/1000)}function item(html){return `<div class="item">${html}</div>`}function fdate(ts){return ts?new Date(Number(ts)*1000).toLocaleString():'—'}
function populateOptions(){['roleChannel','announcementChannel','eventChannel','giveawayChannel'].forEach(id=>fill(id,opts.text_channels,'Choisir'));['giveawayRequired','giveawayExcluded','giveawayBonus'].forEach(id=>fill(id,opts.roles,'Aucun'));$('roleIds').innerHTML=opts.roles.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('');$('currencyName').value=opts.settings.currency_name||'pièces';$('currencyEmoji').value=opts.settings.currency_emoji||'🪙';$('accentColor').value=opts.settings.accent_color||'#7d8cff';$('privacyOpen').href='/privacy/'+guildId;}
async function boot(){const me=await api('/api/me');csrf=me.csrf;const g=await api('/api/guilds');const installed=g.guilds.filter(x=>x.installed);$('guild').innerHTML=installed.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('');if(!installed.length){notice('Aucun serveur administrable.',false);return}guildId=installed[0].id;await loadAll();startLive()}
async function loadAll(){opts=await api(`/api/guilds/${guildId}/platform-v4/options`);$('brand').firstChild.nodeValue=opts.brand+' ';populateOptions();await Promise.all([loadLive(),loadHealth(),loadAnnouncements(),loadCommands(),loadEconomy(),loadMarket(),loadEvents(),loadGiveaways(),loadStaff(),loadBackups(),loadAudit()]);notice('Platform V4 prêt.')}
async function loadLive(){const d=await api(`/api/guilds/${guildId}/platform-v4/live`);const s=d.stats;$('liveMembers').textContent=s.members;$('liveVoice').textContent=s.voice;$('liveMessages').textContent=s.messages_tracked;$('liveLatency').textContent=s.latency_ms+' ms';$('liveGiveaways').textContent=s.active_giveaways;$('liveEvents').textContent=s.active_events}function startLive(){clearInterval(liveTimer);liveTimer=setInterval(()=>loadLive().catch(()=>{}),5000)}
async function loadHealth(){const d=await api(`/api/guilds/${guildId}/platform-v4/health`);const h=d.health;const entries=[['Discord',h.discord],['SQLite',h.database],['OpenAI configuré',h.openai_configured],['Redis configuré',h.redis_configured],['Postgres configuré',h.postgres_configured],['DB',h.database_ms+' ms'],['Tickets ouverts',h.open_tickets],['Candidatures',h.pending_applications]];$('healthGrid').innerHTML=entries.map(([k,v])=>`<div class="metric"><b class="${typeof v==='boolean'?(v?'ok':'bad'):''}">${esc(typeof v==='boolean'?(v?'OK':'Non'):v)}</b><span>${esc(k)}</span></div>`).join('')}
async function loadAnnouncements(){const d=await api(`/api/guilds/${guildId}/platform-v4/announcements`);$('announcementList').innerHTML=d.items.length?d.items.map(x=>item(`<strong>#${x.id} ${esc(x.title||'Annonce')}</strong><div class="meta">${fdate(x.run_at)} · ${x.repeat_seconds?'récurrente':'unique'} · ${x.enabled?'active':'inactive'}</div><p>${esc(x.content)}</p>${x.enabled?`<button class="btn" data-cancel-ann="${x.id}">Désactiver</button>`:''}`)).join(''):item('Aucune annonce programmée.')}
async function loadCommands(){const d=await api(`/api/guilds/${guildId}/platform-v4/custom-commands`);$('customList').innerHTML=d.items.length?d.items.map(x=>item(`<strong>${esc(opts.prefix)}${esc(x.name)}</strong><p>${esc(x.response)}</p><button class="btn danger" data-del-command="${x.id}">Supprimer</button>`)).join(''):item('Aucune commande personnalisée.')}
async function loadEconomy(){const d=await api(`/api/guilds/${guildId}/platform-v4/economy`);$('ecoFlags').innerHTML=d.flags.length?d.flags.map(x=>item(`<strong>À vérifier</strong><div class="meta">${esc(x.reasons.join(', '))}${x.transaction_id?' · transaction #'+x.transaction_id:''}</div>`)).join(''):item('Aucune anomalie simple détectée dans les transactions récentes.');$('ecoRows').innerHTML=d.transactions.map(x=>`<tr><td>${x.transaction_id}</td><td>${esc(x.transaction_type)}</td><td>${esc(x.sender_id||'—')}</td><td>${esc(x.receiver_id||'—')}</td><td>${esc(x.amount)}</td><td>${esc(x.reason||'')}</td><td>${fdate(x.created_at)}</td></tr>`).join('')}
async function loadMarket(){const d=await api(`/api/guilds/${guildId}/platform-v4/market`);$('marketList').innerHTML=d.items.length?d.items.map(x=>item(`<strong>#${x.id} · ${esc(x.item_name)} × ${x.quantity}</strong><div class="meta">${x.unit_price} / unité · vendeur ${x.seller_id}</div>${String(x.seller_id)===String(d.user_id)?`<button class="btn" data-cancel-listing="${x.id}">Annuler</button>`:`<button class="btn primary" data-buy-listing="${x.id}">Acheter</button>`}`)).join(''):item('Marché vide.');$('tradeList').innerHTML=d.trades.length?d.trades.map(x=>item(`<strong>Échange #${x.id}</strong><div class="meta">${x.creator_id} → ${x.target_id} · donne ${esc(x.offer_item)} × ${x.offer_quantity} · demande ${esc(x.want_item||'rien')} ${x.want_quantity||''} ${x.want_money?' + '+x.want_money+' pièces':''}</div>${String(x.target_id)===String(d.user_id)?`<button class="btn primary" data-accept-trade="${x.id}">Accepter</button>`:''}`)).join(''):item('Aucun échange en attente.');$('inventoryList').innerHTML=d.inventory.length?d.inventory.map(x=>{const usable=d.catalog.some(c=>c.item_name===x.item_name);return item(`<strong>${esc(x.item_name)} × ${x.quantity}</strong>${usable?` <button class="btn" data-use-item="${esc(x.item_name)}">Utiliser</button>`:''}`)}).join(''):item('Inventaire vide.');$('ecoAchievements').innerHTML=d.achievements.map(x=>`<span class="chip ${x.unlocked?'ok':''}">${x.unlocked?'Débloqué · ':''}${esc(x.name)}</span>`).join('')}
async function loadEvents(){const d=await api(`/api/guilds/${guildId}/platform-v4/events`);$('eventList').innerHTML=d.items.length?d.items.map(x=>item(`<strong>#${x.id} ${esc(x.name)}</strong><div class="meta">${fdate(x.start_at)} · ${esc(x.status)} · ${x.participants} participant(s)</div><p>${esc(x.description||'')}</p>`)).join(''):item('Aucun événement.')}
async function loadGiveaways(){const d=await api(`/api/guilds/${guildId}/platform-v4/giveaways`);$('giveawayList').innerHTML=d.items.length?d.items.map(x=>item(`<strong>#${x.id} ${esc(x.prize)}</strong><div class="meta">${esc(x.status)} · fin ${fdate(x.end_at)} · ${x.entries} entrée(s) · ${x.winners_count} gagnant(s)</div>`)).join(''):item('Aucun giveaway.')}
async function loadStaff(){const d=await api(`/api/guilds/${guildId}/platform-v4/staff`);$('staffRows').innerHTML=d.items.map(x=>`<tr><td>${esc(x.name)}</td><td>${x.tickets}</td><td>${x.avg_ticket_minutes} min</td><td>${x.sanctions}</td><td>${x.applications}</td><td>${x.config_changes}</td></tr>`).join('')||'<tr><td colspan="6">Aucune donnée staff.</td></tr>'}
async function loadBackups(){const d=await api(`/api/guilds/${guildId}/platform-v4/backups`);$('backups').innerHTML=d.items.length?d.items.map(x=>item(`<strong>#${x.id} ${esc(x.label)}</strong><div class="meta">${fdate(x.created_at)} · créé par ${x.created_by||'—'}</div><button class="btn" data-restore="${x.id}">Restaurer ce qui manque</button>`)).join(''):item('Aucune sauvegarde serveur.')}
async function loadAudit(){const d=await api(`/api/guilds/${guildId}/platform-v4/audit`);$('auditList').innerHTML=d.items.length?d.items.map(x=>item(`<strong>#${x.id} ${esc(x.action)}</strong><div class="meta">Auteur ${x.actor_id} · ${fdate(x.created_at)} · ${esc(x.target_type)} ${esc(x.target_id)}</div>${x.rollback_kind?`<button class="btn" data-rollback="${x.id}">Rollback</button>`:''}`)).join(''):item('Aucune action Platform V4.');$('setupAuditList').innerHTML=d.setup_history.length?d.setup_history.map(x=>item(`<strong>${esc(x.module)} · ${esc(x.action)}</strong><div class="meta">Auteur ${x.user_id} · ${fdate(x.created_at)}</div>`)).join(''):item('Aucun historique +setup.')}
async function post(url,data){return api(url,{method:'POST',body:JSON.stringify(data)})}async function put(url,data){return api(url,{method:'PUT',body:JSON.stringify(data)})}
$('guild').addEventListener('change',async e=>{guildId=e.target.value;await loadAll()});document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.nav').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.main>section').forEach(x=>x.classList.add('hidden'));$('tab-'+b.dataset.tab).classList.remove('hidden')}));
$('runSetup').onclick=async()=>{try{const d=await post(`/api/guilds/${guildId}/platform-v4/quick-setup`,{profile:$('setupProfile').value});$('setupResult').textContent=JSON.stringify(d.result,null,2);notice('Configuration 1 clic terminée.')}catch(e){notice(e.message,false)}};
$('createBackup').onclick=async()=>{try{await post(`/api/guilds/${guildId}/platform-v4/backups`,{label:$('backupLabel').value});await loadBackups();notice('Sauvegarde créée.')}catch(e){notice(e.message,false)}};
$('saveAnnouncement').onclick=async()=>{try{await post(`/api/guilds/${guildId}/platform-v4/announcements`,{channel_id:$('announcementChannel').value,title:$('announcementTitle').value,content:$('announcementContent').value,run_at:dtValueToTs('announcementWhen'),repeat_seconds:Number($('announcementRepeat').value)});await loadAnnouncements();notice('Annonce programmée.')}catch(e){notice(e.message,false)}};
$('saveCustom').onclick=async()=>{try{await post(`/api/guilds/${guildId}/platform-v4/custom-commands`,{name:$('customName').value,response:$('customResponse').value,embed_title:$('customTitle').value});await loadCommands();notice('Commande créée.')}catch(e){notice(e.message,false)}};
$('publishRoles').onclick=async()=>{try{const roles=[...$('roleIds').selectedOptions].map(o=>({role_id:o.value,label:o.textContent}));await post(`/api/guilds/${guildId}/platform-v4/role-menu`,{channel_id:$('roleChannel').value,title:$('roleTitle').value,description:$('roleDescription').value,roles});notice('Menu de rôles publié.')}catch(e){notice(e.message,false)}};
$('marketCreate').onclick=async()=>{try{await post(`/api/guilds/${guildId}/platform-v4/market`,{item_name:$('marketItem').value,quantity:Number($('marketQty').value),unit_price:Number($('marketPrice').value)});await loadMarket();notice('Objet mis en vente.')}catch(e){notice(e.message,false)}};
$('tradeCreate').onclick=async()=>{try{await post(`/api/guilds/${guildId}/platform-v4/trades`,{target_id:$('tradeTarget').value,offer_item:$('tradeOffer').value,offer_quantity:Number($('tradeOfferQty').value),want_item:$('tradeWant').value,want_quantity:Number($('tradeWantQty').value),want_money:Number($('tradeMoney').value)});await loadMarket();notice('Échange proposé.')}catch(e){notice(e.message,false)}};
$('catalogSave').onclick=async()=>{try{const effect=$('catalogEffect').value;const raw=Number($('catalogValue').value||0);await post(`/api/guilds/${guildId}/platform-v4/catalog`,{item_name:$('catalogItem').value,effect_type:effect,effect_value:effect==='role'?0:raw,role_id:effect==='role'?raw:null});await loadMarket();notice('Objet utilisable configuré.')}catch(e){notice(e.message,false)}};
$('createEvent').onclick=async()=>{try{await post(`/api/guilds/${guildId}/platform-v4/events`,{channel_id:$('eventChannel').value,name:$('eventName').value,description:$('eventDescription').value,start_at:dtValueToTs('eventWhen'),reminder_minutes:Number($('eventReminder').value),reward_amount:Number($('eventReward').value)});await loadEvents();notice('Événement créé.')}catch(e){notice(e.message,false)}};
$('createGiveaway').onclick=async()=>{try{await post(`/api/guilds/${guildId}/platform-v4/giveaways`,{channel_id:$('giveawayChannel').value,prize:$('giveawayPrize').value,end_at:dtValueToTs('giveawayWhen'),winners_count:Number($('giveawayWinners').value),required_level:Number($('giveawayLevel').value),required_role_id:$('giveawayRequired').value,excluded_role_id:$('giveawayExcluded').value,bonus_role_id:$('giveawayBonus').value,bonus_entries:Number($('giveawayBonusEntries').value),min_account_age_days:Number($('giveawayAccountAge').value),min_member_age_days:Number($('giveawayMemberAge').value)});await loadGiveaways();notice('Giveaway créé.')}catch(e){notice(e.message,false)}};
$('saveDesign').onclick=async()=>{try{opts.settings=(await put(`/api/guilds/${guildId}/platform-v4/settings`,{currency_name:$('currencyName').value,currency_emoji:$('currencyEmoji').value,accent_color:$('accentColor').value})).settings;notice('Personnalisation enregistrée.')}catch(e){notice(e.message,false)}};
$('privacyExport').onclick=async()=>{try{const d=await api(`/api/platform-v4/privacy/${guildId}`);$('privacyData').textContent=JSON.stringify(d.data,null,2);notice('Données chargées.')}catch(e){notice(e.message,false)}};$('privacyDelete').onclick=async()=>{try{const confirm=$('privacyConfirm').value;if(confirm!=='DELETE')throw new Error('Écris DELETE exactement.');const d=await post(`/api/platform-v4/privacy/${guildId}/delete`,{confirm});$('privacyData').textContent=JSON.stringify(d.result,null,2);notice('Données personnelles supprimées.')}catch(e){notice(e.message,false)}};
document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;try{if(b.dataset.cancelAnn){await post(`/api/guilds/${guildId}/platform-v4/announcements/${b.dataset.cancelAnn}/cancel`,{});await loadAnnouncements()}if(b.dataset.delCommand){await api(`/api/guilds/${guildId}/platform-v4/custom-commands/${b.dataset.delCommand}`,{method:'DELETE',body:'{}'});await loadCommands()}if(b.dataset.buyListing){await post(`/api/guilds/${guildId}/platform-v4/market/${b.dataset.buyListing}/buy`,{});await loadMarket()}if(b.dataset.cancelListing){await post(`/api/guilds/${guildId}/platform-v4/market/${b.dataset.cancelListing}/cancel`,{});await loadMarket()}if(b.dataset.acceptTrade){await post(`/api/guilds/${guildId}/platform-v4/trades/${b.dataset.acceptTrade}/accept`,{});await loadMarket()}if(b.dataset.useItem){await post(`/api/guilds/${guildId}/platform-v4/items/use`,{item_name:b.dataset.useItem});await loadMarket()}if(b.dataset.restore){const confirm=prompt('Écris RESTORE pour confirmer la restauration non destructive.');if(confirm==='RESTORE'){await post(`/api/guilds/${guildId}/platform-v4/backups/${b.dataset.restore}/restore`,{confirm});await loadBackups();notice('Restauration terminée.')}}if(b.dataset.rollback){await post(`/api/guilds/${guildId}/platform-v4/audit/${b.dataset.rollback}/rollback`,{});await loadAll();notice('Rollback appliqué.')}}catch(err){notice(err.message,false)}});
boot().catch(e=>notice(e.message,false));
</script></body></html>'''

PRIVACY_HTML = r'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Confidentialité</title><style>body{margin:0;background:#080a10;color:#f4f6fb;font-family:system-ui}.shell{max-width:900px;margin:auto;padding:24px}.card{border:1px solid #252b3a;background:#10131b;border-radius:16px;padding:18px;margin-bottom:12px}.muted{color:#949caf}.btn{border:1px solid #252b3a;background:#171b27;color:#f4f6fb;border-radius:10px;padding:10px 12px;cursor:pointer;text-decoration:none}.danger{border-color:#6b2b36;background:#251216}.row{display:flex;gap:8px;flex-wrap:wrap}pre{white-space:pre-wrap;overflow:auto;max-height:560px;border:1px solid #252b3a;background:#090c12;padding:12px;border-radius:10px}input{width:100%;margin:10px 0;padding:10px;background:#090c12;color:white;border:1px solid #252b3a;border-radius:9px}@media(max-width:600px){.shell{padding:10px}}</style></head><body><div class="shell"><div class="card"><h1>Centre de confidentialité</h1><p class="muted">Tu peux consulter les données personnelles enregistrées sur toi, puis demander leur suppression. Les sanctions, avertissements et journaux de sécurité/audit restent conservés pour l'intégrité du serveur. Les anciennes transactions économiques sont anonymisées.</p><div class="row"><a class="btn" href="/app">Dashboard</a><a class="btn" href="/platform-v4">Platform V4</a><button class="btn" id="load">Charger mes données</button></div></div><div class="card"><pre id="data">Clique sur « Charger mes données ».</pre></div><div class="card"><h2>Suppression</h2><p class="muted">Les ventes/échanges en cours doivent être terminés ou annulés d'abord.</p><input id="confirm" placeholder="Écris DELETE"><button class="btn danger" id="delete">Supprimer mes données personnelles</button><p id="status" class="muted"></p></div></div><script>const gid=location.pathname.split('/').pop();let csrf='';async function api(url,opt={}){opt.credentials='same-origin';opt.headers={'Content-Type':'application/json',...(opt.headers||{})};if(opt.method&&opt.method!=='GET')opt.headers['X-CSRF-Token']=csrf;const r=await fetch(url,opt);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'Erreur');return d}async function boot(){csrf=(await api('/api/me')).csrf}document.getElementById('load').onclick=async()=>{try{const d=await api('/api/platform-v4/privacy/'+gid);document.getElementById('data').textContent=JSON.stringify(d.data,null,2)}catch(e){document.getElementById('status').textContent=e.message}};document.getElementById('delete').onclick=async()=>{try{const c=document.getElementById('confirm').value;if(c!=='DELETE')throw new Error('Écris DELETE exactement.');const d=await api('/api/platform-v4/privacy/'+gid+'/delete',{method:'POST',body:JSON.stringify({confirm:c})});document.getElementById('data').textContent=JSON.stringify(d.result,null,2);document.getElementById('status').textContent='Suppression terminée.'}catch(e){document.getElementById('status').textContent=e.message}};boot()</script></body></html>'''


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard

        async def startup_platform(_app):
            getter = getattr(bot, "get_cog", None)
            if not callable(getter) or not hasattr(bot, "db") or getter("PlatformV4") is not None:
                return
            try:
                from cogs import platform_v4
                await platform_v4.setup(bot)
            except Exception:
                logger.exception("Impossible de démarrer Platform V4.")

        app.on_startup.append(startup_platform)
        app.router.add_routes([
            web.get("/platform-v4", handle_page),
            web.get("/privacy/{guild_id}", handle_privacy_page),
            web.get("/api/guilds/{guild_id}/platform-v4/options", lambda r: api_options(dashboard, r)),
            web.put("/api/guilds/{guild_id}/platform-v4/settings", lambda r: api_settings(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/live", lambda r: api_live(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/health", lambda r: api_health(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/announcements", lambda r: api_announcements_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/announcements", lambda r: api_announcements_post(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/announcements/{item_id}/cancel", lambda r: api_announcement_cancel(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/custom-commands", lambda r: api_commands_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/custom-commands", lambda r: api_commands_post(dashboard, r)),
            web.delete("/api/guilds/{guild_id}/platform-v4/custom-commands/{item_id}", lambda r: api_command_delete(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/role-menu", lambda r: api_role_menu(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/economy", lambda r: api_economy(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/market", lambda r: api_market_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/market", lambda r: api_market_create(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/market/{listing_id}/buy", lambda r: api_market_buy(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/market/{listing_id}/cancel", lambda r: api_market_cancel(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/trades", lambda r: api_trade_create(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/trades/{trade_id}/accept", lambda r: api_trade_accept(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/catalog", lambda r: api_catalog(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/items/use", lambda r: api_use_item(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/events", lambda r: api_events_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/events", lambda r: api_events_post(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/giveaways", lambda r: api_giveaways_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/giveaways", lambda r: api_giveaways_post(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/quick-setup", lambda r: api_quick_setup(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/backups", lambda r: api_backups_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/backups", lambda r: api_backups_post(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/backups/{backup_id}/restore", lambda r: api_backup_restore(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/staff", lambda r: api_staff(dashboard, r)),
            web.get("/api/guilds/{guild_id}/platform-v4/audit", lambda r: api_audit_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/platform-v4/audit/{audit_id}/rollback", lambda r: api_audit_rollback(dashboard, r)),
            web.get("/api/platform-v4/privacy/{guild_id}", lambda r: api_privacy_get(dashboard, r)),
            web.post("/api/platform-v4/privacy/{guild_id}/delete", lambda r: api_privacy_delete(dashboard, r)),
        ])
        return app

    dashboard.build_app = build_app
    logger.info("Dashboard Platform V4 installé.")
