/* SentriX dashboard — noyau : état, réseau, cache, composants.
   Règles : une page est rendue uniquement lors d'une navigation, d'un enregistrement ou
   d'une action explicite. Aucun rendu périodique, aucun observateur du DOM. */
const $ = id => document.getElementById(id);
const content = () => $('content');

const state = {
  user: null, csrf: '', developer: false,
  guilds: [], guildId: '', guild: null,
  page: 'overview', sub: '',
  dirty: { settings: {}, automod: {}, ai: {}, welcome: {} },
  cache: new Map(),
  guildAbort: null,
  progressCount: 0, progressTimer: null,
  live: null,
  reduceMotion: false,
};

/* ---------- utilitaires ---------- */
function esc(v) { return String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function number(v) { return Number(v || 0).toLocaleString('fr-FR'); }
function age(sec) {
  sec = Math.max(0, Number(sec || 0));
  if (sec < 60) return `${Math.floor(sec)} s`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h`;
  return `${Math.floor(sec / 86400)} j`;
}
function when(ts) { if (!ts) return '—'; try { return new Date(Number(ts) * (Number(ts) < 1e12 ? 1000 : 1)).toLocaleString('fr-FR'); } catch (_) { return '—'; } }
function plural(n, one, many) { return `${number(n)} ${Number(n) > 1 ? (many || one + 's') : one}`; }
function toast(message, bad = false) {
  const n = document.createElement('div');
  n.className = `toast ${bad ? 'bad' : 'ok'}`;
  n.setAttribute('role', bad ? 'alert' : 'status');
  n.textContent = String(message || '');
  $('toastWrap').appendChild(n);
  setTimeout(() => n.remove(), bad ? 6000 : 3600);
}

/* ---------- réseau ---------- */
const BACKGROUND_PATHS = new Set(['/api/public', '/health', '/ready']);
function isBackground(url) {
  try { const p = new URL(String(url), location.origin).pathname; return BACKGROUND_PATHS.has(p) || p.endsWith('/live/metrics'); } catch (_) { return false; }
}
function progressStart() {
  state.progressCount += 1;
  if (state.progressCount > 1) return;
  clearTimeout(state.progressTimer);
  state.progressTimer = setTimeout(() => { const p = $('progress'); p.classList.remove('done'); p.classList.add('on'); }, 350);
}
function progressEnd() {
  state.progressCount = Math.max(0, state.progressCount - 1);
  if (state.progressCount) return;
  clearTimeout(state.progressTimer);
  const p = $('progress');
  if (p.classList.contains('on')) { p.classList.remove('on'); p.classList.add('done'); setTimeout(() => p.classList.remove('done'), 300); }
}
async function api(url, options = {}) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) };
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  if (state.csrf && options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  const background = Boolean(options.background) || isBackground(url);
  const request = { ...options }; delete request.background;
  if (!background) progressStart();
  try {
    const r = await fetch(url, { credentials: 'same-origin', cache: 'no-store', ...request, headers });
    let data = {};
    try { data = await r.json(); } catch (_) {}
    if (!r.ok) {
      const servedBy = r.headers.get('X-SentriX-HA-Served-By') || '';
      const branchSkew = r.status === 404 && servedBy === 'peer' && new URL(String(url), location.origin).pathname.startsWith('/api/guilds/');
      const message = branchSkew
        ? 'Le serveur de test n’est pas encore l’instance Discord active. La bascule HA est nécessaire pour tester cette nouvelle page.'
        : (data.error || data.message || `Erreur HTTP ${r.status}`);
      throw Object.assign(new Error(message), { status: branchSkew ? 503 : r.status, upstreamStatus: r.status, servedBy, data });
    }
    return data;
  } finally { if (!background) progressEnd(); }
}
const guildUrl = (path = '') => `/api/guilds/${encodeURIComponent(state.guildId)}${path}`;
const gget = path => api(guildUrl(path));
const gpost = (path, body, method = 'POST') => api(guildUrl(path), { method, body: JSON.stringify(body || {}) });
const gdel = path => api(guildUrl(path), { method: 'DELETE' });

/* ---------- cache par serveur ----------
   Les données déjà chargées sont réutilisées tant qu'elles sont valides ; une écriture
   invalide explicitement ce qui la concerne. */
async function cached(name, loader, { force = false, ttl = 60000 } = {}) {
  const key = `${state.guildId}:${name}`;
  const hit = state.cache.get(key);
  if (hit && !force && Date.now() - hit.at < ttl) return hit.value;
  if (hit?.pending && !force) return hit.pending;
  const pending = loader().then(value => { state.cache.set(key, { at: Date.now(), value }); return value; })
    .catch(e => { state.cache.delete(key); throw e; });
  state.cache.set(key, { at: 0, value: hit?.value, pending });
  return pending;
}
function invalidate(...names) {
  if (!names.length) { state.cache.clear(); return; }
  for (const n of names) state.cache.delete(`${state.guildId}:${n}`);
}
const diagnostics = (force = false) => cached('diagnostics', () => gget('/diagnostics'), { force });
const v62 = (force = false) => cached('v62', () => gget('/v62'), { force });
const setupTools = (force = false) => cached('setup-tools', () => gget('/setup-tools'), { force });
const opsOverview = (force = false) => cached('ops-overview', () => gget('/ops/overview'), { force });
async function v62Action(payload) { const r = await gpost('/v62', payload); invalidate('v62', 'diagnostics'); toast(r.message || 'Enregistré.'); return r; }
async function setupAction(payload) { const r = await gpost('/setup-tools', payload); invalidate('setup-tools', 'diagnostics'); toast(r.message || 'Action appliquée.'); return r; }
async function reloadGuild() {
  const data = await gget('');
  state.guild = data;
  invalidate('diagnostics');
  updateChrome();
}

/* ---------- modifications non enregistrées ---------- */
function hasDirty() { return Object.values(state.dirty).some(x => Object.keys(x).length); }
function markDirty(kind, key, value) {
  state.dirty[kind][key] = value;
  $('saveState').textContent = 'Modifications non enregistrées';
  $('saveBar').classList.remove('hidden');
}
function clearDirty() { state.dirty = { settings: {}, automod: {}, ai: {}, welcome: {} }; $('saveBar').classList.add('hidden'); }
/* Une erreur serveur qui nomme un réglage (« Le champ welcome_image_url … ») s'affiche sous ce
   champ ; les autres passent par un toast. */
function showFieldError(message) {
  const m = /Le (?:champ|réglage) ([a-z_]+)/i.exec(String(message || ''));
  const el = m && content().querySelector(`[data-setting="${m[1]}"],[data-automod="${m[1]}"],[data-ai="${m[1]}"]`);
  if (!el) return false;
  const holder = el.closest('.field, .switch-row'); if (!holder) return false;
  holder.classList.add('invalid');
  let slot = holder.querySelector('.error.server'); if (!slot) { slot = document.createElement('span'); slot.className = 'error server'; holder.appendChild(slot); }
  slot.textContent = String(message).replace(/^Le (?:champ|réglage) [a-z_]+ /i, 'Ce champ ');
  el.focus({ preventScroll: false });
  el.addEventListener('input', () => { holder.classList.remove('invalid'); slot.remove(); }, { once: true });
  return true;
}
async function saveDirty() {
  if (!hasDirty() || !state.guildId) return;
  const btn = $('saveButton'); btn.disabled = true; $('saveState').textContent = 'Enregistrement…';
  try {
    const { welcome, ...settings } = state.dirty;
    if (Object.values(settings).some(x => Object.keys(x).length)) await api(guildUrl('/settings'), { method: 'PUT', body: JSON.stringify(settings) });
    if (Object.keys(welcome || {}).length) {
      const current = state.cache.get(`${state.guildId}:welcome`)?.value || {};
      await api(guildUrl('/welcome'), { method: 'PUT', body: JSON.stringify({ title: current.title, show_avatar: current.show_avatar, show_member_count: current.show_member_count, mode: current.mode, goodbye_mode: current.goodbye_mode, ...welcome }) });
      invalidate('welcome');
    }
    clearDirty();
    toast('Modifications enregistrées.');
    await reloadGuild();
    await render();
  } catch (e) { $('saveState').textContent = 'Modifications non enregistrées'; if (!showFieldError(e.message)) toast(e.message, true); } finally { btn.disabled = false; }
}
function readControl(el) { return el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value; }
function bindEditable(root = content()) {
  for (const kind of ['setting', 'automod', 'ai', 'welcome']) {
    root.querySelectorAll(`[data-${kind}]`).forEach(el => {
      const bucket = kind === 'setting' ? 'settings' : kind;
      const handler = () => markDirty(bucket, el.dataset[kind], readControl(el));
      el.addEventListener('input', handler);
      el.addEventListener('change', handler);
    });
  }
  root.querySelectorAll('textarea[maxlength]').forEach(t => {
    const counter = t.closest('.field')?.querySelector('.counter');
    if (!counter) return;
    const sync = () => { counter.textContent = `${t.value.length} / ${t.maxLength}`; };
    t.addEventListener('input', sync); sync();
  });
}
async function guardDirty() {
  if (!hasDirty()) return true;
  const ok = await confirmDialog({ title: 'Modifications non enregistrées', body: 'Vous avez des modifications non enregistrées sur cette page.', confirm: 'Quitter sans enregistrer', cancel: 'Rester' });
  if (ok) clearDirty();
  return ok;
}

/* ---------- options Discord ---------- */
function roles() { return state.guild?.roles || []; }
function channels(type = 'text') {
  const all = state.guild?.channels || [];
  return all.filter(c => {
    const t = String(c.type);
    if (type === 'category') return t.includes('category');
    if (type === 'voice') return t.includes('voice') || t.includes('stage');
    if (type === 'any') return true;
    return !t.includes('voice') && !t.includes('category') && !t.includes('stage');
  });
}
function roleOptions(value = '', placeholder = 'Aucun rôle') {
  return `<option value="">${esc(placeholder)}</option>` + roles().map(r => `<option value="${esc(r.id)}" ${String(value || '') === String(r.id) ? 'selected' : ''}>@${esc(r.name)}</option>`).join('');
}
function channelOptions(value = '', type = 'text', placeholder = 'Aucun salon') {
  const prefix = type === 'category' ? '' : type === 'voice' ? '🔊 ' : '#';
  return `<option value="">${esc(placeholder)}</option>` + channels(type).map(c => `<option value="${esc(c.id)}" ${String(value || '') === String(c.id) ? 'selected' : ''}>${prefix}${esc(c.name)}</option>`).join('');
}
function channelName(id) { const c = (state.guild?.channels || []).find(x => String(x.id) === String(id)); return c ? `#${c.name}` : ''; }
function roleName(id) { const r = roles().find(x => String(x.id) === String(id)); return r ? `@${r.name}` : ''; }
function resourceIssue(field) {
  const d = state.cache.get(`${state.guildId}:diagnostics`)?.value;
  return (d?.invalid_resources || []).find(x => x.field === field) || null;
}

/* ---------- composants ---------- */
function card(title, copy, body, cls = '') {
  return `<section class="card ${cls}">${title || copy ? `<div class="card-head"><div>${title ? `<h2>${esc(title)}</h2>` : ''}${copy ? `<p>${esc(copy)}</p>` : ''}</div></div>` : ''}${body}</section>`;
}
function field(label, key, value = '', opts = {}) {
  const full = opts.full ? ' full' : '';
  const kind = opts.kind || 'setting';
  const attr = key ? `data-${kind}="${esc(key)}"` : (opts.id ? `id="${esc(opts.id)}"` : '');
  const issue = key && kind === 'setting' ? resourceIssue(key) : null;
  const hint = issue ? `<span class="error">${esc(issue.reason)}</span>` : opts.hint ? `<small>${esc(opts.hint)}</small>` : '';
  const id = opts.id || `f-${key || Math.random().toString(36).slice(2)}`;
  const idAttr = opts.id ? '' : `id="${id}"`;
  let control;
  if (opts.select) control = `<select ${attr} ${idAttr}>${opts.select}</select>`;
  else if (opts.textarea) control = `<textarea ${attr} ${idAttr} maxlength="${opts.max || 2000}" rows="${opts.rows || 4}" placeholder="${esc(opts.placeholder || '')}">${esc(value || '')}</textarea>`;
  else control = `<input ${attr} ${idAttr} type="${opts.type || 'text'}" value="${esc(value ?? '')}" ${opts.min != null ? `min="${opts.min}"` : ''} ${opts.max != null ? `max="${opts.max}"` : ''} ${opts.step != null ? `step="${opts.step}"` : ''} placeholder="${esc(opts.placeholder || '')}">`;
  const counter = opts.textarea ? `<span class="counter"></span>` : '';
  return `<div class="field${full}${issue ? ' invalid' : ''}"><div class="label-row"><label for="${esc(id)}">${esc(label)}</label>${counter}</div>${control}${hint}</div>`;
}
function switchRow(label, key, on, copy = '', kind = 'automod') {
  return `<label class="switch-row"><span class="switch-copy"><b>${esc(label)}</b>${copy ? `<span>${esc(copy)}</span>` : ''}</span><input class="switch" type="checkbox" data-${kind}="${esc(key)}" ${on ? 'checked' : ''}></label>`;
}
function advanced(body, copy = 'Réglages rares. Rien ici n’est nécessaire pour démarrer.', open = false) {
  return `<details class="advanced full" ${open ? 'open' : ''}><summary><span>Paramètres avancés</span><small>${esc(copy)}</small></summary><div class="advanced-body">${body}</div></details>`;
}
function emptyState(title, copy, action) {
  return `<div class="empty"><b>${esc(title)}</b>${copy ? `<span>${esc(copy)}</span>` : ''}${action ? `<button class="btn primary" type="button" data-empty-action="${esc(action.id)}">${esc(action.label)}</button>` : ''}</div>`;
}
const STATUS = { active: ['Activé', 'ok'], inactive: ['Désactivé', ''], missing: ['Non configuré', 'warn'], partial: ['Partiellement configuré', 'warn'], error: ['Erreur', 'bad'] };
function badge(code, label) {
  const [text, cls] = STATUS[code] || [String(code || '—'), ''];
  return `<span class="badge ${cls}">${esc(label || text)}</span>`;
}
function notice(text, kind = '') { return `<div class="notice ${kind}">${esc(text)}</div>`; }
function kpi(label, value) { return `<div class="kpi"><small>${esc(label)}</small><strong>${esc(value)}</strong></div>`; }
function errorView(e, retry) {
  const haPreview = Number(e?.status || 0) === 503 && e?.servedBy === 'peer';
  const title = haPreview ? 'Le serveur de test attend la bascule HA' : 'Impossible de charger cette page';
  const copy = haPreview
    ? 'Le dashboard affiché vient bien du standby, mais les données Discord sont encore servies par le primary. Cette page deviendra disponible dès que le standby sera l’instance active.'
    : (e?.message || 'Erreur inconnue');
  content().innerHTML = `<div class="error-state"><h2>${esc(title)}</h2><p>${esc(copy)}</p>${haPreview ? '<span class="badge warn">Standby passif</span>' : ''}<button class="btn primary" id="retryPage" type="button">Réessayer</button></div>`;
  $('retryPage').onclick = retry || (() => render(true));
}
function previewText(text) {
  /* Même table que cogs/control_center_v3.render_member_template, plus {level}/{xp} (Niveaux). */
  const g = state.guild?.guild || {}, u = state.user || {};
  const name = u.username || 'membre';
  return String(text || '')
    .replace(/\{member\}|\{membre\}|\{mention\}|\{user\}|\(user\)|\[user\]|<user>/g, '@' + name)
    .replace(/\{username\}/g, name).replace(/\{display_name\}/g, u.global_name || name)
    .replace(/\{server\}|\{serveur\}/g, g.name || 'Mon serveur')
    .replace(/\{member_count\}/g, String(g.members || 42))
    .replace(/\{level\}/g, '5').replace(/\{xp\}/g, '1 250');
}
function md(text) {
  return esc(previewText(text))
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(^|[^*])\*(?!\*)(.+?)\*(?!\*)/g, '$1<i>$2</i>')
    .replace(/__(.+?)__/g, '<u>$1</u>').replace(/`([^`]+)`/g, '<code>$1</code>');
}
function discordMessage({ content: text = '', embed = null } = {}) {
  let embedHtml = '';
  if (embed && (embed.title || embed.description || embed.image || embed.footer || (embed.fields || []).length)) {
    const fields = (embed.fields || []).filter(f => f && (f.name || f.value)).map(f => `<div class="d-field"><b>${md(f.name)}</b><div>${md(f.value)}</div></div>`).join('');
    const stamp = embed.timestamp ? 'Aujourd’hui à ' + new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) : '';
    embedHtml = `<div class="d-embed" style="border-left-color:${esc(embed.color || '#4da3ff')}"><div class="d-embed-main">${embed.author ? `<div class="d-foot">${esc(embed.author)}</div>` : ''}${embed.title ? `<div class="d-title">${md(embed.title)}</div>` : ''}${embed.description ? `<div class="d-desc">${md(embed.description)}</div>` : ''}${fields ? `<div class="d-fields">${fields}</div>` : ''}${embed.image ? `<img class="d-image" src="${esc(embed.image)}" alt="">` : ''}${embed.footer || stamp ? `<div class="d-foot">${esc(embed.footer || '')}${embed.footer && stamp ? ' • ' : ''}${stamp}</div>` : ''}</div>${embed.thumbnail ? `<div class="d-thumb">${embed.thumbnail === 'avatar' ? '<span class="d-avatar-thumb">' + esc((state.user?.username || 'M').slice(0, 1).toUpperCase()) + '</span>' : `<img src="${esc(embed.thumbnail)}" alt="">`}</div>` : ''}</div>`;
  }
  const body = text ? `<div class="d-text">${md(text)}</div>` : (embedHtml ? '' : `<div class="d-empty">Message vide.</div>`);
  return `<div class="discord-preview"><div class="d-avatar">S</div><div class="d-body"><span class="d-name">SentriX</span><span class="d-tag">APP</span><span class="d-time">Aujourd’hui</span>${body}${embedHtml}</div></div>`;
}

/* ---------- modales ---------- */
let modalResolve = null;
function openModal({ title, body, actions = [], onOpen }) {
  closeModal();
  $('modalTitle').textContent = title || '';
  $('modalBody').innerHTML = body || '';
  $('modalActions').innerHTML = actions.map((a, i) => `<button class="btn ${a.kind || ''}" type="button" data-modal-action="${i}">${esc(a.label)}</button>`).join('');
  $('modalActions').querySelectorAll('[data-modal-action]').forEach(b => b.onclick = async () => {
    const a = actions[Number(b.dataset.modalAction)];
    if (a.keep) { try { b.disabled = true; await a.onClick?.(); } finally { b.disabled = false; } return; }
    closeModal(a.value);
    await a.onClick?.();
  });
  $('modalBackdrop').classList.remove('hidden');
  const first = $('modalBody').querySelector('input,select,textarea,button');
  setTimeout(() => (first || $('modalClose')).focus(), 0);
  onOpen?.();
  return new Promise(res => { modalResolve = res; });
}
function closeModal(value) { $('modalBackdrop').classList.add('hidden'); const r = modalResolve; modalResolve = null; r?.(value); }
function confirmDialog({ title, body, confirm = 'Confirmer', cancel = 'Annuler', danger = false }) {
  return openModal({ title, body: `<p>${esc(body || '')}</p>`, actions: [{ label: cancel, value: false }, { label: confirm, value: true, kind: danger ? 'danger' : 'primary' }] }).then(Boolean);
}
function promptDialog({ title, label, value = '', placeholder = '', confirm = 'Valider', type = 'text' }) {
  return openModal({
    title,
    body: `<div class="field"><label for="promptInput">${esc(label || '')}</label>${type === 'textarea' ? `<textarea id="promptInput" rows="4" placeholder="${esc(placeholder)}">${esc(value)}</textarea>` : `<input id="promptInput" type="${esc(type)}" value="${esc(value)}" placeholder="${esc(placeholder)}">`}</div>`,
    actions: [{ label: 'Annuler', value: null }, { label: confirm, kind: 'primary', value: '__read__' }],
  }).then(v => v === '__read__' ? $('promptInput').value : null);
}
function pickDialog({ title, items, search = true, render: draw }) {
  return openModal({
    title,
    body: `${search ? `<input class="input" id="pickSearch" type="search" placeholder="Rechercher…" autocomplete="off">` : ''}<div class="options" id="pickOptions"></div>`,
    actions: [{ label: 'Annuler', value: null }],
    onOpen: () => {
      const box = $('pickOptions');
      const paint = q => {
        const n = String(q || '').toLocaleLowerCase('fr');
        const list = items.filter(i => !n || i.label.toLocaleLowerCase('fr').includes(n));
        box.innerHTML = list.length ? list.map(i => `<button type="button" data-pick="${esc(i.value)}">${draw ? draw(i) : esc(i.label)}</button>`).join('') : '<div class="empty">Aucun résultat.</div>';
        box.querySelectorAll('[data-pick]').forEach(b => b.onclick = () => closeModal(items.find(i => String(i.value) === b.dataset.pick)));
      };
      paint('');
      const s = $('pickSearch'); if (s) { s.oninput = () => paint(s.value); s.focus(); }
    },
  });
}
$('modalClose').onclick = () => closeModal();
$('modalBackdrop').onclick = e => { if (e.target === $('modalBackdrop')) closeModal(); };

/* ---------- chrome (barre latérale, en-tête) ---------- */
function updateChrome() {
  const d = state.guild;
  if (!d) {
    const user = state.user || {};
    $('sideGuildName').textContent = 'Mon espace';
    $('sideGuildMeta').textContent = 'Choisissez un serveur pour le configurer';
    if (user.avatar_url) $('sideGuildIcon').innerHTML = `<img src="${esc(user.avatar_url)}" alt="">`;
    else $('sideGuildIcon').textContent = String(user.global_name || user.username || 'ME').slice(0, 2).toUpperCase();
    return;
  }
  const g = d.guild || {};
  $('sideGuildName').textContent = g.name || 'Serveur';
  $('sideGuildMeta').textContent = `${plural(g.members, 'membre')} · ${plural(g.channels_count, 'salon')}`;
  if (g.icon_url) $('sideGuildIcon').innerHTML = `<img src="${esc(g.icon_url)}" alt="">`;
  else $('sideGuildIcon').textContent = (g.name || 'S').slice(0, 2).toUpperCase();
}
function setRuntime(online, latency) {
  $('runtimeDot').classList.toggle('off', !online);
  $('runtimeText').textContent = online ? `En ligne${latency != null ? ` · ${latency} ms` : ''}` : 'Reconnexion Discord…';
}
