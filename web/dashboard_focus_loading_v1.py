"""Affinage UX du dashboard SentriX.

- masque le gros panneau Outils serveur de la vue principale et le deplace dans une
  fenetre dediee ouverte par un bouton compact ;
- affiche un vrai ecran de chargement SentriX meme lors d'un acces direct a /app.

Le module est purement visuel : aucune route, permission ou action serveur n'est modifiee.
"""
from __future__ import annotations

from typing import Any

_INSTALLED = False


FOCUS_CSS = r"""
<style id="sentrix-focus-loading-css">
  #sxDirectLoader{
    position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;
    background:
      radial-gradient(circle at 50% 35%,rgba(124,108,255,.18),transparent 32%),
      radial-gradient(circle at 50% 110%,rgba(87,70,210,.15),transparent 38%),
      #090b12;
    opacity:1;visibility:visible;transition:opacity .38s ease,visibility .38s ease;
  }
  #sxDirectLoader.sx-loader-hide{opacity:0;visibility:hidden;pointer-events:none}
  .sx-loader-card{width:min(390px,calc(100vw - 42px));text-align:center;padding:34px 28px}
  .sx-loader-mark{width:78px;height:78px;margin:0 auto 20px;position:relative;display:grid;place-items:center}
  .sx-loader-mark::before,.sx-loader-mark::after{content:"";position:absolute;inset:0;border-radius:24px;border:1px solid rgba(157,143,255,.28)}
  .sx-loader-mark::before{animation:sxLoaderOrbit 1.7s cubic-bezier(.55,.08,.35,.95) infinite}
  .sx-loader-mark::after{inset:9px;border-color:rgba(124,108,255,.52);animation:sxLoaderOrbitReverse 1.25s linear infinite}
  .sx-loader-core{width:46px;height:46px;border-radius:15px;display:grid;place-items:center;background:linear-gradient(145deg,#8d7dff,#5444c8);box-shadow:0 12px 40px rgba(92,73,218,.35);font-size:22px;font-weight:900;letter-spacing:-.05em;color:white}
  .sx-loader-title{font-size:28px;font-weight:900;letter-spacing:-.045em;color:#f3f5ff}
  .sx-loader-sub{margin-top:7px;color:#939bb0;font-size:13px}
  .sx-loader-bar{height:5px;margin:22px auto 0;max-width:230px;border-radius:99px;background:#1a2030;overflow:hidden;border:1px solid rgba(255,255,255,.035)}
  .sx-loader-bar i{display:block;height:100%;width:42%;border-radius:inherit;background:linear-gradient(90deg,#6655da,#9b8cff,#6655da);animation:sxLoaderBar 1.15s ease-in-out infinite}
  @keyframes sxLoaderOrbit{0%{transform:rotate(0) scale(.92)}50%{transform:rotate(180deg) scale(1.04)}100%{transform:rotate(360deg) scale(.92)}}
  @keyframes sxLoaderOrbitReverse{to{transform:rotate(-360deg)}}
  @keyframes sxLoaderBar{0%{transform:translateX(-125%)}100%{transform:translateX(240%)}}

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
  @media(prefers-reduced-motion:reduce){#sxDirectLoader *,#sxServerToolsLauncher,.sx-tools-modal-shell{animation:none!important;transition:none!important}}
</style>
"""


LOADER_HTML = r"""
<div id="sxDirectLoader" aria-live="polite" aria-label="Chargement de SentriX">
  <div class="sx-loader-card">
    <div class="sx-loader-mark"><div class="sx-loader-core">S</div></div>
    <div class="sx-loader-title">SentriX</div>
    <div class="sx-loader-sub">Préparation de votre dashboard</div>
    <div class="sx-loader-bar"><i></i></div>
  </div>
</div>
"""


FOCUS_JS = r"""
<script id="sentrix-focus-loading-js">
(() => {
  "use strict";
  if (window.__sentrixFocusLoadingV1) return;
  window.__sentrixFocusLoadingV1 = true;

  const bootStarted = performance.now();
  let loaderHidden = false;

  function hideLoader(){
    if (loaderHidden) return;
    loaderHidden = true;
    const loader = document.getElementById("sxDirectLoader");
    if (!loader) return;
    const elapsed = performance.now() - bootStarted;
    const wait = Math.max(0, 720 - elapsed);
    setTimeout(() => {
      loader.classList.add("sx-loader-hide");
      setTimeout(() => loader.remove(), 480);
    }, wait);
  }

  if (document.readyState === "complete") hideLoader();
  else window.addEventListener("load", () => setTimeout(hideLoader, 90), {once:true});
  // Le loader ne doit jamais pouvoir bloquer l'interface si une ressource secondaire traine.
  setTimeout(hideLoader, 3600);

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
          <div><h2 id="sxServerToolsModalTitle">Outils serveur</h2><p>Configuration, création de structure et maintenance du serveur.</p></div>
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
    const overlay = ensureOverlay();
    const body = document.getElementById("sxServerToolsModalBody");
    if (body && root.parentNode !== body) body.appendChild(root);

    // L'ancien panneau ne doit plus reprendre de place dans la page principale.
    root.style.margin = "0";
    root.dataset.sentrixCollapsedIntoModal = "1";
  }

  const observer = new MutationObserver(() => relocateServerTools());
  const startObserver = () => {
    observer.observe(document.documentElement, {childList:true, subtree:true});
    relocateServerTools();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startObserver, {once:true});
  else startObserver();

  // Filet de sécurité pour les modules qui construisent leur UI après un appel API tardif.
  const lateTimer = setInterval(relocateServerTools, 900);
  setTimeout(() => clearInterval(lateTimer), 30000);
})();
</script>
"""


def install(dashboard_module: Any) -> None:
    """Injecte les deux raffinements dans la page /app sans toucher au backend."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    html = dashboard_module.INDEX_HTML
    if 'id="sentrix-focus-loading-css"' not in html:
        html = html.replace("</head>", FOCUS_CSS + "\n</head>", 1)
    if 'id="sxDirectLoader"' not in html:
        if "<body>" in html:
            html = html.replace("<body>", "<body>\n" + LOADER_HTML, 1)
        else:
            # Fallback : le script cree quand meme l'interface, mais on prefere l'injection
            # immediate ci-dessus pour eviter tout flash de contenu lors d'un acces direct.
            html = html.replace("</body>", LOADER_HTML + "\n</body>", 1)
    if 'id="sentrix-focus-loading-js"' not in html:
        html = html.replace("</body>", FOCUS_JS + "\n</body>", 1)
    dashboard_module.INDEX_HTML = html
