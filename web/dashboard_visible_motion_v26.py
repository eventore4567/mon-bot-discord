"""SentriX Dashboard V26 — visible motion authority.

Presentation-only layer that makes page, loading, button and surface motion clearly perceptible
on the real dashboard while preserving performance and reduced-motion accessibility.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-visible-motion-v26")

STYLE_MARKER = "sentrix-dashboard-visible-motion-v26"
JS_MARKER = "__sentrixDashboardVisibleMotionV26"

STYLE = f'''<style id="{STYLE_MARKER}">
:root{{--sx26-fast:140ms;--sx26-page:340ms;--sx26-card:420ms;--sx26-ease:cubic-bezier(.2,.8,.2,1);--sx26-spring:cubic-bezier(.16,1,.3,1)}}
#sx26Progress{{position:fixed;z-index:2147483000;left:0;top:0;width:100%;height:4px;opacity:0;pointer-events:none;transform:scaleX(0);transform-origin:left center;background:linear-gradient(90deg,#2563eb,#60a5fa 58%,#b8e0ff);box-shadow:0 0 18px rgba(96,165,250,.68);transition:transform 240ms var(--sx26-ease),opacity 120ms ease}}
#sx26Progress.show{{opacity:1}}
#sx26Shade{{position:fixed;z-index:2147482000;inset:0;pointer-events:none;opacity:0;background:radial-gradient(circle at 50% 10%,rgba(64,150,230,.08),transparent 35%),rgba(4,8,12,.13);backdrop-filter:blur(1px);transition:opacity 150ms ease}}
body.sx26-loading #sx26Shade{{opacity:1}}
#content.sx26-out{{opacity:.25!important;transform:translateY(10px) scale(.992)!important;filter:blur(1px);transition:opacity 120ms ease,transform 120ms ease,filter 120ms ease!important}}
#content.sx26-in{{animation:sx26-page-in var(--sx26-page) var(--sx26-spring) both}}
@keyframes sx26-page-in{{0%{{opacity:0;transform:translateY(18px) scale(.988);filter:blur(3px)}}55%{{opacity:1;transform:translateY(-2px) scale(1.002);filter:blur(0)}}100%{{opacity:1;transform:none;filter:none}}}}
.sx26-stagger{{animation:sx26-surface-in var(--sx26-card) var(--sx26-spring) both;animation-delay:calc(var(--sx26-order,0) * 42ms)}}
@keyframes sx26-surface-in{{0%{{opacity:0;transform:translateY(18px) scale(.985)}}70%{{opacity:1;transform:translateY(-1px) scale(1.001)}}100%{{opacity:1;transform:none}}}}
.sx26-row{{animation:sx26-row-in 300ms var(--sx26-ease) both;animation-delay:calc(var(--sx26-order,0) * 20ms)}}
@keyframes sx26-row-in{{from{{opacity:0;transform:translateX(-12px)}}to{{opacity:1;transform:none}}}}
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]){{transform-origin:center;transition:transform 110ms var(--sx26-ease),box-shadow 160ms ease,filter 160ms ease!important}}
@media(hover:hover) and (pointer:fine){{:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):not(:disabled):hover{{transform:translateY(-2px) scale(1.012)!important;filter:brightness(1.05)}}}}
:where(.btn,button[data-sx24-intent],.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page]):not(:disabled):active{{transform:translateY(2px) scale(.955)!important;filter:brightness(.96);transition-duration:55ms!important}}
.sx26-ripple{{position:absolute!important;z-index:3!important;width:18px;height:18px;border-radius:999px;pointer-events:none;background:rgba(255,255,255,.42);box-shadow:0 0 0 1px rgba(255,255,255,.08);transform:translate(-50%,-50%) scale(0);animation:sx26-ripple 600ms ease-out forwards!important}}
@keyframes sx26-ripple{{35%{{opacity:.28}}100%{{opacity:0;transform:translate(-50%,-50%) scale(22)}}}}
:where(.nav button,.p18-tab,[data-sx12-tab],[data-p18-tab],[data-page]){{position:relative}}
:where(.nav button,.p18-tab,[data-sx12-tab],[data-p18-tab],[data-page]).sx26-active-pop{{animation:sx26-nav-pop 300ms var(--sx26-spring)}}
@keyframes sx26-nav-pop{{0%{{transform:translateX(-4px) scale(.97)}}55%{{transform:translateX(2px) scale(1.02)}}100%{{transform:none}}}}
:where(.toast,[data-toast],.snackbar).sx26-toast{{animation:sx26-toast-in 360ms var(--sx26-spring) both!important}}
@keyframes sx26-toast-in{{from{{opacity:0;transform:translateY(22px) scale(.94)}}60%{{opacity:1;transform:translateY(-2px) scale(1.01)}}to{{transform:none}}}}
:where([role="dialog"],.modal,.drawer,.sheet).sx26-dialog{{animation:sx26-dialog-in 380ms var(--sx26-spring) both!important}}
@keyframes sx26-dialog-in{{from{{opacity:0;transform:translateY(24px) scale(.94)}}65%{{opacity:1;transform:translateY(-2px) scale(1.01)}}to{{transform:none}}}}
:where(.modal-backdrop,.overlay,.drawer-backdrop).sx26-overlay{{animation:sx26-overlay-in 220ms ease both!important}}
@keyframes sx26-overlay-in{{from{{opacity:0}}to{{opacity:1}}}}
:where(.sx12-skeleton,.skeleton,[data-skeleton]){{background-size:280% 100%!important;animation:sx26-skeleton 1s ease-in-out infinite!important}}
@keyframes sx26-skeleton{{0%{{background-position:180% 0}}100%{{background-position:-80% 0}}}}
.sx26-success{{animation:sx26-success 480ms var(--sx26-spring)!important}}
@keyframes sx26-success{{0%{{transform:scale(.9);filter:brightness(1)}}45%{{transform:scale(1.08);filter:brightness(1.25)}}100%{{transform:none;filter:none}}}}
@media(prefers-reduced-motion:reduce){{#sx26Progress,#sx26Shade,#content,.sx26-stagger,.sx26-row,.sx26-ripple,.sx26-active-pop,.sx26-toast,.sx26-dialog,.sx26-overlay,.sx26-success,:where(.sx12-skeleton,.skeleton,[data-skeleton]){{animation:none!important;transition:none!important;transform:none!important;filter:none!important}}#sx26Shade{{display:none!important}}}}
</style>'''

SCRIPT = r'''<script id="sentrix-dashboard-visible-motion-v26-js">
(() => {
  "use strict";
  if (window.__sentrixDashboardVisibleMotionV26) return;
  window.__sentrixDashboardVisibleMotionV26 = true;

  const reducedQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  const reduced = () => !!reducedQuery?.matches;
  const content = document.getElementById("content") || document.querySelector(".workspace");
  const navSelector = ".nav button,.p18-tab,[data-sx12-tab],[data-sx12-go],[data-p18-tab],[data-p18-go],[data-page],.palette-item,[data-guild]";
  const surfaceSelector = ".sx12-hero,.card,.p18-card,.sx12-card,.metric,.p18-kpi,.sx12-kpi,.p18-result,.sx12-item,.sx12-invite-card,.sx12-webhook-card,.sx12-flow-card,.sx-empty-premium";
  const rowSelector = ".row,.sx12-table tbody tr,.p18-table tbody tr,.sx12-event";
  let busy = false;
  let timer = null;
  let settleTimer = null;
  let lastSignature = "";

  const progress = document.createElement("div");
  progress.id = "sx26Progress";
  progress.setAttribute("aria-hidden", "true");
  document.body.appendChild(progress);
  const shade = document.createElement("div");
  shade.id = "sx26Shade";
  shade.setAttribute("aria-hidden", "true");
  document.body.appendChild(shade);

  const setProgress = n => progress.style.transform = `scaleX(${Math.max(0,Math.min(1,n))})`;
  const begin = () => {
    clearTimeout(timer);
    busy = true;
    document.body.classList.add("sx26-loading");
    content?.classList.remove("sx26-in");
    content?.classList.add("sx26-out");
    progress.classList.add("show");
    setProgress(.1);
    requestAnimationFrame(() => setProgress(.42));
    timer = setTimeout(() => setProgress(.76), 180);
  };
  const end = () => {
    if (!busy && !document.body.classList.contains("sx26-loading")) return;
    clearTimeout(timer);
    busy = false;
    setProgress(1);
    document.body.classList.remove("sx26-loading");
    content?.classList.remove("sx26-out");
    if (!reduced() && content) {
      content.classList.remove("sx26-in");
      void content.offsetWidth;
      content.classList.add("sx26-in");
    }
    animateSurfaces();
    timer = setTimeout(() => {
      progress.classList.remove("show");
      setProgress(0);
    }, reduced() ? 0 : 240);
  };

  const replay = (node, cls) => {
    if (!(node instanceof HTMLElement) || reduced()) return;
    node.classList.remove(cls);
    void node.offsetWidth;
    node.classList.add(cls);
  };
  const animateSurfaces = () => {
    if (!content || reduced()) return;
    [...content.querySelectorAll(surfaceSelector)].slice(0,30).forEach((node,index) => {
      node.style.setProperty("--sx26-order", String(index));
      replay(node,"sx26-stagger");
    });
    [...content.querySelectorAll(rowSelector)].slice(0,36).forEach((node,index) => {
      node.style.setProperty("--sx26-order", String(index));
      replay(node,"sx26-row");
    });
  };
  const signature = () => {
    const heading = content?.querySelector("h1,h2")?.textContent?.trim() || "";
    const page = content?.querySelector(".sx12-page,.p18-page,.card,.sx-empty-premium")?.className || "";
    return `${heading}|${page}|${content?.childElementCount || 0}`;
  };
  const scheduleSettle = () => {
    clearTimeout(settleTimer);
    settleTimer = setTimeout(() => {
      const sig = signature();
      if (sig !== lastSignature || busy) {
        lastSignature = sig;
        end();
      }
    }, 35);
  };

  document.addEventListener("click", event => {
    const nav = event.target.closest(navSelector);
    if (nav) {
      begin();
      replay(nav,"sx26-active-pop");
      clearTimeout(settleTimer);
      settleTimer = setTimeout(() => { if (busy) end(); }, 1200);
    }
  }, true);

  document.addEventListener("pointerdown", event => {
    if (reduced()) return;
    const button = event.target.closest("button,.btn,[role='button']");
    if (!button || button.matches(":disabled,[aria-disabled='true']")) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const rect = button.getBoundingClientRect();
    const ripple = document.createElement("span");
    ripple.className = "sx26-ripple";
    ripple.style.left = `${event.clientX - rect.left}px`;
    ripple.style.top = `${event.clientY - rect.top}px`;
    button.appendChild(ripple);
    ripple.addEventListener("animationend", () => ripple.remove(), {once:true});
  }, {capture:true,passive:true});

  if (content) {
    new MutationObserver(() => scheduleSettle()).observe(content,{childList:true,subtree:true,characterData:true});
    new MutationObserver(() => {
      const ownBusy = content.getAttribute("aria-busy") === "true" || !!content.querySelector('[aria-busy="true"]');
      if (ownBusy) begin(); else scheduleSettle();
    }).observe(content,{attributes:true,subtree:true,attributeFilter:["aria-busy"]});
  }

  const decorateAdded = root => {
    if (!(root instanceof HTMLElement)) return;
    [root,...(root.querySelectorAll?.(".toast,[data-toast],.snackbar,[role='dialog'],.modal,.drawer,.sheet,.modal-backdrop,.overlay,.drawer-backdrop") || [])].forEach(node => {
      if (node.matches?.(".toast,[data-toast],.snackbar")) replay(node,"sx26-toast");
      else if (node.matches?.("[role='dialog'],.modal,.drawer,.sheet")) replay(node,"sx26-dialog");
      else if (node.matches?.(".modal-backdrop,.overlay,.drawer-backdrop")) replay(node,"sx26-overlay");
    });
  };
  new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(decorateAdded))).observe(document.body,{childList:true,subtree:true});

  document.addEventListener("sentrix:live", () => {
    if (reduced() || !content) return;
    content.querySelectorAll(".notice.ok,.badge.ok,.sx12-badge.ok").forEach(node => replay(node,"sx26-success"));
  });
  window.addEventListener("pageshow", () => requestAnimationFrame(() => { lastSignature = signature(); animateSurfaces(); }));
  requestAnimationFrame(() => { lastSignature = signature(); animateSurfaces(); });
})();
</script>'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if STYLE_MARKER not in html and "</head>" in html:
        html = html.replace("</head>", STYLE + "\n</head>", 1)
    if "sentrix-dashboard-visible-motion-v26-js" not in html and "</body>" in html:
        html = html.replace("</body>", SCRIPT + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    ok = STYLE_MARKER in html and JS_MARKER in html
    logger.info("Dashboard Visible Motion V26 installed=%s.", ok)
    return ok


__all__ = ["install", "STYLE_MARKER", "JS_MARKER", "STYLE", "SCRIPT"]
