"""Clarity pass for the SentriX dashboard.

This layer intentionally removes visual overload introduced by the major V5 pass. It keeps
all existing routes, settings, save logic and page navigation, but presents them with fewer
simultaneous concepts, larger readable controls and a simpler overview.
"""

from __future__ import annotations


CLARITY_CSS = r"""
<style id="sentrix-dashboard-v51-clarity-css">
  :root{
    --c-bg:#080a0f;
    --c-side:#0d1017;
    --c-panel:#111620;
    --c-panel-2:#151b27;
    --c-line:#293145;
    --c-line-2:#384159;
    --c-text:#f5f3fa;
    --c-muted:#9aa2b5;
    --c-purple:#8f72f6;
    --c-purple-soft:#8f72f61c;
    --c-green:#5ad79f;
    --c-amber:#f0be67;
    --c-red:#ff7589;
  }

  html,body{background:var(--c-bg)!important}
  body{font-size:15px!important;color:var(--c-text)!important}

  /* Remove the clever-but-busy controls. The sidebar itself is enough. */
  #sxV5NavSearch,.sx-v5-command-button,#sxV5Palette,.sx-v5-palette,
  .sx-v5-page-status,.sx-v5-insights,#dashboard .sx-summary{display:none!important}

  #dashboard .shell{grid-template-columns:270px minmax(0,1fr)!important}
  #dashboard .side{
    padding:0 14px 16px!important;
    background:var(--c-side)!important;
    border-right:1px solid #202738!important;
  }
  #dashboard .side .brand{
    height:78px!important;margin:0 -14px 12px!important;padding:0 20px!important;
    border-bottom:1px solid #202738!important;font-size:19px!important;
  }
  #dashboard .side .user{
    margin:6px 0 15px!important;padding:11px 12px!important;background:#121722!important;
    border:1px solid #252d40!important;border-radius:12px!important;box-shadow:none!important;
  }
  #dashboard #navigation{padding:2px 0 18px!important}
  #dashboard .sx-nav-group{
    padding:18px 11px 7px!important;color:#70788b!important;font-size:10px!important;
    letter-spacing:.12em!important;font-weight:900!important;
  }
  #dashboard #navigation button{
    min-height:44px!important;padding:10px 13px!important;border-radius:10px!important;
    color:#aeb4c4!important;font-size:13px!important;font-weight:750!important;gap:0!important;
    border:1px solid transparent!important;background:transparent!important;
  }
  #dashboard #navigation button .sx-nav-icon{display:none!important}
  #dashboard #navigation button:hover{background:#151a25!important;border-color:#242c3e!important;color:#f3f1f8!important;transform:none!important}
  #dashboard #navigation button.active{
    background:var(--c-purple-soft)!important;border-color:#4a3e6f!important;color:#fff!important;
    box-shadow:inset 3px 0 0 var(--c-purple)!important;
  }
  #dashboard .side-bottom{padding-top:12px!important;border-top:1px solid #202738!important}
  #dashboard .side-bottom .btn{min-height:39px!important;background:#141925!important;border-color:#293145!important}
  #dashboard .side-bottom .btn.primary{background:#7459dc!important;border-color:#8067df!important}

  /* Clear page chrome. */
  #dashboard .sx-topbar{
    height:64px!important;padding:0 32px!important;background:rgba(8,10,15,.94)!important;
    border-bottom:1px solid #202738!important;backdrop-filter:blur(14px)!important;
  }
  #dashboard .sx-breadcrumb{font-size:12px!important}
  #dashboard .sx-top-status{height:34px!important;background:#111620!important;border-color:#283044!important}
  #dashboard .sx-top-save{height:36px!important;border-radius:9px!important;background:#8265ed!important}

  #dashboard .workspace-head{
    padding:28px 32px 24px!important;gap:24px!important;align-items:center!important;
    border-bottom:1px solid #171c28!important;background:transparent!important;
  }
  #dashboard .workspace-head h1{font-size:30px!important;letter-spacing:-.035em!important}
  #dashboard .workspace-head p{font-size:13px!important;line-height:1.5!important;color:#8e96aa!important}
  #dashboard .server-select{height:46px!important;background:#0f131c!important;border-color:#30384d!important;font-size:14px!important}
  .sx-server-box{min-width:300px!important}
  .sx-server-box>label{font-size:10px!important;color:#848ca0!important}

  #dashboard #serverContent{padding:0 32px 74px!important;animation:none!important}
  #dashboard .fields{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:14px!important}
  #dashboard .sx-section-head{
    grid-column:1/-1!important;margin:0!important;padding:28px 0 8px!important;
    border-bottom:0!important;
  }
  #dashboard .sx-section-head small{display:none!important}
  #dashboard .sx-section-head h2{
    margin:0!important;font-size:24px!important;line-height:1.2!important;letter-spacing:-.035em!important;
    color:#f7f5fb!important;
  }
  #dashboard .sx-section-head p{
    margin:7px 0 0!important;font-size:13px!important;line-height:1.55!important;color:#8d95a8!important;
    max-width:720px!important;
  }

  /* Settings are now simple cards with readable controls. */
  #dashboard .field,#dashboard label.switch{
    min-width:0!important;padding:21px!important;border:1px solid var(--c-line)!important;
    border-radius:14px!important;background:var(--c-panel)!important;box-shadow:none!important;
    transition:border-color .13s ease,background .13s ease!important;
  }
  #dashboard .field:hover,#dashboard label.switch:hover{border-color:var(--c-line-2)!important;box-shadow:none!important;transform:none!important}
  #dashboard .field:focus-within,#dashboard label.switch:focus-within{border-color:#6551a3!important;box-shadow:0 0 0 3px rgba(143,114,246,.07)!important}
  #dashboard .field.sx-v5-configured::after{display:none!important}
  #dashboard .field.sx-v5-dirty,#dashboard label.switch.sx-v5-dirty{border-color:#6c55b5!important;box-shadow:0 0 0 3px rgba(143,114,246,.06)!important}
  #dashboard label.switch.sx-v5-enabled{background:#121a19!important;border-color:#30483e!important}
  #dashboard .field label,#dashboard label.switch b{
    color:#f1eff6!important;font-size:14px!important;font-weight:800!important;line-height:1.35!important;
  }
  #dashboard .field .hint,#dashboard label.switch span{
    margin-top:7px!important;color:#858da1!important;font-size:12px!important;line-height:1.5!important;
  }
  #dashboard .select,#dashboard input:not([type="checkbox"]),#dashboard textarea{
    margin-top:11px!important;min-height:46px!important;padding:11px 13px!important;
    border:1px solid #30384c!important;border-radius:10px!important;background:#0c1017!important;
    color:#f4f2f8!important;font-size:14px!important;
  }
  #dashboard textarea{min-height:120px!important;resize:vertical!important}
  #dashboard .select:focus,#dashboard input:focus,#dashboard textarea:focus{border-color:#725cc0!important;box-shadow:0 0 0 3px rgba(143,114,246,.08)!important}
  #dashboard label.switch{grid-column:1/-1!important;min-height:76px!important;display:flex!important;align-items:center!important;justify-content:space-between!important;gap:24px!important}
  #dashboard label.switch>div{min-width:0!important}
  #dashboard label.switch input[type="checkbox"]{flex:0 0 auto!important;width:44px!important;height:24px!important}

  #dashboard .savebar{
    margin-top:18px!important;padding:12px 14px!important;border-radius:12px!important;
    border-color:#31394e!important;background:rgba(12,15,22,.97)!important;box-shadow:0 15px 38px rgba(0,0,0,.24)!important;
  }
  #dashboard .save-status{font-size:12px!important;color:#9098aa!important}
  #dashboard .savebar .btn.primary{min-width:130px!important}

  /* Simple overview: one intro, four numbers, four clear destinations. */
  #dashboard .sx-v5-overview-hero,#dashboard .sx-v5-health,#dashboard .sx-hubs{display:none!important}
  .sx-v51-overview{display:grid;gap:18px;padding-top:26px}
  .sx-v51-head{
    display:flex;align-items:center;justify-content:space-between;gap:24px;
    padding:26px;border:1px solid #2b3348;border-radius:18px;background:#121722;
  }
  .sx-v51-server{display:flex;align-items:center;gap:16px;min-width:0}
  .sx-v51-avatar{
    width:62px;height:62px;flex:0 0 62px;border-radius:16px;overflow:hidden;display:grid;place-items:center;
    border:1px solid #4a4165;background:#211a35;color:#d7cdff;font-size:22px;font-weight:900;
  }
  .sx-v51-avatar img{width:100%;height:100%;object-fit:cover}
  .sx-v51-server h2{margin:0;font-size:25px;letter-spacing:-.035em;color:#f7f5fb}
  .sx-v51-server p{margin:7px 0 0;color:#929aad;font-size:13px;line-height:1.5}
  .sx-v51-ready{flex:0 0 auto;text-align:right}
  .sx-v51-ready small{display:block;color:#81899d;font-size:9px;font-weight:900;letter-spacing:.1em;text-transform:uppercase}
  .sx-v51-ready strong{display:block;margin-top:3px;font-size:28px;letter-spacing:-.04em;color:#cfc4ff}

  .sx-v51-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
  .sx-v51-stat{padding:18px;border:1px solid #283044;border-radius:14px;background:#10151e}
  .sx-v51-stat small{display:block;color:#7f879a;font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.07em}
  .sx-v51-stat strong{display:block;margin-top:8px;color:#f4f2f8;font-size:24px;letter-spacing:-.035em}
  .sx-v51-stat span{display:block;margin-top:3px;color:#70788b;font-size:11px}

  .sx-v51-title{margin:6px 0 -3px;font-size:18px;color:#f1eff5;letter-spacing:-.02em}
  .sx-v51-title span{display:block;margin-top:5px;color:#858da0;font-size:12px;font-weight:500;letter-spacing:0}
  .sx-v51-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
  .sx-v51-card{padding:22px;border:1px solid #293145;border-radius:15px;background:#111620}
  .sx-v51-card small{display:block;color:#a995ff;font-size:9px;font-weight:900;letter-spacing:.1em;text-transform:uppercase}
  .sx-v51-card h3{margin:7px 0 7px;font-size:18px;color:#f4f2f8;letter-spacing:-.025em}
  .sx-v51-card p{margin:0;color:#8b93a6;font-size:12px;line-height:1.55}
  .sx-v51-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}
  .sx-v51-actions button{
    min-height:38px;padding:0 13px;border:1px solid #343d53;border-radius:9px;background:#171c28;
    color:#eeeaf5;font-size:12px;font-weight:800;cursor:pointer;
  }
  .sx-v51-actions button:hover{border-color:#5b4a86;background:#1b202e}
  .sx-v51-actions button:first-child{border-color:#6650ac;background:#251e3b;color:#d6ccff}

  /* Welcome preview stays useful but does not dominate the page. */
  .sx-v5-preview-wrap{grid-template-columns:1fr!important;gap:10px!important;margin-top:4px!important}
  .sx-v5-preview-copy{display:none!important}
  .sx-v5-discord-preview{padding:18px!important;border-radius:14px!important;box-shadow:none!important}

  /* Moderation and notifications: flatter, easier to scan. */
  #dashboard .sanction-toolbar{padding:12px!important;border-radius:12px!important;background:#111620!important;box-shadow:none!important}
  #dashboard .sanction-card,#dashboard .notification-item,#dashboard .notification-empty{
    border-color:#293145!important;border-radius:13px!important;background:#111620!important;box-shadow:none!important;
  }
  #dashboard .sanction-card:hover,#dashboard .notification-item:hover{border-color:#3a435a!important}
  #dashboard .sanction-body p,#dashboard .notification-item span{color:#9199aa!important}

  #dashboard .toast{font-size:13px!important;border-radius:11px!important}

  @media(max-width:1100px){
    .sx-v51-stats{grid-template-columns:repeat(2,minmax(0,1fr))}
  }
  @media(max-width:980px){
    #dashboard .shell{grid-template-columns:1fr!important}
    #dashboard .workspace-head,#dashboard #serverContent{padding-left:20px!important;padding-right:20px!important}
    #dashboard .sx-topbar{padding-left:20px!important;padding-right:20px!important}
    #dashboard .fields{grid-template-columns:1fr!important}
    #dashboard .field.full,#dashboard label.switch{grid-column:auto!important}
    .sx-v51-grid{grid-template-columns:1fr}
  }
  @media(max-width:680px){
    #dashboard .workspace-head h1{font-size:26px!important}
    .sx-v51-head{display:grid;padding:20px}.sx-v51-ready{text-align:left}.sx-v51-avatar{width:54px;height:54px;flex-basis:54px;border-radius:14px}
    .sx-v51-stats{grid-template-columns:1fr 1fr}.sx-v51-stat{padding:15px}.sx-v51-stat strong{font-size:21px}
    .sx-v51-card{padding:18px}.sx-v51-actions{display:grid;grid-template-columns:1fr 1fr}.sx-v51-actions button{padding:0 8px}
    #dashboard label.switch{gap:14px!important;padding:18px!important}
  }
  @media(max-width:430px){.sx-v51-stats{grid-template-columns:1fr}.sx-v51-actions{grid-template-columns:1fr}}
</style>
"""


CLARITY_JS = r"""
<script id="sentrix-dashboard-v51-clarity-js">
(() => {
  "use strict";
  if(window.__sentrixDashboardV51Clarity)return;
  window.__sentrixDashboardV51Clarity=true;

  const copy={
    general:["Général","Les réglages principaux de SentriX pour ce serveur."],
    security:["Sécurité","Activez uniquement les protections dont votre serveur a besoin."],
    sanctions:["Sanctions","Retrouvez les bannissements, mutes et avertissements au même endroit."],
    logs:["Logs","Choisissez où SentriX doit envoyer chaque type de journal."],
    welcome:["Accueil","Configurez les messages d’arrivée, de départ et le rôle automatique."],
    levels:["Niveaux","Réglez l’expérience et les annonces de montée de niveau."],
    tickets:["Tickets","Configurez simplement le support et les fermetures de tickets."],
    ai:["Intelligence artificielle","Choisissez le modèle, les limites et la mémoire de SentriX."],
    notifications:["Notifications","Publiez automatiquement les nouvelles vidéos et publications."],
    embeds:["Embeds","Créez des messages Discord propres avec l’éditeur SentriX."],
    roles:["Rôles et salons","Reliez SentriX aux rôles et salons déjà présents sur Discord."]
  };

  const getState=()=>{try{return typeof state!=="undefined"?state:null}catch(_){return null}};
  const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const fmt=value=>Number(value||0).toLocaleString("fr-FR");
  const isSet=value=>value!==null&&value!==undefined&&value!==""&&value!==0&&value!==false;

  function completion(s){
    const settings=s.guildData?.settings||{},automod=s.guildData?.automod||{},ai=s.guildData?.ai||{};
    const logs=["log_messages","log_members","log_voice","log_roles","log_server","log_automod","log_moderation","log_channel"].filter(k=>isSet(settings[k])).length;
    const protections=["antispam","antilink","antiinvite","antimention","anticaps","antiemoji","antiraid","antibot","antiaccount","antiscam","antinuke","escalation"].filter(k=>Number(automod[k])).length;
    const checks=[isSet(settings.prefix),logs>0,protections>=3,isSet(settings.welcome_channel),isSet(settings.mod_role)||isSet(settings.admin_role),isSet(settings.ticket_category)||isSet(settings.ticket_log_channel),isSet(settings.level_channel),Number(ai.enabled)===1];
    return Math.round(checks.filter(Boolean).length/checks.length*100);
  }

  function go(key){
    const button=document.querySelector('#navigation button[data-tab="'+CSS.escape(key)+'"]');
    if(button)button.click();
  }

  function renderOverview(){
    const s=getState();if(!s?.guildData||s.tab!=="overview")return;
    const host=document.querySelector("#fields>.sx-overview,#fields .sx-overview");if(!host)return;
    const guild=s.guildData.guild||{},metrics=s.guildData.metrics||{};
    const score=completion(s);
    const first=String(guild.name||"S").trim().slice(0,1).toUpperCase();
    const icon=guild.icon_url?'<img src="'+esc(guild.icon_url)+'" alt="">':esc(first);
    const latency=s.publicData?.latency_ms==null?"—":fmt(s.publicData.latency_ms)+" ms";
    host.innerHTML='<div class="sx-v51-overview">'
      +'<section class="sx-v51-head"><div class="sx-v51-server"><div class="sx-v51-avatar">'+icon+'</div><div><h2>'+esc(guild.name||"Votre serveur")+'</h2><p>Choisissez simplement la partie que vous voulez modifier. Chaque bouton ouvre une page séparée.</p></div></div><div class="sx-v51-ready"><small>Configuration</small><strong>'+score+'%</strong></div></section>'
      +'<section class="sx-v51-stats">'
      +'<article class="sx-v51-stat"><small>Membres</small><strong>'+fmt(guild.members)+'</strong><span>sur le serveur</span></article>'
      +'<article class="sx-v51-stat"><small>Tickets ouverts</small><strong>'+fmt(metrics.open_tickets)+'</strong><span>à traiter</span></article>'
      +'<article class="sx-v51-stat"><small>Avertissements</small><strong>'+fmt(metrics.warnings)+'</strong><span>enregistrés</span></article>'
      +'<article class="sx-v51-stat"><small>Latence</small><strong>'+latency+'</strong><span>connexion Discord</span></article>'
      +'</section>'
      +'<h3 class="sx-v51-title">Que voulez-vous configurer ?<span>Les réglages sont rangés en quatre parties simples.</span></h3>'
      +'<section class="sx-v51-grid">'
      +'<article class="sx-v51-card"><small>PROTECTION</small><h3>Sécurité et modération</h3><p>Anti-spam, anti-liens, sanctions et salons de logs.</p><div class="sx-v51-actions"><button data-v51-go="security">Sécurité</button><button data-v51-go="sanctions">Sanctions</button><button data-v51-go="logs">Logs</button></div></article>'
      +'<article class="sx-v51-card"><small>COMMUNAUTÉ</small><h3>Accueil et progression</h3><p>Messages de bienvenue, rôle automatique et niveaux.</p><div class="sx-v51-actions"><button data-v51-go="welcome">Accueil</button><button data-v51-go="levels">Niveaux</button><button data-v51-go="roles">Rôles et salons</button></div></article>'
      +'<article class="sx-v51-card"><small>SUPPORT</small><h3>Tickets</h3><p>Catégorie, logs, transcript et évaluation du support.</p><div class="sx-v51-actions"><button data-v51-go="tickets">Configurer les tickets</button></div></article>'
      +'<article class="sx-v51-card"><small>OUTILS</small><h3>IA et publications</h3><p>Intelligence artificielle, notifications sociales et embeds.</p><div class="sx-v51-actions"><button data-v51-go="ai">IA</button><button data-v51-go="notifications">Notifications</button><button data-v51-go="embeds">Embeds</button></div></article>'
      +'</section></div>';
    host.querySelectorAll("[data-v51-go]").forEach(button=>button.addEventListener("click",()=>go(button.dataset.v51Go)));
  }

  function simplifyPage(){
    const s=getState();if(!s?.guildData)return;
    document.body.dataset.tab=String(s.tab||"overview");
    if(s.tab==="overview"){renderOverview();return;}
    const heading=document.querySelector("#fields .sx-section-head");
    const data=copy[s.tab];
    if(heading&&data){
      const h2=heading.querySelector("h2"),p=heading.querySelector("p");
      if(h2)h2.textContent=data[0];
      if(p)p.textContent=data[1];
    }
  }

  let timer=null;
  function schedule(delay=20){clearTimeout(timer);timer=setTimeout(simplifyPage,delay)}

  document.addEventListener("click",event=>{
    if(event.target?.closest?.("#navigation button[data-tab]"))schedule(35);
  },true);
  document.addEventListener("change",event=>{if(event.target?.id==="serverSelect")schedule(250)},true);

  const observer=new MutationObserver(()=>schedule(15));
  function start(){
    const fields=document.getElementById("fields");if(fields)observer.observe(fields,{childList:true,subtree:false});
    [0,120,500,1200,2500].forEach(delay=>setTimeout(simplifyPage,delay));
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();
})();
</script>
"""


def apply_clarity_v51(html: str) -> str:
    if not isinstance(html, str):
        return html
    if 'id="sentrix-dashboard-v51-clarity-css"' not in html:
        html = html.replace("</head>", CLARITY_CSS + "\n</head>", 1)
    if 'id="sentrix-dashboard-v51-clarity-js"' not in html:
        html = html.replace("</body>", CLARITY_JS + "\n</body>", 1)
    return html


__all__ = ["apply_clarity_v51"]
