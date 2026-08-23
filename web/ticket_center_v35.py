"""Dashboard V35 — centre de gestion complet des tickets SentriX.

Cette couche enrichit l'onglet Tickets sans remplacer les réglages historiques. Elle ajoute :
- métriques temps réel ;
- liste des panels et activation/désactivation ;
- création rapide de panel ;
- vue synthétique des types de tickets ;
- tickets ouverts avec état, responsable et accès direct au salon Discord.

Les routes restent limitées aux administrateurs déjà autorisés par le dashboard principal.
"""
from __future__ import annotations

import logging
import re

from aiohttp import web

from database.db import now

logger = logging.getLogger("bot.dashboard.ticket-center-v35")
_INSTALLED = False


CSS = r"""
<style id="sentrix-ticket-center-v35-css">
  #sentrixTicketCenterV35{grid-column:1/-1;margin-top:10px;display:grid;gap:12px}
  .sx-ticket-head{display:flex;align-items:flex-end;justify-content:space-between;gap:14px;padding-top:6px;border-top:1px solid #252c3b}
  .sx-ticket-head h3{margin:0;color:#f1eff6;font-size:16px}.sx-ticket-head p{margin:4px 0 0;color:#7e8799;font-size:10px;line-height:1.45}
  .sx-ticket-refresh{min-height:34px;padding:0 12px;border:1px solid #31394d;border-radius:9px;background:#171d29;color:#e8e6ee;font-weight:750;cursor:pointer}
  .sx-ticket-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
  .sx-ticket-metric{min-width:0;padding:11px 12px;border:1px solid #252d40;border-radius:11px;background:#0f141e}
  .sx-ticket-metric span{display:block;color:#788195;font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}.sx-ticket-metric b{display:block;margin-top:3px;color:#f3f1f8;font-size:19px}
  .sx-ticket-section{border:1px solid #252d40;border-radius:12px;background:#0f141e;overflow:hidden}
  .sx-ticket-section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 12px;border-bottom:1px solid #222a3a}.sx-ticket-section-head b{font-size:12px;color:#efedf5}.sx-ticket-section-head span{font-size:9px;color:#778095}
  .sx-ticket-create{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:9px 12px;border-bottom:1px solid #222a3a}.sx-ticket-create input{min-width:0}.sx-ticket-create button{min-height:36px;padding:0 12px;border:1px solid #725bd0;border-radius:9px;background:#765de0;color:#fff;font-weight:800;cursor:pointer}
  .sx-ticket-list{display:grid}.sx-ticket-row{display:grid;grid-template-columns:minmax(150px,1.15fr) minmax(130px,.8fr) minmax(130px,.8fr) auto;gap:10px;align-items:center;min-height:50px;padding:8px 12px;border-top:1px solid #1e2533}.sx-ticket-row:first-child{border-top:0}
  .sx-ticket-main{min-width:0}.sx-ticket-main b{display:block;color:#eceaf2;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sx-ticket-main span,.sx-ticket-cell{display:block;color:#7d8698;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sx-ticket-state{display:inline-flex;align-items:center;justify-content:center;min-width:64px;padding:4px 7px;border:1px solid #343d52;border-radius:999px;background:#171d29;color:#b7bfd0;font-size:8px;font-weight:900;letter-spacing:.05em;text-transform:uppercase}.sx-ticket-state.on{border-color:#3d6454;background:#15261f;color:#8ed8b4}.sx-ticket-state.warn{border-color:#6a5630;background:#281f11;color:#e4c06d}
  .sx-ticket-actions{display:flex;justify-content:flex-end;gap:6px}.sx-ticket-actions button,.sx-ticket-actions a{display:inline-flex;align-items:center;justify-content:center;min-height:31px;padding:0 9px;border:1px solid #343d52;border-radius:8px;background:#171d29;color:#dcd9e4;font-size:9px;font-weight:800;text-decoration:none;cursor:pointer}.sx-ticket-actions button.primary{border-color:#6c55c8;background:#271f45;color:#cbbdff}
  .sx-ticket-empty{padding:18px 12px;color:#757e91;font-size:10px;text-align:center}.sx-ticket-error{padding:10px 12px;border:1px solid #67333a;border-radius:10px;background:#281519;color:#e99aa3;font-size:10px}
  @media(max-width:900px){.sx-ticket-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.sx-ticket-row{grid-template-columns:minmax(140px,1fr) minmax(110px,.8fr) auto}.sx-ticket-row>.sx-ticket-cell:nth-of-type(2){display:none}}
  @media(max-width:620px){.sx-ticket-head{align-items:flex-start}.sx-ticket-metrics{grid-template-columns:1fr 1fr}.sx-ticket-row{grid-template-columns:minmax(0,1fr) auto}.sx-ticket-cell{display:none!important}.sx-ticket-create{grid-template-columns:1fr}.sx-ticket-create button{width:100%}}
</style>
"""


JS = r"""
<script id="sentrix-ticket-center-v35-js">
(() => {
  "use strict";
  if (window.__sentrixTicketCenterV35) return;
  window.__sentrixTicketCenterV35 = true;
  let loadedGuild="",loading=false,data=null;

  function guildId(){try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):"";}catch(_){return "";}}
  function csrf(){try{return typeof state!=="undefined"?state.csrf||"":"";}catch(_){return "";}}
  function active(){try{return typeof state!=="undefined"&&state.tab==="tickets";}catch(_){return false;}}
  function esc(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);}
  function toast35(message,bad=false){try{if(typeof toast==="function")return toast(message,bad);}catch(_){}if(bad)console.error(message);else console.info(message);}
  function age(ts){if(!ts)return"—";const s=Math.max(0,Math.floor(Date.now()/1000)-Number(ts));if(s<60)return`${s}s`;if(s<3600)return`${Math.floor(s/60)} min`;if(s<86400)return`${Math.floor(s/3600)} h`;return`${Math.floor(s/86400)} j`;}
  function root(){if(!active()){document.getElementById("sentrixTicketCenterV35")?.remove();return null;}const fields=document.getElementById("fields");if(!fields)return null;let el=document.getElementById("sentrixTicketCenterV35");if(!el){el=document.createElement("section");el.id="sentrixTicketCenterV35";fields.appendChild(el);}return el;}
  function panelName(id){return data?.panels?.find(x=>String(x.id)===String(id))?.name||`Panel #${id}`;}
  function typeName(id,fallback){return data?.types?.find(x=>String(x.id)===String(id))?.name||fallback||"Type inconnu";}
  function memberName(id,fallback="Non assigné"){if(!id)return fallback;const item=data?.members?.[String(id)];return item?.name||`ID ${id}`;}
  function channelName(id){const item=data?.channels?.[String(id)];return item?`#${item.name}`:`ID ${id}`;}

  function renderPanels(){const rows=data.panels||[];if(!rows.length)return '<div class="sx-ticket-empty">Aucun panel. Créez votre premier panel ici ou avec +ticketsetup.</div>';return `<div class="sx-ticket-list">${rows.map(p=>`<div class="sx-ticket-row"><div class="sx-ticket-main"><b>${esc(p.name)}</b><span>${esc(p.title||"Sans titre")} · ${esc(p.style==="button"?"Boutons":"Menu déroulant")}</span></div><span class="sx-ticket-cell">${p.channel_id?esc(channelName(p.channel_id)):"Pas encore envoyé"}</span><span class="sx-ticket-cell">${Number(p.type_count||0)} type(s) · max ${Number(p.max_per_member||1)}/membre</span><div class="sx-ticket-actions"><span class="sx-ticket-state ${p.enabled?"on":""}">${p.enabled?"Actif":"Inactif"}</span><button class="primary" type="button" data-panel-toggle="${esc(p.id)}">${p.enabled?"Désactiver":"Activer"}</button></div></div>`).join("")}</div>`;}
  function renderTypes(){const rows=data.types||[];if(!rows.length)return '<div class="sx-ticket-empty">Aucun type de ticket configuré.</div>';return `<div class="sx-ticket-list">${rows.map(t=>`<div class="sx-ticket-row"><div class="sx-ticket-main"><b>${esc(t.name)}</b><span>${esc(panelName(t.panel_id))}</span></div><span class="sx-ticket-cell">Staff : ${esc(memberName(t.staff_role_id,"Rôle non défini"))}</span><span class="sx-ticket-cell">Max ${Number(t.max_per_member||1)} · Auto ${Number(t.autoclose_hours||0)?`${Number(t.autoclose_hours)} h`:"off"} · Formulaire ${t.use_form?"on":"off"}</span><div class="sx-ticket-actions"><span class="sx-ticket-state ${t.mention_staff?"on":""}">${t.mention_staff?"Ping staff":"Sans ping"}</span></div></div>`).join("")}</div>`;}
  function renderOpen(){const rows=data.open_tickets||[];if(!rows.length)return '<div class="sx-ticket-empty">Aucun ticket ouvert actuellement.</div>';return `<div class="sx-ticket-list">${rows.map(t=>{const url=`https://discord.com/channels/${guildId()}/${t.channel_id}`;const claimed=Boolean(t.claimed_by);return `<div class="sx-ticket-row"><div class="sx-ticket-main"><b>Ticket #${esc(t.id)} · ${esc(typeName(t.type_id,t.category))}</b><span>${esc(channelName(t.channel_id))} · ouvert il y a ${esc(age(t.created_at))}</span></div><span class="sx-ticket-cell">Membre : ${esc(memberName(t.user_id,"Utilisateur inconnu"))}</span><span class="sx-ticket-cell">${claimed?`Pris par ${esc(memberName(t.claimed_by,"Staff"))}`:"En attente de prise en charge"} · activité ${esc(age(t.last_activity_at))}</span><div class="sx-ticket-actions"><span class="sx-ticket-state ${claimed?"on":"warn"}">${claimed?"Pris":"À prendre"}</span><a href="${url}" target="_blank" rel="noopener">Ouvrir</a></div></div>`;}).join("")}</div>`;}
  function render(){const el=root();if(!el||!data)return;const m=data.metrics||{};el.innerHTML=`<div class="sx-ticket-head"><div><h3>Centre Tickets</h3><p>Panels, types et tickets ouverts réunis au même endroit. Les réglages généraux restent juste au-dessus.</p></div><button class="sx-ticket-refresh" id="sxTicketRefresh" type="button">Actualiser</button></div><div class="sx-ticket-metrics"><div class="sx-ticket-metric"><span>Ouverts</span><b>${Number(m.open||0)}</b></div><div class="sx-ticket-metric"><span>Non pris</span><b>${Number(m.unclaimed||0)}</b></div><div class="sx-ticket-metric"><span>Fermés sur 7 jours</span><b>${Number(m.closed_7d||0)}</b></div><div class="sx-ticket-metric"><span>Note moyenne</span><b>${m.average_rating?Number(m.average_rating).toFixed(1)+" / 5":"—"}</b></div></div><section class="sx-ticket-section"><div class="sx-ticket-section-head"><b>Panels</b><span>${Number(data.panels?.length||0)} configuré(s)</span></div><div class="sx-ticket-create"><input id="sxTicketPanelName" type="text" maxlength="80" placeholder="Nom du nouveau panel"><button id="sxTicketCreatePanel" type="button">Créer le panel</button></div>${renderPanels()}</section><section class="sx-ticket-section"><div class="sx-ticket-section-head"><b>Types de tickets</b><span>${Number(data.types?.length||0)} type(s)</span></div>${renderTypes()}</section><section class="sx-ticket-section"><div class="sx-ticket-section-head"><b>Tickets ouverts</b><span>${Number(data.open_tickets?.length||0)} affiché(s)</span></div>${renderOpen()}</section>`;
    document.getElementById("sxTicketRefresh")?.addEventListener("click",()=>load(guildId(),true));
    document.getElementById("sxTicketCreatePanel")?.addEventListener("click",createPanel);
    el.querySelectorAll("[data-panel-toggle]").forEach(btn=>btn.addEventListener("click",()=>togglePanel(btn.dataset.panelToggle)));
  }
  async function load(id,force=false){if(!id||loading)return;if(!force&&loadedGuild===id&&data){render();return;}loading=true;const el=root();if(el&&!data)el.innerHTML='<div class="sx-ticket-empty">Chargement du centre Tickets…</div>';try{const response=await fetch(`/api/guilds/${id}/ticket-center`,{credentials:"same-origin",cache:"no-store"});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||"Impossible de charger les tickets.");if(guildId()!==id||!active())return;loadedGuild=id;data=body;render();}catch(error){if(el)el.innerHTML=`<div class="sx-ticket-error">${esc(error.message||"Impossible de charger les tickets.")}</div>`;toast35(error.message||"Impossible de charger les tickets.",true);}finally{loading=false;}}
  async function createPanel(){const id=guildId(),input=document.getElementById("sxTicketPanelName"),name=input?.value.trim()||"";if(!id||!name)return toast35("Entrez un nom pour le panel.",true);try{const response=await fetch(`/api/guilds/${id}/ticket-center/panels`,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({name})});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||"Création impossible.");toast35(body.message||"Panel créé.");data=null;await load(id,true);}catch(error){toast35(error.message||"Création impossible.",true);}}
  async function togglePanel(panelId){const id=guildId();if(!id||!panelId)return;try{const response=await fetch(`/api/guilds/${id}/ticket-center/panels/${panelId}/toggle`,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:"{}"});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.error||"Modification impossible.");toast35(body.message||"Panel mis à jour.");data=null;await load(id,true);}catch(error){toast35(error.message||"Modification impossible.",true);}}
  let last="";const tick=()=>{const id=guildId(),key=`${id}:${active()?"tickets":"other"}`;if(!id||!active()){document.getElementById("sentrixTicketCenterV35")?.remove();last=key;return;}if(key!==last||loadedGuild!==id||!data){last=key;data=null;load(id,true);return;}if(!document.getElementById("sentrixTicketCenterV35"))render();};
  setInterval(tick,650);window.addEventListener("pageshow",tick);setTimeout(tick,150);
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-ticket-center-v35-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    return html


def _safe_name(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:80]


def _member_snapshot(guild, user_ids: set[int]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for user_id in user_ids:
        if not user_id:
            continue
        member = guild.get_member(int(user_id))
        if member is not None:
            result[str(user_id)] = {
                "id": str(user_id),
                "name": getattr(member, "display_name", None) or getattr(member, "name", None) or str(member),
            }
    return result


def _channel_snapshot(guild, channel_ids: set[int]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for channel_id in channel_ids:
        if not channel_id:
            continue
        channel = guild.get_channel(int(channel_id))
        if channel is not None:
            result[str(channel_id)] = {"id": str(channel_id), "name": channel.name}
    return result


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    async def get_ticket_center(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        db = request.app["bot"].db
        stamp = now()
        metrics = {}
        queries = {
            "open": ("SELECT COUNT(*) n FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (guild_id,)),
            "unclaimed": ("SELECT COUNT(*) n FROM tickets WHERE guild_id = ? AND status = 'ouvert' AND claimed_by IS NULL", (guild_id,)),
            "closed_7d": ("SELECT COUNT(*) n FROM tickets WHERE guild_id = ? AND status = 'ferme' AND closed_at >= ?", (guild_id, stamp - 7 * 86400)),
            "average_rating": ("SELECT AVG(rating) n FROM tickets WHERE guild_id = ? AND rating IS NOT NULL", (guild_id,)),
        }
        for key, (query, params) in queries.items():
            try:
                row = await db.fetchone(query, params)
                metrics[key] = row["n"] if row and row["n"] is not None else 0
            except Exception:
                metrics[key] = 0

        panels = await db.fetchall(
            "SELECT p.*, (SELECT COUNT(*) FROM ticket_types t WHERE t.panel_id = p.id) AS type_count "
            "FROM ticket_panels_v2 p WHERE p.guild_id = ? ORDER BY p.id DESC LIMIT 50",
            (guild_id,),
        )
        types = await db.fetchall(
            "SELECT * FROM ticket_types WHERE guild_id = ? ORDER BY panel_id, position, id LIMIT 100",
            (guild_id,),
        )
        open_tickets = await db.fetchall(
            "SELECT id, channel_id, user_id, category, priority, claimed_by, created_at, last_activity_at, type_id "
            "FROM tickets WHERE guild_id = ? AND status = 'ouvert' ORDER BY created_at DESC LIMIT 50",
            (guild_id,),
        )

        panel_items = [dict(row) for row in panels]
        type_items = [dict(row) for row in types]
        ticket_items = [dict(row) for row in open_tickets]
        user_ids: set[int] = set()
        channel_ids: set[int] = set()
        for item in ticket_items:
            if item.get("user_id"):
                user_ids.add(int(item["user_id"]))
            if item.get("claimed_by"):
                user_ids.add(int(item["claimed_by"]))
            if item.get("channel_id"):
                channel_ids.add(int(item["channel_id"]))
        for panel in panel_items:
            if panel.get("channel_id"):
                channel_ids.add(int(panel["channel_id"]))

        # Les rôles sont rangés dans le même dictionnaire de libellés afin que le client
        # n'ait jamais besoin de recevoir la liste complète des membres du serveur.
        members = _member_snapshot(guild, user_ids)
        for item in type_items:
            role_id = item.get("staff_role_id")
            if role_id:
                role = guild.get_role(int(role_id))
                if role is not None:
                    members[str(role_id)] = {"id": str(role_id), "name": "@" + role.name}

        return web.json_response({
            "ok": True,
            "metrics": metrics,
            "panels": panel_items,
            "types": type_items,
            "open_tickets": ticket_items,
            "members": members,
            "channels": _channel_snapshot(guild, channel_ids),
        })

    async def create_panel(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
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
        name = _safe_name(payload.get("name") if isinstance(payload, dict) else "")
        if len(name) < 2:
            return dashboard._json_error("Le nom du panel doit contenir au moins 2 caractères.", 400)
        db = request.app["bot"].db
        existing = await db.fetchone(
            "SELECT id FROM ticket_panels_v2 WHERE guild_id = ? AND LOWER(name) = LOWER(?)",
            (guild_id, name),
        )
        if existing:
            return dashboard._json_error("Un panel avec ce nom existe déjà.", 409)
        cur = await db.execute(
            "INSERT INTO ticket_panels_v2 (guild_id, name, title, description, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, name, f"Support — {name}", "Choisissez une option ci-dessous pour ouvrir un ticket.", now()),
        )
        logger.info("Ticket Center V35 : panel #%s créé sur %s (%s).", cur.lastrowid, guild.name, guild.id)
        return web.json_response({"ok": True, "panel_id": cur.lastrowid, "message": f"Panel « {name} » créé."})

    async def toggle_panel(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
            panel_id = int(request.match_info["panel_id"])
        except ValueError:
            return dashboard._json_error("Identifiant invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        db = request.app["bot"].db
        panel = await db.fetchone("SELECT id, name, enabled FROM ticket_panels_v2 WHERE id = ? AND guild_id = ?", (panel_id, guild_id))
        if not panel:
            return dashboard._json_error("Panel introuvable.", 404)
        enabled = 0 if panel["enabled"] else 1
        await db.execute("UPDATE ticket_panels_v2 SET enabled = ? WHERE id = ? AND guild_id = ?", (enabled, panel_id, guild_id))
        state = "activé" if enabled else "désactivé"
        logger.info("Ticket Center V35 : panel #%s %s sur %s (%s).", panel_id, state, guild.name, guild.id)
        return web.json_response({"ok": True, "enabled": bool(enabled), "message": f"Panel « {panel['name']} » {state}."})

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/ticket-center", get_ticket_center)
        app.router.add_post("/api/guilds/{guild_id}/ticket-center/panels", create_panel)
        app.router.add_post("/api/guilds/{guild_id}/ticket-center/panels/{panel_id}/toggle", toggle_panel)
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Dashboard V35 : centre Tickets installé.")


__all__ = ["install"]
