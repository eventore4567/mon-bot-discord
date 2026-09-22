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
   guild_config (salon, message, image) + welcome_presentation_v2 (type, titre, avatar, compteur). */
const welcomePresentation = (force = false) => cached('welcome', () => gget('/welcome'), { force });
const GOODBYE_DEFAULT = '**{username}** a quitté **{server}**.';
function messageTypeSwitch(mode, key = 'mode') {
  return `<div class="field full"><span class="label">Type de message</span><div class="seg" role="radiogroup" aria-label="Type de message" data-mode-key="${esc(key)}"><button type="button" role="radio" aria-checked="${mode !== 'embed'}" data-mode="text" class="${mode !== 'embed' ? 'active' : ''}">Message simple</button><button type="button" role="radio" aria-checked="${mode === 'embed'}" data-mode="embed" class="${mode === 'embed' ? 'active' : ''}">Embed</button></div><small>${mode === 'embed' ? 'Un encadré avec titre, avatar et image.' : 'Un message texte, comme un membre l’écrirait.'}</small></div>`;
}
async function renderWelcome() {
  const s = settings();
  const sv = key => (key in state.dirty.settings ? state.dirty.settings[key] : s[key]);  // brouillon non enregistré conservé au redessin
  let pres = { title: 'Bienvenue sur {server}', show_avatar: true, show_member_count: true, mode: 'embed', default_text: 'Bienvenue {member} !' };
  try { pres = { ...pres, ...(await welcomePresentation()) }; } catch (_) {}
  const draft = state.dirty.welcome || {};
  const goodbyeMode = draft.goodbye_mode || pres.goodbye_mode || 'embed';
  if (state.sub === 'departs') {
    const embedMode = goodbyeMode === 'embed';
    content().innerHTML = `<div class="grid">${await moduleHead('goodbye', 'Message envoyé quand un membre quitte le serveur.', 'Départs')}${card('', '', `<div class="fields">${channelField('Salon des départs', 'goodbye_channel', sv('goodbye_channel'), { full: true, embed: embedMode, hint: 'Le message de départ est envoyé dans ce salon.' })}${messageTypeSwitch(goodbyeMode, 'goodbye_mode')}<div class="field full"><div class="label-row"><label for="f-goodbye_message">Message</label><span class="counter"></span>${variablesButton('f-goodbye_message')}</div><textarea id="f-goodbye_message" data-setting="goodbye_message" maxlength="1000" rows="4" placeholder="${esc(GOODBYE_DEFAULT)}">${esc(sv('goodbye_message') || '')}</textarea></div>${previewBlock('goodbyePreview')}</div>`, 'full')}${embedMode ? advanced(card('Présentation', 'Réglage partagé avec la bienvenue.', `<label class="switch-row"><span class="switch-copy"><b>Afficher l’avatar du membre</b><span>En miniature de l’encadré.</span></span><input class="switch" data-welcome="show_avatar" type="checkbox" ${(draft.show_avatar ?? pres.show_avatar) ? 'checked' : ''}></label>`)) : ''}</div>`;
    bindEditable(); bindModuleButtons(); bindVariables(); bindChannelWarnings(); bindModeSwitch();
    bindPreview(content(), 'goodbyePreview', () => {
      const text = $('f-goodbye_message').value || GOODBYE_DEFAULT;
      const avatar = content().querySelector('[data-welcome="show_avatar"]')?.checked ?? pres.show_avatar;
      return embedMode ? { embed: { title: 'Départ d’un membre', description: text, color: '#6b7280', thumbnail: avatar ? 'avatar' : '', footer: 'SentriX' } } : { content: text };
    });
    return;
  }
  const mode = draft.mode || pres.mode || 'embed';
  const embedMode = mode === 'embed';
  const channelChosen = Boolean(sv('welcome_channel') && channelName(sv('welcome_channel')));
  content().innerHTML = `<div class="grid">${await moduleHead('welcome', 'Message envoyé quand un membre arrive.', 'Bienvenue')}${card('', '', `<div class="fields">${channelField('Salon de bienvenue', 'welcome_channel', sv('welcome_channel'), { full: true, embed: embedMode, hint: 'Le message est envoyé dans ce salon, avec une mention du nouveau membre.' })}${messageTypeSwitch(mode)}${embedMode ? `<div class="field full"><div class="label-row"><label for="f-welcome-title">Titre de l’encadré</label>${variablesButton('f-welcome-title')}</div><input id="f-welcome-title" data-welcome="title" maxlength="256" value="${esc(draft.title ?? pres.title ?? '')}" placeholder="Bienvenue sur {server}"></div>` : ''}<div class="field full"><div class="label-row"><label for="f-welcome_message">Message</label><span class="counter"></span>${variablesButton('f-welcome_message')}</div><textarea id="f-welcome_message" data-setting="welcome_message" maxlength="2000" rows="4" placeholder="${esc(pres.default_text || '')}">${esc(sv('welcome_message') || '')}</textarea></div>${previewBlock('welcomePreview')}</div><div class="toolbar"><button class="btn" type="button" id="welcomeTest" ${channelChosen ? '' : 'disabled'}>Envoyer un message test</button><small id="welcomeTestHint">${channelChosen ? `Envoyé dans ${esc(channelName(sv('welcome_channel')))}, visible de tous mais sans mention.` : 'Choisissez un salon et enregistrez pour pouvoir tester.'}</small></div>`, 'full')}${embedMode ? advanced(card('Image et présentation', '', `<div class="fields">${field('Grande image (HTTPS)', 'welcome_image_url', sv('welcome_image_url') || '', { type: 'url', full: true, placeholder: 'https://…', hint: 'Affichée sous le message.' })}</div><label class="switch-row"><span class="switch-copy"><b>Afficher l’avatar du membre</b><span>En miniature de l’encadré.</span></span><input class="switch" data-welcome="show_avatar" type="checkbox" ${(draft.show_avatar ?? pres.show_avatar) ? 'checked' : ''}></label><label class="switch-row"><span class="switch-copy"><b>Afficher le nombre de membres</b><span>Un champ « Membres » sous le message.</span></span><input class="switch" data-welcome="show_member_count" type="checkbox" ${(draft.show_member_count ?? pres.show_member_count) ? 'checked' : ''}></label>`)) : ''}</div>`;
  bindEditable(); bindModuleButtons(); bindVariables(); bindChannelWarnings(); bindModeSwitch();
  const compute = () => {
    const text = $('f-welcome_message').value || pres.default_text || '';
    if (!embedMode) return { content: '{member}\n' + text };
    const avatar = content().querySelector('[data-welcome="show_avatar"]')?.checked ?? pres.show_avatar;
    const count = content().querySelector('[data-welcome="show_member_count"]')?.checked ?? pres.show_member_count;
    const members = Number(state.guild?.guild?.members || 0);
    return { content: '{member}', embed: { title: $('f-welcome-title').value || pres.default_title || 'Bienvenue sur {server}', description: text, image: $('f-welcome_image_url')?.value || '', thumbnail: avatar ? 'avatar' : '', fields: count ? [{ name: 'Membres', value: `${members} membre${members > 1 ? 's' : ''}` }] : [], footer: 'SentriX' } };
  };
  bindPreview(content(), 'welcomePreview', compute);
  $('welcomeTest').onclick = async () => {
    if (hasDirty()) return toast('Enregistrez d’abord vos modifications, puis relancez le test.', true);
    if (!(await confirmDialog({ title: 'Envoyer un message test ?', body: `Le message de bienvenue sera envoyé dans ${channelName(sv('welcome_channel'))}, sans mentionner personne.`, confirm: 'Envoyer' }))) return;
    const b = $('welcomeTest'); b.disabled = true;
    try { const r = await gpost('/welcome/test', {}); toast(r.message || 'Message test envoyé.'); } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
  };
}
/* Le type (simple / embed) change la forme du formulaire : on mémorise le brouillon puis on
   redessine la page ; l'enregistrement passe par la barre comme les autres champs. */
function bindModeSwitch(root = content()) {
  root.querySelectorAll('[data-mode]').forEach(b => b.onclick = async () => {
    if (b.classList.contains('active')) return;
    const draft = {};
    root.querySelectorAll('[data-welcome]').forEach(el => { draft[el.dataset.welcome] = readControl(el); });
    Object.assign(state.dirty.welcome, draft);
    markDirty('welcome', b.closest('[data-mode-key]')?.dataset.modeKey || 'mode', b.dataset.mode);
    await render();
  });
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

/* Tickets — cohérence panneau ⇄ types (le redesign complet arrive au lot 5).
   Un type appartient à UN panneau ; la publication ne regarde que le panneau sélectionné. */
const BUTTON_STYLES = [['bleu', 'Bleu'], ['gris', 'Gris'], ['vert', 'Vert'], ['rouge', 'Rouge']];
async function renderTickets() {
  // Les types peuvent avoir été créés depuis Discord : on relit toujours l'état réel.
  let data; try { data = await v62(true); } catch (e) { return errorView(e); }
  const panels = data.tickets?.panels || [], types = data.tickets?.types || [];
  const countFor = id => types.filter(t => String(t.panel_id) === String(id)).length;
  const head = '';
  const editingPanel = Boolean(state.ticketEditorOpen || state.ticketCreate);

  if (!editingPanel && panels.length) {
    content().innerHTML = `<div class="grid ticket-page ticket-panels-home">
      <section class="card full ticket-panels-card">
        <div class="card-head">
          <div><h2>Panneaux de tickets</h2><p>Choisissez un panneau à modifier. Les réglages détaillés s’ouvrent dans une page interne séparée.</p></div>
          <button class="btn primary" id="ticketCreateOpen" type="button">Nouveau panneau</button>
        </div>
        <div class="ticket-panel-list">
          ${panels.map(p => {
            const n = countFor(p.id);
            const published = Boolean(p.message_id);
            const channel = channelName(p.channel_id) || (p.channel_id ? 'salon introuvable' : 'aucun salon');
            return `<article class="ticket-panel-row">
              <div class="ticket-panel-main">
                <b>${esc(p.title || p.name || 'Panneau')}</b>
                <small>${esc(p.name || 'Support')} · ${plural(n, 'type')} · ${esc(channel)}</small>
              </div>
              <span class="badge ${published ? 'ok' : 'warn'}">${published ? 'Publié' : 'Non publié'}</span>
              <button class="btn sm" type="button" data-ticket-panel-open="${esc(p.id)}">Configurer</button>
            </article>`;
          }).join('')}
        </div>
      </section>
    </div>`;
    $('ticketCreateOpen').onclick = () => {
      state.ticketPanelId = null;
      state.ticketCreate = true;
      state.ticketEditorOpen = true;
      render({ navigation: true });
    };
    content().querySelectorAll('[data-ticket-panel-open]').forEach(b => b.onclick = () => {
      state.ticketPanelId = b.dataset.ticketPanelOpen;
      state.ticketCreate = false;
      state.ticketEditorOpen = true;
      render({ navigation: true });
    });
    return;
  }

  if (!panels.length && !state.ticketCreate) {
    content().innerHTML = `<div class="grid ticket-page">${head}${emptyState('Vous n’avez pas encore configuré vos tickets', 'Créez un premier panneau : les membres cliqueront dessus pour ouvrir un ticket.', { id: 'ticketCreate', label: 'Créer mon premier panneau' })}</div>`;
    bindModuleButtons();
    content().querySelector('[data-empty-action="ticketCreate"]').onclick = () => {
      state.ticketPanelId = null;
      state.ticketCreate = true;
      state.ticketEditorOpen = true;
      render({ navigation: true });
    };
    return;
  }
  // Panneau sélectionné : celui mémorisé, sinon celui qui a le plus de types, sinon le premier.
  let selected = panels.find(p => String(p.id) === String(state.ticketPanelId));
  if (!selected && !state.ticketCreate) selected = [...panels].sort((a, b) => countFor(b.id) - countFor(a.id))[0] || null;
  const panel = selected || {};
  const panelTypes = selected ? types.filter(t => String(t.panel_id) === String(selected.id)) : [];
  const colorHex = p => p?.color ? '#' + Number(p.color).toString(16).padStart(6, '0') : '#4DA3FF';
  const canPublish = Boolean(selected?.id) && panelTypes.length > 0 && Boolean(panel.channel_id);
  const publishHint = !selected?.id ? 'Enregistrez d’abord le panneau.' : !panelTypes.length ? 'Ajoutez au moins un type à ce panneau pour pouvoir le publier.' : !panel.channel_id ? 'Choisissez le salon du panneau, puis enregistrez.' : panel.message_id ? `Publié dans ${channelName(panel.channel_id) || 'un salon'} · ${plural(panelTypes.length, 'type')}. Republiez après un changement.` : `Prêt à publier dans ${channelName(panel.channel_id) || 'un salon'} · ${plural(panelTypes.length, 'type')}.`;
  const editorHead = `<section class="ticket-editor-head full">
    <button class="btn sm" id="ticketEditorBack" type="button">Retour aux panneaux</button>
    <div><b>${esc(selected ? (panel.title || panel.name || 'Panneau') : 'Nouveau panneau')}</b><small>${selected ? 'Modification du panneau' : 'Création d’un panneau'}</small></div>
  </section>`;
  content().innerHTML = `<div class="grid ticket-page ticket-panel-editor">${head}${editorHead}${card('Panneau', 'Le message Discord sur lequel les membres cliquent pour ouvrir un ticket.', `<div class="fields"><div class="field"><label for="ticketName">Nom interne</label><input id="ticketName" value="${esc(panel.name || 'Support')}"></div><div class="field"><label for="ticketChannel">Salon du panneau</label><select id="ticketChannel">${channelOptions(panel.channel_id || '', 'text', 'Choisir un salon')}</select></div><div class="field full"><label for="ticketTitle">Titre affiché</label><input id="ticketTitle" value="${esc(panel.title || 'Support')}"></div><div class="field full"><label for="ticketDescription">Description</label><textarea id="ticketDescription" maxlength="2000" rows="2">${esc(panel.description || 'Choisissez une option ci-dessous pour ouvrir un ticket.')}</textarea></div><div class="field"><label for="ticketStyle">Affichage</label><select id="ticketStyle"><option value="select">Menu déroulant</option><option value="button" ${panel.style === 'button' ? 'selected' : ''}>Boutons</option></select></div><div class="field"><label for="ticketMax">Tickets ouverts par membre</label><input id="ticketMax" type="number" min="1" max="20" value="${Number(panel.max_per_member || 1)}"></div><div class="field"><label for="ticketColor">Couleur</label><input id="ticketColor" type="color" value="${colorHex(panel)}"></div></div><div class="toolbar"><button class="btn primary" type="button" id="ticketSave">${selected ? 'Enregistrer' : 'Créer le panneau'}</button><button class="btn" type="button" id="ticketPublish" ${canPublish ? '' : 'disabled'}>${panel.message_id ? 'Mettre à jour dans Discord' : 'Publier dans Discord'}</button>${selected ? `<button class="btn danger" type="button" id="ticketDelete">Supprimer</button>` : ''}<small id="ticketPublishHint">${esc(publishHint)}</small></div>`, 'full')}<section class="card full"><div class="card-head"><div><h2>Types de ce panneau</h2><p>${selected ? `Chaque type devient une option du panneau « ${esc(panel.name || 'Support')} ».` : 'Créez le panneau, puis ajoutez ses types.'}</p></div>${selected ? `<button class="btn primary" type="button" id="ticketTypeAdd">Ajouter un type</button>` : ''}</div><div class="list">${panelTypes.length ? panelTypes.map(t => `<div class="row"><div class="row-main"><b>${esc(t.emoji || '🎫')} ${esc(t.name || 'Type')}</b><small>${esc(t.description || 'Sans description')}${t.staff_role_id ? ' · ' + esc(roleName(t.staff_role_id) || 'rôle supprimé') : ''}${t.use_form ? ' · formulaire' : ''}</small></div><div class="row-actions"><button class="btn sm" type="button" data-type-edit="${esc(t.id)}">Modifier</button><button class="btn sm danger" type="button" data-type-del="${esc(t.id)}">Retirer</button></div></div>`).join('') : emptyState('Aucun type sur ce panneau', 'Exemple : Support, Recrutement, Signalement.')}</div>${types.length > panelTypes.length ? `<p class="card-copy"><small>${plural(types.length - panelTypes.length, 'autre type existe', 'autres types existent')} sur d’autres panneaux.</small></p>` : ''}</section></div>`;
  bindModuleButtons();
  $('ticketEditorBack').onclick = () => {
    state.ticketEditorOpen = false;
    state.ticketCreate = false;
    render({ navigation: true });
  };
  $('ticketSave').onclick = async () => {
    try {
      const r = await v62Action({ action: 'ticket_panel_save', panel_id: selected?.id || null, name: $('ticketName').value, title: $('ticketTitle').value, description: $('ticketDescription').value, channel_id: $('ticketChannel').value, style: $('ticketStyle').value, max_per_member: $('ticketMax').value, color: $('ticketColor').value, enabled: true });
      if (r?.panel_id) state.ticketPanelId = String(r.panel_id);
      state.ticketCreate = false;
      state.ticketEditorOpen = true;
      await renderTickets();
    } catch (e) { toast(e.message, true); }
  };
  $('ticketPublish').onclick = async () => { if (!selected?.id) return; try { await v62Action({ action: 'ticket_send', panel_id: selected.id }); await renderTickets(); } catch (e) { toast(e.message, true); } };
  const del = $('ticketDelete'); if (del) del.onclick = async () => { if (!(await confirmDialog({ title: 'Supprimer ce panneau ?', body: `Le panneau « ${panel.name || 'Support'} » et ses ${plural(panelTypes.length, 'type')} seront supprimés. Les tickets déjà ouverts restent.`, confirm: 'Supprimer', danger: true }))) return; try { await v62Action({ action: 'ticket_panel_delete', panel_id: selected.id }); state.ticketPanelId = null; state.ticketCreate = false; state.ticketEditorOpen = false; await render({ navigation: true }); } catch (e) { toast(e.message, true); } };
  const typeEditor = (t) => openModal({
    title: t ? `Modifier « ${t.name} »` : 'Ajouter un type de ticket',
    body: `<div class="fields"><div class="field"><label for="ttName">Nom</label><input id="ttName" maxlength="80" value="${esc(t?.name || '')}" placeholder="Support"></div><div class="field"><label for="ttEmoji">Emoji</label><input id="ttEmoji" maxlength="100" value="${esc(t?.emoji || '🎫')}"></div><div class="field full"><label for="ttDesc">Description (visible par les membres)</label><input id="ttDesc" maxlength="150" value="${esc(t?.description || '')}" placeholder="Besoin d’aide ? Ouvrez un ticket."></div><div class="field"><label for="ttStaff">Rôle qui gère ces tickets</label><select id="ttStaff">${roleOptions(t?.staff_role_id || '', 'Rôle staff du serveur')}</select></div><div class="field"><label for="ttCategory">Catégorie des salons</label><select id="ttCategory">${channelOptions(t?.category_id || '', 'category', 'Catégorie par défaut')}</select></div><div class="field"><label for="ttLog">Salon des logs de ces tickets</label><select id="ttLog">${channelOptions(t?.log_channel_id || '', 'text', 'Logs tickets par défaut')}</select></div><div class="field"><label for="ttStyle">Couleur du bouton</label><select id="ttStyle">${BUTTON_STYLES.map(([v, l]) => `<option value="${v}" ${(t?.button_style || 'bleu') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div><div class="field full"><label for="ttOpen">Message envoyé à l’ouverture (facultatif)</label><textarea id="ttOpen" maxlength="1000" rows="3">${esc(t?.open_message || '')}</textarea></div></div><label class="switch-row"><span class="switch-copy"><b>Mentionner le rôle staff</b><span>À chaque ouverture de ticket.</span></span><input class="switch" id="ttMention" type="checkbox" ${t ? (t.mention_staff ? 'checked' : '') : 'checked'}></label>`,
    actions: [{ label: 'Annuler' }, { label: t ? 'Enregistrer' : 'Ajouter', kind: 'primary', keep: true, onClick: async () => {
      if (!$('ttName').value.trim()) return toast('Donnez un nom au type.', true);
      try { await v62Action({ action: 'ticket_type_save', type_id: t?.id || null, panel_id: selected.id, name: $('ttName').value, emoji: $('ttEmoji').value, description: $('ttDesc').value, staff_role_id: $('ttStaff').value, category_id: $('ttCategory').value, log_channel_id: $('ttLog').value, button_style: $('ttStyle').value, open_message: $('ttOpen').value, mention_staff: $('ttMention').checked, use_form: Boolean(t?.use_form), max_per_member: t?.max_per_member || 1, autoclose_hours: t?.autoclose_hours || 0, name_format: t?.name_format || 'ticket-{pseudo}', button_label: t?.button_label || $('ttName').value }); closeModal(); await renderTickets(); } catch (e) { toast(e.message, true); }
    } }],
  });
  const addBtn = $('ticketTypeAdd'); if (addBtn) addBtn.onclick = () => typeEditor(null);
  content().querySelectorAll('[data-type-edit]').forEach(b => b.onclick = () => typeEditor(types.find(t => String(t.id) === b.dataset.typeEdit)));
  content().querySelectorAll('[data-type-del]').forEach(b => b.onclick = async () => { const t = types.find(x => String(x.id) === b.dataset.typeDel); if (!(await confirmDialog({ title: `Retirer le type « ${t?.name || ''} » ?`, body: 'Il disparaîtra du panneau à la prochaine publication.', confirm: 'Retirer', danger: true }))) return; try { await v62Action({ action: 'ticket_type_delete', type_id: b.dataset.typeDel }); await renderTickets(); } catch (e) { toast(e.message, true); } });
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
