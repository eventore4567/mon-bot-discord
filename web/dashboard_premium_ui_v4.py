"""SentriX dashboard Premium UI V4.

Purely additive presentation layer: keeps all validated dashboard fields/routes intact while
making every section share the same polished control-center language as the new Logs mockup.
"""
from __future__ import annotations

PREMIUM_CSS = r'''
<style id="sentrix-premium-ui-v4-css">
:root{--sx-bg:#08111b;--sx-bg2:#0a1521;--sx-panel:#0c1723;--sx-panel2:#101d2b;--sx-line:#203247;--sx-line2:#2a3f56;--sx-text:#eef5ff;--sx-muted:#8fa1b7;--sx-blue:#2f9bff;--sx-green:#36d98a;--sx-red:#ff5b63;--sx-yellow:#f3c74f;--sx-purple:#8b68ff;--sx-radius:15px;--sx-shadow:0 18px 44px #0007}
html,body{background:radial-gradient(circle at 72% -20%,#102b41 0,#08111b 38%,#060d15 100%)!important;color:var(--sx-text)!important}
body{min-height:100vh}.shell{background:transparent!important}.workspace{background:transparent!important;padding:28px 30px 50px!important}
.side{background:linear-gradient(180deg,#09131e,#081019)!important;border-right:1px solid var(--sx-line)!important;box-shadow:14px 0 45px #0004}
.brand,.user{border-color:var(--sx-line)!important}.brand-logo{background:linear-gradient(145deg,#2b9dff,#1b69e8)!important;box-shadow:0 8px 24px #2189ff44}.brand span{letter-spacing:.02em}
.sentrix-nav-search,.nav-filter,input[type=search]{background:#09131e!important;border:1px solid var(--sx-line2)!important;color:var(--sx-text)!important;border-radius:12px!important;min-height:42px!important}
.nav-label{color:#75879e!important;font-size:11px!important;letter-spacing:.18em!important;font-weight:900!important;margin-top:22px!important}
.nav button{border:1px solid transparent!important;border-radius:10px!important;color:#aebbc9!important;min-height:42px!important;font-weight:720!important;transition:.16s ease!important}.nav button:hover{background:#0f1d2b!important;color:#e9f4ff!important}.nav button.active{background:linear-gradient(90deg,#102c47,#12243a)!important;color:#fff!important;border-color:#21486a!important;box-shadow:inset 3px 0 0 var(--sx-blue)!important}
.workspace-head{padding:2px 0 18px!important;border-bottom:1px solid #132538!important;margin-bottom:20px!important}.workspace-head h1,#pageTitle{font-size:30px!important;letter-spacing:-.035em!important}.workspace-head p,#pageSubtitle{color:var(--sx-muted)!important}.server-select,.select,select,input,textarea{background:#0a1521!important;border:1px solid var(--sx-line2)!important;color:var(--sx-text)!important;border-radius:10px!important}.select:focus,select:focus,input:focus,textarea:focus{outline:none!important;border-color:#2e8ee6!important;box-shadow:0 0 0 3px #268ee622!important}
.panel,.sentrix-control-card,.sentrix-control-stat,.sx-ops-card,.metric,.field-group,.field,.card{background:linear-gradient(180deg,#0e1a27,#0b1621)!important;border:1px solid var(--sx-line)!important;border-radius:var(--sx-radius)!important;box-shadow:0 10px 30px #0002!important}
.panel{padding:0!important;overflow:hidden!important}.panel-head{padding:20px 22px!important;border-bottom:1px solid var(--sx-line)!important;background:linear-gradient(180deg,#101d2a,#0d1824)!important}.panel-head h2{font-size:22px!important;letter-spacing:-.02em!important}.panel-head p{color:var(--sx-muted)!important}
.overview{gap:12px!important;margin:0 0 16px!important}.metric{padding:18px 18px!important;min-height:102px!important;position:relative!important;overflow:hidden!important}.metric:after{content:"";position:absolute;inset:auto -25px -45px auto;width:110px;height:110px;border-radius:50%;background:#2f9bff0c}.metric small{color:#9bb0c5!important;text-transform:none!important;letter-spacing:.02em!important}.metric strong{font-size:27px!important;letter-spacing:-.03em!important;margin-top:8px!important;display:block!important}
.fields{padding:18px!important;gap:14px!important}.field-group{padding:16px!important}.field{padding:16px!important}.field label,.field b{color:#dce9f6!important}.field small,.hint{color:var(--sx-muted)!important;line-height:1.45!important}
.btn{border-radius:10px!important;border:1px solid var(--sx-line2)!important;background:linear-gradient(180deg,#132437,#0e1c2a)!important;color:#eaf4ff!important;box-shadow:none!important;font-weight:760!important}.btn:hover{border-color:#376184!important;background:#162b3f!important;transform:translateY(-1px)}.btn.primary{background:linear-gradient(180deg,#2f9bff,#1979e8)!important;border-color:#3ca4ff!important;color:white!important;box-shadow:0 10px 25px #1787ff28!important}.btn.ghost{background:#0b1520!important}
.savebar{position:sticky!important;bottom:12px!important;margin:14px 18px 18px!important;padding:12px 14px!important;border:1px solid var(--sx-line2)!important;border-radius:12px!important;background:#0a1420ee!important;backdrop-filter:blur(16px)!important;box-shadow:var(--sx-shadow)!important;z-index:12!important}.save-status{color:#9aacc0!important}
.sentrix-quickbar{padding:10px 0 2px!important}.sentrix-mini-badge{background:#102d24!important;color:#78efb7!important;border-color:#1f5b47!important}
.sentrix-control-grid{gap:14px!important}.sentrix-control-card{min-height:128px!important;padding:18px!important;position:relative!important;overflow:hidden!important}.sentrix-control-card:hover{border-color:#2d6d9f!important;transform:translateY(-2px)!important;box-shadow:0 18px 36px #0005!important}.sentrix-control-card.primary{background:linear-gradient(145deg,#102943,#0d1d2d)!important;border-color:#1e5b89!important}.sentrix-control-card .icon{filter:saturate(.9)}
.sx-ops-card{padding:16px!important}.sx-ops-item{border-color:#1f3448!important;background:#0a1520!important}.sx-ops-input{background:#09141f!important;border-color:#2a4055!important}
.sentrix-premium-hero{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:4px 0 16px}.sentrix-premium-hero-main{display:flex;gap:14px;align-items:flex-start}.sentrix-premium-icon{width:50px;height:50px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(145deg,#123557,#0d2237);border:1px solid #25577d;color:#69b8ff;font-size:22px;font-weight:900;box-shadow:0 10px 26px #0004}.sentrix-premium-hero h2{font-size:30px;margin:0 0 3px;letter-spacing:-.035em}.sentrix-premium-hero p{margin:0;color:var(--sx-muted);max-width:760px}.sentrix-premium-actions{display:flex;gap:9px;flex-wrap:wrap;justify-content:flex-end}.sentrix-status-pill{display:inline-flex;align-items:center;gap:7px;padding:9px 12px;border-radius:10px;background:#0d241d;border:1px solid #1d503f;color:#66e7a8;font-size:12px;font-weight:850}.sentrix-status-pill:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--sx-green);box-shadow:0 0 10px #36d98a88}
.sentrix-premium-kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin:0 0 16px}.sentrix-premium-kpi{padding:15px 16px;border:1px solid var(--sx-line);border-radius:13px;background:linear-gradient(180deg,#0e1b28,#0a151f);min-height:92px}.sentrix-premium-kpi small{display:block;color:#9eb1c5;font-size:12px;margin-bottom:7px}.sentrix-premium-kpi strong{display:block;font-size:23px;letter-spacing:-.025em}.sentrix-premium-kpi em{font-style:normal;font-size:11px;color:#6f8297}
.sentrix-section-tabs{display:flex;gap:0;border:1px solid var(--sx-line);border-radius:12px;overflow:auto;background:#0a1520;margin:0 0 16px}.sentrix-section-tabs span{padding:10px 17px;color:#9cadc0;border-right:1px solid #172b3d;white-space:nowrap;font-size:12px;font-weight:760}.sentrix-section-tabs span.active{background:#102b44;color:#dff2ff;box-shadow:inset 0 -2px 0 var(--sx-blue)}
.sentrix-context-note{margin:0 18px 18px;padding:12px 14px;border:1px solid #173d58;border-radius:10px;background:#0a1c29;color:#89a7c0;font-size:12px}
.table-wrap,table{border-color:var(--sx-line)!important}table{background:#09141e!important}thead{background:#132338!important}th{color:#9fb3c6!important}td{border-color:#172a3d!important;color:#d7e4ef!important}tbody tr:hover{background:#0f2030!important}
.toast{background:#0c1824!important;border:1px solid #27415b!important;box-shadow:var(--sx-shadow)!important}
::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-track{background:#08111b}::-webkit-scrollbar-thumb{background:#26384a;border-radius:20px;border:2px solid #08111b}::-webkit-scrollbar-thumb:hover{background:#39526a}
@media(max-width:1200px){.sentrix-premium-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:760px){.workspace{padding:18px 14px 40px!important}.sentrix-premium-hero{flex-direction:column}.sentrix-premium-actions{justify-content:flex-start}.sentrix-premium-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.sentrix-premium-hero h2{font-size:25px}}@media(max-width:480px){.sentrix-premium-kpis{grid-template-columns:1fr}}
</style>
'''

PREMIUM_JS = r'''
<script id="sentrix-premium-ui-v4-js">
(()=>{
  "use strict";
  if(window.__sentrixPremiumV4)return;window.__sentrixPremiumV4=true;
  const meta={
    control:["CC","Centre de contrôle","Vue globale du serveur, santé, raccourcis et opérations importantes."],
    general:["CF","Configuration","Réglages essentiels, comportement général et paramètres de base."],
    security:["SE","Sécurité","AutoMod, anti-raid, anti-spam, anti-scam et protections avancées."],
    sanctions:["MO","Modération","Historique des sanctions et actions administratives sur les membres."],
    logs:["LG","Logs","Surveillez, filtrez et configurez précisément les événements de votre serveur."],
    welcome:["AD","Arrivées & départs","Bienvenue, départ, rôle automatique et messages personnalisés."],
    levels:["NV","Niveaux","Progression XP, annonces et comportement du système de niveaux."],
    tickets:["TI","Tickets","Support, catégories, transcripts, évaluations et logs des tickets."],
    ai:["AI","Intelligence artificielle","Modèle, limites, mémoire et comportement IA de SentriX."],
    notifications:["NO","Notifications","YouTube, TikTok, Twitch et autres publications automatiques."],
    roles:["RO","Rôles & salons","Associez précisément les rôles et salons utilisés par les modules."],
    community:["CO","Communauté","Suggestions, giveaways, annonces, partenaires et statistiques."],
    verification:["VE","Vérification","Règlement, vérification et attribution des rôles membre."],
    staff:["ST","Équipe & Staff","Rôles internes, signalements et outils de supervision du staff."],
    ops:["DG","Diagnostic","Santé, maintenance, historique, réparation et opérations avancées."],
    access:["AC","Accès & commandes","Contrôlez où et comment les commandes SentriX peuvent être utilisées."],
    dms:["DM","Messages privés","Gestion et supervision des messages privés envoyés par le bot."],
    embeds:["EM","Embeds & design","Construisez et prévisualisez les messages visuels du bot."]
  };
  const $=id=>document.getElementById(id), fmt=n=>Number(n||0).toLocaleString("fr-FR");
  function data(){try{return state?.guildData||null}catch(_){return null}}function tab(){try{return state?.tab||"general"}catch(_){return"general"}}
  function kpis(){const d=data(),m=d?.metrics||{},g=d?.guild||{};return [["Membres",g.members||0,"serveur"],["Commandes · 24 h",m.commands_24h||0,"activité"],["Tickets ouverts",m.open_tickets||0,"support"],["Avertissements",m.warnings||0,"modération"],["Profils XP",m.profiles||0,"niveaux"],["Comptes économie",m.economy_accounts||0,"économie"]]}
  function ensure(){const content=$("serverContent");if(!content||!data())return;let hero=$("sentrixPremiumHero");if(!hero){hero=document.createElement("div");hero.id="sentrixPremiumHero";hero.className="sentrix-premium-hero";content.insertBefore(hero,content.firstChild)}let strip=$("sentrixPremiumKpis");if(!strip){strip=document.createElement("div");strip.id="sentrixPremiumKpis";strip.className="sentrix-premium-kpis";hero.insertAdjacentElement("afterend",strip)}let tabs=$("sentrixSectionTabs");if(!tabs){tabs=document.createElement("div");tabs.id="sentrixSectionTabs";tabs.className="sentrix-section-tabs";strip.insertAdjacentElement("afterend",tabs)}render()}
  function render(){const t=tab(),info=meta[t]||["SX",(window.tabs?.[t]?.title||"SentriX"),(window.tabs?.[t]?.description||"Configuration du serveur.")],hero=$("sentrixPremiumHero"),strip=$("sentrixPremiumKpis"),nav=$("sentrixSectionTabs");if(!hero||!strip||!nav)return;hero.innerHTML=`<div class="sentrix-premium-hero-main"><div class="sentrix-premium-icon">${info[0]}</div><div><h2>${info[1]}</h2><p>${info[2]}</p></div></div><div class="sentrix-premium-actions"><span class="sentrix-status-pill">Temps réel</span><button class="btn" type="button" data-premium-action="refresh">Actualiser</button><button class="btn" type="button" data-premium-action="diagnostic">Diagnostic</button>${t==='logs'?'<button class="btn" type="button" data-premium-action="export">Exporter</button>':''}</div>`;strip.innerHTML=kpis().map(x=>`<div class="sentrix-premium-kpi"><small>${x[0]}</small><strong>${fmt(x[1])}</strong><em>${x[2]}</em></div>`).join("");const labels=t==='logs'?["Tous","Modération","Messages","Commandes","Membres","Système","Économie","Tickets","AutoMod"]:t==='security'?["Protection","Messages","Arrivées","Anti-raid","Anti-nuke"]:t==='tickets'?["Général","Catégorie","Transcripts","Évaluations","Logs"]:t==='ai'?["Général","Modèle","Limites","Mémoire","Journalisation"]:t==='notifications'?["Sources","YouTube","TikTok","Twitch","Destinations"]:["Configuration","Permissions","Aperçu","Historique"];nav.innerHTML=labels.map((x,i)=>`<span class="${i===0?'active':''}">${x}</span>`).join('')}
  document.addEventListener("click",async e=>{const b=e.target.closest?.("[data-premium-action]");if(!b)return;const a=b.dataset.premiumAction;if(a==='refresh'&&state?.guildId&&typeof selectGuild==='function'){b.disabled=true;try{await selectGuild(state.guildId)}finally{b.disabled=false}}else if(a==='diagnostic'){document.querySelector('[data-tab="ops"],[data-tab="diagnostic"]')?.click()}else if(a==='export'&&state?.guildId){try{const r=await fetch(`/api/guilds/${state.guildId}/ops/export`,{credentials:'same-origin'}),d=await r.json();if(!r.ok)throw new Error(d.error||'Export impossible');const blob=new Blob([JSON.stringify(d.config||d,null,2)],{type:'application/json'}),u=URL.createObjectURL(blob),x=document.createElement('a');x.href=u;x.download=`sentrix-${state.guildId}-config.json`;x.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}catch(err){window.toast?.(err.message,true)}}});
  const hook=()=>{try{if(typeof renderTab==='function'&&!renderTab._sentrixPremiumV4){const orig=renderTab;window.renderTab=function(){const r=orig.apply(this,arguments);setTimeout(ensure,0);return r};window.renderTab._sentrixPremiumV4=true}if(typeof selectGuild==='function'&&!selectGuild._sentrixPremiumV4){const orig=selectGuild;window.selectGuild=async function(){const r=await orig.apply(this,arguments);setTimeout(ensure,0);return r};window.selectGuild._sentrixPremiumV4=true}}catch(_){}ensure()};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',hook,{once:true});else hook();new MutationObserver(()=>ensure()).observe(document.body,{childList:true,subtree:true});
})();
</script>
'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html or "</head>" not in html or "</body>" not in html:
        return False
    if 'id="sentrix-premium-ui-v4-css"' not in html:
        html = html.replace("</head>", PREMIUM_CSS + "\n</head>", 1)
    if 'id="sentrix-premium-ui-v4-js"' not in html:
        html = html.replace("</body>", PREMIUM_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    return True
