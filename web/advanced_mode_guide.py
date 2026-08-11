"""Guide avancé du dashboard : conserve toute la puissance du mode avancé sans le rendre confus.

Le mode simple reste le parcours le plus guidé. Ce module ajoute au mode avancé un accès
rapide, une recherche et les nouveautés Community / Engagement V3 sans masquer la navigation
historique ni retirer de réglages experts.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.advanced-guide")
_INSTALLED = False


ADVANCED_GUIDE_CSS = r'''
<style id="sentrix-advanced-guide-css">
#sxAdvancedGuide{display:none;margin:0 0 18px;padding:18px;border:1px solid var(--line,#252b3a);border-radius:17px;background:linear-gradient(145deg,rgba(20,25,39,.97),rgba(12,15,24,.97));box-shadow:0 16px 40px rgba(0,0,0,.18)}
body.sx-simple-advanced #sxAdvancedGuide{display:block}
.sx-advanced-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:14px}.sx-advanced-head h3{margin:0 0 4px;font-size:18px}.sx-advanced-head p{margin:0;color:var(--muted,#949caf);font-size:12px;line-height:1.5}.sx-advanced-badge{border:1px solid rgba(125,140,255,.5);background:rgba(125,140,255,.1);color:var(--text,#f4f6fb);border-radius:999px;padding:6px 9px;font-size:10px;font-weight:800;white-space:nowrap}
.sx-advanced-search{display:grid;grid-template-columns:1fr auto;gap:8px;margin-bottom:13px}.sx-advanced-search input{min-width:0;border:1px solid var(--line,#252b3a);background:#0a0d14;color:var(--text,#f4f6fb);border-radius:11px;padding:11px 12px;outline:none}.sx-advanced-search input:focus{border-color:var(--brand2,#7d8cff)}
.sx-advanced-groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.sx-advanced-group{border:1px solid var(--line,#252b3a);border-radius:13px;background:#0d111b;padding:12px}.sx-advanced-group-title{font-size:10px;color:var(--brand2,#7d8cff);font-weight:850;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}.sx-advanced-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.sx-advanced-action{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:2px;min-height:58px;border:1px solid #262d3e;border-radius:10px;background:#121725;color:var(--text,#f4f6fb);padding:9px 10px;text-decoration:none;cursor:pointer;text-align:left}.sx-advanced-action:hover{border-color:var(--brand2,#7d8cff);background:#171d2d}.sx-advanced-action strong{font-size:12px}.sx-advanced-action span{font-size:10px;color:var(--muted,#949caf);line-height:1.35}.sx-advanced-action.sx-featured{border-color:rgba(125,140,255,.55);background:linear-gradient(145deg,rgba(37,45,77,.9),rgba(20,25,42,.95))}.sx-advanced-action.sx-hidden{display:none!important}
.sx-advanced-sync{display:flex;flex-wrap:wrap;gap:6px;margin-top:11px}.sx-advanced-sync span{font-size:10px;color:var(--muted,#949caf);border:1px solid var(--line,#252b3a);border-radius:999px;padding:5px 7px;background:#0a0d14}.sx-advanced-empty{display:none;margin-top:10px;color:var(--muted,#949caf);font-size:12px}.sx-advanced-empty.show{display:block}
@media(max-width:900px){.sx-advanced-groups{grid-template-columns:1fr}.sx-advanced-actions{grid-template-columns:repeat(2,minmax(0,1fr))}.sx-advanced-head{flex-direction:column}}
@media(max-width:560px){.sx-advanced-actions,.sx-advanced-search{grid-template-columns:1fr}}
</style>
'''


ADVANCED_GUIDE_JS = r'''
<script id="sentrix-advanced-guide-js">
(() => {
  "use strict";
  if (window.__sentrixAdvancedGuide) return;
  window.__sentrixAdvancedGuide = true;

  const GROUPS = [
    {title:"Essentiels",items:[
      ["Sécurité","Anti-spam, anti-raid, anti-nuke","security","securite sécurité spam raid nuke protection"],
      ["Sanctions","Bans, mutes, warns et membres","sanctions","sanction moderation modération ban mute warn membre"],
      ["Accueil","Bienvenue, autorôle et vérification","welcome","accueil welcome bienvenue autorole autorôle verification vérification"],
      ["Tickets","Support et configuration tickets","tickets","ticket support formulaire transcript aide"]]},
    {title:"Communauté & nouveautés",items:[
      ["Centre communauté","Automatisations, candidatures et vocaux","/community","communaute communauté automatisation candidature vocal temporaire"],
      ["Engagement V3","Profils, quêtes, saisons, suggestions et starboard","/engagement","engagement profil quete quête saison suggestion starboard onboarding succes succès",true],
      ["IA","Conversation, modèles et mémoire","ai","ia intelligence artificielle modele modèle memoire mémoire"],
      ["Notifications","YouTube, TikTok, Twitch et réseaux","notifications","notification youtube tiktok twitch reseaux réseaux"]]},
    {title:"Serveur & suivi",items:[
      ["Logs","Salons de logs et historique","logs","logs journal historique salon"],
      ["Rôles & salons","Relier les rôles et salons aux fonctions","roles","role rôle salon permission channel"],
      ["Configuration complète","Tous les systèmes du serveur","/setup-center","setup configuration economie économie niveau verification vérification"],
      ["Outils staff","Profils, dossiers et diagnostics","/operations","operations staff dossier profil diagnostic"]]},
    {title:"Outils experts",items:[
      ["Enterprise","Recours, Modmail, backups et automatisations","/enterprise","enterprise recours appeal modmail backup sauvegarde automation"],
      ["Navigation complète","Tous les réglages restent dans le menu","__navigation__","navigation complet tous réglages menu avancé avance"],
      ["Engagement — profil","Voir ton profil membre","/engagement","profil membre points quetes succès classement"],
      ["Communauté — staff","Candidatures et vocaux temporaires","/community","staff candidature application vocal temporaire"]]}
  ];

  function esc(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
  function currentGuild(){try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):"";}catch(_){return "";}}
  function hrefWithGuild(path){const gid=currentGuild();if(!gid||!path.startsWith("/"))return path;return path+(path.includes("?")?"&":"?")+"guild="+encodeURIComponent(gid);}
  function openTarget(target){
    if(!target)return;
    if(target==="__navigation__"){const nav=document.getElementById("navigation");if(nav)nav.scrollIntoView({behavior:"smooth",block:"start"});return;}
    if(target.startsWith("/")){location.href=hrefWithGuild(target);return;}
    const button=document.querySelector('#navigation [data-tab="'+CSS.escape(target)+'"]');
    if(button){button.click();window.scrollTo({top:0,behavior:"smooth"});}
  }

  function buildGuide(){
    const controls=document.getElementById("sxSimpleControls");
    const navigation=document.getElementById("navigation");
    if(!controls||!navigation||document.getElementById("sxAdvancedGuide"))return;
    const guide=document.createElement("section");guide.id="sxAdvancedGuide";
    guide.innerHTML=`<div class="sx-advanced-head"><div><h3>Mode avancé guidé</h3><p>Tous les réglages experts restent disponibles, mais les fonctions importantes et les nouveautés sont maintenant accessibles directement.</p></div><span class="sx-advanced-badge">COMPLET + PLUS SIMPLE</span></div><div class="sx-advanced-search"><input id="sxAdvancedSearch" type="search" autocomplete="off" placeholder="Rechercher : Engagement, tickets, sécurité, candidatures, logs..."><button class="btn" id="sxAdvancedClear" type="button">Effacer</button></div><div class="sx-advanced-groups">${GROUPS.map(group=>`<div class="sx-advanced-group"><div class="sx-advanced-group-title">${esc(group.title)}</div><div class="sx-advanced-actions">${group.items.map(item=>`<button class="sx-advanced-action${item[4]?' sx-featured':''}" type="button" data-sx-advanced-target="${esc(item[2])}" data-sx-keywords="${esc((item[0]+' '+item[1]+' '+item[3]).toLocaleLowerCase('fr'))}"><strong>${esc(item[0])}</strong><span>${esc(item[1])}</span></button>`).join("")}</div></div>`).join("")}</div><div id="sxAdvancedEmpty" class="sx-advanced-empty">Aucun raccourci trouvé. Le menu complet juste en dessous contient toujours tous les réglages.</div><div class="sx-advanced-sync"><span>Onboarding V2</span><span>6 quêtes</span><span>10 succès</span><span>Saisons</span><span>Suggestions V2</span><span>Starboard</span><span>IA tickets</span><span>Candidatures</span><span>Vocaux temporaires</span></div>`;
    controls.insertAdjacentElement("afterend",guide);
    guide.addEventListener("click",event=>{const action=event.target.closest("[data-sx-advanced-target]");if(action)openTarget(action.getAttribute("data-sx-advanced-target"));});
    const input=guide.querySelector("#sxAdvancedSearch"),clear=guide.querySelector("#sxAdvancedClear"),empty=guide.querySelector("#sxAdvancedEmpty");
    const filter=()=>{const q=String(input.value||"").trim().toLocaleLowerCase("fr");let visible=0;guide.querySelectorAll(".sx-advanced-action").forEach(action=>{const show=!q||String(action.dataset.sxKeywords||"").includes(q);action.classList.toggle("sx-hidden",!show);if(show)visible+=1;});empty.classList.toggle("show",visible===0);};
    input.addEventListener("input",filter);clear.addEventListener("click",()=>{input.value="";filter();input.focus();});
  }
  function renameAdvancedButton(){const button=document.getElementById("sxUseAdvanced");if(button&&button.textContent.trim()==="Mode avancé")button.textContent="Mode avancé guidé";}
  function ensure(){buildGuide();renameAdvancedButton();}
  ensure();if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",ensure,{once:true});
  const observer=new MutationObserver(ensure);observer.observe(document.documentElement,{childList:true,subtree:true});setTimeout(()=>observer.disconnect(),20000);
})();
</script>
'''


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    html = getattr(dashboard, "INDEX_HTML", "")
    if not isinstance(html, str):
        return
    if 'id="sentrix-advanced-guide-css"' not in html and "</head>" in html:
        html = html.replace("</head>", ADVANCED_GUIDE_CSS + "\n</head>", 1)
    if 'id="sentrix-advanced-guide-js"' not in html and "</body>" in html:
        html = html.replace("</body>", ADVANCED_GUIDE_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Mode avancé guidé installé.")
