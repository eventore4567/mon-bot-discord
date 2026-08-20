"""Couche visuelle V2 du dashboard SentriX.

Ajoute un snapshot vivant au mode simple sans remplacer les routes, les permissions OAuth
ou les fonctions critiques de web.dashboard. Les chiffres proviennent exclusivement de
/api/guild/<id>, déjà protégé par la vérification administrateur du dashboard.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.v2-home")
_INSTALLED = False

V2_CSS = r"""
<style id="sentrix-v2-home-css">
  .sx-v2-strip{
    margin:14px 0;
    border:1px solid var(--line);
    border-radius:16px;
    padding:16px;
    background:linear-gradient(135deg,#111728,#0d111d);
  }
  .sx-v2-head{
    display:flex;
    justify-content:space-between;
    align-items:flex-start;
    gap:12px;
    margin-bottom:12px;
  }
  .sx-v2-head h3{margin:0;font-size:17px}
  .sx-v2-head p{margin:4px 0 0;color:var(--muted);font-size:12px;line-height:1.45}
  .sx-v2-badge{
    border:1px solid #3c4770;
    border-radius:999px;
    padding:5px 9px;
    font-size:10px;
    font-weight:850;
    letter-spacing:.08em;
    text-transform:uppercase;
    color:var(--brand2);
    white-space:nowrap;
  }
  .sx-v2-metrics{
    display:grid;
    grid-template-columns:repeat(5,minmax(0,1fr));
    gap:8px;
  }
  .sx-v2-metric{
    border:1px solid #29314c;
    border-radius:12px;
    padding:11px;
    background:#0d1220;
    min-width:0;
  }
  .sx-v2-metric b{
    display:block;
    font-size:18px;
    overflow:hidden;
    text-overflow:ellipsis;
  }
  .sx-v2-metric span{
    display:block;
    margin-top:3px;
    color:var(--muted);
    font-size:10px;
    text-transform:uppercase;
    letter-spacing:.04em;
  }
  .sx-v2-bar{
    height:3px;
    margin-top:8px;
    border-radius:999px;
    overflow:hidden;
    background:#202840;
  }
  .sx-v2-bar i{
    display:block;
    height:100%;
    width:0;
    background:var(--brand);
    border-radius:inherit;
    transition:width .35s ease;
  }
  .sx-v2-links{
    display:grid;
    grid-template-columns:repeat(4,minmax(0,1fr));
    gap:8px;
    margin-top:10px;
  }
  .sx-v2-link{
    border:1px solid #29314c;
    border-radius:11px;
    background:#101625;
    color:var(--text);
    padding:11px;
    cursor:pointer;
    text-align:left;
  }
  .sx-v2-link:hover{border-color:#4d5b8c;background:#151d30}
  .sx-v2-link b,.sx-v2-link span{display:block}
  .sx-v2-link span{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.35}
  @media(max-width:900px){
    .sx-v2-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
    .sx-v2-links{grid-template-columns:repeat(2,minmax(0,1fr))}
  }
  @media(max-width:560px){
    .sx-v2-head{display:grid}
    .sx-v2-metrics,.sx-v2-links{grid-template-columns:1fr}
  }
</style>
"""

V2_JS = r"""
<script id="sentrix-v2-home-js">
(() => {
  "use strict";
  if (window.__sentrixV2Home) return;
  window.__sentrixV2Home = true;

  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
  const fmt = value => {
    const n = Number(value || 0);
    return Number.isFinite(n) ? Math.round(n).toLocaleString("fr-FR") : "0";
  };
  const guildId = () => {
    try { return typeof state !== "undefined" && state.guildId ? String(state.guildId) : ""; }
    catch (_) { return ""; }
  };

  function openPage(path){
    const gid = guildId();
    location.href = path + (gid ? "?guild=" + encodeURIComponent(gid) : "");
  }

  function openDestination(id){
    const button = document.querySelector('[data-sx-destination="'+id+'"]');
    if (button) { button.click(); return; }
    if (id === "operations") openPage("/operations");
    else if (id === "community") openPage("/community");
    else if (id === "engagement") openPage("/engagement");
    else if (id === "setup") openPage("/setup-center");
  }

  function ensure(){
    const home = document.getElementById("sxSimpleHome");
    if (!home) return null;
    let section = document.getElementById("sxV2Snapshot");
    if (section) return section;
    section = document.createElement("section");
    section.id = "sxV2Snapshot";
    section.className = "sx-v2-strip";
    const hero = home.querySelector(".sx-simple-hero");
    if (hero && hero.nextSibling) hero.parentNode.insertBefore(section, hero.nextSibling);
    else home.prepend(section);
    section.addEventListener("click", event => {
      const target = event.target.closest("[data-sx-v2-go]");
      if (!target) return;
      openDestination(target.getAttribute("data-sx-v2-go"));
    });
    return section;
  }

  function currentData(){
    try {
      if (typeof state !== "undefined" && state.guildData) return state.guildData;
    } catch (_) {}
    return null;
  }

  function render(){
    const section = ensure();
    if (!section) return;
    const data = currentData();
    if (!data || !guildId()) {
      section.innerHTML = `
        <div class="sx-v2-head">
          <div><h3>SentriX V2 Control Center</h3>
          <p>Choisissez un serveur pour afficher les données en direct.</p></div>
          <span class="sx-v2-badge">V2 LIVE</span>
        </div>`;
      return;
    }

    const guild = data.guild || {};
    const metrics = data.metrics || {};
    const items = [
      ["Membres", guild.members || 0],
      ["Commandes 24 h", metrics.commands_24h || 0],
      ["Tickets ouverts", metrics.open_tickets || 0],
      ["Avertissements", metrics.warnings || 0],
      ["Profils actifs", metrics.profiles || 0],
    ];
    const maxValue = Math.max(1, ...items.map(item => Number(item[1]) || 0));
    const cards = items.map(([label,value]) => {
      const width = Math.max(4, Math.round(((Number(value)||0) / maxValue) * 100));
      return `<div class="sx-v2-metric"><b>${fmt(value)}</b><span>${esc(label)}</span><div class="sx-v2-bar"><i style="width:${width}%"></i></div></div>`;
    }).join("");

    section.innerHTML = `
      <div class="sx-v2-head">
        <div>
          <h3>SentriX V2 Control Center</h3>
          <p>${esc(guild.name || "Serveur")} · aperçu en direct de l'activité et accès aux centres principaux.</p>
        </div>
        <span class="sx-v2-badge">V2 LIVE</span>
      </div>
      <div class="sx-v2-metrics">${cards}</div>
      <div class="sx-v2-links">
        <button class="sx-v2-link" type="button" data-sx-v2-go="operations"><b>Centre staff</b><span>Dossiers, membres et diagnostics.</span></button>
        <button class="sx-v2-link" type="button" data-sx-v2-go="community"><b>Communauté</b><span>Croissance et activité du serveur.</span></button>
        <button class="sx-v2-link" type="button" data-sx-v2-go="engagement"><b>Engagement</b><span>Niveaux, économie et rétention.</span></button>
        <button class="sx-v2-link" type="button" data-sx-v2-go="setup"><b>Configuration</b><span>Tous les systèmes dans un seul centre.</span></button>
      </div>`;
  }

  let lastSignature = "";
  function tick(){
    ensure();
    const data = currentData();
    const signature = JSON.stringify([
      guildId(),
      data && data.guild && data.guild.members,
      data && data.metrics && data.metrics.commands_24h,
      data && data.metrics && data.metrics.open_tickets,
      data && data.metrics && data.metrics.warnings,
      data && data.metrics && data.metrics.profiles,
    ]);
    if (signature !== lastSignature) {
      lastSignature = signature;
      render();
    }
  }

  const observer = new MutationObserver(() => { ensure(); });
  observer.observe(document.documentElement, {childList:true, subtree:true});
  setInterval(tick, 1200);
  setTimeout(tick, 50);
})();
</script>
"""


def install(dashboard_module) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    html = dashboard_module.INDEX_HTML
    if 'id="sentrix-v2-home-css"' not in html:
        html = html.replace("</head>", V2_CSS + "\n</head>", 1)
    if 'id="sentrix-v2-home-js"' not in html:
        html = html.replace("</body>", V2_JS + "\n</body>", 1)
    dashboard_module.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Dashboard V2 Home installé.")
