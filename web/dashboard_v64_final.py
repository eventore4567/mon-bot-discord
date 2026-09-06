"""SentriX V64 — verrou de navigation du dashboard final.

V61 garde encore un renderer de compatibilité qui reconstruit son ancienne sidebar lorsqu'une
page historique (Accueil, Logs, IA, etc.) est affichée. V62 reconstruit la bonne sidebar avant
cet appel. V64 est la dernière couche : elle restaure la navigation finale seulement si une
couche héritée l'a réellement remplacée, puis ne fait plus que synchroniser l'état actif.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-v64-final")

CSS = r'''
/* V64 : navigation finale, détails bleus SentriX et suppression des vestiges vides */
:root{
  /* Le shell garde le charbon/corail demandé, mais les détails fonctionnels bleus
     différencient clairement SentriX du modèle de référence. */
  --sx-blue:#4da3ff;
  --sx-blue2:#78bdff;
}
.sx-empty-filter{display:none!important}
.navigation{padding-bottom:30px}
.navigation .sx-nav-tools{padding:8px 12px 4px}
.navigation .sx-nav-search{width:100%;border:1px solid #454d55;background:#252a2f;color:#eef3f7;border-radius:6px;padding:9px 10px;outline:0}
.navigation .sx-nav-search:focus{border-color:var(--sx-blue,#4da3ff);box-shadow:0 0 0 2px #4da3ff24}
#fields .action-grid:empty,#fields .sx-unified-grid:empty{display:none!important}
#fields .action-card a[href^="/"],#fields a[href="/setup-center"],#fields a[href="/feature-suite"],#fields a[href="/community"],#fields a[href="/operations"]{display:none!important}

/* Les éléments explicitement bleus de V62/V63 restent bleus : boutons secondaires,
   cartes d'information, aperçu et états utiles. Le corail reste réservé au branding et
   aux actions principales du shell. */
.btn.blue{background:var(--sx-blue,#4da3ff)!important;border-color:var(--sx-blue,#4da3ff)!important;color:#fff!important}
.btn.blue:hover{background:var(--sx-blue2,#78bdff)!important;border-color:var(--sx-blue2,#78bdff)!important}
.sx-v63-hero-main{border-color:#3f709b!important;background:linear-gradient(135deg,#2c333b,#263646)!important}
.sx-v63-chip.blue{border-color:#35688f!important;background:#1d3045!important;color:#d8ebff!important}
.sx-v62-card.info{border-color:#3f709b!important}

/* Responsive final : les anciennes couches ont plusieurs grilles différentes. Ces règles
   sont injectées en dernier afin qu'aucune carte ne déborde sur tablette/mobile. */
@media(max-width:1180px){
  .workspace{padding:26px 24px 58px!important}
  .sx-v63-hero{grid-template-columns:1fr!important}
  .sx-v63-economy{grid-template-columns:1fr 1fr!important}
  .sx-v63-economy>:first-child{grid-column:1/-1!important}
  .sx-v62-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .sx-v62-grid>.full{grid-column:1/-1!important}
}
@media(max-width:820px){
  html,body{overflow-x:hidden!important}
  .topbar{padding-left:14px!important;padding-right:14px!important}
  .shell{grid-template-columns:58px minmax(0,1fr)!important}
  .sidebar{left:58px!important;width:min(86vw,300px)!important;max-width:300px!important}
  .workspace{grid-column:2!important;min-width:0!important;width:100%!important;max-width:100vw!important;padding:20px 14px 48px!important;overflow-x:hidden!important}
  .workspace-head{gap:12px!important;margin-bottom:16px!important}
  .workspace-head h1{font-size:25px!important}
  .metrics{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:8px!important}
  .grid2,.embed-builder,.fields-grid,.action-grid,.sx-v62-grid,.sx-v63-modules,.sx-v63-palette,.sx-v63-economy{grid-template-columns:1fr!important}
  .sx-v62-grid>.full,.sx-v63-economy>:first-child,.field.full{grid-column:auto!important}
  .panel,.panel-section,.sx-v62-card,.sx-v63-module,.action-card,.list-row{min-width:0!important;max-width:100%!important}
  #fields input,#fields select,#fields textarea{max-width:100%!important;min-width:0!important}
  .list-row,.sanction-row{grid-template-columns:1fr!important;align-items:stretch!important}
  .sx-v63-save,.savebar{flex-wrap:wrap!important}
  .sx-v63-discord{min-height:150px!important}
}
@media(max-width:540px){
  .topbar{height:66px!important;padding:0 10px!important}
  .brand{font-size:17px!important;gap:8px!important}
  .brand-mark{width:30px!important;height:30px!important}
  .shell{min-height:calc(100vh - 66px)!important;grid-template-columns:52px minmax(0,1fr)!important}
  .server-rail{padding:10px 5px!important}
  .rail-guild,.rail-add{width:42px!important;height:42px!important}
  .sidebar{left:52px!important;top:66px!important;width:min(88vw,292px)!important;max-width:292px!important}
  .workspace{padding:16px 10px 42px!important}
  .workspace-head{flex-direction:column!important;align-items:stretch!important}
  .workspace-head h1{font-size:23px!important}
  .runtime-pill{display:none!important}
  .metrics{grid-template-columns:1fr!important}
  .metric{padding:10px 12px!important}
  .panel-section{padding:14px 11px!important}
  .content-head h2{font-size:21px!important}
  .sx-v63-save,.savebar{flex-direction:column!important;align-items:stretch!important}
  .sx-v63-save .btn,.savebar .btn{width:100%!important}
  .sx-v63-palette,.sx-v63-modules{grid-template-columns:1fr!important}
  #fields button,#fields .btn{max-width:100%!important}
}
'''

JS = r'''
<script id="sentrix-v64-final">
(() => {
  "use strict";
  if(window.__sentrixV64Final)return;window.__sentrixV64Final=true;
  const FINAL_GROUPS=[
    ["Général",[["overview","Vue d’ensemble","▦"],["welcome","Arrivées et départs","▤"],["messages","Messages","☷"],["levels","Niveaux","↗"]]],
    ["Membres & rôles",[["roles","Rôles automatiques","▣"],["secure_roles","Rôles sécurisés","◆"],["reaction_roles","Rôles-réactions","☷"],["verification","Vérification & règlement","✓"]]],
    ["Modération",[["sanctions","Modération","⌁"],["security","Auto-Modération","◇"],["reports","Signalements","⚑"],["logs","Logs","◔"]]],
    ["Communauté",[["economy","Économie","$"],["suggestions","Suggestions","●"],["notifications","Notifications sociales","◖"]]],
    ["Outils",[["tickets","Tickets","▰"],["ai","Intelligence artificielle","AI"],["embeds","Embeds","E"],["games","Mini-jeux","◆"],["design","Design","◫"]]],
    ["Configuration",[["setup","Configuration serveur","⚙"],["access","Accès & commandes","⌘"],["dm","Messages privés","✉"],["status","Statut SentriX","●"]]],
  ];
  const FINAL_TABS=new Set(FINAL_GROUPS.flatMap(([,items])=>items.map(([tab])=>tab)));
  let lastSearch='';
  function normalize(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('fr')}
  function filterNav(nav){const q=normalize(lastSearch).trim();nav.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('sx-empty-filter',Boolean(q)&&!normalize(b.textContent).includes(q)));nav.querySelectorAll('.sx-nav-group').forEach(group=>{let node=group.nextElementSibling,visible=false;while(node&&!node.classList.contains('sx-nav-group')){if(node.matches?.('button[data-tab]')&&!node.classList.contains('sx-empty-filter'))visible=true;node=node.nextElementSibling}group.style.display=visible?'':'none'})}
  function finalNavPresent(nav){const tabs=[...nav.querySelectorAll('button[data-tab]')].map(b=>b.dataset.tab);return tabs.length===FINAL_TABS.size&&tabs.every(tab=>FINAL_TABS.has(tab))&&Boolean(nav.querySelector('.sx-nav-group'))}
  function syncNavigation(nav){nav.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.tab));filterNav(nav)}
  function bindNavigation(nav){
    if(nav.dataset.v64Bound==='1')return;nav.dataset.v64Bound='1';
    nav.addEventListener('click',event=>{
      const button=event.target.closest?.('button[data-tab]');if(!button||!nav.contains(button))return;
      event.preventDefault();event.stopImmediatePropagation();
      state.tab=button.dataset.tab;
      nav.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('active',b===button));
      try{localStorage.setItem('sentrix:v61:tab',state.tab)}catch(_){}
      renderTab();
      try{history.replaceState({},'',`/app?tab=${encodeURIComponent(state.tab)}&guild=${encodeURIComponent(state.guildId||'')}`)}catch(_){}
      if(innerWidth<821)$('sidebar')?.classList.remove('open');
    },true);
  }
  function buildNavigation(nav){
    const currentInput=nav.querySelector('#sxNavSearch');if(currentInput)lastSearch=currentInput.value||lastSearch;
    nav.innerHTML='<div class="sx-nav-tools"><input id="sxNavSearch" class="sx-nav-search" type="search" placeholder="Rechercher une fonction…" aria-label="Rechercher une fonction"></div>'+FINAL_GROUPS.map(([label,items])=>`<div class="sx-nav-group">${label}</div>`+items.map(([tab,label,icon])=>`<button type="button" data-tab="${tab}" class="${state.tab===tab?'active':''}"><span class="nav-icon">${icon}</span>${label}</button>`).join('')).join('');
    const input=nav.querySelector('#sxNavSearch');input.value=lastSearch;input.addEventListener('input',event=>{lastSearch=event.target.value;filterNav(nav)});filterNav(nav);
  }
  function lockNavigation(){const nav=$('navigation');if(!nav)return;bindNavigation(nav);if(finalNavPresent(nav)){syncNavigation(nav);return}buildNavigation(nav)}
  function stripExternalCards(){
    document.querySelectorAll('#fields a[href],#fields button').forEach(el=>{
      const text=(el.textContent||'').trim().toLocaleLowerCase('fr');
      if(['ouvrir','configuration avancée','éditeur complet','etat du service','état du service'].includes(text))el.remove();
    });
  }
  const beforeV64=renderTab;
  renderTab=function(){const result=beforeV64();lockNavigation();stripExternalCards();return result};
  lockNavigation();stripExternalCards();
})();
</script>
'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v64-final"' in html:
        return True
    if 'id="sentrix-v63-polish"' not in html:
        logger.error("V64 refusé : V63 polish absent.")
        return False
    if "</style>" not in html or "</body>" not in html:
        return False
    dashboard.INDEX_HTML = html.replace("</style>", CSS + "\n</style>", 1).replace("</body>", JS + "\n</body>", 1)
    dashboard._sentrix_dashboard_version = "v64-final"
    logger.info("Dashboard V64 final installé : navigation stable, détails bleus SentriX et responsive mobile/tablette verrouillé.")
    return True


__all__ = ["install"]
