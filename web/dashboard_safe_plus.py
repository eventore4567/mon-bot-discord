"""Enrichissement sûr du dashboard principal SentriX.

Cette couche ajoute davantage de détails, d'indicateurs et d'accès rapides sans remplacer
les fonctions JavaScript critiques du dashboard (selectGuild, renderTab, fetch, save...).
Elle est volontairement passive : elle lit l'état déjà chargé et déclenche uniquement les
boutons natifs existants.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.safe-plus")
_INSTALLED = False


SAFE_PLUS_CSS = r"""
<style id="sentrix-safe-plus-css">
  #sentrixSafeOverview{margin:0 0 22px;border:1px solid #2b3150;border-radius:20px;background:linear-gradient(145deg,#121725,#0c101a);box-shadow:0 22px 60px #0005;overflow:hidden}
  .sx-safe-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:22px 22px 17px;border-bottom:1px solid #252b42;background:radial-gradient(circle at 12% -50%,#6f5cff30,transparent 45%)}
  .sx-safe-kicker{font-size:11px;letter-spacing:.1em;text-transform:uppercase;font-weight:850;color:#978cff;margin-bottom:7px}
  .sx-safe-title{font-size:22px;font-weight:900;letter-spacing:-.035em;color:#f7f5ff}
  .sx-safe-sub{margin-top:6px;color:#929bb2;font-size:13px;line-height:1.5}
  .sx-safe-health{min-width:126px;text-align:center;border:1px solid #343b59;border-radius:15px;padding:11px 13px;background:#0b0f19}
  .sx-safe-health strong{display:block;font-size:27px;line-height:1;color:#e9e6ff}.sx-safe-health span{display:block;margin-top:6px;font-size:11px;color:#8e97ad;text-transform:uppercase;letter-spacing:.07em;font-weight:800}
  .sx-safe-body{padding:18px 22px 22px;display:grid;gap:16px}
  .sx-safe-statuses{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
  .sx-safe-status{border:1px solid #252c43;border-radius:13px;background:#0c111c;padding:12px 13px;min-width:0}
  .sx-safe-status small{display:block;color:#768097;font-size:10px;text-transform:uppercase;letter-spacing:.07em;font-weight:850;margin-bottom:6px}
  .sx-safe-status b{display:block;font-size:13px;color:#eef0fb;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .sx-safe-status.good b{color:#76dfb4}.sx-safe-status.warn b{color:#f0c26c}.sx-safe-status.bad b{color:#ff8c9d}
  .sx-safe-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
  .sx-safe-metric{border:1px solid #242b40;border-radius:13px;background:#0b0f18;padding:14px}
  .sx-safe-metric span{display:block;color:#858ea3;font-size:11px;margin-bottom:7px}.sx-safe-metric strong{display:block;font-size:20px;color:#f3f4ff;letter-spacing:-.025em}
  .sx-safe-grid{display:grid;grid-template-columns:1.05fr .95fr;gap:12px}
  .sx-safe-card{border:1px solid #252c43;border-radius:15px;background:#0c111c;padding:16px}
  .sx-safe-card h3{font-size:14px;margin:0 0 12px;color:#f2f3ff}.sx-safe-card p{margin:0;color:#8f98ad;font-size:12px;line-height:1.55}
  .sx-safe-progress{height:8px;border-radius:999px;background:#20263a;overflow:hidden;margin:11px 0 8px}.sx-safe-progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#725fff,#9b8cff,#58d6a5);border-radius:999px;transition:width .25s ease}
  .sx-safe-row{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:8px;color:#8e97ad;font-size:12px}.sx-safe-row b{color:#e9ebf7}
  .sx-safe-missing{display:grid;gap:7px;margin-top:10px}.sx-safe-missing div{display:flex;align-items:center;gap:8px;font-size:12px;color:#a3aabd}.sx-safe-missing i{width:7px;height:7px;border-radius:50%;background:#f0b861;flex:0 0 auto}.sx-safe-missing .ok i{background:#57d39f}.sx-safe-missing .ok{color:#86cdb0}
  .sx-safe-actions{display:flex;flex-wrap:wrap;gap:8px}.sx-safe-action{border:1px solid #303853;border-radius:10px;background:#151b2a;color:#e7e9f5;padding:9px 11px;font-size:12px;font-weight:750;cursor:pointer;transition:.16s}.sx-safe-action:hover{border-color:#7062d8;transform:translateY(-1px)}.sx-safe-action.primary{background:linear-gradient(135deg,#7460ec,#5d4bc9);border-color:#8172ec;color:white}.sx-safe-action.link{text-decoration:none;display:inline-flex;align-items:center}
  .sx-safe-foot{display:flex;justify-content:space-between;gap:12px;align-items:center;color:#707991;font-size:11px;padding-top:2px}.sx-safe-foot code{color:#aaa4c8;background:#171c2b;border:1px solid #282f48;border-radius:7px;padding:3px 6px}
  @media(max-width:1050px){.sx-safe-statuses,.sx-safe-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.sx-safe-grid{grid-template-columns:1fr}}
  @media(max-width:620px){.sx-safe-head{flex-direction:column}.sx-safe-health{width:100%}.sx-safe-statuses,.sx-safe-metrics{grid-template-columns:1fr 1fr}.sx-safe-body{padding:15px}.sx-safe-head{padding:18px}.sx-safe-foot{align-items:flex-start;flex-direction:column}}
  @media(max-width:430px){.sx-safe-statuses,.sx-safe-metrics{grid-template-columns:1fr}}
</style>
"""


SAFE_PLUS_JS = r"""
<script id="sentrix-safe-plus-js">
(() => {
  "use strict";
  if (window.__sentrixSafePlus) return;
  window.__sentrixSafePlus = true;

  let publicData = null;
  let lastSignature = "";
  let publicLoading = false;

  const htmlEscape = value => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
  const formatNumber = value => Number(value || 0).toLocaleString("fr-FR");

  function readState() {
    try {
      if (typeof state === "undefined") return null;
      return state;
    } catch (_) {
      return null;
    }
  }

  async function refreshPublic() {
    if (publicLoading) return;
    publicLoading = true;
    try {
      const response = await fetch("/api/public", {cache:"no-store", credentials:"same-origin"});
      if (response.ok) publicData = await response.json();
    } catch (_) {
      // L'interface principale gère déjà les erreurs réseau.
    } finally {
      publicLoading = false;
    }
  }

  function configured(value) {
    return value !== null && value !== undefined && value !== "" && value !== 0 && value !== "0";
  }

  function scoreData(data) {
    const settings = data.settings || {};
    const automod = data.automod || {};
    const ai = data.ai || {};
    const essentials = [
      ["Préfixe", settings.prefix],
      ["Rôle modérateur", settings.mod_role],
      ["Rôle administrateur", settings.admin_role],
      ["Rôle membre", settings.member_role],
      ["Salon règlement", settings.rules_channel],
      ["Salon bienvenue", settings.welcome_channel],
      ["Salon logs modération", settings.log_moderation || settings.log_channel],
      ["Logs tickets", settings.ticket_log_channel],
      ["Catégorie tickets", settings.ticket_category],
      ["Salon commandes", settings.bot_commands_channel]
    ];
    const essentialDone = essentials.filter(item => configured(item[1])).length;
    const automodKeys = ["antispam","antilink","antiinvite","antimention","anticaps","antiemoji","antiraid","antibot","antiaccount","antiscam","antinuke","escalation"];
    const automodDone = automodKeys.filter(key => Number(automod[key]) === 1).length;
    const logKeys = ["log_server","log_messages","log_members","log_voice","log_roles","log_moderation","log_automod","ticket_log_channel"];
    const logDone = logKeys.filter(key => configured(settings[key])).length;
    const aiReady = Number(ai.enabled || 0) === 1;

    // Pondération : configuration 50 %, sécurité 25 %, logs 20 %, IA 5 %.
    const score = Math.round(
      (essentialDone / essentials.length) * 50 +
      (automodDone / automodKeys.length) * 25 +
      (logDone / logKeys.length) * 20 +
      (aiReady ? 5 : 0)
    );
    return {score, essentials, essentialDone, automodDone, automodTotal:automodKeys.length, logDone, logTotal:logKeys.length, aiReady};
  }

  function statusClass(ok, partial=false) {
    if (ok) return "good";
    if (partial) return "warn";
    return "bad";
  }

  function tabButton(tab) {
    return document.querySelector(`#navigation button[data-tab="${tab}"]`);
  }

  function goTab(tab) {
    const button = tabButton(tab);
    if (button) button.click();
    else if (typeof toast === "function") toast("Cet onglet n'est pas disponible sur cette version du dashboard.", true);
  }

  function render() {
    const s = readState();
    const content = document.getElementById("serverContent");
    if (!s || !content || !s.guildData || !s.guildId || content.classList.contains("hidden")) return;

    const data = s.guildData;
    const score = scoreData(data);
    const metrics = data.metrics || {};
    const guild = data.guild || {};
    const signature = [
      s.guildId, score.score, metrics.commands_24h, metrics.open_tickets, metrics.warnings,
      guild.members, guild.roles_count, guild.channels_count, publicData?.online, publicData?.latency_ms
    ].join(":");
    if (signature === lastSignature && document.getElementById("sentrixSafeOverview")) return;
    lastSignature = signature;

    let root = document.getElementById("sentrixSafeOverview");
    if (!root) {
      root = document.createElement("section");
      root.id = "sentrixSafeOverview";
      content.insertBefore(root, content.firstChild);
    }

    const missing = score.essentials.filter(item => !configured(item[1]));
    const missingHtml = missing.length
      ? missing.slice(0, 6).map(item => `<div><i></i><span>${htmlEscape(item[0])} à configurer</span></div>`).join("")
      : '<div class="ok"><i></i><span>Les réglages essentiels sont configurés.</span></div>';

    const botOnline = publicData?.online !== false;
    const logsPartial = score.logDone > 0 && score.logDone < score.logTotal;
    const securityPartial = score.automodDone > 0 && score.automodDone < score.automodTotal;
    const botLabel = publicData ? (botOnline ? `En ligne · ${publicData.latency_ms ?? "—"} ms` : "Connexion en cours") : "Vérification…";

    root.innerHTML = `
      <div class="sx-safe-head">
        <div>
          <div class="sx-safe-kicker">SentriX · Vue détaillée</div>
          <div class="sx-safe-title">${htmlEscape(guild.name || "Serveur")}</div>
          <div class="sx-safe-sub">État du bot, configuration, sécurité, logs et activité du serveur en un seul aperçu.</div>
        </div>
        <div class="sx-safe-health"><strong>${score.score}%</strong><span>Configuration</span></div>
      </div>
      <div class="sx-safe-body">
        <div class="sx-safe-statuses">
          <div class="sx-safe-status ${statusClass(botOnline)}"><small>SentriX</small><b>${htmlEscape(botLabel)}</b></div>
          <div class="sx-safe-status ${statusClass(score.automodDone === score.automodTotal, securityPartial)}"><small>Sécurité</small><b>${score.automodDone}/${score.automodTotal} protections actives</b></div>
          <div class="sx-safe-status ${statusClass(score.logDone === score.logTotal, logsPartial)}"><small>Journalisation</small><b>${score.logDone}/${score.logTotal} logs reliés</b></div>
          <div class="sx-safe-status ${statusClass(score.aiReady)}"><small>Intelligence artificielle</small><b>${score.aiReady ? "Activée" : "Désactivée"}</b></div>
        </div>

        <div class="sx-safe-metrics">
          <div class="sx-safe-metric"><span>Membres</span><strong>${formatNumber(guild.members)}</strong></div>
          <div class="sx-safe-metric"><span>Commandes · 24 h</span><strong>${formatNumber(metrics.commands_24h)}</strong></div>
          <div class="sx-safe-metric"><span>Tickets ouverts</span><strong>${formatNumber(metrics.open_tickets)}</strong></div>
          <div class="sx-safe-metric"><span>Avertissements</span><strong>${formatNumber(metrics.warnings)}</strong></div>
          <div class="sx-safe-metric"><span>Profils XP</span><strong>${formatNumber(metrics.profiles)}</strong></div>
          <div class="sx-safe-metric"><span>Comptes économie</span><strong>${formatNumber(metrics.economy_accounts)}</strong></div>
          <div class="sx-safe-metric"><span>Rôles</span><strong>${formatNumber(guild.roles_count)}</strong></div>
          <div class="sx-safe-metric"><span>Salons</span><strong>${formatNumber(guild.channels_count)}</strong></div>
        </div>

        <div class="sx-safe-grid">
          <div class="sx-safe-card">
            <h3>Qualité de configuration</h3>
            <p>Score calculé à partir des réglages essentiels, de l'AutoMod, des salons de logs et de l'IA.</p>
            <div class="sx-safe-progress"><i style="width:${Math.max(0,Math.min(100,score.score))}%"></i></div>
            <div class="sx-safe-row"><span>Réglages essentiels</span><b>${score.essentialDone}/${score.essentials.length}</b></div>
            <div class="sx-safe-row"><span>Protections AutoMod</span><b>${score.automodDone}/${score.automodTotal}</b></div>
            <div class="sx-safe-row"><span>Salons de logs</span><b>${score.logDone}/${score.logTotal}</b></div>
          </div>
          <div class="sx-safe-card">
            <h3>À terminer</h3>
            <p>Les points importants encore manquants sont affichés ici pour finir la configuration plus vite.</p>
            <div class="sx-safe-missing">${missingHtml}</div>
          </div>
        </div>

        <div class="sx-safe-card">
          <h3>Accès rapides</h3>
          <div class="sx-safe-actions">
            <button class="sx-safe-action primary" type="button" data-sx-tab="security">Sécurité</button>
            <button class="sx-safe-action" type="button" data-sx-tab="tickets">Tickets</button>
            <button class="sx-safe-action" type="button" data-sx-tab="sanctions">Sanctions</button>
            <button class="sx-safe-action" type="button" data-sx-tab="logs">Logs</button>
            <button class="sx-safe-action" type="button" data-sx-tab="ai">IA</button>
            <button class="sx-safe-action" type="button" data-sx-tab="roles">Rôles / salons</button>
            <button class="sx-safe-action" type="button" data-sx-tab="welcome">Accueil</button>
            <button class="sx-safe-action" type="button" data-sx-tab="levels">Niveaux</button>
            <a class="sx-safe-action link" href="/setup-center">Setup avancé</a>
            <a class="sx-safe-action link" href="/embed-builder">Créateur d'embeds</a>
            <button class="sx-safe-action" type="button" data-sx-refresh="1">Actualiser les données</button>
          </div>
        </div>

        <div class="sx-safe-foot">
          <span>Les actions utilisent les contrôles natifs du dashboard : aucune interception de clic critique.</span>
          <span>ID serveur : <code>${htmlEscape(guild.id || s.guildId)}</code></span>
        </div>
      </div>`;

    root.querySelectorAll("[data-sx-tab]").forEach(button => {
      button.addEventListener("click", () => goTab(button.dataset.sxTab));
    });
    const refresh = root.querySelector("[data-sx-refresh]");
    if (refresh) refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      try {
        if (typeof selectGuild === "function" && s.guildId) await selectGuild(s.guildId);
        await refreshPublic();
        lastSignature = "";
        render();
        if (typeof toast === "function") toast("Données du dashboard actualisées.");
      } catch (error) {
        if (typeof toast === "function") toast(error?.message || "Actualisation impossible.", true);
      } finally {
        refresh.disabled = false;
      }
    });
  }

  // Aucun monkey-patch : on observe uniquement le DOM et l'état existant.
  const observer = new MutationObserver(() => render());
  const start = () => {
    if (document.body) observer.observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:["class"]});
    refreshPublic().finally(() => { lastSignature = ""; render(); });
    render();
    setInterval(() => { lastSignature = ""; render(); }, 5000);
    setInterval(() => refreshPublic().then(() => { lastSignature = ""; render(); }), 30000);
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    html = dashboard.INDEX_HTML
    if 'id="sentrix-safe-plus-css"' not in html:
        html = html.replace("</head>", SAFE_PLUS_CSS + "\n</head>", 1)
    if 'id="sentrix-safe-plus-js"' not in html:
        html = html.replace("</body>", SAFE_PLUS_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Dashboard Safe Plus chargé : détails, score, diagnostics et accès rapides sans wrappers critiques.")
