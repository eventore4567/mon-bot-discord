"""SentriX Dashboard V60 MAX — finition fonctionnelle du rework.

Ce module enrichit uniquement le frontend V60 que nous contrôlons. Il n'essaie pas de
réparer les anciennes couches historiques : il ajoute les contrôles avancés, les actions de
modération réelles, l'éditeur d'embeds complet et les garde-fous UX juste avant le snapshot
immuable servi sur /app.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-v60-max")

MAX_CSS = r'''
/* SentriX V60 MAX */
:focus-visible{outline:2px solid var(--accent2);outline-offset:2px}
.sx-nav-tools{padding:10px 12px 6px;position:sticky;top:0;background:linear-gradient(180deg,var(--side) 82%,transparent);z-index:3}
.sx-nav-search{width:100%;border:1px solid #454a50;background:#24282d;color:#f3f4f5;border-radius:6px;padding:9px 10px;outline:0}.sx-nav-search:focus{border-color:var(--accent)}
.sx-top-action{border:1px solid #ffffff18;background:#2a2e33;color:#e8e9ea;border-radius:7px;padding:8px 10px;cursor:pointer;font-weight:800}.sx-top-action:hover{border-color:var(--accent);color:var(--accent2)}
.sx-mobile-menu{display:none}.sx-profile-menu{position:relative}.sx-profile-popover{position:absolute;right:0;top:52px;width:220px;background:#25292e;border:1px solid #484d53;border-radius:8px;box-shadow:0 18px 50px #0008;padding:7px;z-index:80}.sx-profile-popover a,.sx-profile-popover button{display:flex;width:100%;border:0;background:transparent;color:#eee;padding:10px;border-radius:6px;text-align:left;cursor:pointer}.sx-profile-popover a:hover,.sx-profile-popover button:hover{background:#31353a}.sx-profile-popover .danger{color:#ff9fa9}
.sx-overview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.sx-overview-card{background:#303439;border:1px solid #484d53;border-radius:7px;padding:16px}.sx-overview-card h3{margin:0 0 6px;font-size:15px}.sx-overview-card p{margin:0;color:#aeb0b3;font-size:12px;line-height:1.5}.sx-overview-value{font-size:26px;font-weight:900;margin-top:9px}.sx-overview-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.sx-modal-backdrop{position:fixed;inset:0;background:#1118;backdrop-filter:blur(3px);display:grid;place-items:center;padding:20px;z-index:150}.sx-modal{width:min(520px,100%);background:#282c31;border:1px solid #555b62;border-radius:9px;box-shadow:0 24px 80px #000a;overflow:hidden}.sx-modal-head{display:flex;align-items:center;justify-content:space-between;padding:16px 17px;border-bottom:1px solid #454a50}.sx-modal-head h3{margin:0;font-size:17px}.sx-modal-close{border:0;background:transparent;color:#bbb;font-size:20px;cursor:pointer}.sx-modal-body{padding:17px}.sx-modal-foot{padding:13px 17px;border-top:1px solid #454a50;display:flex;justify-content:flex-end;gap:8px}.sx-modal textarea{width:100%;min-height:100px;background:#22262b;color:#fff;border:1px solid #4b5056;border-radius:6px;padding:11px;resize:vertical}
.sx-sanction-user{display:flex;gap:9px;align-items:center;min-width:0}.sx-sanction-avatar{width:34px;height:34px;border-radius:50%;background:#1d2024;overflow:hidden;display:grid;place-items:center;flex:0 0 auto}.sx-sanction-avatar img{width:100%;height:100%;object-fit:cover}.sx-sanction-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.sx-mini{padding:7px 9px;font-size:11px}.sx-search-row{display:grid;grid-template-columns:220px minmax(200px,1fr) auto;gap:9px;margin-bottom:14px}.sx-search-row .btn{align-self:end}
.sx-embed-layout{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(320px,.8fr);gap:20px}.sx-embed-editor{display:grid;grid-template-columns:1fr 1fr;gap:12px}.sx-embed-editor .full{grid-column:1/-1}.sx-embed-fields{display:grid;gap:8px}.sx-embed-field{display:grid;grid-template-columns:1fr 1.4fr auto;gap:8px;padding:10px;border:1px solid #474c52;border-radius:6px;background:#2b2f34}.sx-inline-check{display:flex;align-items:center;gap:7px;color:#bbb;font-size:12px}.sx-inline-check input{width:auto}.sx-discord-authorline{display:flex;align-items:center;gap:7px;font-size:12px;margin-bottom:8px}.sx-discord-thumb{float:right;width:72px;height:72px;border-radius:4px;object-fit:cover;margin:0 0 8px 12px}.sx-discord-image{display:block;max-width:100%;max-height:300px;object-fit:contain;border-radius:4px;margin-top:12px}.sx-discord-footer{display:flex;gap:6px;align-items:center;color:#b5bac1;font-size:11px;margin-top:11px}.sx-discord-footer img,.sx-discord-authorline img{width:20px;height:20px;border-radius:50%;object-fit:cover}.sx-discord-fields{display:grid;grid-template-columns:repeat(12,1fr);gap:8px;margin-top:10px}.sx-discord-field{grid-column:span 12;min-width:0}.sx-discord-field.inline{grid-column:span 4}.sx-discord-field b,.sx-discord-field span{display:block;overflow-wrap:anywhere}.sx-discord-field span{color:#dbdee1;font-size:12px;margin-top:2px;white-space:pre-wrap}
.sx-toolbar{display:flex;gap:8px;align-items:center;justify-content:flex-end;margin:-6px 0 18px}.sx-toolbar-status{margin-right:auto;color:#aaa;font-size:12px}.sx-kbd{border:1px solid #555a60;border-bottom-width:2px;border-radius:4px;padding:1px 5px;font-size:10px;color:#bbb}
.sx-empty-filter{display:none!important}.sx-loading-line{height:3px;position:fixed;top:0;left:0;right:0;z-index:200;background:linear-gradient(90deg,transparent,var(--accent),transparent);background-size:35% 100%;animation:sxload 1s linear infinite}@keyframes sxload{from{background-position:-50% 0}to{background-position:150% 0}}
@media(max-width:1180px){.sx-embed-layout{grid-template-columns:1fr}.sx-overview-grid{grid-template-columns:1fr 1fr}.sx-search-row{grid-template-columns:1fr 1fr}}
@media(max-width:820px){.sx-mobile-menu{display:inline-flex}.sx-toolbar{justify-content:flex-start;flex-wrap:wrap}.sx-toolbar-status{width:100%;margin:0}.sx-overview-grid{grid-template-columns:1fr}.sx-search-row{grid-template-columns:1fr}.sx-profile-popover{right:-8px}}
@media(max-width:600px){.sx-embed-editor{grid-template-columns:1fr}.sx-embed-editor .full{grid-column:auto}.sx-embed-field{grid-template-columns:1fr}.sx-discord-field.inline{grid-column:span 12}}
'''

MAX_JS = r'''
<script id="sentrix-v60-max">
(() => {
  "use strict";
  if (window.__sentrixV60Max) return;
  window.__sentrixV60Max = true;

  const sx = {
    savedTabKey: "sentrix:v60:tab",
    loading: 0,
    confirmAction: null,
  };

  function startLoading(){
    sx.loading += 1;
    if (!$('sxLoadingLine')) {
      const el=document.createElement('div'); el.id='sxLoadingLine'; el.className='sx-loading-line'; document.body.appendChild(el);
    }
  }
  function stopLoading(){
    sx.loading=Math.max(0,sx.loading-1);
    if(!sx.loading) $('sxLoadingLine')?.remove();
  }

  const sxApiBase = api;
  api = async function(url, options={}){
    startLoading();
    try{return await sxApiBase(url,options)}finally{stopLoading()}
  };

  function ensureChrome(){
    const nav=$('navigation');
    if(nav && !$('sxNavSearch')){
      const tools=document.createElement('div'); tools.className='sx-nav-tools';
      tools.innerHTML='<input id="sxNavSearch" class="sx-nav-search" type="search" placeholder="Rechercher une fonction…" aria-label="Rechercher une fonction">';
      nav.prepend(tools);
      $('sxNavSearch').addEventListener('input',event=>{
        const q=String(event.target.value||'').trim().toLocaleLowerCase('fr');
        nav.querySelectorAll('button[data-tab]').forEach(button=>button.classList.toggle('sx-empty-filter',q && !button.textContent.toLocaleLowerCase('fr').includes(q)));
      });
    }
    if(nav && !nav.querySelector('[data-tab="overview"]')){
      const b=document.createElement('button'); b.type='button'; b.dataset.tab='overview';
      b.innerHTML='<span class="nav-icon">▦</span>Vue d’ensemble';
      const first=nav.querySelector('button[data-tab]'); nav.insertBefore(b,first);
      tabMeta.overview=['Vue d’ensemble','État du serveur, raccourcis et activité récente de SentriX.'];
    }
    const topRight=document.querySelector('.top-right');
    if(topRight && !$('sxMobileMenu')){
      const menu=document.createElement('button'); menu.id='sxMobileMenu'; menu.type='button'; menu.className='sx-top-action sx-mobile-menu'; menu.textContent='Menu';
      menu.onclick=()=>$('sidebar')?.classList.toggle('open'); topRight.prepend(menu);
    }
    const profile=document.querySelector('.profile');
    if(profile && !profile.closest('.sx-profile-menu')){
      const wrap=document.createElement('div'); wrap.className='sx-profile-menu'; profile.parentNode.insertBefore(wrap,profile); wrap.appendChild(profile);
      profile.tabIndex=0; profile.setAttribute('role','button'); profile.setAttribute('aria-haspopup','menu');
      const pop=document.createElement('div'); pop.id='sxProfilePopover'; pop.className='sx-profile-popover hidden';
      pop.innerHTML='<a href="/setup-center">Centre de configuration</a><a href="/operations">État de SentriX</a><button id="sxLogout" class="danger" type="button">Se déconnecter</button>';
      wrap.appendChild(pop);
      const toggle=()=>pop.classList.toggle('hidden'); profile.addEventListener('click',toggle); profile.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle()}});
      $('sxLogout').onclick=async()=>{try{await api('/logout',{method:'POST'});location.href='/'}catch(e){toast(e.message,true)}};
      document.addEventListener('click',e=>{if(!wrap.contains(e.target))pop.classList.add('hidden')});
    }
    const workspace=document.querySelector('.workspace');
    if(workspace && !$('sxToolbar')){
      const bar=document.createElement('div'); bar.id='sxToolbar'; bar.className='sx-toolbar';
      bar.innerHTML='<span id="sxToolbarStatus" class="sx-toolbar-status">Prêt</span><button id="sxRefresh" class="sx-top-action" type="button">Actualiser</button><a class="sx-top-action" href="/setup-center">Configuration avancée</a><span class="sx-kbd">Ctrl/⌘ + S</span>';
      const metrics=document.querySelector('.metrics'); workspace.insertBefore(bar,metrics||workspace.firstChild);
      $('sxRefresh').onclick=async()=>{if(state.guildId){try{await selectGuild(state.guildId);toast('Données actualisées.')}catch(e){toast(e.message,true)}}};
    }
  }

  function renderOverview(){
    const g=state.guildData?.guild||{},m=state.guildData?.metrics||{},p=state.public||{};
    $('tabTitle').textContent='Vue d’ensemble'; $('tabDescription').textContent='État du serveur, raccourcis et activité récente de SentriX.';
    document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='overview'));
    $('fields').innerHTML=`<div class="panel-section"><div class="sx-overview-grid">
      <div class="sx-overview-card"><h3>Membres</h3><p>Communauté actuellement visible par SentriX.</p><div class="sx-overview-value">${number(g.members)}</div></div>
      <div class="sx-overview-card"><h3>Salons</h3><p>Salons et catégories détectés sur le serveur.</p><div class="sx-overview-value">${number(g.channels_count)}</div></div>
      <div class="sx-overview-card"><h3>Rôles</h3><p>Rôles disponibles pour vos automatisations.</p><div class="sx-overview-value">${number(g.roles_count)}</div></div>
      <div class="sx-overview-card"><h3>Commandes · 24 h</h3><p>Commandes enregistrées sur les dernières 24 heures.</p><div class="sx-overview-value">${number(m.commands_24h)}</div></div>
      <div class="sx-overview-card"><h3>Tickets ouverts</h3><p>Tickets qui demandent encore une intervention.</p><div class="sx-overview-value">${number(m.open_tickets)}</div></div>
      <div class="sx-overview-card"><h3>Avertissements</h3><p>Avertissements actuellement comptabilisés.</p><div class="sx-overview-value">${number(m.warnings)}</div></div>
    </div></div>`+section('Accès rapides','Ouvrez les zones importantes sans quitter le serveur sélectionné.',`<div class="action-grid">
      <div class="action-card"><h3>Configuration</h3><p>Réglages avancés et systèmes supplémentaires.</p><a class="btn primary" href="/setup-center">Ouvrir</a></div>
      <div class="action-card"><h3>Communauté</h3><p>Outils de croissance et d’engagement.</p><a class="btn primary" href="/community">Ouvrir</a></div>
      <div class="action-card"><h3>État du bot</h3><p>${p.online?'SentriX est connecté à Discord.':'Connexion Discord en cours.'}</p><a class="btn primary" href="/operations">Voir l’état</a></div>
    </div>`);
    $('saveBar').classList.add('hidden'); state.dirty=false;
  }

  function variablePreview(text){
    return String(text||'').replaceAll('{user.username}',state.user?.username||'tomioka').replaceAll('{user.mention}','@'+(state.user?.username||'tomioka')).replaceAll('{server.name}',state.guildData?.guild?.name||'Serveur').replaceAll('{level}','12');
  }

  renderWelcome = function(){
    const s=state.guildData.settings||{},welcomeText=s.welcome_message||'Bienvenue {user.username} !\nNous sommes ravis de t’accueillir sur {server.name}.',goodbyeText=s.goodbye_message||'{user.username} a quitté {server.name}.\nMerci d’avoir fait partie de l’aventure !';
    $('fields').innerHTML=section('Message de Bienvenue','Configurez le message envoyé aux nouveaux membres.',`<div class="grid2"><div class="fields-grid">
      ${selectField('Salon des messages de bienvenue','welcome_channel',channelOptions(s.welcome_channel),true)}
      ${textInput('Message personnalisé','welcome_message',welcomeText,{textarea:true,max:2000,full:true})}
      ${textInput('Image de bienvenue HTTPS','welcome_image_url',s.welcome_image_url||'',{type:'url',full:true,placeholder:'https://…',hint:'Facultatif. Utilisez une URL HTTPS publique.'})}
      <div class="field full"><div class="hint">Variables : {user.username}, {user.mention}, {server.name}</div></div>
    </div><div><div class="preview-label">Prévisualisation</div><div class="discord-preview"><div class="discord-author"><span class="bot-avatar">S</span><span>SentriX <span class="app-badge">APP</span></span></div><div class="discord-embed"><strong>Un nouveau membre nous rejoint !</strong><div id="welcomePreview" class="preview-text"></div></div></div></div></div>`,`<input id="welcomeEnabled" class="switch" type="checkbox" ${s.welcome_channel?'checked':''}>`)+section('Message d’Au Revoir','Configurez le message envoyé lorsqu’un membre quitte le serveur.',`<div class="grid2"><div class="fields-grid">
      ${selectField("Salon des messages d'au revoir",'goodbye_channel',channelOptions(s.goodbye_channel),true)}
      ${textInput('Message personnalisé','goodbye_message',goodbyeText,{textarea:true,max:1000,full:true})}
    </div><div><div class="preview-label">Prévisualisation</div><div class="discord-preview"><div class="discord-author"><span class="bot-avatar">S</span><span>SentriX <span class="app-badge">APP</span></span></div><div class="discord-embed"><strong>Un membre nous a quitté.</strong><div id="goodbyePreview" class="preview-text"></div></div></div></div></div>`,`<input id="goodbyeEnabled" class="switch" type="checkbox" ${s.goodbye_channel?'checked':''}>`);
    const sync=()=>{$('welcomePreview').textContent=variablePreview($('fields').querySelector('[data-setting="welcome_message"]')?.value);$('goodbyePreview').textContent=variablePreview($('fields').querySelector('[data-setting="goodbye_message"]')?.value)};
    $('fields').addEventListener('input',sync); sync();
  };

  renderRoles = function(){const s=state.guildData.settings||{};$('fields').innerHTML=section('Rôles automatiques','Choisissez les rôles attribués ou utilisés automatiquement par SentriX.',`<div class="fields-grid">${selectField('Rôle automatique','autorole',roleOptions(s.autorole))}${selectField('Rôle membre','member_role',roleOptions(s.member_role))}${selectField('Rôle booster','booster_role',roleOptions(s.booster_role))}${selectField('Rôle avertissement','warn_role',roleOptions(s.warn_role))}${selectField('Rôle mute','mute_role',roleOptions(s.mute_role))}</div>`)};
  renderSecureRoles = function(){const s=state.guildData.settings||{};$('fields').innerHTML=section('Accès sécurisés','Rôles utilisés pour la vérification, la modération et les accès sensibles.',`<div class="fields-grid">${selectField('Rôle de vérification','verification_role',roleOptions(s.verification_role))}${selectField('Rôle vérifié','verify_role',roleOptions(s.verify_role))}${selectField('Rôle modérateur','mod_role',roleOptions(s.mod_role))}${selectField('Rôle administrateur','admin_role',roleOptions(s.admin_role))}${selectField('Salon de vérification','verification_channel',channelOptions(s.verification_channel))}</div>`)};
  renderMessages = function(){const s=state.guildData.settings||{};const defs=[['Salon des règles','rules_channel'],['Salon de vérification','verification_channel'],['Salon des annonces','announce_channel'],['Salon giveaways','giveaway_channel'],['Salon commandes bot','bot_commands_channel'],['Salon partenaires','partner_channel'],['Salon statistiques','stats_channel'],['Salon AFK','afk_channel'],['Salon erreurs','error_channel']];$('fields').innerHTML=section('Messages et salons système','Centralisez les destinations utilisées par les principales fonctions.',`<div class="fields-grid">${defs.map(([l,k])=>selectField(l,k,channelOptions(s[k]))).join('')}</div>`)};
  renderReports = function(){const s=state.guildData.settings||{};$('fields').innerHTML=section('Signalements','Définissez le salon privé utilisé par les signalements.',`<div class="fields-grid">${selectField('Salon des signalements','report_channel',channelOptions(s.report_channel))}${selectField('Salon erreurs','error_channel',channelOptions(s.error_channel))}</div>`)};
  renderSuggestions = function(){const s=state.guildData.settings||{};$('fields').innerHTML=section('Suggestions','Définissez où les suggestions et annonces associées doivent être publiées.',`<div class="fields-grid">${selectField('Salon des suggestions','suggest_channel',channelOptions(s.suggest_channel))}${selectField('Salon des annonces','announce_channel',channelOptions(s.announce_channel))}</div>`)};

  const sxSecurityBase=renderSecurity;
  renderSecurity = function(){sxSecurityBase();const s=state.guildData.settings||{};const root=$('fields')?.querySelector('.panel-section');if(!root)return;const extra=document.createElement('div');extra.className='fields-grid';extra.style.marginTop='18px';extra.innerHTML=`<div class="field"><label>Niveau de sécurité</label><select data-setting="security_level"><option value="faible" ${s.security_level==='faible'?'selected':''}>Faible</option><option value="moyen" ${s.security_level==='moyen'?'selected':''}>Moyen</option><option value="eleve" ${s.security_level==='eleve'?'selected':''}>Élevé</option></select></div>${textInput('Warns avant ban','warn_ban_threshold',s.warn_ban_threshold??3,{type:'number'})}`;root.appendChild(extra)};

  renderTickets = function(){const s=state.guildData.settings||{};$('fields').innerHTML=section('Réglages rapides','Configuration essentielle des tickets. Les panels et boutons restent disponibles dans l’éditeur avancé.',`<div class="fields-grid">${selectField('Catégorie des tickets','ticket_category',channelOptions(s.ticket_category,'category'))}${selectField('Salon de logs tickets','ticket_log_channel',channelOptions(s.ticket_log_channel))}${textInput('Délai avant suppression (secondes)','ticket_delete_delay',s.ticket_delete_delay??0,{type:'number'})}<div class="field full">${toggleHtml('Transcript en MP','Envoie le transcript au membre après fermeture.',Boolean(s.ticket_transcript_dm),'data-setting="ticket_transcript_dm" data-type="bool"')}${toggleHtml('Évaluation du ticket','Demande une note après la fermeture.',Boolean(s.ticket_rating_enabled),'data-setting="ticket_rating_enabled" data-type="bool"')}</div></div><div class="sx-overview-actions"><a class="btn primary" href="/setup-center">Éditeur complet</a><a class="btn" href="/operations">État du service</a></div>`)};

  renderNotifications = function(){const items=state.guildData.social_notifications||[];$('fields').innerHTML=section('Ajouter une source','YouTube, TikTok, Twitch, Instagram, X, Facebook, Dailymotion, Vimeo ou Kick.',`<div class="fields-grid"><div class="field full"><label>Lien de la chaîne ou du profil</label><input id="notifSource" type="url" placeholder="https://…"></div><div class="field"><label>Salon Discord</label><select id="notifChannel">${channelOptions('')}</select></div><div class="field"><label>Rôle à notifier</label><select id="notifRole">${roleOptions('')}</select></div><div class="field full"><label>Texte personnalisé</label><textarea id="notifText" maxlength="1000" placeholder="Nouveau contenu disponible !"></textarea></div><div class="field full"><label>Image HTTPS facultative</label><input id="notifImage" type="url" placeholder="https://…"></div><div class="field full"><button class="btn primary" id="createNotif" type="button">Ajouter la notification</button></div></div>`)+section('Sources configurées','Supprimez une source sans toucher aux autres réglages.',`<div class="list">${items.length?items.map(n=>`<div class="list-row"><div><b>${esc(n.platform||'Source')}</b><small>${esc(n.source_url)}</small></div><small>${esc(n.custom_text||'Message automatique')}</small><button class="btn danger" data-delete-notif="${esc(n.id)}" type="button">Supprimer</button></div>`).join(''):'<div class="empty">Aucune notification sociale configurée.</div>'}</div>`);$('createNotif').onclick=createNotification;$('fields').querySelectorAll('[data-delete-notif]').forEach(b=>b.onclick=()=>deleteNotification(b.dataset.deleteNotif))};
  createNotification = async function(){try{await api(`/api/guilds/${encodeURIComponent(state.guildId)}/notifications`,{method:'POST',body:JSON.stringify({source_url:$('notifSource').value,discord_channel_id:$('notifChannel').value,role_id:$('notifRole').value,custom_text:$('notifText').value,image_url:$('notifImage').value})});toast('Notification ajoutée.');await selectGuild(state.guildId)}catch(e){toast(e.message,true)}};

  function embedFieldRow(field={name:'',value:'',inline:false}){return `<div class="sx-embed-field"><input data-embed-field="name" maxlength="256" placeholder="Nom" value="${esc(field.name)}"><textarea data-embed-field="value" maxlength="1024" placeholder="Valeur">${esc(field.value)}</textarea><button class="btn danger sx-mini" data-remove-embed-field type="button">Supprimer</button><label class="sx-inline-check"><input data-embed-field="inline" type="checkbox" ${field.inline?'checked':''}> Côte à côte</label></div>`}
  function bindEmbedFields(){const list=$('sxEmbedFields');list?.querySelectorAll('[data-remove-embed-field]').forEach(b=>b.onclick=()=>{b.closest('.sx-embed-field')?.remove();syncEmbedPreview()});list?.querySelectorAll('input,textarea').forEach(el=>el.addEventListener('input',syncEmbedPreview))}
  function collectEmbedFields(){return [...document.querySelectorAll('.sx-embed-field')].map(row=>({name:row.querySelector('[data-embed-field="name"]')?.value||'',value:row.querySelector('[data-embed-field="value"]')?.value||'',inline:Boolean(row.querySelector('[data-embed-field="inline"]')?.checked)})).filter(f=>f.name||f.value)}
  function safeImage(url){return /^https:\/\//i.test(String(url||''))?String(url):''}
  function syncEmbedPreview(){
    if(!$('embedPreviewBox'))return;const color=$('embedColor')?.value||'#d66f55';$('embedPreviewBox').style.borderLeftColor=/^#[0-9a-f]{6}$/i.test(color)?color:'var(--accent)';
    $('embedPreviewTitle').textContent=$('embedTitle')?.value||'Titre de l’embed';$('embedPreviewDescription').textContent=$('embedDescription')?.value||'Votre description apparaîtra ici.';$('embedPreviewContent').textContent=$('embedContent')?.value||'';
    const author=$('embedAuthorName')?.value||'',authorIcon=safeImage($('embedAuthorIcon')?.value),a=$('embedPreviewAuthor');a.innerHTML=author?(authorIcon?`<img src="${esc(authorIcon)}" alt="">`:'')+`<b>${esc(author)}</b>`:'';a.classList.toggle('hidden',!author);
    const thumb=safeImage($('embedThumbnail')?.value),thumbEl=$('embedPreviewThumb');thumbEl.src=thumb;thumbEl.classList.toggle('hidden',!thumb);const image=safeImage($('embedImage')?.value),imageEl=$('embedPreviewImage');imageEl.src=image;imageEl.classList.toggle('hidden',!image);
    const footer=$('embedFooter')?.value||'',footerIcon=safeImage($('embedFooterIcon')?.value),foot=$('embedPreviewFooter');foot.innerHTML=footer?(footerIcon?`<img src="${esc(footerIcon)}" alt="">`:'')+`<span>${esc(footer)}</span>`:'';foot.classList.toggle('hidden',!footer);
    $('embedPreviewFields').innerHTML=collectEmbedFields().map(f=>`<div class="sx-discord-field ${f.inline?'inline':''}"><b>${esc(f.name||'Champ')}</b><span>${esc(f.value||'Valeur')}</span></div>`).join('');
  }
  renderEmbeds = function(){$('fields').innerHTML=section('Créateur d’embed','Tous les principaux champs Discord sont disponibles avec un aperçu en direct.',`<div class="sx-embed-layout"><div class="sx-embed-editor">
    <div class="field full"><label>Salon d’envoi</label><select id="embedChannel">${channelOptions('')}</select></div><div class="field full"><label>Message au-dessus de l’embed</label><textarea id="embedContent" maxlength="2000"></textarea></div>
    <div class="field"><label>Titre</label><input id="embedTitle" maxlength="256"></div><div class="field"><label>Lien du titre</label><input id="embedUrl" type="url" placeholder="https://…"></div><div class="field full"><label>Description</label><textarea id="embedDescription" maxlength="4096"></textarea></div>
    <div class="field"><label>Couleur</label><input id="embedColor" value="#d66f55" maxlength="7"></div><div class="field"><label>Miniature</label><input id="embedThumbnail" type="url" placeholder="https://…"></div><div class="field full"><label>Grande image ou GIF</label><input id="embedImage" type="url" placeholder="https://…"></div>
    <div class="field"><label>Auteur</label><input id="embedAuthorName" maxlength="256"></div><div class="field"><label>Icône auteur</label><input id="embedAuthorIcon" type="url" placeholder="https://…"></div><div class="field full"><label>Lien auteur</label><input id="embedAuthorUrl" type="url" placeholder="https://…"></div>
    <div class="field"><label>Footer</label><input id="embedFooter" maxlength="2048"></div><div class="field"><label>Icône footer</label><input id="embedFooterIcon" type="url" placeholder="https://…"></div><div class="field full">${toggleHtml('Afficher la date et l’heure','Ajoute le timestamp Discord.',false,'id="embedTimestamp"')}</div>
    <div class="field full"><label>Champs</label><div id="sxEmbedFields" class="sx-embed-fields"></div><button id="sxAddEmbedField" class="btn" type="button">+ Ajouter un champ</button></div>
    <div class="field full"><button class="btn primary" id="sendEmbed" type="button">Envoyer l’embed</button></div>
    </div><div class="embed-preview"><div class="preview-label">Aperçu Discord</div><div class="discord-preview"><div class="discord-author"><span class="bot-avatar">S</span><span>SentriX <span class="app-badge">APP</span></span></div><div id="embedPreviewContent" class="preview-text"></div><div id="embedPreviewBox" class="discord-embed"><img id="embedPreviewThumb" class="sx-discord-thumb hidden" alt=""><div id="embedPreviewAuthor" class="sx-discord-authorline hidden"></div><strong id="embedPreviewTitle">Titre de l’embed</strong><div id="embedPreviewDescription" class="preview-text">Votre description apparaîtra ici.</div><div id="embedPreviewFields" class="sx-discord-fields"></div><img id="embedPreviewImage" class="sx-discord-image hidden" alt=""><div id="embedPreviewFooter" class="sx-discord-footer hidden"></div></div></div></div></div>`);
    $('sxAddEmbedField').onclick=()=>{const rows=$('sxEmbedFields').querySelectorAll('.sx-embed-field');if(rows.length>=25)return toast('Discord limite un embed à 25 champs.',true);$('sxEmbedFields').insertAdjacentHTML('beforeend',embedFieldRow());bindEmbedFields()};$('sendEmbed').onclick=sendEmbed;$('fields').querySelectorAll('#embedContent,#embedTitle,#embedDescription,#embedColor,#embedThumbnail,#embedImage,#embedAuthorName,#embedAuthorIcon,#embedFooter,#embedFooterIcon').forEach(el=>el.addEventListener('input',syncEmbedPreview));syncEmbedPreview()};
  sendEmbed = async function(){try{const payload={channel_id:$('embedChannel').value,content:$('embedContent').value,title:$('embedTitle').value,url:$('embedUrl').value,description:$('embedDescription').value,color:$('embedColor').value,thumbnail_url:$('embedThumbnail').value,image_url:$('embedImage').value,author_name:$('embedAuthorName').value,author_icon_url:$('embedAuthorIcon').value,author_url:$('embedAuthorUrl').value,footer_text:$('embedFooter').value,footer_icon_url:$('embedFooterIcon').value,timestamp:Boolean($('embedTimestamp').checked),fields:collectEmbedFields()};const result=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/embeds`,{method:'POST',body:JSON.stringify(payload)});toast(result.message||'Embed envoyé dans Discord.')}catch(e){toast(e.message,true)}};

  function closeModal(){document.querySelector('.sx-modal-backdrop')?.remove();sx.confirmAction=null}
  function actionModal(title,copy,action){closeModal();sx.confirmAction=action;const back=document.createElement('div');back.className='sx-modal-backdrop';back.innerHTML=`<div class="sx-modal" role="dialog" aria-modal="true" aria-labelledby="sxModalTitle"><div class="sx-modal-head"><h3 id="sxModalTitle">${esc(title)}</h3><button class="sx-modal-close" type="button">×</button></div><div class="sx-modal-body"><p>${esc(copy)}</p><label>Raison</label><textarea id="sxActionReason" maxlength="500" placeholder="Raison de l’action…">Action effectuée depuis le dashboard SentriX</textarea></div><div class="sx-modal-foot"><button class="btn" data-cancel type="button">Annuler</button><button class="btn primary" data-confirm type="button">Confirmer</button></div></div>`;document.body.appendChild(back);back.querySelector('.sx-modal-close').onclick=closeModal;back.querySelector('[data-cancel]').onclick=closeModal;back.addEventListener('click',e=>{if(e.target===back)closeModal()});back.querySelector('[data-confirm]').onclick=async()=>{const reason=$('sxActionReason').value.trim();if(!reason)return toast('Ajoutez une raison.',true);const fn=sx.confirmAction;closeModal();await fn(reason)}}
  async function sanctionAction(userId,action,reason){try{const data=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/sanctions/${encodeURIComponent(userId)}/${encodeURIComponent(action)}`,{method:'POST',body:JSON.stringify({reason})});toast(data.message||'Action appliquée.');await loadSanctions()}catch(e){toast(e.message,true)}}
  loadSanctions = async function(){try{const filter=$('sanctionFilter')?.value||state.sanctionFilter||'all',userId=$('sanctionUserSearch')?.value.trim()||'';state.sanctionFilter=filter;const q=new URLSearchParams({filter,limit:'50'});if(userId)q.set('user_id',userId);const data=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/sanctions?${q}`),rows=data.sanctions||[],list=$('sanctionList');if(!list)return;list.innerHTML=rows.length?rows.map(s=>{const uid=s.user?.id||s.user_id,avatar=s.user?.avatar_url?`<img src="${esc(s.user.avatar_url)}" alt="">`:esc((s.user?.name||'?').slice(0,1).toUpperCase());const actions=[];if(s.current_banned)actions.push(`<button class="btn sx-mini" data-sanction="unban" data-user="${esc(uid)}" type="button">Débannir</button>`);if(s.current_muted)actions.push(`<button class="btn sx-mini" data-sanction="unmute" data-user="${esc(uid)}" type="button">Unmute</button>`);if(Number(s.warn_count)>0)actions.push(`<button class="btn danger sx-mini" data-sanction="clear-warnings" data-user="${esc(uid)}" type="button">Effacer ${Number(s.warn_count)} warn(s)</button>`);return `<div class="list-row"><div class="sx-sanction-user"><span class="sx-sanction-avatar">${avatar}</span><div><b>${esc(s.user?.name||uid)}</b><small>${esc(uid)} · #${esc(s.case_number||s.id)} · ${esc(s.action)}</small></div></div><small>${esc(s.reason||'Aucune raison')}</small><div class="sx-sanction-actions">${actions.join('')}</div></div>`}).join(''):'<div class="empty">Aucune sanction pour ce filtre.</div>';list.querySelectorAll('[data-sanction]').forEach(b=>b.onclick=()=>actionModal('Confirmer l’action',`Action ${b.dataset.sanction} sur ${b.dataset.user}.`,reason=>sanctionAction(b.dataset.user,b.dataset.sanction,reason)))}catch(e){toast(e.message,true)}};
  renderSanctions = function(){state.dirty=false;$('fields').innerHTML=section('Historique et actions de modération','Recherchez un utilisateur, consultez son état puis retirez une sanction active si nécessaire.',`<div class="sx-search-row"><div class="field"><label>Filtre</label><select id="sanctionFilter"><option value="all">Toutes</option><option value="ban">Bans</option><option value="mute">Mutes</option><option value="warn">Warns</option></select></div><div class="field"><label>ID Discord</label><input id="sanctionUserSearch" inputmode="numeric" placeholder="123456789…"></div><button id="sanctionSearch" class="btn" type="button">Rechercher</button></div><div id="sanctionList" class="list"><div class="empty">Chargement…</div></div>`);$('sanctionFilter').value=state.sanctionFilter;$('sanctionSearch').onclick=loadSanctions;$('sanctionUserSearch').addEventListener('keydown',e=>{if(e.key==='Enter')loadSanctions()});$('sanctionFilter').onchange=loadSanctions;loadSanctions()};

  const sxRenderTabBase=renderTab;
  renderTab = function(){
    ensureChrome();
    if(state.tab==='overview'){renderOverview();return}
    sxRenderTabBase();
    try{localStorage.setItem(sx.savedTabKey,state.tab)}catch(_){}
    if($('sxToolbarStatus'))$('sxToolbarStatus').textContent=`${tabMeta[state.tab]?.[0]||'SentriX'} · ${state.guildData?.guild?.name||''}`;
  };

  const sxSelectGuildBase=selectGuild;
  selectGuild = async function(value){
    try{return await sxSelectGuildBase(value)}catch(error){
      $('serverContent')?.classList.add('hidden');const empty=$('emptyState');if(empty){empty.classList.remove('hidden');empty.innerHTML=`<b>Impossible de charger ce serveur.</b><br>${esc(error.message||'Erreur inconnue')}<br><button id="sxRetryGuild" class="btn primary" type="button" style="margin-top:12px">Réessayer</button>`;$('sxRetryGuild').onclick=()=>selectGuild(value)}throw error
    }
  };

  document.addEventListener('click',event=>{
    const button=event.target.closest('#navigation button[data-tab]');
    if(!button)return;
    if(state.dirty && button.dataset.tab!==state.tab && !confirm('Des modifications ne sont pas enregistrées. Changer de page quand même ?')){event.preventDefault();event.stopImmediatePropagation()}
  },true);
  $('serverSelect')?.addEventListener('change',event=>{if(state.dirty && String(event.target.value)!==String(state.guildId) && !confirm('Des modifications ne sont pas enregistrées. Changer de serveur quand même ?')){event.stopImmediatePropagation();event.target.value=state.guildId}},true);
  document.addEventListener('keydown',event=>{
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();if(!$('saveBar')?.classList.contains('hidden'))save(event)}
    if(event.key==='/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName||'')){event.preventDefault();$('sxNavSearch')?.focus()}
    if(event.key==='Escape'){closeModal();$('sxProfilePopover')?.classList.add('hidden');$('sidebar')?.classList.remove('open')}
  });

  ensureChrome();
  const restore=()=>{if(!state.guildData)return;let saved='';try{saved=localStorage.getItem(sx.savedTabKey)||''}catch(_){}if(saved && (saved==='overview'||tabMeta[saved])){state.tab=saved;renderTab()}};
  setTimeout(restore,700);
})();
</script>
'''


def install(dashboard) -> bool:
    """Ajoute la couche MAX au document V60 contrôlé, avant le snapshot immuable."""
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v60-max"' in html:
        return True
    if getattr(dashboard, "_sentrix_dashboard_version", None) != "v60":
        logger.error("Dashboard V60 MAX refusé : le frontend V60 de base n'est pas actif.")
        return False
    if "</style>" not in html or "</body>" not in html:
        logger.error("Dashboard V60 MAX refusé : document incomplet.")
        return False
    html = html.replace("</style>", MAX_CSS + "\n</style>", 1)
    html = html.replace("</body>", MAX_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    dashboard._sentrix_dashboard_version = "v60-max"
    logger.info("Dashboard V60 MAX installé : contrôles avancés, embeds complets et modération active.")
    return True


__all__ = ["install", "MAX_CSS", "MAX_JS"]
