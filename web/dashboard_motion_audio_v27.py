"""SentriX Dashboard V27 — real V15 motion + local UI audio.

Final presentation layer for the browser-visible V15/native renderer. It uses the Web
Animations API directly on #content and the real cards/rows, so motion is not dependent on
legacy CSS classes winning the cascade. Short UI tones are generated locally with Web Audio
only after trusted user gestures; no external audio asset or autoplay is used.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-motion-audio-v27")

STYLE_MARKER = "sentrix-dashboard-motion-audio-v27"
JS_MARKER = "__sentrixDashboardMotionAudioV27"

STYLE = f'''<style id="{STYLE_MARKER}">
:root{{--sx27-blue:#60a5fa;--sx27-blue2:#2f87e5;--sx27-spring:cubic-bezier(.16,1,.3,1)}}
#sx27Flash{{position:fixed;z-index:2147483500;inset:0;pointer-events:none;opacity:0;background:radial-gradient(circle at 52% 18%,rgba(74,158,239,.12),transparent 34%),rgba(2,6,10,.10)}}
.sx27-ring{{position:absolute!important;z-index:8!important;left:50%;top:50%;width:18px;height:18px;border-radius:999px;pointer-events:none;border:1px solid rgba(255,255,255,.28);box-shadow:0 0 22px rgba(96,165,250,.45);transform:translate(-50%,-50%) scale(.25);opacity:0;animation:sx27-ring 440ms ease-out forwards!important}}
@keyframes sx27-ring{{30%{{opacity:.58}}100%{{opacity:0;transform:translate(-50%,-50%) scale(4.8)}}}}
body[data-sx27-transition="1"] #content{{transform-origin:50% 8%}}
@media(prefers-reduced-motion:reduce){{#sx27Flash,.sx27-ring{{display:none!important;animation:none!important}}}}
</style>'''

SCRIPT = r'''<script id="sentrix-dashboard-motion-audio-v27-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardMotionAudioV27) return;
  window.__sentrixDashboardMotionAudioV27 = true;

  const content = document.getElementById("content") || document.querySelector(".workspace");
  if (!content) return;
  const reducedQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const reduced = () => !!reducedQuery?.matches;
  const navSelector = ".nav button,button[data-tab],[data-page],[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],.palette-item,.guild-btn,[data-guild]";
  const surfaceSelector = ".card,.metric,.p18-card,.p18-kpi,.sx12-hero,.sx12-card,.sx12-kpi,.sx12-item,.sx12-invite-card,.sx12-webhook-card,.sx12-flow-card,.permission-grid,.fields,.list";
  const rowSelector = ".row,.p18-table tbody tr,.sx12-table tbody tr,.sx12-event";
  let pageAnimation = null;
  let transitionPending = false;
  let settleTimer = null;
  let progressTimer = null;
  let lastSignature = "";
  let audioContext = null;
  let soundEnabled = localStorage.getItem("sentrix:ui-sound-v27") !== "0";

  // Barre de progression fixée en haut retirée à la demande : quatre couches (V19, V25, V26,
  // V27) empilaient chacune la leur, ce qui se lisait comme un chargement permanent.
  const flash = document.createElement("div");
  flash.id = "sx27Flash";
  flash.setAttribute("aria-hidden", "true");
  document.body.appendChild(flash);

  const setProgress = () => {};
  const startProgress = () => {
    clearTimeout(progressTimer);
    setProgress(.06);
    requestAnimationFrame(() => setProgress(.38));
    progressTimer = setTimeout(() => setProgress(.72), 150);
  };
  const finishProgress = () => {
    clearTimeout(progressTimer);
    setProgress(1);
    progressTimer = setTimeout(() => {
      setProgress(0);
    }, reduced() ? 0 : 220);
  };

  const ensureAudio = () => {
    if (!soundEnabled) return null;
    if (!audioContext) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return null;
      audioContext = new Ctx();
    }
    if (audioContext.state === "suspended") audioContext.resume().catch(() => {});
    return audioContext;
  };
  const tone = (kind="action") => {
    const ctx = ensureAudio();
    if (!ctx) return;
    const profiles = {
      nav:[470,690,.072,.026],
      primary:[610,760,.055,.022],
      action:[520,610,.045,.017],
      toggle:[430,545,.040,.016],
      danger:[300,245,.060,.020]
    };
    const [from,to,duration,volume] = profiles[kind] || profiles.action;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(from, now);
    osc.frequency.exponentialRampToValueAtTime(Math.max(40,to), now + duration);
    gain.gain.setValueAtTime(.0001, now);
    gain.gain.exponentialRampToValueAtTime(volume, now + .008);
    gain.gain.exponentialRampToValueAtTime(.0001, now + duration);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + duration + .012);
  };
  const classifySound = button => {
    if (!button) return "action";
    const text = (button.textContent || "").toLocaleLowerCase("fr");
    const intent = button.dataset?.sx24Intent || "";
    if (intent === "danger" || button.classList.contains("danger") || /(supprimer|ban|kick|révoquer|désactiver)/.test(text)) return "danger";
    if (button.matches(".switch,[role='switch']") || button.closest("label")?.querySelector(".switch")) return "toggle";
    if (intent === "primary" || button.classList.contains("primary") || /(créer|enregistrer|confirmer|activer|publier|sauvegarder)/.test(text)) return "primary";
    return "action";
  };

  // Le « flash » plein écran de navigation a été retiré : un voile qui apparaît puis
  // disparaît sur toute la page se lit comme un clignotement.
  const animateFlash = () => {};
  // Règle anti-clignotement : la page en place reste affichée telle quelle pendant un
  // chargement ; seules les données changent. Aucune sortie (assombrissement, flou,
  // réduction) n'est jouée, et l'entrée d'une NOUVELLE page est un léger glissement
  // sans passer par opacity 0.
  const animateExit = () => {
    pageAnimation?.cancel();
    pageAnimation = null;
  };
  const animateSurfaceNodes = () => {
    if (reduced()) return;
    [...content.querySelectorAll(surfaceSelector)].slice(0,24).forEach((node,index) => {
      node.getAnimations().forEach(a => a.cancel());
      node.animate([
        {opacity:.72,transform:"translateY(8px)"},
        {opacity:1,transform:"none"}
      ],{duration:260,delay:Math.min(index,10)*22,easing:"cubic-bezier(.16,1,.3,1)"});
    });
  };
  const animateEnter = () => {
    transitionPending = false;
    document.body.dataset.sx27Transition = "0";
    pageAnimation?.cancel();
    pageAnimation = null;
    if (!reduced()) {
      pageAnimation = content.animate([
        {opacity:.85,transform:"translateY(6px)"},
        {opacity:1,transform:"translateY(0)"}
      ],{duration:220,easing:"cubic-bezier(.16,1,.3,1)"});
      pageAnimation.finished.then(() => { pageAnimation = null; }).catch(() => {});
      animateSurfaceNodes();
    }
    finishProgress();
    document.dispatchEvent(new CustomEvent("sentrix:v27-page-enter"));
  };
  const beginTransition = () => {
    if (transitionPending) return;
    transitionPending = true;
    document.body.dataset.sx27Transition = "1";
    startProgress();
    animateExit();
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => { if (transitionPending) animateEnter(); }, 1200);
  };

  const signature = () => {
    const heading = content.querySelector("h1,h2")?.textContent?.trim() || "";
    const tab = document.body.dataset.sxTab || new URL(location.href).searchParams.get("tab") || "";
    const cards = content.querySelectorAll(".card,.sx12-card,.p18-card").length;
    return `${tab}|${heading}|${cards}|${content.childElementCount}`;
  };
  const settleFromDom = () => {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => {
      const next = signature();
      lastSignature = next;
      // Un rafraîchissement de données (lignes, compteurs, badges) ne rejoue JAMAIS
      // l'entrée des cartes : c'était la cause du clignotement à chaque mise à jour.
      // Seule une vraie navigation (transition en attente) anime l'arrivée de la page.
      if (transitionPending) animateEnter();
    }, 24);
  };

  document.addEventListener("pointerdown", event => {
    if (!event.isTrusted) return;
    const button = event.target.closest("button,.btn,[role='button'],.switch");
    if (!button || button.matches(":disabled,[aria-disabled='true']")) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    ensureAudio();
    const nav = event.target.closest(navSelector);
    tone(nav ? "nav" : classifySound(button));
    if (!reduced()) {
      button.animate([
        {transform:"scale(1)"},
        {transform:"translateY(2px) scale(.90)",offset:.38},
        {transform:"translateY(-1px) scale(1.035)",offset:.74},
        {transform:"scale(1)"}
      ],{duration:210,easing:"cubic-bezier(.16,1,.3,1)"});
      const ring = document.createElement("span");
      ring.className = "sx27-ring";
      button.style.position ||= "relative";
      button.style.overflow ||= "hidden";
      button.appendChild(ring);
      ring.addEventListener("animationend",()=>ring.remove(),{once:true});
    }
    if (nav) {
      beginTransition();
      if (!reduced()) nav.animate([
        {transform:"translateX(0) scale(1)"},
        {transform:"translateX(5px) scale(1.045)",offset:.55},
        {transform:"translateX(0) scale(1)"}
      ],{duration:270,easing:"cubic-bezier(.16,1,.3,1)"});
    }
  }, {capture:true,passive:true});

  new MutationObserver(records => {
    if (records.some(r => r.type === "childList" && (r.addedNodes.length || r.removedNodes.length))) settleFromDom();
  }).observe(content,{childList:true,subtree:true});

  // Seul un VRAI changement d'onglet est une navigation : un setAttribute avec la même
  // valeur (l'adaptateur V9 réécrivait data-sx-tab toutes les 1,5 s) produit aussi un
  // enregistrement de mutation, et relançait l'entrée de page + des cartes en boucle.
  new MutationObserver(records => {
    const changed = records.some(r => r.oldValue !== document.body.getAttribute("data-sx-tab"));
    if (!changed) return;
    beginTransition();
    settleFromDom();
  }).observe(document.body,{attributes:true,attributeOldValue:true,attributeFilter:["data-sx-tab"]});


  window.__sentrixMotionV27 = {
    get soundEnabled(){return soundEnabled},
    setSound(enabled){soundEnabled=!!enabled;localStorage.setItem("sentrix:ui-sound-v27",soundEnabled?"1":"0");return soundEnabled},
    preview(){beginTransition();setTimeout(animateEnter,170);tone("nav")}
  };

  lastSignature = signature();
})();
</script>'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if STYLE_MARKER not in html and "</head>" in html:
        html = html.replace("</head>", STYLE + "\n</head>", 1)
    if "sentrix-dashboard-motion-audio-v27-js" not in html and "</body>" in html:
        html = html.replace("</body>", SCRIPT + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    ok = STYLE_MARKER in html and JS_MARKER in html
    logger.info("Dashboard Motion + Audio V27 installed=%s.", ok)
    return ok


__all__ = ["install", "STYLE_MARKER", "JS_MARKER", "STYLE", "SCRIPT"]
