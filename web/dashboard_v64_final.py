"""SentriX V64 — verrou de navigation du dashboard final et système motion+son réel.

V61 garde encore un renderer de compatibilité qui reconstruit son ancienne sidebar lorsqu'une
page historique (Accueil, Logs, IA, etc.) est affichée. V62 reconstruit la bonne sidebar avant
cet appel. V64 est la dernière couche avant le gel (dashboard_frontend_freeze_v55) : elle
restaure la navigation finale seulement si une couche héritée l'a réellement remplacée, puis ne
fait plus que synchroniser l'état actif.

C'est aussi, depuis cette révision, le seul endroit du code où ajouter une animation, un son ou
une préférence d'interface a un effet réel sur ``/app`` : ``dashboard_rework_v60.py`` écrase au
boot le document produit par ``web/__init__.py`` (donc dashboard_polish.py,
dashboard_accessibility.py, dashboard_oxyde_theme.py, dashboard_button_feedback.py etc. ne
survivent jamais jusqu'ici), et le gel V55 fige ensuite tout ce qui reste. Voir la mémoire
« SentriX : dashboard_rework_v60.py écrase tout » pour la chaîne complète.
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

/* V64 motion+sound : ce bloc est le premier système d'animation à réellement atteindre
   /app — tout ce qui existait avant (dashboard_polish.py, dashboard_accessibility.py,
   dashboard_oxyde_theme.py...) est écrasé au boot par le remplacement brutal de
   dashboard_rework_v60.py avant que cette couche ne s'applique. Voir mémoire
   "SentriX : dashboard_rework_v60.py écrase tout". */
.btn,.navigation button,.rail-guild,.switch,.sx-big-switch,.action-card{transition:transform .12s ease,border-color .15s ease,background .15s ease,color .15s ease}
.btn:active{transform:scale(.96)}
.action-card:hover,.metric:hover{transform:translateY(-2px);border-color:#5f656c}
.toast{transition:opacity .18s ease,transform .18s ease;opacity:0;transform:translateY(10px) scale(.97)}
.toast.sx-toast-in{opacity:1;transform:translateY(0) scale(1)}
@media(prefers-reduced-motion:no-preference){
  html:not(.sx-motion-off) #serverContent.sx-tab-enter{animation:sx-tab-in .22s cubic-bezier(.16,1,.3,1)}
  html:not(.sx-motion-off) #fields.sx-tab-enter .panel-section,
  html:not(.sx-motion-off) #fields.sx-tab-enter .action-card,
  html:not(.sx-motion-off) #fields.sx-tab-enter .list-row{animation:sx-card-in .26s cubic-bezier(.16,1,.3,1) both;animation-delay:var(--sx-stagger,0ms)}
  @keyframes sx-tab-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
  @keyframes sx-card-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
}
html.sx-motion-off .toast{transition:none}
.sx-interface-btn{width:38px;height:38px;border-radius:50%;border:1px solid #ffffff20;background:#2c3035;color:#eef0f2;font-size:16px;cursor:pointer;display:grid;place-items:center;flex:0 0 auto}
.sx-interface-btn:hover{border-color:var(--sx-blue,#4da3ff);color:var(--sx-blue,#4da3ff)}
.sx-interface-popover{position:fixed;z-index:120;width:280px;background:#2b2f34;border:1px solid #454a50;border-radius:10px;box-shadow:0 16px 40px #0008;padding:14px 16px}
.sx-interface-popover .sx-interface-title{font-weight:900;font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:#d2d3d4;margin-bottom:2px}

/* Accessibilité (portée depuis dashboard_accessibility.py, qui n'atteint jamais /app pour
   la même raison que le reste : voir la mémoire citée plus haut). Non destructif : aucune
   route ni permission n'est modifiée, uniquement des aides clavier/lecteur d'écran, contraste,
   cibles tactiles et réduction des animations. */
.sx-skip-link{position:fixed;left:12px;top:10px;z-index:100000;transform:translateY(-150%);padding:10px 14px;border-radius:8px;background:#fff;color:#000;font-weight:800;box-shadow:0 4px 18px rgba(0,0,0,.35);transition:transform .15s ease}
.sx-skip-link:focus{transform:translateY(0)}
.sx-sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
:where(button,a,input,select,textarea,[role="button"]):focus-visible{outline:3px solid #fff!important;outline-offset:3px!important;box-shadow:0 0 0 5px var(--sx-blue,#4da3ff)!important}
:where(button,select,input[type="button"],input[type="submit"],[role="button"]){min-height:44px}
:where(input,select,textarea){font-size:max(16px,1em)}
[aria-disabled="true"],button:disabled{cursor:not-allowed;opacity:.62}
[aria-hidden="true"]{pointer-events:none}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;animation-iteration-count:1!important;transition-duration:.001ms!important;scroll-behavior:auto!important}}
@media(prefers-contrast:more){:root{--muted:#d1d5db!important;--line:#8b95aa!important}:where(button,a,input,select,textarea){text-decoration-thickness:2px}}
@media(forced-colors:active){*{forced-color-adjust:auto}:where(button,a,input,select,textarea,[role="button"]):focus-visible{outline:3px solid Highlight!important;box-shadow:none!important}}
@media(max-width:560px){:where(button,[role="button"],select){min-height:48px}:where(button,[role="button"]){line-height:1.25}}

/* Confirmation avant action critique (modal stylée, portée depuis
   dashboard_confirm_modal_v47.py — même raison, jamais servie jusqu'ici). Les deux
   confirm() natifs qui gardaient réellement une suppression (panel/type de ticket dans
   dashboard_v62_dense.py) appellent désormais window.sentrixConfirm défini plus bas. Les
   deux confirm() qui bloquent une navigation avec modifications non enregistrées
   (dashboard_v60_max.py) restent natifs : ils doivent rester synchrones pour pouvoir
   annuler la navigation en cours, ce qu'une modale asynchrone ne peut pas faire. */
.sentrix-confirm-backdrop{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(3,5,10,.76);backdrop-filter:blur(7px);-webkit-backdrop-filter:blur(7px)}
.sentrix-confirm-backdrop.hidden{display:none!important}
.sentrix-confirm-card{width:min(440px,100%);background:linear-gradient(180deg,#171b29,#10131e);border:1px solid #303750;border-radius:20px;box-shadow:0 30px 100px rgba(0,0,0,.62);overflow:hidden}
@media(prefers-reduced-motion:no-preference){.sentrix-confirm-card{animation:sentrixConfirmIn .16s ease-out}}
@keyframes sentrixConfirmIn{from{opacity:0;transform:translateY(10px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
.sentrix-confirm-body{padding:25px 25px 20px}
.sentrix-confirm-title{font-size:20px;font-weight:850;letter-spacing:-.02em;margin:0 0 9px;color:#f2f4ff}
.sentrix-confirm-text{margin:0;color:#a3abc0;line-height:1.6;font-size:14px}
.sentrix-confirm-actions{display:flex;justify-content:flex-end;gap:10px;padding:17px 20px;border-top:1px solid #262d43;background:#0d1019}
.sentrix-confirm-btn{border:1px solid #303850;border-radius:11px;padding:10px 16px;font:inherit;font-weight:750;cursor:pointer;color:#eef1ff;background:#171c2c;transition:transform .12s ease,border-color .15s ease}
.sentrix-confirm-btn:hover{transform:translateY(-1px);border-color:#505a7a}
.sentrix-confirm-btn.primary{border-color:transparent;background:linear-gradient(135deg,var(--sx-blue,#4da3ff),var(--sx-blue2,#78bdff));color:#08131f}
.sentrix-confirm-btn.danger{border-color:#713044;background:#3a1520;color:#ff9aaa}
.sentrix-confirm-btn:focus-visible{outline:2px solid var(--sx-blue,#4da3ff)!important;outline-offset:2px!important;box-shadow:none!important}
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

  /* --- Préférences Interface (Animations / Sons), persistées localement --- */
  function prefersReducedMotionOS(){try{return matchMedia('(prefers-reduced-motion: reduce)').matches}catch(_){return false}}
  function readPref(key,fallback){try{const v=localStorage.getItem(key);return v===null?fallback:v==='1'}catch(_){return fallback}}
  function writePref(key,value){try{localStorage.setItem(key,value?'1':'0')}catch(_){}}
  let motionEnabled=readPref('sentrix:pref:motion',!prefersReducedMotionOS());
  let soundEnabled=readPref('sentrix:pref:sound',true);
  function applyMotionPref(){document.documentElement.classList.toggle('sx-motion-off',!motionEnabled)}
  applyMotionPref();

  /* --- Petits sons UI : contrairement à dashboard_button_feedback.py (jamais servi, et
     dont le seul déclencheur était "pointerover", mort sur écran tactile et découplé du
     geste qui débloque l'AudioContext), ici chaque son est déclenché par le même geste
     réel (clic/clavier) qui débloque l'AudioContext. */
  let audioCtx=null;
  function getAudioCtx(){
    if(audioCtx)return audioCtx;
    try{const Ctor=window.AudioContext||window.webkitAudioContext;if(!Ctor)return null;audioCtx=new Ctor()}catch(_){return null}
    return audioCtx;
  }
  function unlockAudio(){const ctx=getAudioCtx();if(!ctx)return;if(ctx.state==='suspended'){ctx.resume().catch(()=>{})}}
  function playTone(freq,duration,gainPeak){
    if(!soundEnabled)return;
    const ctx=getAudioCtx();if(!ctx)return;
    try{
      if(ctx.state==='suspended')ctx.resume().catch(()=>{});
      const osc=ctx.createOscillator(),gain=ctx.createGain();
      osc.type='sine';osc.frequency.value=freq;
      const now=ctx.currentTime;
      gain.gain.setValueAtTime(0,now);
      gain.gain.linearRampToValueAtTime(gainPeak,now+.008);
      gain.gain.exponentialRampToValueAtTime(.0001,now+duration);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now);osc.stop(now+duration+.02);
    }catch(_){}
  }
  function tickSound(){playTone(720,.07,.05)}
  function successSound(){playTone(880,.09,.055);setTimeout(()=>playTone(1180,.1,.045),70)}
  function errorSound(){playTone(300,.14,.06)}
  function toggleSound(){playTone(560,.05,.04)}
  document.addEventListener('pointerdown',unlockAudio,{passive:true});
  document.addEventListener('keydown',unlockAudio,{passive:true});
  document.addEventListener('change',event=>{if(event.target.closest?.('.switch,.sx-big-switch'))toggleSound()});

  /* --- Transition d'apparition au changement d'onglet (contenu déjà remplacé
     instantanément par renderTab ; on rejoue seulement l'entrée visuelle) --- */
  function replayEnter(el){if(!el)return;el.classList.remove('sx-tab-enter');void el.offsetWidth;el.classList.add('sx-tab-enter')}
  function staggerChildren(container){
    if(!container)return;
    container.querySelectorAll('.panel-section,.action-card,.list-row').forEach((node,i)=>{node.style.setProperty('--sx-stagger',Math.min(i,8)*35+'ms')});
  }
  /* Le clic de navigation est intercepté en phase de capture par V64 lui-même
     (bindNavigation ci-dessus fait stopImmediatePropagation), donc un écouteur
     séparé sur #navigation ne recevrait jamais l'événement : le son de changement
     d'onglet est déclenché depuis renderTab (toujours appelé par un vrai clic ou un
     vrai changement de serveur), pas depuis un écouteur concurrent. */
  let lastAnimatedTab=null;
  const beforeMotionTab=renderTab;
  renderTab=function(){
    const result=beforeMotionTab();
    const fields=$('fields');
    staggerChildren(fields);
    replayEnter($('serverContent'));
    replayEnter(fields);
    if(lastAnimatedTab!==null&&lastAnimatedTab!==state.tab)tickSound();
    lastAnimatedTab=state.tab;
    return result;
  };

  /* --- Toast : glissement + fondu, plus un son distinct succès/erreur --- */
  if(typeof toast==='function'){
    const beforeToast=toast;
    let toastFadeTimer;
    toast=function(message,bad=false){
      beforeToast(message,bad);
      const el=$('toast');
      if(bad)errorSound();else successSound();
      if(!el)return;
      clearTimeout(toastFadeTimer);
      el.classList.remove('sx-toast-in');
      void el.offsetWidth;
      el.classList.add('sx-toast-in');
      toastFadeTimer=setTimeout(()=>el.classList.remove('sx-toast-in'),3900);
    };
  }

  /* --- Réglages "Interface" : un bouton dans la topbar, pas un onglet.
     V61/V62/V63 possèdent leur propre routage pour tous les onglets de FINAL_TABS
     (aucun ne retombe plus sur renderGeneral, vérifié en navigateur réel : l'onglet
     "general" du V60 de base n'a même plus de bouton dans la sidebar reconstruite par
     V64). Un onglet ne serait donc pas fiable ; un contrôle toujours visible l'est. */
  function buildInterfacePopover(){
    const topRight=document.querySelector('.top-right');
    if(!topRight||$('sxInterfaceBtn'))return;
    const btn=document.createElement('button');
    btn.type='button';btn.id='sxInterfaceBtn';btn.className='sx-interface-btn';
    btn.title='Interface';btn.setAttribute('aria-label','Réglages d’interface');btn.textContent='⚙';
    const pop=document.createElement('div');
    pop.id='sxInterfacePopover';pop.className='sx-interface-popover hidden';
    pop.innerHTML='<div class="sx-interface-title">Interface</div>'
      +'<div class="switch-line"><div class="switch-copy"><b>Animations</b><span>Transitions et apparitions dans le tableau de bord.</span></div><input id="sxPrefMotion" class="switch" type="checkbox" '+(motionEnabled?'checked':'')+'></div>'
      +'<div class="switch-line"><div class="switch-copy"><b>Sons de l’interface</b><span>Petits retours sonores lors des actions.</span></div><input id="sxPrefSound" class="switch" type="checkbox" '+(soundEnabled?'checked':'')+'></div>';
    topRight.insertBefore(btn,topRight.firstChild);
    document.body.appendChild(pop);
    function position(){const r=btn.getBoundingClientRect();pop.style.top=(r.bottom+8)+'px';pop.style.right=(innerWidth-r.right)+'px'}
    btn.addEventListener('click',event=>{event.stopPropagation();position();pop.classList.toggle('hidden')});
    document.addEventListener('click',event=>{if(!pop.contains(event.target)&&event.target!==btn)pop.classList.add('hidden')});
    document.addEventListener('keydown',event=>{if(event.key==='Escape')pop.classList.add('hidden')});
    addEventListener('resize',()=>{if(!pop.classList.contains('hidden'))position()});
    pop.querySelector('#sxPrefMotion').addEventListener('change',event=>{motionEnabled=event.target.checked;writePref('sentrix:pref:motion',motionEnabled);applyMotionPref()});
    pop.querySelector('#sxPrefSound').addEventListener('change',event=>{soundEnabled=event.target.checked;writePref('sentrix:pref:sound',soundEnabled)});
  }
  buildInterfacePopover();
})();
</script>

<div id="sentrixConfirmBackdrop" class="sentrix-confirm-backdrop hidden" role="dialog" aria-modal="true" aria-labelledby="sentrixConfirmTitle" aria-describedby="sentrixConfirmText">
  <div class="sentrix-confirm-card">
    <div class="sentrix-confirm-body">
      <h2 id="sentrixConfirmTitle" class="sentrix-confirm-title">Confirmation</h2>
      <p id="sentrixConfirmText" class="sentrix-confirm-text">Confirmer cette action ?</p>
    </div>
    <div class="sentrix-confirm-actions">
      <button id="sentrixConfirmCancel" class="sentrix-confirm-btn" type="button">Annuler</button>
      <button id="sentrixConfirmOk" class="sentrix-confirm-btn primary" type="button">Confirmer</button>
    </div>
  </div>
</div>
<script id="sentrix-confirm-modal-js-v47">
(() => {
  "use strict";
  if(window.__sentrixConfirmModal)return;window.__sentrixConfirmModal=true;
  let pendingResolve = null;

  function closeSentrixConfirm(result) {
    const backdrop = document.getElementById("sentrixConfirmBackdrop");
    if (backdrop) backdrop.classList.add("hidden");
    const resolve = pendingResolve;
    pendingResolve = null;
    if (resolve) resolve(Boolean(result));
  }

  window.sentrixConfirm = function(message, options = {}) {
    const backdrop = document.getElementById("sentrixConfirmBackdrop");
    const title = document.getElementById("sentrixConfirmTitle");
    const text = document.getElementById("sentrixConfirmText");
    const ok = document.getElementById("sentrixConfirmOk");
    const cancel = document.getElementById("sentrixConfirmCancel");
    if (!backdrop || !title || !text || !ok || !cancel) return Promise.resolve(false);

    if (pendingResolve) {
      pendingResolve(false);
      pendingResolve = null;
    }

    title.textContent = options.title || "Confirmer l’action";
    text.textContent = String(message || "Confirmer cette action ?");
    ok.textContent = options.confirmText || "Confirmer";
    cancel.textContent = options.cancelText || "Annuler";
    ok.classList.toggle("danger", Boolean(options.danger));
    ok.classList.toggle("primary", !options.danger);
    backdrop.classList.remove("hidden");

    return new Promise(resolve => {
      pendingResolve = resolve;
      setTimeout(() => ok.focus(), 0);
    });
  };

  const backdrop = document.getElementById("sentrixConfirmBackdrop");
  const ok = document.getElementById("sentrixConfirmOk");
  const cancel = document.getElementById("sentrixConfirmCancel");
  if (backdrop && ok && cancel) {
    ok.addEventListener("click", () => closeSentrixConfirm(true));
    cancel.addEventListener("click", () => closeSentrixConfirm(false));
    backdrop.addEventListener("click", event => {
      if (event.target === backdrop) closeSentrixConfirm(false);
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !backdrop.classList.contains("hidden")) closeSentrixConfirm(false);
    });
  }
})();
</script>

<script id="sentrix-a11y-js">
(() => {
  "use strict";
  if (window.__sentrixAccessibility) return;
  window.__sentrixAccessibility = true;

  const clean = value => String(value || "").replace(/\s+/g," ").trim();
  let scheduled = false;

  function ensureMain(){
    let main = document.querySelector("main");
    if (!main) {
      main = document.getElementById("sxSimpleHome") || document.querySelector(".main-content,.content,[data-main]");
      if (main && !main.hasAttribute("role")) main.setAttribute("role","main");
    }
    if (main && !main.id) main.id = "sentrix-main";
    return main;
  }

  function ensureSkipLink(){
    if (document.getElementById("sxSkipLink")) return;
    const main = ensureMain();
    if (!main) return;
    const link = document.createElement("a");
    link.id = "sxSkipLink";
    link.className = "sx-skip-link";
    link.href = "#" + main.id;
    link.textContent = "Aller au contenu principal";
    document.body.prepend(link);
  }

  function labelControls(root=document){
    root.querySelectorAll("button,[role='button']").forEach(el => {
      if (el.hasAttribute("aria-label")) return;
      const text = clean(el.innerText || el.textContent);
      const fallback = clean(el.getAttribute("title") || el.dataset.label || el.dataset.action || el.dataset.sxV2Go);
      if (text || fallback) el.setAttribute("aria-label", text || fallback);
    });

    root.querySelectorAll("input,select,textarea").forEach(el => {
      if (el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby")) return;
      const id = el.id;
      let explicit = null;
      if (id) {
        try {
          const escaped = (window.CSS && CSS.escape) ? CSS.escape(id) : id.replace(/[^a-zA-Z0-9_-]/g, "\\$&");
          explicit = document.querySelector(`label[for="${escaped}"]`);
        } catch (_) {}
      }
      if (explicit) return;
      const placeholder = clean(el.getAttribute("placeholder"));
      const name = clean(el.getAttribute("name"));
      if (placeholder || name) el.setAttribute("aria-label", placeholder || name);
    });

    root.querySelectorAll("img:not([alt])").forEach(img => {
      const title = clean(img.getAttribute("title"));
      const cls = String(img.className || "").toLowerCase();
      if (title) img.alt = title;
      else if (cls.includes("avatar")) img.alt = "Avatar";
      else img.alt = "";
    });
  }

  function markCurrentNavigation(){
    document.querySelectorAll("a[href]").forEach(link => {
      try {
        const url = new URL(link.href, location.href);
        if (url.pathname === location.pathname) link.setAttribute("aria-current","page");
        else if (link.getAttribute("aria-current") === "page") link.removeAttribute("aria-current");
      } catch (_) {}
    });
  }

  function enhance(){
    scheduled = false;
    try {
      if (!document.documentElement.lang) document.documentElement.lang = "fr";
      ensureSkipLink();
      labelControls();
      markCurrentNavigation();
    } catch (_) {}
  }

  function schedule(){
    if (scheduled) return;
    scheduled = true;
    setTimeout(enhance, 0);
  }

  /* Pas de MutationObserver ni de requestAnimationFrame ici : renderTab() (déjà chaîné par
     le bloc motion ci-dessus) est le seul point précis où le contenu change réellement dans
     cette page mono-document, donc on s'y accroche au lieu d'observer tout le sous-arbre. */
  if (typeof renderTab === "function") {
    const beforeA11y = renderTab;
    renderTab = function(){ const result = beforeA11y(); schedule(); return result; };
  }
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)schedule();});
  window.addEventListener("popstate",schedule);
  schedule();
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
    logger.info("Dashboard V64 final installé : navigation stable, détails bleus SentriX, responsive mobile/tablette verrouillé, motion+son réels, préférences Interface, accessibilité et confirmation d'action critique.")
    return True


__all__ = ["install"]
