"""Dernière barrière anti-loader bloquant pour le dashboard SentriX.

Les anciennes couches du dashboard peuvent encore injecter plusieurs écrans de chargement
plein écran. Même quand les API répondent correctement, un de ces overlays peut rester
visible si son contrôleur JavaScript n'atteint pas son chemin de fermeture. Cette couche est
installée au dernier boundary Railway et transforme ces loaders en éléments non bloquants.
"""
from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard-loader-hard-stop-v4")

MARKER = 'id="sentrix-loader-hard-stop-v4"'
BUILD = "loader-hard-stop-v4"

_HARD_STOP = r'''
<style id="sentrix-loader-hard-stop-v4">
  /* Aucun overlay historique ne doit pouvoir recouvrir le dashboard après le rendu HTML. */
  #sxLoadingExperience,
  #sxDirectLoader {
    display:none!important;
    opacity:0!important;
    visibility:hidden!important;
    pointer-events:none!important;
  }
</style>
<script id="sentrix-loader-hard-stop-v4-js">
(() => {
  "use strict";
  if (window.__sentrixLoaderHardStopV4) return;
  window.__sentrixLoaderHardStopV4 = true;

  const clearBlockingLoaders = () => {
    for (const id of ["sxLoadingExperience", "sxDirectLoader"]) {
      const node = document.getElementById(id);
      if (node) node.remove();
    }
    const content = document.getElementById("content");
    if (content) content.removeAttribute("aria-busy");
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", clearBlockingLoaders, {once:true});
  } else {
    clearBlockingLoaders();
  }

  // Filets de sécurité contre une couche tardive qui réinjecterait un loader.
  queueMicrotask(clearBlockingLoaders);
  setTimeout(clearBlockingLoaders, 500);
  setTimeout(clearBlockingLoaders, 3000);
})();
</script>
'''


def patch_html(html: str) -> str:
    """Ajoute le hard-stop une seule fois au document final."""
    html = str(html or "")
    if MARKER in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", _HARD_STOP + "\n</body>", 1)
    return html + _HARD_STOP


def install(dashboard) -> bool:
    """Patch aussi la réponse /app, après tous les anciens wrappers de rendu."""
    current = getattr(dashboard, "handle_index", None)
    if current is None:
        return False
    if getattr(current, "_sentrix_loader_hard_stop_v4", False):
        return True

    dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))

    async def hardened_index(request: web.Request):
        response = await current(request)
        if request.path != "/app" or not isinstance(response, web.Response) or response.status >= 300:
            return response

        source = response.text if isinstance(response.text, str) else str(
            getattr(dashboard, "INDEX_HTML", "") or ""
        )
        html = patch_html(source)
        headers = dict(response.headers)
        for key in ("Content-Type", "Content-Length"):
            headers.pop(key, None)
        headers["X-SentriX-Loader-Hard-Stop"] = BUILD
        return web.Response(
            text=html,
            status=response.status,
            content_type="text/html",
            headers=headers,
        )

    hardened_index._sentrix_loader_hard_stop_v4 = True
    hardened_index._sentrix_previous_handler = current
    dashboard.handle_index = hardened_index

    ok = MARKER in dashboard.INDEX_HTML
    logger.warning("Dashboard loader hard-stop V4 installed=%s.", ok)
    return ok


__all__ = ["install", "patch_html", "MARKER", "BUILD"]
