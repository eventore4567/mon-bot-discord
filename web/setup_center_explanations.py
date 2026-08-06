"""Explications détaillées et recherche des salons restants du Centre Setup."""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.setup-center-help")
_INSTALLED = False


SETUP_HELP_UI = r"""
<style>
  .setup-guide{margin:18px 22px 0;padding:15px 16px;border:1px solid #35405f;border-left:4px solid var(--brand);border-radius:13px;background:#101725}
  .setup-guide h3{margin:0 0 7px;font-size:16px}.setup-guide p{margin:0;color:var(--muted);line-height:1.55}.setup-guide ul{margin:9px 0 0;padding-left:18px;color:#cbd1e3;line-height:1.55}.setup-guide .warn{margin-top:10px;padding:8px 10px;border:1px solid #5b4f2c;border-radius:9px;background:#2b2413;color:#f3d68d;font-size:12px}
  .setup-detail{margin-top:7px;padding:8px 9px;border:1px dashed #303950;border-radius:9px;background:#0b101b;color:#aeb7cf;font-size:12px;line-height:1.5}
  .setup-extra-search{position:relative;margin:0 0 8px}.setup-extra-search input{padding-left:38px}.setup-extra-search::before{content:"⌕";position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:18px;pointer-events:none}.setup-extra-search-status{margin:5px 0 8px;color:var(--muted);font-size:12px;min-height:17px}.setup-extra-search-status.exact{color:var(--ok);font-weight:800}
</style>
<script>
(() => {
  const guides={
    games:{title:"Comprendre les réglages des mini-jeux",text:"Ces options décident où, par qui et avec quelles récompenses les jeux peuvent être utilisés.",items:["Si Salons autorisés est vide, les jeux fonctionnent partout sauf dans les salons bloqués.","Si vous ajoutez des salons autorisés, seuls ces salons sont utilisables ; un salon bloqué reste toujours interdit.","Pour les rôles, un membre doit avoir au moins un rôle autorisé si la liste est remplie, et aucun rôle bloqué."],warning:"0 dans Limite quotidienne signifie illimité. Enregistrez après chaque changement."},
    design:{title:"Personnaliser l’apparence de SentriX",text:"Les couleurs et symboles sont utilisés dans les embeds, barres de progression et réponses compatibles.",items:["La couleur principale sert au style général.","Le footer apparaît au bas de nombreux messages du bot.","Le mode compact réduit la taille de certaines réponses ; les graphiques ajoutent davantage de détails visuels."],warning:"Utilisez l’aperçu avant d’enregistrer pour éviter un texte ou des symboles illisibles."},
    advanced:{title:"Outils Setup avancés",text:"Cette page regroupe les réglages sensibles qui modifient le fonctionnement du bot.",items:["Désactiver une commande ne la supprime pas : elle peut être réactivée plus tard.","Les salons ignorés ne recevront pas les commandes configurables concernées.","Les exemptions AutoMod, la liste blanche anti-nuke et les gestionnaires doivent être accordés uniquement à des personnes de confiance."],warning:"Les réinitialisations sont définitives pour la section choisie et demandent le nom exact du serveur."}
  };
  const details={
    game_daily:"Nombre maximal de manches récompensées par membre et par jour. 0 désactive la limite.",
    game_event:"Multiplie la récompense de base pendant un événement. Exemple : 2 double la récompense.",
    game_min:"Plancher appliqué à la récompense finale par rapport au montant de base.",
    game_max:"Plafond appliqué à la récompense finale. Il doit être supérieur ou égal au minimum.",
    game_disabled:"Les jeux sélectionnés restent indisponibles même si l’interrupteur général est activé.",
    game_allowed_channels:"Laissez vide pour autoriser tous les salons non bloqués. Remplissez pour créer une liste blanche de salons.",
    game_blocked_channels:"Ces salons sont toujours interdits, même si un autre réglage les autorise.",
    game_allowed_roles:"Laissez vide pour ne pas exiger de rôle précis. Sinon le membre doit posséder au moins un rôle choisi.",
    game_blocked_roles:"Un membre possédant l’un de ces rôles ne peut pas jouer, même s’il possède aussi un rôle autorisé.",
    ignoredChannel:"Ajoutez un salon pour empêcher les commandes configurables d’y fonctionner.",
    verifyChannel:"Salon textuel où sera envoyé le bouton de vérification.",
    selfRoleChannel:"Salon textuel où les membres pourront choisir leurs rôles de notification."
  };
  const searchTargets=["ignoredChannel","verifyChannel","selfRoleChannel"];
  const originals=new WeakMap();
  function normalise(value){return String(value||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().replace(/[^a-z0-9]+/g," ").trim();}
  function lev(a,b){if(a===b)return 0;if(!a.length)return b.length;if(!b.length)return a.length;const p=Array.from({length:b.length+1},(_,i)=>i),c=new Array(b.length+1);for(let i=1;i<=a.length;i++){c[0]=i;for(let j=1;j<=b.length;j++){const cost=a[i-1]===b[j-1]?0:1;c[j]=Math.min(c[j-1]+1,p[j]+1,p[j-1]+cost);}for(let j=0;j<=b.length;j++)p[j]=c[j];}return p[b.length];}
  function searchable(text){return normalise(String(text||"").split(" — ")[0]);}
  function rank(name,q){if(name===q)return -1000;if(name.startsWith(q))return -500+name.length-q.length;const i=name.indexOf(q);if(i>=0)return -300+i;return lev(name,q);}
  function ensureGuide(){const head=document.querySelector(".panel-head");if(!head)return;let box=document.getElementById("setupHelpGuide");if(!box){box=document.createElement("div");box.id="setupHelpGuide";box.className="setup-guide";head.insertAdjacentElement("afterend",box);}const tab=(typeof state!=="undefined"&&state.tab)||"games",data=guides[tab]||guides.games;box.innerHTML=`<h3>💡 ${data.title}</h3><p>${data.text}</p><ul>${data.items.map(item=>`<li>${item}</li>`).join("")}</ul><div class="warn">${data.warning}</div>`;}
  function addDetails(){for(const [id,text] of Object.entries(details)){const control=document.getElementById(id);if(!control)continue;const field=control.closest(".field");if(!field||field.querySelector(`.setup-detail[data-for="${id}"]`))continue;const detail=document.createElement("div");detail.className="setup-detail";detail.dataset.for=id;detail.textContent=text;field.appendChild(detail);}}
  function remember(select){if(originals.has(select))return;originals.set(select,[...select.options].map((option,index)=>({value:String(option.value),text:option.textContent||"",index})));}
  function filter(select,input,status){remember(select);const q=normalise(input.value),selected=String(select.value||"");if(!q){select.replaceChildren();for(const entry of originals.get(select)||[]){const option=document.createElement("option");option.value=entry.value;option.textContent=entry.text;option.selected=entry.value===selected;select.appendChild(option);}status.textContent=`${select.options.length} choix disponibles`;status.classList.remove("exact");return;}const entries=(originals.get(select)||[]).filter(e=>e.value).map(e=>({...e,name:searchable(e.text),score:rank(searchable(e.text),q)})).sort((a,b)=>a.score-b.score||a.index-b.index);const exact=entries.find(e=>e.name===q);let matches=entries.filter(e=>e.score<0||e.score<=Math.max(4,Math.ceil(q.length*.45))).slice(0,8);if(!matches.length)matches=entries.slice(0,Math.min(6,entries.length));const keep=new Set([...matches.map(e=>e.value),selected]);select.replaceChildren();const empty=document.createElement("option");empty.value="";empty.textContent="Non configuré";empty.selected=!selected;select.appendChild(empty);for(const entry of entries){if(!keep.has(entry.value))continue;const option=document.createElement("option");option.value=entry.value;option.textContent=entry.text;option.selected=entry.value===selected;select.appendChild(option);}select.dataset.best=matches[0]?.value||"";status.textContent=exact?"✓ Salon exact trouvé":`${matches.length} salon${matches.length>1?"s":""} proche${matches.length>1?"s":""}`;status.classList.toggle("exact",Boolean(exact));}
  function bindSearch(id){const select=document.getElementById(id);if(!(select instanceof HTMLSelectElement)||select.dataset.extraSearchReady==="1"||select.dataset.searchReady==="1")return;select.dataset.extraSearchReady="1";const field=select.closest(".field");if(!field)return;const wrapper=document.createElement("div");wrapper.className="setup-extra-search";const input=document.createElement("input");input.type="search";input.placeholder="Rechercher un salon…";input.autocomplete="off";input.spellcheck=false;wrapper.appendChild(input);const status=document.createElement("div");status.className="setup-extra-search-status";field.insertBefore(wrapper,select);field.insertBefore(status,select.nextSibling);input.addEventListener("input",()=>filter(select,input,status));input.addEventListener("keydown",event=>{if(event.key!=="Enter")return;event.preventDefault();if(!select.dataset.best)return;select.value=select.dataset.best;select.dispatchEvent(new Event("change",{bubbles:true}));input.value="";filter(select,input,status);});filter(select,input,status);}
  function enhance(){ensureGuide();addDetails();searchTargets.forEach(bindSearch);}
  const content=document.getElementById("content");if(content)new MutationObserver(()=>queueMicrotask(enhance)).observe(content,{childList:true,subtree:true});document.querySelectorAll("[data-tab]").forEach(button=>button.addEventListener("click",()=>setTimeout(enhance,0)));enhance();
})();
</script>
"""


def _inject(html: str) -> str:
    marker = "</body>"
    if marker not in html:
        logger.warning("Centre Setup : insertion des explications impossible.")
        return html
    return html.replace(marker, SETUP_HELP_UI + "\n" + marker, 1)


def install(setup_center) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original = setup_center.handle_setup_center

    async def handle_setup_center(request):
        response = await original(request)
        response.text = _inject(response.text or "")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    setup_center.handle_setup_center = handle_setup_center
    logger.info("Explications détaillées du Centre Setup chargées.")
