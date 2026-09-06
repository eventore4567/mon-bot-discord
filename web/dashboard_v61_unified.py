"""SentriX V61 — dashboard unifié de type DraftBot.

Objectifs :
- une seule application visible : ``/app`` ;
- aucune navigation vers les anciens centres violets ;
- suppression de l'onglet générique « Fonctions avancées » ;
- sidebar structurée par catégories, pages cohérentes et palette V60 partout ;
- réutilisation des vraies API existantes pour Setup, mini-jeux, design, systèmes et statut.

Les anciennes pages restent disponibles uniquement comme implémentations/backend tant que
leurs routes API sont utiles. Leurs pages HTML sont redirigées vers l'onglet correspondant de
``/app`` pour éviter deux interfaces concurrentes.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from aiohttp import web

logger = logging.getLogger("bot.dashboard-v61-unified")

CSS = r'''
/* SentriX V61 — navigation et pages unifiées */
.sx-nav-group{padding:16px 17px 7px;color:#888c91;font-size:9px;font-weight:950;letter-spacing:.12em;text-transform:uppercase}
.navigation .sx-nav-group:first-child{padding-top:8px}
.navigation button[data-tab]{border-left:3px solid transparent}
.navigation button[data-tab].active{border-left-color:var(--accent);background:#292c31;color:#fff}
.topnav a[data-open-tab]{cursor:pointer}
.sx-unified-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.sx-unified-grid .full{grid-column:1/-1}
.sx-unified-card{background:#303439;border:1px solid #484d53;border-radius:7px;padding:16px}.sx-unified-card h3{margin:0 0 6px;font-size:15px}.sx-unified-card p{margin:0 0 12px;color:#aaadb0;font-size:11px;line-height:1.5}.sx-unified-card .field{margin-top:9px}
.sx-switch-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:center;background:#303439;border:1px solid #484d53;border-radius:7px;padding:16px}.sx-switch-card h3{margin:0 0 5px;font-size:15px}.sx-switch-card p{margin:0;color:#aeb0b3;font-size:11px;line-height:1.5}.sx-big-switch{position:relative;width:56px;height:30px;border:0;border-radius:999px;background:#777b80;cursor:pointer}.sx-big-switch:after{content:"";position:absolute;width:22px;height:22px;left:4px;top:4px;background:#fff;border-radius:50%;transition:.16s}.sx-big-switch.on{background:var(--accent)}.sx-big-switch.on:after{left:30px}.sx-big-switch:disabled{opacity:.5;cursor:not-allowed}
.sx-inline-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.sx-inline-actions .btn{min-width:120px}.sx-danger-zone{border-color:#75434a;background:#38262a}.sx-danger-zone h3{color:#ffb0b8}
.sx-settings-list{display:grid;gap:8px}.sx-settings-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;padding:10px;border:1px solid #484d53;background:#2c3035;border-radius:6px}.sx-settings-row b{display:block;font-size:12px}.sx-settings-row small{display:block;color:#9da0a4;margin-top:3px}
.sx-games-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.sx-games-grid .full{grid-column:1/-1}.sx-multi{min-height:135px}
.sx-design-preview{border-left:4px solid var(--preview,#d66f55);padding:14px;background:#2d3136;border-radius:6px}.sx-design-colours{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.sx-design-colour{display:grid;grid-template-columns:54px minmax(0,1fr);gap:8px}.sx-design-colour input[type=color]{height:42px;padding:3px}
.sx-status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.sx-status-card{background:#303439;border:1px solid #484d53;border-radius:7px;padding:14px}.sx-status-card small{display:block;color:#9da0a4;font-size:10px}.sx-status-card strong{display:block;font-size:23px;margin-top:5px}.sx-status-ok{color:#8ce0b2}.sx-status-bad{color:#ff9da8}
.sx-old-center-note{padding:10px 12px;border:1px solid #6a5738;background:#3a3024;border-radius:6px;color:#e7c987;font-size:11px}
@media(max-width:1000px){.sx-status-grid{grid-template-columns:1fr 1fr}.sx-unified-grid{grid-template-columns:1fr}.sx-unified-grid .full{grid-column:auto}}
@media(max-width:650px){.sx-status-grid,.sx-games-grid,.sx-design-colours{grid-template-columns:1fr}.sx-games-grid .full{grid-column:auto}.sx-inline-actions{align-items:stretch;flex-direction:column}.sx-inline-actions .btn{width:100%}}
'''

JS = r'''
<script id="sentrix-v61-unified">
(() => {
  "use strict";
  if(window.__sentrixV61Unified)return;window.__sentrixV61Unified=true;

  const v61={setup:null,systems:null,design:null};
  const groups=[
    ["Général",[["overview","Vue d’ensemble","▦"],["welcome","Arrivées et départs","▤"],["messages","Messages","☷"],["levels","Niveaux","↗"]]],
    ["Membres & rôles",[["roles","Rôles automatiques","▣"],["secure_roles","Rôles sécurisés","◆"],["reaction_roles","Rôles-réactions","☷"]]],
    ["Modération",[["sanctions","Modération","⌁"],["security","Auto-Modération","◇"],["reports","Signalements","⚑"],["logs","Logs","◔"]]],
    ["Outils",[["tickets","Tickets","▰"],["notifications","Notifications sociales","◖"],["ai","Intelligence artificielle","AI"],["embeds","Embeds","E"],["games","Mini-jeux","◆"],["design","Design","◫"]]],
    ["Configuration",[["setup","Configuration serveur","⚙"],["access","Accès & commandes","⌘"],["dm","Messages privés","✉"],["status","Statut SentriX","●"],["general","Général technique","⚙"]]],
  ];

  function rebuildNavigation(){
    const nav=$('navigation');if(!nav)return;
    nav.innerHTML=groups.map(([label,items])=>`<div class="sx-nav-group">${label}</div>`+items.map(([tab,label,icon])=>`<button type="button" data-tab="${tab}"><span class="nav-icon">${icon}</span>${label}</button>`).join('')).join('');
    nav.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.tab));
    tabMeta.setup=['Configuration serveur','Systèmes globaux, logs, vérification et outils de configuration sans quitter le dashboard.'];
    tabMeta.games=['Mini-jeux','Configurez complètement les mini-jeux depuis la même interface.'];
    tabMeta.design=['Design','Personnalisez les couleurs et l’apparence des messages SentriX.'];
    tabMeta.status=['Statut SentriX','État du bot et vérification de la configuration du serveur.'];
  }

  function openTab(tab){
    if(!tab)return;
    state.tab=tab;
    try{localStorage.setItem('sentrix:v61:tab',tab)}catch(_){}
    renderTab();
    if(innerWidth<821)$('sidebar')?.classList.remove('open');
    try{history.replaceState({},'',`/app?tab=${encodeURIComponent(tab)}&guild=${encodeURIComponent(state.guildId||'')}`)}catch(_){}
  }

  function rewriteChrome(){
    const top=document.querySelector('.topnav');
    if(top){top.innerHTML='<a href="#" data-open-tab="overview">DASHBOARD</a><a href="#" data-open-tab="setup">CONFIGURATION</a><a href="#" data-open-tab="status">STATUS</a>'}
    const support=document.querySelector('.support-btn');if(support){support.href='#';support.textContent='STATUS';support.dataset.openTab='status'}
    const pop=$('sxProfilePopover');if(pop){pop.innerHTML='<button type="button" data-open-tab="setup">Configuration</button><button type="button" data-open-tab="status">Statut SentriX</button><button id="sxLogout" class="danger" type="button">Se déconnecter</button>';const out=$('sxLogout');if(out)out.onclick=async()=>{try{await api('/logout',{method:'POST'});location.href='/'}catch(e){toast(e.message,true)}}}
    const toolbar=$('sxToolbar');if(toolbar){const links=toolbar.querySelectorAll('a[href]');links.forEach(a=>{a.href='#';a.dataset.openTab='setup';a.textContent='Configuration'})}
  }

  const oldMap={
    '/setup-center':'setup','/feature-suite':'setup','/operations':'status','/community':'overview','/engagement':'overview','/embed-builder':'embeds','/owner-servers':'overview'
  };
  document.addEventListener('click',event=>{
    const direct=event.target.closest?.('[data-open-tab]');if(direct){event.preventDefault();openTab(direct.dataset.openTab);return}
    const link=event.target.closest?.('a[href]');if(!link)return;
    let path='';try{path=new URL(link.href,location.href).pathname}catch(_){return}
    const tab=oldMap[path];if(!tab)return;
    event.preventDefault();
    if(path==='/feature-suite')toast('L’ancien centre « Fonctions avancées » a été supprimé. Les réglages utiles sont maintenant intégrés au dashboard.');
    openTab(tab);
  },true);

  function loading(text='Chargement…'){$('fields').innerHTML=`<div class="panel-section"><div class="empty">${esc(text)}</div></div>`;$('saveBar').classList.add('hidden')}
  async function getSetup(force=false){if(!v61.setup||force)v61.setup=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/setup-tools`);return v61.setup}
  async function getSystems(force=false){if(!v61.systems||force){const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/systems`);v61.systems=r.systems||r}return v61.systems}
  async function getDesign(force=false){if(!v61.design||force){const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/design`);v61.design=r.design||r}return v61.design}
  function resetCaches(){v61.setup=null;v61.systems=null;v61.design=null}

  async function setupAction(payload,rerender=true){const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/setup-tools`,{method:'POST',body:JSON.stringify(payload)});toast(r.message||'Configuration appliquée.');v61.setup=null;if(rerender)await renderSetup();return r}
  async function toggleSystem(key){const systems=await getSystems();const next=!Boolean(systems[key]);const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/systems`,{method:'PUT',body:JSON.stringify({[key]:next})});v61.systems=r.systems;toast(r.message||'Système mis à jour.');renderSetup()}

  async function renderSetup(){
    $('tabTitle').textContent='Configuration serveur';$('tabDescription').textContent='Tous les réglages essentiels restent dans le dashboard principal.';document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='setup'));loading('Chargement de la configuration…');
    try{
      const [s,d]=await Promise.all([getSystems(true),getSetup(true)]);
      const economy=Boolean(s.economy_enabled),levels=Boolean(s.levels_enabled);
      $('fields').innerHTML=`<div class="panel-section"><div class="sx-unified-grid">
        <div class="sx-switch-card"><div><h3>Argent & boutiques</h3><p>Active ou coupe l’économie sans supprimer les soldes existants.</p></div><button class="sx-big-switch ${economy?'on':''}" data-system="economy_enabled" aria-checked="${economy}"></button></div>
        <div class="sx-switch-card"><div><h3>Niveaux & XP</h3><p>Active ou coupe les gains d’XP, niveaux et rôles de palier.</p></div><button class="sx-big-switch ${levels?'on':''}" data-system="levels_enabled" aria-checked="${levels}"></button></div>
        <section class="sx-unified-card"><h3>Créer les salons de logs</h3><p>Crée uniquement les salons manquants et configure automatiquement SentriX.</p><button id="sxCreateLogs" class="btn primary" type="button">Créer/configurer les logs</button></section>
        <section class="sx-unified-card"><h3>Panneau de vérification</h3><p>Choisissez le salon et le rôle attribué après vérification.</p><div class="field"><label>Salon</label><select id="sxVerifyChannel">${channelOptions(d.verification?.channel_id||'')}</select></div><div class="field"><label>Rôle</label><select id="sxVerifyRole">${roleOptions(d.verification?.role_id||'')}</select></div><button id="sxVerifyPanel" class="btn primary" type="button">Publier le panneau</button></section>
        <section class="sx-unified-card"><h3>Panneau de rôles</h3><p>Publiez un panneau de rôles directement depuis SentriX.</p><div class="field"><label>Salon</label><select id="sxRolePanelChannel">${channelOptions('')}</select></div><div class="field"><label>Titre</label><input id="sxRolePanelTitle" maxlength="256" value="Choisissez vos notifications"></div><button id="sxRolePanel" class="btn primary" type="button">Publier le panneau</button></section>
        <section class="sx-unified-card"><h3>Accès & commandes</h3><p>Les commandes désactivées, gestionnaires, salons ignorés et exemptions AutoMod sont dans une page dédiée mais toujours dans ce dashboard.</p><button class="btn" data-open-tab="access" type="button">Ouvrir Accès & commandes</button></section>
        <section class="sx-unified-card full sx-danger-zone"><h3>Réinitialisation</h3><p>Écrivez exactement le nom du serveur avant d’effacer une partie de la configuration.</p><div class="sx-inline-actions"><select id="sxResetScope"><option value="commands">Commandes</option><option value="ignored">Salons ignorés</option><option value="games">Mini-jeux</option><option value="security">Sécurité</option><option value="all">Toute la configuration</option></select><input id="sxResetConfirm" placeholder="Nom exact du serveur"><button id="sxReset" class="btn danger" type="button">Réinitialiser</button></div></section>
      </div></div>`;
      $('fields').querySelectorAll('[data-system]').forEach(b=>b.onclick=()=>toggleSystem(b.dataset.system));
      $('sxCreateLogs').onclick=()=>setupAction({action:'create_logs'});
      $('sxVerifyPanel').onclick=()=>setupAction({action:'verify_panel',channel_id:$('sxVerifyChannel').value,role_id:$('sxVerifyRole').value},false);
      $('sxRolePanel').onclick=()=>setupAction({action:'self_role_panel',channel_id:$('sxRolePanelChannel').value,title:$('sxRolePanelTitle').value},false);
      $('sxReset').onclick=()=>setupAction({action:'reset',scope:$('sxResetScope').value,confirmation:$('sxResetConfirm').value});
      $('saveBar').classList.add('hidden');state.dirty=false;
    }catch(e){toast(e.message,true);loading(e.message||'Configuration indisponible')}
  }

  function multiOptions(items,selected=[]){const set=new Set((selected||[]).map(String));return items.map(x=>`<option value="${esc(x.id??x)}" ${set.has(String(x.id??x))?'selected':''}>${esc(x.name??x)}</option>`).join('')}
  function selectedValues(id){return [...($(id)?.selectedOptions||[])].map(o=>o.value)}
  async function renderGames(){
    $('tabTitle').textContent='Mini-jeux';$('tabDescription').textContent='Configuration complète des mini-jeux, sans ouvrir une autre page.';document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='games'));loading('Chargement des mini-jeux…');
    try{const d=await getSetup(true),g=d.games||{},channels=(state.guildData.channels||[]).filter(c=>['text','news'].includes(c.type));$('fields').innerHTML=`<div class="panel-section"><div class="sx-games-grid">
      <div class="field"><label>Activer les mini-jeux</label><input id="game_enabled" type="checkbox" ${g.enabled?'checked':''}></div><div class="field"><label>Limite quotidienne</label><input id="game_daily" type="number" min="0" max="10000" value="${esc(g.daily_limit??50)}"></div>
      <div class="field"><label>Difficulté</label><select id="game_diff"><option value="facile" ${g.default_difficulty==='facile'?'selected':''}>Facile</option><option value="normal" ${g.default_difficulty==='normal'?'selected':''}>Normale</option><option value="difficile" ${g.default_difficulty==='difficile'?'selected':''}>Difficile</option></select></div><div class="field"><label>Multiplicateur événement</label><input id="game_event" type="number" step="0.1" min="0" max="100" value="${esc(g.event_multiplier??1)}"></div>
      <div class="field"><label>Récompense minimum</label><input id="game_min" type="number" step="0.1" min="0" max="100" value="${esc(g.min_reward_multiplier??1)}"></div><div class="field"><label>Récompense maximum</label><input id="game_max" type="number" step="0.1" min="0" max="100" value="${esc(g.max_reward_multiplier??1)}"></div>
      <div class="field full"><label>Jeux désactivés</label><select id="game_disabled" class="sx-multi" multiple>${(d.game_names||[]).map(n=>`<option value="${esc(n)}" ${(g.disabled_games||[]).includes(n)?'selected':''}>${esc(n)}</option>`).join('')}</select></div>
      <div class="field"><label>Salons autorisés</label><select id="game_allowed_channels" class="sx-multi" multiple>${multiOptions(channels,g.allowed_channel_ids)}</select></div><div class="field"><label>Salons bloqués</label><select id="game_blocked_channels" class="sx-multi" multiple>${multiOptions(channels,g.blocked_channel_ids)}</select></div>
      <div class="field"><label>Rôles autorisés</label><select id="game_allowed_roles" class="sx-multi" multiple>${multiOptions(state.guildData.roles||[],g.allowed_role_ids)}</select></div><div class="field"><label>Rôles bloqués</label><select id="game_blocked_roles" class="sx-multi" multiple>${multiOptions(state.guildData.roles||[],g.blocked_role_ids)}</select></div>
      <div class="field"><label><input id="game_logs" type="checkbox" ${g.logs_enabled?'checked':''}> Journaliser les récompenses</label></div><div class="field"><label><input id="game_board" type="checkbox" ${g.leaderboard_enabled?'checked':''}> Activer le classement</label></div><div class="field"><label><input id="game_dm" type="checkbox" ${g.dm_results?'checked':''}> Résultats en MP</label></div><div class="field"><label><input id="game_compact" type="checkbox" ${g.compact_mode?'checked':''}> Mode compact</label></div>
    </div></div>`;$('saveBar').classList.remove('hidden');$('saveButton').textContent='Enregistrer les mini-jeux';$('saveStatus').textContent='Aucune modification';$('fields').querySelectorAll('input,select').forEach(el=>el.oninput=()=>{state.dirty=true;$('saveStatus').textContent='Modifications non enregistrées'});state.dirty=false}catch(e){toast(e.message,true);loading(e.message)}
  }
  async function saveGames(){const payload={enabled:$('game_enabled').checked,logs_enabled:$('game_logs').checked,leaderboard_enabled:$('game_board').checked,dm_results:$('game_dm').checked,compact_mode:$('game_compact').checked,daily_limit:$('game_daily').value,event_multiplier:$('game_event').value,min_reward_multiplier:$('game_min').value,max_reward_multiplier:$('game_max').value,default_difficulty:$('game_diff').value,disabled_games:selectedValues('game_disabled'),allowed_channel_ids:selectedValues('game_allowed_channels'),blocked_channel_ids:selectedValues('game_blocked_channels'),allowed_role_ids:selectedValues('game_allowed_roles'),blocked_role_ids:selectedValues('game_blocked_roles')};const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/games`,{method:'PUT',body:JSON.stringify(payload)});toast(r.message||'Mini-jeux enregistrés.');v61.setup=null;state.dirty=false;$('saveStatus').textContent='Enregistré';await renderGames()}

  function hex(v){return '#'+Number(v||0).toString(16).padStart(6,'0').slice(-6)}
  async function renderDesign(){
    $('tabTitle').textContent='Design';$('tabDescription').textContent='Personnalisez SentriX sans quitter le dashboard.';document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='design'));loading('Chargement du design…');
    try{const d=await getDesign(true),cols=[['primary_color','Couleur principale'],['secondary_color','Couleur secondaire'],['success_color','Succès'],['warning_color','Avertissement'],['danger_color','Erreur']];$('fields').innerHTML=`<div class="panel-section"><div class="sx-unified-grid"><section class="sx-unified-card full"><h3>Couleurs des messages</h3><div class="sx-design-colours">${cols.map(([k,l])=>`<div class="field"><label>${l}</label><div class="sx-design-colour"><input type="color" data-design-color="${k}" value="${hex(d[k])}"><input data-design="${k}" value="${hex(d[k])}" maxlength="7"></div></div>`).join('')}</div></section><div class="field full"><label>Footer</label><input data-design="footer" value="${esc(d.footer||'SentriX')}" maxlength="100"></div><div class="field"><label>Longueur progression</label><input data-design="progress_length" type="number" min="3" max="30" value="${esc(d.progress_length||10)}"></div><div class="field"><label>Symbole rempli</label><input data-design="progress_filled" value="${esc(d.progress_filled||'■')}" maxlength="16"></div><div class="field"><label>Symbole vide</label><input data-design="progress_empty" value="${esc(d.progress_empty||'□')}" maxlength="16"></div><div class="field"><label><input data-design="show_avatars" type="checkbox" ${d.show_avatars?'checked':''}> Afficher les avatars</label></div><div class="field"><label><input data-design="compact_mode" type="checkbox" ${d.compact_mode?'checked':''}> Mode compact</label></div><div class="field"><label><input data-design="charts_enabled" type="checkbox" ${d.charts_enabled?'checked':''}> Graphiques</label></div><div id="sxDesignPreview" class="sx-design-preview full"><h3>Exemple SentriX</h3><p id="sxDesignFooter"></p></div></div></div>`;
      const sync=()=>{const primary=$('[data-design="primary_color"]')?.value||'#d66f55';$('sxDesignPreview').style.setProperty('--preview',primary);$('sxDesignFooter').textContent=$('[data-design="footer"]')?.value||'SentriX'};document.querySelectorAll('[data-design-color]').forEach(p=>p.oninput=()=>{const input=document.querySelector(`[data-design="${p.dataset.designColor}"]`);input.value=p.value.toUpperCase();state.dirty=true;sync()});document.querySelectorAll('[data-design]').forEach(el=>el.oninput=()=>{state.dirty=true;$('saveStatus').textContent='Modifications non enregistrées';sync()});sync();$('saveBar').classList.remove('hidden');$('saveButton').textContent='Enregistrer le design';$('saveStatus').textContent='Aucune modification';state.dirty=false}catch(e){toast(e.message,true);loading(e.message)}
  }
  async function saveDesign(){const out={};document.querySelectorAll('[data-design]').forEach(el=>out[el.dataset.design]=el.type==='checkbox'?el.checked:el.value);const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/design`,{method:'PUT',body:JSON.stringify(out)});v61.design=r.design;toast(r.message||'Design enregistré.');state.dirty=false;$('saveStatus').textContent='Enregistré';await renderDesign()}

  async function renderReactionRoles(){
    $('tabTitle').textContent='Rôles-réactions';$('tabDescription').textContent='Créez un panneau de rôles directement depuis le dashboard.';document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='reaction_roles'));$('fields').innerHTML=section('Nouveau panneau','Le panneau utilise le système réel de rôles de SentriX.',`<div class="fields-grid">${selectField('Salon','rr_channel',channelOptions(''),true)}${textInput('Titre','rr_title','Choisissez vos notifications',{full:true,max:256})}<div class="field full"><button id="rr_publish" class="btn primary" type="button">Publier le panneau</button></div></div>`);$('rr_publish').onclick=()=>setupAction({action:'self_role_panel',channel_id:$('fields').querySelector('[data-setting="rr_channel"]').value,title:$('fields').querySelector('[data-setting="rr_title"]').value},false);$('saveBar').classList.add('hidden');state.dirty=false
  }

  async function renderStatus(){
    $('tabTitle').textContent='Statut SentriX';$('tabDescription').textContent='État du bot et qualité de la configuration de ce serveur.';document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='status'));loading('Analyse du serveur…');
    try{const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/diagnostics`),p=state.public||{},s=d.summary||{};$('fields').innerHTML=`<div class="panel-section"><div class="sx-status-grid"><div class="sx-status-card"><small>Bot Discord</small><strong class="${p.online?'sx-status-ok':'sx-status-bad'}">${p.online?'EN LIGNE':'HORS LIGNE'}</strong></div><div class="sx-status-card"><small>Configuration</small><strong>${Number(d.score||0)}%</strong></div><div class="sx-status-card"><small>Modules actifs</small><strong>${Number(s.active||0)}</strong></div><div class="sx-status-card"><small>Erreurs</small><strong class="${Number(s.errors||0)?'sx-status-bad':'sx-status-ok'}">${Number(s.errors||0)}</strong></div></div></div>`+section('Vérification des modules','Les statuts viennent de Discord et de la base actuelle.',`<div class="sx-settings-list">${Object.entries(d.modules||{}).map(([k,v])=>`<div class="sx-settings-row"><div><b>${esc(k)}</b><small>${esc(v.detail||'')}</small></div><span class="sx-state ${esc(v.code)}">${esc(v.status)}</span></div>`).join('')}</div>`);$('saveBar').classList.add('hidden');state.dirty=false}catch(e){toast(e.message,true);loading(e.message)}
  }

  const baseSelectGuild=selectGuild;selectGuild=async function(value){const changed=String(value)!==String(state.guildId);const r=await baseSelectGuild(value);if(changed)resetCaches();return r};
  const baseRenderTab=renderTab;renderTab=function(){
    rebuildNavigation();rewriteChrome();
    if(state.tab==='setup'){renderSetup();return}
    if(state.tab==='games'){renderGames();return}
    if(state.tab==='design'){renderDesign();return}
    if(state.tab==='status'){renderStatus();return}
    if(state.tab==='reaction_roles'){renderReactionRoles();return}
    if(['economy','recurring','community','infinity','custom_commands','word_reactions','birthdays','features'].includes(state.tab))state.tab='overview';
    return baseRenderTab();
  };
  const baseSave=save;save=async function(event){if(state.tab==='games'){event?.preventDefault?.();return saveGames()}if(state.tab==='design'){event?.preventDefault?.();return saveDesign()}return baseSave(event)};

  // Le vieux nom « Fonctions avancées » disparaît même si une couche historique a tenté de l'ajouter.
  document.querySelectorAll('[data-tab="features"]').forEach(n=>n.remove());
  rebuildNavigation();rewriteChrome();
  const params=new URLSearchParams(location.search);const requested=params.get('tab');const allowed=new Set(groups.flatMap(g=>g[1].map(x=>x[0])));if(requested&&allowed.has(requested))state.tab=requested;else if(requested==='features')state.tab='setup';
  setTimeout(()=>{if(state.guildData)renderTab()},120);
})();
</script>
'''


def _redirect(module, attr: str, tab: str) -> bool:
    current = getattr(module, attr, None)
    if current is None or getattr(current, "_sentrix_v61_redirect", False):
        return current is not None

    async def redirected(request: web.Request):
        params = {"tab": tab}
        guild_id = str(request.query.get("guild") or "").strip()
        if guild_id.isdigit():
            params["guild"] = guild_id
        raise web.HTTPFound("/app?" + urlencode(params))

    redirected._sentrix_v61_redirect = True
    redirected._sentrix_original = current
    setattr(module, attr, redirected)
    return True


def _redirect_legacy_pages() -> int:
    from . import setup_center, feature_suite_dashboard_v37, operations_center, community_growth

    count = 0
    count += int(_redirect(setup_center, "handle_setup_center", "setup"))
    count += int(_redirect(feature_suite_dashboard_v37, "handle_page", "setup"))
    count += int(_redirect(operations_center, "handle_operations_page", "status"))
    count += int(_redirect(community_growth, "handle_page", "overview"))
    try:
        from . import engagement_hub
        for attr in ("handle_page", "handle_engagement_page"):
            if hasattr(engagement_hub, attr):
                count += int(_redirect(engagement_hub, attr, "overview"))
    except Exception:
        pass
    return count


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v61-unified"' in html:
        return True
    if not str(getattr(dashboard, "_sentrix_dashboard_version", "")).startswith("v60"):
        logger.error("Dashboard V61 refusé : V60 absent.")
        return False
    if "</style>" not in html or "</body>" not in html:
        return False

    # Retire toute intégration Feature Suite éventuellement laissée par une ancienne branche.
    html = html.replace('<button type="button" data-tab="features"><span class="nav-icon">⚙</span>Fonctions avancées</button>', '')
    dashboard.INDEX_HTML = html.replace("</style>", CSS + "\n</style>", 1).replace("</body>", JS + "\n</body>", 1)
    redirects = _redirect_legacy_pages()
    dashboard._sentrix_dashboard_version = "v61-draft-unified"
    logger.info("Dashboard V61 installé : une seule interface /app, anciens centres redirigés=%s, Fonctions avancées supprimé.", redirects)
    return True


__all__ = ["install", "CSS", "JS", "_redirect_legacy_pages"]
