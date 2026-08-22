"""Nettoyage visuel final des interfaces web SentriX.

Le dashboard doit rester sobre et professionnel : aucun emoji décoratif, gros check vert,
pictogramme ou symbole graphique injecté dans les boutons, onglets, titres et badges.
Cette couche finale impose aussi les vrais noms produits, un état actif noir et l'identité
Discord réelle (nom + avatar animé quand Discord en fournit un).
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger("bot.dashboard.no-icons")
_INSTALLED = False


CLEAN_CSS = r"""
<style id="sentrix-no-decorative-icons-css">
  .sx-system-icon,
  .decorative-icon,
  .status-icon,
  .check-icon,
  .emoji-icon,
  [data-decorative-icon="true"]{display:none!important}
  .sx-system-tile>div:first-child{min-width:0}
  button,.btn,.tab,label,h1,h2,h3,h4,h5,h6{font-family:inherit}

  /* Les sélecteurs/entrées de centres restent sobres : plus de gros violet plein. */
  .sx-dashboard-dark-option,
  .sx-dashboard-dark-option:hover,
  .sx-dashboard-dark-option:focus,
  .sx-dashboard-dark-option.active,
  .sx-dashboard-dark-option[aria-current="page"]{
    background:#050608!important;
    background-image:none!important;
    border-color:#2b3140!important;
    color:#f7f8fb!important;
    box-shadow:none!important;
  }
  .sx-dashboard-dark-option *{color:inherit!important}

  /* Vraie photo Discord, y compris GIF animé. */
  #userAvatar{
    overflow:hidden!important;
    border-radius:50%!important;
    background:#07080c!important;
    background-image:none!important;
    box-shadow:0 0 0 1px #34394a!important;
  }
  #userAvatar img.sx-real-discord-avatar{
    display:block!important;
    width:100%!important;
    height:100%!important;
    object-fit:cover!important;
    border-radius:50%!important;
    transform:none!important;
  }
</style>
"""


CLEAN_JS = r"""
<script id="sentrix-no-decorative-icons-js">
(() => {
  "use strict";
  if (window.__sentrixNoDecorativeIcons) return;
  window.__sentrixNoDecorativeIcons = true;

  const emojiRE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0E}\u{FE0F}]/gu;
  const uiSelector = [
    "button", ".btn", ".tab", "nav", "aside", ".navigation", "#navigation",
    "h1", "h2", "h3", "h4", "h5", "h6", "label", ".badge", ".chip",
    ".sx-chip", ".sx-system-state", ".sx-sec-stat", ".sx-safe-kicker",
    ".sx-safe-status", ".sx-safe-metric", ".panel-head", ".head"
  ].join(",");

  const visibleNames = [
    [/Engagement\s+V3/gi, "Engagement communautaire"],
    [/Platform\s+V4/gi, "Centre de contrôle"],
    [/SentriX\s+V2\s+Control\s+Center/gi, "Aperçu du serveur"],
    [/V2\s+LIVE/gi, "EN DIRECT"],
    [/Bot\s+V10\s*[—-]\s*/gi, ""],
    [/Conservation automatique\s+V10/gi, "Conservation automatique"],
    [/V10\s+indisponible/gi, "Diagnostic indisponible"],
    [/Giveaways\s+V2/gi, "Giveaways avancés"],
    [/Économie\s+V2/gi, "Économie"],
    [/Dashboard\s+Community\s+Growth\s+V2/gi, "Communauté"],
  ];

  function cleanTextNode(node){
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const parent = node.parentElement;
    if (!parent) return;
    if (parent.closest("textarea,input,pre,code,[contenteditable='true'],.embed-preview,.preview,[data-user-content='true']")) return;
    let cleaned = node.nodeValue.replace(emojiRE, "");
    for (const [pattern, replacement] of visibleNames) cleaned = cleaned.replace(pattern, replacement);
    cleaned = cleaned.replace(/\s{2,}/g, " ");
    if (cleaned !== node.nodeValue) node.nodeValue = cleaned;
  }

  function markDarkProductOptions(root=document){
    const candidates = root.querySelectorAll ? root.querySelectorAll("button,a,[role='button'],.btn,.card") : [];
    for (const element of candidates) {
      const text = (element.textContent || "").replace(/\s+/g, " ").trim().toLocaleLowerCase("fr");
      if (
        text.includes("engagement communautaire") ||
        text.includes("centre de contrôle") ||
        text.includes("profils, quêtes, saisons") ||
        text.includes("opérations, économie, sauvegardes") ||
        text.includes("opérations, économie, backups")
      ) element.classList.add("sx-dashboard-dark-option");
    }
  }

  function cleanElement(element){
    if (!(element instanceof Element)) return;
    if (element.matches(uiSelector) || element.closest(uiSelector)) {
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      nodes.forEach(cleanTextNode);
    }
    if (element.matches(".sx-system-icon,.decorative-icon,.status-icon,.check-icon,.emoji-icon,[data-decorative-icon='true']")) {
      element.style.display = "none";
    }
  }

  function cleanAll(root=document){
    if (root.nodeType === Node.ELEMENT_NODE) cleanElement(root);
    const scope = root.querySelectorAll ? root : document;
    scope.querySelectorAll(uiSelector).forEach(cleanElement);
    scope.querySelectorAll(".sx-system-icon,.decorative-icon,.status-icon,.check-icon,.emoji-icon,[data-decorative-icon='true']").forEach(cleanElement);
    markDarkProductOptions(scope);
  }

  let identityBusy = false;
  async function syncDiscordIdentity(){
    if (identityBusy) return;
    const userName = document.getElementById("userName");
    const userAvatar = document.getElementById("userAvatar");
    if (!userName && !userAvatar) return;
    identityBusy = true;
    try {
      const response = await fetch("/api/me", {credentials:"same-origin", cache:"no-store"});
      if (!response.ok) return;
      const data = await response.json();
      const user = data && data.user ? data.user : null;
      if (!user) return;
      if (userName && user.username) userName.textContent = user.username;
      if (userAvatar && user.avatar_url) {
        const current = userAvatar.querySelector("img.sx-real-discord-avatar");
        if (!current || current.getAttribute("src") !== user.avatar_url) {
          const image = document.createElement("img");
          image.className = "avatar sx-real-discord-avatar";
          image.src = user.avatar_url;
          image.alt = user.username ? `Photo de profil de ${user.username}` : "Photo de profil Discord";
          image.decoding = "async";
          userAvatar.replaceChildren(image);
        }
      }
    } catch (_) {
      /* La page principale gère déjà l'état de session. */
    } finally {
      identityBusy = false;
    }
  }

  const observer = new MutationObserver(mutations => {
    let identityMayHaveChanged = false;
    for (const mutation of mutations) {
      if (mutation.type === "characterData") cleanTextNode(mutation.target);
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.TEXT_NODE) cleanTextNode(node);
        else if (node.nodeType === Node.ELEMENT_NODE) {
          cleanAll(node);
          if (node.id === "userAvatar" || node.id === "userName" || node.querySelector?.("#userAvatar,#userName")) identityMayHaveChanged = true;
        }
      }
      if (mutation.target?.id === "userAvatar" || mutation.target?.id === "userName") identityMayHaveChanged = true;
    }
    if (identityMayHaveChanged) setTimeout(syncDiscordIdentity, 0);
  });

  function start(){
    cleanAll(document);
    syncDiscordIdentity();
    observer.observe(document.documentElement, {subtree:true, childList:true, characterData:true});
    /* Les anciennes couches d'avatar peuvent finir leur initialisation après DOMContentLoaded. */
    setTimeout(syncDiscordIdentity, 150);
    setTimeout(syncDiscordIdentity, 900);
    setTimeout(syncDiscordIdentity, 2200);
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


def _unique_modules(*groups) -> tuple:
    result = []
    seen = set()
    for group in groups:
        for module in group:
            if module is None:
                continue
            marker = id(module)
            if marker in seen:
                continue
            seen.add(marker)
            result.append(module)
    return tuple(result)


def install(*modules) -> None:
    """Installe les derniers outils sûrs puis nettoie toutes les pages en dernier."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    enterprise_module = None
    platform_module = None
    if modules:
        try:
            from . import production_health
            production_health.install(modules[0])
        except Exception:
            logger.exception("Impossible d'installer le healthcheck de production.")
        try:
            from . import dashboard_server_tools
            dashboard_server_tools.install(modules[0])
        except Exception:
            logger.exception("Impossible d'installer les outils serveur du dashboard.")
        try:
            from . import enterprise_suite
            enterprise_suite.install(modules[0])
            enterprise_module = enterprise_suite
        except Exception:
            logger.exception("Impossible d'installer le centre Enterprise du dashboard.")
        try:
            from . import platform_v4
            platform_module = platform_v4
        except Exception:
            logger.exception("Impossible de charger le centre de contrôle du dashboard.")

    loaded_web_modules = tuple(
        module
        for name, module in tuple(sys.modules.items())
        if module is not None and (name == "web" or name.startswith("web."))
    )
    all_modules = _unique_modules(
        modules,
        (enterprise_module,) if enterprise_module is not None else (),
        (platform_module,) if platform_module is not None else (),
        loaded_web_modules,
    )

    try:
        from . import secondary_interaction_reliability
        secondary_interaction_reliability.install(*all_modules)
    except Exception:
        logger.exception("Impossible d'installer la fiabilité des interactions secondaires.")

    try:
        from . import dashboard_button_feedback
        dashboard_button_feedback.install(*all_modules)
    except Exception:
        logger.exception("Impossible d'installer les micro-interactions des boutons.")

    candidate_names = (
        "INDEX_HTML",
        "SETUP_CENTER_HTML",
        "SETUP_HTML",
        "DESIGN_SETUP_HTML",
        "EMBED_CENTER_HTML",
        "OWNER_SERVERS_HTML",
        "OPERATIONS_HTML",
        "ENTERPRISE_HTML",
        "APPEAL_HTML",
        "COMMUNITY_HTML",
        "ENGAGEMENT_HTML",
        "PROFILE_HTML",
        "PLATFORM_HTML",
        "PRIVACY_HTML",
    )
    changed = 0
    for module in all_modules:
        for name in candidate_names:
            html = getattr(module, name, None)
            if not isinstance(html, str) or "</body>" not in html:
                continue
            new_html = _inject(html)
            if new_html != html:
                setattr(module, name, new_html)
                changed += 1

    logger.info("Dashboard SentriX finalisé : noms produit, thème noir et identité Discord sur %s page(s).", changed)
