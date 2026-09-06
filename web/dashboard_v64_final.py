"""SentriX V64 — verrou de navigation du dashboard final.

V61 garde encore un renderer de compatibilité qui reconstruit son ancienne sidebar lorsqu'une
page historique (Accueil, Logs, IA, etc.) est affichée. V62 reconstruit la bonne sidebar avant
cet appel, mais V61 pouvait ensuite l'écraser. V64 est la dernière couche et réaffirme la
navigation finale APRÈS chaque rendu, sans toucher aux API ni aux données métier.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-v64-final")

CSS = r'''
/* V64 : navigation finale et suppression des vestiges vides */
.sx-empty-filter{display:none!important}
.navigation{padding-bottom:30px}
.navigation .sx-nav-tools{padding:8px 12px 4px}
.navigation .sx-nav-search{width:100%;border:1px solid #454d55;background:#252a2f;color:#eef3f7;border-radius:6px;padding:9px 10px;outline:0}
.navigation .sx-nav-search:focus{border-color:var(--sx-blue,#4da3ff);box-shadow:0 0 0 2px #4da3ff18}
#fields .action-grid:empty,#fields .sx-unified-grid:empty{display:none!important}
#fields .action-card a[href^="/"],#fields a[href="/setup-center"],#fields a[href="/feature-suite"],#fields a[href="/community"],#fields a[href="/operations"]{display:none!important}
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
  let lastSearch='';
  function normalize(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('fr')}
  function filterNav(nav){const q=normalize(lastSearch).trim();nav.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('sx-empty-filter',Boolean(q)&&!normalize(b.textContent).includes(q)));nav.querySelectorAll('.sx-nav-group').forEach(group=>{let node=group.nextElementSibling,visible=false;while(node&&!node.classList.contains('sx-nav-group')){if(node.matches?.('button[data-tab]')&&!node.classList.contains('sx-empty-filter'))visible=true;node=node.nextElementSibling}group.style.display=visible?'':'none'})}
  function lockNavigation(){
    const nav=$('navigation');if(!nav)return;
    const currentInput=nav.querySelector('#sxNavSearch');if(currentInput)lastSearch=currentInput.value||lastSearch;
    nav.innerHTML='<div class="sx-nav-tools"><input id="sxNavSearch" class="sx-nav-search" type="search" placeholder="Rechercher une fonction…" aria-label="Rechercher une fonction"></div>'+FINAL_GROUPS.map(([label,items])=>`<div class="sx-nav-group">${label}</div>`+items.map(([tab,label,icon])=>`<button type="button" data-tab="${tab}" class="${state.tab===tab?'active':''}"><span class="nav-icon">${icon}</span>${label}</button>`).join('')).join('');
    const input=nav.querySelector('#sxNavSearch');input.value=lastSearch;input.addEventListener('input',event=>{lastSearch=event.target.value;filterNav(nav)});filterNav(nav);
  }
  function stripExternalCards(){
    document.querySelectorAll('#fields a[href],#fields button').forEach(el=>{
      const text=(el.textContent||'').trim().toLocaleLowerCase('fr');
      if(['ouvrir','configuration avancée','éditeur complet','etat du service','état du service'].includes(text))el.remove();
    });
  }
  const beforeV64=renderTab;
  renderTab=function(){const result=beforeV64();setTimeout(()=>{lockNavigation();stripExternalCards()},0);return result};
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
    logger.info("Dashboard V64 final installé : sidebar dense verrouillée après tous les renderers hérités.")
    return True


__all__ = ["install"]
