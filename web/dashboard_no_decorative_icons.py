"""Nettoyage visuel final des interfaces web SentriX.

Le dashboard doit rester sobre et professionnel : aucun emoji décoratif, gros check vert,
pictogramme ou symbole graphique injecté dans les boutons, onglets, titres et badges.
Les avatars/photos de profil, images configurées par l'utilisateur et aperçus d'embed ne
sont pas touchés.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.no-icons")
_INSTALLED = False


CLEAN_CSS = r"""
<style id="sentrix-no-decorative-icons-css">
  /* Les anciens blocs servant uniquement à afficher un pictogramme disparaissent. */
  .sx-system-icon,
  .decorative-icon,
  .status-icon,
  .check-icon,
  .emoji-icon,
  [data-decorative-icon="true"]{display:none!important}

  /* Évite qu'un ancien emplacement d'icône laisse une grosse colonne vide. */
  .sx-system-tile>div:first-child{min-width:0}
  button,.btn,.tab,label,h1,h2,h3,h4,h5,h6{font-family:inherit}
</style>
"""


CLEAN_JS = r"""
<script id="sentrix-no-decorative-icons-js">
(() => {
  "use strict";
  if (window.__sentrixNoDecorativeIcons) return;
  window.__sentrixNoDecorativeIcons = true;

  // Emoji Unicode + dingbats + variation selectors. On garde la ponctuation normale,
  // les puces sobres et le texte saisi/configuré par les utilisateurs.
  const emojiRE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0E}\u{FE0F}]/gu;
  const uiSelector = [
    "button", ".btn", ".tab", "nav", "aside", ".navigation", "#navigation",
    "h1", "h2", "h3", "h4", "h5", "h6", "label", ".badge", ".chip",
    ".sx-chip", ".sx-system-state", ".sx-sec-stat", ".sx-safe-kicker",
    ".sx-safe-status", ".sx-safe-metric", ".panel-head", ".head"
  ].join(",");

  function cleanTextNode(node){
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const parent = node.parentElement;
    if (!parent) return;
    if (parent.closest("textarea,input,pre,code,[contenteditable='true'],.embed-preview,.preview,[data-user-content='true']")) return;
    const cleaned = node.nodeValue.replace(emojiRE, "").replace(/\s{2,}/g, " ");
    if (cleaned !== node.nodeValue) node.nodeValue = cleaned;
  }

  function cleanElement(element){
    if (!(element instanceof Element)) return;
    if (element.matches(uiSelector) || element.closest(uiSelector)) {
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(cleanTextNode);
    }

    // Un élément explicitement prévu uniquement pour une icône devient inutile une fois
    // son pictogramme retiré. On ne touche jamais aux avatars, images ou aperçus.
    if (element.matches(".sx-system-icon,.decorative-icon,.status-icon,.check-icon,.emoji-icon,[data-decorative-icon='true']")) {
      element.style.display = "none";
    }
  }

  function cleanAll(root=document){
    if (root.nodeType === Node.ELEMENT_NODE) cleanElement(root);
    const scope = root.querySelectorAll ? root : document;
    scope.querySelectorAll(uiSelector).forEach(cleanElement);
    scope.querySelectorAll(".sx-system-icon,.decorative-icon,.status-icon,.check-icon,.emoji-icon,[data-decorative-icon='true']").forEach(cleanElement);
  }

  const observer = new MutationObserver(mutations => {
    for (const mutation of mutations) {
      if (mutation.type === "characterData") cleanTextNode(mutation.target);
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.TEXT_NODE) cleanTextNode(node);
        else if (node.nodeType === Node.ELEMENT_NODE) cleanAll(node);
      }
    }
  });

  function start(){
    cleanAll(document);
    observer.observe(document.documentElement, {subtree:true, childList:true, characterData:true});
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-no-decorative-icons-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", CLEAN_CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", CLEAN_JS + "\n</body>", 1)
    return html


def install(*modules) -> None:
    """Applique le nettoyage en DERNIER sur les pages web connues de SentriX."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    candidate_names = (
        "INDEX_HTML",
        "SETUP_CENTER_HTML",
        "SETUP_HTML",
        "DESIGN_SETUP_HTML",
        "EMBED_CENTER_HTML",
        "OWNER_SERVERS_HTML",
    )
    changed = 0
    for module in modules:
        if module is None:
            continue
        for name in candidate_names:
            html = getattr(module, name, None)
            if not isinstance(html, str) or "</body>" not in html:
                continue
            new_html = _inject(html)
            if new_html != html:
                setattr(module, name, new_html)
                changed += 1

    logger.info("Dashboard SentriX sans icônes décoratives : %s page(s) nettoyée(s).", changed)
