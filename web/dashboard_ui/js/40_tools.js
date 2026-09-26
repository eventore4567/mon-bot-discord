/* ---------- Plus d'outils ---------- */

/* Paramètres : préfixe, salons système, maintenance */
async function renderSettings() {
  const s = settings();
  let maint = null; try { maint = (await opsOverview()).maintenance || null; } catch (_) {}
  content().innerHTML = `<div class="grid">${card('Paramètres principaux', '', `<div class="fields">${field('Préfixe des commandes', 'prefix', s.prefix || '+', { hint: '1 à 5 caractères.' })}${field('Salon des commandes du bot', 'bot_commands_channel', '', { select: channelOptions(s.bot_commands_channel) })}${field('Salon des annonces', 'announce_channel', '', { select: channelOptions(s.announce_channel) })}${field('Salon des erreurs', 'error_channel', '', { select: channelOptions(s.error_channel) })}</div>`, 'full')}${card('Communauté', 'Destinations des suggestions, signalements et giveaways.', `<div class="fields">${field('Suggestions', 'suggest_channel', '', { select: channelOptions(s.suggest_channel) })}${field('Signalements', 'report_channel', '', { select: channelOptions(s.report_channel) })}${field('Giveaways', 'giveaway_channel', '', { select: channelOptions(s.giveaway_channel) })}${field('Partenariats', 'partner_channel', '', { select: channelOptions(s.partner_channel) })}</div>`, 'full')}${maint ? card('Mode maintenance', 'Coupe les commandes concernées sans arrêter SentriX.', `<div class="fields">${field('Raison affichée', '', maint.reason || '', { id: 'maintReason', full: true, placeholder: 'Maintenance en cours' })}</div><div class="toolbar"><button class="btn ${maint.enabled ? 'danger' : ''}" type="button" id="maintToggle">${maint.enabled ? 'Désactiver la maintenance' : 'Activer la maintenance'}</button>${badge(maint.enabled ? 'error' : 'active', maint.enabled ? 'Maintenance active' : 'Mode normal')}</div>`, 'full') : ''}</div>`;
  bindEditable();
  const t = $('maintToggle');
  if (t) t.onclick = async () => { try { await gpost('/ops/maintenance', { enabled: !maint.enabled, reason: $('maintReason').value }); invalidate('ops-overview'); toast(maint.enabled ? 'Maintenance désactivée.' : 'Maintenance activée.'); await render(); } catch (e) { toast(e.message, true); } };
}

/* Commandes & accès : commandes désactivées, gestionnaires, accès dashboard par rôle */
async function renderAccess() {
  let data = null, error = null;
  try { data = await setupTools(); } catch (e) { error = e; }
  let access = null; try { access = await gget('/ops/access'); } catch (_) {}
  const disabled = new Set(data?.disabled_commands || []), commands = data?.commands || [];
  const tiers = access?.tiers || access?.levels || [['viewer', 'Lecture'], ['operator', 'Opérateur'], ['admin', 'Administrateur dashboard']];
  content().innerHTML = `<div class="grid">${error ? notice(`Liste des commandes indisponible : ${error.message}`, 'warn') : card('Commandes', 'Désactivez une commande pour ce serveur sans toucher au bot.', `<div class="toolbar"><input class="search-input" id="commandSearch" type="search" placeholder="Rechercher une commande…"><select class="search-input" id="commandFilter"><option value="all">Toutes</option><option value="enabled">Actives</option><option value="disabled">Désactivées</option></select></div><div class="list" id="commandList"></div>`, 'full')}${data ? `<section class="card full"><div class="card-head"><div><h2>Gestionnaires</h2><p>Membres avec des accès supplémentaires à SentriX.</p></div><span class="badge blue">${number((data.managers || []).length)}</span></div><div class="list">${(data.managers || []).length ? (data.managers || []).map(m => `<div class="row"><div class="row-main"><b>${esc(m.name || m.id)}</b><small>${esc((m.categories || []).join(', '))}</small></div><button class="btn sm danger" type="button" data-manager-remove="${esc(m.id)}">Retirer</button></div>`).join('') : emptyState('Aucun gestionnaire supplémentaire')}</div></section>` : ''}${access ? `<section class="card full"><div class="card-head"><div><h2>Accès au dashboard par rôle</h2><p>Donnez à un rôle Discord un accès limité à ce dashboard.</p></div><button class="btn primary" type="button" id="accessAdd">Ajouter un rôle</button></div><div class="list">${(access.roles || access.items || []).length ? (access.roles || access.items).map(r => `<div class="row"><div class="row-main"><b>${esc(roleName(r.role_id) || r.role_name || r.role_id)}</b><small>${esc(r.tier || r.level || '')}</small></div><button class="btn sm danger" type="button" data-access-remove="${esc(r.role_id)}">Retirer</button></div>`).join('') : emptyState('Aucun accès délégué', 'Seuls les administrateurs Discord voient ce dashboard.')}</div></section>` : ''}</div>`;
  if (data) {
    const draw = () => {
      const q = $('commandSearch').value.toLowerCase(), f = $('commandFilter').value;
      const items = commands.filter(c => (!q || `${c.name} ${c.description || ''}`.toLowerCase().includes(q))).filter(c => f === 'all' || (f === 'disabled' && disabled.has(c.name)) || (f === 'enabled' && !disabled.has(c.name)));
      $('commandList').innerHTML = items.length ? items.map(c => { const off = disabled.has(c.name); return `<div class="row"><div class="row-main"><b>+${esc(c.name)}</b><small>${esc(c.description || '')}</small></div><button class="btn sm ${off ? 'primary' : ''}" type="button" data-cmd="${esc(c.name)}" data-enable="${off ? '1' : '0'}" ${c.protected ? 'disabled' : ''}>${c.protected ? 'Protégée' : off ? 'Réactiver' : 'Désactiver'}</button></div>`; }).join('') : emptyState('Aucune commande correspondante');
      $('commandList').querySelectorAll('[data-cmd]').forEach(b => b.onclick = async () => { try { await setupAction({ action: 'command', command: b.dataset.cmd, enabled: b.dataset.enable === '1' }); await renderAccess(); } catch (e) { toast(e.message, true); } });
    };
    $('commandSearch').oninput = draw; $('commandFilter').onchange = draw; draw();
    content().querySelectorAll('[data-manager-remove]').forEach(b => b.onclick = async () => { if (!(await confirmDialog({ title: 'Retirer ce gestionnaire ?', body: 'Il perdra ses accès supplémentaires.', confirm: 'Retirer', danger: true }))) return; try { await setupAction({ action: 'manager', user_id: b.dataset.managerRemove, enabled: false }); await renderAccess(); } catch (e) { toast(e.message, true); } });
  }
  const add = $('accessAdd');
  if (add) add.onclick = () => openModal({
    title: 'Ajouter un accès au dashboard',
    body: `<div class="fields"><div class="field"><label for="accessRole">Rôle</label><select id="accessRole">${roleOptions('', 'Choisir un rôle')}</select></div><div class="field"><label for="accessTier">Niveau</label><select id="accessTier">${tiers.map(t => Array.isArray(t) ? `<option value="${esc(t[0])}">${esc(t[1])}</option>` : `<option value="${esc(t.id || t)}">${esc(t.label || t)}</option>`).join('')}</select></div></div>`,
    actions: [{ label: 'Annuler' }, { label: 'Ajouter', kind: 'primary', keep: true, onClick: async () => { if (!$('accessRole').value) return toast('Choisissez un rôle.', true); try { await gpost('/ops/access', { role_id: $('accessRole').value, tier: $('accessTier').value, level: $('accessTier').value }); closeModal(); toast('Accès ajouté.'); await renderAccess(); } catch (e) { toast(e.message, true); } } }],
  });
  content().querySelectorAll('[data-access-remove]').forEach(b => b.onclick = async () => { if (!(await confirmDialog({ title: 'Retirer cet accès ?', body: 'Ce rôle ne pourra plus ouvrir le dashboard.', confirm: 'Retirer', danger: true }))) return; try { await gdel(`/ops/access/${encodeURIComponent(b.dataset.accessRemove)}`); await renderAccess(); } catch (e) { toast(e.message, true); } });
}

/* Envoyer un embed */
function renderEmbeds() {
  content().innerHTML = `<div class="grid">${card('Message', 'Composez, vérifiez l’aperçu, puis envoyez.', `<div class="fields"><div class="field full"><label for="embedChannel">Salon d’envoi</label><select id="embedChannel">${channelOptions('', 'text', 'Choisir un salon')}</select></div><div class="field full"><label for="embedContent">Texte au-dessus de l’embed (facultatif)</label><textarea id="embedContent" maxlength="2000" rows="2"></textarea></div><div class="field full"><label for="embedTitle">Titre</label><input id="embedTitle" maxlength="256"></div><div class="field full"><label for="embedDescription">Description</label><textarea id="embedDescription" maxlength="4096" rows="6"></textarea></div><div class="field"><label for="embedColor">Couleur</label><input id="embedColor" type="color" value="#4da3ff"></div><div class="field"><label for="embedImage">Grande image (HTTPS)</label><input id="embedImage" type="url" placeholder="https://…"></div></div>${advanced(`<div class="fields">${[['embedThumb', 'Miniature (HTTPS)', 'url'], ['embedUrl', 'Lien du titre', 'url'], ['embedAuthor', 'Nom de l’auteur', 'text'], ['embedAuthorIcon', 'Icône de l’auteur (HTTPS)', 'url'], ['embedAuthorUrl', 'Lien de l’auteur', 'url'], ['embedFooter', 'Texte du pied', 'text'], ['embedFooterIcon', 'Icône du pied (HTTPS)', 'url']].map(([id, l, t]) => `<div class="field"><label for="${id}">${esc(l)}</label><input id="${id}" type="${t}"></div>`).join('')}</div><label class="switch-row"><span class="switch-copy"><b>Afficher la date et l’heure</b></span><input class="switch" id="embedTimestamp" type="checkbox"></label><div class="field full"><label for="embedFields">Champs (un par ligne : Nom | Valeur)</label><textarea id="embedFields" rows="3" placeholder="Règle 1 | Soyez respectueux"></textarea></div>`, 'Auteur, pied de page, miniature, champs.')}<div class="toolbar"><button class="btn primary" type="button" id="embedSend">Envoyer dans Discord</button></div>`, 'full')}${card('Aperçu', '', `<div id="embedPreview"></div>`, 'full')}</div>`;
  const val = id => $(id).value.trim();
  const paint = () => { $('embedPreview').innerHTML = discordMessage({ content: val('embedContent'), embed: { title: val('embedTitle'), description: val('embedDescription'), color: val('embedColor'), image: val('embedImage'), author: val('embedAuthor'), footer: val('embedFooter'), timestamp: $('embedTimestamp').checked } }); };
  content().querySelectorAll('input,textarea,select').forEach(el => el.addEventListener('input', paint)); paint();
  bindEditable();
  $('embedSend').onclick = async () => {
    if (!val('embedChannel')) return toast('Choisissez un salon.', true);
    const fields = val('embedFields').split('\n').map(l => l.split('|')).filter(p => p.length >= 2).map(([name, ...rest]) => ({ name: name.trim(), value: rest.join('|').trim(), inline: false }));
    const b = $('embedSend'); b.disabled = true;
    try {
      const r = await gpost('/embeds', { channel_id: val('embedChannel'), content: val('embedContent'), title: val('embedTitle'), description: val('embedDescription'), color: val('embedColor'), image_url: val('embedImage'), thumbnail_url: val('embedThumb'), url: val('embedUrl'), author_name: val('embedAuthor'), author_icon_url: val('embedAuthorIcon'), author_url: val('embedAuthorUrl'), footer_text: val('embedFooter'), footer_icon_url: val('embedFooterIcon'), timestamp: $('embedTimestamp').checked, fields });
      toast(r.message || 'Embed envoyé.');
    } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
  };
}

/* IA */
async function renderAI() {
  const a = state.guild?.ai || {};
  content().innerHTML = `<div class="grid">${await moduleHead('ai', 'Les membres peuvent parler à SentriX.')}${card('', '', switchRow('Activer l’IA', 'enabled', Boolean(a.enabled), 'Les membres peuvent parler à SentriX.', 'ai') + switchRow('Mémoire de conversation', 'memory_enabled', Boolean(a.memory_enabled), 'Se souvient du contexte pendant un moment.', 'ai'), 'full')}${advanced(card('Limites et modèle', '', switchRow('Journaliser les usages', 'logs_enabled', Boolean(a.logs_enabled), '', 'ai') + `<div class="fields" style="margin-top:12px">${field('Modèle', 'default_model', '', { kind: 'ai', select: ['luna', 'terra', 'sol'].map(x => `<option value="${x}" ${a.default_model === x ? 'selected' : ''}>${x[0].toUpperCase() + x.slice(1)}</option>`).join('') })}${field('Raisonnement', 'reasoning_effort', '', { kind: 'ai', select: ['none', 'low', 'medium', 'high', 'xhigh', 'max'].map(x => `<option value="${x}" ${a.reasoning_effort === x ? 'selected' : ''}>${x}</option>`).join('') })}${field('Délai entre deux questions (s)', 'cooldown_seconds', a.cooldown_seconds ?? 0, { kind: 'ai', type: 'number', min: 0, max: 3600 })}${field('Limite par minute', 'per_minute_limit', a.per_minute_limit ?? 10, { kind: 'ai', type: 'number', min: 1, max: 100 })}${field('Limite par jour', 'daily_limit', a.daily_limit ?? 500, { kind: 'ai', type: 'number', min: 1, max: 10000 })}${field('Mémoire (minutes)', 'memory_minutes', a.memory_minutes ?? 60, { kind: 'ai', type: 'number', min: 1, max: 1440 })}</div>`))}</div>`;
  bindEditable(); bindModuleButtons();
}

/* Invitations & webhooks */
let inviteWindow = '7d';
const inviteAnalytics = (force = false) => cached('invite-analytics', () => gget('/invites/analytics'), { force, ttl: 20000 });

function inviteGrowthChart(series = []) {
  if (!series.length) return emptyState('Pas encore assez de données');
  const max = Math.max(1, ...series.map(x => Math.max(Number(x.joins || 0), Number(x.leaves || 0))));
  return `<div style="display:grid;grid-template-columns:repeat(${series.length},minmax(8px,1fr));gap:5px;align-items:end;height:150px;padding-top:8px">
    ${series.map(x => {
      const j = Math.max(2, Math.round((Number(x.joins || 0) / max) * 120));
      const l = Math.max(2, Math.round((Number(x.leaves || 0) / max) * 120));
      return `<div title="${esc(when(x.ts))} · ${number(x.joins)} arrivée(s) · ${number(x.leaves)} départ(s)" style="display:flex;gap:2px;align-items:end;height:130px"><span style="flex:1;height:${j}px;background:linear-gradient(180deg,#55d69a,#268c62);border-radius:5px 5px 2px 2px"></span><span style="flex:1;height:${l}px;background:linear-gradient(180deg,#ff788b,#a83e50);border-radius:5px 5px 2px 2px"></span></div>`;
    }).join('')}
  </div><div style="display:flex;gap:16px;margin-top:8px"><small><span style="color:#55d69a">■</span> Arrivées</small><small><span style="color:#ff788b">■</span> Départs</small></div>`;
}

async function renderInvites() {
  if (state.sub === 'webhooks') {
    let d; try { d = await gget('/growth/webhooks'); } catch (e) { return errorView(e); }
    content().innerHTML = `<div class="grid">${card('Webhooks du serveur', 'Inventaire sans exposer les jetons.', `<div class="list">${(d.items || []).length ? d.items.map(w => `<div class="row"><div class="row-main"><b>${esc(w.name || 'Webhook')}</b><small>#${esc(w.channel_name || 'inconnu')} · ${esc(w.type || 'webhook')}</small></div><code>${esc(w.id)}</code></div>`).join('') : emptyState('Aucun webhook')}</div>`, 'full')}</div>`;
    return;
  }

  let d;
  try { d = await inviteAnalytics(); } catch (e) { return errorView(e); }
  const period = d.periods?.[inviteWindow] || d.periods?.['7d'] || {};
  const board = (d.leaderboard || []).filter(x => !x.hidden);
  const hidden = (d.leaderboard || []).filter(x => x.hidden);
  const codes = d.codes || [];
  const sourceRows = period.sources || [];

  const leaderboardRows = board.length ? board.slice(0, 25).map((x, index) => {
    const m = x.member || {};
    const name = m.display_name || m.name || m.id || 'Utilisateur';
    return `<div class="row">
      <div class="row-main">
        <b>#${index + 1} · ${esc(name)}</b>
        <small>${number(x.real)} réelle(s) · ${number(x.fake)} fake · ${number(x.left)} repartie(s) · ${number(x.bonus)} bonus · rétention ${esc(x.retention)}%</small>
      </div>
      <div class="row-actions">
        <strong>${number(x.credited)}</strong>
        <button class="btn sm" type="button" data-invited-list="${esc(m.id)}">Invités</button>
        <button class="btn sm ghost" type="button" data-hide-inviter="${esc(m.id)}" data-hidden="1">Masquer</button>
      </div>
    </div>`;
  }).join('') : emptyState('Aucun classement', 'Les invitants apparaîtront après les premières arrivées attribuées.');

  const codeRows = codes.length ? codes.map(i => `<div class="row">
    <div class="row-main">
      <b>${i.label ? esc(i.label) + ' · ' : ''}<code>${esc(i.code)}</code></b>
      <small>#${esc(i.channel_name || 'inconnu')} · créateur ${esc(i.inviter_name || 'inconnu')} · ${number(i.tracked_joins)} arrivée(s) suivie(s) · ${number(i.tracked_active)} encore présente(s)</small>
    </div>
    <div class="row-actions">
      <strong>${plural(i.uses, 'utilisation')}</strong>
      <button class="btn sm" type="button" data-invite-label="${esc(i.code)}" data-current-label="${esc(i.label || '')}">Label</button>
    </div>
  </div>`).join('') : emptyState(
    d.can_manage_invites ? 'Aucun code actif' : 'Invitations Discord illisibles',
    d.can_manage_invites ? 'Créez une invitation sur Discord pour la voir ici.' : 'SentriX a besoin de la permission Gérer le serveur pour lire les codes actifs.'
  );

  const hiddenRows = hidden.length ? hidden.map(x => `<div class="row"><div class="row-main"><b>${esc(x.member?.display_name || x.member?.name || x.member?.id)}</b><small>${number(x.credited)} invitation(s) créditée(s)</small></div><button class="btn sm" type="button" data-hide-inviter="${esc(x.member?.id)}" data-hidden="0">Réafficher</button></div>`).join('') : emptyState('Aucun membre masqué');

  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head">
        <div><h2>Analytics invitations</h2><p>Historique réellement observé par SentriX. La synchronisation des codes ne reconstruit jamais rétroactivement qui a invité qui.</p></div>
        <div class="toolbar">
          ${['24h','7d','30d','all'].map(w => `<button class="btn sm ${inviteWindow === w ? 'primary' : 'ghost'}" type="button" data-invite-window="${w}">${w === 'all' ? 'Tout' : w}</button>`).join('')}
          <button class="btn sm" id="inviteSync" type="button">Synchroniser</button>
          <button class="btn sm ghost" id="inviteExport" type="button">Exporter CSV</button>
          <button class="btn sm ghost" id="inviteRefresh" type="button">Actualiser</button>
        </div>
      </div>
      <div class="kpis" style="margin-top:14px">
        <div class="kpi"><small>Arrivées</small><b>${number(period.joins)}</b><span>${number(period.attributed)} attribuée(s)</span></div>
        <div class="kpi"><small>Départs</small><b>${number(period.leaves)}</b><span>${number(period.fake_active)} compte(s) récent(s) actif(s)</span></div>
        <div class="kpi"><small>Encore présents</small><b>${number(period.active)}</b><span>Croissance nette ${number(Number(period.joins || 0) - Number(period.leaves || 0))}</span></div>
        <div class="kpi"><small>Rétention</small><b>${esc(period.retention || 0)}%</b><span>Membres encore présents</span></div>
      </div>
    </section>

    ${card('Évolution', 'Arrivées et départs sur la période choisie.', inviteGrowthChart(period.series || []), 'full')}

    <section class="card">
      <div class="card-head"><div><h2>Sources d’arrivée</h2><p>Basé uniquement sur les données réellement enregistrées.</p></div></div>
      <div class="list">${sourceRows.length ? sourceRows.map(s => `<div class="row"><div class="row-main"><b>${esc(s.name)}</b></div><strong>${number(s.count)}</strong></div>`).join('') : emptyState('Aucune source enregistrée')}</div>
    </section>

    <section class="card">
      <div class="card-head"><div><h2>Recherche</h2><p>Filtre instantanément les invitants et les codes affichés sur cette page.</p></div></div>
      <div class="field full"><label for="inviteSearch">Pseudo, ID, code ou label</label><input class="search-input" id="inviteSearch" type="search" placeholder="Ex. Tomioka, 123456…, youtube"></div>
      <small id="inviteSearchCount"></small>
    </section>

    <section class="card full">
      <div class="card-head"><div><h2>Classement des invitants</h2><p>Classement par invitations créditées : réelles + bonus staff. Les fake et les départs ne donnent pas de crédit.</p></div><span class="badge blue">${plural(board.length, 'invitant')}</span></div>
      <div class="list" id="inviteLeaderboard">${leaderboardRows}</div>
    </section>

    <section class="card full">
      <div class="card-head"><div><h2>Codes d’invitation actifs</h2><p>Utilisations Discord, attribution SentriX et labels internes staff.</p></div><span class="badge">${plural(codes.length, 'code')}</span></div>
      <div class="list" id="inviteCodes">${codeRows}</div>
    </section>

    ${advanced(`<section class="card full"><div class="card-head"><div><h2>Membres masqués du classement</h2><p>Le suivi reste intact ; seul l’affichage du classement est masqué.</p></div><span class="badge">${number(hidden.length)}</span></div><div class="list">${hiddenRows}</div></section>`)}
  </div>`;

  content().querySelectorAll('[data-invite-window]').forEach(b => b.onclick = async () => {
    inviteWindow = b.dataset.inviteWindow;
    await renderInvites();
  });

  $('inviteRefresh').onclick = async () => {
    invalidate('invite-analytics');
    await renderInvites();
  };

  $('inviteSync').onclick = async () => {
    const ok = await confirmDialog({
      title: 'Synchroniser les invitations ?',
      body: 'SentriX va relire les codes et leurs compteurs actuels sur Discord. Cette opération ne crée aucune attribution historique de membre.',
      confirm: 'Synchroniser'
    });
    if (!ok) return;
    const b = $('inviteSync'); b.disabled = true;
    try {
      const r = await gpost('/invites/sync', {});
      toast(r.message || 'Invitations synchronisées.');
      invalidate('invite-analytics');
      await renderInvites();
    } catch (e) { toast(e.message, true); b.disabled = false; }
  };

  $('inviteExport').onclick = () => {
    const rows = [
      ['rang','user_id','nom','reelles','fake','reparties','bonus','creditees','retention'],
      ...board.map((x, i) => [i + 1, x.member?.id || '', x.member?.display_name || x.member?.name || '', x.real, x.fake, x.left, x.bonus, x.credited, x.retention]),
    ];
    const csv = rows.map(row => row.map(value => {
      const s = String(value ?? '');
      return /[",\n]/.test(s) ? '"' + s.replaceAll('"','""') + '"' : s;
    }).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = `sentrix-invitations-${state.guildId}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 800);
  };

  content().querySelectorAll('[data-invite-label]').forEach(b => b.onclick = async () => {
    const value = await promptDialog({
      title: `Label du code ${b.dataset.inviteLabel}`,
      label: 'Label interne',
      value: b.dataset.currentLabel || '',
      confirm: 'Enregistrer'
    });
    if (value === null) return;
    try {
      await gpost(`/invites/codes/${encodeURIComponent(b.dataset.inviteLabel)}`, { label: value }, 'PUT');
      toast('Label enregistré.');
      invalidate('invite-analytics');
      await renderInvites();
    } catch (e) { toast(e.message, true); }
  });

  content().querySelectorAll('[data-hide-inviter]').forEach(b => b.onclick = async () => {
    try {
      const hiddenValue = b.dataset.hidden === '1';
      const r = await gpost('/invites/leaderboard-hidden', { user_id: b.dataset.hideInviter, hidden: hiddenValue });
      toast(r.message || 'Classement mis à jour.');
      invalidate('invite-analytics');
      await renderInvites();
    } catch (e) { toast(e.message, true); }
  });

  content().querySelectorAll('[data-invited-list]').forEach(b => b.onclick = async () => {
    try {
      const d = await gget(`/invites/inviters/${encodeURIComponent(b.dataset.invitedList)}`);
      const rows = (d.items || []).map(x => `<div class="row"><div class="row-main"><b>${esc(x.member?.display_name || x.member?.name || x.member?.id)}</b><small>Code ${esc(x.invite_code || 'inconnu')} · arrivé ${esc(when(x.joined_at))}${x.left_at ? ' · reparti ' + esc(when(x.left_at)) : ''}${x.suspect_account ? ' · compte récent' : ''}</small></div><span class="badge ${x.left_at ? 'warn' : x.suspect_account ? 'bad' : 'ok'}">${x.left_at ? 'Reparti' : x.suspect_account ? 'Récent' : 'Présent'}</span></div>`).join('');
      openModal({ title: `Membres invités · ${number(d.total)}`, body: `<div class="list">${rows || emptyState('Aucun membre invité')}</div>`, actions: [{ label: 'Fermer' }] });
    } catch (e) { toast(e.message, true); }
  });

  const search = $('inviteSearch');
  search.oninput = () => {
    const q = search.value.trim().toLocaleLowerCase('fr');
    const targets = [
      ...$('inviteLeaderboard').querySelectorAll('.row'),
      ...$('inviteCodes').querySelectorAll('.row'),
    ];
    let visible = 0;
    for (const row of targets) {
      const show = !q || row.textContent.toLocaleLowerCase('fr').includes(q);
      row.style.display = show ? '' : 'none';
      if (show) visible += 1;
    }
    $('inviteSearchCount').textContent = q ? `${visible} résultat(s) visible(s)` : '';
  };
}

/* Sauvegardes & historique */
async function renderBackups() {
  if (state.sub === 'history') {
    let o; try { o = await opsOverview(true); } catch (e) { return errorView(e); }
    const rows = o.history || [];
    content().innerHTML = `<div class="grid">${card('Historique des configurations', 'Chaque enregistrement crée une version restaurable.', `<div class="list">${rows.length ? rows.map(h => `<div class="row"><div class="row-main"><b>${esc((h.changed_keys || []).join(', ') || 'Configuration')}</b><small>${when(h.created_at)} · ${esc(h.username || h.user_id || 'utilisateur')}</small></div><div class="row-actions"><button class="btn sm" type="button" data-diff="${h.id}">Comparer</button><button class="btn sm" type="button" data-rollback="${h.id}">Restaurer</button></div></div>`).join('') : emptyState('Aucun historique', 'Les prochaines modifications apparaîtront ici.')}</div>`, 'full')}</div>`;
    content().querySelectorAll('[data-rollback]').forEach(b => b.onclick = async () => { if (!(await confirmDialog({ title: 'Restaurer cette version ?', body: 'La configuration actuelle sera remplacée par cette version.', confirm: 'Restaurer', danger: true }))) return; try { await gpost(`/ops/history/${b.dataset.rollback}/rollback`, {}); toast('Configuration restaurée.'); invalidate(); await reloadGuild(); await render(); } catch (e) { toast(e.message, true); } });
    content().querySelectorAll('[data-diff]').forEach(b => b.onclick = async () => { try { const d = await gget(`/product/audit/${encodeURIComponent(b.dataset.diff)}/diff`); openModal({ title: 'Différences avec la configuration actuelle', body: (d.diff || []).length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Réglage</th><th>Avant</th><th>Maintenant</th></tr></thead><tbody>${d.diff.map(x => `<tr><td>${esc(x.path)}</td><td><code>${esc(JSON.stringify(x.before))}</code></td><td><code>${esc(JSON.stringify(x.after))}</code></td></tr>`).join('')}</tbody></table></div>` : '<p>Aucune différence.</p>', actions: [{ label: 'Fermer' }] }); } catch (e) { toast(e.message, true); } });
    return;
  }
  content().innerHTML = `<div class="grid">${card('Exporter / importer', 'La configuration complète au format JSON.', `<div class="toolbar"><button class="btn primary" type="button" id="opsExport">Exporter</button><button class="btn" type="button" id="opsDownload">Télécharger</button><button class="btn" type="button" id="opsImport">Importer le JSON ci-dessous</button></div><div class="field" style="margin-top:10px"><label for="opsJson">Configuration JSON</label><textarea id="opsJson" rows="12" placeholder="L’export apparaîtra ici. Collez un export pour l’importer."></textarea></div>`, 'full')}${card('Réparation', 'Corrige automatiquement ce qui est sûr : salons supprimés, rôles introuvables.', `<div class="toolbar"><button class="btn" type="button" id="opsRepair">Réparer la configuration</button></div>`, 'full')}</div>`;
  const exportCfg = async () => { const d = await gget('/ops/export'); $('opsJson').value = JSON.stringify(d.config, null, 2); return d; };
  $('opsExport').onclick = async () => { try { await exportCfg(); toast('Export généré.'); } catch (e) { toast(e.message, true); } };
  $('opsDownload').onclick = async () => { try { const d = await exportCfg(); const blob = new Blob([JSON.stringify(d.config, null, 2)], { type: 'application/json' }), u = URL.createObjectURL(blob), a = document.createElement('a'); a.href = u; a.download = `sentrix-${state.guildId}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(u), 800); } catch (e) { toast(e.message, true); } };
  $('opsImport').onclick = async () => { let cfg; try { cfg = JSON.parse($('opsJson').value); } catch (_) { return toast('JSON invalide.', true); } if (!(await confirmDialog({ title: 'Importer cette configuration ?', body: 'Les réglages actuels seront remplacés. Une version restaurable est conservée dans l’historique.', confirm: 'Importer', danger: true }))) return; try { await gpost('/ops/import', cfg); toast('Configuration importée.'); invalidate(); await reloadGuild(); await render(); } catch (e) { toast(e.message, true); } };
  $('opsRepair').onclick = async () => { if (!(await confirmDialog({ title: 'Réparer la configuration ?', body: 'Seules les références cassées (salon ou rôle supprimé) seront retirées.', confirm: 'Réparer' }))) return; try { const r = await gpost('/ops/repair', {}); toast(r.message || 'Réparation terminée.'); invalidate(); await reloadGuild(); } catch (e) { toast(e.message, true); } };
}

/* Message privé à un membre (propriétaire) */
async function renderDM() {
  let info; try { info = await gget('/dm/apercu'); } catch (e) { content().innerHTML = `<div class="grid">${card('Réservé au propriétaire du serveur', e.message || 'Vous n’avez pas accès à cette section.', '', 'full')}</div>`; return; }
  content().innerHTML = `<div class="grid">${card('Message privé à un membre', `Envoyé au nom de ${info.guild?.name || 'ce serveur'}. Indiquez l’identifiant Discord du membre.`, `<div class="fields"><div class="field"><label for="dmOneUser">ID du membre</label><input id="dmOneUser" inputmode="numeric" placeholder="123456789012345678"></div><div class="field full"><label for="dmOneMessage">Message</label><textarea id="dmOneMessage" maxlength="${esc(info.longueur_max || 3500)}" rows="5"></textarea></div></div><div id="dmPreview"></div><div class="toolbar"><button class="btn primary" type="button" id="dmOneSend">Envoyer</button></div>`, 'full')}</div>`;
  const paint = () => { $('dmPreview').innerHTML = discordMessage({ content: $('dmOneMessage').value }); };
  $('dmOneMessage').addEventListener('input', paint); paint();
  $('dmOneUser').oninput = e => { const m = /(\d{15,22})/.exec(e.target.value || ''); if (m && e.target.value !== m[1]) e.target.value = m[1]; };
  $('dmOneSend').onclick = async () => {
    const user_id = $('dmOneUser').value.trim(), message = $('dmOneMessage').value;
    if (!user_id) return toast('Indiquez un identifiant de membre.', true);
    if (!message.trim()) return toast('Le message est vide.', true);
    if (!(await confirmDialog({ title: 'Envoyer ce message privé ?', body: `Le membre ${user_id} recevra ce message au nom du serveur.`, confirm: 'Envoyer' }))) return;
    const b = $('dmOneSend'); b.disabled = true;
    try { const r = await gpost('/dm/user', { user_id, message }); toast(r.message || 'Message envoyé.'); if (r.resultat === 'envoye') { $('dmOneMessage').value = ''; paint(); } } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
  };
}

/* Diagnostic (propriétaire du serveur / développeur) */
async function renderDiagnostic() {
  const d = await diagnostics(true);
  let ops = null; try { ops = await opsOverview(true); } catch (_) {}
  let health = null; try { health = await gget('/ops/health'); } catch (_) {}
  const invalid = d.invalid_resources || [];
  const status = ops?.status || {};
  const tech = health || status;
  content().innerHTML = `<div class="grid">${card('Santé de la configuration', `Score ${Number(d.score || 0)} % · calculé depuis Discord et la base.`, `<div class="kpis">${kpi('Modules actifs', number(d.summary?.active))}${kpi('Erreurs', number(d.summary?.errors))}${kpi('À configurer', number(d.summary?.missing))}${kpi('Ressources cassées', number(invalid.length))}</div>`, 'full')}${card('État technique', '', `<div class="kpis">${kpi('Discord', tech.discord_ready === false ? 'Hors ligne' : 'Connecté')}${kpi('Latence', tech.latency_ms != null ? `${tech.latency_ms} ms` : '—')}${kpi('Base de données', tech.db_latency_ms != null ? `${tech.db_latency_ms} ms` : tech.database || '—')}${kpi('Version', tech.release || tech.sha || tech.version || '—')}${kpi('Extensions', tech.extensions != null ? number(tech.extensions) : '—')}${kpi('Commandes · 24 h', number(metrics().commands_24h))}</div>`, 'full')}${card('Permissions de SentriX', 'Une permission manquante peut bloquer un module.', `<div class="permission-grid">${(d.permissions || []).map(p => `<div class="permission"><span>${esc(p.name)}</span><span class="badge ${p.granted ? 'ok' : 'bad'}">${p.granted ? 'OK' : 'Manquante'}</span></div>`).join('')}</div>`, 'full')}<section class="card full"><div class="card-head"><div><h2>Ressources à corriger</h2><p>Salons ou rôles supprimés, inaccessibles ou placés au-dessus de SentriX.</p></div><span class="badge ${invalid.length ? 'bad' : 'ok'}">${number(invalid.length)}</span></div><div class="list">${invalid.length ? invalid.map(x => `<div class="row"><div class="row-main"><b>${esc(x.field)}</b><small>${esc(x.type)} ${esc(x.id)} · ${esc(x.reason)}</small></div><span class="badge bad">À corriger</span></div>`).join('') : emptyState('Aucune ressource cassée')}</div></section>${ops ? `<section class="card full"><div class="card-head"><div><h2>Diagnostics du bot</h2><p>Points relevés par les vérifications internes.</p></div></div><div class="list">${(ops.diagnostics || []).length ? ops.diagnostics.map(x => `<div class="row"><div class="row-main"><b>${esc(x.title || x.code || 'Point')}</b><small>${esc(x.detail || x.message || '')}</small></div><span class="badge ${x.severity === 'error' ? 'bad' : x.severity === 'warning' ? 'warn' : ''}">${esc(x.severity || 'info')}</span></div>`).join('') : emptyState('Rien à signaler')}</div></section>${card('Activité staff · 24 h', '', `<div class="list">${(ops.staff || []).length ? ops.staff.map((s, i) => `<div class="row"><div class="row-main"><b>#${i + 1} · ${esc(s.username || s.user_id)}</b></div><strong>${plural(s.actions, 'action')}</strong></div>`).join('') : emptyState('Aucune action staff enregistrée')}</div>`, 'full')}` : ''}</div>`;
}
