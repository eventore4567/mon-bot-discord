"""SentriX Dashboard V25 — premium motion system.

Presentation-only final layer for event-driven motion across the real dashboard. V25 animates
page changes, buttons, cards, dialogs, toasts, skeletons and loading state while respecting
prefers-reduced-motion. It adds no routes, data, polling or business behavior.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-motion-system-v25")

STYLE_MARKER = "sentrix-dashboard-motion-system-v25"
JS_MARKER = "__sentrixDashboardMotionSystemV25"

STYLE = f'''<style id="{STYLE_MARKER}">
:root{{
  --sx25-fast:120ms;--sx25-ui:180ms;--sx25-page:260ms;--sx25-slow:420ms;
  --sx25-ease:cubic-bezier(.2,.8,.2,1);--sx25-spring:cubic-bezier(.16,1,.3,1);
}}
#content.sx25-page-in{{animation:sx25-page-in var(--sx25-page) var(--sx25-spring) both}}
#content.sx25-page-out{{opacity:1;transform:none;transition:none}}
@keyframes sx25-page-in{{from{{opacity:1;transform:translateY(2px)}}to{{opacity:1;transform:none}}}}
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]){{position:relative;overflow:hidden;isolation:isolate;transform-origin:center;will-change:auto}}
@media(hover:hover) and (pointer:fine){{
  :where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):not(:disabled):hover{{transform:translateY(-1px)}}
}}
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):not(:disabled):active{{transform:translateY(1px) scale(.975)!important;transition-duration:70ms!important}}
.sx25-ripple{{position:absolute;z-index:-1;width:16px;height:16px;border-radius:999px;pointer-events:none;background:rgba(255,255,255,.24);transform:translate(-50%,-50%) scale(0);animation:sx25-ripple 520ms ease-out forwards}}
@keyframes sx25-ripple{{70%{{opacity:.16}}to{{opacity:0;transform:translate(-50%,-50%) scale(15)}}}}
:where(.card,.p18-card,.sx12-card,.metric,.p18-kpi,.sx12-kpi,.p18-result,.sx12-item,.sx12-invite-card,.sx12-webhook-card,.sx12-flow-card).sx25-enter{{animation:sx25-card-in 360ms var(--sx25-spring) both;animation-delay:calc(var(--sx25-order,0) * 24ms)}}
@keyframes sx25-card-in{{from{{opacity:1;transform:translateY(3px)}}to{{opacity:1;transform:none}}}}
:where(.row,.sx12-table tbody tr,.p18-table tbody tr).sx25-row-enter{{animation:sx25-row-in 260ms var(--sx25-ease) both;animation-delay:calc(var(--sx25-order,0) * 14ms)}}
@keyframes sx25-row-in{{from{{opacity:1;transform:translateX(-2px)}}to{{opacity:1;transform:none}}}}
:where(.toast,[data-toast],.snackbar).sx25-toast-enter{{animation:sx25-toast-in 300ms var(--sx25-spring) both}}
@keyframes sx25-toast-in{{from{{opacity:0;transform:translateY(12px) scale(.97)}}to{{opacity:1;transform:none}}}}
:where([role="dialog"],.modal,.drawer,.sheet).sx25-dialog-enter{{animation:sx25-dialog-in 300ms var(--sx25-spring) both}}
@keyframes sx25-dialog-in{{from{{opacity:0;transform:translateY(10px) scale(.985)}}to{{opacity:1;transform:none}}}}
:where(.modal-backdrop,.overlay,.drawer-backdrop).sx25-overlay-enter{{animation:sx25-fade-in 180ms ease both}}
@keyframes sx25-fade-in{{from{{opacity:0}}to{{opacity:1}}}}
:where(.sx12-skeleton,.skeleton,[data-skeleton]){{position:relative;overflow:hidden}}
:where(.sx12-skeleton,.skeleton,[data-skeleton])::after{{content:"";position:absolute;inset:0;transform:translateX(-100%);background:linear-gradient(90deg,transparent,rgba(132,184,230,.11),transparent);animation:sx25-shimmer 1.25s linear infinite}}
@keyframes sx25-shimmer{{to{{transform:translateX(100%)}}}}
:where(.nav button,.p18-tab,[data-sx12-tab],[data-p18-tab],[data-page]){{transition:background-color var(--sx25-ui) var(--sx25-ease),color var(--sx25-ui) var(--sx25-ease),border-color var(--sx25-ui) var(--sx25-ease),transform var(--sx25-fast) var(--sx25-ease),box-shadow var(--sx25-ui) var(--sx25-ease)!important}}
:where(.nav button,.p18-tab,[data-sx12-tab],[data-p18-tab],[data-page])[aria-current="page"],:where(.nav button,.p18-tab,[data-sx12-tab],[data-p18-tab],[data-page]).active{{animation:sx25-selected 260ms var(--sx25-spring)}}
@keyframes sx25-selected{{from{{transform:scale(.985)}}55%{{transform:scale(1.012)}}to{{transform:none}}}}
:where(.notice.ok,.badge.ok,.sx12-badge.ok).sx25-state-change{{animation:sx25-success 380ms var(--sx25-spring)}}
@keyframes sx25-success{{0%{{transform:scale(.96)}}55%{{transform:scale(1.035)}}100%{{transform:none}}}}
:where(input,select,textarea){{transition:border-color var(--sx25-ui) ease,box-shadow var(--sx25-ui) ease,background-color var(--sx25-ui) ease}}
@media(prefers-reduced-motion:reduce){{
  #content.sx25-page-in,#content.sx25-page-out,.sx25-enter,.sx25-row-enter,.sx25-toast-enter,.sx25-dialog-enter,.sx25-overlay-enter,.sx25-state-change{{animation:none!important;transition:none!important;transform:none!important}}
  .sx25-ripple,:where(.sx12-skeleton,.skeleton,[data-skeleton])::after{{display:none!important;animation:none!important}}
  :where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]){{transform:none!important}}
}}
</style>'''

SCRIPT = r'''<script id="sentrix-dashboard-motion-system-v25-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardMotionSystemV25) return;
  window.__sentrixDashboardMotionSystemV25 = true;

  const reducedQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const reduced = () => !!reducedQuery?.matches;
  const content = document.getElementById("content");
  const navSelector = ".nav button,.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page],.palette-item,[data-guild]";
  let navigationPending = false;
  let progressTimer = null;
  let lastHeading = content?.querySelector("h1,h2")?.textContent?.trim() || "";

  // Barre de progression fixée en haut retirée à la demande : quatre couches (V19, V25, V26,
  // V27) empilaient chacune la leur, ce qui se lisait comme un chargement permanent.
  const setProgress = () => {};
  const startProgress = () => {
    clearTimeout(progressTimer);
    setProgress(.08);
    requestAnimationFrame(() => setProgress(.34));
    progressTimer = setTimeout(() => setProgress(.68), 180);
  };
  const finishProgress = () => {
    clearTimeout(progressTimer);
    setProgress(1);
    progressTimer = setTimeout(() => {
      setProgress(0);
    }, reduced() ? 0 : 190);
  };

  const replayClass = (node, className) => {
    if (!(node instanceof HTMLElement) || reduced()) return;
    node.classList.remove(className);
    void node.offsetWidth;
    node.classList.add(className);
  };

  const animateSurface = () => {
    if (!content) return;
    content.classList.remove("sx25-page-out");
    replayClass(content, "sx25-page-in");
    const cards = [...content.querySelectorAll(".card,.p18-card,.sx12-card,.metric,.p18-kpi,.sx12-kpi,.p18-result,.sx12-item,.sx12-invite-card,.sx12-webhook-card,.sx12-flow-card")].slice(0,24);
    cards.forEach((node, index) => {
      node.style.setProperty("--sx25-order", String(Math.min(index, 8)));
      replayClass(node, "sx25-enter");
    });
    const rows = [...content.querySelectorAll(".row,.sx12-table tbody tr,.p18-table tbody tr")].slice(0,28);
    rows.forEach((node, index) => {
      node.style.setProperty("--sx25-order", String(Math.min(index, 8)));
      replayClass(node, "sx25-row-enter");
    });
  };

  const settleNavigation = () => {
    navigationPending = false;
    animateSurface();
    finishProgress();
  };

  if (content) {
    new MutationObserver(() => {
      const heading = content.querySelector("h1,h2")?.textContent?.trim() || "";
      if (navigationPending || (heading && heading !== lastHeading)) {
        lastHeading = heading;
        requestAnimationFrame(settleNavigation);
      }
    }).observe(content, {childList:true,subtree:true});

    new MutationObserver(() => {
      if (content.getAttribute("aria-busy") === "true") startProgress();
      else if (!navigationPending) finishProgress();
    }).observe(content, {attributes:true,attributeFilter:["aria-busy"]});
  }

  document.addEventListener("click", event => {
    const target = event.target.closest(navSelector);
    if (!target) return;
    navigationPending = true;
    startProgress();
  }, true);

  document.addEventListener("pointerdown", event => {
    if (reduced()) return;
    const button = event.target.closest("button,.btn,[role='button']");
    if (!button || button.matches(":disabled,[aria-disabled='true']")) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const rect = button.getBoundingClientRect();
    const ripple = document.createElement("span");
    ripple.className = "sx25-ripple";
    ripple.style.left = `${event.clientX - rect.left}px`;
    ripple.style.top = `${event.clientY - rect.top}px`;
    button.appendChild(ripple);
    ripple.addEventListener("animationend", () => ripple.remove(), {once:true});
  }, {capture:true,passive:true});

  const decorateAdded = root => {
    if (!(root instanceof HTMLElement)) return;
    const nodes = [root, ...root.querySelectorAll?.(".toast,[data-toast],.snackbar,[role='dialog'],.modal,.drawer,.sheet,.modal-backdrop,.overlay,.drawer-backdrop") || []];
    nodes.forEach(node => {
      if (node.matches?.(".toast,[data-toast],.snackbar")) replayClass(node, "sx25-toast-enter");
      else if (node.matches?.("[role='dialog'],.modal,.drawer,.sheet")) replayClass(node, "sx25-dialog-enter");
      else if (node.matches?.(".modal-backdrop,.overlay,.drawer-backdrop")) replayClass(node, "sx25-overlay-enter");
    });
  };
  new MutationObserver(records => {
    records.forEach(record => record.addedNodes.forEach(decorateAdded));
  }).observe(document.body, {childList:true,subtree:true});

  // Plus de pulsation des badges à chaque tick temps réel (20 s) : trois couches la
  // rejouaient en même temps, ce qui se lisait comme un clignotement périodique.
  window.addEventListener("pageshow", () => requestAnimationFrame(animateSurface));

  requestAnimationFrame(animateSurface);
})();
</script>'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if STYLE_MARKER not in html and "</head>" in html:
        html = html.replace("</head>", STYLE + "\n</head>", 1)
    if "sentrix-dashboard-motion-system-v25-js" not in html and "</body>" in html:
        html = html.replace("</body>", SCRIPT + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    ok = STYLE_MARKER in html and JS_MARKER in html
    logger.info("Dashboard Motion System V25 installed=%s.", ok)
    return ok


__all__ = ["install", "STYLE_MARKER", "JS_MARKER", "STYLE", "SCRIPT"]
