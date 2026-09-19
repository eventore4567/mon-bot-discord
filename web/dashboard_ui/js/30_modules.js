/* ---------- pages des modules (contenu repris tel quel au lot 1, refondu lot par lot) ---------- */
function messagePreviewBlock(key, fallback) {
  return `<div class="field full"><div class="label-row"><span class="label">Aperçu</span></div><div data-preview-for="${esc(key)}" data-fallback="${esc(fallback || '')}">${discordMessage({ content: fallback })}</div></div>`;
}
function bindPreviews(root = content()) {
  root.querySelectorAll('[data-preview-for]').forEach(box => {
    const src = root.querySelector(`[data-setting="${box.dataset.previewFor}"]`);
    if (!src) return;
    const paint = () => { box.innerHTML = discordMessage({ content: src.value || box.dataset.fallback }); };
    src.addEventListener('input', paint); paint();
  });
}

/* Accueil & Départs — même moteur que le bouton « Bienvenue » de /setup :
   guild_config (salon, message, image) + welcome_presentation_v2 (titre, avatar, compteur). */
const welcomePresentation = (force = false) => cached('welcome', () => gget('/welcome'), { force });
async function renderWelcome() {
  const s = settings();
  let pres = { title: 'Bienvenue sur {server}', show_avatar: true, show_member_count: true, default_text: 'Bienvenue {member} !' };
  try { pres = await welcomePresentation(); } catch (_) {}
  if (state.sub === 'departs') {
    content().innerHTML = `<div class="grid">${await moduleHead('goodbye', 'Message envoyé quand un membre quitte le serveur.', 'Départs')}${card('', '', `<div class="fields">${channelField('Salon', 'goodbye_channel', s.goodbye_channel, { full: true, hint: 'Le message de départ est envoyé dans ce salon.' })}<div class="field full"><div class="label-row"><label for="f-goodbye_message">Message</label><span class="counter"></span>${variablesButton('f-goodbye_message')}</div><textarea id="f-goodbye_message" data-setting="goodbye_message" maxlength="1000" rows="4" placeholder="**{username}** a quitté **{server}**.">${esc(s.goodbye_message || '')}</textarea></div>${previewBlock('goodbyePreview')}</div>`, 'full')}${advanced(card('Présentation', 'Partagée avec la bienvenue.', `<label class="switch-row"><span class="switch-copy"><b>Afficher l’avatar du membre</b><span>En miniature du message.</span></span><input class="switch" id="presAvatar" type="checkbox" ${pres.show_avatar ? 'checked' : ''}></label>`))}</div>`;
    bindEditable(); bindModuleButtons(); bindVariables(); bindChannelWarnings();
    bindPreview(content(), 'goodbyePreview', () => ({ embed: { title: 'Départ d’un membre', description: $('f-goodbye_message').value || '**{username}** a quitté **{server}**.', color: '#6b7280', thumbnail: $('presAvatar').checked ? 'avatar' : '', footer: 'SentriX' } }));
    $('presAvatar').onchange = () => savePresentation({ ...pres, show_avatar: $('presAvatar').checked });
    return;
  }
  content().innerHTML = `<div class="grid">${await moduleHead('welcome', 'Message envoyé quand un membre arrive.', 'Bienvenue')}${card('', '', `<div class="fields">${channelField('Salon de bienvenue', 'welcome_channel', s.welcome_channel, { full: true, hint: 'Choisissez le salon où SentriX enverra le message.' })}<div class="field full"><div class="label-row"><label for="presTitle">Titre</label></div><input id="presTitle" maxlength="256" value="${esc(pres.title || '')}" placeholder="Bienvenue sur {server}"></div><div class="field full"><div class="label-row"><label for="f-welcome_message">Message</label><span class="counter"></span>${variablesButton('f-welcome_message')}</div><textarea id="f-welcome_message" data-setting="welcome_message" maxlength="2000" rows="4" placeholder="${esc(pres.default_text || '')}">${esc(s.welcome_message || '')}</textarea></div>${previewBlock('welcomePreview')}</div><div class="toolbar"><button class="btn" type="button" id="welcomeTest">Envoyer un message test</button><small>Envoyé dans le salon choisi, adressé à vous seulement.</small></div>`, 'full')}${advanced(card('Image et présentation', '', `<div class="fields">${field('Grande image (HTTPS)', 'welcome_image_url', s.welcome_image_url || '', { type: 'url', full: true, placeholder: 'https://…', hint: 'Affichée sous le message.' })}</div><label class="switch-row"><span class="switch-copy"><b>Afficher l’avatar du membre</b><span>En miniature du message.</span></span><input class="switch" id="presAvatar" type="checkbox" ${pres.show_avatar ? 'checked' : ''}></label><label class="switch-row"><span class="switch-copy"><b>Afficher le nombre de membres</b><span>Un champ « Membres » sous le message.</span></span><input class="switch" id="presCount" type="checkbox" ${pres.show_member_count ? 'checked' : ''}></label>`))}</div>`;
  bindEditable(); bindModuleButtons(); bindVariables(); bindChannelWarnings();
  const compute = () => ({
    content: '{member}',
    embed: { title: $('presTitle').value || pres.default_title || 'Bienvenue sur {server}', description: $('f-welcome_message').value || pres.default_text || '', image: $('f-welcome_image_url').value, thumbnail: $('presAvatar').checked ? 'avatar' : '', fields: $('presCount').checked ? [{ name: 'Membres', value: '{member_count} membre(s)' }] : [], footer: 'SentriX' },
  });
  bindPreview(content(), 'welcomePreview', compute);
  /* Titre / avatar / compteur ont leur propre table : enregistrés à part, sans passer par la barre. */
  const persistPresentation = () => savePresentation({ title: $('presTitle').value, show_avatar: $('presAvatar').checked, show_member_count: $('presCount').checked });
  $('presTitle').addEventListener('change', persistPresentation);
  $('presAvatar').onchange = persistPresentation; $('presCount').onchange = persistPresentation;
  $('welcomeTest').onclick = async () => {
    if (hasDirty()) return toast('Enregistrez d’abord vos modifications.', true);
    const channel = channelName(s.welcome_channel);
    if (!channel) return toast('Choisissez d’abord un salon de bienvenue.', true);
    if (!(await confirmDialog({ title: 'Envoyer un message test ?', body: `Le message de bienvenue sera envoyé dans ${channel}, adressé à vous.`, confirm: 'Envoyer' }))) return;
    const b = $('welcomeTest'); b.disabled = true;
    try { const r = await gpost('/welcome/test', {}); toast(r.message || 'Test envoyé.'); } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
  };
}
async function savePresentation(values) {
  try { await gpost('/welcome', { title: values.title, show_avatar: values.show_avatar, show_member_count: values.show_member_count }, 'PUT'); invalidate('welcome'); toast('Présentation enregistrée.'); }
  catch (e) { toast(e.message, true); }
}

/* Niveaux */
async function renderLevels() {
  const s = settings(), m = metrics();
  content().innerHTML = `<div class="grid">${await moduleHead('levels', `XP gagné en discutant. ${plural(m.profiles, 'membre')} avec une progression.`)}${card('', '', `<div class="fields">${field('Salon des annonces de niveau', 'level_channel', '', { select: channelOptions(s.level_channel), hint: 'Vide = répondre dans le salon du message.' })}${field('Message de niveau', 'level_message', s.level_message || '', { textarea: true, full: true, max: 1000, placeholder: 'Bravo {user}, niveau {level} !' })}${messagePreviewBlock('level_message', 'Bravo {user}, niveau {level} !')}</div>`, 'full')}${advanced(card('Multiplicateur XP', '1 = normal, 2 = deux fois plus vite.', `<div class="fields">${field('Multiplicateur', 'xp_multiplier', s.xp_multiplier ?? 1, { type: 'number', min: .1, max: 5, step: .1 })}</div>`))}</div>`;
  bindEditable(); bindModuleButtons(); bindPreviews();
}

/* Économie */
async function renderEconomy() {
  const m = metrics();
  content().innerHTML = `<div class="grid">${await moduleHead('economy', `Argent, banque et boutique. ${plural(m.economy_accounts, 'compte')} enregistré(s).`)}${card('Accès aux commandes', 'Choisissez qui peut utiliser chaque commande économique.', `<div class="toolbar"><button class="btn" type="button" data-go="access">Ouvrir Commandes & accès</button></div>`, 'full')}</div>`;
  bindModuleButtons();
}

/* Rôles */
async function renderRoles() {
  const s = settings();
  content().innerHTML = `<div class="grid">${await moduleHead('roles', 'Rôles donnés automatiquement par SentriX.')}${card('', '', `<div class="fields">${field('Rôle donné à l’arrivée', 'autorole', '', { select: roleOptions(s.autorole) })}${field('Rôle modérateur', 'mod_role', '', { select: roleOptions(s.mod_role), hint: 'Accès aux commandes de modération.' })}</div>`, 'full')}${advanced(card('Rôles membres', '', `<div class="fields">${field('Rôle membre', 'member_role', '', { select: roleOptions(s.member_role) })}${field('Rôle booster', 'booster_role', '', { select: roleOptions(s.booster_role) })}${field('Rôle administrateur', 'admin_role', '', { select: roleOptions(s.admin_role) })}</div>`) + card('Sanctions', 'Rôles optionnels donnés par +warn / +mute.', `<div class="fields">${field('Rôle après un avertissement', 'warn_role', '', { select: roleOptions(s.warn_role) })}${field('Rôle pendant un mute', 'mute_role', '', { select: roleOptions(s.mute_role) })}</div>`) + card('Vérification', '', `<div class="fields">${field('Rôle vérifié', 'verify_role', '', { select: roleOptions(s.verify_role) })}${field('Rôle en attente de vérification', 'verification_role', '', { select: roleOptions(s.verification_role) })}</div>`))}</div>`;
  bindEditable(); bindModuleButtons();
}

/* Sécurité : protections / vérification / sanctions */
async function renderSecurity() {
  if (state.sub === 'verification') return renderVerification();
  if (state.sub === 'sanctions') return renderSanctions();
  const a = state.guild?.automod || {}, s = settings();
  let d = null; try { d = await diagnostics(); } catch (_) {}
  const missing = (d?.permissions || []).filter(p => !p.granted);
  content().innerHTML = `<div class="grid">${await moduleHead('automod', 'Protections automatiques. Activez seulement ce dont votre serveur a besoin.', 'Protections')}${missing.length ? `<div class="notice warn full">SentriX n’a pas toutes les permissions nécessaires : ${esc(missing.map(p => p.name).join(', '))}. Certaines protections ne pourront pas agir.</div>` : ''}${card('', '', AUTOMOD.map(([k, l, c]) => switchRow(l, k, Boolean(a[k]), c)).join(''), 'full')}${advanced(card('Politique de sécurité', '', `<div class="fields">${field('Niveau de sécurité', 'security_level', '', { select: ['faible', 'moyen', 'eleve'].map(v => `<option value="${v}" ${s.security_level === v ? 'selected' : ''}>${v === 'eleve' ? 'Élevé' : v[0].toUpperCase() + v.slice(1)}</option>`).join('') })}${field('Avertissements avant ban automatique', 'warn_ban_threshold', s.warn_ban_threshold ?? 0, { type: 'number', min: 0, max: 20, hint: '0 = jamais de ban automatique.' })}</div>` + switchRow('Escalade AutoMod', 'escalation', Boolean(a.escalation), 'Augmente progressivement les sanctions.')))}</div>`;
  bindEditable(); bindModuleButtons();
}

async function renderVerification() {
  let v; try { v = await cached('verification-v6', () => gget('/verification-v6')); } catch (e) { return errorView(e); }
  const s = settings();
  content().innerHTML = `<div class="grid">${card('Vérification Discord', 'Le membre lit le règlement, réussit le CAPTCHA et reçoit le rôle.', `<div class="fields">${field('Salon de vérification', '', '', { id: 'verifyChannel', select: channelOptions(v.channel_id || s.verification_channel || '') })}${field('Rôle après réussite', '', '', { id: 'verifyRole', select: roleOptions(v.role_id || s.verify_role || '') })}${field('Titre du panneau', '', v.title || '', { id: 'verifyTitle', full: true })}${field('Règlement', '', v.rules_text || '', { id: 'verifyRules', textarea: true, max: 4000, rows: 8, full: true })}${field('Image HTTPS (facultative)', '', v.image_url || '', { id: 'verifyImage', type: 'url', full: true, placeholder: 'https://…' })}${field('Tentatives CAPTCHA', '', s.verify_captcha_max_attempts ?? 3, { id: 'verifyTries', type: 'number', min: 1, max: 10 })}</div><label class="switch-row"><span class="switch-copy"><b>CAPTCHA obligatoire</b><span>Demande un code visuel avant d’attribuer le rôle.</span></span><input class="switch" id="verifyCaptcha" type="checkbox" ${v.captcha_enabled ?? s.verify_captcha_enabled ? 'checked' : ''}></label><div class="toolbar"><button class="btn" type="button" id="verifySave">Enregistrer</button><button class="btn primary" type="button" id="verifyPublish">Enregistrer et publier sur Discord</button>${v.jump_url ? `<a class="btn ghost" href="${esc(v.jump_url)}" target="_blank" rel="noopener">Voir le panneau</a>` : ''}<span class="badge ${v.published ? 'ok' : 'warn'}">${v.published ? 'Publié' : 'Pas encore publié'}</span></div>`, 'full')}${card('Aperçu', '', `<div id="verifyPreview"></div>`, 'full')}</div>`;
  const paint = () => { $('verifyPreview').innerHTML = discordMessage({ embed: { title: $('verifyTitle').value || 'Vérification', description: $('verifyRules').value || 'Votre règlement apparaîtra ici.', image: $('verifyImage').value } }); };
  ['verifyTitle', 'verifyRules', 'verifyImage'].forEach(id => $(id).addEventListener('input', paint)); paint();
  const save = async publish => {
    const b = $(publish ? 'verifyPublish' : 'verifySave'); b.disabled = true;
    try {
      await v62Action({ action: 'verification_save', channel_id: $('verifyChannel').value, role_id: $('verifyRole').value, rules_text: $('verifyRules').value, image_url: $('verifyImage').value, captcha_enabled: $('verifyCaptcha').checked, captcha_max_attempts: $('verifyTries').value, publish: false });
      if (publish) { const r = await gpost('/verification-v6/publish', { title: $('verifyTitle').value, rules_text: $('verifyRules').value, image_url: $('verifyImage').value }); toast(r.message || 'Vérification publiée.'); }
      invalidate('verification-v6');
      await reloadGuild();
      await render();
    } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
  };
  $('verifySave').onclick = () => save(false);
  $('verifyPublish').onclick = () => save(true);
}

async function renderSanctions() {
  let data; try { data = await gget('/sanctions'); } catch (e) { return errorView(e); }
  const rows = data.sanctions || data.items || [];
  content().innerHTML = `<div class="grid"><section class="card full"><div class="card-head"><div><h2>Sanctions</h2><p>Historique des sanctions appliquées par SentriX.</p></div><span class="badge blue">${plural(rows.length, 'résultat')}</span></div><div class="toolbar"><input class="search-input" id="sanctionSearch" type="search" placeholder="Rechercher un ID, une action, une raison…"><select class="search-input" id="sanctionType"><option value="">Toutes les actions</option>${['ban', 'mute', 'warn', 'kick', 'unban', 'unmute'].map(x => `<option>${x}</option>`).join('')}</select><button class="btn ghost" type="button" data-go="dm">Envoyer un message privé</button></div><div class="list" id="sanctionList"></div></section></div>`;
  const draw = () => {
    const q = $('sanctionSearch').value.toLowerCase(), t = $('sanctionType').value;
    const items = rows.filter(x => (!t || String(x.action || x.type || '') === t) && (!q || JSON.stringify(x).toLowerCase().includes(q)));
    $('sanctionList').innerHTML = items.length ? items.map(x => {
      const uid = x.user_id || x.target_id || x.member_id || '—', action = x.action || x.type || 'action', reason = x.reason || 'Aucune raison';
      const reversible = action === 'ban' ? 'unban' : action === 'mute' ? 'unmute' : action === 'warn' ? 'clear-warnings' : '';
      const labels = { unban: 'Débannir', unmute: 'Lever le mute', 'clear-warnings': 'Effacer les avertissements' };
      return `<div class="row"><div class="row-main"><b>${esc(action)} · ${esc(uid)}</b><small>${esc(reason)}${x.created_at ? ' · ' + when(x.created_at) : ''}</small></div><div class="row-actions">${reversible ? `<button class="btn sm" type="button" data-sanction="${reversible}" data-user="${esc(uid)}">${labels[reversible]}</button>` : ''}</div></div>`;
    }).join('') : emptyState('Aucune sanction', 'Les sanctions appliquées par SentriX apparaîtront ici.');
    $('sanctionList').querySelectorAll('[data-sanction]').forEach(b => b.onclick = async () => {
      const reason = await promptDialog({ title: b.textContent, label: 'Raison', value: 'Action depuis le dashboard SentriX', confirm: b.textContent });
      if (!reason) return;
      try { const r = await gpost(`/sanctions/${encodeURIComponent(b.dataset.user)}/${encodeURIComponent(b.dataset.sanction)}`, { reason }); toast(r.message || 'Action appliquée.'); await renderSanctions(); } catch (e) { toast(e.message, true); }
    });
  };
  $('sanctionSearch').oninput = draw; $('sanctionType').onchange = draw; draw();
  bindModuleButtons();
}

/* Logs */
async function renderLogs() {
  const s = settings();
  content().innerHTML = `<div class="grid">${await moduleHead('logs', 'Tout ce qui se passe sur le serveur, écrit dans un salon.')}${card('', '', `<div class="fields">${field('Salon des logs', 'log_channel', '', { select: channelOptions(s.log_channel), full: true, hint: 'Reçoit tous les logs qui n’ont pas de salon dédié.' })}</div>`, 'full')}${advanced(card('Un salon par type', 'Vide = salon des logs général.', `<div class="fields">${LOG_TYPES.map(([l, k]) => field(l, k, '', { select: channelOptions(s[k]) })).join('')}</div>`))}</div>`;
  bindEditable(); bindModuleButtons();
}

/* Tickets */
async function renderTickets() {
  let data; try { data = await v62(); } catch (e) { return errorView(e); }
  const panels = data.tickets?.panels || [], types = data.tickets?.types || [];
  const panel = panels[0] || {};
  const colorHex = p => p?.color ? '#' + Number(p.color).toString(16).padStart(6, '0') : '#4DA3FF';
  const head = await moduleHead('tickets', 'Panneaux, types et publication du système Tickets.');
  if (!panels.length && !state.ticketCreate) {
    content().innerHTML = `<div class="grid">${head}${emptyState('Aucun système de tickets configuré', 'Créez votre premier panneau : les membres cliqueront dessus pour ouvrir un ticket.', { id: 'ticketCreate', label: 'Créer mon premier panneau' })}</div>`;
    bindModuleButtons();
    content().querySelector('[data-empty-action="ticketCreate"]').onclick = () => { state.ticketCreate = true; renderTickets(); };
    return;
  }
  content().innerHTML = `<div class="grid">${head}${card('Panneau', 'Créez un panneau ou modifiez un panneau existant.', `<div class="fields"><div class="field"><label for="ticketPanelPick">Panneau</label><select id="ticketPanelPick"><option value="">Nouveau panneau</option>${panels.map(p => `<option value="${esc(p.id)}">#${esc(p.id)} · ${esc(p.name || p.title || 'Panneau')}</option>`).join('')}</select></div><div class="field"><label for="ticketName">Nom interne</label><input id="ticketName" value="${esc(panel.name || 'Support')}"></div><div class="field full"><label for="ticketTitle">Titre public</label><input id="ticketTitle" value="${esc(panel.title || 'Support')}"></div><div class="field full"><label for="ticketDescription">Description</label><textarea id="ticketDescription" maxlength="2000">${esc(panel.description || 'Choisissez une option ci-dessous pour ouvrir un ticket.')}</textarea></div><div class="field"><label for="ticketChannel">Salon du panneau</label><select id="ticketChannel">${channelOptions(panel.channel_id || '')}</select></div><div class="field"><label for="ticketStyle">Affichage</label><select id="ticketStyle"><option value="select">Menu déroulant</option><option value="button" ${panel.style === 'button' ? 'selected' : ''}>Boutons</option></select></div><div class="field"><label for="ticketMax">Limite par membre</label><input id="ticketMax" type="number" min="1" max="20" value="${Number(panel.max_per_member || 1)}"></div><div class="field"><label for="ticketColor">Couleur</label><input id="ticketColor" type="color" value="${colorHex(panel)}"></div></div><div class="toolbar"><button class="btn primary" type="button" id="ticketSave">Enregistrer</button><button class="btn" type="button" id="ticketPublish" ${panel.id ? '' : 'disabled'}>Publier / mettre à jour</button></div>`, 'full')}<section class="card full"><div class="card-head"><div><h2>Types de tickets</h2><p>Gérés par le moteur Tickets existant (commandes et /setup).</p></div><span class="badge blue">${number(types.length)}</span></div><div class="list">${types.length ? types.map(t => `<div class="row"><div class="row-main"><b>${esc(t.name || 'Type')}</b><small>Panneau #${esc(t.panel_id)}${t.description ? ' · ' + esc(t.description) : ''}</small></div><span class="badge ${t.use_form ? 'blue' : ''}">${t.use_form ? 'Formulaire' : 'Direct'}</span></div>`).join('') : emptyState('Aucun type de ticket', 'Les types se créent depuis Discord pour l’instant.')}</div></section></div>`;
  bindModuleButtons();
  const fill = p => { $('ticketName').value = p?.name || 'Support'; $('ticketTitle').value = p?.title || 'Support'; $('ticketDescription').value = p?.description || 'Choisissez une option ci-dessous pour ouvrir un ticket.'; $('ticketChannel').value = String(p?.channel_id || ''); $('ticketStyle').value = p?.style === 'button' ? 'button' : 'select'; $('ticketMax').value = p?.max_per_member || 1; $('ticketColor').value = colorHex(p); $('ticketPublish').disabled = !p?.id; };
  $('ticketPanelPick').onchange = () => fill(panels.find(p => String(p.id) === $('ticketPanelPick').value));
  if (panel.id) { $('ticketPanelPick').value = String(panel.id); fill(panel); }
  $('ticketSave').onclick = async () => { try { const selected = panels.find(p => String(p.id) === $('ticketPanelPick').value); await v62Action({ action: 'ticket_panel_save', panel_id: selected?.id || null, name: $('ticketName').value, title: $('ticketTitle').value, description: $('ticketDescription').value, channel_id: $('ticketChannel').value, style: $('ticketStyle').value, max_per_member: $('ticketMax').value, color: $('ticketColor').value, enabled: true }); state.ticketCreate = false; await renderTickets(); } catch (e) { toast(e.message, true); } };
  $('ticketPublish').onclick = async () => { try { const selected = panels.find(p => String(p.id) === $('ticketPanelPick').value) || panel; if (!selected?.id) return; await v62Action({ action: 'ticket_send', panel_id: selected.id }); } catch (e) { toast(e.message, true); } };
}

/* Notifications */
async function renderNotifications() {
  const items = state.guild?.social_notifications || [];
  content().innerHTML = `<div class="grid">${await moduleHead('notifications', 'Annonce les nouvelles vidéos et lives dans un salon.')}<section class="card full"><div class="card-head"><div><h2>Sources suivies</h2><p>${plural(items.length, 'source')}</p></div><button class="btn primary" type="button" id="notifAdd">Ajouter une source</button></div><div class="list">${items.length ? items.map(n => `<div class="row"><div class="row-main"><b>${esc(n.platform || 'Source')} · ${esc(channelName(n.discord_channel_id) || 'salon introuvable')}</b><small>${esc(n.source_url || '')}${n.role_id ? ' · ' + esc(roleName(n.role_id)) : ''}</small></div><div class="row-actions">${badge(n.enabled === 0 ? 'inactive' : 'active')}<button class="btn sm danger" type="button" data-del-notif="${esc(n.id)}">Supprimer</button></div></div>`).join('') : emptyState('Aucune source suivie', 'Ajoutez une chaîne YouTube, Twitch, TikTok… SentriX annoncera chaque nouveauté.')}</div></section></div>`;
  bindModuleButtons();
  $('notifAdd').onclick = () => openModal({
    title: 'Ajouter une source',
    body: `<div class="fields"><div class="field full"><label for="notifUrl">Lien de la chaîne</label><input id="notifUrl" type="url" placeholder="https://www.youtube.com/@…"><small>YouTube, Twitch, TikTok, Instagram, X, Kick…</small></div><div class="field"><label for="notifChannel">Salon d’annonce</label><select id="notifChannel">${channelOptions('')}</select></div><div class="field"><label for="notifRole">Rôle à prévenir</label><select id="notifRole">${roleOptions('')}</select></div><div class="field full"><label for="notifText">Texte de l’annonce (facultatif)</label><textarea id="notifText" maxlength="1000" placeholder="Nouvelle vidéo !"></textarea></div><div class="field full"><label for="notifImage">Image HTTPS (facultative)</label><input id="notifImage" type="url" placeholder="https://…"></div></div>`,
    actions: [{ label: 'Annuler' }, { label: 'Ajouter', kind: 'primary', keep: true, onClick: async () => {
      try { await gpost('/notifications', { source_url: $('notifUrl').value, discord_channel_id: $('notifChannel').value, role_id: $('notifRole').value, custom_text: $('notifText').value, image_url: $('notifImage').value }); closeModal(); toast('Source ajoutée.'); await reloadGuild(); await render(); } catch (e) { toast(e.message, true); }
    } }],
  });
  content().querySelectorAll('[data-del-notif]').forEach(b => b.onclick = async () => {
    if (!(await confirmDialog({ title: 'Supprimer cette source ?', body: 'SentriX n’annoncera plus cette chaîne.', confirm: 'Supprimer', danger: true }))) return;
    try { await gdel(`/notifications/${encodeURIComponent(b.dataset.delNotif)}`); toast('Source supprimée.'); await reloadGuild(); await render(); } catch (e) { toast(e.message, true); }
  });
}

/* Automatisation : réactions automatiques (API growth V12) */
let reactEmojis = [];
async function renderAutomation() {
  let d; try { d = await gget('/automation/reactions'); } catch (e) { return errorView(e); }
  const items = d.items || [];
  content().innerHTML = `<div class="grid"><section class="card full"><div class="card-head"><div><h2>Réactions automatiques</h2><p>SentriX ajoute des emojis aux messages d’un salon, à tous ou selon un mot-clé.</p></div><button class="btn primary" type="button" id="reactCreate">Ajouter une règle</button></div><div class="list">${items.length ? items.map(r => `<div class="row"><div class="row-main"><b>${esc(channelName(r.channel_id) || '#' + (r.channel_name || r.channel_id))}</b><small>${r.mode === 'keyword' ? 'Mot-clé « ' + esc(r.keyword) + ' »' : 'Tous les messages'} · ${(r.emojis || []).map(esc).join(' ')}</small></div><div class="row-actions"><label class="switch-row" style="padding:4px 8px"><input class="switch" type="checkbox" data-react-toggle="${r.id}" ${r.enabled ? 'checked' : ''} aria-label="Activer la règle"></label><button class="btn sm danger" type="button" data-react-del="${r.id}">Supprimer</button></div></div>`).join('') : emptyState('Aucune réaction automatique', 'Exemple : ajouter 👍 et 👎 sous chaque suggestion.')}</div></section></div>`;
  $('reactCreate').onclick = () => {
    reactEmojis = [];
    const drawEmojis = () => { const box = $('reactEmojiList'); if (box) box.innerHTML = reactEmojis.length ? reactEmojis.map((x, i) => `<button class="btn sm" type="button" data-react-rm="${i}">${esc(x)} ×</button>`).join('') : '<small>Aucun emoji choisi.</small>'; box?.querySelectorAll('[data-react-rm]').forEach(b => b.onclick = () => { reactEmojis.splice(Number(b.dataset.reactRm), 1); drawEmojis(); }); };
    const readEmojis = () => { const el = $('reactEmojiInput'); for (const x of (el.value || '').trim().split(/[\s,]+/).filter(Boolean)) { if (reactEmojis.length >= 8) break; if (!reactEmojis.includes(x)) reactEmojis.push(x); } el.value = ''; drawEmojis(); };
    openModal({
      title: 'Nouvelle réaction automatique',
      body: `<div class="fields"><div class="field"><label for="reactChannel">Salon</label><select id="reactChannel">${channelOptions('')}</select></div><div class="field"><label for="reactMode">Quand ?</label><select id="reactMode"><option value="all">Tous les messages</option><option value="keyword">Si le message contient un mot</option></select></div><div class="field full"><label for="reactKeyword">Mot-clé (si nécessaire)</label><input id="reactKeyword" maxlength="80" placeholder="gg"></div><div class="field full"><label for="reactEmojiInput">Emojis (8 maximum)</label><div class="toolbar"><input class="search-input" id="reactEmojiInput" placeholder="❤️ 🔥 👀 ou <:nom:123…>"><button class="btn" type="button" id="reactEmojiAdd">Ajouter</button></div><div class="toolbar" id="reactEmojiList"></div></div></div><label class="switch-row"><span class="switch-copy"><b>Ignorer les bots</b><span>Évite les boucles de réactions.</span></span><input class="switch" id="reactIgnoreBots" type="checkbox" checked></label>`,
      actions: [{ label: 'Annuler' }, { label: 'Créer la règle', kind: 'primary', keep: true, onClick: async () => {
        readEmojis();
        if (!$('reactChannel').value) return toast('Choisissez un salon.', true);
        if (!reactEmojis.length) return toast('Choisissez au moins un emoji.', true);
        try { await gpost('/automation/reactions', { action: 'create', channel_id: $('reactChannel').value, mode: $('reactMode').value, keyword: $('reactKeyword').value.trim(), emojis: reactEmojis, ignore_bots: $('reactIgnoreBots').checked }); closeModal(); toast('Réaction automatique créée.'); await renderAutomation(); } catch (e) { toast(e.message, true); }
      } }],
      onOpen: () => { drawEmojis(); $('reactEmojiAdd').onclick = readEmojis; $('reactEmojiInput').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); readEmojis(); } }; },
    });
  };
  content().querySelectorAll('[data-react-toggle]').forEach(x => x.onchange = async () => { try { await gpost('/automation/reactions', { action: 'toggle', id: Number(x.dataset.reactToggle), enabled: x.checked }); } catch (e) { x.checked = !x.checked; toast(e.message, true); } });
  content().querySelectorAll('[data-react-del]').forEach(x => x.onclick = async () => { if (!(await confirmDialog({ title: 'Supprimer cette règle ?', body: 'SentriX cessera d’ajouter ces réactions.', confirm: 'Supprimer', danger: true }))) return; try { await gpost('/automation/reactions', { action: 'delete', id: Number(x.dataset.reactDel) }); await renderAutomation(); } catch (e) { toast(e.message, true); } });
}
