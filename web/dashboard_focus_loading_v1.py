"""Affinage de la vue principale du dashboard SentriX.

Ce module conserve uniquement le rangement du panneau « Outils serveur » dans une fenêtre
dédiée. L'ancien loader plein écran ``sxDirectLoader`` est supprimé à la source : un module
de confort ne doit jamais bloquer /app ni attendre l'événement ``window.load``.
"""
from __future__ import annotations

from typing import Any

_INSTALLED = False

FOCUS_CSS = r"""
<style id="sentrix-focus-loading-css">
  #sxServerToolsLauncher{margin:0 0 18px;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:13px 15px;border:1px solid #2a3149;border-radius:13px;background:linear-gradient(180deg,#121827,#0d121c);box-shadow:0 5px 0 #080b12;animation:sxToolsLauncherIn .28s ease both}
  #sxServerToolsLauncher .sx-tools-launch-copy{min-width:0}
  #sxServerToolsLauncher b{display:block;font-size:13px;color:#eef1ff}
  #sxServerToolsLauncher span{display:block;margin-top:3px;color:#858fa7;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #sxOpenServerToolsPanel{flex:0 0 auto;border:1px solid #4d4b81;border-radius:9px;background:linear-gradient(180deg,#28264b,#1a1934);color:#f4f1ff;padding:9px 13px;font-weight:800;font-size:11px;cursor:pointer;transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease}
  #sxOpenServerToolsPanel:hover{transform:translateY(-1px);border-color:#7769df;box-shadow:0 8px 22px rgba(93,77,211,.17)}
  #sxServerToolsOverlay{position:fixed;inset:0;z-index:10020;display:none;align-items:center;justify-content:center;padding:28px;background:rgba(4,6,12,.76);backdrop-filter:blur(9px)}
  #sxServerToolsOverlay.show{display:flex;animation:sxToolsBackdrop .18s ease both}
  .sx-tools-modal-shell{width:min(1120px,calc(100vw - 42px));max-height:min(88vh,920px);display:flex;flex-direction:column;border:1px solid #303753;border-radius:20px;background:linear-gradient(180deg,#111725,#0b1019);box-shadow:0 38px 120px rgba(0,0,0,.68);overflow:hidden;animation:sxToolsModalIn .24s cubic-bezier(.2,.8,.2,1) both}
  .sx-tools-modal-top{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:17px 20px;border-bottom:1px solid #252d45;background:linear-gradient(180deg,#171d2c,#111725)}
  .sx-tools-modal-top h2{margin:0;font-size:17px;letter-spacing:-.025em}.sx-tools-modal-top p{margin:4px 0 0;color:#8e97ad;font-size:11px}
  #sxCloseServerToolsPanel{width:36px;height:36px;display:grid;place-items:center;border:1px solid #343c58;border-radius:10px;background:#0d121d;color:#c7cce0;font-size:20px;line-height:1;cursor:pointer}
  #sxCloseServerToolsPanel:hover{border-color:#6259ab;color:white}
  #sxServerToolsModalBody{overflow:auto;padding:20px}
  #sxServerToolsModalBody #sentrixServerTools{margin:0!important;box-shadow:none!important}
  @keyframes sxToolsLauncherIn{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
  @keyframes sxToolsBackdrop{from{opacity:0}to{opacity:1}}
  @keyframes sxToolsModalIn{from{opacity:0;transform:translateY(15px) scale(.985)}to{opacity:1;transform:none}}
  @media(max-width:720px){#sxServerToolsLauncher{align-items:flex-start;flex-direction:column}#sxOpenServerToolsPanel{width:100%}#sxServerToolsOverlay{padding:12px}.sx-tools-modal-shell{width:100%;max-height:94vh;border-radius:16px}#sxServerToolsModalBody{padding:12px}}
  @media(prefers-reduced-motion:reduce){#sxServerToolsLauncher,.sx-tools-modal-shell{animation:none!important;transition:none!important}}
</style>
"""

FOCUS_JS = r"""
<script id="sentrix-focus-loading-js">
(() => {
  "use strict";
  if (window.__sentrixFocusLoadingV1) return;
  window.__sentrixFocusLoadingV1 = true;

  function ensureOverlay(){
    let overlay = document.getElementById("sxServerToolsOverlay");
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = "sxServerToolsOverlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "sxServerToolsModalTitle");
    overlay.innerHTML = `
      <section class="sx-tools-modal-shell">
        <header class="sx-tools-modal-top">
          <div><h2 id="sxServerToolsModalTitle">Outils serveur</h2><p>Configuration et maintenance du serveur.</p></div>
          <button id="sxCloseServerToolsPanel" type="button" aria-label="Fermer">×</button>
        </header>
        <div id="sxServerToolsModalBody"></div>
      </section>`;
    document.body.appendChild(overlay);

    const close = () => {
      const wipe = document.getElementById("sxWipeDialog");
      if (wipe && wipe.open) return;
      overlay.classList.remove("show");
      document.body.style.removeProperty("overflow");
    };
    const open = () => {
      overlay.classList.add("show");
      document.body.style.overflow = "hidden";
      const closeButton = document.getElementById("sxCloseServerToolsPanel");
      if (closeButton) setTimeout(() => closeButton.focus(), 0);
    };
    overlay.addEventListener("click", event => { if (event.target === overlay) close(); });
    document.getElementById("sxCloseServerToolsPanel").addEventListener("click", close);
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && overlay.classList.contains("show")) close();
    });
    overlay._sentrixOpen = open;
    return overlay;
  }

  function ensureLauncher(host){
    let launcher = document.getElementById("sxServerToolsLauncher");
    if (launcher) return launcher;
    launcher = document.createElement("div");
    launcher.id = "sxServerToolsLauncher";
    launcher.innerHTML = `
      <div class="sx-tools-launch-copy"><b>Outils serveur</b><span>Configurer la structure ou ouvrir les outils de maintenance.</span></div>
      <button id="sxOpenServerToolsPanel" type="button">Ouvrir les outils</button>`;
    const overview = document.getElementById("sentrixSafeOverview");
    if (overview && overview.parentNode === host) overview.insertAdjacentElement("afterend", launcher);
    else host.insertBefore(launcher, host.firstChild);
    document.getElementById("sxOpenServerToolsPanel").addEventListener("click", () => {
      const overlay = ensureOverlay();
      if (overlay._sentrixOpen) overlay._sentrixOpen();
    });
    return launcher;
  }

  function relocateServerTools(){
    const root = document.getElementById("sentrixServerTools");
    const host = document.getElementById("serverContent");
    if (!root || !host) return;
    ensureLauncher(host);
    ensureOverlay();
    const body = document.getElementById("sxServerToolsModalBody");
    if (body && root.parentNode !== body) body.appendChild(root);
    root.style.margin = "0";
    root.dataset.sentrixCollapsedIntoModal = "1";
  }

  const observer = new MutationObserver(relocateServerTools);
  const startObserver = () => {
    observer.observe(document.documentElement, {childList:true, subtree:true});
    relocateServerTools();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startObserver, {once:true});
  else startObserver();
})();
</script>
"""


def install(dashboard_module: Any) -> None:
    """Range les outils serveur sans injecter de loader ni modifier le réseau."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    html = str(dashboard_module.INDEX_HTML or "")
    if 'id="sentrix-focus-loading-css"' not in html and "</head>" in html:
        html = html.replace("</head>", FOCUS_CSS + "\n</head>", 1)
    if 'id="sentrix-focus-loading-js"' not in html:
        if "</body>" in html:
            html = html.replace("</body>", FOCUS_JS + "\n</body>", 1)
        else:
            html += FOCUS_JS
    dashboard_module.INDEX_HTML = html
