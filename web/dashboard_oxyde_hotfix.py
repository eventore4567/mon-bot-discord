"""Final reliability layer for the Oxyde-inspired SentriX dashboard.

The main dashboard has accumulated several optional modules over time. This layer keeps
those modules and their backend routes available, but prevents their client-side helpers
from cluttering the primary sidebar. It also makes the guild payload fail-soft so an
optional database table can never leave /app completely blank.
"""

from __future__ import annotations

import logging
import sys

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard.oxyde-hotfix")
_PATCHED = False


HOTFIX_CSS = r"""
<style id="sentrix-oxyde-hotfix-css">
  /* Final desktop shell: no white sidebar scrollbar and no overlapping footer. */
  #dashboard .side{
    display:flex!important;
    flex-direction:column!important;
    overflow:hidden!important;
    scrollbar-width:none!important;
  }
  #dashboard .side::-webkit-scrollbar,
  #dashboard #navigation::-webkit-scrollbar{width:0!important;height:0!important;display:none!important}
  #dashboard #navigation{
    flex:1 1 auto!important;
    min-height:0!important;
    overflow-y:auto!important;
    overflow-x:hidden!important;
    padding-bottom:18px!important;
  }
  #dashboard .side-bottom{
    position:static!important;
    left:auto!important;right:auto!important;bottom:auto!important;
    flex:0 0 auto!important;
    margin-top:auto!important;
    padding:13px 0 0!important;
    background:linear-gradient(180deg,rgba(9,11,18,0),#090b12 25%)!important;
    border-top:1px solid #20263a!important;
  }

  /* Optional centres remain available by URL, but no longer inject random controls. */
  #sentrixOperationsLink,#sentrixEnterpriseLink{display:none!important}
  #sentrixGlobalSearch{display:none!important}
  #dashboard .side-bottom>div:has(#sentrixGlobalSearch){display:none!important;margin:0!important}

  /* Server selector gets a proper compact card instead of floating alone. */
  .sx-server-box{min-width:310px;display:grid;gap:7px}
  .sx-server-box>label{font-size:10px;font-weight:900;letter-spacing:.11em;text-transform:uppercase;color:#747b90;padding-left:2px}
  .sx-server-box .server-select{min-width:0!important;width:100%!important;background:#0e121c!important;border-color:#2a3145!important}

  /* Better empty/loading/error state. */
  #emptyState.sx-empty-premium{
    margin:28px 0 0!important;
    min-height:330px!important;
    display:grid!important;
    place-items:center!important;
    border:1px dashed #30384f!important;
    border-radius:22px!important;
    background:linear-gradient(145deg,#10141f,#0b0e16)!important;
    color:#8d95a9!important;
    padding:34px!important;
  }
  .sx-load-card{width:min(620px,100%);text-align:center}
  .sx-load-orb{width:58px;height:58px;margin:0 auto 18px;border-radius:18px;border:1px solid #57468b;background:radial-gradient(circle at 35% 30%,#b7a4ff,#7658e8 48%,#2a2248 100%);box-shadow:0 0 34px #7f63ef3d;animation:sxOrb 1.8s ease-in-out infinite}
  .sx-load-card h3{margin:0;color:#f4f2fb;font-size:20px;letter-spacing:-.025em}
  .sx-load-card p{margin:8px auto 0;max-width:520px;color:#838ba0;line-height:1.55;font-size:13px}
  .sx-load-card .btn{margin-top:18px}
  @keyframes sxOrb{50%{transform:translateY(-5px) scale(1.035);box-shadow:0 0 48px #8f73ff55}}

  /* Small visual pass to make the interface feel less flat. */
  #dashboard .field,#dashboard .sanction-card,#dashboard .notification-item,
  #dashboard .sx-hub-card,#dashboard .sx-summary-main,#dashboard .sx-summary-stat{
    box-shadow:0 16px 44px rgba(0,0,0,.18)!important;
  }
  #dashboard .sx-hub-card{transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease!important}
  #dashboard .sx-hub-card:hover{transform:translateY(-2px);border-color:#51436f!important;box-shadow:0 22px 55px rgba(0,0,0,.26)!important}

  @media(max-width:980px){
    #dashboard .side{overflow:visible!important}
    #dashboard #navigation{overflow-x:auto!important;overflow-y:hidden!important;padding-bottom:8px!important}
    #dashboard .side-bottom{display:none!important}
    .sx-server-box{min-width:0;width:100%}
  }
  @media(prefers-reduced-motion:reduce){.sx-load-orb{animation:none!important}}
</style>
"""


HOTFIX_JS = r"""
<script id="sentrix-oxyde-hotfix-js">
(() => {
  "use strict";
  if (window.__sentrixOxydeHotfix) return;
  window.__sentrixOxydeHotfix = true;

  let recoveryBusy = false;
  let lastRecoveryGuild = "";

  const getState = () => {
    try { return typeof state !== "undefined" ? state : null; }
    catch (_) { return null; }
  };

  const formatNumber = value => Number(value || 0).toLocaleString("fr-FR");

  function cleanupSidebar(){
    for (const id of ["sentrixOperationsLink","sentrixEnterpriseLink"]) {
      const node=document.getElementById(id);
      if(node) node.style.setProperty("display","none","important");
    }
    const globalSearch=document.getElementById("sentrixGlobalSearch");
    if(globalSearch){
      globalSearch.style.setProperty("display","none","important");
      const box=globalSearch.parentElement;
      if(box && box.parentElement?.classList.contains("side-bottom")) box.style.setProperty("display","none","important");
    }
    const side=document.querySelector("#dashboard .side");
    if(side) side.classList.add("sx-clean-side");
  }

  function beautifyServerPicker(){
    const select=document.getElementById("serverSelect");
    if(!select || select.closest(".sx-server-box")) return;
    const parent=select.parentNode;
    if(!parent) return;
    const box=document.createElement("div");
    box.className="sx-server-box";
    const label=document.createElement("label");
    label.htmlFor="serverSelect";
    label.textContent="Serveur actif";
    parent.insertBefore(box,select);
    box.append(label,select);
  }

  function loadingState(text="Chargement du serveur…"){
    const empty=document.getElementById("emptyState");
    if(!empty) return;
    empty.classList.add("sx-empty-premium");
    empty.innerHTML='<div class="sx-load-card"><div class="sx-load-orb"></div><h3>'+text+'</h3><p>SentriX récupère les rôles, salons et réglages du serveur. Cette page se remplit automatiquement.</p></div>';
  }

  function errorState(message,guildId){
    const empty=document.getElementById("emptyState");
    if(!empty) return;
    empty.classList.remove("hidden");
    empty.classList.add("sx-empty-premium");
    empty.innerHTML='<div class="sx-load-card"><div class="sx-load-orb" style="filter:saturate(.45)"></div><h3>Impossible de charger ce serveur</h3><p>'+escapeHtml(message||"Une erreur inconnue est survenue.")+'</p><button type="button" class="btn primary" id="sxRetryGuild">Réessayer</button></div>';
    document.getElementById("sxRetryGuild")?.addEventListener("click",()=>directLoadGuild(guildId,true));
  }

  function escapeHtml(value){
    return String(value ?? "").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  }

  function applyGuildData(guildId,data){
    const s=getState();
    if(!s || !data?.guild) return false;
    s.guildId=String(guildId);
    s.guildData=data;

    const select=document.getElementById("serverSelect");
    if(select && [...select.options].some(option=>String(option.value)===String(guildId))) select.value=String(guildId);

    const title=document.getElementById("pageTitle");
    const subtitle=document.getElementById("pageSubtitle");
    if(title) title.textContent=data.guild.name || "Serveur";
    if(subtitle) subtitle.textContent=`${formatNumber(data.guild.members)} membres · ${formatNumber(data.guild.channels_count)} salons · ${formatNumber(data.guild.roles_count)} rôles`;

    const metricMap={metricMembers:data.guild.members,metricCommands:data.metrics?.commands_24h,metricTickets:data.metrics?.open_tickets,metricWarnings:data.metrics?.warnings};
    for(const [id,value] of Object.entries(metricMap)){
      const el=document.getElementById(id);if(el)el.textContent=formatNumber(value);
    }

    document.getElementById("emptyState")?.classList.add("hidden");
    document.getElementById("serverContent")?.classList.remove("hidden","loading");

    const hash=(location.hash||"").replace(/^#/,"");
    try{if(hash && typeof tabs!=="undefined" && tabs[hash]) s.tab=hash;}catch(_){}
    try{if(typeof renderTab==="function") renderTab();}catch(error){console.error("SentriX render recovery",error);return false;}
    return true;
  }

  async function directLoadGuild(guildId,force=false){
    const id=String(guildId||"").trim();
    if(!id || id.startsWith("invite:") || recoveryBusy) return;
    const s=getState();
    if(!force && s?.guildData && String(s.guildId)===id){
      document.getElementById("emptyState")?.classList.add("hidden");
      document.getElementById("serverContent")?.classList.remove("hidden");
      return;
    }
    recoveryBusy=true;
    lastRecoveryGuild=id;
    loadingState("Chargement de "+(document.getElementById("serverSelect")?.selectedOptions?.[0]?.textContent||"votre serveur"));
    try{
      const response=await fetch("/api/guilds/"+encodeURIComponent(id),{cache:"no-store",credentials:"same-origin"});
      let data={};try{data=await response.json();}catch(_){}
      if(!response.ok) throw new Error(data.error||`Erreur HTTP ${response.status}`);
      if(!applyGuildData(id,data)) throw new Error("Les données du serveur ont été reçues mais leur affichage a échoué.");
      try{localStorage.setItem("sentrix:main:guild",id);}catch(_){}
    }catch(error){
      console.error("SentriX guild recovery",error);
      errorState(error?.message||"Chargement impossible.",id);
    }finally{
      recoveryBusy=false;
    }
  }

  function candidateGuild(){
    const select=document.getElementById("serverSelect");
    if(!(select instanceof HTMLSelectElement)) return "";
    const current=String(select.value||"");
    if(current && !current.startsWith("invite:")) return current;
    const first=[...select.options].find(option=>option.value && !String(option.value).startsWith("invite:"));
    return first?String(first.value):"";
  }

  async function recoverIfNeeded(){
    cleanupSidebar();beautifyServerPicker();
    const s=getState();
    if(!s || !s.user) return;
    if(s.guildData && s.guildId){
      document.getElementById("emptyState")?.classList.add("hidden");
      document.getElementById("serverContent")?.classList.remove("hidden");
      return;
    }
    const id=candidateGuild();
    if(!id) return;
    if(lastRecoveryGuild===id && recoveryBusy) return;
    await directLoadGuild(id);
  }

  document.addEventListener("change",event=>{
    if(event.target?.id!=="serverSelect") return;
    const value=String(event.target.value||"");
    if(value && !value.startsWith("invite:")) setTimeout(()=>directLoadGuild(value),450);
  },true);

  const observer=new MutationObserver(()=>{cleanupSidebar();beautifyServerPicker();});
  const start=()=>{
    cleanupSidebar();beautifyServerPicker();
    if(document.body) observer.observe(document.body,{childList:true,subtree:true});
    [260,850,1800,3600].forEach(delay=>setTimeout(recoverIfNeeded,delay));
    setInterval(()=>{cleanupSidebar();recoverIfNeeded();},5000);
  };
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",start,{once:true});
  else start();
})();
</script>
"""


def _dashboard_module():
    return sys.modules.get("web.dashboard")


def patch_dashboard_runtime(dashboard=None) -> None:
    """Make the guild payload resilient without weakening the admin/session checks."""
    global _PATCHED
    if _PATCHED:
        return
    dashboard = dashboard or _dashboard_module()
    if dashboard is None or not hasattr(dashboard, "handle_guild"):
        return

    async def resilient_handle_guild(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except (KeyError, ValueError):
            return dashboard._json_error("Identifiant de serveur invalide.", 400)

        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error

        db = request.app["bot"].db

        try:
            conf = await db.get_guild_config(guild_id)
        except Exception:
            logger.exception("Dashboard: lecture guild_config impossible pour %s", guild_id)
            conf = None

        try:
            automod = await db.get_automod(guild_id)
        except Exception:
            logger.exception("Dashboard: lecture AutoMod impossible pour %s", guild_id)
            automod = None

        ai_settings = None
        try:
            await db.execute(
                "INSERT OR IGNORE INTO ai_settings (guild_id, updated_at) VALUES (?, ?)",
                (guild_id, dashboard.now()),
            )
            ai_settings = await db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,))
        except Exception:
            logger.exception("Dashboard: lecture IA impossible pour %s", guild_id)

        try:
            metrics = await dashboard._guild_metrics(db, guild_id)
        except Exception:
            logger.exception("Dashboard: métriques impossibles pour %s", guild_id)
            metrics = {"warnings": 0, "open_tickets": 0, "profiles": 0, "economy_accounts": 0, "commands_24h": 0}

        social_notifications = []
        try:
            social_rows = await db.fetchall(
                """
                SELECT id, source_url, platform, discord_channel_id, role_id,
                       custom_text, image_url, enabled, created_at, last_checked_at
                FROM social_notifications
                WHERE guild_id = ?
                ORDER BY id DESC
                """,
                (guild_id,),
            )
            social_notifications = [dict(row) for row in social_rows]
        except Exception:
            logger.exception("Dashboard: notifications sociales impossibles pour %s", guild_id)

        roles = [
            {"id": str(role.id), "name": role.name, "color": str(role.color)}
            for role in sorted(guild.roles, key=lambda role: role.position, reverse=True)
            if not role.is_default() and not role.managed
        ]
        channels = [
            {"id": str(channel.id), "name": channel.name, "type": str(channel.type)}
            for channel in guild.channels
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel))
        ]

        return web.json_response({
            "guild": {
                "id": str(guild.id),
                "name": guild.name,
                "icon_url": str(guild.icon.url) if guild.icon else None,
                "members": guild.member_count or 0,
                "roles_count": len(guild.roles),
                "channels_count": len(guild.channels),
            },
            "settings": dict(conf) if conf else {},
            "automod": dict(automod) if automod else {},
            "ai": dict(ai_settings) if ai_settings else {},
            "social_notifications": social_notifications,
            "roles": roles,
            "channels": channels,
            "metrics": metrics,
        })

    resilient_handle_guild._sentrix_oxyde_hotfix = True
    dashboard.handle_guild = resilient_handle_guild
    _PATCHED = True
    logger.info("Dashboard Oxyde hotfix: chargement serveur fail-soft activé.")


def apply_dashboard_hotfix(html: str) -> str:
    if not isinstance(html, str):
        return html
    if 'id="sentrix-oxyde-hotfix-css"' not in html:
        html = html.replace("</head>", HOTFIX_CSS + "\n</head>", 1)
    if 'id="sentrix-oxyde-hotfix-js"' not in html:
        html = html.replace("</body>", HOTFIX_JS + "\n</body>", 1)
    return html


__all__ = ["apply_dashboard_hotfix", "patch_dashboard_runtime"]
