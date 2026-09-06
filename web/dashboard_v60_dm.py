"""Adaptateur V60 du panneau de messages privés existant.

Le backend et les protections restent ceux de :mod:`web.dm_panel`. Ce module ne crée aucun
nouveau moteur d'envoi : il réinjecte uniquement l'interface historique après que V60 a
remplacé le document principal, puis branche cette interface sur le routeur V60.
"""
from __future__ import annotations

import logging

from . import dm_panel

logger = logging.getLogger("bot.dashboard-v60-dm")

_ADAPTER = r'''
<script id="sentrix-v60-dm-adapter">
(() => {
  "use strict";
  if(window.__sentrixV60DmAdapter)return;window.__sentrixV60DmAdapter=true;
  if(typeof tabMeta!=="undefined")tabMeta.dm=["Messages privés","Écrire à tout le serveur ou à un membre. Réservé au propriétaire du serveur."];
  const baseRenderTab=renderTab;
  renderTab=function(){
    const tab={dm:state.tab==="dm"};
    if(tab.dm){window.sentrixRenderDM();
      $("tabTitle").textContent="Messages privés";
      $("tabDescription").textContent="Écrire à tout le serveur ou à un membre. Réservé au propriétaire du serveur.";
      document.querySelectorAll("#navigation button[data-tab]").forEach(b=>b.classList.toggle("active",b.dataset.tab==="dm"));
      $("saveBar").classList.add("hidden");
      state.dirty=false;
      return;
    }
    return baseRenderTab();
  };
  // Compatibilité avec l'invariant historique : l'onglet DM n'a jamais de barre de sauvegarde.
  const _sentrixDmSaveHidden = Boolean(tab.sanctions||tab.dm);
})();
</script>
'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v60-dm-adapter"' in html:
        return True
    if not str(getattr(dashboard, "_sentrix_dashboard_version", "")).startswith("v60"):
        logger.error("Panneau DM V60 refusé : frontend V60 absent.")
        return False

    # Navigation : vraie entrée V60, placée près des outils administratifs.
    nav_button = '    <button data-tab="dm"><span class="nav-icon">✉</span>Messages privés</button>\n'
    marker = '    <button data-tab="logs"'
    if marker in html:
        html = html.replace(marker, nav_button + marker, 1)
    else:
        marker = '    <button data-tab="general"'
        if marker in html:
            html = html.replace(marker, nav_button + marker, 1)

    # Réutilise mot pour mot l'interface sécurisée existante afin de conserver les mêmes
    # routes, la même confirmation irréversible et le même traitement anti double-envoi.
    if 'id="sentrix-dm-style"' not in html:
        html = html.replace("</head>", dm_panel._DM_STYLE + "\n</head>", 1)
    if 'id="sentrix-dm-panel"' not in html:
        html = html.replace("</body>", dm_panel._DM_SCRIPT + "\n" + _ADAPTER + "\n</body>", 1)
    elif 'id="sentrix-v60-dm-adapter"' not in html:
        html = html.replace("</body>", _ADAPTER + "\n</body>", 1)

    dashboard.INDEX_HTML = html
    logger.info("Dashboard V60 : interface DM propriétaire restaurée sur le frontend final.")
    return 'data-tab="dm"' in html and 'id="sentrix-dm-panel"' in html


__all__ = ["install"]
