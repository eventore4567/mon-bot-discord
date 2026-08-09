"""Correctif robuste du basculement Mode simple / Mode avancé du dashboard."""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.simple-mode-switch-fix")
_INSTALLED = False


SWITCH_CSS = r"""
<style id="sentrix-simple-mode-switch-fix-css">
  #sxModeEscape{
    position:fixed;
    right:18px;
    bottom:18px;
    z-index:2147483000;
    min-width:132px;
    min-height:42px;
    padding:10px 14px;
    border:1px solid var(--line,#30384f);
    border-radius:12px;
    background:var(--panel,#121722);
    color:var(--text,#f5f7fb);
    font:inherit;
    font-weight:750;
    cursor:pointer;
    box-shadow:0 12px 30px rgba(0,0,0,.28);
  }
  #sxModeEscape:hover{filter:brightness(1.08)}
  #sxModeEscape:focus-visible{outline:2px solid var(--brand2,#8aa4ff);outline-offset:2px}
  @media(max-width:680px){
    #sxModeEscape{right:12px;bottom:12px;min-width:118px;min-height:40px;padding:9px 12px}
  }
</style>
"""


SWITCH_JS = r"""
<script id="sentrix-simple-mode-switch-fix-js">
(() => {
  "use strict";
  if (window.__sentrixSimpleModeSwitchFix) return;
  window.__sentrixSimpleModeSwitchFix = true;

  const MODE_KEY = "sentrix_dashboard_mode_v1";
  const byId = id => document.getElementById(id);

  function persist(mode){
    try { localStorage.setItem(MODE_KEY, mode); } catch (_) {}
  }

  function apply(mode){
    const advanced = mode === "advanced";
    persist(advanced ? "advanced" : "simple");

    document.body.classList.toggle("sx-simple-advanced", advanced);
    document.body.classList.toggle("sx-simple-mode", !advanced);
    document.body.classList.remove("sx-simple-detail");
    document.body.classList.toggle("sx-simple-home-active", !advanced);

    const home = byId("sxSimpleHome");
    if (home) home.classList.toggle("hidden", advanced);

    const back = byId("sxSimpleBack");
    if (back) back.style.removeProperty("display");

    const simpleButton = byId("sxUseSimple");
    const advancedButton = byId("sxUseAdvanced");
    if (simpleButton) {
      simpleButton.disabled = false;
      simpleButton.setAttribute("aria-pressed", advanced ? "false" : "true");
    }
    if (advancedButton) {
      advancedButton.disabled = false;
      advancedButton.setAttribute("aria-pressed", advanced ? "true" : "false");
    }

    const floating = byId("sxModeEscape");
    if (floating) {
      floating.textContent = advanced ? "Mode simple" : "Mode avancé";
      floating.setAttribute("aria-label", advanced ? "Passer au mode simple" : "Passer au mode avancé");
    }

    if (!advanced) {
      const message = byId("sxSimpleMessage");
      if (message && !message.textContent.trim()) message.textContent = "Choisissez un serveur puis une action.";
    }

    window.scrollTo({top:0, behavior:"smooth"});
  }

  function currentMode(){
    try {
      if (localStorage.getItem(MODE_KEY) === "advanced") return "advanced";
    } catch (_) {}
    return document.body.classList.contains("sx-simple-advanced") ? "advanced" : "simple";
  }

  function ensureEscapeButton(){
    if (!document.body || byId("sxModeEscape")) return;
    const button = document.createElement("button");
    button.id = "sxModeEscape";
    button.type = "button";
    button.textContent = currentMode() === "advanced" ? "Mode simple" : "Mode avancé";
    button.setAttribute("aria-label", button.textContent === "Mode simple" ? "Passer au mode simple" : "Passer au mode avancé");
    document.body.appendChild(button);
  }

  document.addEventListener("click", event => {
    const target = event.target.closest && event.target.closest("#sxUseSimple,#sxUseAdvanced,#sxModeEscape");
    if (!target) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    if (target.id === "sxUseAdvanced") {
      apply("advanced");
      return;
    }
    if (target.id === "sxUseSimple") {
      apply("simple");
      return;
    }
    apply(currentMode() === "advanced" ? "simple" : "advanced");
  }, true);

  function start(){
    ensureEscapeButton();
    const mode = currentMode();
    const floating = byId("sxModeEscape");
    if (floating) floating.textContent = mode === "advanced" ? "Mode simple" : "Mode avancé";

    const simpleButton = byId("sxUseSimple");
    const advancedButton = byId("sxUseAdvanced");
    if (simpleButton) simpleButton.disabled = false;
    if (advancedButton) advancedButton.disabled = false;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, {once:true});
  } else {
    start();
  }

  const observer = new MutationObserver(() => start());
  observer.observe(document.documentElement, {childList:true, subtree:true});
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    html = getattr(dashboard, "INDEX_HTML", "")
    if not isinstance(html, str) or "</body>" not in html:
        logger.warning("Correctif de bascule dashboard non installé : INDEX_HTML indisponible.")
        return

    if 'id="sentrix-simple-mode-switch-fix-js"' not in html:
        if "</head>" in html:
            html = html.replace("</head>", SWITCH_CSS + "\n</head>", 1)
        html = html.replace("</body>", SWITCH_JS + "\n</body>", 1)
        dashboard.INDEX_HTML = html

    logger.info("Bascule Mode simple / Mode avancé du dashboard renforcée.")
