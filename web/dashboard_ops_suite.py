"""Operational dashboard suite for SentriX.

Adds advanced dashboard-only operations without changing the visual identity of the main UI.
The module is intentionally late-bound and idempotent so it can be installed by the Railway
HA entrypoint after the existing product layers.
"""
from __future__ import annotations

import json
import logging
import time
from types import MethodType

from aiohttp import web
from discord.ext import commands

logger = logging.getLogger("bot.dashboard.ops-suite")
_INSTALLED = False

OPS_CSS = r'''
<style id="sentrix-ops-suite-css">
  .sx-ops-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.sx-ops-card{border:1px solid var(--line,#29304a);border-radius:14px;background:var(--panel,#111522);padding:15px}.sx-ops-card.full{grid-column:1/-1}.sx-ops-card h3{margin:0 0 8px;font-size:14px}.sx-ops-card p{margin:0;color:var(--muted,#949db5);font-size:12px;line-height:1.5}.sx-ops-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px}.sx-ops-list{display:grid;gap:8px;margin-top:10px}.sx-ops-item{border:1px solid var(--line,#29304a);border-radius:10px;padding:10px;background:#0b101a}.sx-ops-item b{font-size:12px}.sx-ops-item small{display:block;color:var(--muted,#949db5);margin-top:3px;line-height:1.4}.sx-ops-badge{display:inline-flex;border:1px solid var(--line,#29304a);border-radius:999px;padding:4px 7px;font-size:10px;font-weight:800}.sx-ops-badge.ok{color:#8ee6bd}.sx-ops-badge.warn{color:#f0c66c}.sx-ops-badge.bad{color:#ff9aaa}.sx-ops-input,.sx-ops-select,.sx-ops-textarea{width:100%;border:1px solid var(--line,#29304a);border-radius:9px;background:#0a0e18;color:var(--text,#f3f5ff);padding:9px 10px}.sx-ops-textarea{min-height:110px;resize:vertical}.sx-ops-table{width:100%;border-collapse:collapse;margin-top:8px}.sx-ops-table th,.sx-ops-table td{text-align:left;padding:8px;border-bottom:1px solid var(--line,#29304a);font-size:11px}.sx-unsaved{display:none;font-size:10px;font-weight:800;color:#f0c66c;margin-left:8px}.sx-unsaved.show{display:inline-flex}.sx-action-queue{position:fixed;right:16px;bottom:16px;z-index:220;width:min(360px,calc(100vw - 32px));display:grid;gap:8px;pointer-events:none}.sx-action{pointer-events:auto;border:1px solid var(--line,#29304a);border-radius:11px;background:#0d121c;padding:10px 12px;box-shadow:0 14px 40px #0007}.sx-action b{font-size:11px}.sx-action small{display:block;color:var(--muted,#949db5);margin-top:3px}.sx-ops-check{display:flex;gap:8px;align-items:flex-start}.sx-ops-check input{margin-top:2px}@media(max-width:800px){.sx-ops-grid{grid-template-columns:1fr}.sx-ops-card.full{grid-column:auto}}
</style>
'''

OPS_JS = r'''
<script id="sentrix-ops-suite-js">
(() => {
  "use strict";
  if (window.__sentrixOpsSuite) return;
  window.__sentrixOpsSuite = true;
  const byId = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const S = () => { try { return typeof state !== "undefined" ? state : null; } catch (_) { return null; } };
  const guildId = () => String(S()?.guildId || byId("serverSelect")?.value || "").replace(/^invite:/,"");
  const csrf = () => String(S()?.csrf || "");
  const api = async (url, options={}) => {
    const headers = {...(options.headers||{})};
    if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrf();
    if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(url,{credentials:"same-origin",cache:"no-store",...options,headers});
    let data={}; try{data=await response.json()}catch(_){}
    if(!response.ok) throw new Error(data.error||`Erreur HTTP ${response.status}`);
    return data;
  };
  const queue = (()=>{let node=byId("sxActionQueue");if(!node){node=document.createElement("div");node.id="sxActionQueue";node.className="sx-action-queue";document.body.appendChild(node)}return node})();
  function action(label,promise){const item=document.createElement("div");item.className="sx-action";item.innerHTML=`<b>${esc(label)}</b><small>En cours…</small>`;queue.appendChild(item);return promise.then(v=>{item.querySelector("small").textContent="Terminé";setTimeout(()=>item.remove(),2200);return v},e=>{item.querySelector("small").textContent=e.message||"Erreur";setTimeout(()=>item.remove(),5000);throw e})}

  function installDirtyGuard(){const badge=document.createElement("span");badge.id="sxUnsavedBadge";badge.className="sx-unsaved";badge.textContent="Modifications non enregistrées";byId("saveBar")?.appendChild(badge);document.addEventListener("input",e=>{if(e.target.closest("#fields")){badge.classList.add("show");const s=S();if(s)s.dirty=true}},true);document.addEventListener("change",e=>{if(e.target.closest("#fields")){badge.classList.add("show");const s=S();if(s)s.dirty=true}},true);byId("saveButton")?.addEventListener("click",()=>setTimeout(()=>{if(!S()?.dirty)badge.classList.remove("show")},350));window.addEventListener("beforeunload",e=>{if(S()?.dirty){e.preventDefault();e.returnValue=""}})}

  function improveSearch(){const input=byId("globalSearch")||byId("paletteInput")||byId("sentrixNavSearch");if(!input)return;input.addEventListener("input",()=>{const q=input.value.trim().toLocaleLowerCase("fr");if(!q)return;let best=null;for(const [name,tab] of Object.entries(window.tabs||{})){const hay=[name,tab?.title,tab?.description,...(tab?.fields||[]).flatMap(f=>[f.key,f.label])].filter(Boolean).join(" ").toLocaleLowerCase("fr");if(hay.includes(q)){best=name;break}}if(best){document.querySelector(`[data-tab="${CSS.escape(best)}"]`)?.classList.add("sx-search-hit");setTimeout(()=>document.querySelector(`[data-tab="${CSS.escape(best)}"]`)?.classList.remove("sx-search-hit"),1000)}})}

  function checklist(data){const cfg=data?.guild_data?.settings||S()?.guildData?.settings||{};const automod=data?.guild_data?.automod||S()?.guildData?.automod||{};const items=[
    ["Salon de logs",Boolean(cfg.log_channel||cfg.log_moderation)],
    ["Tickets",Boolean(cfg.ticket_category||cfg.ticket_log_channel)],
    ["Vérification",Boolean(cfg.verification_channel&& (cfg.verification_role||cfg.verify_role))],
    ["Sécurité",Object.values(automod).some(v=>Number(v)===1)],
    ["Accueil",Boolean(cfg.welcome_channel)],
    ["Rôle staff",Boolean(cfg.mod_role||cfg.admin_role)]
  ];return items.map(([label,ok])=>`<label class="sx-ops-check"><input type="checkbox" disabled ${ok?"checked":""}><span>${esc(label)}</span></label>`).join("")}

  async function loadOps(){const id=guildId();if(!id)return;const fields=byId("fields");if(!fields)return;fields.innerHTML='<div class="sx-ops-card"><p>Chargement des opérations…</p></div>';try{const data=await api(`/api/guilds/${encodeURIComponent(id)}/ops/overview`);const d=data.diagnostics||[];const hist=data.history||[];const staff=data.staff||[];const policies=data.policies||[];const maintenance=data.maintenance||{};fields.innerHTML=`<div class="sx-ops-grid full">
    <section class="sx-ops-card"><h3>État temps réel</h3><div class="sx-ops-list"><div class="sx-ops-item"><b>Discord</b><small>${data.status?.discord_ready?"En ligne":"Hors ligne"} · ${data.status?.latency_ms??"—"} ms</small></div><div class="sx-ops-item"><b>Permissions SentriX</b><small>${esc((data.status?.bot_permissions||[]).join(", ")||"Aucune permission critique manquante")}</small></div></div></section>
    <section class="sx-ops-card"><h3>Onboarding</h3><div class="sx-ops-list">${checklist(data)}</div></section>
    <section class="sx-ops-card full"><h3>Diagnostic automatique</h3><div class="sx-ops-row"><button class="btn" id="sxRepairSafe">Réparer automatiquement ce qui est sûr</button><span class="sx-ops-badge ${d.some(x=>x.severity==='error')?'bad':d.length?'warn':'ok'}">${d.length?`${d.length} point(s) détecté(s)`:"Aucun problème détecté"}</span></div><div class="sx-ops-list">${d.length?d.map(x=>`<div class="sx-ops-item"><b>${esc(x.title)}</b><small>${esc(x.message)}</small></div>`).join(""):'<div class="sx-ops-item"><b>Configuration saine</b><small>Aucune référence cassée ni permission critique manquante détectée.</small></div>'}</div></section>
    <section class="sx-ops-card"><h3>Mode maintenance</h3><input id="sxMaintenanceReason" class="sx-ops-input" maxlength="180" placeholder="Raison affichée au staff" value="${esc(maintenance.reason||"")}"><div class="sx-ops-row"><button class="btn ${maintenance.enabled?'danger':'primary'}" id="sxMaintenanceToggle">${maintenance.enabled?'Désactiver':'Activer'} la maintenance</button></div></section>
    <section class="sx-ops-card"><h3>Commandes par salon</h3><input id="sxPolicyCommand" class="sx-ops-input" placeholder="Commande, ex. moderation ban"><select id="sxPolicyChannel" class="sx-ops-select"><option value="0">Tous les salons</option>${(S()?.guildData?.channels||[]).map(c=>`<option value="${esc(c.id)}"># ${esc(c.name)}</option>`).join("")}</select><div class="sx-ops-row"><button class="btn" id="sxPolicyDisable">Désactiver</button><button class="btn" id="sxPolicyEnable">Réactiver</button></div><div class="sx-ops-list">${policies.slice(0,8).map(p=>`<div class="sx-ops-item"><b>${esc(p.command_name)}</b><small>${p.channel_id?`Salon ${esc(p.channel_id)}`:"Tous les salons"} · ${p.enabled?"autorisé":"bloqué"}</small></div>`).join("")||'<div class="sx-ops-item"><small>Aucune règle personnalisée.</small></div>'}</div></section>
    <section class="sx-ops-card full"><h3>Import / export / duplication</h3><textarea id="sxConfigJson" class="sx-ops-textarea" placeholder="Export JSON ou configuration à importer"></textarea><div class="sx-ops-row"><button class="btn" id="sxExportConfig">Exporter</button><button class="btn" id="sxImportConfig">Importer</button><select id="sxCloneTarget" class="sx-ops-select" style="width:auto;min-width:220px"><option value="">Copier vers…</option>${(S()?.guilds||[]).filter(g=>g.installed&&String(g.id)!==id).map(g=>`<option value="${esc(g.id)}">${esc(g.name)}</option>`).join("")}</select><button class="btn" id="sxCloneConfig">Dupliquer</button></div></section>
    <section class="sx-ops-card full"><h3>Historique et rollback</h3><table class="sx-ops-table"><thead><tr><th>Date</th><th>Utilisateur</th><th>Changements</th><th></th></tr></thead><tbody>${hist.slice(0,12).map(h=>`<tr><td>${new Date((h.created_at||0)*1000).toLocaleString("fr-FR")}</td><td>${esc(h.username||h.user_id)}</td><td>${esc((h.changed_keys||[]).join(", ")||"configuration")}</td><td><button class="btn" data-rollback="${h.id}">Restaurer</button></td></tr>`).join("")||'<tr><td colspan="4">Aucun historique enregistré.</td></tr>'}</tbody></table></section>
    <section class="sx-ops-card full"><h3>Activité staff</h3><table class="sx-ops-table"><thead><tr><th>Utilisateur</th><th>Commandes 24 h</th></tr></thead><tbody>${staff.slice(0,15).map(s=>`<tr><td>${esc(s.user_id)}</td><td>${Number(s.actions||0).toLocaleString("fr-FR")}</td></tr>`).join("")||'<tr><td colspan="2">Aucune donnée staff disponible.</td></tr>'}</tbody></table></section>
  </div>`;wireOps(id)}catch(e){fields.innerHTML=`<div class="sx-ops-card"><h3>Opérations indisponibles</h3><p>${esc(e.message)}</p></div>`}}

  function wireOps(id){byId("sxRepairSafe")?.addEventListener("click",()=>action("Réparation du diagnostic",api(`/api/guilds/${id}/ops/repair`,{method:"POST",body:"{}"})).then(loadOps).catch(e=>window.toast?.(e.message,true)));byId("sxMaintenanceToggle")?.addEventListener("click",()=>action("Mise à jour maintenance",api(`/api/guilds/${id}/ops/maintenance`,{method:"POST",body:JSON.stringify({enabled:!byId("sxMaintenanceToggle").classList.contains("danger"),reason:byId("sxMaintenanceReason").value})})).then(loadOps).catch(e=>window.toast?.(e.message,true)));const policy=enabled=>{const command=byId("sxPolicyCommand").value.trim();if(!command)return window.toast?.("Indique une commande.",true);return action("Mise à jour politique de commande",api(`/api/guilds/${id}/ops/policies`,{method:"POST",body:JSON.stringify({command_name:command,channel_id:Number(byId("sxPolicyChannel").value)||null,enabled})})).then(loadOps).catch(e=>window.toast?.(e.message,true))};byId("sxPolicyDisable")?.addEventListener("click",()=>policy(false));byId("sxPolicyEnable")?.addEventListener("click",()=>policy(true));byId("sxExportConfig")?.addEventListener("click",()=>action("Export de configuration",api(`/api/guilds/${id}/ops/export`)).then(data=>{byId("sxConfigJson").value=JSON.stringify(data.config,null,2)}).catch(e=>window.toast?.(e.message,true)));byId("sxImportConfig")?.addEventListener("click",()=>{let config;try{config=JSON.parse(byId("sxConfigJson").value)}catch{return window.toast?.("JSON invalide.",true)}action("Import de configuration",api(`/api/guilds/${id}/ops/import`,{method:"POST",body:JSON.stringify(config)})).then(async()=>{await window.selectGuild?.(id);await loadOps()}).catch(e=>window.toast?.(e.message,true))});byId("sxCloneConfig")?.addEventListener("click",()=>{const target=byId("sxCloneTarget").value;if(!target)return window.toast?.("Choisis un serveur cible.",true);action("Duplication de configuration",api(`/api/guilds/${id}/ops/clone/${target}`,{method:"POST",body:"{}"})).then(()=>window.toast?.("Configuration copiée." )).catch(e=>window.toast?.(e.message,true))});document.querySelectorAll("[data-rollback]").forEach(btn=>btn.addEventListener("click",()=>action("Rollback de configuration",api(`/api/guilds/${id}/ops/history/${btn.dataset.rollback}/rollback`,{method:"POST",body:"{}"})).then(async()=>{await window.selectGuild?.(id);await loadOps()}).catch(e=>window.toast?.(e.message,true))))}

  function installTab(){if(typeof tabs==="undefined"||typeof renderTab!=="function")return false;if(!tabs.ops)tabs.ops={title:"Opérations",description:"Diagnostic, historique, maintenance, politiques de commandes et sauvegardes.",readonly:true,fields:[]};const nav=byId("navigation");if(nav&&!nav.querySelector('[data-tab="ops"]')){const b=document.createElement("button");b.type="button";b.dataset.tab="ops";b.textContent="Opérations";nav.appendChild(b)}const original=renderTab;if(!original.__sxOpsWrapped){renderTab=function(){if(S()?.tab==="ops"){byId("tabTitle").textContent="Opérations";byId("tabDescription").textContent=tabs.ops.description;byId("saveBar")?.classList.add("hidden");loadOps();return}return original()};renderTab.__sxOpsWrapped=true}return true}

  const start=()=>{installDirtyGuard();improveSearch();let tries=0;const timer=setInterval(()=>{tries++;if(installTab()||tries>40)clearInterval(timer)},250)};if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
</script>
'''


def _row_dict(row):
    return dict(row) if row else {}


async def _ensure_tables(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            snapshot_json TEXT NOT NULL,
            changed_json TEXT NOT NULL
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_maintenance (
            guild_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_command_policy (
            guild_id INTEGER NOT NULL,
            command_name TEXT NOT NULL,
            channel_id INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, command_name, channel_id)
        )
    """)


async def _snapshot(dashboard, db, guild_id: int) -> dict:
    conf = await db.get_guild_config(guild_id)
    automod = await db.get_automod(guild_id)
    ai = await db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,))
    return {"settings": _row_dict(conf), "automod": _row_dict(automod), "ai": _row_dict(ai)}


async def _record_history(dashboard, request: web.Request, guild_id: int, before: dict, changed: list[str]) -> None:
    db = request.app["bot"].db
    await _ensure_tables(db)
    session = dashboard._session(request) or {}
    user = session.get("user") or {}
    await db.execute(
        "INSERT INTO sentrix_dashboard_history (guild_id,user_id,username,created_at,snapshot_json,changed_json) VALUES (?,?,?,?,?,?)",
        (guild_id, int(user.get("id") or 0), str(user.get("username") or "Dashboard"), int(time.time()), json.dumps(before, ensure_ascii=False), json.dumps(changed, ensure_ascii=False)),
    )
    await db.execute("DELETE FROM sentrix_dashboard_history WHERE guild_id = ? AND id NOT IN (SELECT id FROM sentrix_dashboard_history WHERE guild_id = ? ORDER BY id DESC LIMIT 50)", (guild_id, guild_id))


def _critical_permissions(guild) -> list[str]:
    me = guild.me
    if me is None:
        return ["Bot absent du cache Discord"]
    p = me.guild_permissions
    missing = []
    checks = [("manage_roles","Gérer les rôles"),("manage_channels","Gérer les salons"),("ban_members","Bannir"),("moderate_members","Exclure temporairement"),("view_audit_log","Voir les logs d'audit")]
    for attr, label in checks:
        if not getattr(p, attr, False):
            missing.append(label)
    return missing


async def _diagnostics(dashboard, db, guild) -> list[dict]:
    conf = _row_dict(await db.get_guild_config(guild.id))
    issues = []
    for field in getattr(dashboard, "ROLE_FIELDS", set()):
        value = conf.get(field)
        if value and guild.get_role(int(value)) is None:
            issues.append({"severity":"error","title":"Rôle supprimé","message":f"{field} pointe vers un rôle qui n'existe plus.","field":field,"kind":"setting"})
    for field in set(getattr(dashboard, "CHANNEL_FIELDS", set())) | {"ticket_category"}:
        value = conf.get(field)
        if value and guild.get_channel(int(value)) is None:
            issues.append({"severity":"error","title":"Salon supprimé","message":f"{field} pointe vers un salon qui n'existe plus.","field":field,"kind":"setting"})
    missing = _critical_permissions(guild)
    if missing:
        issues.append({"severity":"warning","title":"Permissions SentriX incomplètes","message":"Permissions manquantes : " + ", ".join(missing)})
    if not conf.get("log_channel") and not conf.get("log_moderation"):
        issues.append({"severity":"warning","title":"Aucun log principal","message":"Configure un salon de logs généraux ou de modération."})
    if conf.get("ticket_category") and not conf.get("ticket_log_channel"):
        issues.append({"severity":"warning","title":"Tickets sans logs","message":"Les tickets sont configurés mais aucun salon de logs ticket n'est défini."})
    channel_fields = [f for f in getattr(dashboard, "CHANNEL_FIELDS", set()) if conf.get(f)]
    used = {}
    for field in channel_fields:
        used.setdefault(str(conf[field]), []).append(field)
    for names in used.values():
        if len(names) >= 5:
            issues.append({"severity":"warning","title":"Concentration de configuration","message":"Beaucoup de modules utilisent le même salon : " + ", ".join(sorted(names)[:7])})
    return issues


async def _require_manageable(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        return None, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    return guild_id, session, guild, error


def _csrf(dashboard, request, session):
    return dashboard._require_csrf(request, session)


async def _staff_activity(db, guild_id: int) -> list[dict]:
    candidates = [
        "SELECT user_id, COUNT(*) AS actions FROM command_logs WHERE guild_id = ? AND timestamp >= ? GROUP BY user_id ORDER BY actions DESC LIMIT 25",
        "SELECT author_id AS user_id, COUNT(*) AS actions FROM command_logs WHERE guild_id = ? AND timestamp >= ? GROUP BY author_id ORDER BY actions DESC LIMIT 25",
    ]
    for query in candidates:
        try:
            rows = await db.fetchall(query, (guild_id, int(time.time()) - 86400))
            return [dict(row) for row in rows]
        except Exception:
            continue
    return []


async def _history(db, guild_id: int) -> list[dict]:
    try:
        rows = await db.fetchall("SELECT id,user_id,username,created_at,changed_json FROM sentrix_dashboard_history WHERE guild_id = ? ORDER BY id DESC LIMIT 30", (guild_id,))
    except Exception:
        return []
    result=[]
    for row in rows:
        item=dict(row)
        try:item["changed_keys"]=json.loads(item.pop("changed_json") or "[]")
        except Exception:item["changed_keys"]=[]
        result.append(item)
    return result


async def _maintenance(db, guild_id: int) -> dict:
    try:
        row = await db.fetchone("SELECT enabled,reason,updated_by,updated_at FROM sentrix_dashboard_maintenance WHERE guild_id = ?", (guild_id,))
        if row:
            item=dict(row);item["enabled"]=bool(item.get("enabled"));return item
    except Exception:
        pass
    return {"enabled":False,"reason":""}


async def _policies(db, guild_id: int) -> list[dict]:
    try:
        rows=await db.fetchall("SELECT command_name,channel_id,enabled,updated_by,updated_at FROM sentrix_dashboard_command_policy WHERE guild_id = ? ORDER BY updated_at DESC LIMIT 50",(guild_id,))
        out=[]
        for row in rows:
            item=dict(row);item["enabled"]=bool(item.get("enabled"));item["channel_id"]=item.get("channel_id") or None;out.append(item)
        return out
    except Exception:
        return []


def install(dashboard) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        from web import dashboard_control_center
        dashboard_control_center.install(dashboard)
    except Exception:
        logger.exception("Existing control center could not be installed; continuing with ops suite.")

    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-ops-suite-css"' not in html:
        html = html.replace("</head>", OPS_CSS + "\n</head>", 1)
    if 'id="sentrix-ops-suite-js"' not in html:
        html = html.replace("</body>", OPS_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html

    original_update = dashboard.handle_update_guild
    if not getattr(original_update, "_sentrix_ops_history", False):
        async def update_with_history(request: web.Request):
            try:
                guild_id=int(request.match_info["guild_id"])
                before=await _snapshot(dashboard, request.app["bot"].db, guild_id)
                payload=await request.json()
                changed=list((payload.get("settings") or {}).keys())+list((payload.get("automod") or {}).keys())+list((payload.get("ai") or {}).keys())
            except Exception:
                before={};changed=[];guild_id=0
            response=await original_update(request)
            if guild_id and getattr(response,"status",500)<300 and before:
                try: await _record_history(dashboard, request, guild_id, before, changed)
                except Exception: logger.exception("Unable to record dashboard history.")
            return response
        update_with_history._sentrix_ops_history=True
        dashboard.handle_update_guild=update_with_history

    original_build = dashboard.build_app
    if not getattr(original_build, "_sentrix_ops_routes", False):
        def build_app_with_ops(bot):
            app=original_build(bot)

            async def overview(request):
                guild_id,session,guild,error=await _require_manageable(dashboard,request)
                if error:return error
                db=bot.db;await _ensure_tables(db)
                guild_data=await dashboard._assemble_guild_payload(db,guild)
                return web.json_response({"ok":True,"status":{"discord_ready":bot.is_ready(),"latency_ms":round(bot.latency*1000) if bot.is_ready() else None,"bot_permissions":_critical_permissions(guild)},"diagnostics":await _diagnostics(dashboard,db,guild),"history":await _history(db,guild_id),"staff":await _staff_activity(db,guild_id),"maintenance":await _maintenance(db,guild_id),"policies":await _policies(db,guild_id),"guild_data":guild_data})

            async def export_config(request):
                guild_id,session,guild,error=await _require_manageable(dashboard,request)
                if error:return error
                return web.json_response({"ok":True,"config":await _snapshot(dashboard,bot.db,guild_id)})

            async def import_config(request):
                guild_id,session,guild,error=await _require_manageable(dashboard,request)
                if error:return error
                csrf=_csrf(dashboard,request,session)
                if csrf:return csrf
                try: payload=await request.json()
                except Exception:return dashboard._json_error("JSON de configuration invalide.",400)
                settings=payload.get("settings") or {};automod=payload.get("automod") or {};ai=payload.get("ai") or {}
                clean_settings,msg=dashboard._validate_settings(guild,settings)
                if msg:return dashboard._json_error(msg,400)
                clean_ai,msg=dashboard._validate_ai(ai)
                if msg:return dashboard._json_error(msg,400)
                for k,v in automod.items():
                    if k not in dashboard.AUTOMOD_FIELDS or v not in (True,False,0,1):return dashboard._json_error(f"Réglage AutoMod {k} invalide.",400)
                db=bot.db;before=await _snapshot(dashboard,db,guild_id)
                for k,v in clean_settings.items():await db.set_guild_config(guild_id,k,v)
                for k,v in automod.items():await db.set_automod(guild_id,k,int(bool(v)))
                if clean_ai:
                    await db.execute("INSERT OR IGNORE INTO ai_settings (guild_id, updated_at) VALUES (?, ?)",(guild_id,int(time.time())))
                    for k,v in clean_ai.items():await db.execute(f"UPDATE ai_settings SET {k} = ?, updated_at = ? WHERE guild_id = ?",(v,int(time.time()),guild_id))
                await _record_history(dashboard,request,guild_id,before,list(clean_settings)+list(automod)+list(clean_ai))
                return web.json_response({"ok":True,"message":"Configuration importée."})

            async def clone_config(request):
                source_id,session,source,error=await _require_manageable(dashboard,request)
                if error:return error
                csrf=_csrf(dashboard,request,session)
                if csrf:return csrf
                try: target_id=int(request.match_info["target_id"])
                except ValueError:return dashboard._json_error("Serveur cible invalide.",400)
                fake=request.clone(rel_url=request.rel_url.with_path(f"/api/guilds/{target_id}"))
                fake._match_info={"guild_id":str(target_id)}
                _,target,target_error=await dashboard._manageable_guild(fake,target_id)
                if target_error:return dashboard._json_error("Tu dois aussi administrer le serveur cible.",403)
                snap=await _snapshot(dashboard,bot.db,source_id);clean_settings,msg=dashboard._validate_settings(target,snap.get("settings") or {})
                if msg:return dashboard._json_error("La configuration source contient une référence incompatible avec le serveur cible. Utilise export/import pour l'ajuster.",409)
                before=await _snapshot(dashboard,bot.db,target_id)
                for k,v in clean_settings.items():await bot.db.set_guild_config(target_id,k,v)
                for k,v in (snap.get("automod") or {}).items():
                    if k in dashboard.AUTOMOD_FIELDS:await bot.db.set_automod(target_id,k,int(bool(v)))
                await _record_history(dashboard,request,target_id,before,list(clean_settings)+(list((snap.get("automod") or {}).keys())))
                return web.json_response({"ok":True,"message":"Configuration dupliquée."})

            async def rollback(request):
                guild_id,session,guild,error=await _require_manageable(dashboard,request)
                if error:return error
                csrf=_csrf(dashboard,request,session)
                if csrf:return csrf
                try: history_id=int(request.match_info["history_id"])
                except ValueError:return dashboard._json_error("Historique invalide.",400)
                await _ensure_tables(bot.db)
                row=await bot.db.fetchone("SELECT snapshot_json FROM sentrix_dashboard_history WHERE id = ? AND guild_id = ?",(history_id,guild_id))
                if not row:return dashboard._json_error("Version d'historique introuvable.",404)
                try:snap=json.loads(row["snapshot_json"])
                except Exception:return dashboard._json_error("Historique corrompu.",500)
                before=await _snapshot(dashboard,bot.db,guild_id)
                clean_settings,msg=dashboard._validate_settings(guild,snap.get("settings") or {})
                if msg:return dashboard._json_error(msg,409)
                clean_ai,msg=dashboard._validate_ai({k:v for k,v in (snap.get("ai") or {}).items() if k in dashboard.AI_BOOL_FIELDS or k in dashboard.AI_INT_FIELDS or k in dashboard.AI_CHOICE_FIELDS})
                if msg:return dashboard._json_error(msg,409)
                for k,v in clean_settings.items():await bot.db.set_guild_config(guild_id,k,v)
                for k,v in (snap.get("automod") or {}).items():
                    if k in dashboard.AUTOMOD_FIELDS:await bot.db.set_automod(guild_id,k,int(bool(v)))
                if clean_ai:
                    await bot.db.execute("INSERT OR IGNORE INTO ai_settings (guild_id, updated_at) VALUES (?, ?)",(guild_id,int(time.time())))
                    for k,v in clean_ai.items():await bot.db.execute(f"UPDATE ai_settings SET {k} = ?, updated_at = ? WHERE guild_id = ?",(v,int(time.time()),guild_id))
                await _record_history(dashboard,request,guild_id,before,["rollback"])
                return web.json_response({"ok":True,"message":"Configuration restaurée."})

            async def repair(request):
                guild_id,session,guild,error=await _require_manageable(dashboard,request)
                if error:return error
                csrf=_csrf(dashboard,request,session)
                if csrf:return csrf
                db=bot.db;conf=_row_dict(await db.get_guild_config(guild_id));before=await _snapshot(dashboard,db,guild_id);fixed=[]
                for field in getattr(dashboard,"ROLE_FIELDS",set()):
                    value=conf.get(field)
                    if value and guild.get_role(int(value)) is None:await db.set_guild_config(guild_id,field,None);fixed.append(field)
                for field in set(getattr(dashboard,"CHANNEL_FIELDS",set()))|{"ticket_category"}:
                    value=conf.get(field)
                    if value and guild.get_channel(int(value)) is None:await db.set_guild_config(guild_id,field,None);fixed.append(field)
                if fixed:await _record_history(dashboard,request,guild_id,before,fixed)
                return web.json_response({"ok":True,"fixed":fixed,"message":f"{len(fixed)} référence(s) cassée(s) corrigée(s)."})

            async def maintenance(request):
                guild_id,session,guild,error=await _require_manageable(dashboard,request)
                if error:return error
                csrf=_csrf(dashboard,request,session)
                if csrf:return csrf
                try: payload=await request.json()
                except Exception:payload={}
                enabled=1 if payload.get("enabled") else 0;reason=str(payload.get("reason") or "Maintenance SentriX").strip()[:180]
                await _ensure_tables(bot.db);user_id=int(session["user"]["id"])
                await bot.db.execute("INSERT INTO sentrix_dashboard_maintenance (guild_id,enabled,reason,updated_by,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,reason=excluded.reason,updated_by=excluded.updated_by,updated_at=excluded.updated_at",(guild_id,enabled,reason,user_id,int(time.time())))
                return web.json_response({"ok":True,"enabled":bool(enabled),"reason":reason})

            async def policies(request):
                guild_id,session,guild,error=await _require_manageable(dashboard,request)
                if error:return error
                csrf=_csrf(dashboard,request,session)
                if csrf:return csrf
                try: payload=await request.json()
                except Exception:return dashboard._json_error("Formulaire invalide.",400)
                name=str(payload.get("command_name") or "").strip().lower()[:120]
                if not name:return dashboard._json_error("Indique une commande.",400)
                channel_id=int(payload.get("channel_id") or 0);enabled=1 if payload.get("enabled") else 0
                if channel_id and guild.get_channel(channel_id) is None:return dashboard._json_error("Salon introuvable.",400)
                await _ensure_tables(bot.db);user_id=int(session["user"]["id"])
                await bot.db.execute("INSERT INTO sentrix_dashboard_command_policy (guild_id,command_name,channel_id,enabled,updated_by,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id,command_name,channel_id) DO UPDATE SET enabled=excluded.enabled,updated_by=excluded.updated_by,updated_at=excluded.updated_at",(guild_id,name,channel_id,enabled,user_id,int(time.time())))
                return web.json_response({"ok":True})

            app.router.add_get("/api/guilds/{guild_id}/ops/overview",overview)
            app.router.add_get("/api/guilds/{guild_id}/ops/export",export_config)
            app.router.add_post("/api/guilds/{guild_id}/ops/import",import_config)
            app.router.add_post("/api/guilds/{guild_id}/ops/clone/{target_id}",clone_config)
            app.router.add_post("/api/guilds/{guild_id}/ops/history/{history_id}/rollback",rollback)
            app.router.add_post("/api/guilds/{guild_id}/ops/repair",repair)
            app.router.add_post("/api/guilds/{guild_id}/ops/maintenance",maintenance)
            app.router.add_post("/api/guilds/{guild_id}/ops/policies",policies)
            _install_runtime_policy(bot)
            return app
        build_app_with_ops._sentrix_ops_routes=True
        dashboard.build_app=build_app_with_ops

    _INSTALLED=True
    logger.info("SentriX dashboard ops suite installed.")
    return True


def _install_runtime_policy(bot) -> None:
    if getattr(bot,"_sentrix_dashboard_policy_guard",False):
        return
    bot._sentrix_dashboard_policy_guard=True
    cache={}

    async def rules(guild_id:int):
        now_m=time.monotonic();item=cache.get(guild_id)
        if item and now_m-item[0]<3:return item[1]
        db=bot.db
        try:
            await _ensure_tables(db)
            maintenance=await _maintenance(db,guild_id)
            policies=await _policies(db,guild_id)
        except Exception:
            maintenance={"enabled":False};policies=[]
        value=(maintenance,policies);cache[guild_id]=(now_m,value);return value

    async def allowed(guild,member,channel_id:int,command_name:str):
        if guild is None:return True,None
        if getattr(getattr(member,"guild_permissions",None),"administrator",False):return True,None
        maintenance,policies=await rules(guild.id)
        if maintenance.get("enabled"):return False,maintenance.get("reason") or "SentriX est en maintenance sur ce serveur."
        name=(command_name or "").strip().lower()
        for p in policies:
            if p.get("command_name") not in {name,name.split(" ",1)[0]}:continue
            cid=int(p.get("channel_id") or 0)
            if cid and cid!=int(channel_id or 0):continue
            if not p.get("enabled"):return False,"Cette commande est désactivée dans ce contexte depuis le dashboard."
        return True,None

    async def prefix_check(ctx):
        ok,message=await allowed(ctx.guild,ctx.author,getattr(ctx.channel,"id",0),getattr(ctx.command,"qualified_name",getattr(ctx.command,"name","")))
        if not ok:
            try:await ctx.send(message,delete_after=8)
            except Exception:pass
        return ok
    bot.add_check(prefix_check)

    tree=getattr(bot,"tree",None)
    if tree is not None and not getattr(tree,"_sentrix_dashboard_policy_guard",False):
        original=tree.interaction_check
        async def interaction_check(self,interaction):
            try:
                base=await original(interaction)
                if base is False:return False
            except TypeError:
                base=await original(self,interaction)
                if base is False:return False
            command=getattr(interaction,"command",None)
            name=getattr(command,"qualified_name",getattr(command,"name",""))
            ok,message=await allowed(interaction.guild,interaction.user,getattr(interaction.channel,"id",0),name)
            if not ok:
                try:
                    if interaction.response.is_done():await interaction.followup.send(message,ephemeral=True)
                    else:await interaction.response.send_message(message,ephemeral=True)
                except Exception:pass
            return ok
        tree.interaction_check=MethodType(interaction_check,tree)
        tree._sentrix_dashboard_policy_guard=True
