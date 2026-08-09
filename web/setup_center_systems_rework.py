"""Rework visuel du Centre Setup + déplacement des interrupteurs globaux.

Les interrupteurs Argent/Boutiques et Niveaux/XP vivent ici, pas sur l'accueil du
dashboard principal. Cette couche ne touche pas aux routes API : elle réutilise
/api/guilds/{guild_id}/systems fourni par dashboard_system_features.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.setup-rework")
_INSTALLED = False


REWORK_CSS = r"""
<style id="sentrix-setup-semi2d-rework">
  /* Rework semi-2D : rectangles nets, profondeur légère, pas de grosses cartes rondes. */
  body{background:linear-gradient(180deg,#080a10 0%,#0a0d15 48%,#080a10 100%)!important}
  .top{background:#090c13f2!important;border-bottom:1px solid #242b3e!important;box-shadow:0 8px 24px #0005}
  main{max-width:1380px!important;padding-top:26px!important}
  .head{background:linear-gradient(180deg,#121725,#0d111c);border:1px solid #262e44;border-radius:14px;padding:20px 22px;box-shadow:0 6px 0 #070910,0 18px 40px #0004;margin-bottom:26px!important}
  .head h1{font-size:30px!important;letter-spacing:-.025em}.head p{line-height:1.55}

  .tabs{display:grid!important;grid-template-columns:repeat(4,minmax(170px,1fr));gap:13px!important;overflow:visible!important;margin:22px 0 25px!important}
  .tab{min-height:76px!important;white-space:normal!important;text-align:left!important;padding:15px 17px!important;border-radius:12px!important;border:1px solid #303951!important;background:linear-gradient(180deg,#1a2030,#111624)!important;color:#e9ecf8!important;box-shadow:0 5px 0 #080b12,0 12px 24px #0003!important;transition:transform .12s ease,box-shadow .12s ease,border-color .12s ease!important;font-size:14px!important}
  .tab:hover{transform:translateY(-1px);border-color:#657198!important}
  .tab.active{background:linear-gradient(180deg,#7667f5,#5949cc)!important;border-color:#9389ff!important;box-shadow:0 5px 0 #352b83,0 14px 28px #0004!important;color:#fff!important}
  .tab:active,.tab.active:active{transform:translateY(3px)!important;box-shadow:0 2px 0 #252b3e!important}

  .panel{border-radius:14px!important;background:#0f1420!important;border:1px solid #283047!important;box-shadow:0 7px 0 #070910,0 22px 45px #0004!important}
  .panel-head{background:linear-gradient(180deg,#161c2a,#111623);padding:19px 22px!important}
  .panel-head h2{font-size:20px!important}.panel-head p{font-size:13px!important;line-height:1.5}
  .content{padding:20px!important}
  .grid{gap:14px!important}
  .card{border-radius:11px!important;background:linear-gradient(180deg,#121827,#0d121d)!important;border:1px solid #283149!important;box-shadow:0 4px 0 #090c13!important;padding:17px!important}
  .card h3{font-size:15px!important}.card p{font-size:12px!important;line-height:1.55!important}
  .field .select,.field input,.field textarea,select.select,input,textarea{border-radius:9px!important;background:#0a0f19!important;border-color:#2a334c!important}
  .check{border-radius:9px!important;background:#121827!important;box-shadow:0 3px 0 #090c13}

  .btn:not(.tab){border-radius:9px!important;background:linear-gradient(180deg,#20283a,#151b2a)!important;border:1px solid #343e59!important;box-shadow:0 3px 0 #090c13!important;transition:.12s ease!important}
  .btn:not(.tab):hover{transform:translateY(-1px);border-color:#66749a!important}
  .btn:not(.tab):active{transform:translateY(2px);box-shadow:0 1px 0 #090c13!important}
  .btn.primary:not(.tab){background:linear-gradient(180deg,#7d6eff,#5b4bd6)!important;border-color:#9186ff!important;box-shadow:0 3px 0 #382d8e!important}
  .btn.danger:not(.tab){background:linear-gradient(180deg,#4b1f2b,#31151e)!important;border-color:#7c3549!important;box-shadow:0 3px 0 #190b10!important}

  .sx-system-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
  .sx-system-tile{position:relative;display:grid;grid-template-columns:1fr auto;gap:18px;align-items:center;min-height:178px;padding:22px;border:1px solid #303a55;border-radius:12px;background:linear-gradient(180deg,#171e2d 0%,#101622 100%);box-shadow:0 6px 0 #080b12,0 18px 34px #0003;overflow:hidden}
  .sx-system-tile::before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:#7466f5}
  .sx-system-tile.off{border-color:#54303b;background:linear-gradient(180deg,#25161d,#151017)}
  .sx-system-tile.off::before{background:#d65770}
  .sx-system-icon{font-size:30px;line-height:1;margin-bottom:11px}.sx-system-tile h3{font-size:18px;margin:0 0 7px}.sx-system-tile p{margin:0;color:#9aa3ba;font-size:12px;line-height:1.58;max-width:620px}
  .sx-system-detail{display:flex;flex-wrap:wrap;gap:7px;margin-top:13px}.sx-chip{font-size:10px;font-weight:800;padding:5px 8px;border-radius:7px;border:1px solid #303a55;background:#0c111b;color:#bcc4d8}
  .sx-system-state{display:inline-flex;margin-top:13px;padding:5px 8px;border-radius:7px;border:1px solid #315f50;background:#12342b;color:#8ce6c4;font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.045em}.sx-system-state.off{border-color:#713044;background:#30151f;color:#ff9db0}
  .sx-big-toggle{width:68px;height:38px;border:1px solid #59637f;border-radius:10px;background:linear-gradient(180deg,#323b52,#20283a);box-shadow:0 4px 0 #090c13;position:relative;cursor:pointer;transition:.15s;padding:0}
  .sx-big-toggle::after{content:"";position:absolute;width:27px;height:27px;left:5px;top:5px;border-radius:7px;background:#eef1ff;box-shadow:0 2px 5px #0006;transition:.15s}
  .sx-big-toggle.on{background:linear-gradient(180deg,#7d6eff,#5949d0);border-color:#978dff;box-shadow:0 4px 0 #382e8d}.sx-big-toggle.on::after{left:35px}.sx-big-toggle:active{transform:translateY(2px);box-shadow:0 2px 0 #090c13}.sx-big-toggle:disabled{opacity:.45;cursor:not-allowed}
  .sx-system-note{grid-column:1/-1;padding:14px 16px;border:1px solid #283149;border-radius:10px;background:#0b1019;color:#8e98b0;font-size:12px;line-height:1.55}

  @media(max-width:900px){.tabs{grid-template-columns:repeat(2,minmax(0,1fr))!important}.sx-system-grid{grid-template-columns:1fr}.sx-system-note{grid-column:auto}}
  @media(max-width:560px){main{padding:18px 12px 55px!important}.head{padding:16px!important}.tabs{grid-template-columns:1fr!important}.tab{min-height:60px!important}.sx-system-tile{grid-template-columns:1fr auto;padding:17px;min-height:0}.sx-chip{display:none}}
</style>
"""


SYSTEMS_JS = r"""
<script id="sentrix-setup-systems-js">
(() => {
  "use strict";
  if (window.__sentrixSetupSystems) return;
  window.__sentrixSetupSystems = true;

  let systemValues = null;
  let systemGuild = "";
  let busy = false;

  function systemCard(feature, icon, title, description, chips, enabled){
    return `<article class="sx-system-tile ${enabled ? "" : "off"}">
      <div>
        <div class="sx-system-icon">${icon}</div>
        <h3>${title}</h3>
        <p>${description}</p>
        <div class="sx-system-detail">${chips.map(c=>`<span class="sx-chip">${c}</span>`).join("")}</div>
        <span class="sx-system-state ${enabled ? "" : "off"}">${enabled ? "Activé" : "Désactivé"}</span>
      </div>
      <button type="button" class="sx-big-toggle ${enabled ? "on" : ""}" data-sx-system="${feature}" role="switch" aria-checked="${enabled ? "true" : "false"}" title="${enabled ? "Désactiver" : "Activer"} ${title}"></button>
    </article>`;
  }

  function paintSystems(){
    if (!systemValues || !state.guildId || state.tab !== "systems") return;
    const economy = Boolean(systemValues.economy_enabled);
    const levels = Boolean(systemValues.levels_enabled);
    $("title").textContent = "Systèmes du serveur";
    $("description").textContent = "Active ou désactive complètement les grands systèmes de SentriX. Les changements sont immédiats.";
    $("content").innerHTML = `<div class="sx-system-grid">
      ${systemCard("economy","💰","Argent & boutiques","Coupe tout le système économique du serveur, y compris les boutiques. Les soldes existants restent enregistrés.",["Balance / banque","Daily & work","Paiements","Boutiques","Récompenses jeux"],economy)}
      ${systemCard("levels","📈","Niveaux & XP","Coupe les gains d'XP, les niveaux, les classements de niveau et les rôles automatiques de palier.",["XP messages","Niveaux","Classement","Rôles de palier","Progression"],levels)}
      <div class="sx-system-note"><b>Conservation des données :</b> désactiver un système ne supprime rien. En le réactivant, les anciens soldes, niveaux et réglages reviennent exactement comme avant.</div>
    </div>`;
    document.querySelectorAll("[data-sx-system]").forEach(button => button.onclick = () => toggleSystem(button.dataset.sxSystem));
  }

  window.renderSystems = async function renderSystems(){
    const guildId = String(state.guildId || "");
    if (!guildId) return;
    $("title").textContent = "Systèmes du serveur";
    $("description").textContent = "Chargement des interrupteurs globaux…";
    $("content").innerHTML = '<div class="muted">Chargement…</div>';
    if (systemGuild !== guildId) systemValues = null;
    try {
      const result = await api(`/api/guilds/${guildId}/systems`);
      if (String(state.guildId) !== guildId || state.tab !== "systems") return;
      systemGuild = guildId;
      systemValues = result.systems || result;
      paintSystems();
    } catch (error) {
      message(error.message || "Impossible de charger les systèmes.", true);
      $("content").innerHTML = '<div class="muted">Impossible de charger les systèmes pour le moment.</div>';
    }
  };

  async function toggleSystem(feature){
    if (busy || !systemValues || !state.guildId) return;
    busy = true;
    document.querySelectorAll("[data-sx-system]").forEach(button => button.disabled = true);
    const key = feature === "economy" ? "economy_enabled" : "levels_enabled";
    const next = !Boolean(systemValues[key]);
    try {
      const result = await api(`/api/guilds/${state.guildId}/systems`, {
        method:"PUT",
        headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},
        body:JSON.stringify({[key]:next})
      });
      systemValues = result.systems;
      paintSystems();
      message(result.message || "Réglage appliqué immédiatement.");
    } catch (error) {
      message(error.message || "Modification impossible.", true);
    } finally {
      busy = false;
      document.querySelectorAll("[data-sx-system]").forEach(button => button.disabled = false);
    }
  }

  /* Quand le serveur change, on force une nouvelle lecture pour ne jamais afficher
     l'état du serveur précédent pendant quelques millisecondes. */
  document.addEventListener("change", event => {
    if (event.target && event.target.id === "guild") {
      systemGuild = "";
      systemValues = null;
    }
  }, true);
})();
</script>
"""


def _rework(html: str) -> str:
    if 'id="sentrix-setup-semi2d-rework"' in html:
        return html

    # 1) Les systèmes deviennent la première page du Setup, jamais l'accueil /app.
    old_tabs = '<div class="tabs"><button class="btn tab active" data-tab="games">🎮 Mini-jeux</button><button class="btn tab" data-tab="design">🎨 Design</button><button class="btn tab" data-tab="advanced">⚙️ Setup avancé</button></div>'
    new_tabs = '<div class="tabs"><button class="btn tab active" data-tab="systems">⚡ Systèmes</button><button class="btn tab" data-tab="games">🎮 Mini-jeux</button><button class="btn tab" data-tab="design">🎨 Design</button><button class="btn tab" data-tab="advanced">⚙️ Setup avancé</button></div>'
    html = html.replace(old_tabs, new_tabs, 1)

    html = html.replace(
        '<h1>Configuration avancée</h1><p>Mini-jeux, design et outils Setup, isolés du dashboard principal.</p>',
        '<h1>Configuration du serveur</h1><p>Tous les réglages importants de SentriX sont regroupés ici, sans surcharger la page d’accueil.</p>',
        1,
    )

    html = html.replace(
        'const state={csrf:"",guilds:[],guildId:"",guildData:null,setup:null,design:null,tab:"games"};',
        'const state={csrf:"",guilds:[],guildId:"",guildData:null,setup:null,design:null,tab:"systems"};',
        1,
    )

    old_render = 'function render(){if(!state.guildId)return;if(state.tab==="games")renderGames();else if(state.tab==="design")renderDesign();else renderAdvanced();}'
    new_render = 'function render(){if(!state.guildId)return;if(state.tab==="systems")renderSystems();else if(state.tab==="games")renderGames();else if(state.tab==="design")renderDesign();else renderAdvanced();}'
    html = html.replace(old_render, new_render, 1)

    if "</head>" in html:
        html = html.replace("</head>", REWORK_CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", SYSTEMS_JS + "\n</body>", 1)
    return html


def install(setup_center) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    setup_center.SETUP_CENTER_HTML = _rework(setup_center.SETUP_CENTER_HTML)
    logger.info("Centre Setup rework : systèmes déplacés dans Setup + rectangles semi-2D.")
