"""Garde-fous runtime du dashboard V60.

Cette couche finale traite les trois cas qui avaient historiquement produit un écran vide :
une landing visible pendant l'authentification, une ancienne requête serveur qui termine après
la nouvelle, et un état d'onglet invalide conservé dans le navigateur.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-v60-bootguard")

_GUARD_JS = r'''
<script id="sentrix-v60-bootguard">
(() => {
  "use strict";
  if(window.__sentrixV60Bootguard)return;window.__sentrixV60Bootguard=true;

  state.guildAbort = null;
  state.guildRetryTimer = null;

  function showGuildFailure(message,retryValue){
    $("serverContent")?.classList.add("hidden");
    const empty=$("emptyState");
    if(!empty)return;
    empty.classList.remove("hidden");
    empty.innerHTML=`<b>${esc(message)}</b>${retryValue?'<br><button id="sentrixV60RetryGuild" class="btn primary" type="button" style="margin-top:12px">Réessayer</button>':''}`;
    if(retryValue)$("sentrixV60RetryGuild")?.addEventListener("click",()=>selectGuild(retryValue),{once:true});
  }

  function applyGuildGuarded(raw,data){
    state.guildId=raw;state.guildData=data;state.dirty=false;
    try{localStorage.setItem("sentrix:v60:guild",raw)}catch(_){}
    const g=data.guild||{};
    $("pageTitle").textContent=g.name||"Serveur";
    $("pageSubtitle").textContent=`${number(g.members)} membres · ${number(g.channels_count)} salons · ${number(g.roles_count)} rôles`;
    $("guildName").textContent=g.name||"Serveur";
    $("guildMembers").textContent=`${number(g.members)} membres`;
    $("guildLogo").innerHTML=g.icon_url?`<img src="${esc(g.icon_url)}" alt="">`:esc((g.name||"S").slice(0,2).toUpperCase());
    $("metricMembers").textContent=number(g.members);
    $("metricCommands").textContent=number(data.metrics?.commands_24h);
    $("metricTickets").textContent=number(data.metrics?.open_tickets);
    $("metricWarnings").textContent=number(data.metrics?.warnings);
    $("emptyState").classList.add("hidden");
    $("serverContent").classList.remove("hidden");
    renderGuildRail();renderTab();
  }

  // Une seule requête de serveur peut gagner. Changer rapidement de serveur annule la
  // précédente au lieu de laisser une réponse obsolète écraser l'interface courante.
  selectGuild=async function(value){
    if(!value)return;
    const raw=String(value);
    if(raw.startsWith("invite:")){
      const id=raw.slice(7),g=state.guilds.find(x=>String(x.id)===id);
      if(g?.invite_url)location.href=g.invite_url;
      return;
    }
    if(state.guildAbort)state.guildAbort.abort();
    state.guildAbort = new AbortController();
    const controller=state.guildAbort;
    if(state.guildRetryTimer){clearTimeout(state.guildRetryTimer);state.guildRetryTimer=null;}
    $("serverContent").classList.add("hidden");
    $("emptyState").classList.remove("hidden");
    $("emptyState").textContent="Chargement du serveur…";
    try{
      const data=await api(`/api/guilds/${encodeURIComponent(raw)}`,{signal:controller.signal});
      if(controller!==state.guildAbort||controller.signal.aborted)return;
      applyGuildGuarded(raw,data);
    }catch(e){
      if(e?.name==="AbortError"||controller.signal.aborted)return;
      if(e.status===503){
        showGuildFailure("Reconnexion Discord en cours…",raw);
        state.guildRetryTimer=setTimeout(()=>{if(String($("serverSelect")?.value||"")===raw)selectGuild(raw)},2500);
        return;
      }
      if(e.status===401){
        $("dashboard")?.classList.add("hidden");
        $("landing")?.classList.remove("hidden");
        toast("Votre session Discord a expiré. Reconnectez-vous.",true);
        return;
      }
      showGuildFailure(e.message||"Impossible de charger ce serveur.",raw);
      toast(e.message||"Chargement impossible.",true);
    }
  };

  const renderTabBeforeGuard=renderTab;
  renderTab=function(){
    const special=new Set(["overview","access","dm"]);
    if(!special.has(state.tab)&&!tabMeta[state.tab])state.tab="general";
    return renderTabBeforeGuard();
  };

  // Si /api/me est lent, la landing reste masquée. Elle n'est révélée que si loadSession
  // confirme ensuite que la session est absente/expirée.
  $("landing")?.classList.add("hidden");
})();
</script>
'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v60-bootguard"' in html:
        return True
    if not str(getattr(dashboard, "_sentrix_dashboard_version", "")).startswith("v60"):
        return False

    # Masqué dès le document reçu par le navigateur : aucun flash de landing avant /api/me.
    html = html.replace('<section id="landing" class="landing">', '<section id="landing" class="landing hidden">', 1)
    html = html.replace("</body>", _GUARD_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    dashboard._sentrix_dashboard_version = "v60-max-suite-guarded"
    logger.info("Dashboard V60 : boot guard installé (landing, AbortController, 401/503, onglets invalides).")
    return True


__all__ = ["install"]
