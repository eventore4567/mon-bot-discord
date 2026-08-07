"""Deep links stables pour le dashboard SentriX.

Permet aux boutons Discord d'ouvrir directement le bon serveur et le bon onglet via :
/app?guild=<id>&tab=<onglet>

Le patch reste isolé du dashboard principal pour pouvoir être retiré facilement.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-deeplinks")
_INSTALLED = False


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    html = dashboard.INDEX_HTML

    # Deux destinations dédiées pour que les boutons +setup n'arrivent plus tous sur Général.
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

    dashboard.INDEX_HTML = html
    _INSTALLED = True
    logger.info("Deep links du dashboard SentriX chargés.")
