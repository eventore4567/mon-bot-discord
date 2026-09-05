"""Dernière couche produit SentriX.

Elle ne crée pas de nouvelle API : les routes dashboard sont déjà installées avant aiohttp.
Cette couche répare seulement l'interface HTML finale après les anciens patchs visuels et
réaffirme les contrôles opérationnels des tickets une fois tous les cogs chargés.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.sentrix-final-product-finish")


_EMBED_RUNTIME_JS = r'''
<script id="sentrix-embed-runtime-finish">
(() => {
  "use strict";
  if (window.__sentrixEmbedRuntimeFinish) return;
  window.__sentrixEmbedRuntimeFinish = true;

  const getState = () => { try { return typeof state !== "undefined" ? state : null; } catch (_) { return null; } };
  const byId = id => document.getElementById(id);

  function renderEmbedPage(){
    const s = getState();
    if (!s || s.tab !== "embeds" || !s.guildData || typeof renderEmbeds !== "function") return false;
    const title = byId("tabTitle");
    const description = byId("tabDescription");
    if (title) title.textContent = "Créateur d'embed";
    if (description) description.textContent = "Créez, prévisualisez puis envoyez un embed Discord depuis SentriX.";
    renderEmbeds();
    const bar = byId("saveBar");
    if (bar) bar.classList.remove("hidden");
    const save = byId("saveButton");
    if (save) save.textContent = "Envoyer l'embed";
    const status = byId("saveStatus");
    if (status) status.textContent = "Aperçu en direct";
    s.dirty = false;
    return true;
  }

  function installRenderHook(){
    try {
      if (typeof renderTab !== "function" || renderTab.__sentrixEmbedsFinal) return;
      const previous = renderTab;
      const wrapped = function(...args){
        const s = getState();
        if (s?.tab === "embeds" && renderEmbedPage()) return;
        return previous.apply(this, args);
      };
      wrapped.__sentrixEmbedsFinal = true;
      wrapped.__sentrixPrevious = previous;
      renderTab = wrapped;
    } catch (error) {
      console.warn("SentriX embed render hook", error);
    }
  }

  function findNavigation(){
    const candidates = [
      document.querySelector("aside nav"),
      document.querySelector("aside"),
      document.querySelector(".sidebar nav"),
      document.querySelector(".sidebar"),
      document.querySelector("[class*='sidebar']"),
      document.querySelector("nav")
    ];
    return candidates.find(Boolean) || null;
  }

  function ensureButton(){
    let button = document.querySelector('[data-tab="embeds"]');
    if (!button) {
      const nav = findNavigation();
      if (!nav) return null;
      const sample = nav.querySelector("button[data-tab]") || nav.querySelector("button");
      button = document.createElement("button");
      button.type = "button";
      button.dataset.tab = "embeds";
      button.textContent = "Embeds";
      button.id = "sentrixEmbedDashboardButton";
      if (sample?.className) button.className = sample.className;
      nav.appendChild(button);
    }
    if (button.dataset.sentrixEmbedBound !== "1") {
      button.dataset.sentrixEmbedBound = "1";
      button.addEventListener("click", event => {
        event.preventDefault();
        const s = getState();
        if (!s) return;
        s.tab = "embeds";
        document.querySelectorAll("[data-tab]").forEach(item => item.classList.toggle("active", item === button));
        renderEmbedPage();
      }, true);
    }
    return button;
  }

  async function sendCurrentEmbed(event){
    const s = getState();
    if (s?.tab !== "embeds" || typeof sendEmbed !== "function") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    await sendEmbed();
  }

  document.addEventListener("click", event => {
    if (event.target?.id === "saveButton") sendCurrentEmbed(event);
  }, true);
  document.addEventListener("submit", event => {
    if (event.target?.id === "settingsForm") sendCurrentEmbed(event);
  }, true);

  function install(){
    installRenderHook();
    ensureButton();
    const s = getState();
    if (s?.tab === "embeds") renderEmbedPage();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, {once:true});
  else install();
  [250, 1000, 2500].forEach(delay => setTimeout(install, delay));
})();
</script>
'''


def _install_embed_dashboard_finish() -> bool:
    """Injecte CSS + JS sans dépendre des anciennes chaînes exactes de renderTab/CSS."""
    try:
        from web import dashboard
        from web import embed_dashboard
    except Exception:
        logger.exception("Dashboard embed finish indisponible.")
        return False

    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    css_marker = 'id="sentrix-embed-runtime-finish-css"'
    js_marker = 'id="sentrix-embed-runtime-finish"'

    if css_marker not in html:
        css = f'\n<style id="sentrix-embed-runtime-finish-css">\n{embed_dashboard.EMBED_CSS}\n</style>\n'
        html = html.replace("</head>", css + "</head>", 1) if "</head>" in html else css + html

    # EMBED_JS contient les fonctions renderEmbeds/sendEmbed. L'injecter ici rend la
    # correction indépendante du vieux point d'insertion "function renderTab()".
    if js_marker not in html:
        script = (
            '\n<script id="sentrix-embed-runtime-core">\n'
            + embed_dashboard.EMBED_JS
            + '\n</script>\n'
            + _EMBED_RUNTIME_JS
        )
        html = html.replace("</body>", script + "\n</body>", 1) if "</body>" in html else html + script

    dashboard.INDEX_HTML = html
    ok = css_marker in html and js_marker in html
    logger.info("Dashboard embeds final installé=%s.", ok)
    return ok


def _restore_ticket_operations(bot: commands.Bot) -> bool:
    try:
        from cogs import ticket_controls_minimal
        ticket_controls_minimal.install(bot, "cogs.sentrix_regression_fix")
        from cogs import tickets as tickets_mod
        expected = set(ticket_controls_minimal._ALLOWED_KEYS)
        available = set(tickets_mod.STAFF_BUTTONS)
        ok = expected.issubset(available)
        logger.info("Tickets opérationnels complets=%s (%s).", ok, ", ".join(sorted(available)))
        return ok
    except Exception:
        logger.exception("Restauration des contrôles opérationnels tickets impossible.")
        return False


async def install(bot: commands.Bot) -> dict[str, bool]:
    state = {
        "embed_dashboard_final": _install_embed_dashboard_finish(),
        "ticket_operations": _restore_ticket_operations(bot),
    }
    bot.sentrix_final_product_finish_state = state
    logger.info("SentriX final product finish: %s", state)
    return state


__all__ = ["install"]
