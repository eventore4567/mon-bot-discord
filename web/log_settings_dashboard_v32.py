"""Dashboard V32 — configuration des journaux avancés SentriX.

Ajoute un bloc autonome à l'onglet Logs du dashboard principal, sans remplacer renderTab,
selectGuild ou le formulaire historique. Les cinq catégories V32 ont chacune leur salon
et leur interrupteur : salons, dossiers, anti-spam, anti-raid et activité staff.
"""
from __future__ import annotations

import logging

import discord
from aiohttp import web

from utils import log_service

logger = logging.getLogger("bot.dashboard.logs-v32")
_INSTALLED = False

ADVANCED_TYPES = {
    "channels": {
        "label": "Salons / catégories",
        "hint": "Création, suppression et modification des salons et catégories.",
        "recommended": "logs-salons",
    },
    "cases": {
        "label": "Dossiers de modération",
        "hint": "Avertissements et dossiers de sanctions suivis par SentriX.",
        "recommended": "logs-dossiers",
    },
    "spam": {
        "label": "Protection anti-spam",
        "hint": "Spam, liens, invitations, mentions, caps, emojis et arnaques.",
        "recommended": "logs-protect-spam-logs",
    },
    "raid": {
        "label": "Protection anti-raid",
        "hint": "Raids, anti-nuke, bots/comptes suspects et actions massives.",
        "recommended": "raidprotect-logs",
    },
    "staff": {
        "label": "Activité modérateur",
        "hint": "Commandes sensibles exécutées par les modérateurs et administrateurs.",
        "recommended": "moderator-only",
    },
}

CSS = r"""
<style id="sentrix-advanced-logs-v32-css">
  #sentrixAdvancedLogsV32{grid-column:1/-1;margin-top:12px;padding:20px;border:1px solid #2a3150;border-radius:18px;background:linear-gradient(145deg,#121725,#0e121c);box-shadow:0 15px 42px #0003}
  .sx-log32-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:15px}
  .sx-log32-head h3{margin:0;color:#f3f1f8;font-size:16px}.sx-log32-head p{margin:5px 0 0;color:#7f879b;font-size:11px;line-height:1.5;max-width:720px}
  .sx-log32-badge{border:1px solid #4b3f72;border-radius:999px;background:#211b35;color:#bbaaff;padding:5px 9px;font-size:9px;font-weight:900;letter-spacing:.07em;text-transform:uppercase;white-space:nowrap}
  .sx-log32-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
  .sx-log32-card{padding:15px;border:1px solid #252d40;border-radius:14px;background:#0f141e}
  .sx-log32-card:last-child:nth-child(odd){grid-column:1/-1}
  .sx-log32-title{display:flex;justify-content:space-between;gap:12px;align-items:center}.sx-log32-title b{font-size:13px;color:#efedf5}
  .sx-log32-card p{margin:6px 0 12px;color:#788195;font-size:10px;line-height:1.45}
  .sx-log32-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center}
  .sx-log32-row select{width:100%;min-width:0}
  .sx-log32-toggle{position:relative;width:50px;height:28px;border:0;border-radius:999px;background:#343b50;cursor:pointer;box-shadow:inset 0 0 0 1px #ffffff0d}
  .sx-log32-toggle::after{content:"";position:absolute;left:4px;top:4px;width:20px;height:20px;border-radius:50%;background:#fff;transition:.16s}
  .sx-log32-toggle.on{background:#8066eb}.sx-log32-toggle.on::after{left:26px}.sx-log32-toggle:disabled{opacity:.5;cursor:not-allowed}
  .sx-log32-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:15px;padding-top:14px;border-top:1px solid #222a3c}
  .sx-log32-status{color:#727b90;font-size:10px}.sx-log32-save{min-height:38px;padding:0 14px;border:1px solid #735bd2;border-radius:10px;background:linear-gradient(135deg,#8f73ff,#6f52dd);color:#fff;font-weight:850;cursor:pointer}.sx-log32-save:disabled{opacity:.55;cursor:not-allowed}
  @media(max-width:760px){.sx-log32-grid{grid-template-columns:1fr}.sx-log32-card:last-child:nth-child(odd){grid-column:auto}.sx-log32-head{display:block}.sx-log32-badge{display:inline-block;margin-top:9px}}
</style>
"""

JS = r"""
<script id="sentrix-advanced-logs-v32-js">
(() => {
  "use strict";
  if (window.__sentrixAdvancedLogsV32) return;
  window.__sentrixAdvancedLogsV32 = true;

  const META = {
    channels:{label:"Salons / catégories",hint:"Création, suppression et modification des salons et catégories.",recommended:"logs-salons"},
    cases:{label:"Dossiers de modération",hint:"Avertissements et dossiers de sanctions suivis par SentriX.",recommended:"logs-dossiers"},
    spam:{label:"Protection anti-spam",hint:"Spam, liens, invitations, mentions, caps, emojis et arnaques.",recommended:"logs-protect-spam-logs"},
    raid:{label:"Protection anti-raid",hint:"Raids, anti-nuke, bots/comptes suspects et actions massives.",recommended:"raidprotect-logs"},
    staff:{label:"Activité modérateur",hint:"Commandes sensibles exécutées par les modérateurs et administrateurs.",recommended:"moderator-only"}
  };
  let activeGuild = "";
  let settings = null;
  let loading = false;
  let dirty = false;

  function guildId(){try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):"";}catch(_){return "";}}
  function csrf(){try{return typeof state!=="undefined"?state.csrf||"":"";}catch(_){return "";}}
  function isLogsTab(){try{return typeof state!=="undefined"&&state.tab==="logs";}catch(_){return false;}}
  function notify(message,bad=false){try{if(typeof toast==="function")return toast(message,bad);}catch(_){} if(bad)console.error(message);else console.info(message);}
  function esc32(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);}

  function textChannels(){
    try{return (state.guildData?.channels||[]).filter(c=>["text","news"].includes(String(c.type)));}
    catch(_){return [];}
  }
  function options(current){
    return '<option value="">Non configuré</option>'+textChannels().map(c=>`<option value="${esc32(c.id)}" ${String(current||"")===String(c.id)?"selected":""}>#${esc32(c.name)}</option>`).join("");
  }
  function ensureRoot(){
    if(!isLogsTab()) { document.getElementById("sentrixAdvancedLogsV32")?.remove(); return null; }
    const fields=document.getElementById("fields");
    if(!fields)return null;
    let root=document.getElementById("sentrixAdvancedLogsV32");
    if(!root){root=document.createElement("section");root.id="sentrixAdvancedLogsV32";fields.appendChild(root);}
    return root;
  }
  function card(key, item){
    const enabled=Boolean(item?.enabled), channel=item?.channel_id||"";
    return `<article class="sx-log32-card" data-log32-card="${key}">
      <div class="sx-log32-title"><b>${esc32(META[key].label)}</b><span>${enabled?"ACTIF":"INACTIF"}</span></div>
      <p>${esc32(META[key].hint)} Salon conseillé : <b>${esc32(META[key].recommended)}</b>.</p>
      <div class="sx-log32-row">
        <select class="select" data-log32-channel="${key}">${options(channel)}</select>
        <button class="sx-log32-toggle ${enabled?"on":""}" type="button" role="switch" aria-checked="${enabled?"true":"false"}" data-log32-toggle="${key}" title="Activer ou désactiver"></button>
      </div>
    </article>`;
  }
  function render(){
    const root=ensureRoot(); if(!root||!settings)return;
    root.innerHTML=`<div class="sx-log32-head"><div><h3>Logs supplémentaires</h3><p>Ces catégories complètent les logs existants. Elles utilisent exactement le même rendu SentriX et restent indépendantes les unes des autres.</p></div><span class="sx-log32-badge">V32</span></div>
      <div class="sx-log32-grid">${Object.keys(META).map(k=>card(k,settings[k]||{})).join("")}</div>
      <div class="sx-log32-foot"><span class="sx-log32-status" id="sentrixLog32Status">${dirty?"Modifications non enregistrées":"Configuration synchronisée"}</span><button class="sx-log32-save" id="sentrixLog32Save" type="button">Enregistrer ces logs</button></div>`;
    root.querySelectorAll("[data-log32-toggle]").forEach(button=>button.addEventListener("click",()=>{button.classList.toggle("on");button.setAttribute("aria-checked",button.classList.contains("on")?"true":"false");dirty=true;document.getElementById("sentrixLog32Status").textContent="Modifications non enregistrées";}));
    root.querySelectorAll("[data-log32-channel]").forEach(select=>select.addEventListener("change",()=>{dirty=true;document.getElementById("sentrixLog32Status").textContent="Modifications non enregistrées";}));
    document.getElementById("sentrixLog32Save")?.addEventListener("click",save);
  }
  async function load(id){
    if(!id||loading)return; loading=true;
    try{
      const response=await fetch(`/api/guilds/${id}/advanced-logs`,{cache:"no-store",credentials:"same-origin"});
      const data=await response.json().catch(()=>({})); if(!response.ok)throw new Error(data.error||"Impossible de charger les logs supplémentaires.");
      if(guildId()!==id)return; activeGuild=id;settings=data.logs||{};dirty=false;render();
    }catch(error){notify(error.message||"Impossible de charger les logs supplémentaires.",true);}finally{loading=false;}
  }
  async function save(){
    const id=guildId(),root=document.getElementById("sentrixAdvancedLogsV32"); if(!id||!root)return;
    const logs={};
    Object.keys(META).forEach(key=>{const select=root.querySelector(`[data-log32-channel="${key}"]`);const toggle=root.querySelector(`[data-log32-toggle="${key}"]`);logs[key]={channel_id:select?.value||null,enabled:Boolean(toggle?.classList.contains("on"))};});
    const button=document.getElementById("sentrixLog32Save"); if(button)button.disabled=true;
    try{
      const response=await fetch(`/api/guilds/${id}/advanced-logs`,{method:"PUT",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({logs})});
      const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error||"Enregistrement impossible.");
      settings=data.logs||settings;dirty=false;render();notify(data.message||"Logs supplémentaires enregistrés.");
    }catch(error){notify(error.message||"Enregistrement impossible.",true);const status=document.getElementById("sentrixLog32Status");if(status)status.textContent="Enregistrement impossible";}finally{const fresh=document.getElementById("sentrixLog32Save");if(fresh)fresh.disabled=false;}
  }

  let lastKey="";
  const tick=()=>{
    const id=guildId(),key=`${id}:${isLogsTab()?"logs":"other"}`;
    if(!id||!isLogsTab()){document.getElementById("sentrixAdvancedLogsV32")?.remove();lastKey=key;return;}
    const root=document.getElementById("sentrixAdvancedLogsV32");
    if(key!==lastKey||activeGuild!==id||!settings){lastKey=key;settings=null;dirty=false;load(id);return;}
    if(!root&&!dirty)render();
  };
  setInterval(tick,650);window.addEventListener("pageshow",tick);setTimeout(tick,180);
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-advanced-logs-v32-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    return html


async def _snapshot(bot, guild_id: int) -> dict[str, dict]:
    return {key: await log_service.get_log_setting(bot, guild_id, key) for key in ADVANCED_TYPES}


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard.build_app

    async def get_advanced_logs(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, _guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        logs = await _snapshot(request.app["bot"], guild_id)
        return web.json_response({"ok": True, "logs": logs, "meta": ADVANCED_TYPES})

    async def put_advanced_logs(request: web.Request):
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
            return dashboard._json_error("Le formulaire envoyé est invalide.", 400)
        values = payload.get("logs") if isinstance(payload, dict) else None
        if not isinstance(values, dict):
            return dashboard._json_error("Aucune configuration de logs valide reçue.", 400)

        for key, item in values.items():
            if key not in ADVANCED_TYPES or not isinstance(item, dict):
                return dashboard._json_error("Une catégorie de logs envoyée est invalide.", 400)
            raw_channel = item.get("channel_id")
            enabled = bool(item.get("enabled", False))
            channel_id = None
            if raw_channel not in (None, "", 0, "0"):
                try:
                    channel_id = int(raw_channel)
                except (TypeError, ValueError):
                    return dashboard._json_error(f"Salon invalide pour {ADVANCED_TYPES[key]['label']}.", 400)
                channel = guild.get_channel(channel_id)
                if channel is None or not isinstance(channel, discord.TextChannel):
                    return dashboard._json_error(f"Le salon choisi pour {ADVANCED_TYPES[key]['label']} n'est pas un salon texte valide.", 400)
                ok, reason = log_service.validate_channel(guild, channel_id)
                if not ok:
                    return dashboard._json_error(f"{ADVANCED_TYPES[key]['label']} : {reason}.", 400)
            if enabled and not channel_id:
                return dashboard._json_error(f"Choisissez un salon avant d'activer {ADVANCED_TYPES[key]['label']}.", 400)

            await log_service.set_log_channel(request.app["bot"], guild_id, key, channel_id)
            await log_service.set_log_enabled(request.app["bot"], guild_id, key, enabled)

        logs = await _snapshot(request.app["bot"], guild_id)
        logger.info(
            "Dashboard V32 : %s (%s) a mis à jour les logs avancés sur %s (%s).",
            session["user"].get("username"), session["user"].get("id"), guild.name, guild.id,
        )
        return web.json_response({
            "ok": True,
            "logs": logs,
            "message": "Configuration des logs supplémentaires enregistrée.",
        })

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/advanced-logs", get_advanced_logs)
        app.router.add_put("/api/guilds/{guild_id}/advanced-logs", put_advanced_logs)
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Dashboard V32 : configuration des logs avancés installée.")


__all__ = ["install", "ADVANCED_TYPES"]
