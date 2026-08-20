"""Accessibilité du dashboard SentriX V2.3.

Injection non destructive : aucune route ni permission n'est modifiée. Cette couche ajoute
uniquement des aides clavier/lecteur d'écran, contraste, cibles tactiles et réduction des
animations au HTML déjà protégé par le dashboard principal.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-accessibility")
_INSTALLED = False

A11Y_CSS = r"""
<style id="sentrix-a11y-css">
  .sx-skip-link{
    position:fixed;left:12px;top:10px;z-index:100000;transform:translateY(-150%);
    padding:10px 14px;border-radius:8px;background:#fff;color:#000;font-weight:800;
    box-shadow:0 4px 18px rgba(0,0,0,.35);
  }
  .sx-skip-link:focus{transform:translateY(0)}
  .sx-sr-only{
    position:absolute!important;width:1px!important;height:1px!important;padding:0!important;
    margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;
    white-space:nowrap!important;border:0!important;
  }
  :where(button,a,input,select,textarea,[role="button"]):focus-visible{
    outline:3px solid #ffffff!important;outline-offset:3px!important;
    box-shadow:0 0 0 5px #5865f2!important;
  }
  :where(button,select,input[type="button"],input[type="submit"],[role="button"]){min-height:44px}
  :where(input,select,textarea){font-size:max(16px,1em)}
  [aria-disabled="true"],button:disabled{cursor:not-allowed;opacity:.62}
  .sx-v21-dot,[aria-hidden="true"]{pointer-events:none}

  @media (prefers-reduced-motion: reduce){
    *,*::before,*::after{
      animation-duration:.001ms!important;animation-iteration-count:1!important;
      transition-duration:.001ms!important;scroll-behavior:auto!important;
    }
  }
  @media (prefers-contrast: more){
    :root{--muted:#d1d5db!important;--line:#8b95aa!important}
    .sx-v2-strip,.sx-v2-metric,.sx-v2-link,.sx-v21-chip{border-width:2px!important}
    :where(button,a,input,select,textarea){text-decoration-thickness:2px}
  }
  @media (forced-colors: active){
    *{forced-color-adjust:auto}
    .sx-v2-bar i,.sx-v21-dot{forced-color-adjust:none;background:Highlight!important}
    :where(button,a,input,select,textarea,[role="button"]):focus-visible{outline:3px solid Highlight!important;box-shadow:none!important}
  }
  @media(max-width:560px){
    :where(button,[role="button"],select){min-height:48px}
    :where(button,[role="button"]){line-height:1.25}
  }
</style>
"""

A11Y_JS = r"""
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
      const explicit = id ? document.querySelector(`label[for="${CSS.escape(id)}"]`) : null;
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

    root.querySelectorAll(".sx-v21-dot,.sx-v2-bar").forEach(el => el.setAttribute("aria-hidden","true"));
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
    if (!document.documentElement.lang) document.documentElement.lang = "fr";
    ensureSkipLink();
    labelControls();
    markCurrentNavigation();
  }

  function schedule(){
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(enhance);
  }

  const observer = new MutationObserver(schedule);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)schedule();});
  window.addEventListener("popstate",schedule);
  setTimeout(schedule,25);
})();
</script>
"""


def install(dashboard_module) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    html = dashboard_module.INDEX_HTML
    if 'id="sentrix-a11y-css"' not in html:
        html = html.replace("</head>", A11Y_CSS + "\n</head>", 1)
    if 'id="sentrix-a11y-js"' not in html:
        html = html.replace("</body>", A11Y_JS + "\n</body>", 1)
    dashboard_module.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Dashboard V2.3 accessibilité installé : clavier, contraste, mobile et lecteurs d'écran.")
