"""Mode simplifié et personnalisé du dashboard SentriX.

Cette couche ne remplace aucune API et ne monkey-patch aucune fonction métier. Elle ajoute
une page d'accueil guidée dans /app, activée par défaut pour les nouveaux navigateurs,
avec favoris et récents stockés uniquement dans le navigateur. Le dashboard historique
reste accessible avec « Mode avancé ».
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard.simple-mode")
_INSTALLED = False


SIMPLE_CSS = r"""
<style id="sentrix-simple-dashboard-css">
  #sxSimpleControls{display:grid;gap:8px;margin:8px 0 14px}
  #sxSimpleControls .sx-simple-mode-row{display:grid;grid-template-columns:1fr 1fr;gap:7px}
  #sxSimpleControls button{width:100%}
  #sxSimpleHome{margin-bottom:22px}
  .sx-simple-hero{padding:24px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(145deg,#151a2a,#10141f)}
  .sx-simple-hero h2{font-size:24px;margin:0 0 7px;letter-spacing:-.025em}
  .sx-simple-hero p{margin:0;color:var(--muted);line-height:1.55}
  .sx-simple-search{margin-top:17px;display:grid;grid-template-columns:1fr auto;gap:9px}
  .sx-simple-search input{min-width:0}
  .sx-simple-results{display:grid;gap:7px;margin-top:9px}
  .sx-simple-result-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px}
  .sx-simple-result{width:100%;text-align:left;border:1px solid var(--line);border-radius:11px;padding:11px 13px;background:#0d111c;color:var(--text);cursor:pointer}
  .sx-simple-result:hover{border-color:#4d5778;background:#121726}
  .sx-simple-result b,.sx-simple-result span{display:block}
  .sx-simple-result span{color:var(--muted);font-size:12px;margin-top:3px}
  .sx-simple-pin{border:1px solid var(--line);border-radius:11px;background:#0d111c;color:var(--muted);padding:0 12px;cursor:pointer;font-weight:760;white-space:nowrap}
  .sx-simple-pin:hover,.sx-simple-pin[aria-pressed="true"]{border-color:#5865f2;color:var(--text);background:#151b31}
  .sx-simple-personal{margin-top:14px;border:1px solid var(--line);border-radius:15px;padding:16px;background:#0d111c}
  .sx-simple-personal-head{display:flex;justify-content:space-between;align-items:end;gap:12px;margin-bottom:10px}
  .sx-simple-personal-head h3{margin:0;font-size:15px}
  .sx-simple-personal-head p{margin:3px 0 0;color:var(--muted);font-size:11px}
  .sx-simple-shortcuts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .sx-simple-shortcut{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;align-items:stretch}
  .sx-simple-shortcut-main{border:1px solid #283049;border-radius:11px;padding:11px;background:#101522;color:var(--text);cursor:pointer;text-align:left;min-width:0}
  .sx-simple-shortcut-main b,.sx-simple-shortcut-main span{display:block;overflow:hidden;text-overflow:ellipsis}
  .sx-simple-shortcut-main span{color:var(--muted);font-size:11px;margin-top:3px;white-space:nowrap}
  .sx-simple-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
  .sx-simple-card{border:1px solid var(--line);border-radius:15px;padding:18px;background:var(--panel);display:grid;gap:11px;align-content:space-between;min-height:154px}
  .sx-simple-card h3{margin:0 0 5px;font-size:17px}
  .sx-simple-card p{margin:0;color:var(--muted);line-height:1.5;font-size:13px}
  .sx-simple-card-actions{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
  .sx-simple-card-actions .btn{justify-self:start}
  .sx-simple-kicker{font-size:11px;color:var(--brand2);font-weight:800;text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px}
  .sx-simple-steps{margin-top:14px;border:1px solid var(--line);border-radius:15px;padding:16px;background:#0d111c}
  .sx-simple-steps-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}
  .sx-simple-steps-head h3{margin:0;font-size:15px}
  .sx-simple-step-list{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
  .sx-simple-step{border:1px solid #283049;border-radius:11px;padding:11px;background:#101522;color:var(--text);cursor:pointer;text-align:left}
  .sx-simple-step b,.sx-simple-step span{display:block}
  .sx-simple-step span{color:var(--muted);font-size:11px;margin-top:3px;line-height:1.4}
  .sx-simple-advanced{margin-top:12px}
  .sx-simple-advanced summary{cursor:pointer;color:var(--muted);font-weight:750;padding:8px 0}
  .sx-simple-advanced-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:5px}
  .sx-simple-advanced-grid button{min-height:68px;text-align:left;justify-content:flex-start}
  #sxSimpleBack{display:none;margin-bottom:14px}
  body.sx-simple-mode.sx-simple-detail #sxSimpleBack{display:inline-flex}
  body.sx-simple-mode .nav-label{display:none}
  body.sx-simple-mode #navigation{display:none}
  body.sx-simple-mode.sx-simple-home-active #serverContent{display:none!important}
  body.sx-simple-advanced #sxSimpleHome,body.sx-simple-advanced #sxSimpleBack{display:none!important}
  body.sx-simple-advanced #navigation{display:block}
  body.sx-simple-advanced .nav-label{display:block}
  .sx-simple-hint{margin-top:12px;color:var(--muted);font-size:12px;line-height:1.5}
  .sx-simple-status{min-height:18px;margin-top:7px;color:var(--muted);font-size:11px}
  #sxSimpleHome :is(button,input,summary):focus-visible{outline:2px solid #7c8cff;outline-offset:2px}
  @media(max-width:980px){
    #sxSimpleControls{grid-template-columns:1fr auto;margin:10px 0}
    #sxSimpleControls .sx-simple-mode-row{display:flex}
    body.sx-simple-advanced #navigation{display:flex}
    .sx-simple-grid,.sx-simple-shortcuts{grid-template-columns:1fr 1fr}
  }
  @media(max-width:680px){
    .sx-simple-grid,.sx-simple-step-list,.sx-simple-advanced-grid,.sx-simple-shortcuts{grid-template-columns:1fr}
    .sx-simple-search{grid-template-columns:1fr}
    .sx-simple-result-row{grid-template-columns:1fr}
    .sx-simple-pin{min-height:40px}
    .sx-simple-hero{padding:18px}
    #sxSimpleControls{grid-template-columns:1fr}
    .sx-simple-personal-head{align-items:start;flex-direction:column}
  }
  @media(prefers-reduced-motion:reduce){#sxSimpleHome *{scroll-behavior:auto!important;transition:none!important}}
</style>
"""


SIMPLE_JS = r"""
<script id="sentrix-simple-dashboard-js">
(() => {
  "use strict";
  if (window.__sentrixSimpleDashboard) return;
  window.__sentrixSimpleDashboard = true;

  const MODE_KEY = "sentrix_dashboard_mode_v1";
  const FAVORITES_KEY = "sentrix:dashboard-favorites";
  const RECENTS_KEY = "sentrix:dashboard-recents";
  const destinations = [
    {id:"security",title:"Sécuriser le serveur",desc:"Anti-spam, anti-liens, anti-raid, anti-nuke et autres protections.",tab:"security",keywords:"securite sécurité automod spam lien raid nuke protection"},
    {id:"sanctions",title:"Gérer les sanctions",desc:"Voir les bans, mutes et avertissements puis agir sur un membre.",tab:"sanctions",keywords:"moderation modération sanction ban mute warn membre"},
    {id:"welcome",title:"Configurer l'accueil",desc:"Message de bienvenue, autorôle, vérification et arrivée des membres.",tab:"welcome",keywords:"accueil bienvenue welcome verification vérification autorole autorôle"},
    {id:"tickets",title:"Configurer les tickets",desc:"Support, logs de tickets et réglages principaux du système.",tab:"tickets",keywords:"ticket support aide formulaire transcript"},
    {id:"ai",title:"Configurer l'IA",desc:"Activer SentriX IA, modèle, limites et mémoire.",tab:"ai",keywords:"ia intelligence artificielle chat sentrix modèle modele"},
    {id:"notifications",title:"Notifications sociales",desc:"YouTube, TikTok, Twitch et autres notifications automatiques.",tab:"notifications",keywords:"notification youtube tiktok twitch reseaux réseaux"},
    {id:"logs",title:"Configurer les logs",desc:"Choisir les salons où SentriX enregistre les actions importantes.",tab:"logs",keywords:"logs journal salon historique"},
    {id:"roles",title:"Rôles et salons",desc:"Relier les rôles et salons du serveur aux fonctions de SentriX.",tab:"roles",keywords:"role rôle salon permissions channel"},
    {id:"setup",title:"Configuration complète",desc:"Tous les systèmes du serveur dans le centre de configuration.",page:"/setup-center",keywords:"setup configuration complet economie économie niveaux verification"},
    {id:"operations",title:"Outils staff",desc:"Profils membres, dossiers, diagnostics et outils d'exploitation.",page:"/operations",keywords:"staff operations membre dossier diagnostic commandes personnalisées"},
    {id:"enterprise",title:"Recours, Modmail et sauvegardes",desc:"Recours de bannissement, Modmail, monitoring, backups et automatisations.",page:"/enterprise",keywords:"recours appeal modmail backup sauvegarde monitoring automation"}
  ];
  const destinationIds = new Set(destinations.map(item => item.id));
  const byId = id => document.getElementById(id);
  let lastSearchMatches = [];
  let lastGuildId = "";
  let guildCheckQueued = false;

  function guildId(){
    try { return typeof state !== "undefined" && state.guildId ? String(state.guildId) : ""; }
    catch (_) { return ""; }
  }
  function destination(id){ return destinations.find(item => item.id === id); }
  function escapeHtml(value){
    return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  }
  function normalize(value){
    return String(value || "").toLocaleLowerCase("fr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim();
  }
  function safeReadList(key){
    try {
      const value = JSON.parse(localStorage.getItem(key) || "[]");
      return Array.isArray(value) ? value.filter(id => destinationIds.has(id)).slice(0, 8) : [];
    } catch (_) { return []; }
  }
  function writeList(key, values){
    try { localStorage.setItem(key, JSON.stringify(values.filter(id => destinationIds.has(id)).slice(0, 8))); }
    catch (_) {}
  }
  function favorites(){ return safeReadList(FAVORITES_KEY); }
  function recents(){ return safeReadList(RECENTS_KEY); }
  function isAdvanced(){ return localStorage.getItem(MODE_KEY) === "advanced"; }
  function setMode(mode){
    localStorage.setItem(MODE_KEY, mode);
    applyMode();
  }
  function announce(message){
    const node = byId("sxSimpleStatus");
    if (node) node.textContent = message || "";
  }
  function rememberRecent(id){
    if (!destinationIds.has(id)) return;
    writeList(RECENTS_KEY, [id, ...recents().filter(item => item !== id)].slice(0, 5));
    renderPersonalShortcuts();
  }
  function toggleFavorite(id){
    if (!destinationIds.has(id)) return;
    const current = favorites();
    const active = current.includes(id);
    writeList(FAVORITES_KEY, active ? current.filter(item => item !== id) : [id, ...current]);
    renderPersonalShortcuts();
    syncFavoriteButtons();
    const item = destination(id);
    announce(active ? `${item.title} retiré des favoris.` : `${item.title} ajouté aux favoris.`);
  }
  function favoriteButton(item, compact=false){
    const active = favorites().includes(item.id);
    const label = active ? `Retirer ${item.title} des favoris` : `Ajouter ${item.title} aux favoris`;
    const text = compact ? (active ? "Épinglé" : "Épingler") : (active ? "Retirer" : "Épingler");
    return `<button type="button" class="sx-simple-pin" data-sx-favorite="${item.id}" aria-pressed="${active ? "true" : "false"}" aria-label="${escapeHtml(label)}">${text}</button>`;
  }
  function syncFavoriteButtons(){
    const current = new Set(favorites());
    document.querySelectorAll("[data-sx-favorite]").forEach(button => {
      const item = destination(button.dataset.sxFavorite);
      if (!item) return;
      const active = current.has(item.id);
      button.setAttribute("aria-pressed", active ? "true" : "false");
      button.setAttribute("aria-label", active ? `Retirer ${item.title} des favoris` : `Ajouter ${item.title} aux favoris`);
      button.textContent = active ? "Épinglé" : "Épingler";
    });
  }
  function renderPersonalShortcuts(){
    const box = byId("sxSimpleShortcuts");
    if (!box) return;
    const favoriteIds = favorites();
    const recentIds = recents().filter(id => !favoriteIds.includes(id));
    const items = [
      ...favoriteIds.map(id => ({id,kind:"Favori"})),
      ...recentIds.slice(0, Math.max(0, 6 - favoriteIds.length)).map(id => ({id,kind:"Récent"}))
    ].slice(0, 6);
    if (!items.length) {
      box.innerHTML = '<div class="sx-simple-hint">Épinglez vos réglages les plus utilisés : ils apparaîtront ici avec vos derniers accès.</div>';
      return;
    }
    box.innerHTML = items.map(entry => {
      const item = destination(entry.id);
      if (!item) return "";
      return `<div class="sx-simple-shortcut"><button type="button" class="sx-simple-shortcut-main" data-sx-destination="${item.id}"><b>${escapeHtml(item.title)}</b><span>${entry.kind} · ${escapeHtml(item.desc)}</span></button>${favoriteButton(item,true)}</div>`;
    }).join("");
  }
  function openDestination(item){
    if (!item) return;
    const gid = guildId();
    rememberRecent(item.id);
    if (item.page) {
      const suffix = gid ? "?guild=" + encodeURIComponent(gid) : "";
      location.href = item.page + suffix;
      return;
    }
    if (!gid) {
      const status = byId("sxSimpleMessage");
      if (status) status.textContent = "Choisissez d'abord un serveur en haut à droite.";
      announce("Aucun serveur sélectionné.");
      return;
    }
    const button = document.querySelector('#navigation [data-tab="' + item.tab + '"]');
    if (!button) {
      announce("Ce réglage n'est pas disponible dans cette version du dashboard.");
      return;
    }
    document.body.classList.remove("sx-simple-home-active");
    document.body.classList.add("sx-simple-detail");
    const home = byId("sxSimpleHome");
    if (home) home.classList.add("hidden");
    button.click();
    window.scrollTo({top:0,behavior:"smooth"});
  }
  function showHome(){
    if (isAdvanced()) return;
    document.body.classList.add("sx-simple-mode","sx-simple-home-active");
    document.body.classList.remove("sx-simple-detail","sx-simple-advanced");
    const home = byId("sxSimpleHome");
    if (home) home.classList.remove("hidden");
    const message = byId("sxSimpleMessage");
    if (message) message.textContent = guildId() ? "Choisissez ce que vous voulez régler. SentriX vous emmène directement au bon endroit." : "Choisissez d'abord un serveur en haut à droite.";
    renderPersonalShortcuts();
    syncFavoriteButtons();
    window.scrollTo({top:0,behavior:"smooth"});
  }
  function applyMode(){
    const advanced = isAdvanced();
    document.body.classList.toggle("sx-simple-advanced", advanced);
    document.body.classList.toggle("sx-simple-mode", !advanced);
    if (advanced) {
      document.body.classList.remove("sx-simple-home-active","sx-simple-detail");
      const home = byId("sxSimpleHome");
      if (home) home.classList.add("hidden");
    } else {
      showHome();
    }
    const simpleButton = byId("sxUseSimple");
    const advancedButton = byId("sxUseAdvanced");
    if (simpleButton) {
      simpleButton.disabled = !advanced;
      simpleButton.setAttribute("aria-pressed", advanced ? "false" : "true");
    }
    if (advancedButton) {
      advancedButton.disabled = advanced;
      advancedButton.setAttribute("aria-pressed", advanced ? "true" : "false");
    }
  }
  function scoreDestination(item, tokens){
    const title = normalize(item.title);
    const keywords = normalize(item.keywords);
    const desc = normalize(item.desc);
    let score = 0;
    for (const token of tokens) {
      if (!token) continue;
      if (title === token) score += 12;
      else if (title.startsWith(token)) score += 8;
      else if (title.includes(token)) score += 5;
      if (keywords.split(/\s+/).includes(token)) score += 6;
      else if (keywords.includes(token)) score += 3;
      if (desc.includes(token)) score += 1;
    }
    return score;
  }
  function renderSearch(query){
    const box = byId("sxSimpleResults");
    const status = byId("sxSimpleSearchStatus");
    if (!box) return;
    const tokens = normalize(query).split(/\s+/).filter(Boolean);
    if (!tokens.length) {
      lastSearchMatches = [];
      box.innerHTML = "";
      if (status) status.textContent = "";
      return;
    }
    lastSearchMatches = destinations
      .map((item,index) => ({item,index,score:scoreDestination(item,tokens)}))
      .filter(entry => entry.score > 0)
      .sort((a,b) => b.score - a.score || a.index - b.index)
      .slice(0,7)
      .map(entry => entry.item);
    box.innerHTML = lastSearchMatches.length ? lastSearchMatches.map(item => `<div class="sx-simple-result-row"><button type="button" class="sx-simple-result" data-sx-destination="${item.id}"><b>${escapeHtml(item.title)}</b><span>${escapeHtml(item.desc)}</span></button>${favoriteButton(item,true)}</div>`).join("") : '<div class="sx-simple-hint">Aucun réglage trouvé. Essayez par exemple : tickets, sécurité, logs, IA, recours.</div>';
    if (status) status.textContent = lastSearchMatches.length ? `${lastSearchMatches.length} résultat${lastSearchMatches.length > 1 ? "s" : ""}. Entrée ouvre le premier.` : "Aucun résultat.";
  }
  function checkGuildChange(){
    guildCheckQueued = false;
    const currentGuildId = guildId();
    if (currentGuildId === lastGuildId) return;
    lastGuildId = currentGuildId;
    if (!isAdvanced()) showHome();
  }
  function scheduleGuildCheck(){
    if (guildCheckQueued) return;
    guildCheckQueued = true;
    requestAnimationFrame(checkGuildChange);
  }
  function installGuildObserver(dashboard){
    const select = byId("serverSelect");
    if (select) select.addEventListener("change", () => requestAnimationFrame(checkGuildChange));
    const target = byId("serverRail") || byId("serverList") || dashboard;
    if (target && "MutationObserver" in window) {
      const observer = new MutationObserver(scheduleGuildCheck);
      observer.observe(target,{subtree:true,childList:true,attributes:true,attributeFilter:["class","aria-selected","data-guild-id","value"]});
    }
    window.addEventListener("popstate", scheduleGuildCheck);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) scheduleGuildCheck(); });
  }
  function build(){
    const dashboard = byId("dashboard");
    const workspace = dashboard && dashboard.querySelector(".workspace");
    const head = workspace && workspace.querySelector(".workspace-head");
    const nav = byId("navigation");
    if (!workspace || !head || !nav || byId("sxSimpleHome")) return false;

    const controls = document.createElement("div");
    controls.id = "sxSimpleControls";
    controls.innerHTML = '<button class="btn primary" id="sxSimpleHomeButton" type="button">Accueil simple</button><div class="sx-simple-mode-row"><button class="btn" id="sxUseSimple" type="button" aria-pressed="false">Mode simple</button><button class="btn" id="sxUseAdvanced" type="button" aria-pressed="false">Mode avancé</button></div>';
    nav.parentNode.insertBefore(controls, nav);

    const home = document.createElement("section");
    home.id = "sxSimpleHome";
    home.className = "hidden";
    home.innerHTML = `<div class="sx-simple-hero"><div class="sx-simple-kicker">Dashboard simplifié</div><h2>Que voulez-vous faire ?</h2><p id="sxSimpleMessage">Choisissez un serveur puis une action.</p><div class="sx-simple-search"><input id="sxSimpleSearch" type="search" autocomplete="off" aria-label="Rechercher un réglage SentriX" placeholder="Rechercher : tickets, sécurité, logs, IA, recours..."><button class="btn" id="sxSimpleSearchClear" type="button">Effacer</button></div><div id="sxSimpleSearchStatus" class="sx-simple-status" role="status" aria-live="polite"></div><div class="sx-simple-results" id="sxSimpleResults"></div></div><section class="sx-simple-personal" aria-labelledby="sxSimplePersonalTitle"><div class="sx-simple-personal-head"><div><h3 id="sxSimplePersonalTitle">Vos accès rapides</h3><p>Favoris persistants et derniers réglages ouverts sur cet appareil.</p></div><span class="sx-simple-hint">Épingler = garder ici</span></div><div class="sx-simple-shortcuts" id="sxSimpleShortcuts"></div><div id="sxSimpleStatus" class="sx-simple-status" role="status" aria-live="polite"></div></section><div class="sx-simple-steps"><div class="sx-simple-steps-head"><h3>Configuration recommandée en 3 étapes</h3><span class="sx-simple-hint">Pour un nouveau serveur</span></div><div class="sx-simple-step-list"><button class="sx-simple-step" type="button" data-sx-destination="security"><b>1. Sécurité</b><span>Activez les protections principales.</span></button><button class="sx-simple-step" type="button" data-sx-destination="welcome"><b>2. Accueil</b><span>Configurez l'arrivée des membres.</span></button><button class="sx-simple-step" type="button" data-sx-destination="tickets"><b>3. Tickets</b><span>Préparez le support du serveur.</span></button></div></div><div class="sx-simple-grid"><article class="sx-simple-card"><div><div class="sx-simple-kicker">Protection</div><h3>Sécurité</h3><p>Anti-spam, anti-liens, anti-raid, anti-nuke et autres protections.</p></div><div class="sx-simple-card-actions"><button class="btn primary" type="button" data-sx-destination="security">Configurer</button><button class="btn" type="button" data-sx-favorite="security" aria-pressed="false">Épingler</button></div></article><article class="sx-simple-card"><div><div class="sx-simple-kicker">Staff</div><h3>Modération</h3><p>Consultez les sanctions et gérez rapidement les membres sanctionnés.</p></div><div class="sx-simple-card-actions"><button class="btn primary" type="button" data-sx-destination="sanctions">Ouvrir</button><button class="btn" type="button" data-sx-favorite="sanctions" aria-pressed="false">Épingler</button></div></article><article class="sx-simple-card"><div><div class="sx-simple-kicker">Communauté</div><h3>Accueil et tickets</h3><p>Configurez l'arrivée des membres puis le système de support.</p></div><div class="sx-simple-card-actions"><button class="btn" type="button" data-sx-destination="welcome">Accueil</button><button class="btn" type="button" data-sx-destination="tickets">Tickets</button></div></article><article class="sx-simple-card"><div><div class="sx-simple-kicker">Fonctions</div><h3>IA et notifications</h3><p>Réglez l'IA SentriX et les notifications de vos réseaux.</p></div><div class="sx-simple-card-actions"><button class="btn" type="button" data-sx-destination="ai">IA</button><button class="btn" type="button" data-sx-destination="notifications">Notifications</button></div></article></div><details class="sx-simple-advanced"><summary>Outils avancés</summary><div class="sx-simple-advanced-grid"><button class="btn" type="button" data-sx-destination="setup">Configuration complète</button><button class="btn" type="button" data-sx-destination="operations">Outils staff</button><button class="btn" type="button" data-sx-destination="enterprise">Recours, Modmail et sauvegardes</button></div></details><div class="sx-simple-hint">Besoin d'un réglage précis ? Utilisez la recherche ci-dessus ou passez en Mode avancé pour retrouver tous les onglets historiques. Raccourci : / pour rechercher, Cmd/Ctrl+K pour la palette globale.</div>`;
    head.insertAdjacentElement("afterend", home);

    const back = document.createElement("button");
    back.id = "sxSimpleBack";
    back.className = "btn";
    back.type = "button";
    back.textContent = "Retour à l'accueil simple";
    home.insertAdjacentElement("afterend", back);

    dashboard.addEventListener("click", event => {
      const favoriteTarget = event.target.closest("[data-sx-favorite]");
      if (favoriteTarget) {
        event.preventDefault();
        event.stopPropagation();
        toggleFavorite(favoriteTarget.dataset.sxFavorite);
        return;
      }
      const target = event.target.closest("[data-sx-destination]");
      if (target) openDestination(destination(target.dataset.sxDestination));
    });
    byId("sxSimpleHomeButton").addEventListener("click", showHome);
    byId("sxSimpleBack").addEventListener("click", showHome);
    byId("sxUseSimple").addEventListener("click", () => setMode("simple"));
    byId("sxUseAdvanced").addEventListener("click", () => setMode("advanced"));
    byId("sxSimpleSearch").addEventListener("input", event => renderSearch(event.target.value));
    byId("sxSimpleSearch").addEventListener("keydown", event => {
      if (event.key === "Enter" && lastSearchMatches.length) {
        event.preventDefault();
        openDestination(lastSearchMatches[0]);
      } else if (event.key === "Escape") {
        event.currentTarget.value = "";
        renderSearch("");
      }
    });
    byId("sxSimpleSearchClear").addEventListener("click", () => { const input=byId("sxSimpleSearch"); input.value=""; renderSearch(""); input.focus(); });
    document.addEventListener("keydown", event => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey || isAdvanced()) return;
      const active = document.activeElement;
      if (active && (active.matches("input,textarea,select") || active.isContentEditable)) return;
      event.preventDefault();
      const input = byId("sxSimpleSearch");
      if (input) { showHome(); input.focus(); }
    });

    lastGuildId = guildId();
    installGuildObserver(dashboard);
    renderPersonalShortcuts();
    syncFavoriteButtons();
    applyMode();
    return true;
  }

  function start(){
    if (build()) return;
    let tries = 0;
    const retry = () => {
      tries += 1;
      if (build() || tries > 80) return;
      requestAnimationFrame(retry);
    };
    requestAnimationFrame(retry);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    html = getattr(dashboard, "INDEX_HTML", "")
    if not isinstance(html, str) or "</body>" not in html:
        logger.warning("Mode simplifié non installé : INDEX_HTML indisponible.")
        return
    if 'id="sentrix-simple-dashboard-js"' not in html:
        if "</head>" in html:
            html = html.replace("</head>", SIMPLE_CSS + "\n</head>", 1)
        html = html.replace("</body>", SIMPLE_JS + "\n</body>", 1)
        dashboard.INDEX_HTML = html
    logger.info("Dashboard simplifié SentriX installé (favoris, récents et navigation événementielle).")