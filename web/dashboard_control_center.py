"""Centre de contrôle avancé du dashboard SentriX.

Cette couche est volontairement isolée du dashboard principal : elle ajoute uniquement de
l'interface cliente autour des API et champs déjà validés par web.dashboard. Aucun nouveau
réglage non supporté n'est écrit en base.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.control-center")
_INSTALLED = False


CONTROL_CENTER_CSS = r"""
<style id="sentrix-control-center-css">
  .sentrix-nav-search{margin:0 0 10px;width:100%;padding:10px 11px;border:1px solid var(--line,#29304a);border-radius:10px;background:#0a0e18;color:var(--text,#f3f5ff);outline:none}
  .sentrix-nav-search:focus{border-color:var(--brand,#7c6cff);box-shadow:0 0 0 3px #7c6cff1f}
  .sentrix-control-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;width:100%}
  .sentrix-control-card{appearance:none;border:1px solid #272f48;border-radius:15px;background:linear-gradient(145deg,#111725,#0d111b);padding:17px;text-align:left;color:var(--text,#f3f5ff);cursor:pointer;transition:.18s;min-height:118px;display:flex;flex-direction:column;gap:7px;text-decoration:none}
  .sentrix-control-card:hover{transform:translateY(-2px);border-color:#6f62ef;box-shadow:0 14px 34px #0005}
  .sentrix-control-card .icon{font-size:23px;line-height:1}.sentrix-control-card b{font-size:15px}.sentrix-control-card span{font-size:12px;color:var(--muted,#9ca5bc);line-height:1.45}
  .sentrix-control-card.primary{background:linear-gradient(145deg,#2b245a,#17152d);border-color:#6e5dff70}
  .sentrix-control-stats{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:4px}
  .sentrix-control-stat{padding:14px;border:1px solid #252d45;border-radius:13px;background:#0b101a}.sentrix-control-stat small{display:block;color:var(--muted,#9ca5bc);margin-bottom:5px}.sentrix-control-stat strong{font-size:20px}
  .sentrix-quickbar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin:0 0 14px}.sentrix-quickbar .btn{min-height:40px}
  .sentrix-mini-badge{font-size:11px;font-weight:800;color:#b9b1ff;background:#7c6cff18;border:1px solid #7c6cff35;border-radius:999px;padding:5px 8px;margin-left:auto}
  .overview{grid-template-columns:repeat(auto-fit,minmax(155px,1fr))!important}
  @media(max-width:1050px){.sentrix-control-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.sentrix-control-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:620px){.sentrix-control-grid,.sentrix-control-stats{grid-template-columns:1fr}.sentrix-control-card{min-height:100px}}
</style>
"""


CONTROL_CENTER_JS = r"""
<script id="sentrix-control-center-js">
(() => {
  "use strict";
  if (window.__sentrixControlCenterLoaded) return;
  window.__sentrixControlCenterLoaded = true;

  if (typeof tabs === "undefined" || typeof state === "undefined" || typeof renderTab !== "function") return;

  // Nouvelles catégories : uniquement des champs déjà autorisés et validés côté serveur.
  tabs.control = {
    title:"Centre de contrôle",
    description:"Accès rapide aux fonctions importantes de SentriX.",
    readonly:true,
    fields:[]
  };
  tabs.community = {
    title:"Communauté",
    description:"Reliez annonces, suggestions, giveaways, partenariats, statistiques et signalements aux bons salons.",
    fields:[
      {key:"announce_channel",label:"Salon des annonces",type:"channel"},
      {key:"suggest_channel",label:"Salon des suggestions",type:"channel"},
      {key:"giveaway_channel",label:"Salon des giveaways",type:"channel"},
      {key:"partner_channel",label:"Salon des partenariats",type:"channel"},
      {key:"stats_channel",label:"Salon des statistiques",type:"channel"},
      {key:"afk_channel",label:"Salon AFK",type:"channel"},
      {key:"report_channel",label:"Salon des signalements",type:"channel"}
    ]
  };
  tabs.verification = {
    title:"Vérification et membres",
    description:"Configurez l'arrivée des membres, le règlement et les rôles de vérification.",
    fields:[
      {key:"rules_channel",label:"Salon du règlement",type:"channel"},
      {key:"verification_channel",label:"Salon de vérification",type:"channel"},
      {key:"verification_role",label:"Rôle de vérification",type:"role"},
      {key:"verify_role",label:"Rôle attribué après vérification",type:"role"},
      {key:"member_role",label:"Rôle membre",type:"role"},
      {key:"booster_role",label:"Rôle booster",type:"role"}
    ]
  };
  tabs.staff = {
    title:"Équipe et modération",
    description:"Rôles du staff, rôle muet, avertissements et salons internes utiles à la modération.",
    fields:[
      {key:"admin_role",label:"Rôle administrateur",type:"role"},
      {key:"mod_role",label:"Rôle modérateur",type:"role"},
      {key:"mute_role",label:"Rôle muet",type:"role"},
      {key:"warn_role",label:"Rôle d'avertissement",type:"role"},
      {key:"report_channel",label:"Salon des signalements",type:"channel"},
      {key:"error_channel",label:"Salon des erreurs SentriX",type:"channel"},
      {key:"log_moderation",label:"Salon des logs de modération",type:"channel"}
    ]
  };

  const navigation = document.getElementById("navigation");
  if (!navigation) return;

  function makeTab(name, label, where="end") {
    if (navigation.querySelector(`button[data-tab="${name}"]`)) return;
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.tab = name;
    button.textContent = label;
    if (where === "start") navigation.insertBefore(button, navigation.firstChild);
    else navigation.appendChild(button);
  }

  makeTab("control", "Centre de contrôle", "start");
  makeTab("community", "Communauté");
  makeTab("verification", "Vérification");
  makeTab("staff", "Équipe / Staff");

  // Recherche instantanée dans tous les onglets du menu.
  if (!document.getElementById("sentrixNavSearch")) {
    const search = document.createElement("input");
    search.id = "sentrixNavSearch";
    search.className = "sentrix-nav-search";
    search.type = "search";
    search.placeholder = "Rechercher un réglage…";
    search.autocomplete = "off";
    navigation.parentNode.insertBefore(search, navigation);
    search.addEventListener("input", () => {
      const query = search.value.trim().toLocaleLowerCase("fr");
      navigation.querySelectorAll("button[data-tab]").forEach(button => {
        button.hidden = Boolean(query) && !button.textContent.toLocaleLowerCase("fr").includes(query);
      });
    });
  }

  function selectTab(name) {
    const button = navigation.querySelector(`button[data-tab="${name}"]`);
    if (button) button.click();
  }

  function ensureExtraMetrics() {
    const overview = document.querySelector("#serverContent .overview");
    if (!overview || !state.guildData) return;
    const metrics = state.guildData.metrics || {};
    const entries = [
      ["metricProfilesExtra", "Profils XP", metrics.profiles || 0],
      ["metricEconomyExtra", "Comptes économie", metrics.economy_accounts || 0]
    ];
    for (const [id, label, value] of entries) {
      let item = document.getElementById(id);
      if (!item) {
        item = document.createElement("div");
        item.id = id;
        item.className = "metric";
        item.innerHTML = `<small>${label}</small><strong>0</strong>`;
        overview.appendChild(item);
      }
      item.querySelector("strong").textContent = Number(value || 0).toLocaleString("fr-FR");
    }
  }

  function ensureQuickbar() {
    const content = document.getElementById("serverContent");
    if (!content || !state.guildData) return;
    let bar = document.getElementById("sentrixQuickbar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "sentrixQuickbar";
      bar.className = "sentrix-quickbar";
      bar.innerHTML = `
        <a class="btn" href="/setup-center">Setup avancé</a>
        <a class="btn" href="/embed-builder">Créateur d'embeds</a>
        <button class="btn" type="button" data-quick="refresh">Actualiser</button>
        <button class="btn" type="button" data-quick="copy-id">Copier l'ID serveur</button>
        <span class="sentrix-mini-badge">Centre SentriX</span>`;
      const panel = content.querySelector(".panel");
      content.insertBefore(bar, panel || null);
      bar.addEventListener("click", async event => {
        const button = event.target.closest("button[data-quick]");
        if (!button) return;
        if (button.dataset.quick === "refresh" && state.guildId) {
          button.disabled = true;
          try { await selectGuild(state.guildId); }
          finally { button.disabled = false; }
        }
        if (button.dataset.quick === "copy-id" && state.guildId) {
          try {
            await navigator.clipboard.writeText(String(state.guildId));
            if (typeof toast === "function") toast("ID du serveur copié.");
          } catch {
            if (typeof toast === "function") toast("Impossible de copier automatiquement l'ID.", true);
          }
        }
      });
    }
  }

  function controlCard(icon, title, description, tab, extra="") {
    return `<button class="sentrix-control-card ${extra}" type="button" data-control-tab="${tab}"><span class="icon">${icon}</span><b>${title}</b><span>${description}</span></button>`;
  }

  function linkCard(icon, title, description, href, extra="") {
    return `<a class="sentrix-control-card ${extra}" href="${href}"><span class="icon">${icon}</span><b>${title}</b><span>${description}</span></a>`;
  }

  function renderControlCenter() {
    if (!state.guildData) return;
    const data = state.guildData;
    const metrics = data.metrics || {};
    document.getElementById("tabTitle").textContent = "Centre de contrôle";
    document.getElementById("tabDescription").textContent = "Toutes les fonctions importantes de ce serveur au même endroit.";
    document.getElementById("saveBar").classList.add("hidden");
    const fields = document.getElementById("fields");
    fields.innerHTML = `<div class="sentrix-control-grid full">
      <div class="sentrix-control-stats">
        <div class="sentrix-control-stat"><small>Membres</small><strong>${Number(data.guild.members||0).toLocaleString("fr-FR")}</strong></div>
        <div class="sentrix-control-stat"><small>Commandes 24 h</small><strong>${Number(metrics.commands_24h||0).toLocaleString("fr-FR")}</strong></div>
        <div class="sentrix-control-stat"><small>Tickets ouverts</small><strong>${Number(metrics.open_tickets||0).toLocaleString("fr-FR")}</strong></div>
        <div class="sentrix-control-stat"><small>Avertissements</small><strong>${Number(metrics.warnings||0).toLocaleString("fr-FR")}</strong></div>
        <div class="sentrix-control-stat"><small>Profils XP</small><strong>${Number(metrics.profiles||0).toLocaleString("fr-FR")}</strong></div>
        <div class="sentrix-control-stat"><small>Comptes économie</small><strong>${Number(metrics.economy_accounts||0).toLocaleString("fr-FR")}</strong></div>
        <div class="sentrix-control-stat"><small>Rôles</small><strong>${Number(data.guild.roles_count||0).toLocaleString("fr-FR")}</strong></div>
        <div class="sentrix-control-stat"><small>Salons</small><strong>${Number(data.guild.channels_count||0).toLocaleString("fr-FR")}</strong></div>
      </div>
      ${controlCard("🛡️","Sécurité","AutoMod, anti-raid, anti-scam et anti-nuke.","security","primary")}
      ${controlCard("🎫","Tickets","Catégorie, transcripts, évaluations et logs tickets.","tickets","primary")}
      ${controlCard("📋","Sanctions","Bans, mutes, warns et actions de retrait.","sanctions")}
      ${controlCard("🧾","Logs","Choisir précisément chaque salon de journalisation.","logs")}
      ${controlCard("🤖","Intelligence artificielle","Modèle, mémoire, limites et vitesse de l'IA.","ai")}
      ${controlCard("🔔","Notifications","YouTube, TikTok, Twitch et autres sources sociales.","notifications")}
      ${controlCard("👥","Rôles et salons","Relier les rôles et salons principaux aux fonctions du bot.","roles")}
      ${controlCard("📣","Communauté","Annonces, suggestions, giveaways, partenaires et stats.","community")}
      ${controlCard("✅","Vérification","Règlement, vérification et rôles membre/booster.","verification")}
      ${controlCard("🔨","Équipe / Staff","Rôles staff, mute, warns, signalements et erreurs.","staff")}
      ${controlCard("👋","Accueil","Bienvenue, départ, image et rôle automatique.","welcome")}
      ${controlCard("📈","Niveaux","XP, multiplicateur et annonces de niveaux.","levels")}
      ${linkCard("⚙️","Setup avancé","Mini-jeux, design et réglages Setup supplémentaires.","/setup-center","primary")}
      ${linkCard("🖌️","Créateur d'embeds","Créer et envoyer des embeds Discord depuis le dashboard.","/embed-builder","primary")}
    </div>`;
    fields.querySelectorAll("[data-control-tab]").forEach(button => {
      button.addEventListener("click", () => selectTab(button.dataset.controlTab));
    });
  }

  const originalRenderTab = renderTab;
  renderTab = function sentrixRenderTab() {
    if (state.tab === "control") {
      renderControlCenter();
      return;
    }
    originalRenderTab();
    ensureExtraMetrics();
    ensureQuickbar();
  };

  const originalSelectGuild = selectGuild;
  selectGuild = async function sentrixSelectGuild(value) {
    const result = await originalSelectGuild(value);
    ensureExtraMetrics();
    ensureQuickbar();
    if (state.tab === "control" && state.guildData) renderControlCenter();
    return result;
  };

  // Si le premier serveur a fini de charger avant l'injection, enrichit quand même la page.
  let attempts = 0;
  const readyTimer = setInterval(() => {
    attempts += 1;
    if (state.guildData) {
      ensureExtraMetrics();
      ensureQuickbar();
      clearInterval(readyTimer);
    } else if (attempts > 40) clearInterval(readyTimer);
  }, 250);
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    html = dashboard.INDEX_HTML
    if 'id="sentrix-control-center-css"' not in html:
        html = html.replace("</head>", f"{CONTROL_CENTER_CSS}\n</head>", 1)
    if 'id="sentrix-control-center-js"' not in html:
        html = html.replace("</body>", f"{CONTROL_CENTER_JS}\n</body>", 1)

    dashboard.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Centre de contrôle avancé du dashboard SentriX chargé.")
