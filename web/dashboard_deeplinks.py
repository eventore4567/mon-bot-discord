"""Deep links stables pour le dashboard SentriX.

Permet aux boutons Discord d'ouvrir directement le bon serveur et le bon onglet via :
/app?guild=<id>&tab=<onglet>

Le patch reste isolé du dashboard principal pour pouvoir être retiré facilement.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-deeplinks")
_INSTALLED = False


# Cette couche s'exécute côté navigateur après le script principal. Elle rend les deep links
# robustes même si le chargement OAuth/session ou le premier serveur sélectionné réinitialise
# temporairement l'onglet. La destination est conservée dans sessionStorage pendant un éventuel
# aller-retour vers Discord puis réappliquée dès que le dashboard est prêt.
DEEPLINK_RUNTIME_JS = r"""
<script id="sentrix-deeplink-runtime">
(() => {
  "use strict";
  if (window.__sentrixDeepLinkRuntime) return;
  window.__sentrixDeepLinkRuntime = true;

  const allowedTabs = new Set([
    "overview", "commands", "general", "security", "sanctions", "logs",
    "welcome", "levels", "tickets", "ai", "notifications", "roles"
  ]);
  const params = new URLSearchParams(location.search);
  const incomingTab = params.get("tab");
  const incomingGuild = params.get("guild");

  if (incomingTab && allowedTabs.has(incomingTab)) {
    sessionStorage.setItem("sentrix:deeplink:tab", incomingTab);
  }
  if (incomingGuild && /^\d{10,24}$/.test(incomingGuild)) {
    sessionStorage.setItem("sentrix:deeplink:guild", incomingGuild);
  }

  const targetTab = sessionStorage.getItem("sentrix:deeplink:tab");
  const targetGuild = sessionStorage.getItem("sentrix:deeplink:guild");
  if (!targetTab || !allowedTabs.has(targetTab)) return;

  let attempts = 0;
  let stableSince = 0;

  function applyDeepLink() {
    attempts += 1;
    const navigation = document.getElementById("navigation");
    const serverSelect = document.getElementById("serverSelect");
    const tabButton = navigation?.querySelector(`button[data-tab="${targetTab}"]`);

    // Choisit d'abord l'onglet. Le handler normal du dashboard met state.tab à jour ; ainsi,
    // même si les données du serveur sont encore en train de charger, renderTab utilisera ensuite
    // Tickets/Sécurité au lieu de revenir sur Général.
    if (tabButton && !tabButton.classList.contains("active")) {
      tabButton.click();
    }

    // Sélectionne ensuite le serveur précis depuis lequel +setup a été exécuté.
    if (serverSelect && targetGuild) {
      const optionExists = Array.from(serverSelect.options).some(option => option.value === targetGuild);
      if (optionExists && serverSelect.value !== targetGuild) {
        serverSelect.value = targetGuild;
        serverSelect.dispatchEvent(new Event("change", {bubbles: true}));
      }
    }

    const tabReady = Boolean(tabButton?.classList.contains("active"));
    const guildReady = !targetGuild || serverSelect?.value === targetGuild;
    if (tabReady && guildReady) {
      if (!stableSince) stableSince = Date.now();
      // On laisse assez de temps au fetch /api/guilds/{id} de finir avant d'oublier la cible.
      if (Date.now() - stableSince > 1400) {
        sessionStorage.removeItem("sentrix:deeplink:tab");
        sessionStorage.removeItem("sentrix:deeplink:guild");
        clearInterval(timer);
        return;
      }
    } else {
      stableSince = 0;
    }

    if (attempts >= 80) clearInterval(timer);
  }

  const timer = setInterval(applyDeepLink, 150);
  applyDeepLink();
  window.addEventListener("pageshow", applyDeepLink);
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    html = dashboard.INDEX_HTML

    # Deux destinations dédiées pour que les boutons de service puissent ouvrir un vrai aperçu
    # ou une page commandes, sans modifier les onglets existants comme Tickets et Sécurité.
    html = html.replace(
        '<button data-tab="general" class="active">Général</button>',
        '<button data-tab="overview">Aperçu</button>\n'
        '        <button data-tab="commands">Commandes</button>\n'
        '        <button data-tab="general" class="active">Général</button>',
        1,
    )

    html = html.replace(
        'const tabs={\n      general:{',
        'const tabs={\n'
        '      overview:{title:"Aperçu du serveur",description:"Résumé rapide de l’activité et de l’état de ce serveur.",readonly:true,fields:[]},\n'
        '      commands:{title:"Commandes",description:"Réglages principaux des commandes SentriX sur ce serveur.",fields:['
        '{key:"prefix",label:"Préfixe des commandes",type:"text",hint:"Entre 1 et 5 caractères. Le préfixe par défaut est +."},'
        '{key:"bot_commands_channel",label:"Salon réservé aux commandes",type:"channel",hint:"Facultatif : choisissez le salon principal utilisé pour les commandes SentriX."}'
        ']},\n'
        '      general:{',
        1,
    )

    # Un onglet en lecture seule ne doit jamais afficher le bouton Enregistrer.
    html = html.replace(
        '$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions));',
        '$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions||tab.readonly));',
        1,
    )

    # Le chemin rapide reste pris en charge directement par le chargement normal quand le HTML
    # n'a pas été transformé par une autre couche. Le runtime ci-dessous sert de deuxième garantie.
    old_load_guilds = (
        'async function loadGuilds(){const data=await json("/api/guilds");state.guilds=data.guilds;'
        'const select=$("serverSelect");select.innerHTML=\'<option value="">Choisissez un serveur</option>\'+'
        'data.guilds.map(g=>`<option value="${g.installed?esc(g.id):"invite:"+esc(g.id)}">${esc(g.name)}${g.installed?"":" — ajouter SentriX"}</option>`).join("");'
        'const first=data.guilds.find(g=>g.installed);if(first){select.value=first.id;await selectGuild(first.id);}}'
    )
    new_load_guilds = (
        'async function loadGuilds(){const data=await json("/api/guilds");state.guilds=data.guilds;'
        'const select=$("serverSelect");select.innerHTML=\'<option value="">Choisissez un serveur</option>\'+'
        'data.guilds.map(g=>`<option value="${g.installed?esc(g.id):"invite:"+esc(g.id)}">${esc(g.name)}${g.installed?"":" — ajouter SentriX"}</option>`).join("");'
        'const params=new URLSearchParams(location.search);const requestedTab=params.get("tab");'
        'if(requestedTab&&tabs[requestedTab])state.tab=requestedTab;'
        'const requestedGuild=params.get("guild");'
        'const preferred=data.guilds.find(g=>g.installed&&String(g.id)===String(requestedGuild));'
        'const first=preferred||data.guilds.find(g=>g.installed);'
        '$("navigation").querySelectorAll("button[data-tab]").forEach(x=>x.classList.toggle("active",x.dataset.tab===state.tab));'
        'if(first){select.value=first.id;await selectGuild(first.id);}}'
    )
    html = html.replace(old_load_guilds, new_load_guilds, 1)

    # Quand l'utilisateur change d'onglet dans le dashboard, l'URL reste partageable.
    old_nav = (
        '$("navigation").addEventListener("click",e=>{const button=e.target.closest("button[data-tab]");'
        'if(!button)return;state.tab=button.dataset.tab;$("navigation").querySelectorAll("button").forEach(x=>x.classList.toggle("active",x===button));renderTab();});'
    )
    new_nav = (
        '$("navigation").addEventListener("click",e=>{const button=e.target.closest("button[data-tab]");'
        'if(!button)return;state.tab=button.dataset.tab;$("navigation").querySelectorAll("button").forEach(x=>x.classList.toggle("active",x===button));'
        'const params=new URLSearchParams(location.search);params.set("tab",state.tab);if(state.guildId)params.set("guild",state.guildId);'
        'history.replaceState({},"",`${location.pathname}?${params}`);renderTab();});'
    )
    html = html.replace(old_nav, new_nav, 1)

    # En sélectionnant un autre serveur, le deep link suit également ce serveur.
    html = html.replace(
        'state.guildId=value;$("serverContent").classList.add("loading");',
        'state.guildId=value;const deepParams=new URLSearchParams(location.search);deepParams.set("guild",value);deepParams.set("tab",state.tab);history.replaceState({},"",`${location.pathname}?${deepParams}`);$("serverContent").classList.add("loading");',
        1,
    )

    # Toujours injecté en dernier : ce script ne dépend pas de la réussite des remplacements ci-dessus.
    if 'id="sentrix-deeplink-runtime"' not in html:
        html = html.replace("</body>", f"{DEEPLINK_RUNTIME_JS}\n</body>", 1)

    dashboard.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Deep links robustes du dashboard SentriX chargés.")
