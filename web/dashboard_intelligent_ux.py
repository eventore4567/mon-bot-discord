"""SentriX V2.4 — recherche/actions rapides du dashboard, 100 % côté client.

Aucune route ni permission n'est ajoutée. La recherche ne fait qu'orienter vers les centres
déjà existants, avec raccourci clavier, cibles tactiles et libellés accessibles.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-intelligent-ux")
_INSTALLED = False

CSS = r"""
<style id="sentrix-v24-intelligent-css">
  .sx-v24-quick{margin:12px 0 16px;padding:14px;border:1px solid var(--line);border-radius:14px;background:#0f1524}
  .sx-v24-quick-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}
  .sx-v24-quick h3{margin:0;font-size:15px}.sx-v24-quick small{color:var(--muted)}
  .sx-v24-search{display:flex;gap:8px;align-items:center}
  .sx-v24-search input{flex:1;min-width:0;border:1px solid #33405f;border-radius:10px;background:#0b1020;color:var(--text);padding:11px 12px}
  .sx-v24-results{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-top:9px}
  .sx-v24-result{border:1px solid #2d3856;border-radius:10px;background:#121a2b;color:var(--text);padding:10px;text-align:left;cursor:pointer;min-height:48px}
  .sx-v24-result b,.sx-v24-result span{display:block}.sx-v24-result span{margin-top:2px;color:var(--muted);font-size:10px}
  .sx-v24-result:hover{border-color:#6373aa}.sx-v24-result:focus-visible{outline:2px solid #fff;outline-offset:2px}
  @media(max-width:800px){.sx-v24-results{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:520px){.sx-v24-quick-head{display:grid}.sx-v24-results{grid-template-columns:1fr}.sx-v24-result{min-height:52px}}
</style>
"""

JS = r"""
<script id="sentrix-v24-intelligent-js">
(() => {
  "use strict";
  if (window.__sentrixV24IntelligentUX) return;
  window.__sentrixV24IntelligentUX = true;

  const ACTIONS = [
    {label:"Centre staff",words:"staff moderation sanctions dossiers membres ban mute",path:"/operations",desc:"Modération et diagnostics"},
    {label:"Tickets",words:"ticket tickets support claim transcript",path:"/operations",desc:"Support et suivi"},
    {label:"Sécurité",words:"securite security automod raid antinuke blacklist",path:"/setup-center",desc:"Protections du serveur"},
    {label:"Configuration",words:"configuration setup roles salons logs welcome",path:"/setup-center",desc:"Réglages du serveur"},
    {label:"Économie",words:"economie economy argent monnaie shop boutique niveaux xp",path:"/engagement",desc:"Économie et progression"},
    {label:"Communauté",words:"communaute membres croissance invites activite",path:"/community",desc:"Croissance et activité"},
    {label:"IA",words:"ia ai intelligence assistant openai",path:"/setup-center",desc:"Réglages IA"},
    {label:"Engagement",words:"engagement retention jeux niveaux reputation",path:"/engagement",desc:"Rétention et activité"}
  ];

  const norm = value => String(value||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
  const guildId = () => {try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):"";}catch(_){return "";}};
  const go = path => {const gid=guildId();location.href=path+(gid?"?guild="+encodeURIComponent(gid):"");};

  function matches(query){
    const q=norm(query);
    if(!q)return ACTIONS.slice(0,4);
    const terms=q.split(/\s+/).filter(Boolean);
    return ACTIONS.map(action=>{
      const hay=norm(action.label+" "+action.words+" "+action.desc);
      const score=terms.reduce((n,term)=>n+(hay.includes(term)?1:0),0);
      return {action,score};
    }).filter(item=>item.score>0).sort((a,b)=>b.score-a.score).slice(0,6).map(item=>item.action);
  }

  function render(section,input,results){
    const list=matches(input.value);
    results.innerHTML=list.map((a,i)=>`<button type="button" class="sx-v24-result" data-v24-path="${a.path}" aria-label="${a.label}: ${a.desc}"><b>${a.label}</b><span>${a.desc}</span></button>`).join("") || '<small>Aucun raccourci trouvé. Essaie « tickets », « sécurité » ou « économie ».</small>';
    section.querySelectorAll("[data-v24-path]").forEach(btn=>btn.addEventListener("click",()=>go(btn.dataset.v24Path)));
  }

  function ensure(){
    if(document.getElementById("sxV24Quick"))return;
    const home=document.getElementById("sxSimpleHome") || document.querySelector("main") || document.querySelector(".main-content,.content");
    if(!home)return;
    const section=document.createElement("section");section.id="sxV24Quick";section.className="sx-v24-quick";section.setAttribute("aria-label","Recherche rapide du dashboard");
    section.innerHTML='<div class="sx-v24-quick-head"><div><h3>Accès rapide</h3><small>Recherche un système sans parcourir tous les menus.</small></div><small>Raccourci : /</small></div><div class="sx-v24-search"><input id="sxV24Search" type="search" autocomplete="off" placeholder="Tickets, sécurité, économie, IA…" aria-label="Rechercher un système du dashboard"></div><div id="sxV24Results" class="sx-v24-results" aria-live="polite"></div>';
    home.prepend(section);
    const input=section.querySelector("#sxV24Search"),results=section.querySelector("#sxV24Results");
    render(section,input,results);
    input.addEventListener("input",()=>render(section,input,results));
    input.addEventListener("keydown",event=>{if(event.key==="Enter"){const first=section.querySelector("[data-v24-path]");if(first){event.preventDefault();first.click();}}});
  }

  document.addEventListener("keydown",event=>{
    if(event.key!=="/"||event.ctrlKey||event.metaKey||event.altKey)return;
    const tag=(document.activeElement&&document.activeElement.tagName||"").toLowerCase();
    if(["input","textarea","select"].includes(tag))return;
    const input=document.getElementById("sxV24Search");if(input){event.preventDefault();input.focus();}
  });

  let scheduled=false;
  const schedule=()=>{if(scheduled)return;scheduled=true;requestAnimationFrame(()=>{scheduled=false;ensure();});};
  new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(schedule,40);
})();
</script>
"""


def install(dashboard_module) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    html = dashboard_module.INDEX_HTML
    if 'id="sentrix-v24-intelligent-css"' not in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if 'id="sentrix-v24-intelligent-js"' not in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    dashboard_module.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Dashboard V2.4 : recherche intelligente et raccourcis clavier installés.")
