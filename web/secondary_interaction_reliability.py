"""Fiabilité des interactions pour les pages secondaires SentriX.

Cette couche reste volontairement absente de /app : le dashboard principal conserve son
JavaScript natif sans wrapper fetch. Operations, Enterprise et Recours sont des pages
isolées ; on peut donc y ajouter un filet de sécurité léger qui :
- force les boutons sans type explicite à type=button ;
- affiche les erreurs HTTP/API au lieu de laisser un bouton sembler mort ;
- affiche aussi les erreurs JavaScript/promesses non gérées ;
- ne consomme jamais la réponse originale (response.clone()).
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.secondary-interactions")
_INSTALLED = False


RELIABILITY_JS = r"""
<script id="sentrix-secondary-interaction-reliability">
(() => {
  "use strict";
  if (window.__sentrixSecondaryInteractionReliability) return;
  window.__sentrixSecondaryInteractionReliability = true;

  function statusBox() {
    let box = document.getElementById("status");
    if (box) return box;
    box = document.getElementById("sentrixInteractionStatus");
    if (box) return box;
    box = document.createElement("div");
    box.id = "sentrixInteractionStatus";
    box.setAttribute("role", "status");
    box.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:9999;max-width:min(520px,calc(100vw - 32px));padding:11px 13px;border:1px solid #6a3040;border-radius:10px;background:#2c141d;color:#ffb2bf;font:600 13px system-ui;box-shadow:0 12px 35px #0008;display:none";
    document.body.appendChild(box);
    return box;
  }

  function showError(message) {
    const box = statusBox();
    const text = String(message || "Action impossible. Réessayez.").trim();
    box.textContent = text.length > 700 ? text.slice(0, 697) + "..." : text;
    box.classList.remove("hidden");
    box.classList.add("bad");
    box.style.display = "block";
  }

  function normaliseError(value) {
    if (!value) return "Action impossible. Réessayez.";
    if (typeof value === "string") return value;
    if (value.message) return value.message;
    try { return JSON.stringify(value); } catch (_) { return String(value); }
  }

  document.querySelectorAll("button:not([type])").forEach(button => {
    button.type = "button";
  });

  // Les pages secondaires utilisent toutes fetch() pour leurs actions. On observe les
  // échecs sans modifier la réponse remise au code métier : le clone est lu en parallèle.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    try {
      const response = await nativeFetch(...args);
      if (!response.ok) {
        const url = String(response.url || args[0] || "");
        if (url.includes("/api/")) {
          response.clone().text().then(raw => {
            let message = "Action refusée par SentriX (HTTP " + response.status + ").";
            if (raw) {
              try {
                const data = JSON.parse(raw);
                message = data.error || data.message || message;
              } catch (_) {
                if (raw.length < 500 && !raw.trim().startsWith("<")) message = raw.trim() || message;
              }
            }
            showError(message);
          }).catch(() => showError("Action refusée par SentriX (HTTP " + response.status + ")."));
        }
      }
      return response;
    } catch (error) {
      showError("Impossible de joindre SentriX : " + normaliseError(error));
      throw error;
    }
  };

  window.addEventListener("unhandledrejection", event => {
    showError("Action interrompue : " + normaliseError(event.reason));
  });
  window.addEventListener("error", event => {
    if (event && event.message) showError("Erreur de page : " + event.message);
  });
})();
</script>
"""


def _inject(html: str) -> str:
    if not isinstance(html, str) or "</body>" not in html:
        return html
    if 'id="sentrix-secondary-interaction-reliability"' in html:
        return html
    return html.replace("</body>", RELIABILITY_JS + "\n</body>", 1)


def install(*modules) -> None:
    """Renforce uniquement Operations, Enterprise et la page publique de recours."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    names = {"OPERATIONS_HTML", "ENTERPRISE_HTML", "APPEAL_HTML"}
    changed = 0
    for module in modules:
        if module is None:
            continue
        for name in names:
            html = getattr(module, name, None)
            if not isinstance(html, str):
                continue
            patched = _inject(html)
            if patched != html:
                setattr(module, name, patched)
                changed += 1
    logger.info("Fiabilité interactions secondaires : %s page(s) renforcée(s).", changed)
