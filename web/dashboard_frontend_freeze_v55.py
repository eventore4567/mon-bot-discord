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

_UNIFIED_PRODUCT_UX = r'''
<script id="sentrix-unified-product-ux-v3">
(() => {
  "use strict";
  if (window.__sentrixUnifiedProductUxV3) return;
  window.__sentrixUnifiedProductUxV3 = true;

  const byId = id => document.getElementById(id);
  const activeInput = () => ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName || "");
  const hasUnsavedChanges = () => {
    const save = byId("saveButton");
    return Boolean(save && !save.classList.contains("hidden"));
  };
  const confirmNavigation = action => !hasUnsavedChanges() || window.confirm(
    `Tu as des modifications non enregistrées. ${action} les annulera. Continuer ?`
  );

  // Changer de serveur ou actualiser recharge les données et peut effacer le brouillon local.
  // On bloque donc l'action AVANT les handlers du dashboard tant que l'utilisateur n'a pas confirmé.
  document.addEventListener("click", event => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const guild = target.closest("[data-guild]");
    if (guild && !confirmNavigation("Changer de serveur")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    const refresh = target.closest("#refreshButton");
    if (refresh && !confirmNavigation("Actualiser les données")) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  // Les boutons de navigation exposent toujours la page active aux lecteurs d'écran,
  // même si renderNav() reconstruit complètement la sidebar.
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

  // Palette : flèches pour naviguer, Entrée pour ouvrir, sans sortir du champ de recherche.
  const paletteInput = byId("paletteInput");
  const paletteResults = byId("paletteResults");
  const paletteItems = () => [...document.querySelectorAll("#paletteResults [data-palette-tab]")];
  const selectPaletteItem = index => {
    const items = paletteItems();
    if (!items.length) return;
    const normalized = ((index % items.length) + items.length) % items.length;
    items.forEach((item, i) => item.classList.toggle("active", i === normalized));
    items[normalized].scrollIntoView?.({block:"nearest"});
  };
  if (paletteInput && paletteResults) {
    paletteInput.addEventListener("keydown", event => {
      const items = paletteItems();
      if (!items.length) return;
      const current = items.findIndex(item => item.classList.contains("active"));
      if (event.key === "ArrowDown") {
        event.preventDefault();
        selectPaletteItem(current < 0 ? 0 : current + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        selectPaletteItem(current < 0 ? items.length - 1 : current - 1);
      } else if (event.key === "Enter" && current >= 0) {
        event.preventDefault();
        items[current].click();
      }
    });
    new MutationObserver(() => {
      const items = paletteItems();
      if (items.length && !items.some(item => item.classList.contains("active"))) selectPaletteItem(0);
    }).observe(paletteResults, {childList:true, subtree:true});
  }

  // Raccourci rapide : / ouvre directement la recherche globale quand on n'écrit pas déjà.
  document.addEventListener("keydown", event => {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey || activeInput()) return;
    const search = byId("globalSearch");
    if (!search) return;
    event.preventDefault();
    search.focus();
    search.select?.();
  });

  // État réseau visible immédiatement. Le dashboard garde la main sur le vrai statut Discord.
  window.addEventListener("offline", () => {
    byId("runtimeDot")?.classList.add("off");
    const text = byId("runtimeText");
    if (text) text.textContent = "Hors ligne";
  });
  window.addEventListener("online", () => {
    const text = byId("runtimeText");
    if (text) text.textContent = "Reconnexion…";
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

    # Le backend sanctions expose explicitement ``clear-warnings``.
    html = html.replace(
        "action==='warn'?'clearwarnings':",
        "action==='warn'?'clear-warnings':",
    )

    # Le recovery legacy de sentrix_product_update ne doit pas se réinjecter par-dessus
    # unified-v2. Le nouveau frontend possède déjà ses états erreur/retry.
    if _PRODUCT_RECOVERY_MARKER not in html and "</body>" in html:
        html = html.replace(
            "</body>",
            '<script id="sentrix-product-dashboard-recovery">/* unified-v2 owns recovery */</script>\n</body>',
            1,
        )
    return html


def _enhance_unified_product_ux(html: str) -> str:
    """Ajoute une couche UX finale, idempotente et indépendante des APIs produit."""
    html = str(html or "")
    if _UNIFIED_MARKER not in html or _UNIFIED_PRODUCT_UX_MARKER in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", _UNIFIED_PRODUCT_UX + "\n</body>", 1)
    return html + _UNIFIED_PRODUCT_UX


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

    # Les routes DM partagent exactement le moteur de +dmall. L'ancienne injection HTML est
    # remplacée ensuite par le frontend unifié, mais le backend et son verrou restent uniques.
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

        # Les tests unitaires du gel utilisent volontairement un objet minimal : dans ce cas
        # on vérifie uniquement l'immuabilité du snapshot et on ne fabrique pas une app aiohttp.
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
