"""Interrupteurs Économie / Niveaux dans le dashboard principal SentriX.

Couche sûre : ajoute uniquement deux routes API et une carte autonome. Elle ne remplace ni
renderTab, ni selectGuild, ni fetch, ni save du dashboard principal.
"""
from __future__ import annotations

import logging

from aiohttp import web

from utils.system_features import get_system_features, set_system_feature

logger = logging.getLogger("bot.dashboard.system-features")
_INSTALLED = False

SYSTEMS_CSS = r"""
<style id="sentrix-system-features-css">
  #sentrixSystemFeatures{margin:0 0 20px;border:1px solid #2a3150;border-radius:18px;background:linear-gradient(145deg,#111624,#0b0f19);overflow:hidden;box-shadow:0 16px 48px #0004}
  .sx-systems-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;padding:18px 20px;border-bottom:1px solid #252c44}
  .sx-systems-head h2{font-size:16px;margin:0 0 5px}.sx-systems-head p{margin:0;color:var(--muted,#949db5);font-size:12px;line-height:1.5}
  .sx-systems-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:16px 20px 20px}
  .sx-system-card{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center;padding:15px;border:1px solid #252d46;border-radius:14px;background:#0c111c}
  .sx-system-title{display:flex;align-items:center;gap:9px;font-weight:850;color:#f2f3ff}.sx-system-title span:first-child{font-size:19px}
  .sx-system-card p{margin:6px 0 0;color:#8e97ad;font-size:11px;line-height:1.5;max-width:560px}
  .sx-system-state{display:inline-flex;margin-top:8px;padding:4px 7px;border-radius:999px;font-size:10px;font-weight:900;letter-spacing:.04em;text-transform:uppercase;background:#153a30;color:#7be0ba;border:1px solid #2b6958}
  .sx-system-state.off{background:#3a1821;color:#ff9bad;border-color:#713044}
  .sx-system-toggle{position:relative;width:54px;height:30px;border:0;border-radius:999px;background:#384057;cursor:pointer;padding:0;transition:.18s;box-shadow:inset 0 0 0 1px #ffffff0c}
  .sx-system-toggle::after{content:"";position:absolute;left:4px;top:4px;width:22px;height:22px;border-radius:50%;background:#fff;transition:.18s;box-shadow:0 3px 8px #0005}
  .sx-system-toggle.on{background:#6f5cf0}.sx-system-toggle.on::after{left:28px}.sx-system-toggle:disabled{opacity:.5;cursor:not-allowed}
  .sx-systems-note{grid-column:1/-1;color:#7e879c;font-size:11px;line-height:1.45;padding:0 2px}
  @media(max-width:760px){.sx-systems-grid{grid-template-columns:1fr}.sx-systems-head{padding:16px}.sx-systems-grid{padding:14px 16px 18px}.sx-systems-note{grid-column:auto}}
</style>
"""

SYSTEMS_JS = r"""
<script id="sentrix-system-features-js">
(() => {
  "use strict";
  if (window.__sentrixSystemFeatures) return;
  window.__sentrixSystemFeatures = true;

  let activeGuild = "";
  let values = null;
  let loading = false;

  function getGuildId(){
    try { return typeof state !== "undefined" && state.guildId ? String(state.guildId) : ""; }
    catch (_) { return ""; }
  }

  function csrf(){
    try { return typeof state !== "undefined" ? state.csrf || "" : ""; }
    catch (_) { return ""; }
  }

  function notify(message, bad=false){
    try {
      if (typeof toast === "function") return toast(message, bad);
    } catch (_) {}
    if (bad) console.error(message); else console.info(message);
  }

  function rootTarget(){
    const content = document.getElementById("serverContent");
    if (!content || content.classList.contains("hidden")) return null;
    return content;
  }

  function ensureRoot(){
    const content = rootTarget();
    if (!content) return null;
    let root = document.getElementById("sentrixSystemFeatures");
    if (!root) {
      root = document.createElement("section");
      root.id = "sentrixSystemFeatures";
      const detailed = document.getElementById("sentrixSafeOverview");
      if (detailed && detailed.parentNode === content) detailed.insertAdjacentElement("afterend", root);
      else content.insertBefore(root, content.firstChild);
    }
    return root;
  }

  function card(feature, icon, title, description, enabled){
    return `<article class="sx-system-card">
      <div>
        <div class="sx-system-title"><span>${icon}</span><span>${title}</span></div>
        <p>${description}</p>
        <span class="sx-system-state ${enabled ? "" : "off"}">${enabled ? "Activé" : "Désactivé"}</span>
      </div>
      <button class="sx-system-toggle ${enabled ? "on" : ""}" type="button" role="switch" aria-checked="${enabled ? "true" : "false"}" data-system-feature="${feature}" title="${enabled ? "Désactiver" : "Activer"} ${title}"></button>
    </article>`;
  }

  function render(){
    const root = ensureRoot();
    if (!root || !values) return;
    const economy = Boolean(values.economy_enabled);
    const levels = Boolean(values.levels_enabled);
    root.innerHTML = `
      <div class="sx-systems-head">
        <div><h2>⚙️ Systèmes du serveur</h2><p>Activez ou coupez complètement les grands systèmes de SentriX pour ce serveur.</p></div>
      </div>
      <div class="sx-systems-grid">
        ${card("economy", "💰", "Argent et boutiques", "Coupe les soldes, daily/work, transferts, récompenses monétaires, achats et toutes les boutiques.", economy)}
        ${card("levels", "📈", "Niveaux et XP", "Coupe les gains d'XP, commandes de niveau, classements de niveaux et attribution des rôles de palier.", levels)}
        <div class="sx-systems-note">Les données existantes ne sont jamais supprimées : réactiver un système restaure les anciens soldes et niveaux.</div>
      </div>`;
    root.querySelectorAll("[data-system-feature]").forEach(button => {
      button.addEventListener("click", () => toggle(button.dataset.systemFeature, button));
    });
  }

  async function load(guildId){
    if (!guildId || loading) return;
    loading = true;
    try {
      const response = await fetch(`/api/guilds/${guildId}/systems`, {cache:"no-store", credentials:"same-origin"});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Impossible de charger les systèmes du serveur.");
      if (getGuildId() !== guildId) return;
      activeGuild = guildId;
      values = data.systems || data;
      render();
    } catch (error) {
      notify(error.message || "Impossible de charger les systèmes.", true);
    } finally {
      loading = false;
    }
  }

  async function toggle(feature, button){
    const guildId = getGuildId();
    if (!guildId || !values || guildId !== activeGuild) return;
    const key = feature === "economy" ? "economy_enabled" : "levels_enabled";
    const next = !Boolean(values[key]);
    const all = document.querySelectorAll("#sentrixSystemFeatures [data-system-feature]");
    all.forEach(item => item.disabled = true);
    try {
      const response = await fetch(`/api/guilds/${guildId}/systems`, {
        method:"PUT",
        credentials:"same-origin",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},
        body:JSON.stringify({[key]:next})
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Modification impossible.");
      values = data.systems;
      render();
      notify(data.message || "Système mis à jour.");
    } catch (error) {
      notify(error.message || "Modification impossible.", true);
    } finally {
      document.querySelectorAll("#sentrixSystemFeatures [data-system-feature]").forEach(item => item.disabled = false);
    }
  }

  let lastSeen = "";
  const tick = () => {
    const guildId = getGuildId();
    if (!guildId) {
      activeGuild = "";
      values = null;
      document.getElementById("sentrixSystemFeatures")?.remove();
      lastSeen = "";
      return;
    }
    if (guildId !== lastSeen || guildId !== activeGuild) {
      lastSeen = guildId;
      values = null;
      load(guildId);
      return;
    }
    if (values) render();
  };

  setInterval(tick, 700);
  window.addEventListener("pageshow", tick);
  setTimeout(tick, 150);
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-system-features-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", SYSTEMS_CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", SYSTEMS_JS + "\n</body>", 1)
    return html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard.build_app

    async def get_systems(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, _guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        systems = await get_system_features(request.app["bot"].db, guild_id, fresh=True)
        return web.json_response({"ok": True, "systems": systems})

    async def put_systems(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        try:
            payload = await request.json()
        except Exception:
            return dashboard._json_error("Le formulaire envoyé est invalide.", 400)
        if not isinstance(payload, dict):
            return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

        allowed = {"economy_enabled": "economy", "levels_enabled": "levels"}
        updates = [(key, feature, payload[key]) for key, feature in allowed.items() if key in payload]
        if not updates:
            return dashboard._json_error("Aucun système reconnu à modifier.", 400)
        if len(updates) > 2:
            return dashboard._json_error("Trop de réglages envoyés.", 400)

        db = request.app["bot"].db
        systems = await get_system_features(db, guild_id, fresh=True)
        changed = []
        for key, feature, raw in updates:
            if raw not in (True, False, 0, 1):
                return dashboard._json_error(f"La valeur {key} doit être activée ou désactivée.", 400)
            systems = await set_system_feature(db, guild_id, feature, bool(raw))
            changed.append(feature)

        labels = []
        if "economy" in changed:
            labels.append("argent/boutiques")
        if "levels" in changed:
            labels.append("niveaux/XP")
        logger.info(
            "Dashboard : %s (%s) a modifié %s sur %s (%s).",
            session["user"].get("username"), session["user"].get("id"),
            ", ".join(labels), guild.name, guild.id,
        )
        return web.json_response({
            "ok": True,
            "systems": systems,
            "message": "Réglage appliqué immédiatement : " + ", ".join(labels) + ".",
        })

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/systems", get_systems)
        app.router.add_put("/api/guilds/{guild_id}/systems", put_systems)
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Interrupteurs Argent/Niveaux ajoutés au dashboard stable.")
