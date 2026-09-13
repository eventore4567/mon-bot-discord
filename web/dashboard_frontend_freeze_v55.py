"""Gel final du dashboard SentriX.

Le backend historique conserve ses routes/API, mais ``/app`` est désormais servi depuis une
seule source frontend : :mod:`web.dashboard_unified_v2`. Les anciennes couches V60 -> V64
ne sont plus empilées pour fabriquer l'interface finale.
"""
from __future__ import annotations

import hashlib
import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard-frontend-v55")

_REQUIRED_MARKERS = (
    'async function loadSession()',
    'async function loadGuilds()',
    'async function selectGuild(value)',
)
_REQUIRED_ENDPOINTS = ("/api/me", "/api/guilds")
_UNIFIED_MARKER = 'id="sentrix-dashboard-unified-v2"'
_PRODUCT_RECOVERY_MARKER = 'id="sentrix-product-dashboard-recovery"'
_UNIFIED_PRODUCT_UX_MARKER = 'id="sentrix-unified-product-ux-v3"'
_LOADING_UX_CSS_MARKER = 'id="sentrix-loading-experience-css"'
_LOADING_UX_HTML_MARKER = 'id="sxLoadingExperience"'

_LOADING_UX_CSS = r'''
<style id="sentrix-loading-experience-css">
  #sxLoadingExperience{
    position:fixed;inset:0;z-index:190;display:flex;align-items:center;justify-content:center;
    padding:24px;background:rgba(9,11,14,.94);backdrop-filter:blur(16px) saturate(115%);
    opacity:1;visibility:visible;transition:opacity .22s ease,visibility .22s ease,background .22s ease;
  }
  #sxLoadingExperience[data-mode="guild"]{inset:64px 0 0 330px;background:rgba(11,13,16,.86)}
  #sxLoadingExperience.sx-load-hidden{opacity:0;visibility:hidden;pointer-events:none}
  .sx-load-card{width:min(540px,100%);border:1px solid #2d3743;border-radius:18px;background:linear-gradient(180deg,#171c23,#101419);box-shadow:0 28px 90px rgba(0,0,0,.48);padding:28px}
  .sx-load-brand{display:flex;align-items:center;gap:15px}.sx-load-mark{position:relative;width:58px;height:58px;flex:0 0 58px;display:grid;place-items:center}
  .sx-load-mark:before,.sx-load-mark:after{content:"";position:absolute;border-radius:18px;border:1px solid rgba(77,163,255,.38);inset:0;animation:sxLoadOrbit 2s cubic-bezier(.55,.1,.35,.9) infinite}
  .sx-load-mark:after{inset:7px;border-color:rgba(119,188,255,.55);animation-direction:reverse;animation-duration:1.45s}
  .sx-load-core{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:linear-gradient(145deg,#58adff,#286db4);color:#fff;font-weight:950;font-size:17px;box-shadow:0 10px 34px rgba(40,109,180,.34)}
  .sx-load-copy{min-width:0}.sx-load-kicker{color:#77bcff;font-size:9px;font-weight:900;letter-spacing:.12em;text-transform:uppercase}.sx-load-title{margin-top:3px;font-size:21px;line-height:1.2;font-weight:900;letter-spacing:-.035em}.sx-load-sub{margin-top:5px;color:#929dac;font-size:12px;line-height:1.5}
  .sx-load-rail{height:3px;margin:22px 0 18px;border-radius:999px;background:#242b34;overflow:hidden}.sx-load-rail>i{display:block;width:38%;height:100%;border-radius:inherit;background:linear-gradient(90deg,transparent,#4da3ff,#9ed1ff,#4da3ff,transparent);animation:sxLoadRail 1.35s ease-in-out infinite}
  .sx-load-steps{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}.sx-load-step{min-width:0;border:1px solid #29323d;border-radius:9px;background:#12171d;padding:8px 9px;color:#697687;transition:border-color .18s ease,background .18s ease,color .18s ease}
  .sx-load-step b{display:flex;align-items:center;gap:6px;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sx-load-step b:before{content:"";width:6px;height:6px;border-radius:50%;background:#45515f;flex:0 0 auto}.sx-load-step span{display:block;margin-top:2px;font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .sx-load-step.active{border-color:#376d9e;background:#122438;color:#cfe8ff}.sx-load-step.active b:before{background:#6bb8ff;box-shadow:0 0 12px rgba(77,163,255,.7);animation:sxLoadPulse 1.2s ease-in-out infinite}.sx-load-step.done{border-color:#2d5443;background:#12231c;color:#9bdab9}.sx-load-step.done b:before{background:#55d69a;box-shadow:none}
  .sx-load-footer{min-height:38px;margin-top:16px;display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid #252d36;padding-top:14px}.sx-load-note{color:#758293;font-size:10px}.sx-load-note.warn{color:#efbd61}.sx-load-note.bad{color:#ff9daa}.sx-load-retry{min-height:34px;border:1px solid #3f78ab;border-radius:8px;background:#18324a;color:#d8edff;padding:0 12px;font-weight:850;font-size:10px;cursor:pointer}.sx-load-retry:hover{background:#20405e;border-color:#5ca8eb}.sx-load-retry.hidden{display:none!important}
  .loading-screen{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:12px;padding:8px 0!important}.loading-screen .loading-block{grid-column:span 6;height:118px!important;margin:0!important;border:1px solid #252e39;border-radius:12px!important;position:relative;overflow:hidden}.loading-screen .loading-block:first-child{grid-column:1/-1;height:82px!important}.loading-screen .loading-block:after{content:"";position:absolute;left:14px;top:16px;width:42%;height:10px;border-radius:7px;background:#303946;box-shadow:0 22px 0 #272f39,0 44px 0 #222932}
  @keyframes sxLoadOrbit{0%{transform:rotate(0deg) scale(.94)}50%{transform:rotate(180deg) scale(1.03)}100%{transform:rotate(360deg) scale(.94)}}
  @keyframes sxLoadRail{0%{transform:translateX(-135%)}100%{transform:translateX(365%)}}
  @keyframes sxLoadPulse{50%{opacity:.45;transform:scale(.78)}}
  @media(max-width:840px){#sxLoadingExperience[data-mode="guild"]{inset:64px 0 0 56px}.sx-load-card{padding:22px}.sx-load-steps{grid-template-columns:repeat(2,minmax(0,1fr))}.loading-screen .loading-block{grid-column:1/-1}}
  @media(max-width:560px){#sxLoadingExperience{padding:12px}#sxLoadingExperience[data-mode="guild"]{inset:64px 0 0 52px}.sx-load-card{padding:18px;border-radius:14px}.sx-load-brand{align-items:flex-start}.sx-load-mark{width:48px;height:48px;flex-basis:48px}.sx-load-title{font-size:18px}.sx-load-steps{grid-template-columns:1fr 1fr}.sx-load-footer{align-items:flex-start;flex-direction:column}.sx-load-retry{width:100%}}
  @media(prefers-reduced-motion:reduce){#sxLoadingExperience,.sx-load-step{transition:none!important}.sx-load-mark:before,.sx-load-mark:after,.sx-load-rail>i,.sx-load-step.active b:before{animation:none!important}.sx-load-rail>i{width:100%;opacity:.75}}
</style>
'''

_LOADING_UX_HTML = r'''
<div id="sxLoadingExperience" data-mode="boot" role="status" aria-live="polite" aria-atomic="true">
  <div class="sx-load-card">
    <div class="sx-load-brand">
      <div class="sx-load-mark" aria-hidden="true"><div class="sx-load-core">S</div></div>
      <div class="sx-load-copy">
        <div class="sx-load-kicker">SentriX Control Center</div>
        <div class="sx-load-title" id="sxLoadTitle">Vérification de ta session</div>
        <div class="sx-load-sub" id="sxLoadSub">On prépare ton espace sans masquer les erreurs si quelque chose bloque.</div>
      </div>
    </div>
    <div class="sx-load-rail" aria-hidden="true"><i></i></div>
    <div class="sx-load-steps" aria-hidden="true">
      <div class="sx-load-step active" data-sx-step="session"><b>Session</b><span>Compte Discord</span></div>
      <div class="sx-load-step" data-sx-step="discord"><b>Discord</b><span>État SentriX</span></div>
      <div class="sx-load-step" data-sx-step="guilds"><b>Serveurs</b><span>Accès administrateur</span></div>
      <div class="sx-load-step" data-sx-step="guild"><b>Configuration</b><span>Données du serveur</span></div>
    </div>
    <div class="sx-load-footer">
      <div class="sx-load-note" id="sxLoadNote">Connexion sécurisée en cours…</div>
      <button type="button" class="sx-load-retry hidden" id="sxLoadRetry">Réessayer</button>
    </div>
  </div>
</div>
'''

_UNIFIED_PRODUCT_UX = r'''
<script id="sentrix-unified-product-ux-v3">
(() => {
  "use strict";
  if (window.__sentrixUnifiedProductUxV3) return;
  window.__sentrixUnifiedProductUxV3 = true;

  const byId = id => document.getElementById(id);
  const LONG_WAIT_MS = 3500;
  const RETRY_WAIT_MS = 8000;
  const HARD_TIMEOUT_MS = 20000;
  const stepOrder = ["session", "discord", "guilds", "guild"];
  const loader = byId("sxLoadingExperience");
  const loadTitle = byId("sxLoadTitle");
  const loadSub = byId("sxLoadSub");
  const loadNote = byId("sxLoadNote");
  const loadRetry = byId("sxLoadRetry");
  const originalFetch = window.fetch.bind(window);
  let activeKind = "session";
  let longTimer = null;
  let retryTimer = null;
  let pendingCritical = 0;

  const copy = {
    session:["Vérification de ta session","On confirme ton compte et les permissions du dashboard."],
    discord:["Synchronisation avec Discord","SentriX vérifie quelle instance Discord est active."],
    guilds:["Chargement de tes serveurs","On récupère uniquement les serveurs que tu peux administrer."],
    guild:["Préparation du serveur","Configuration, rôles, salons et modules arrivent maintenant."],
  };
  const activeInput = () => ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName || "");
  const clearLoadTimers = () => {clearTimeout(longTimer);clearTimeout(retryTimer);longTimer=retryTimer=null;};
  const setBusy = busy => {const content=byId("content");if(content)content.setAttribute("aria-busy",busy?"true":"false")};
  const setSteps = kind => {
    const index = stepOrder.indexOf(kind);
    document.querySelectorAll("[data-sx-step]").forEach(node => {
      const i = stepOrder.indexOf(node.dataset.sxStep);
      node.classList.toggle("done",i >= 0 && i < index);
      node.classList.toggle("active",i === index);
    });
  };
  const setLoadCopy = (kind, note="Connexion sécurisée en cours…") => {
    activeKind = kind;
    const values = copy[kind] || copy.guild;
    if(loadTitle)loadTitle.textContent=values[0];
    if(loadSub)loadSub.textContent=values[1];
    if(loadNote){loadNote.textContent=note;loadNote.className="sx-load-note"}
    setSteps(kind);
  };
  const armWaitStates = () => {
    clearLoadTimers();
    if(loadRetry)loadRetry.classList.add("hidden");
    longTimer=setTimeout(()=>{
      if(!loader || loader.classList.contains("sx-load-hidden"))return;
      if(loadNote){loadNote.textContent="Ça prend plus longtemps que prévu, mais SentriX répond encore…";loadNote.className="sx-load-note warn"}
    },LONG_WAIT_MS);
    retryTimer=setTimeout(()=>{
      if(!loader || loader.classList.contains("sx-load-hidden"))return;
      if(loadNote){loadNote.textContent="Le chargement est anormalement long. Tu peux relancer proprement.";loadNote.className="sx-load-note warn"}
      loadRetry?.classList.remove("hidden");
    },RETRY_WAIT_MS);
  };
  const showLoader = (kind,mode="boot") => {
    if(!loader)return;
    loader.dataset.mode=mode;
    loader.classList.remove("sx-load-hidden");
    setBusy(mode==="guild");
    setLoadCopy(kind);
    armWaitStates();
  };
  const hideLoader = () => {
    if(!loader)return;
    clearLoadTimers();
    pendingCritical=0;
    setBusy(false);
    document.querySelectorAll("[data-sx-step]").forEach(node=>{node.classList.remove("active");node.classList.add("done")});
    setTimeout(()=>loader.classList.add("sx-load-hidden"),120);
  };
  const failLoader = (message,detail="Réessaie quand tu veux. Aucune modification n’a été perdue.") => {
    if(!loader)return;
    clearLoadTimers();
    loader.classList.remove("sx-load-hidden");
    if(loadTitle)loadTitle.textContent=message;
    if(loadSub)loadSub.textContent=detail;
    if(loadNote){loadNote.textContent=navigator.onLine?"Le dashboard a arrêté d’attendre au lieu de tourner en boucle.":"Hors ligne — vérifie ta connexion Internet.";loadNote.className="sx-load-note bad"}
    loadRetry?.classList.remove("hidden");
  };
  const classifyRequest = input => {
    let path="";
    try{path=new URL(typeof input==="string"?input:input?.url||"",location.origin).pathname}catch(_){return null}
    if(path==="/api/me")return "session";
    if(path==="/api/public")return "discord";
    if(path==="/api/guilds")return "guilds";
    if(/^\/api\/guilds\/[^/]+$/.test(path))return "guild";
    return null;
  };
  const critical = kind => kind==="session"||kind==="guilds"||kind==="guild";

  if(loadRetry)loadRetry.addEventListener("click",()=>location.reload());
  showLoader("session","boot");

  window.fetch = async function sentrixLoadingFetch(input, options={}){
    const kind=classifyRequest(input);
    const isCritical=critical(kind);
    if(kind){
      if(isCritical)pendingCritical+=1;
      const dashboardVisible=!byId("dashboard")?.classList.contains("hidden");
      const mode=kind==="guild"&&dashboardVisible?"guild":"boot";
      if(isCritical)showLoader(kind,mode);else if(activeKind==="session")setLoadCopy("discord");
    }
    const externalSignal=options?.signal;
    const controller=!externalSignal&&kind?new AbortController():null;
    const timeout=controller?setTimeout(()=>controller.abort(),HARD_TIMEOUT_MS):null;
    try{
      const response=await originalFetch(input,controller?{...options,signal:controller.signal}:options);
      if(kind==="session"&&response.status===401){hideLoader();return response}
      if(kind&&response.ok){
        if(kind==="session")setLoadCopy("discord","Session prête. Synchronisation Discord…");
        if(kind==="discord"&&activeKind==="discord")setLoadCopy("guilds","Discord prêt. Recherche de tes serveurs…");
        if(kind==="guilds"){
          setLoadCopy("guild","Serveurs trouvés. Préparation de la configuration…");
          try{
            const payload=await response.clone().json();
            if(!(payload.guilds||[]).some(g=>g.installed))setTimeout(hideLoader,140);
          }catch(_){}
        }
        if(kind==="guild")setTimeout(hideLoader,150);
      }else if(isCritical&&response.status>=400){
        if(response.status===503)failLoader("Bascule SentriX en cours","L’instance Discord active change. Attends quelques secondes puis réessaie.");
        else failLoader("Impossible de terminer le chargement",`Le serveur a répondu avec l’erreur ${response.status}.`);
      }
      return response;
    }catch(error){
      if(isCritical){
        if(error?.name==="AbortError")failLoader("Le chargement prend trop de temps","SentriX a arrêté cette tentative après 20 secondes pour éviter un spinner infini.");
        else if(!navigator.onLine)failLoader("Hors ligne","La connexion Internet a été interrompue. Tes réglages locaux restent intacts.");
        else failLoader("Connexion interrompue",error?.message||"Impossible de joindre SentriX.");
      }
      throw error;
    }finally{
      if(timeout)clearTimeout(timeout);
      if(isCritical)pendingCritical=Math.max(0,pendingCritical-1);
    }
  };

  window.addEventListener("offline",()=>{
    byId("runtimeDot")?.classList.add("off");
    const text=byId("runtimeText");if(text)text.textContent="Hors ligne";
    if(loader&&!loader.classList.contains("sx-load-hidden"))failLoader("Hors ligne","SentriX reprendra dès que ta connexion sera revenue.");
  });
  window.addEventListener("online",()=>{
    const text=byId("runtimeText");if(text)text.textContent="Reconnexion…";
    if(loader&&!loader.classList.contains("sx-load-hidden")){
      setLoadCopy(activeKind,"Connexion retrouvée. Tu peux réessayer maintenant.");
      loadRetry?.classList.remove("hidden");
    }
  });

  const hasUnsavedChanges = () => {
    const save = byId("saveButton");
    return Boolean(save && !save.classList.contains("hidden"));
  };
  const confirmNavigation = action => !hasUnsavedChanges() || window.confirm(
    `Tu as des modifications non enregistrées. ${action} les annulera. Continuer ?`
  );

  document.addEventListener("click", event => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const guild = target.closest("[data-guild]");
    if (guild && !confirmNavigation("Changer de serveur")) {
      event.preventDefault();event.stopImmediatePropagation();return;
    }
    const refresh = target.closest("#refreshButton");
    if (refresh && !confirmNavigation("Actualiser les données")) {
      event.preventDefault();event.stopImmediatePropagation();
    }
  }, true);

  const syncNavigationA11y = () => {
    document.querySelectorAll("#navigation [data-tab]").forEach(button => {
      if (button.classList.contains("active")) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
      if (!button.title) button.title = button.textContent?.trim() || "Ouvrir";
    });
  };
  const navigation = byId("navigation");
  if (navigation) {
    new MutationObserver(syncNavigationA11y).observe(navigation, {childList:true, subtree:true});
    syncNavigationA11y();
  }

  const paletteInput = byId("paletteInput");
  const paletteResults = byId("paletteResults");
  const paletteItems = () => [...document.querySelectorAll("#paletteResults [data-palette-tab]")];
  const selectPaletteItem = index => {
    const items = paletteItems();if (!items.length) return;
    const normalized = ((index % items.length) + items.length) % items.length;
    items.forEach((item, i) => item.classList.toggle("active", i === normalized));
    items[normalized].scrollIntoView?.({block:"nearest"});
  };
  if (paletteInput && paletteResults) {
    paletteInput.addEventListener("keydown", event => {
      const items = paletteItems();if (!items.length) return;
      const current = items.findIndex(item => item.classList.contains("active"));
      if (event.key === "ArrowDown") {event.preventDefault();selectPaletteItem(current < 0 ? 0 : current + 1)}
      else if (event.key === "ArrowUp") {event.preventDefault();selectPaletteItem(current < 0 ? items.length - 1 : current - 1)}
      else if (event.key === "Enter" && current >= 0) {event.preventDefault();items[current].click()}
    });
    new MutationObserver(() => {
      const items = paletteItems();
      if (items.length && !items.some(item => item.classList.contains("active"))) selectPaletteItem(0);
    }).observe(paletteResults, {childList:true, subtree:true});
  }

  document.addEventListener("keydown", event => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey || activeInput()) return;
    const search = byId("globalSearch");if (!search) return;
    event.preventDefault();search.focus();search.select?.();
  });
})();
</script>
'''


def _snapshot_is_usable(html: str) -> tuple[bool, list[str]]:
    """Validate the authenticated boot chain without depending on one fetch helper syntax."""
    missing = [marker for marker in _REQUIRED_MARKERS if marker not in html]
    missing.extend(endpoint for endpoint in _REQUIRED_ENDPOINTS if endpoint not in html)
    return not missing, missing


def _ensure_v60_features_final(dashboard) -> bool:
    """Compatibilité avec les anciens gates : l'UI héritée ne doit plus être rendue."""
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if _UNIFIED_MARKER in html:
        return True
    try:
        from .dashboard_v61_postfix import _legacy_feature_ui_present
        return not _legacy_feature_ui_present(html)
    except Exception:
        return 'id="sentrix-v60-features-inline"' not in html and 'id="sxFeaturesFrame"' not in html


def _theme_secondary_pages_final() -> bool:
    return True


def _is_unified_document(dashboard, html: str) -> bool:
    version = str(getattr(dashboard, "_sentrix_dashboard_version", "") or "")
    return version.startswith("unified-v2") or _UNIFIED_MARKER in html


def _finalize_unified_html(html: str) -> str:
    """Applique les contrats nécessaires au document unique avant de le figer."""
    if _UNIFIED_MARKER not in html:
        return html

    html = html.replace(
        "action==='warn'?'clearwarnings':",
        "action==='warn'?'clear-warnings':",
    )

    if _PRODUCT_RECOVERY_MARKER not in html and "</body>" in html:
        html = html.replace(
            "</body>",
            '<script id="sentrix-product-dashboard-recovery">/* unified-v2 owns recovery */</script>\n</body>',
            1,
        )
    return html


def _enhance_unified_product_ux(html: str) -> str:
    """Ajoute la couche UX finale et le chargement premium, sans modifier les APIs produit."""
    html = str(html or "")
    if _UNIFIED_MARKER not in html:
        return html
    if _LOADING_UX_CSS_MARKER not in html and "</head>" in html:
        html = html.replace("</head>", _LOADING_UX_CSS + "\n</head>", 1)
    if _LOADING_UX_HTML_MARKER not in html:
        if "<body>" in html:
            html = html.replace("<body>", "<body>\n" + _LOADING_UX_HTML, 1)
        elif "</body>" in html:
            html = html.replace("</body>", _LOADING_UX_HTML + "\n</body>", 1)
    if _UNIFIED_PRODUCT_UX_MARKER not in html:
        if "</body>" in html:
            html = html.replace("</body>", _UNIFIED_PRODUCT_UX + "\n</body>", 1)
        else:
            html += _UNIFIED_PRODUCT_UX
    return html


def install(dashboard) -> bool:
    current = dashboard.handle_index
    if getattr(current, "_sentrix_frontend_freeze_v55", False):
        return True

    snapshot = str(getattr(dashboard, "INDEX_HTML", "") or "")
    usable, missing = _snapshot_is_usable(snapshot)
    if not usable:
        logger.error("Dashboard frontend non figé : marqueurs runtime absents=%s.", missing)
        return False

    if _is_unified_document(dashboard, snapshot):
        if _UNIFIED_MARKER not in snapshot:
            logger.error("Dashboard unifié non figé : marqueur principal absent.")
            return False
        if _PRODUCT_RECOVERY_MARKER not in snapshot:
            logger.error("Dashboard unifié non figé : contrat recovery produit absent.")
            return False
        forbidden = (
            'id="sentrix-v60-features-inline"',
            'id="sxFeaturesFrame"',
        )
        present = [marker for marker in forbidden if marker in snapshot]
        if present:
            logger.error("Dashboard unifié non figé : ancienne UI encore présente=%s.", present)
            return False
    else:
        version = str(getattr(dashboard, "_sentrix_dashboard_version", "") or "")
        if version.startswith("v64") and 'id="sentrix-v64-final"' not in snapshot:
            logger.error("Dashboard V64 non figé : verrou de navigation absent.")
            return False

    digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]
    version = str(getattr(dashboard, "_sentrix_dashboard_version", "v55") or "v55")

    async def frozen_handle_index(request: web.Request):
        if request.path == "/app":
            response = web.Response(text=snapshot, content_type="text/html")
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["X-SentriX-Dashboard"] = f"{version}-frozen"
            response.headers["X-SentriX-Frontend-SHA"] = digest
            return response
        return await current(request)

    frozen_handle_index._sentrix_frontend_freeze_v55 = True
    frozen_handle_index._sentrix_original = current
    frozen_handle_index._sentrix_snapshot_sha = digest
    dashboard.handle_index = frozen_handle_index
    dashboard._sentrix_frontend_snapshot_v55 = snapshot
    dashboard._sentrix_frontend_snapshot_sha_v55 = digest
    logger.info("Dashboard %s figé : %s octets, sha256=%s.", version, len(snapshot.encode("utf-8")), digest)
    return True


def _install_backend_compatibility(dashboard) -> None:
    """Branche uniquement les APIs historiques encore utilisées par unified-v2."""
    try:
        from .dashboard_v60_diagnostics import install as install_diagnostics
        install_diagnostics(dashboard)
    except Exception:
        logger.exception("Dashboard unifié : API diagnostics impossible à installer.")

    try:
        from . import dashboard_v62_dense
        dashboard_v62_dense._install_backend(dashboard)
    except Exception:
        logger.exception("Dashboard unifié : API Tickets/Vérification V62 impossible à installer.")

    try:
        from .dm_panel import installer as install_dm_panel
        install_dm_panel(dashboard)
    except Exception:
        logger.exception("Dashboard unifié : API Messages privés impossible à installer.")


def _install_unified_document(dashboard) -> bool:
    """Pose le document unifié puis ses contrats runtime sans empiler les anciennes UIs."""
    try:
        from .dashboard_unified_v2 import INDEX_HTML
        from .dashboard_unified_runtime_v2 import enhance_html
    except Exception:
        logger.exception("Dashboard unifié V2 : source frontend impossible à importer.")
        return False

    html = enhance_html(_finalize_unified_html(str(INDEX_HTML or "")))
    html = _enhance_unified_product_ux(html)
    usable, missing = _snapshot_is_usable(html)
    if _UNIFIED_MARKER not in html or not usable:
        logger.error("Dashboard unifié V2 incomplet : marqueurs absents=%s.", missing)
        return False

    dashboard.INDEX_HTML = html
    dashboard._sentrix_dashboard_version = "unified-v2"
    return True


def install_product_prestart_hook() -> bool:
    """Branche le frontend unifié au véritable pré-démarrage produit Railway."""
    try:
        import sentrix_product_update as product
    except Exception:
        logger.exception("Dashboard freeze : sentrix_product_update indisponible.")
        return False

    current = product._install_no_store_index
    if getattr(current, "_sentrix_frontend_freeze_hook_v55", False):
        return True

    def no_store_then_freeze(dashboard) -> None:
        current(dashboard)

        if not hasattr(dashboard, "build_app"):
            if not install(dashboard):
                logger.error("Dashboard frontend : gel du snapshot minimal échoué.")
            return

        _install_backend_compatibility(dashboard)
        if not _install_unified_document(dashboard):
            logger.error("Dashboard unifié V2 absent : le gel final est refusé.")
            return

        if not install(dashboard):
            logger.error("Dashboard frontend : gel final échoué.")

    no_store_then_freeze._sentrix_frontend_freeze_hook_v55 = True
    no_store_then_freeze._sentrix_original = current
    product._install_no_store_index = no_store_then_freeze
    logger.info("Dashboard unifié V2 armé : APIs historiques conservées, frontend unique + gel immuable.")
    return True


__all__ = [
    "install",
    "install_product_prestart_hook",
    "_snapshot_is_usable",
    "_ensure_v60_features_final",
    "_theme_secondary_pages_final",
    "_finalize_unified_html",
    "_enhance_unified_product_ux",
    "_install_unified_document",
]
