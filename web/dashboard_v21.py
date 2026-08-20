"""SentriX V2.1 — monitoring visible et finition mobile du dashboard.

La couche ne crée aucune nouvelle route sensible. Elle lit uniquement /health (déjà
secret-free) et enrichit le panneau V2 existant. Les permissions de /api/guild restent
celles du dashboard principal.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.v21")
_INSTALLED = False

V21_CSS = r"""
<style id="sentrix-v21-css">
  .sx-v21-health{
    display:flex;flex-wrap:wrap;gap:7px;margin-top:11px;padding-top:11px;
    border-top:1px solid #29314c;
  }
  .sx-v21-chip{
    display:inline-flex;align-items:center;gap:6px;min-height:28px;padding:5px 9px;
    border:1px solid #303a5c;border-radius:999px;background:#0b101c;
    color:var(--muted);font-size:11px;font-weight:700;white-space:nowrap;
  }
  .sx-v21-dot{width:7px;height:7px;border-radius:50%;background:#6b7280;box-shadow:0 0 10px currentColor}
  .sx-v21-chip[data-state="ok"] .sx-v21-dot{background:#57f287}
  .sx-v21-chip[data-state="warn"] .sx-v21-dot{background:#fee75c}
  .sx-v21-chip[data-state="bad"] .sx-v21-dot{background:#ed4245}
  .sx-v21-meta{margin-left:auto;color:var(--muted);font-size:10px;align-self:center}
  @media(max-width:680px){
    body{overflow-x:hidden}
    .sx-v2-strip{padding:13px;border-radius:13px}
    .sx-v2-head h3{font-size:15px}
    .sx-v2-head p{font-size:11px}
    .sx-v2-metric{padding:10px}
    .sx-v2-metric b{font-size:17px}
    .sx-v2-link{min-height:58px;padding:10px}
    .sx-v21-health{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
    .sx-v21-chip{white-space:normal;min-width:0}
    .sx-v21-meta{grid-column:1/-1;margin-left:0}
    button,select,input,a{touch-action:manipulation}
  }
  @media(max-width:390px){
    .sx-v21-health{grid-template-columns:1fr}
    .sx-v21-meta{grid-column:auto}
  }
</style>
"""

V21_JS = r"""
<script id="sentrix-v21-js">
(() => {
  "use strict";
  if (window.__sentrixV21) return;
  window.__sentrixV21 = true;

  const stateFor = value => value === true || value === "ok" || value === "healthy" ? "ok" :
    value === false || value === "error" || value === "unavailable" ? "bad" : "warn";
  const safe = value => String(value ?? "?").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));

  function chip(label, value, state){
    return `<span class="sx-v21-chip" data-state="${stateFor(state)}"><i class="sx-v21-dot"></i>${safe(label)} <b>${safe(value)}</b></span>`;
  }

  function ensureHost(){
    const section = document.getElementById("sxV2Snapshot");
    if (!section) return null;
    let host = document.getElementById("sxV21Health");
    if (!host){
      host = document.createElement("div");
      host.id = "sxV21Health";
      host.className = "sx-v21-health";
      section.appendChild(host);
    }
    return host;
  }

  async function refreshHealth(){
    const host = ensureHost();
    if (!host) return;
    try{
      const response = await fetch("/health", {cache:"no-store", credentials:"same-origin"});
      const data = await response.json();
      const ai = data.ai || {};
      const prod = data.production_v9 || {};
      const cmd = prod.commands || {};
      const latency = data.latency_ms == null ? "? ms" : `${data.latency_ms} ms`;
      const aiState = (ai.probe && ai.probe.status) || (ai.key_configured ? "configurée" : "non configurée");
      const errors = Number(cmd.recent_errors || 0);
      const slow = Number(cmd.recent_slow_or_stuck || 0);
      host.innerHTML = [
        chip("Bot", data.health_level || (data.ok ? "healthy" : "degraded"), data.health_level || data.ok),
        chip("Discord", latency, data.discord_ready),
        chip("Base", data.database_ok ? "OK" : "erreur", data.database_ok),
        chip("IA", aiState, aiState === "ok" || aiState === "configurée" ? "ok" : (ai.key_configured ? "warn" : "warn")),
        chip("Erreurs 15 min", errors, errors === 0 ? "ok" : (errors < 5 ? "warn" : "bad")),
        chip("Lentes/bloquées", slow, slow === 0 ? "ok" : (slow < 5 ? "warn" : "bad")),
        `<span class="sx-v21-meta">V2.1 · actualisation santé automatique</span>`
      ].join("");
    }catch(_){
      host.innerHTML = chip("Monitoring", "indisponible", "bad") + `<span class="sx-v21-meta">V2.1</span>`;
    }
  }

  const observer = new MutationObserver(() => ensureHost());
  observer.observe(document.documentElement, {childList:true,subtree:true});
  setTimeout(refreshHealth, 250);
  setInterval(refreshHealth, 15000);
})();
</script>
"""


def install(dashboard_module) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    html = dashboard_module.INDEX_HTML
    if 'id="sentrix-v21-css"' not in html:
        html = html.replace("</head>", V21_CSS + "\n</head>", 1)
    if 'id="sentrix-v21-js"' not in html:
        html = html.replace("</body>", V21_JS + "\n</body>", 1)
    dashboard_module.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Dashboard SentriX V2.1 installé : santé live + finition mobile.")
