/* ---------- Communauté : Niveaux, Économie, Rôles ----------
   Données : /levels, /economy, /roles (web/dashboard_api_community.py) + /settings pour les
   clés déjà portées par guild_config. */
const levelsData = (force = false) => cached('levels', () => gget('/levels'), { force });
const economyData = (force = false) => cached('economy', () => gget('/economy'), { force });
const rolesData = (force = false) => cached('roles-panels', () => gget('/roles'), { force });

function multiRolePicker(id, selected = [], placeholder = 'Ajouter un rôle') {
  const chosen = new Set((selected || []).map(String));
  return `<div class="chips" id="${esc(id)}" data-multi-roles="${esc([...chosen].join(','))}">${[...chosen].map(rid => `<span class="chip on" data-chip-role="${esc(rid)}">${esc(roleName(rid) || 'Rôle supprimé')} <button type="button" class="btn link sm" aria-label="Retirer" data-chip-remove="${esc(rid)}">×</button></span>`).join('')}<button class="btn sm ghost" type="button" data-chip-add="${esc(id)}">${esc(placeholder)}</button></div>`;
}
function multiChannelPicker(id, selected = [], placeholder = 'Ajouter un salon') {
  const chosen = new Set((selected || []).map(String));
  return `<div class="chips" id="${esc(id)}" data-multi-channels="${esc([...chosen].join(','))}">${[...chosen].map(cid => `<span class="chip on" data-chip-channel="${esc(cid)}">${esc(channelName(cid) || 'Salon supprimé')} <button type="button" class="btn link sm" aria-label="Retirer" data-chip-remove="${esc(cid)}">×</button></span>`).join('')}<button class="btn sm ghost" type="button" data-chip-add="${esc(id)}">${esc(placeholder)}</button></div>`;
}
function readMulti(id) { const el = $(id); const raw = el?.dataset.multiRoles ?? el?.dataset.multiChannels ?? ''; return raw.split(',').filter(Boolean); }
function bindMultiPickers(root, onChange) {
  root.querySelectorAll('[data-chip-add]').forEach(b => b.onclick = async () => {
    const box = $(b.dataset.chipAdd); const isRole = 'multiRoles' in box.dataset;
    const current = new Set(readMulti(box.id));
    const items = (isRole ? roles().map(r => ({ value: r.id, label: `@${r.name}` })) : channels('text').map(c => ({ value: c.id, label: `#${c.name}` }))).filter(i => !current.has(String(i.value)));
    const pick = await pickDialog({ title: isRole ? 'Ajouter un rôle' : 'Ajouter un salon', items });
    if (!pick) return;
    current.add(String(pick.value));
    const list = [...current];
    box.outerHTML = isRole ? multiRolePicker(box.id, list) : multiChannelPicker(box.id, list);
    bindMultiPickers(root, onChange); onChange?.();
  });
  root.querySelectorAll('[data-chip-remove]').forEach(b => b.onclick = () => {
    const box = b.closest('[data-multi-roles],[data-multi-channels]'); const isRole = 'multiRoles' in box.dataset;
    const list = readMulti(box.id).filter(x => x !== b.dataset.chipRemove);
    box.outerHTML = isRole ? multiRolePicker(box.id, list) : multiChannelPicker(box.id, list);
    bindMultiPickers(root, onChange); onChange?.();
  });
}

/* ============================== Niveaux ============================== */
async function renderLevels() {
  let lv; try { lv = await levelsData(); } catch (e) { return errorView(e); }
  const s = settings(), m = metrics();
  const head = await moduleHead('levels', `XP gagné en discutant. ${plural(m.profiles, 'membre')} avec une progression.`);
  if (state.sub === 'levelup') {
    const name = state.user?.username || 'membre';
    content().innerHTML = `<div class="grid">${head}${card('Annonce de passage de niveau', 'Envoyée par SentriX quand un membre monte de niveau, avec sa carte de profil en image.', `<label class="switch-row"><span class="switch-copy"><b>Annoncer les passages de niveau</b><span>Désactivé : le membre progresse sans message.</span></span><input class="switch" id="lvAnnounce" type="checkbox" ${lv.level_announce_enabled ? 'checked' : ''}></label><div class="fields" style="margin-top:12px">${channelField('Salon des annonces', 'level_channel', s.level_channel, { full: true, placeholder: 'Répondre dans le salon du message', hint: 'Vide = SentriX répond là où le membre vient d’écrire.' })}</div>`, 'full')}${card('Aperçu', 'Le message tel que le bot l’envoie (le texte n’est pas modifiable : la carte est générée automatiquement).', discordMessage({ content: '{member}', embed: { title: 'Niveau atteint', description: `**${name}** passe au niveau **5**.`, color: '#6c5ce7', image: '', footer: '' } }) + `<div class="notice" style="margin-top:8px">Une image « carte de profil » (niveau, XP, rang) est jointe sous l’encadré.</div>`, 'full')}</div>`;
    bindEditable(); bindModuleButtons(); bindChannelWarnings();
    $('lvAnnounce').onchange = () => saveLevels({ level_announce_enabled: $('lvAnnounce').checked });
    return;
  }
  if (state.sub === 'roles') {
    const rows = lv.roles || [];
    content().innerHTML = `<div class="grid">${head}<section class="card full"><div class="card-head"><div><h2>Récompenses de niveau</h2><p>Un rôle donné automatiquement quand le niveau est atteint.</p></div><button class="btn primary" type="button" id="lvRoleAdd">Ajouter une récompense</button></div><div class="list">${rows.length ? rows.map(r => `<div class="row"><div class="row-main"><b>Niveau ${esc(r.level)} → ${esc(roleName(r.role_id) || 'Rôle supprimé')}</b>${roleName(r.role_id) ? '' : '<small class="error">Ce rôle n’existe plus : retirez la récompense.</small>'}</div><button class="btn sm danger" type="button" data-lv-role-del="${esc(r.level)}">Retirer</button></div>`).join('') : emptyState('Aucune récompense', 'Exemple : niveau 5 → @Actif, niveau 10 → @Habitué.')}</div></section>${card('', '', `<label class="switch-row"><span class="switch-copy"><b>Conserver les rôles des niveaux précédents</b><span>Désactivé : seul le rôle du niveau le plus haut est gardé.</span></span><input class="switch" id="lvKeep" type="checkbox" ${lv.level_keep_old_roles ? 'checked' : ''}></label>`, 'full')}</div>`;
    bindModuleButtons();
    $('lvKeep').onchange = () => saveLevels({ level_keep_old_roles: $('lvKeep').checked });
    $('lvRoleAdd').onclick = () => openModal({
      title: 'Ajouter une récompense',
      body: `<div class="fields"><div class="field"><label for="lvRoleLevel">Niveau</label><input id="lvRoleLevel" type="number" min="1" max="1000" value="5"></div><div class="field"><label for="lvRoleRole">Rôle</label><select id="lvRoleRole">${roleOptions('', 'Choisir un rôle')}</select></div></div><small>SentriX doit être placé au-dessus du rôle choisi.</small>`,
      actions: [{ label: 'Annuler' }, { label: 'Ajouter', kind: 'primary', keep: true, onClick: async () => { try { const r = await gpost('/levels/roles', { level: $('lvRoleLevel').value, role_id: $('lvRoleRole').value }); closeModal(); toast(r.message); invalidate('levels'); await render(); } catch (e) { toast(e.message, true); } } }],
    });
    content().querySelectorAll('[data-lv-role-del]').forEach(b => b.onclick = async () => { if (!(await confirmDialog({ title: `Retirer la récompense du niveau ${b.dataset.lvRoleDel} ?`, body: 'Les membres déjà récompensés gardent leur rôle.', confirm: 'Retirer', danger: true }))) return; try { await gdel(`/levels/roles/${b.dataset.lvRoleDel}`); invalidate('levels'); await render(); } catch (e) { toast(e.message, true); } });
    return;
  }
  if (state.sub === 'avance') {
    content().innerHTML = `<div class="grid">${head}${card('Multiplicateur', '1 = normal, 2 = deux fois plus vite.', `<div class="fields">${field('Multiplicateur XP', 'xp_multiplier', s.xp_multiplier ?? 1, { type: 'number', min: .1, max: 5, step: .1 })}</div>`)}${card('Exclusions', 'Aucun XP pour ces rôles ou dans ces salons.', `<div class="field"><span class="label">Rôles exclus</span>${multiRolePicker('lvExRoles', lv.xp_excluded_role_ids)}</div><div class="field" style="margin-top:10px"><span class="label">Salons exclus</span>${multiChannelPicker('lvExChannels', lv.xp_channel_disabled)}</div>`)}${card('', '', `<label class="switch-row"><span class="switch-copy"><b>Pas d’XP sur les commandes</b><span>Les messages qui commencent par le préfixe ne rapportent rien.</span></span><input class="switch" id="lvNoCmd" type="checkbox" ${lv.xp_disabled_on_commands ? 'checked' : ''}></label>`, 'full')}</div>`;
    bindEditable(); bindModuleButtons();
    bindMultiPickers(content(), () => saveLevels({ xp_excluded_role_ids: readMulti('lvExRoles'), xp_channel_disabled: readMulti('lvExChannels') }));
    $('lvNoCmd').onchange = () => saveLevels({ xp_disabled_on_commands: $('lvNoCmd').checked });
    return;
  }
  content().innerHTML = `<div class="grid">${head}${card('Gain d’XP par message', 'Une valeur aléatoire entre le minimum et le maximum, au plus une fois par délai.', `<div class="fields"><div class="field"><label for="lvMin">XP minimum</label><input id="lvMin" type="number" min="1" max="1000" value="${Number(lv.xp_min ?? 10)}"></div><div class="field"><label for="lvMax">XP maximum</label><input id="lvMax" type="number" min="1" max="1000" value="${Number(lv.xp_max ?? 25)}"></div><div class="field"><label for="lvCd">Délai entre deux gains (secondes)</label><input id="lvCd" type="number" min="0" max="3600" value="${Number(lv.xp_cooldown ?? 60)}"></div></div><div class="toolbar"><button class="btn primary" type="button" id="lvSave">Enregistrer</button></div>`, 'full')}</div>`;
  bindModuleButtons();
  $('lvSave').onclick = () => saveLevels({ xp_min: $('lvMin').value, xp_max: $('lvMax').value, xp_cooldown: $('lvCd').value });
}
async function saveLevels(values) {
  try { const r = await gpost('/levels', values, 'PUT'); invalidate('levels'); toast(r.message || 'Enregistré.'); } catch (e) { toast(e.message, true); }
}

/* ============================== Économie ============================== */
async function renderEconomy() {
  let ec; try { ec = await economyData(); } catch (e) { return errorView(e); }
  const m = metrics();
  const head = await moduleHead('economy', `Argent, banque et boutique. ${plural(m.economy_accounts, 'compte')}.`);
  if (state.sub === 'boutique') {
    const items = ec.shop || [];
    const now = Math.floor(Date.now() / 1000);
    const availability = i => (i.available_from && i.available_from > now) ? `disponible à partir du ${when(i.available_from)}` : (i.available_until && i.available_until < now) ? 'plus disponible' : (i.stock === 0 ? 'épuisé' : 'disponible');
    content().innerHTML = `<div class="grid">${head}<section class="card full"><div class="card-head"><div><h2>Articles</h2><p>Des rôles que les membres achètent avec leurs ${esc(ec.currency_plural || 'pièces')}.</p></div><button class="btn primary" type="button" id="shopAdd">Ajouter un article</button></div><div class="module-grid">${items.length ? items.map(i => `<article class="module-card"><div class="card-head"><h3>${esc(roleName(i.role_id) || i.name)}</h3><span class="badge ${availability(i) === 'disponible' ? 'ok' : 'warn'}">${esc(availability(i))}</span></div><p class="info">${i.sale_price ? `<s>${number(i.price)}</s> <b>${number(i.sale_price)}</b>` : `<b>${number(i.price)}</b>`} ${esc(ec.currency_symbol || '')} · Rôle${i.stock >= 0 ? ` · stock ${number(i.stock)}` : ''}${roleName(i.role_id) ? '' : ' · <span class="error">rôle supprimé</span>'}</p>${i.description ? `<p class="info">${esc(i.description)}</p>` : ''}<div class="toolbar"><button class="btn sm" type="button" data-shop-edit="${i.id}">Modifier</button><button class="btn sm danger" type="button" data-shop-del="${i.id}">Retirer</button></div></article>`).join('') : emptyState('Aucun article', 'Ajoutez un rôle que les membres pourront acheter.', { id: 'shopFirst', label: 'Ajouter un article' })}</div></section>${ec.panels?.length ? notice(`${plural(ec.panels.length, 'panneau de boutique publié', 'panneaux de boutique publiés')} dans Discord ; ils se mettent à jour automatiquement après chaque modification.`, 'ok') : notice('Aucun panneau de boutique publié : les membres passent par la commande boutique. Publiez-en un avec la commande shoppanel dans le salon voulu.')}</div>`;
    bindModuleButtons();
    const toDate = ts => ts ? new Date(Number(ts) * 1000).toISOString().slice(0, 16) : '';
    const fromDate = v => v ? Math.floor(new Date(v).getTime() / 1000) : null;
    const editor = (item) => openModal({
      title: item ? 'Modifier l’article' : 'Ajouter un article',
      body: `<div class="fields"><div class="field full"><label for="shopRole">Rôle vendu</label><select id="shopRole" ${item ? 'disabled' : ''}>${roleOptions(item?.role_id || '', 'Choisir un rôle')}</select></div><div class="field"><label for="shopPrice">Prix (${esc(ec.currency_plural || 'pièces')})</label><input id="shopPrice" type="number" min="1" value="${Number(item?.price || 500)}"></div><div class="field"><label for="shopStock">Stock (vide = illimité)</label><input id="shopStock" type="number" min="0" value="${item && item.stock >= 0 ? item.stock : ''}"></div><div class="field full"><label for="shopDesc">Description (facultative)</label><input id="shopDesc" maxlength="200" value="${esc(item?.description || '')}"></div></div>${advanced(`<div class="fields"><div class="field"><label for="shopSale">Prix promotionnel</label><input id="shopSale" type="number" min="1" value="${item?.sale_price || ''}"></div><div class="field"><label for="shopSaleEnd">Fin de la promotion</label><input id="shopSaleEnd" type="datetime-local" value="${toDate(item?.sale_ends_at)}"></div><div class="field"><label for="shopFrom">Disponible à partir du</label><input id="shopFrom" type="datetime-local" value="${toDate(item?.available_from)}"></div><div class="field"><label for="shopUntil">Disponible jusqu’au</label><input id="shopUntil" type="datetime-local" value="${toDate(item?.available_until)}"></div></div>`, 'Promotion et période de disponibilité.')}<small>Les rôles d’administration ou placés au-dessus de SentriX sont refusés.</small>`,
      actions: [{ label: 'Annuler' }, { label: item ? 'Enregistrer' : 'Ajouter', kind: 'primary', keep: true, onClick: async () => { try { const r = await gpost('/economy/shop', { role_id: item?.role_id || $('shopRole').value, price: $('shopPrice').value, description: $('shopDesc').value, stock: $('shopStock').value === '' ? -1 : $('shopStock').value, sale_price: $('shopSale').value || null, sale_ends_at: fromDate($('shopSaleEnd').value), available_from: fromDate($('shopFrom').value), available_until: fromDate($('shopUntil').value) }); closeModal(); toast(r.message); invalidate('economy'); await render(); } catch (e) { toast(e.message, true); } } }],
    });
    $('shopAdd').onclick = () => editor(null);
    const first = content().querySelector('[data-empty-action="shopFirst"]'); if (first) first.onclick = () => editor(null);
    content().querySelectorAll('[data-shop-edit]').forEach(b => b.onclick = () => editor(items.find(i => String(i.id) === b.dataset.shopEdit)));
    content().querySelectorAll('[data-shop-del]').forEach(b => b.onclick = async () => { if (!(await confirmDialog({ title: 'Retirer cet article ?', body: 'Les membres qui l’ont déjà acheté gardent le rôle.', confirm: 'Retirer', danger: true }))) return; try { await gdel(`/economy/shop/${b.dataset.shopDel}`); invalidate('economy'); await render(); } catch (e) { toast(e.message, true); } });
    return;
  }
  if (state.sub === 'jeux') {
    let gd; try { gd = await cached('games', () => gget('/economy/games')); } catch (e) { return errorView(e); }
    const gs = gd.settings || {}, catalog = gd.catalog || [];
    const disabled = new Set(gs.disabled_games || []);
    content().innerHTML = `<div class="grid">${head}${card('Mini-jeux', 'Les jeux rapportent des pièces ; vous choisissez lesquels sont disponibles.', `<label class="switch-row"><span class="switch-copy"><b>Activer les mini-jeux</b><span>Désactivé : toutes les commandes de jeu répondent que les jeux sont fermés.</span></span><input class="switch" id="gmEnabled" type="checkbox" ${gs.enabled ? 'checked' : ''}></label><div class="fields" style="margin-top:12px"><div class="field"><label for="gmDaily">Manches récompensées par membre et par jour</label><input id="gmDaily" type="number" min="0" max="10000" value="${Number(gs.daily_limit ?? 50)}"></div></div>`, 'full')}<section class="card full"><div class="card-head"><div><h2>Jeux disponibles</h2><p>Décochez un jeu pour le retirer du serveur.</p></div></div><div class="chips" id="gmCatalog">${catalog.map(g => `<label class="chip ${disabled.has(g.key) ? '' : 'on'}"><input type="checkbox" data-game="${esc(g.key)}" ${disabled.has(g.key) ? '' : 'checked'}> ${esc(g.label)}</label>`).join('')}</div></section>${card('Où et pour qui', 'Vide = partout et pour tout le monde.', `<div class="field"><span class="label">Salons autorisés</span>${multiChannelPicker('gmAllowedCh', gs.allowed_channel_ids)}</div><div class="field" style="margin-top:10px"><span class="label">Salons bloqués</span>${multiChannelPicker('gmBlockedCh', gs.blocked_channel_ids)}</div><div class="field" style="margin-top:10px"><span class="label">Rôles autorisés</span>${multiRolePicker('gmAllowedRoles', gs.allowed_role_ids)}</div><div class="field" style="margin-top:10px"><span class="label">Rôles bloqués</span>${multiRolePicker('gmBlockedRoles', gs.blocked_role_ids)}</div>`, 'full')}${advanced(`${['logs_enabled', 'Journaliser les parties', 'leaderboard_enabled', 'Classement des jeux', 'dm_results', 'Envoyer les résultats en message privé', 'compact_mode', 'Affichage compact'].reduce((acc, v, i, arr) => i % 2 ? acc : acc + `<label class="switch-row"><span class="switch-copy"><b>${esc(arr[i + 1])}</b></span><input class="switch" type="checkbox" data-game-flag="${v}" ${gs[v] ? 'checked' : ''}></label>`, '')}`)}</div>`;
    bindModuleButtons();
    const save = values => gpost('/economy/games', values, 'PUT').then(r => { invalidate('games'); toast(r.message); }).catch(e => toast(e.message, true));
    $('gmEnabled').onchange = () => save({ enabled: $('gmEnabled').checked });
    $('gmDaily').onchange = () => save({ daily_limit: $('gmDaily').value });
    content().querySelectorAll('[data-game]').forEach(cb => cb.onchange = () => { cb.closest('.chip').classList.toggle('on', cb.checked); save({ disabled_games: [...content().querySelectorAll('[data-game]')].filter(x => !x.checked).map(x => x.dataset.game) }); });
    content().querySelectorAll('[data-game-flag]').forEach(cb => cb.onchange = () => save({ [cb.dataset.gameFlag]: cb.checked }));
    bindMultiPickers(content(), () => save({ allowed_channel_ids: readMulti('gmAllowedCh'), blocked_channel_ids: readMulti('gmBlockedCh'), allowed_role_ids: readMulti('gmAllowedRoles'), blocked_role_ids: readMulti('gmBlockedRoles') }));
    return;
  }
  if (state.sub === 'gains') {
    const g = ec.gains || {}, sym = esc(ec.currency_symbol || '');
    content().innerHTML = `<div class="grid">${head}${card('Gains des commandes', 'Valeurs définies par SentriX : identiques pour tous les serveurs, non modifiables ici.', `<div class="kpis">${kpi('Récompense quotidienne', `${number(g.daily)} ${sym}`)}${kpi('Récompense hebdomadaire', `${number(g.weekly)} ${sym}`)}${kpi('Délai entre deux « travail »', age(g.work_cooldown))}${kpi('Délai du quotidien', age(g.daily_cooldown))}</div><p class="card-copy" style="margin-top:10px"><small>Valeur définie par SentriX.</small></p>`, 'full')}</div>`;
    bindModuleButtons();
    return;
  }
  if (state.sub === 'avance') {
    content().innerHTML = `<div class="grid">${head}${card('Accès aux commandes économiques', 'Choisissez qui peut utiliser chaque commande (balance, pay, rob, shop…).', `<div class="toolbar"><button class="btn" type="button" data-go="access">Ouvrir Commandes & accès</button></div>`, 'full')}${card('Protection anti-abus', 'Automatique : un membre qui enchaîne des actions suspectes est temporairement bloqué. Aucun réglage nécessaire.', '', 'full')}</div>`;
    bindModuleButtons();
    return;
  }
  content().innerHTML = `<div class="grid">${head}${card('Monnaie du serveur', 'Nom et symbole affichés dans toutes les commandes économiques.', `<div class="fields"><div class="field"><label for="ecSing">Nom (singulier)</label><input id="ecSing" maxlength="32" value="${esc(ec.currency_singular || 'Pièce')}"></div><div class="field"><label for="ecPlur">Nom (pluriel)</label><input id="ecPlur" maxlength="32" value="${esc(ec.currency_plural || 'Pièces')}"></div><div class="field"><label for="ecSym">Symbole</label><input id="ecSym" maxlength="16" value="${esc(ec.currency_symbol || '🪙')}"></div></div><div class="toolbar"><button class="btn primary" type="button" id="ecSave">Enregistrer</button></div>`, 'full')}<div class="kpis full">${kpi('Comptes', number(m.economy_accounts))}${kpi('Articles en boutique', number((ec.shop || []).length))}${kpi('Panneaux publiés', number((ec.panels || []).length))}</div></div>`;
  bindModuleButtons();
  $('ecSave').onclick = async () => { try { const r = await gpost('/economy', { currency_singular: $('ecSing').value, currency_plural: $('ecPlur').value, currency_symbol: $('ecSym').value }, 'PUT'); toast(r.message); invalidate('economy'); } catch (e) { toast(e.message, true); } };
}

/* ============================== Rôles ============================== */
async function pickMessage(channelId) {
  /* Sélecteur visuel : les 30 derniers messages du salon, sans identifiant à copier. */
  let d; try { d = await gget(`/roles/messages?channel_id=${encodeURIComponent(channelId)}`); } catch (e) { toast(e.message, true); return null; }
  const items = (d.items || []).map(m => ({ value: m.id, label: `${m.mine ? 'SentriX' : m.author} : ${m.text}`, meta: m }));
  if (!items.length) { toast('Aucun message récent dans ce salon.', true); return null; }
  return pickDialog({ title: 'Choisir le message', items, render: i => `<span class="row-main"><b>${esc(i.meta.mine ? 'SentriX' : i.meta.author)}${i.meta.reactions ? ` · ${plural(i.meta.reactions, 'réaction')}` : ''}</b><small>${esc(i.meta.text)} · ${when(i.meta.created_at)}</small></span>` });
}
async function renderRoles() {
  const s = settings();
  const head = await moduleHead('roles', 'Rôles donnés automatiquement ou choisis par les membres.');
  if (state.sub === 'interactifs') {
    let rp; try { rp = await rolesData(); } catch (e) { return errorView(e); }
    const notif = rp.notification_panels || [], rpanels = rp.reaction_panels || [], reactions = rp.reaction_roles || [];
    const byMessage = {}; reactions.forEach(r => { (byMessage[r.message_id] = byMessage[r.message_id] || []).push(r); });
    rpanels.forEach(p => { if (!byMessage[p.message_id]) byMessage[p.message_id] = []; });
    content().innerHTML = `<div class="grid">${head}<section class="card full"><div class="card-head"><div><h2>Rôles par réaction</h2><p>Un message-panneau ; chaque emoji donne ou retire un rôle.</p></div><button class="btn primary" type="button" id="reactionPanelCreate">Publier un panneau</button></div><div class="list">${Object.keys(byMessage).length ? Object.entries(byMessage).map(([mid, list]) => { const panel = rpanels.find(p => p.message_id === mid); const ch = list[0]?.channel_id || panel?.channel_id; return `<div class="row"><div class="row-main"><b>${esc(panel?.title || 'Message existant')}</b><small>${esc(channelName(ch) || 'salon inconnu')} · ${list.length ? list.map(r => `${esc(r.emoji)} → ${esc(roleName(r.role_id) || 'rôle supprimé')}`).join(' · ') : 'aucune réaction configurée'}</small></div><div class="row-actions"><button class="btn sm primary" type="button" data-reaction-add="${esc(mid)}" data-reaction-channel="${esc(ch || '')}">Ajouter une réaction</button>${list.map(r => `<button class="btn sm ghost" type="button" data-reaction-del="${esc(mid)}|${esc(r.emoji_key || r.emoji)}" title="Retirer ${esc(r.emoji)}">${esc(r.emoji)} ×</button>`).join('')}</div></div>`; }).join('') : emptyState('Aucun panneau de rôles', 'Publiez un panneau, puis ajoutez des réactions ; ou ajoutez une réaction sur un message existant.', { id: 'reactionExisting', label: 'Utiliser un message existant' })}</div>${Object.keys(byMessage).length ? `<div class="toolbar" style="margin-top:8px"><button class="btn ghost sm" type="button" id="reactionExistingBtn">Utiliser un message existant</button></div>` : ''}</section><section class="card full"><div class="card-head"><div><h2>Menus de notifications</h2><p>Un menu déroulant où chaque membre coche ses rôles de notification.</p></div><div class="toolbar"><button class="btn" type="button" id="panelRefresh" ${notif.length ? '' : 'disabled'}>Actualiser</button><button class="btn primary" type="button" id="panelCreate">Publier un menu</button></div></div><div class="list">${notif.length ? notif.map(p => `<div class="row"><div class="row-main"><b>${esc(p.title)}</b><small>${esc(channelName(p.channel_id) || 'salon supprimé')} · ${plural((rp.notification_roles || []).length, 'rôle proposé', 'rôles proposés')}</small></div><span class="badge ok">Publié</span></div>`).join('') : emptyState('Aucun menu publié', 'Le menu propose automatiquement les rôles dont le nom contient « ping » ou « notif ».')}</div>${(rp.notification_roles || []).length ? `<p class="card-copy" style="margin-top:8px"><small>Rôles proposés : ${rp.notification_roles.map(r => '@' + esc(r.name)).join(', ')}</small></p>` : notice('Aucun rôle de notification détecté : créez un rôle dont le nom contient « ping » ou « notif ».', 'warn')}</section></div>`;
    bindModuleButtons();
    const addReaction = (messageId, channelId) => openModal({
      title: 'Ajouter un rôle par réaction',
      body: `<div class="fields">${channelId ? '' : `<div class="field full"><label for="rrChannel">Salon du message</label><select id="rrChannel">${channelOptions('', 'text', 'Choisir un salon')}</select></div>`}<div class="field full"><span class="label">Message</span><div class="toolbar"><button class="btn" type="button" id="rrPick" ${channelId || messageId ? '' : 'disabled'}>${messageId ? 'Message choisi' : 'Choisir le message…'}</button><small id="rrPicked">${messageId ? 'Le panneau sélectionné.' : 'Choisissez d’abord un salon.'}</small></div></div><div class="field"><label for="rrEmoji">Emoji</label><input id="rrEmoji" placeholder="🔔 ou un emoji du serveur"></div><div class="field"><label for="rrRole">Rôle donné</label><select id="rrRole">${roleOptions('', 'Choisir un rôle')}</select></div></div>`,
      actions: [{ label: 'Annuler' }, { label: 'Ajouter', kind: 'primary', keep: true, onClick: async () => {
        const mid = $('modalBody').dataset.messageId || messageId; const ch = channelId || $('rrChannel')?.value;
        if (!ch || !mid) return toast('Choisissez le salon et le message.', true);
        try { const r = await gpost('/roles/reactions', { channel_id: ch, message_id: mid, emoji: $('rrEmoji').value.trim(), role_id: $('rrRole').value }); closeModal(); toast(r.message); invalidate('roles-panels'); await render(); } catch (e) { toast(e.message, true); }
      } }],
      onOpen: () => {
        $('modalBody').dataset.messageId = messageId || '';
        const chSel = $('rrChannel'); if (chSel) chSel.onchange = () => { $('rrPick').disabled = !chSel.value; $('rrPicked').textContent = chSel.value ? 'Choisissez le message.' : 'Choisissez d’abord un salon.'; };
        $('rrPick').onclick = async () => { const ch = channelId || $('rrChannel')?.value; if (!ch) return; const picked = await pickMessage(ch); if (!picked) { return; } /* pickDialog a fermé la modale : on la rouvre avec le message choisi */ addReaction(picked.value, ch); };
      },
    });
    $('reactionPanelCreate').onclick = () => openModal({
      title: 'Publier un panneau de rôles',
      body: `<div class="fields"><div class="field full"><label for="rpChannel">Salon</label><select id="rpChannel">${channelOptions('', 'text', 'Choisir un salon')}</select></div><div class="field full"><label for="rpTitle">Titre</label><input id="rpTitle" maxlength="256" value="Choisissez vos rôles"></div><div class="field full"><label for="rpDesc">Description</label><textarea id="rpDesc" rows="3" maxlength="2000">Réagissez avec l’emoji correspondant pour recevoir ou retirer un rôle.</textarea></div></div><div id="rpPreview"></div>`,
      actions: [{ label: 'Annuler' }, { label: 'Publier', kind: 'primary', keep: true, onClick: async () => { if (!$('rpChannel').value) return toast('Choisissez un salon.', true); try { const r = await gpost('/roles/panels/reaction', { channel_id: $('rpChannel').value, title: $('rpTitle').value, description: $('rpDesc').value }); closeModal(); toast(r.message); invalidate('roles-panels'); await render(); if (r.message_id) addReaction(r.message_id, r.channel_id); } catch (e) { toast(e.message, true); } } }],
      onOpen: () => { const paint = () => { $('rpPreview').innerHTML = discordMessage({ embed: { title: $('rpTitle').value, description: $('rpDesc').value } }); }; $('rpTitle').oninput = paint; $('rpDesc').oninput = paint; paint(); },
    });
    const existing = () => addReaction(null, null);
    const ex1 = content().querySelector('[data-empty-action="reactionExisting"]'); if (ex1) ex1.onclick = existing;
    const ex2 = $('reactionExistingBtn'); if (ex2) ex2.onclick = existing;
    content().querySelectorAll('[data-reaction-add]').forEach(b => b.onclick = () => addReaction(b.dataset.reactionAdd, b.dataset.reactionChannel));
    content().querySelectorAll('[data-reaction-del]').forEach(b => b.onclick = async () => { const [mid, key] = b.dataset.reactionDel.split('|'); if (!(await confirmDialog({ title: 'Retirer cette réaction ?', body: 'Le rôle ne sera plus donné par cette réaction.', confirm: 'Retirer', danger: true }))) return; try { await gdel(`/roles/reactions/${encodeURIComponent(mid)}/${encodeURIComponent(key)}`); invalidate('roles-panels'); await render(); } catch (e) { toast(e.message, true); } });
    $('panelCreate').onclick = () => openModal({
      title: 'Publier un menu de notifications',
      body: `<div class="fields"><div class="field full"><label for="panelChannel">Salon</label><select id="panelChannel">${channelOptions('', 'text', 'Choisir un salon')}</select></div><div class="field full"><label for="panelTitle">Titre</label><input id="panelTitle" maxlength="256" value="Choisissez vos notifications"></div></div>${discordMessage({ embed: { title: 'Choisissez vos notifications', description: 'Choisissez les notifications que vous souhaitez recevoir.\n\n**Notifications disponibles**\n' + ((rp.notification_roles || []).map(r => '• ' + r.name).join('\n') || 'Aucun rôle de notification.') } })}`,
      actions: [{ label: 'Annuler' }, { label: 'Publier', kind: 'primary', keep: true, onClick: async () => { if (!$('panelChannel').value) return toast('Choisissez un salon.', true); try { await setupAction({ action: 'self_role_panel', channel_id: $('panelChannel').value, title: $('panelTitle').value }); closeModal(); invalidate('roles-panels'); await render(); } catch (e) { toast(e.message, true); } } }],
    });
    $('panelRefresh').onclick = async () => { try { const r = await gpost('/roles/panels/refresh', {}); toast(r.message); } catch (e) { toast(e.message, true); } };
    return;
  }
  if (state.sub === 'niveau') {
    let lv = null; try { lv = await levelsData(); } catch (_) {}
    const rows = lv?.roles || [];
    content().innerHTML = `<div class="grid">${head}${card('Rôles de niveau', 'Donnés automatiquement quand un membre atteint le niveau. Se règlent dans Niveaux › Récompenses.', `<div class="list">${rows.length ? rows.map(r => `<div class="row"><div class="row-main"><b>Niveau ${esc(r.level)} → ${esc(roleName(r.role_id) || 'Rôle supprimé')}</b></div></div>`).join('') : emptyState('Aucune récompense de niveau')}</div><div class="toolbar" style="margin-top:10px"><button class="btn primary" type="button" data-go="levels" data-go-sub="roles">Gérer les récompenses</button></div>`, 'full')}</div>`;
    bindModuleButtons();
    return;
  }
  if (state.sub === 'avance') {
    content().innerHTML = `<div class="grid">${head}${card('Rôles de l’équipe', 'Donnent accès aux commandes de modération et d’administration.', `<div class="fields">${field('Rôle modérateur', 'mod_role', '', { select: roleOptions(s.mod_role) })}${field('Rôle administrateur', 'admin_role', '', { select: roleOptions(s.admin_role) })}</div>`)}${card('Rôles membres', '', `<div class="fields">${field('Rôle membre', 'member_role', '', { select: roleOptions(s.member_role) })}${field('Rôle booster', 'booster_role', '', { select: roleOptions(s.booster_role) })}</div>`)}${card('Sanctions', 'Rôles optionnels donnés par les sanctions.', `<div class="fields">${field('Rôle après un avertissement', 'warn_role', '', { select: roleOptions(s.warn_role) })}${field('Rôle pendant un mute', 'mute_role', '', { select: roleOptions(s.mute_role) })}</div>`)}${card('Vérification', 'Se règle aussi dans Sécurité › Vérification.', `<div class="fields">${field('Rôle vérifié', 'verify_role', '', { select: roleOptions(s.verify_role) })}${field('Rôle en attente de vérification', 'verification_role', '', { select: roleOptions(s.verification_role) })}</div>`)}</div>`;
    bindEditable(); bindModuleButtons();
    return;
  }
  content().innerHTML = `<div class="grid">${head}${card('Rôle donné à l’arrivée', 'Attribué automatiquement à chaque nouveau membre.', `<div class="fields">${field('Rôle', 'autorole', '', { select: roleOptions(s.autorole, 'Aucun rôle automatique'), full: true, hint: 'SentriX doit être placé au-dessus de ce rôle.' })}</div>`, 'full')}${card('Ce que reçoit un nouveau membre', '', `<div class="list"><div class="row"><div class="row-main"><b>À l’arrivée</b><small>${esc(roleName(s.autorole) || 'Aucun rôle automatique')}</small></div></div><div class="row"><div class="row-main"><b>Après vérification</b><small>${esc(roleName(s.verify_role) || 'Vérification non configurée')}</small></div><button class="btn sm" type="button" data-go="security" data-go-sub="verification">Configurer</button></div><div class="row"><div class="row-main"><b>Par niveau</b><small>Récompenses de niveau</small></div><button class="btn sm" type="button" data-go="levels" data-go-sub="roles">Configurer</button></div></div>`, 'full')}</div>`;
  bindEditable(); bindModuleButtons();
}
