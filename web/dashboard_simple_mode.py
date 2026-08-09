"""Mode simplifié du dashboard SentriX.

Cette couche ne remplace aucune API et ne monkey-patch aucune fonction métier. Elle ajoute
uniquement une page d'accueil guidée dans /app, activée par défaut pour les nouveaux
navigateurs. Le dashboard historique reste accessible avec « Mode avancé ».
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
  .sx-simple-result{width:100%;text-align:left;border:1px solid var(--line);border-radius:11px;padding:11px 13px;background:#0d111c;color:var(--text);cursor:pointer}
  .sx-simple-result:hover{border-color:#4d5778;background:#121726}
  .sx-simple-result b,.sx-simple-result span{display:block}
  .sx-simple-result span{color:var(--muted);font-size:12px;margin-top:3px}
  .sx-simple-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}
  .sx-simple-card{border:1px solid var(--line);border-radius:15px;padding:18px;background:var(--panel);display:grid;gap:11px;align-content:space-between;min-height:154px}
  .sx-simple-card h3{margin:0 0 5px;font-size:17px}
  .sx-simple-card p{margin:0;color:var(--muted);line-height:1.5;font-size:13px}
  .sx-simple-card .btn{justify-self:start}
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
  @media(max-width:980px){
    #sxSimpleControls{grid-template-columns:1fr auto;margin:10px 0}
    #sxSimpleControls .sx-simple-mode-row{display:flex}
    body.sx-simple-advanced #navigation{display:flex}
    .sx-simple-grid{grid-template-columns:1fr 1fr}
  }
  @media(max-width:680px){
    .sx-simple-grid,.sx-simple-step-list,.sx-simple-advanced-grid{grid-template-columns:1fr}
    .sx-simple-search{grid-template-columns:1fr}
    .sx-simple-hero{padding:18px}
    #sxSimpleControls{grid-template-columns:1fr}
  }
</style>
"""


SIMPLE_JS = r"""
<script id="sentrix-simple-dashboard-js">
(() => {
  "use strict";
  if (window.__sentrixSimpleDashboard) return;
  window.__sentrixSimpleDashboard = true;

  const MODE_KEY = "sentrix_dashboard_mode_v1";
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

  const byId = id => document.getElementById(id);
  function guildId(){
    try { return typeof state !== "undefined" && state.guildId ? String(state.guildId) : ""; }
    catch (_) { return ""; }
  }
  function isAdvanced(){ return localStorage.getItem(MODE_KEY) === "advanced"; }
  function setMode(mode){
    localStorage.setItem(MODE_KEY, mode);
    applyMode();
  }
  function destination(id){ return destinations.find(item => item.id === id); }
  function openDestination(item){
    if (!item) return;
    const gid = guildId();
    if (item.page) {
      const suffix = gid ? "?guild=" + encodeURIComponent(gid) : "";
      location.href = item.page + suffix;
      return;
    }
    if (!gid) {
      const status = byId("sxSimpleMessage");
      if (status) status.textContent = "Choisissez d'abord un serveur en haut à droite.";
      return;
    }
    const button = document.querySelector('#navigation [data-tab="' + item.tab + '"]');
    if (!button) return;
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
    if (simpleButton) simpleButton.disabled = !advanced;
    if (advancedButton) advancedButton.disabled = advanced;
  }
  function renderSearch(query){
    const box = byId("sxSimpleResults");
    if (!box) return;
    const value = String(query || "").trim().toLocaleLowerCase("fr");
    if (!value) { box.innerHTML = ""; return; }
    const matches = destinations.filter(item => (item.title + " " + item.desc + " " + item.keywords).toLocaleLowerCase("fr").includes(value)).slice(0,7);
    box.innerHTML = matches.length ? matches.map(item => '<button type="button" class="sx-simple-result" data-sx-destination="'+item.id+'"><b>'+escapeHtml(item.title)+'</b><span>'+escapeHtml(item.desc)+'</span></button>').join("") : '<div class="sx-simple-hint">Aucun réglage trouvé. Essayez par exemple : tickets, sécurité, logs, IA, recours.</div>';
  }
  function escapeHtml(value){
    return String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  }
  function build(){
    const dashboard = byId("dashboard");
    const workspace = dashboard && dashboard.querySelector(".workspace");
    const head = workspace && workspace.querySelector(".workspace-head");
    const nav = byId("navigation");
    if (!workspace || !head || !nav || byId("sxSimpleHome")) return false;

    const controls = document.createElement("div");
    controls.id = "sxSimpleControls";
    controls.innerHTML = '<button class="btn primary" id="sxSimpleHomeButton" type="button">Accueil simple</button><div class="sx-simple-mode-row"><button class="btn" id="sxUseSimple" type="button">Mode simple</button><button class="btn" id="sxUseAdvanced" type="button">Mode avancé</button></div>';
    nav.parentNode.insertBefore(controls, nav);

    const home = document.createElement("section");
    home.id = "sxSimpleHome";
    home.className = "hidden";
    home.innerHTML = `<div class="sx-simple-hero"><div class="sx-simple-kicker">Dashboard simplifié</div><h2>Que voulez-vous faire ?</h2><p id="sxSimpleMessage">Choisissez un serveur puis une action.</p><div class="sx-simple-search"><input id="sxSimpleSearch" type="search" autocomplete="off" placeholder="Rechercher : tickets, sécurité, logs, IA, recours..."><button class="btn" id="sxSimpleSearchClear" type="button">Effacer</button></div><div class="sx-simple-results" id="sxSimpleResults"></div></div><div class="sx-simple-steps"><div class="sx-simple-steps-head"><h3>Configuration recommandée en 3 étapes</h3><span class="sx-simple-hint">Pour un nouveau serveur</span></div><div class="sx-simple-step-list"><button class="sx-simple-step" type="button" data-sx-destination="security"><b>1. Sécurité</b><span>Activez les protections principales.</span></button><button class="sx-simple-step" type="button" data-sx-destination="welcome"><b>2. Accueil</b><span>Configurez l'arrivée des membres.</span></button><button class="sx-simple-step" type="button" data-sx-destination="tickets"><b>3. Tickets</b><span>Préparez le support du serveur.</span></button></div></div><div class="sx-simple-grid"><article class="sx-simple-card"><div><div class="sx-simple-kicker">Protection</div><h3>Sécurité</h3><p>Anti-spam, anti-liens, anti-raid, anti-nuke et autres protections.</p></div><button class="btn primary" type="button" data-sx-destination="security">Configurer</button></article><article class="sx-simple-card"><div><div class="sx-simple-kicker">Staff</div><h3>Modération</h3><p>Consultez les sanctions et gérez rapidement les membres sanctionnés.</p></div><button class="btn primary" type="button" data-sx-destination="sanctions">Ouvrir</button></article><article class="sx-simple-card"><div><div class="sx-simple-kicker">Communauté</div><h3>Accueil et tickets</h3><p>Configurez l'arrivée des membres puis le système de support.</p></div><div><button class="btn" type="button" data-sx-destination="welcome">Accueil</button> <button class="btn" type="button" data-sx-destination="tickets">Tickets</button></div></article><article class="sx-simple-card"><div><div class="sx-simple-kicker">Fonctions</div><h3>IA et notifications</h3><p>Réglez l'IA SentriX et les notifications de vos réseaux.</p></div><div><button class="btn" type="button" data-sx-destination="ai">IA</button> <button class="btn" type="button" data-sx-destination="notifications">Notifications</button></div></article></div><details class="sx-simple-advanced"><summary>Outils avancés</summary><div class="sx-simple-advanced-grid"><button class="btn" type="button" data-sx-destination="setup">Configuration complète</button><button class="btn" type="button" data-sx-destination="operations">Outils staff</button><button class="btn" type="button" data-sx-destination="enterprise">Recours, Modmail et sauvegardes</button></div></details><div class="sx-simple-hint">Besoin d'un réglage précis ? Utilisez la recherche ci-dessus ou passez en Mode avancé pour retrouver tous les onglets historiques.</div>`;
    head.insertAdjacentElement("afterend", home);

    const back = document.createElement("button");
    back.id = "sxSimpleBack";
    back.className = "btn";
    back.type = "button";
    back.textContent = "Retour à l'accueil simple";
    home.insertAdjacentElement("afterend", back);

    dashboard.addEventListener("click", event => {
      const target = event.target.closest("[data-sx-destination]");
      if (target) openDestination(destination(target.dataset.sxDestination));
    });
    byId("sxSimpleHomeButton").addEventListener("click", showHome);
    byId("sxSimpleBack").addEventListener("click", showHome);
    byId("sxUseSimple").addEventListener("click", () => setMode("simple"));
    byId("sxUseAdvanced").addEventListener("click", () => setMode("advanced"));
    byId("sxSimpleSearch").addEventListener("input", event => renderSearch(event.target.value));
    byId("sxSimpleSearchClear").addEventListener("click", () => { const input=byId("sxSimpleSearch"); input.value=""; renderSearch(""); input.focus(); });
    byId("serverSelect").addEventListener("change", () => setTimeout(() => { if (!isAdvanced()) showHome(); }, 250));

    let lastGuildId = guildId();
    setInterval(() => {
      const currentGuildId = guildId();
      if (currentGuildId === lastGuildId) return;
      lastGuildId = currentGuildId;
      if (!isAdvanced() && !document.body.classList.contains("sx-simple-detail")) showHome();
    }, 600);

    applyMode();
    return true;
  }

  function start(){
    if (build()) return;
    let tries = 0;
    const timer = setInterval(() => { tries += 1; if (build() || tries > 40) clearInterval(timer); }, 250);
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
    logger.info("Dashboard simplifié SentriX installé (mode simple par défaut).")
