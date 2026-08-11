"""Guide lisible du mode avancé du dashboard.

Le panneau est volontairement placé dans la zone principale du dashboard et non dans la
barre latérale. Il garde les raccourcis et la recherche du mode avancé guidé sans compresser
les cartes dans une colonne trop étroite.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.advanced-guide")
_INSTALLED = False


ADVANCED_GUIDE_CSS = r'''
<style id="sentrix-advanced-guide-css">
#sxAdvancedGuide{display:none;width:100%;min-width:0;margin:0 0 18px;padding:20px;border:1px solid var(--line,#252b3a);border-radius:18px;background:linear-gradient(145deg,rgba(20,25,39,.98),rgba(12,15,24,.98));box-shadow:0 16px 40px rgba(0,0,0,.18);overflow:hidden}
body.sx-simple-advanced #sxAdvancedGuide{display:block}
.sx-advanced-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:15px}.sx-advanced-head>div{min-width:0}.sx-advanced-head h3{margin:0 0 5px;font-size:19px;line-height:1.2}.sx-advanced-head p{margin:0;max-width:760px;color:var(--muted,#949caf);font-size:12px;line-height:1.55}.sx-advanced-badge{flex:0 0 auto;border:1px solid rgba(125,140,255,.5);background:rgba(125,140,255,.1);color:var(--text,#f4f6fb);border-radius:999px;padding:6px 10px;font-size:10px;font-weight:800;white-space:nowrap}
.sx-advanced-search{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px;margin-bottom:14px}.sx-advanced-search input{min-width:0;width:100%;border:1px solid var(--line,#252b3a);background:#0a0d14;color:var(--text,#f4f6fb);border-radius:11px;padding:11px 12px;outline:none}.sx-advanced-search input:focus{border-color:var(--brand2,#7d8cff)}
.sx-advanced-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:11px;align-items:start}.sx-advanced-group{min-width:0;border:1px solid var(--line,#252b3a);border-radius:14px;background:#0d111b;padding:13px}.sx-advanced-group-title{font-size:10px;color:var(--brand2,#7d8cff);font-weight:850;text-transform:uppercase;letter-spacing:.08em;margin-bottom:9px;line-height:1.3}.sx-advanced-actions{display:grid;grid-template-columns:1fr;gap:8px}.sx-advanced-action{min-width:0;width:100%;display:grid;gap:3px;min-height:62px;border:1px solid #262d3e;border-radius:11px;background:#121725;color:var(--text,#f4f6fb);padding:10px 11px;text-decoration:none;cursor:pointer;text-align:left;overflow:hidden}.sx-advanced-action:hover{border-color:var(--brand2,#7d8cff);background:#171d2d}.sx-advanced-action strong{display:block;min-width:0;font-size:13px;line-height:1.25;overflow-wrap:anywhere}.sx-advanced-action span{display:block;min-width:0;font-size:10.5px;color:var(--muted,#949caf);line-height:1.4;overflow-wrap:anywhere}.sx-advanced-action.sx-featured{border-color:rgba(125,140,255,.7);background:linear-gradient(145deg,rgba(37,45,77,.92),rgba(20,25,42,.96))}.sx-advanced-action.sx-hidden{display:none!important}
.sx-advanced-sync{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.sx-advanced-sync span{font-size:10px;color:var(--muted,#949caf);border:1px solid var(--line,#252b3a);border-radius:999px;padding:5px 8px;background:#0a0d14}.sx-advanced-empty{display:none;margin-top:10px;color:var(--muted,#949caf);font-size:12px}.sx-advanced-empty.show{display:block}
@media(max-width:760px){#sxAdvancedGuide{padding:15px}.sx-advanced-head{flex-direction:column}.sx-advanced-badge{white-space:normal}.sx-advanced-groups{grid-template-columns:1fr}}
@media(max-width:520px){.sx-advanced-search{grid-template-columns:1fr}.sx-advanced-search .btn{width:100%}}
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
      ["Engagement V3","Profils, quêtes, saisons, suggestions et starboard","/engagement","engagement profil quete quête saison suggestion starboard onboarding succes succès",true],
      ["Centre communauté","Automatisations, candidatures et vocaux temporaires","/community","communaute communauté automatisation candidature vocal temporaire"],
      ["IA","Conversation, modèles et mémoire","ai","ia intelligence artificielle modele modèle memoire mémoire"],
      ["Notifications","YouTube, TikTok, Twitch et réseaux","notifications","notification youtube tiktok twitch reseaux réseaux"]]},
    {title:"Serveur & suivi",items:[
      ["Logs","Salons de logs et historique","logs","logs journal historique salon"],
      ["Rôles & salons","Relier les rôles et salons aux fonctions","roles","role rôle salon permission channel"],
      ["Configuration complète","Tous les systèmes du serveur","/setup-center","setup configuration economie économie niveau verification vérification"],
      ["Outils staff","Profils, dossiers et diagnostics","/operations","operations staff dossier profil diagnostic"]]},
    {title:"Outils experts",items:[
      ["Enterprise","Recours, Modmail, backups et automatisations","/enterprise","enterprise recours appeal modmail backup sauvegarde automation"],
      ["Navigation complète","Descendre vers tous les réglages avancés","__navigation__","navigation complet tous réglages menu avancé avance"],
      ["Profil Engagement","Voir le profil membre et la progression","/engagement","profil membre points quetes succès classement"],
      ["Communauté staff","Candidatures et vocaux temporaires","/community","staff candidature application vocal temporaire"]]}
  ];

  function esc(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
  function currentGuild(){try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):"";}catch(_){return "";}}
  function hrefWithGuild(path){const gid=currentGuild();if(!gid||!path.startsWith("/"))return path;return path+(path.includes("?")?"&":"?")+"guild="+encodeURIComponent(gid);}
  function openTarget(target){
    if(!target)return;
    if(target==="__navigation__"){
      const nav=document.getElementById("navigation");
      if(nav)nav.scrollIntoView({behavior:"smooth",block:"start"});
      return;
    }
    if(target.startsWith("/")){location.href=hrefWithGuild(target);return;}
    const button=document.querySelector('#navigation [data-tab="'+CSS.escape(target)+'"]');
    if(button){button.click();window.scrollTo({top:0,behavior:"smooth"});}
  }

  function mountPoint(){
    const dashboard=document.getElementById("dashboard");
    const workspace=dashboard&&dashboard.querySelector(".workspace");
    const head=workspace&&workspace.querySelector(".workspace-head");
    return {dashboard,workspace,head};
  }

  function buildGuide(){
    const {dashboard,workspace,head}=mountPoint();
    const navigation=document.getElementById("navigation");
    if(!dashboard||!workspace||!head||!navigation||document.getElementById("sxAdvancedGuide"))return false;

    const guide=document.createElement("section");
    guide.id="sxAdvancedGuide";
    guide.innerHTML=`<div class="sx-advanced-head"><div><h3>Mode avancé guidé</h3><p>Les fonctions importantes sont regroupées ici. Le menu complet reste disponible plus bas pour les réglages très précis.</p></div><span class="sx-advanced-badge">COMPLET · PLUS LISIBLE</span></div><div class="sx-advanced-search"><input id="sxAdvancedSearch" type="search" autocomplete="off" placeholder="Rechercher : Engagement, tickets, sécurité, candidatures, logs..."><button class="btn" id="sxAdvancedClear" type="button">Effacer</button></div><div class="sx-advanced-groups">${GROUPS.map(group=>`<div class="sx-advanced-group"><div class="sx-advanced-group-title">${esc(group.title)}</div><div class="sx-advanced-actions">${group.items.map(item=>`<button class="sx-advanced-action${item[4]?' sx-featured':''}" type="button" data-sx-advanced-target="${esc(item[2])}" data-sx-keywords="${esc((item[0]+' '+item[1]+' '+item[3]).toLocaleLowerCase('fr'))}"><strong>${esc(item[0])}</strong><span>${esc(item[1])}</span></button>`).join("")}</div></div>`).join("")}</div><div id="sxAdvancedEmpty" class="sx-advanced-empty">Aucun raccourci trouvé. Le menu complet reste disponible en dessous.</div><div class="sx-advanced-sync"><span>Onboarding V2</span><span>6 quêtes</span><span>10 succès</span><span>Saisons</span><span>Suggestions V2</span><span>Starboard</span><span>IA tickets</span><span>Candidatures</span><span>Vocaux temporaires</span></div>`;

    // Important : le guide doit vivre dans la zone principale. Le placer après
    // sxSimpleControls le coinçait dans la sidebar et écrasait tout le texte.
    head.insertAdjacentElement("afterend",guide);

    guide.addEventListener("click",event=>{
      const action=event.target.closest("[data-sx-advanced-target]");
      if(action)openTarget(action.getAttribute("data-sx-advanced-target"));
    });
    const input=guide.querySelector("#sxAdvancedSearch");
    const clear=guide.querySelector("#sxAdvancedClear");
    const empty=guide.querySelector("#sxAdvancedEmpty");
    const filter=()=>{
      const q=String(input.value||"").trim().toLocaleLowerCase("fr");
      let visible=0;
      guide.querySelectorAll(".sx-advanced-action").forEach(action=>{
        const show=!q||String(action.dataset.sxKeywords||"").includes(q);
        action.classList.toggle("sx-hidden",!show);
        if(show)visible+=1;
      });
      guide.querySelectorAll(".sx-advanced-group").forEach(group=>{
        group.style.display=group.querySelector(".sx-advanced-action:not(.sx-hidden)")?"":"none";
      });
      empty.classList.toggle("show",visible===0);
    };
    input.addEventListener("input",filter);
    clear.addEventListener("click",()=>{input.value="";filter();input.focus();});
    return true;
  }

  function renameAdvancedButton(){
    const button=document.getElementById("sxUseAdvanced");
    if(button&&button.textContent.trim()==="Mode avancé")button.textContent="Mode avancé guidé";
  }
  function ensure(){buildGuide();renameAdvancedButton();}
  ensure();
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",ensure,{once:true});
  const observer=new MutationObserver(ensure);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(()=>observer.disconnect(),20000);
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
    logger.info("Mode avancé guidé lisible installé.")
