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
/* V64 : navigation finale, thème corail SentriX et suppression des vestiges vides */
:root{
  /* Certaines couches V62/V63 utilisaient encore un alias bleu. V64 est injecté en dernier :
     il le remappe vers l'accent corail demandé pour que /app reste visuellement uniforme. */
  --sx-blue:var(--accent,#d66f55);
  --sx-blue2:var(--accent2,#ef8568);
}
.sx-empty-filter{display:none!important}
.navigation{padding-bottom:30px}
.navigation .sx-nav-tools{padding:8px 12px 4px}
.navigation .sx-nav-search{width:100%;border:1px solid #454d55;background:#252a2f;color:#eef3f7;border-radius:6px;padding:9px 10px;outline:0}
.navigation .sx-nav-search:focus{border-color:var(--accent,#d66f55);box-shadow:0 0 0 2px #d66f5524}
#fields .action-grid:empty,#fields .sx-unified-grid:empty{display:none!important}
#fields .action-card a[href^="/"],#fields a[href="/setup-center"],#fields a[href="/feature-suite"],#fields a[href="/community"],#fields a[href="/operations"]{display:none!important}

/* Les CTA ajoutés par V62/V63 doivent suivre la même identité que le shell V60. */
.btn.blue{background:var(--accent,#d66f55)!important;border-color:var(--accent,#d66f55)!important;color:#fff!important}
.btn.blue:hover{background:var(--accent2,#ef8568)!important;border-color:var(--accent2,#ef8568)!important}
.sx-v63-hero-main{border-color:#785044!important;background:linear-gradient(135deg,#34302f,#2f2c2c)!important}
.sx-v63-chip.blue{border-color:#785044!important;background:#3d2d29!important;color:#ffd4c7!important}
.sx-v62-card.info{border-color:#69483f!important}
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
    logger.info("Dashboard V64 final installé : sidebar dense stable, thème corail final et restauration uniquement si une couche héritée remplace la navigation.")
    return True


__all__ = ["install"]
