"""Dashboard V32 — un seul panneau de logs, compact et horizontal.

Les catégories V32 sont intégrées directement dans la liste historique au lieu de créer
un second bloc « Logs supplémentaires ». Cela évite les doublons visuels et applique le
même format rectangle à toutes les lignes de configuration.
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
  #fields.sx-log-rect-list{grid-template-columns:1fr!important;gap:8px!important;align-content:start}
  #fields.sx-log-rect-list>.field{grid-column:1/-1!important;display:grid!important;grid-template-columns:minmax(190px,260px) minmax(260px,1fr)!important;align-items:center!important;gap:14px!important;min-height:54px!important;margin:0!important;padding:9px 12px!important;border:1px solid #252d40!important;border-radius:12px!important;background:#0f141e!important;box-shadow:none!important}
  #fields.sx-log-rect-list>.field label{display:block!important;margin:0!important;color:#efedf5!important;font-size:12px!important;font-weight:780!important;line-height:1.25!important}
  #fields.sx-log-rect-list>.field select,#fields.sx-log-rect-list>.field input{width:100%!important;min-width:0!important;margin:0!important}
  .sx-log32-control{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;min-width:0}
  .sx-log32-toggle{position:relative;width:46px;height:26px;border:0;border-radius:999px;background:#343b50;cursor:pointer;box-shadow:inset 0 0 0 1px #ffffff0d}
  .sx-log32-toggle::after{content:"";position:absolute;left:4px;top:4px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.16s}
  .sx-log32-toggle.on{background:#8066eb}.sx-log32-toggle.on::after{left:24px}.sx-log32-toggle:disabled{opacity:.5;cursor:not-allowed}
  .sx-log32-save-row{grid-column:1/-1!important;display:flex!important;align-items:center!important;justify-content:flex-end!important;gap:10px!important;min-height:46px!important;padding:6px 0 0!important;border:0!important;background:transparent!important}
  .sx-log32-status{color:#7f879b;font-size:10px}.sx-log32-save{min-height:36px;padding:0 13px;border:1px solid #735bd2;border-radius:10px;background:linear-gradient(135deg,#8f73ff,#6f52dd);color:#fff;font-weight:850;cursor:pointer}.sx-log32-save:disabled{opacity:.55;cursor:not-allowed}
  @media(max-width:760px){#fields.sx-log-rect-list>.field{grid-template-columns:1fr!important;gap:6px!important;min-height:0!important;padding:10px!important}.sx-log32-save-row{justify-content:stretch!important}.sx-log32-save{width:100%}}
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
  let activeGuild="",settings=null,loading=false,dirty=false;
  function guildId(){try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):"";}catch(_){return "";}}
  function csrf(){try{return typeof state!=="undefined"?state.csrf||"":"";}catch(_){return "";}}
  function isLogsTab(){try{return typeof state!=="undefined"&&state.tab==="logs";}catch(_){return false;}}
  function notify(message,bad=false){try{if(typeof toast==="function")return toast(message,bad);}catch(_){}if(bad)console.error(message);else console.info(message);}
  function esc(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);}
  function textChannels(){try{return (state.guildData?.channels||[]).filter(c=>["text","news"].includes(String(c.type)));}catch(_){return [];}}
  function options(current){return '<option value="">Non configuré</option>'+textChannels().map(c=>`<option value="${esc(c.id)}" ${String(current||"")===String(c.id)?"selected":""}>#${esc(c.name)}</option>`).join("");}
  function fieldsRoot(){const fields=document.getElementById("fields");if(!fields)return null;if(isLogsTab())fields.classList.add("sx-log-rect-list");else fields.classList.remove("sx-log-rect-list");return fields;}
  function clearAdvancedRows(){document.querySelectorAll(".sx-log32-field,.sx-log32-save-row,#sentrixAdvancedLogsV32").forEach(el=>el.remove());}
  function dedupeBaseRows(fields){const seen=new Set();[...fields.querySelectorAll(":scope > .field")].forEach(row=>{if(row.classList.contains("sx-log32-field"))return;const control=row.querySelector("[data-key],select[name],input[name]");const key=control?.dataset?.key||control?.getAttribute("name")||"";if(!key)return;if(seen.has(key)){row.remove();return;}seen.add(key);});}
  function markDirty(){dirty=true;const status=document.getElementById("sentrixLog32Status");if(status)status.textContent="Modifications non enregistrées";}
  function advancedRow(key,item){const enabled=Boolean(item?.enabled),channel=item?.channel_id||"";const row=document.createElement("div");row.className="field sx-log32-field";row.dataset.log32Key=key;row.title=`${META[key].hint} Salon conseillé : #${META[key].recommended}`;row.innerHTML=`<label>${esc(META[key].label)}</label><div class="sx-log32-control"><select class="select" data-log32-channel="${key}">${options(channel)}</select><button class="sx-log32-toggle ${enabled?"on":""}" type="button" role="switch" aria-checked="${enabled?"true":"false"}" data-log32-toggle="${key}" title="Activer ou désactiver ${esc(META[key].label)}"></button></div>`;row.querySelector("[data-log32-toggle]")?.addEventListener("click",e=>{const button=e.currentTarget;button.classList.toggle("on");button.setAttribute("aria-checked",button.classList.contains("on")?"true":"false");markDirty();});row.querySelector("[data-log32-channel]")?.addEventListener("change",markDirty);return row;}
  function render(){const fields=fieldsRoot();if(!fields||!isLogsTab()||!settings)return;clearAdvancedRows();fields.classList.add("sx-log-rect-list");dedupeBaseRows(fields);Object.keys(META).forEach(key=>fields.appendChild(advancedRow(key,settings[key]||{})));const saveRow=document.createElement("div");saveRow.className="sx-log32-save-row";saveRow.innerHTML=`<span class="sx-log32-status" id="sentrixLog32Status">${dirty?"Modifications non enregistrées":"Tous les logs sont synchronisés"}</span><button class="sx-log32-save" id="sentrixLog32Save" type="button">Enregistrer les logs avancés</button>`;fields.appendChild(saveRow);document.getElementById("sentrixLog32Save")?.addEventListener("click",save);}
  async function load(id){if(!id||loading)return;loading=true;try{const response=await fetch(`/api/guilds/${id}/advanced-logs`,{cache:"no-store",credentials:"same-origin"});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error||"Impossible de charger les logs.");if(guildId()!==id)return;activeGuild=id;settings=data.logs||{};dirty=false;render();}catch(error){notify(error.message||"Impossible de charger les logs.",true);}finally{loading=false;}}
  async function save(){const id=guildId(),fields=fieldsRoot();if(!id||!fields)return;const logs={};Object.keys(META).forEach(key=>{const select=fields.querySelector(`[data-log32-channel="${key}"]`),toggle=fields.querySelector(`[data-log32-toggle="${key}"]`);logs[key]={channel_id:select?.value||null,enabled:Boolean(toggle?.classList.contains("on"))};});const button=document.getElementById("sentrixLog32Save");if(button)button.disabled=true;try{const response=await fetch(`/api/guilds/${id}/advanced-logs`,{method:"PUT",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({logs})});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error||"Enregistrement impossible.");settings=data.logs||settings;dirty=false;render();notify(data.message||"Logs enregistrés.");}catch(error){notify(error.message||"Enregistrement impossible.",true);const status=document.getElementById("sentrixLog32Status");if(status)status.textContent="Enregistrement impossible";}finally{const fresh=document.getElementById("sentrixLog32Save");if(fresh)fresh.disabled=false;}}
  let lastKey="";const tick=()=>{const id=guildId(),key=`${id}:${isLogsTab()?"logs":"other"}`,fields=fieldsRoot();if(!id||!isLogsTab()){clearAdvancedRows();if(fields)fields.classList.remove("sx-log-rect-list");lastKey=key;return;}if(fields)dedupeBaseRows(fields);if(key!==lastKey||activeGuild!==id||!settings){lastKey=key;settings=null;dirty=false;load(id);return;}if(fields&&!fields.querySelector(".sx-log32-field")&&!dirty)render();};
  setInterval(tick,500);window.addEventListener("pageshow",tick);setTimeout(tick,120);
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
        logger.info("Dashboard V32 : %s (%s) a mis à jour les logs avancés sur %s (%s).", session["user"].get("username"), session["user"].get("id"), guild.name, guild.id)
        return web.json_response({"ok": True, "logs": logs, "message": "Configuration des logs avancés enregistrée."})

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/advanced-logs", get_advanced_logs)
        app.router.add_put("/api/guilds/{guild_id}/advanced-logs", put_advanced_logs)
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Dashboard V32 : liste unique de logs en rectangles horizontaux installée.")


__all__ = ["install", "ADVANCED_TYPES"]
