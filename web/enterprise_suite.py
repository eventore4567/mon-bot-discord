"""Dashboard Enterprise SentriX.

Page isolée du dashboard principal avec permissions par section. Les routes privées réutilisent
OAuth, la liste des serveurs gérables et le CSRF existants. Le formulaire /appeal/{token}
est public uniquement parce que le token aléatoire est le secret d'accès au recours.
"""
from __future__ import annotations

import html
import json
import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.enterprise")
_INSTALLED = False


def _service(request: web.Request):
    return request.app["bot"].get_cog("EnterpriseSuite")


async def _payload(request: web.Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:
        raise ValueError("Le formulaire envoyé est invalide.") from exc
    if not isinstance(data, dict):
        raise ValueError("Le formulaire envoyé est invalide.")
    return data


async def _ctx(dashboard, request: web.Request, section: str, *, write: bool = False, owner_admin: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, ValueError):
        return None, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return None, None, None, error
    service = _service(request)
    if service is None:
        return None, None, None, dashboard._json_error("Enterprise Suite n'est pas encore prêt.", 503)
    user_id = int(session["user"]["id"])
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            member = None
    if owner_admin:
        if member is None or (member.id != guild.owner_id and not member.guild_permissions.administrator):
            return None, None, None, dashboard._json_error("Seul le propriétaire ou un administrateur peut modifier cette section.", 403)
    elif not await service.dashboard_access(guild, user_id, section):
        return None, None, None, dashboard._json_error("Votre rôle n'a pas accès à cette section Enterprise.", 403)
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, csrf_error
    return session, guild, service, None


async def _audit(request: web.Request, guild_id: int, user_id: int, action: str, target: str = "", details: dict | None = None):
    try:
        await request.app["bot"].db.execute(
            "INSERT INTO dashboard_audit_log (guild_id,user_id,action,target,details_json,created_at) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, action[:120], target[:300], json.dumps(details or {}, ensure_ascii=False)[:6000], int(time.time())),
        )
    except Exception:
        pass


async def handle_enterprise_page(request: web.Request) -> web.Response:
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login")
    return web.Response(text=ENTERPRISE_HTML, content_type="text/html", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


# ---------------------------------------------------------------- public appeals
async def handle_appeal_page(request: web.Request) -> web.Response:
    token = request.match_info.get("token", "")
    service = _service(request)
    if service is None or not token:
        raise web.HTTPNotFound()
    appeal = await service.appeal_from_token(token)
    if not appeal:
        raise web.HTTPNotFound(text="Lien de recours invalide ou expiré.")
    return web.Response(text=APPEAL_HTML, content_type="text/html", headers={"Cache-Control": "no-store"})


async def api_appeal_public_get(request: web.Request):
    service = _service(request)
    if service is None:
        return web.json_response({"error": "SentriX démarre."}, status=503)
    appeal = await service.appeal_from_token(request.match_info.get("token", ""))
    if not appeal:
        return web.json_response({"error": "Lien invalide."}, status=404)
    public = {
        "id": appeal["id"], "guild_name": appeal["guild_name"], "status": appeal["status"],
        "ban_reason": appeal.get("ban_reason") or "Aucune raison fournie",
        "case_number": appeal.get("case_number"),
        "messages": [m for m in appeal.get("messages", []) if m.get("author_type") == "staff"],
    }
    return web.json_response({"ok": True, "appeal": public})


async def api_appeal_public_post(request: web.Request):
    service = _service(request)
    if service is None:
        return web.json_response({"error": "SentriX démarre."}, status=503)
    try:
        data = await _payload(request)
        result = await service.submit_appeal(request.match_info.get("token", ""), str(data.get("message") or ""))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"ok": True, "status": result["status"]})


# ---------------------------------------------------------------- private summary/settings
async def api_summary(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "monitoring")
    if error:
        return error
    db = request.app["bot"].db
    counts = {}
    for key, sql in {
        "appeals": "SELECT COUNT(*) AS n FROM ban_appeals WHERE guild_id=? AND status IN ('open','more_info','awaiting_user')",
        "modmail": "SELECT COUNT(*) AS n FROM modmail_threads WHERE guild_id=? AND status='open'",
        "automations": "SELECT COUNT(*) AS n FROM automation_rules WHERE guild_id=? AND enabled=1",
        "recommendations": "SELECT COUNT(*) AS n FROM sentrix_recommendations_v2 WHERE guild_id=? AND active=1",
    }.items():
        row = await db.fetchone(sql, (guild.id,))
        counts[key] = int(row["n"] if row else 0)
    return web.json_response({
        "ok": True, "counts": counts, "settings": await service.get_settings(guild.id),
        "monitoring": await service.monitoring_summary(guild.id),
        "sections": service.__class__.__module__ and __import__("cogs.enterprise_suite", fromlist=["DASHBOARD_SECTIONS"]).DASHBOARD_SECTIONS,
        "user_id": int(session["user"]["id"]),
    })


async def api_settings_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request, "permissions")
    if error:
        return error
    return web.json_response({"ok": True, "settings": await service.get_settings(guild.id)})


async def api_settings_put(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "permissions", write=True, owner_admin=True)
    if error:
        return error
    try:
        data = await _payload(request)
        channel_id = data.get("modmail_channel_id")
        if channel_id not in (None, "", 0, "0"):
            channel_id = int(channel_id)
            channel = guild.get_channel(channel_id)
            if channel is None or channel.__class__.__name__ != "TextChannel":
                raise ValueError("Choisissez un salon textuel valide pour le Modmail.")
        else:
            channel_id = None
        settings = await service.update_settings(
            guild.id,
            appeals_enabled=int(bool(data.get("appeals_enabled", True))),
            modmail_enabled=int(bool(data.get("modmail_enabled", True))),
            modmail_channel_id=channel_id,
            automations_enabled=int(bool(data.get("automations_enabled", True))),
            external_backups_enabled=int(bool(data.get("external_backups_enabled", True))),
        )
        await _audit(request, guild.id, int(session["user"]["id"]), "enterprise_settings", str(guild.id))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "settings": settings})


# ---------------------------------------------------------------- appeals staff
async def api_appeals_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request, "appeals")
    if error:
        return error
    return web.json_response({"ok": True, "appeals": await service.list_appeals(guild.id)})


async def api_appeal_review(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "appeals", write=True)
    if error:
        return error
    try:
        appeal_id = int(request.match_info["appeal_id"])
        data = await _payload(request)
        result = await service.review_appeal(guild, appeal_id, int(session["user"]["id"]), str(data.get("decision") or ""), str(data.get("note") or ""))
        await _audit(request, guild.id, int(session["user"]["id"]), "appeal_review", str(appeal_id), {"decision": data.get("decision")})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "appeal": result})


# ---------------------------------------------------------------- modmail
async def api_modmail_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request, "modmail")
    if error:
        return error
    return web.json_response({"ok": True, "threads": await service.list_modmail(guild.id)})


async def api_modmail_messages(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request, "modmail")
    if error:
        return error
    try:
        record_id = int(request.match_info["record_id"])
        messages = await service.modmail_messages(guild.id, record_id)
    except ValueError as exc:
        return dashboard._json_error(str(exc), 404)
    return web.json_response({"ok": True, "messages": messages})


async def api_modmail_reply(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "modmail", write=True)
    if error:
        return error
    try:
        record_id = int(request.match_info["record_id"])
        data = await _payload(request)
        await service.modmail_staff_reply(guild, record_id, int(session["user"]["id"]), str(data.get("message") or ""))
        await _audit(request, guild.id, int(session["user"]["id"]), "modmail_reply", str(record_id))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True})


async def api_modmail_status(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "modmail", write=True)
    if error:
        return error
    try:
        record_id = int(request.match_info["record_id"])
        data = await _payload(request)
        status = str(data.get("status") or "")
        await service.set_modmail_status(guild, record_id, int(session["user"]["id"]), status)
        await _audit(request, guild.id, int(session["user"]["id"]), "modmail_status", str(record_id), {"status": status})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True})


# ---------------------------------------------------------------- automations
async def api_automations_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request, "automations")
    if error:
        return error
    return web.json_response({"ok": True, "rules": await service.list_automations(guild.id)})


async def api_automations_put(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "automations", write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        rule_id = await service.save_automation(guild.id, int(session["user"]["id"]), data)
        await _audit(request, guild.id, int(session["user"]["id"]), "automation_save", str(rule_id), {"trigger": data.get("trigger_type")})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "id": rule_id})


async def api_automations_delete(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "automations", write=True)
    if error:
        return error
    try:
        rule_id = int(request.match_info["rule_id"])
    except ValueError:
        return dashboard._json_error("Automatisation invalide.", 400)
    await service.delete_automation(guild.id, rule_id)
    await _audit(request, guild.id, int(session["user"]["id"]), "automation_delete", str(rule_id))
    return web.json_response({"ok": True})


# ---------------------------------------------------------------- monitoring / canary
async def api_monitoring_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request, "monitoring")
    if error:
        return error
    return web.json_response({"ok": True, **await service.monitoring_summary(guild.id)})


async def api_canary_post(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "monitoring", write=True, owner_admin=True)
    if error:
        return error
    result = await service.run_canary()
    await _audit(request, guild.id, int(session["user"]["id"]), "canary_run", str(guild.id), {"status": result.get("status")})
    return web.json_response({"ok": True, "canary": result})


# ---------------------------------------------------------------- backups
async def api_backups_get(dashboard, request: web.Request):
    _session, _guild, service, error = await _ctx(dashboard, request, "backups")
    if error:
        return error
    return web.json_response({"ok": True, "backups": await service.list_external_backups()})


async def api_backups_post(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "backups", write=True, owner_admin=True)
    if error:
        return error
    result = await service.create_external_backup(int(session["user"]["id"]))
    await _audit(request, guild.id, int(session["user"]["id"]), "external_backup", str(result["id"]), {"storage": result["storage"]})
    return web.json_response({"ok": True, "backup": result})


async def api_backup_restore(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "backups", write=True, owner_admin=True)
    if error:
        return error
    try:
        backup_id = int(request.match_info["backup_id"])
        data = await _payload(request)
        if str(data.get("confirm") or "") != "RESTORE":
            raise ValueError("Confirmation RESTORE requise.")
        await service.restore_external_backup(backup_id, int(session["user"]["id"]))
        await _audit(request, guild.id, int(session["user"]["id"]), "external_backup_restore", str(backup_id))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True})


# ---------------------------------------------------------------- analytics / recommendations
async def api_analytics_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request, "analytics")
    if error:
        return error
    data = await service.analytics(guild)
    since = int(time.time()) - 7 * 86400
    giveaway_rows = await request.app["bot"].db.fetchall(
        "SELECT g.id,g.prize,g.status,COUNT(e.user_id) AS entries FROM giveaways g LEFT JOIN giveaway_entries e ON e.giveaway_id=g.id WHERE g.guild_id=? AND COALESCE(g.created_at,0)>=? GROUP BY g.id ORDER BY g.created_at DESC LIMIT 10",
        (guild.id, since),
    )
    staff_rows = await request.app["bot"].db.fetchall(
        "SELECT moderator_id,COUNT(*) AS actions FROM sanctions WHERE guild_id=? AND created_at>=? GROUP BY moderator_id ORDER BY actions DESC LIMIT 10",
        (guild.id, since),
    )
    data["giveaways"] = [dict(r) for r in giveaway_rows]
    data["staff_activity"] = [dict(r) for r in staff_rows]
    return web.json_response({"ok": True, **data})


async def api_recommendations_post(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "analytics", write=True)
    if error:
        return error
    latest = await service.snapshot_guild(guild)
    recs = await service.recommendations(guild.id)
    await _audit(request, guild.id, int(session["user"]["id"]), "recommendations_refresh", str(guild.id))
    return web.json_response({"ok": True, "latest": latest, "recommendations": recs})


# ---------------------------------------------------------------- dashboard section roles
async def api_access_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request, "permissions", owner_admin=True)
    if error:
        return error
    module = __import__("cogs.enterprise_suite", fromlist=["DASHBOARD_SECTIONS"])
    return web.json_response({"ok": True, "sections": module.DASHBOARD_SECTIONS, "rules": await service.get_dashboard_roles(guild.id)})


async def api_access_put(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, "permissions", write=True, owner_admin=True)
    if error:
        return error
    try:
        data = await _payload(request)
        section = str(data.get("section") or "")
        role_id = int(data.get("role_id") or 0)
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed:
            raise ValueError("Rôle invalide.")
        enabled = bool(data.get("enabled", True))
        await service.set_dashboard_role(guild.id, section, role_id, enabled, int(session["user"]["id"]))
        await _audit(request, guild.id, int(session["user"]["id"]), "dashboard_section_role", f"{section}:{role_id}", {"enabled": enabled})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return await api_access_get(dashboard, request)


ENTERPRISE_LINK_JS = r"""
<script id="sentrix-enterprise-link">
(()=>{"use strict";if(window.__sentrixEnterpriseLink)return;window.__sentrixEnterpriseLink=true;function install(){const host=document.querySelector('.side-bottom')||document.querySelector('.nav');if(!host)return;let a=document.getElementById('sentrixEnterpriseLink');if(!a){a=document.createElement('a');a.id='sentrixEnterpriseLink';a.className='btn ghost';a.textContent='Enterprise';host.appendChild(a)}let id='';try{id=state&&state.guildId?String(state.guildId):''}catch(_){}a.href='/enterprise'+(id?'?guild='+encodeURIComponent(id):'')}setInterval(install,1200);setTimeout(install,120)})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    try:
        from . import admin_only_dashboard
        admin_only_dashboard._PRIVATE_PAGE_PATHS.add("/enterprise")
    except Exception:
        logger.exception("Impossible de protéger /enterprise.")
    original_build_app = dashboard.build_app

    def bind(fn):
        async def handler(request: web.Request):
            return await fn(dashboard, request)
        return handler

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/enterprise", handle_enterprise_page)
        app.router.add_get("/appeal/{token}", handle_appeal_page)
        app.router.add_get("/api/appeal/{token}", api_appeal_public_get)
        app.router.add_post("/api/appeal/{token}", api_appeal_public_post)
        base = "/api/guilds/{guild_id}/enterprise"
        app.router.add_get(base + "/summary", bind(api_summary))
        app.router.add_get(base + "/settings", bind(api_settings_get))
        app.router.add_put(base + "/settings", bind(api_settings_put))
        app.router.add_get(base + "/appeals", bind(api_appeals_get))
        app.router.add_post(base + "/appeals/{appeal_id}", bind(api_appeal_review))
        app.router.add_get(base + "/modmail", bind(api_modmail_get))
        app.router.add_get(base + "/modmail/{record_id}", bind(api_modmail_messages))
        app.router.add_post(base + "/modmail/{record_id}/reply", bind(api_modmail_reply))
        app.router.add_post(base + "/modmail/{record_id}/status", bind(api_modmail_status))
        app.router.add_get(base + "/automations", bind(api_automations_get))
        app.router.add_put(base + "/automations", bind(api_automations_put))
        app.router.add_delete(base + "/automations/{rule_id}", bind(api_automations_delete))
        app.router.add_get(base + "/monitoring", bind(api_monitoring_get))
        app.router.add_post(base + "/canary", bind(api_canary_post))
        app.router.add_get(base + "/backups", bind(api_backups_get))
        app.router.add_post(base + "/backups", bind(api_backups_post))
        app.router.add_post(base + "/backups/{backup_id}/restore", bind(api_backup_restore))
        app.router.add_get(base + "/analytics", bind(api_analytics_get))
        app.router.add_post(base + "/recommendations", bind(api_recommendations_post))
        app.router.add_get(base + "/access", bind(api_access_get))
        app.router.add_put(base + "/access", bind(api_access_put))
        return app

    dashboard.build_app = build_app
    if 'id="sentrix-enterprise-link"' not in dashboard.INDEX_HTML:
        dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace("</body>", ENTERPRISE_LINK_JS + "\n</body>", 1)
    logger.info("Enterprise Suite ajoutée au dashboard.")


APPEAL_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SentriX / Recours</title><style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#090b12;color:#f3f5ff;font:15px system-ui;min-height:100vh;display:grid;place-items:center;padding:20px}.box{width:min(680px,100%);background:#111522;border:1px solid #293149;border-radius:18px;padding:24px}h1{margin:0 0 8px;font-size:26px}p{color:#a7afc2;line-height:1.55}.reason{padding:13px;background:#0b0f18;border:1px solid #283049;border-radius:12px;margin:16px 0;white-space:pre-wrap}textarea{width:100%;min-height:180px;background:#0b0f18;color:#fff;border:1px solid #303957;border-radius:12px;padding:12px;font:inherit;resize:vertical}button{margin-top:10px;border:0;border-radius:10px;padding:11px 15px;background:#7668ff;color:#fff;font-weight:800;cursor:pointer}.status{margin-top:12px;color:#9de1c7}.bad{color:#ff93a5}</style></head><body><main class="box"><h1>Recours de bannissement</h1><p id="server">Chargement</p><div class="reason" id="reason"></div><div id="history"></div><textarea id="message" maxlength="4000" placeholder="Expliquez clairement pourquoi vous souhaitez contester la sanction."></textarea><button id="send">Envoyer le recours</button><div id="status" class="status"></div></main><script>const token=location.pathname.split('/').pop(),$=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));async function load(){const r=await fetch('/api/appeal/'+encodeURIComponent(token),{cache:'no-store'}),d=await r.json();if(!r.ok){$('status').textContent=d.error||'Lien invalide';$('status').className='status bad';$('send').disabled=true;return}$('server').textContent=d.appeal.guild_name+' / Dossier '+(d.appeal.case_number||'-')+' / '+d.appeal.status;$('reason').textContent=d.appeal.ban_reason;const staff=d.appeal.messages||[];$('history').innerHTML=staff.map(m=>'<p><b>Staff :</b> '+esc(m.content)+'</p>').join('');if(!['awaiting_user','more_info'].includes(d.appeal.status)){$('message').disabled=true;$('send').disabled=true;$('status').textContent='Ce recours a déjà été envoyé ou traité.'}}$('send').onclick=async()=>{const r=await fetch('/api/appeal/'+encodeURIComponent(token),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:$('message').value})}),d=await r.json();if(!r.ok){$('status').textContent=d.error||'Erreur';$('status').className='status bad';return}$('status').textContent='Recours envoyé. Le staff pourra maintenant le traiter.';$('message').disabled=true;$('send').disabled=true};load();</script></body></html>"""


ENTERPRISE_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SentriX / Enterprise</title><style>
:root{--bg:#090b12;--panel:#111522;--panel2:#171c2c;--line:#293149;--text:#f3f5ff;--muted:#9ca6bd;--brand:#786aff;--ok:#42d09a;--bad:#ff6d83;--warn:#f1bd5d}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px system-ui,-apple-system,"Segoe UI",sans-serif}button,input,select,textarea{font:inherit}.top{position:sticky;top:0;z-index:10;padding:14px 3vw;background:#090b12ef;border-bottom:1px solid var(--line);display:flex;gap:10px;justify-content:space-between;align-items:center}.brand{font-weight:900;font-size:18px}.actions{display:flex;gap:8px;align-items:center}.btn{border:1px solid var(--line);background:var(--panel2);color:var(--text);border-radius:10px;padding:9px 12px;font-weight:750;cursor:pointer;text-decoration:none}.btn.primary{background:var(--brand);border-color:transparent}.btn.danger{background:#321620;border-color:#6a3040;color:#ff9bab}.btn:disabled{opacity:.45}main{max-width:1450px;margin:auto;padding:24px}.head{display:grid;grid-template-columns:1fr 320px;gap:14px;align-items:end}.head h1{font-size:31px;margin:0 0 6px}.muted,.head p{color:var(--muted)}select,input,textarea{width:100%;background:#0b0f18;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px}textarea{min-height:90px;resize:vertical}.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:9px;margin:18px 0}.metric,.card{background:var(--panel);border:1px solid var(--line);border-radius:14px}.metric{padding:13px}.metric span{display:block;color:var(--muted);font-size:11px}.metric b{font-size:20px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.card.full{grid-column:1/-1}.card h2{font-size:16px;margin:0}.card-head{padding:15px 16px;border-bottom:1px solid var(--line)}.body{padding:15px 16px}.row{display:flex;gap:8px;align-items:end;flex-wrap:wrap}.field{flex:1 1 150px}.field label{display:block;font-weight:750;margin-bottom:5px}.list{display:grid;gap:7px;max-height:350px;overflow:auto;margin-top:10px}.item{background:#0d111b;border:1px solid #252e45;border-radius:10px;padding:10px;display:flex;gap:8px;justify-content:space-between;align-items:center}.grow{flex:1;min-width:0}.meta{font-size:11px;color:var(--muted);margin-top:4px;overflow-wrap:anywhere}.pill{padding:3px 7px;border:1px solid #32604f;border-radius:999px;color:#93dfc2;font-size:10px}.pill.warn{border-color:#6b5531;color:#f0ce83}.pill.bad{border-color:#6a3040;color:#ff9bab}.switches{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.switch{display:flex;gap:8px;align-items:center;padding:9px;border:1px solid var(--line);border-radius:10px}.switch input{width:auto}.status{margin:12px 0;padding:9px 11px;border:1px solid #32604f;background:#123229;border-radius:10px;color:#97e5c7}.status.bad{border-color:#6a3040;background:#2c141d;color:#ff9bab}.hidden{display:none}.chart{height:130px;display:flex;align-items:end;gap:3px;padding:8px;background:#0b0f18;border:1px solid var(--line);border-radius:10px}.bar{flex:1;min-width:3px;background:#7769ff;border-radius:3px 3px 0 0;opacity:.85}.code{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px}@media(max-width:1000px){.grid,.head{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(3,1fr)}}@media(max-width:620px){main{padding:14px}.metrics{grid-template-columns:repeat(2,1fr)}.switches{grid-template-columns:1fr}.top{padding:10px}.actions{flex-wrap:wrap}}
</style></head><body><header class="top"><div class="brand">SentriX / Enterprise</div><div class="actions"><a class="btn" href="/operations">Operations</a><a class="btn" href="/app">Dashboard</a><button class="btn" id="refresh">Actualiser</button></div></header><main><div class="head"><div><h1>Centre Enterprise</h1><p>Recours, Modmail, automatisations, monitoring, sauvegardes, canary, statistiques et accès dashboard.</p></div><div class="field"><label>Serveur</label><select id="guild"><option>Chargement</option></select></div></div><div id="status" class="status hidden"></div><div class="metrics"><div class="metric"><span>Latence</span><b id="mLatency">-</b></div><div class="metric"><span>Shards</span><b id="mShards">-</b></div><div class="metric"><span>Recours ouverts</span><b id="mAppeals">0</b></div><div class="metric"><span>Modmails ouverts</span><b id="mModmail">0</b></div><div class="metric"><span>Automatisations</span><b id="mAuto">0</b></div><div class="metric"><span>Recommandations</span><b id="mRec">0</b></div></div><div class="grid">
<section class="card"><div class="card-head"><h2>Configuration Enterprise</h2></div><div class="body"><div class="switches"><label class="switch"><input id="sAppeals" type="checkbox"> Recours automatiques</label><label class="switch"><input id="sModmail" type="checkbox"> Modmail</label><label class="switch"><input id="sAuto" type="checkbox"> Automatisations</label><label class="switch"><input id="sBackup" type="checkbox"> Backups automatiques</label></div><div class="field" style="margin-top:10px"><label>Salon staff Modmail / recours</label><select id="modmailChannel"></select></div><button class="btn primary" id="saveSettings" style="margin-top:10px">Enregistrer</button></div></section>
<section class="card"><div class="card-head"><h2>Infrastructure et canary</h2></div><div class="body"><div id="infraList" class="list"></div><button class="btn" id="runCanary" style="margin-top:10px">Relancer le contrôle canary</button></div></section>
<section class="card full"><div class="card-head"><h2>Recours de bannissement</h2></div><div class="body"><div id="appealList" class="list"></div></div></section>
<section class="card full"><div class="card-head"><h2>Modmail</h2></div><div class="body"><div class="row"><div class="field"><label>Conversation</label><select id="modmailThread"></select></div><button class="btn" id="loadModmail">Charger</button><button class="btn danger" id="closeModmail">Fermer</button></div><div id="modmailMessages" class="list"></div><div class="row" style="margin-top:10px"><div class="field"><label>Réponse staff</label><textarea id="modmailReply" maxlength="4000"></textarea></div><button class="btn primary" id="sendModmail">Envoyer</button></div></div></section>
<section class="card full"><div class="card-head"><h2>Automatisations</h2></div><div class="body"><p class="muted">Presets sûrs : nouveaux comptes, seuil de warns, ticket sans réponse, annonce hebdomadaire.</p><div class="row"><div class="field"><label>Preset</label><select id="autoPreset"><option value="new_account">Compte récent vers rôle</option><option value="warns">5 warns vers timeout</option><option value="stale_ticket">Ticket 24 h vers notification</option><option value="weekly">Annonce hebdomadaire</option></select></div><div class="field"><label>ID rôle</label><input id="autoRole" inputmode="numeric"></div><div class="field"><label>ID salon</label><input id="autoChannel" inputmode="numeric"></div><div class="field"><label>Texte</label><input id="autoText" maxlength="1000" placeholder="Message automatique"></div><button class="btn primary" id="autoCreate">Créer</button></div><div id="autoList" class="list"></div></div></section>
<section class="card"><div class="card-head"><h2>Monitoring</h2></div><div class="body"><div id="monitorNow" class="list"></div><div id="metricChart" class="chart"></div></div></section>
<section class="card"><div class="card-head"><h2>Sauvegarde catastrophe</h2></div><div class="body"><button class="btn primary" id="backupCreate">Créer maintenant</button><div id="backupList" class="list"></div></div></section>
<section class="card full"><div class="card-head"><h2>Statistiques et recommandations</h2></div><div class="body"><div class="row"><button class="btn" id="refreshRec">Recalculer les recommandations</button></div><div id="analyticsList" class="list"></div><h3>Salons actifs</h3><div id="channelList" class="list"></div><h3>Giveaways récents</h3><div id="giveawayList" class="list"></div><h3>Activité staff</h3><div id="staffList" class="list"></div></div></section>
<section class="card full"><div class="card-head"><h2>Permissions dashboard par section</h2></div><div class="body"><div class="row"><div class="field"><label>Section</label><select id="accessSection"></select></div><div class="field"><label>Rôle</label><select id="accessRole"></select></div><button class="btn primary" id="accessAdd">Autoriser</button><button class="btn danger" id="accessRemove">Retirer</button></div><div id="accessList" class="list"></div></div></section>
</div></main><script>
const S={csrf:'',guildId:'',guild:null,summary:null,appeals:[],modmail:[],automations:[],monitor:null,backups:[],analytics:null,access:null};const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));const ts=v=>v?new Date(Number(v)*1000).toLocaleString('fr-FR'):'-';async function api(url,o={}){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...o});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||'Une erreur est survenue.');return d}function msg(t,b=false){$('status').textContent=t;$('status').className='status'+(b?' bad':'');$('status').classList.remove('hidden');clearTimeout(msg.t);msg.t=setTimeout(()=>$('status').classList.add('hidden'),4500)}function headers(){return {'Content-Type':'application/json','X-CSRF-Token':S.csrf}}function channels(){return (S.guild?.channels||[]).filter(c=>String(c.type||'').includes('text')||c.type===0)}function roles(){return S.guild?.roles||[]}
async function boot(){try{const me=await api('/api/me');S.csrf=me.csrf;const gs=await api('/api/guilds');const list=gs.guilds.filter(g=>g.installed);$('guild').innerHTML='<option value="">Choisissez un serveur</option>'+list.map(g=>`<option value="${esc(g.id)}">${esc(g.name)}</option>`).join('');const q=new URLSearchParams(location.search),wanted=q.get('guild');const id=list.some(g=>String(g.id)===String(wanted))?wanted:(list[0]?.id||'');if(id){$('guild').value=id;await load(id)}}catch(e){msg(e.message,true)}}
async function load(id){S.guildId=String(id);const b=`/api/guilds/${id}/enterprise`;try{const [guild,summary,appeals,modmail,automations,monitor,backups,analytics]=await Promise.all([api(`/api/guilds/${id}`),api(b+'/summary'),api(b+'/appeals').catch(()=>({appeals:[]})),api(b+'/modmail').catch(()=>({threads:[]})),api(b+'/automations').catch(()=>({rules:[]})),api(b+'/monitoring').catch(()=>({current:{},infra:{},history:[]})),api(b+'/backups').catch(()=>({backups:[]})),api(b+'/analytics').catch(()=>({latest:{},top_channels:[],recommendations:[],giveaways:[],staff_activity:[]}))]);S.guild=guild;S.summary=summary;S.appeals=appeals.appeals||[];S.modmail=modmail.threads||[];S.automations=automations.rules||[];S.monitor=monitor;S.backups=backups.backups||[];S.analytics=analytics;try{S.access=await api(b+'/access')}catch{S.access={sections:summary.sections||{},rules:{}}}render()}catch(e){msg(e.message,true)}}
function render(){const s=S.summary||{},m=s.monitoring?.current||S.monitor?.current||{},c=s.counts||{};$('mLatency').textContent=m.latency_ms==null?'-':m.latency_ms+' ms';$('mShards').textContent=m.shard_count||1;$('mAppeals').textContent=c.appeals||0;$('mModmail').textContent=c.modmail||0;$('mAuto').textContent=c.automations||0;$('mRec').textContent=c.recommendations||0;const set=s.settings||{};$('sAppeals').checked=!!Number(set.appeals_enabled??1);$('sModmail').checked=!!Number(set.modmail_enabled??1);$('sAuto').checked=!!Number(set.automations_enabled??1);$('sBackup').checked=!!Number(set.external_backups_enabled??1);$('modmailChannel').innerHTML='<option value="">Dashboard uniquement</option>'+channels().map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');$('modmailChannel').value=String(set.modmail_channel_id||'');renderInfra();renderAppeals();renderModmail();renderAutomations();renderMonitoring();renderBackups();renderAnalytics();renderAccess()}
function renderInfra(){const i=S.monitor?.infra||S.summary?.monitoring?.infra||{},c=S.monitor?.canary||S.summary?.monitoring?.canary;const rows=[['PostgreSQL',i.postgres_online?'online':(i.postgres_configured?'erreur':'fallback SQLite')],['Redis',i.redis_online?'online':(i.redis_configured?'erreur':'cache local')],['Canary',c?.status||'non configuré']];$('infraList').innerHTML=rows.map(([a,b])=>`<div class="item"><b>${esc(a)}</b><span class="pill ${String(b).includes('erreur')?'bad':''}">${esc(b)}</span></div>`).join('')}
function renderAppeals(){$('appealList').innerHTML=S.appeals.map(a=>`<div class="item"><div class="grow"><b>Utilisateur ${esc(a.user_id)} · dossier ${esc(a.case_number||'-')}</b><div class="meta">${esc(a.ban_reason||'')}<br>${esc(a.status)} · ${ts(a.created_at)}</div></div>${a.status==='open'?`<button class="btn primary" data-appeal="${a.id}:accepted">Accepter</button><button class="btn danger" data-appeal="${a.id}:refused">Refuser</button><button class="btn" data-appeal="${a.id}:more_info">Plus d'informations</button>`:''}</div>`).join('')||'<div class="muted">Aucun recours.</div>';document.querySelectorAll('[data-appeal]').forEach(b=>b.onclick=()=>reviewAppeal(b.dataset.appeal))}
async function reviewAppeal(v){const [id,decision]=v.split(':'),note=prompt('Note staff (optionnelle)')||'';try{await api(`/api/guilds/${S.guildId}/enterprise/appeals/${id}`,{method:'POST',headers:headers(),body:JSON.stringify({decision,note})});msg('Recours mis à jour.');await load(S.guildId)}catch(e){msg(e.message,true)}}
function renderModmail(){$('modmailThread').innerHTML='<option value="">Choisissez</option>'+S.modmail.map(t=>`<option value="${t.id}">#${t.id} · ${esc(t.user_id)} · ${esc(t.status)}</option>`).join('');$('modmailMessages').innerHTML='<div class="muted">Choisissez une conversation.</div>'}
async function loadModmail(){const id=$('modmailThread').value;if(!id)return;try{const d=await api(`/api/guilds/${S.guildId}/enterprise/modmail/${id}`);$('modmailMessages').innerHTML=(d.messages||[]).map(m=>`<div class="item"><div class="grow"><b>${esc(m.direction)} · ${esc(m.author_id)}</b><div class="meta">${esc(m.content)}<br>${ts(m.created_at)}</div></div></div>`).join('')||'<div class="muted">Aucun message.</div>'}catch(e){msg(e.message,true)}}
function preset(){const p=$('autoPreset').value,r=$('autoRole').value,c=$('autoChannel').value,t=$('autoText').value||'Action automatique SentriX';if(p==='new_account')return{name:'Comptes récents',trigger_type:'member_join',conditions:{account_age_days_lt:3},actions:[{type:'add_role',role_id:Number(r)}],cooldown_seconds:30};if(p==='warns')return{name:'Seuil de warns',trigger_type:'warn_threshold',conditions:{min_warns:5},actions:[{type:'timeout',minutes:60}],cooldown_seconds:300};if(p==='stale_ticket')return{name:'Ticket sans réponse',trigger_type:'ticket_stale',conditions:{hours:24},actions:[{type:'notify_role',channel_id:Number(c),role_id:Number(r),content:t}],cooldown_seconds:3600};return{name:'Annonce hebdomadaire',trigger_type:'schedule',conditions:{weekdays:[4],hour:20,minute:0},actions:[{type:'send_channel',channel_id:Number(c),content:t}],cooldown_seconds:3600}}
function renderAutomations(){$('autoList').innerHTML=S.automations.map(r=>`<div class="item"><div class="grow"><b>${esc(r.name)}</b><div class="meta">${esc(r.trigger_type)} · ${r.enabled?'actif':'désactivé'}</div></div><button class="btn danger" data-auto-del="${r.id}">Supprimer</button></div>`).join('')||'<div class="muted">Aucune automatisation.</div>';document.querySelectorAll('[data-auto-del]').forEach(b=>b.onclick=async()=>{try{await api(`/api/guilds/${S.guildId}/enterprise/automations/${b.dataset.autoDel}`,{method:'DELETE',headers:headers()});await load(S.guildId)}catch(e){msg(e.message,true)}})}
function renderMonitoring(){const m=S.monitor?.current||{},hist=S.monitor?.history||[];$('monitorNow').innerHTML=[['RAM',m.ram_mb+' MB'],['Base',m.db_size_mb+' MB'],['Serveurs',m.guilds],['Membres',m.members]].map(x=>`<div class="item"><b>${esc(x[0])}</b><span>${esc(x[1])}</span></div>`).join('');const vals=hist.slice().reverse().map(x=>Number(x.latency_ms||0)),max=Math.max(1,...vals);$('metricChart').innerHTML=vals.map(v=>`<div class="bar" title="${v} ms" style="height:${Math.max(2,Math.round(v/max*100))}%"></div>`).join('')}
function renderBackups(){$('backupList').innerHTML=S.backups.map(b=>`<div class="item"><div class="grow"><b>#${b.id} · ${esc(b.storage)}</b><div class="meta">${Math.round(Number(b.size_bytes||0)/1024)} KB · ${ts(b.created_at)} · ${esc(b.status)}</div></div><button class="btn danger" data-restore="${b.id}">Restaurer</button></div>`).join('')||'<div class="muted">Aucune sauvegarde.</div>';document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=async()=>{if(prompt('Tapez RESTORE pour confirmer')!=='RESTORE')return;try{await api(`/api/guilds/${S.guildId}/enterprise/backups/${b.dataset.restore}/restore`,{method:'POST',headers:headers(),body:JSON.stringify({confirm:'RESTORE'})});msg('Base restaurée.');await load(S.guildId)}catch(e){msg(e.message,true)}})}
function renderAnalytics(){const a=S.analytics||{},x=a.latest||{};$('analyticsList').innerHTML=`<div class="item"><div class="grow"><b>24 h : ${esc(x.joins_24h||0)} arrivées / ${esc(x.leaves_24h||0)} départs</b><div class="meta">Tickets ouverts ${esc(x.tickets_open||0)} · sanctions ${esc(x.sanctions_24h||0)} · AutoMod ${esc(x.automod_24h||0)} · commandes ${esc(x.commands_24h||0)}</div></div></div>`+(a.recommendations||[]).map(r=>`<div class="item"><div class="grow"><b>${esc(r.title)}</b><div class="meta">${esc(r.details)}</div></div><span class="pill ${r.severity==='critical'?'bad':r.severity==='warning'?'warn':''}">${esc(r.severity)}</span></div>`).join('');$('channelList').innerHTML=(a.top_channels||[]).map(c=>`<div class="item"><b>${esc(c.name)}</b><span>${esc(c.messages)} messages</span></div>`).join('')||'<div class="muted">Pas encore assez de données.</div>';$('giveawayList').innerHTML=(a.giveaways||[]).map(g=>`<div class="item"><div class="grow"><b>${esc(g.prize||('Giveaway '+g.id))}</b><div class="meta">${esc(g.entries)} participation(s) · ${esc(g.status)}</div></div></div>`).join('')||'<div class="muted">Aucun giveaway récent.</div>';$('staffList').innerHTML=(a.staff_activity||[]).map(s=>`<div class="item"><b>Staff ${esc(s.moderator_id)}</b><span>${esc(s.actions)} sanction(s)</span></div>`).join('')||'<div class="muted">Aucune sanction récente.</div>'}
function renderAccess(){const a=S.access||{sections:S.summary?.sections||{},rules:{}};$('accessSection').innerHTML=Object.entries(a.sections||{}).map(([k,v])=>`<option value="${esc(k)}">${esc(v)}</option>`).join('');$('accessRole').innerHTML=roles().filter(r=>r.name!=='@everyone').map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('');const lines=[];for(const [s,ids] of Object.entries(a.rules||{})){if(!ids.length)continue;lines.push(`<div class="item"><div class="grow"><b>${esc(a.sections?.[s]||s)}</b><div class="meta">${ids.map(id=>esc(roles().find(r=>String(r.id)===String(id))?.name||id)).join(', ')}</div></div></div>`)}$('accessList').innerHTML=lines.join('')||'<div class="muted">Aucune restriction supplémentaire.</div>'}
$('guild').onchange=()=>load($('guild').value);$('refresh').onclick=()=>load(S.guildId);$('saveSettings').onclick=async()=>{try{await api(`/api/guilds/${S.guildId}/enterprise/settings`,{method:'PUT',headers:headers(),body:JSON.stringify({appeals_enabled:$('sAppeals').checked,modmail_enabled:$('sModmail').checked,automations_enabled:$('sAuto').checked,external_backups_enabled:$('sBackup').checked,modmail_channel_id:$('modmailChannel').value||null})});msg('Configuration enregistrée.');await load(S.guildId)}catch(e){msg(e.message,true)}};$('loadModmail').onclick=loadModmail;$('sendModmail').onclick=async()=>{const id=$('modmailThread').value;if(!id)return;try{await api(`/api/guilds/${S.guildId}/enterprise/modmail/${id}/reply`,{method:'POST',headers:headers(),body:JSON.stringify({message:$('modmailReply').value})});$('modmailReply').value='';await loadModmail()}catch(e){msg(e.message,true)}};$('closeModmail').onclick=async()=>{const id=$('modmailThread').value;if(!id)return;try{await api(`/api/guilds/${S.guildId}/enterprise/modmail/${id}/status`,{method:'POST',headers:headers(),body:JSON.stringify({status:'closed'})});await load(S.guildId)}catch(e){msg(e.message,true)}};$('autoCreate').onclick=async()=>{try{await api(`/api/guilds/${S.guildId}/enterprise/automations`,{method:'PUT',headers:headers(),body:JSON.stringify(preset())});msg('Automatisation créée.');await load(S.guildId)}catch(e){msg(e.message,true)}};$('backupCreate').onclick=async()=>{try{await api(`/api/guilds/${S.guildId}/enterprise/backups`,{method:'POST',headers:headers(),body:'{}'});msg('Sauvegarde créée.');await load(S.guildId)}catch(e){msg(e.message,true)}};$('runCanary').onclick=async()=>{try{const d=await api(`/api/guilds/${S.guildId}/enterprise/canary`,{method:'POST',headers:headers(),body:'{}'});msg('Canary : '+d.canary.status);await load(S.guildId)}catch(e){msg(e.message,true)}};$('refreshRec').onclick=async()=>{try{await api(`/api/guilds/${S.guildId}/enterprise/recommendations`,{method:'POST',headers:headers(),body:'{}'});await load(S.guildId)}catch(e){msg(e.message,true)}};async function setAccess(enabled){try{await api(`/api/guilds/${S.guildId}/enterprise/access`,{method:'PUT',headers:headers(),body:JSON.stringify({section:$('accessSection').value,role_id:$('accessRole').value,enabled})});await load(S.guildId)}catch(e){msg(e.message,true)}}$('accessAdd').onclick=()=>setAccess(true);$('accessRemove').onclick=()=>setAccess(false);boot();
</script></body></html>"""
