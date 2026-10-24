/* ---------- Vue d'ensemble : une carte par module ---------- */
const MODULE_SWITCH = { welcome: 'welcome', goodbye: 'goodbye', levels: 'levels', economy: 'economy', logs: 'logs', roles: 'roles', tickets: 'tickets', notifications: 'notifications', automod: 'security', ai: 'ai', moderation: 'moderation' };
const OVERVIEW_CARDS = [
  { key: 'welcome', title: 'Accueil & Départs', page: 'welcome', info: () => { const s = settings(); return s.welcome_channel ? `Salon : ${channelName(s.welcome_channel) || 'introuvable'}` : 'Aucun salon choisi'; } },
  { key: 'levels', title: 'Niveaux', page: 'levels', info: () => { const s = settings(); return s.level_channel ? `Annonces : ${channelName(s.level_channel) || 'introuvable'}` : `${plural(metrics().profiles, 'membre')} avec une progression`; } },
  { key: 'economy', title: 'Économie', page: 'economy', info: () => plural(metrics().economy_accounts, 'compte') },
  { key: 'automod', title: 'Sécurité', page: 'security', info: () => { const a = state.guild?.automod || {}; const n = AUTOMOD.filter(([k]) => a[k]).length; return n ? `${plural(n, 'protection active', 'protections actives')}` : 'Aucune protection active'; } },
  { key: 'tickets', title: 'Tickets', page: 'tickets', info: (m) => m?.detail || '' },
  { key: 'logs', title: 'Logs', page: 'logs', info: () => { const s = settings(); const n = LOG_TYPES.filter(([, k]) => s[k]).length + (s.log_channel ? 1 : 0); return n ? `${n}/${LOG_TYPES.length + 1} salons choisis` : 'Aucun salon choisi'; } },
  { key: 'roles', title: 'Rôles', page: 'roles', info: () => { const s = settings(); return s.autorole ? `À l’arrivée : ${roleName(s.autorole) || 'rôle introuvable'}` : 'Aucun rôle automatique'; } },
  { key: 'notifications', title: 'Notifications', page: 'notifications', info: () => { const n = (state.guild?.social_notifications || []).filter(x => x.enabled !== 0).length; return n ? plural(n, 'source') : 'Aucune source suivie'; } },
];
const AUTOMOD = [
  ['antispam', 'Anti-spam', 'Bloque les rafales de messages.'],
  ['antilink', 'Anti-liens', 'Supprime les liens non autorisés.'],
  ['antilink_strict', 'Blocage total des liens', 'Refuse tous les liens hors exceptions.'],
  ['antiinvite', 'Anti-invitations', 'Filtre les invitations Discord.'],
  ['antimention', 'Anti-mentions', 'Limite les mentions de masse.'],
  ['anticaps', 'Anti-majuscules', 'Réduit les messages tout en majuscules.'],
  ['antiemoji', 'Anti-émojis', 'Limite les répétitions d’émojis.'],
  ['antiscam', 'Anti-scam', 'Filtre les contenus à risque.'],
  ['antiinsult', 'Anti-insultes', 'Filtre insultes et mots interdits.'],
  ['antiraid', 'Anti-raid', 'Réagit aux arrivées anormales.'],
  ['antibot', 'Anti-bots', 'Contrôle les ajouts de bots.'],
  ['antiaccount', 'Anti-comptes récents', 'Détecte les comptes trop récents.'],
  ['join_gate', 'Contrôle des arrivées', 'Évalue la confiance à l’arrivée.'],
  ['risk_engine', 'Analyse des risques', 'Combine les signaux de sécurité.'],
  ['antinuke', 'Protection anti-destruction', 'Protège salons, rôles et actions critiques.'],
  ['security_vanity', 'Lien personnalisé', 'Surveille le lien personnalisé.'],
  ['security_prune', 'Suppressions massives', 'Détecte les suppressions massives de membres.'],
  ['security_permissions', 'Permissions dangereuses', 'Bloque les élévations critiques.'],
  ['escalation', 'Sanctions progressives', 'Compte les récidives (infractions sur 1 h). Les filtres incertains ne sanctionnent jamais seuls.'],
];
const LOG_TYPES = [['Messages', 'log_messages'], ['Membres', 'log_members'], ['Vocal', 'log_voice'], ['Rôles', 'log_roles'], ['Serveur', 'log_server'], ['AutoMod', 'log_automod'], ['Modération', 'log_moderation'], ['Tickets', 'ticket_log_channel'], ['Erreurs', 'error_channel']];
const settings = () => state.guild?.settings || {};
const metrics = () => state.guild?.metrics || {};

function moduleStatus(m) {
  if (!m) return 'missing';
  if (m.code === 'active' && m.configured === false) return 'partial';
  return m.code;
}
async function toggleModule(module, action) {
  try {
    await gpost('/modules', { module, action });
    toast(action === 'enable' ? 'Module activé.' : 'Module désactivé.');
    invalidate('diagnostics');
    await render();
  } catch (e) { toast(e.message, true); }
}
function bindModuleButtons(root = content()) {
  root.querySelectorAll('[data-module]').forEach(b => b.onclick = () => toggleModule(b.dataset.module, b.dataset.action));
  root.querySelectorAll('[data-go]').forEach(b => b.onclick = () => go(b.dataset.go, b.dataset.goSub || ''));
}

function renderProfile() {
  const installed = state.guilds.filter(g => g.installed);
  const missing = state.guilds.filter(g => !g.installed);
  const user = state.user || {};
  const display = user.global_name || user.username || 'Compte Discord';
  const avatar = user.avatar_url ? `<img src="${esc(user.avatar_url)}" alt="">` : esc(String(display).slice(0, 2).toUpperCase());
  const details = [
    ['Identifiant', user.id],
    ['Nom Discord', user.username],
    ['Bio', user.bio],
    ['Anniversaire', user.birthday],
    ['Localisation', user.location],
  ].filter(([, value]) => value != null && String(value).trim() !== '');
  const serverItem = (g, add = false) => `<div class="row"><span class="server-icon">${g.icon_url ? `<img src="${esc(g.icon_url)}" alt="">` : esc((g.name || 'S').slice(0, 2).toUpperCase())}</span><div class="row-main"><b>${esc(g.name)}</b><small>${add ? 'SentriX n’est pas encore installé' : (g.owner ? 'Propriétaire' : 'Administrateur')}</small></div>${add ? `<a class="btn sm" href="${esc(g.invite_url || '#')}">Ajouter</a>` : `<button class="btn sm primary" type="button" data-profile-guild="${esc(g.id)}">Configurer</button>`}</div>`;
  content().innerHTML = `<div class="grid"><section class="card full"><div class="profile-line"><span class="avatar big">${avatar}</span><div><h2>${esc(display)}</h2><p>Votre espace SentriX avant de configurer un serveur.</p></div></div>${details.length ? `<div class="list compact" style="margin-top:14px">${details.map(([k, v]) => `<div class="row"><div class="row-main"><b>${esc(k)}</b><small>${esc(v)}</small></div></div>`).join('')}</div>` : `<p class="info" style="margin-top:12px">Aucune donnée de profil étendue n’est fournie par le backend actuel.</p>`}</section><section class="card full"><div class="card-head"><div><h2>Mes serveurs</h2><p>Choisissez où travailler. Aucun identifiant à coller.</p></div><button class="btn" type="button" id="profilePickServer">Choisir un serveur</button></div><div class="list">${installed.length ? installed.map(g => serverItem(g)).join('') : emptyState('Aucun serveur avec SentriX', 'Ajoutez SentriX à un serveur dont vous êtes administrateur.')}</div></section><section class="card"><h2>Préférences dashboard</h2><div class="list compact"><label class="switch-row"><span class="switch-copy"><b>Ouvrir le dernier serveur utilisé</b><span>Cette préférence reste dans ce navigateur.</span></span><input class="switch" id="prefLastGuild" type="checkbox" ${localStorage.getItem('sentrix:guild') ? 'checked' : ''}></label><label class="switch-row"><span class="switch-copy"><b>Garder “Plus d’outils” ouvert</b><span>Utile si vous utilisez souvent les pages avancées.</span></span><input class="switch" id="prefMoreTools" type="checkbox" ${state.navMore ? 'checked' : ''}></label></div></section><section class="card"><h2>Ajouter SentriX</h2><div class="list">${missing.length ? missing.slice(0, 6).map(g => serverItem(g, true)).join('') : '<p class="info">Tous les serveurs visibles ont déjà SentriX, ou Discord ne fournit pas d’autre serveur administrable.</p>'}</div></section></div>`;
  $('profilePickServer').onclick = openServerPicker;
  content().querySelectorAll('[data-profile-guild]').forEach(b => b.onclick = () => selectGuild(b.dataset.profileGuild));
  $('prefLastGuild').onchange = () => { if (!$('prefLastGuild').checked) localStorage.removeItem('sentrix:guild'); else if (state.guildId) localStorage.setItem('sentrix:guild', state.guildId); };
  $('prefMoreTools').onchange = () => { state.navMore = $('prefMoreTools').checked; localStorage.setItem('sentrix:nav:more', state.navMore ? '1' : '0'); renderNav(); };
}
/* Icônes au trait (24×24, currentColor) : une forme reconnaissable par domaine,
   à la place des abréviations « SE », « LG »… illisibles d'un coup d'œil. */
const SX_ICONS = {
  welcome: '<path d="M4 20V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v15"/><path d="M14 8h4a1 1 0 0 1 1 1v11"/><path d="M2 20h20"/><circle cx="11" cy="12" r=".9" fill="currentColor"/>',
  levels: '<path d="M4 19h16"/><path d="M6 16v-3"/><path d="M11 16V9"/><path d="M16 16V5"/><path d="m14 7 2-2 2 2"/>',
  economy: '<circle cx="12" cy="12" r="8"/><path d="M14.5 9.5c-.5-1-1.4-1.5-2.5-1.5-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.8 2.5 2-1 2-2.5 2c-1.1 0-2-.5-2.5-1.5"/><path d="M12 6.5v1.5M12 16v1.5"/>',
  automod: '<path d="M12 3 5 6v5c0 4.4 3 8.3 7 9.5 4-1.2 7-5.1 7-9.5V6l-7-3Z"/><path d="m9 12 2 2 4-4"/>',
  tickets: '<path d="M4 8a2 2 0 0 0 2-2h12a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H6a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4V8Z"/><path d="M14 6v12" stroke-dasharray="2 2"/>',
  logs: '<path d="M7 4h10a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/><path d="M9 9h6M9 13h6M9 17h3"/>',
  roles: '<path d="M3 12V4h8l9 9-8 8-9-9Z"/><circle cx="7.5" cy="8.5" r="1.3"/>',
  notifications: '<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4l2-2Z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  live: '<circle cx="12" cy="12" r="3"/><path d="M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8"/>',
  alert: '<path d="M12 4 2.5 20h19L12 4Z"/><path d="M12 10v4"/><circle cx="12" cy="17" r=".9" fill="currentColor"/>',
  sanction: '<path d="m14 4 6 6M12 6l6 6M4 20l7-7M9 9l6 6"/>',
  arrival: '<circle cx="10" cy="8" r="3.5"/><path d="M3.5 20a6.5 6.5 0 0 1 13 0"/><path d="M19 8v6M16 11h6"/>',
  ticket: '<path d="M4 8a2 2 0 0 0 2-2h12a2 2 0 0 0 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 0-2 2H6a2 2 0 0 0-2-2v-2a2 2 0 0 0 0-4V8Z"/>',
  command: '<path d="m5 7 5 5-5 5"/><path d="M12 17h7"/>',
};
function sxIcon(name, cls = 'sx-icon') {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${SX_ICONS[name] || SX_ICONS.activity}</svg>`;
}
const MODULE_VISUAL = {
  welcome: ['welcome', 'Communauté'], levels: ['levels', 'Progression'],
  economy: ['economy', 'Progression'], automod: ['automod', 'Protection'],
  tickets: ['tickets', 'Assistance'], logs: ['logs', 'Surveillance'],
  roles: ['roles', 'Communauté'], notifications: ['notifications', 'Automatisation'],
};
function moduleCard({ key, title, page, info }, m) {
  const code = moduleStatus(m);
  const sw = MODULE_SWITCH[key];
  const off = code === 'missing' || code === 'inactive';
  const toggle = sw ? (off ? `<button class="btn sm" type="button" data-module="${sw}" data-action="enable">Activer</button>` : `<button class="btn sm ghost" type="button" data-module="${sw}" data-action="disable">Désactiver</button>`) : '';
  const visual = MODULE_VISUAL[key] || ['activity', 'Outil'];
  let line = ''; try { line = info(m) || ''; } catch (_) {}
  return `<article class="module-card sx-module-card" data-sx-module="${esc(key)}" data-sx-status="${esc(code)}">
    <div class="sx-module-heading">
      <span class="sx-module-icon" aria-hidden="true">${sxIcon(visual[0])}</span>
      <div class="sx-module-copy"><span class="sx-module-category">${esc(visual[1])}</span><h3>${esc(title)}</h3></div>
      ${badge(code)}
    </div>
    <p class="info">${esc(line)}</p>
    <div class="toolbar"><button class="btn sm primary" type="button" data-go="${page}">${off ? 'Configurer' : 'Gérer'} <span aria-hidden="true">↗</span></button>${toggle}</div>
  </article>`;
}
/* En-tête de module réutilisé par chaque page : titre + statut + Activer/Désactiver. */
async function moduleHead(key, copy, title) {
  let m = null; try { m = (await diagnostics()).modules?.[key] || null; } catch (_) {}
  const code = moduleStatus(m);
  const sw = MODULE_SWITCH[key];
  const off = code === 'missing' || code === 'inactive';
  const toggle = sw ? (off ? `<button class="btn primary" type="button" data-module="${sw}" data-action="enable">Activer</button>` : `<button class="btn" type="button" data-module="${sw}" data-action="disable">Désactiver</button>`) : '';
  const problem = code === 'error' && m?.detail ? `<div class="notice bad">${esc(m.detail)}</div>` : '';
  return `<section class="card full"><div class="card-head"><div><h2>${esc(title || pageMeta(state.page)[0])}</h2>${copy ? `<p>${esc(copy)}</p>` : ''}</div><div class="toolbar">${badge(code)}${toggle}</div></div>${problem}</section>`;
}

/* ---------- Centre de commande ----------
   Une seule source par chiffre : santé = score de l'assistant (repli : diagnostic),
   modules actifs = les cartes affichées plus bas, activité = /activity (lignes
   réellement enregistrées par SentriX). */
const activityData = (force = false) => cached('activity', () => gget('/activity'), { force, ttl: 30000 });

function relativeTime(ts) {
  const diff = Math.max(0, Math.round(Date.now() / 1000 - Number(ts || 0)));
  if (diff < 60) return 'à l’instant';
  if (diff < 3600) return `il y a ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `il y a ${Math.floor(diff / 3600)} h`;
  const d = Math.floor(diff / 86400);
  return d === 1 ? 'hier' : `il y a ${d} j`;
}
function dayLabel(offsetFromToday, opts = { weekday: 'short', day: 'numeric' }) {
  const d = new Date(Date.now() - offsetFromToday * 86400000);
  return d.toLocaleDateString('fr-FR', opts);
}
function healthState(score, bad) {
  if (bad || score < 50) return ['bad', 'Critique'];
  if (score < 80) return ['warn', 'À surveiller'];
  return ['ok', 'Excellent'];
}

function healthRing(score, kind, label) {
  const r = 46, c = 2 * Math.PI * r, value = Math.max(0, Math.min(100, Number(score) || 0));
  return `<div class="cc-ring cc-${kind}" role="img" aria-label="Santé du serveur : ${value} %, ${esc(label)}">
    <svg viewBox="0 0 120 120" aria-hidden="true">
      <circle class="cc-ring-track" cx="60" cy="60" r="${r}"/>
      <circle class="cc-ring-value" cx="60" cy="60" r="${r}" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${c.toFixed(1)}" data-target="${(c * (1 - value / 100)).toFixed(1)}"/>
    </svg>
    <div class="cc-ring-copy"><strong><span data-count="${value}">0</span><sup>%</sup></strong><small>santé</small></div>
    <span class="cc-ring-label badge ${kind}">${esc(label)}</span>
  </div>`;
}

function sumLast(list, from, to) { return (list || []).slice(from, to).reduce((a, b) => a + Number(b || 0), 0); }

function trendTile(icon, label, series) {
  const days = (series || []).length;
  const now = sumLast(series, days - 7, days), before = sumLast(series, days - 14, days - 7);
  let trend = '<span class="cc-trend">stable</span>';
  if (before === 0 && now > 0) trend = '<span class="cc-trend up">nouveau</span>';
  else if (before > 0) {
    const pct = Math.round((now - before) / before * 100);
    trend = pct === 0 ? '<span class="cc-trend">stable</span>'
      : `<span class="cc-trend ${pct > 0 ? 'up' : 'down'}">${pct > 0 ? '▲' : '▼'} ${Math.abs(pct)} %</span>`;
  }
  return `<div class="cc-tile">${sxIcon(icon)}<div><small>${esc(label)} · 7 j</small><strong>${number(now)}</strong>${trend}</div></div>`;
}

const ACTIVITY_SERIES = [
  ['commands', 'Commandes'], ['arrivals', 'Arrivées'], ['automod', 'Blocages AutoMod'],
  ['sanctions', 'Sanctions'], ['tickets', 'Tickets ouverts'],
];

function activityChart(a) {
  const s = a.series || {}, cmds = s.commands || [], n = cmds.length || 14;
  const W = 640, H = 190, left = 34, right = 8, top = 12, bottom = 24;
  const plotW = W - left - right, plotH = H - top - bottom;
  const rawMax = Math.max(1, ...cmds.map(Number));
  const step = Math.pow(10, Math.floor(Math.log10(rawMax)));
  const max = Math.ceil(rawMax / step) * step;
  const slot = plotW / n, bw = Math.max(4, slot - 6);
  const y = v => top + plotH - (v / max) * plotH;
  const bars = cmds.map((v, i) => {
    const h = Math.max(v ? 3 : 0, (v / max) * plotH), x = left + i * slot + (slot - bw) / 2, yt = top + plotH - h, rr = Math.min(4, h / 2, bw / 2);
    const path = h ? `M${x},${top + plotH} V${yt + rr} Q${x},${yt} ${x + rr},${yt} H${x + bw - rr} Q${x + bw},${yt} ${x + bw},${yt + rr} V${top + plotH} Z` : '';
    const today = i === n - 1;
    return `<g class="cc-bar${today ? ' today' : ''}" data-i="${i}">
      <rect class="cc-hit" x="${left + i * slot}" y="${top}" width="${slot}" height="${plotH}" tabindex="0" aria-label="${esc(dayLabel(n - 1 - i, { weekday: 'long', day: 'numeric', month: 'long' }))} : ${number(v)} commandes"/>
      ${path ? `<path class="cc-bar-mark" d="${path}"/>` : ''}
    </g>`;
  }).join('');
  const ticks = [0, max / 2, max].map(v => `<g class="cc-grid"><line x1="${left}" x2="${W - right}" y1="${y(v)}" y2="${y(v)}"/><text x="${left - 6}" y="${y(v) + 3}" text-anchor="end">${number(v)}</text></g>`).join('');
  const labels = cmds.map((_, i) => (i % 2 === (n - 1) % 2) ? `<text class="cc-x" x="${left + i * slot + slot / 2}" y="${H - 6}" text-anchor="middle">${esc(i === n - 1 ? 'auj.' : dayLabel(n - 1 - i, { day: 'numeric' }))}</text>` : '').join('');
  const rows = cmds.map((_, i) => `<tr><th scope="row">${esc(dayLabel(n - 1 - i, { weekday: 'short', day: 'numeric', month: 'short' }))}</th>${ACTIVITY_SERIES.map(([k]) => `<td>${number((s[k] || [])[i] || 0)}</td>`).join('')}</tr>`).reverse().join('');
  return `<div class="cc-chart">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Commandes par jour sur ${n} jours">${ticks}${bars}${labels}</svg>
      <div class="cc-tooltip hidden" role="status" aria-live="polite"></div>
    </div>
    <details class="cc-table"><summary>Voir le tableau</summary><div class="table-wrap"><table><thead><tr><th scope="col">Jour</th>${ACTIVITY_SERIES.map(([, l]) => `<th scope="col">${esc(l)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></details>`;
}

function bindActivityChart(a) {
  const root = content().querySelector('.cc-chart'); if (!root) return;
  const tip = root.querySelector('.cc-tooltip'), s = a.series || {}, n = (s.commands || []).length;
  const show = g => {
    const i = Number(g.dataset.i);
    root.querySelectorAll('.cc-bar.on').forEach(x => x.classList.remove('on')); g.classList.add('on');
    tip.innerHTML = `<b>${esc(i === n - 1 ? 'Dernières 24 h' : dayLabel(n - 1 - i, { weekday: 'long', day: 'numeric', month: 'long' }))}</b>${ACTIVITY_SERIES.map(([k, l]) => `<span><em>${esc(l)}</em><strong>${number((s[k] || [])[i] || 0)}</strong></span>`).join('')}`;
    tip.classList.remove('hidden');
    const box = root.getBoundingClientRect(), hit = g.querySelector('.cc-hit').getBoundingClientRect();
    const x = hit.left - box.left + hit.width / 2;
    tip.style.left = `${Math.max(8, Math.min(box.width - tip.offsetWidth - 8, x - tip.offsetWidth / 2))}px`;
  };
  const hide = () => { tip.classList.add('hidden'); root.querySelectorAll('.cc-bar.on').forEach(x => x.classList.remove('on')); };
  root.querySelectorAll('.cc-bar').forEach(g => {
    g.addEventListener('mouseenter', () => show(g));
    const hit = g.querySelector('.cc-hit');
    hit.addEventListener('focus', () => show(g));
    hit.addEventListener('blur', hide);
  });
  root.addEventListener('mouseleave', hide);
}

const FEED_ICON = { sanction: 'sanction', automod: 'automod', arrival: 'arrival', ticket: 'ticket' };
function feedItem(e) {
  const who = e.member?.name || (e.member?.id ? `Membre ${String(e.member.id).slice(-4)}` : 'Membre');
  const initial = esc(who.slice(0, 1).toUpperCase());
  // Avatar supprimé ou CDN injoignable : l'initiale reprend sa place.
  const avatar = e.member?.avatar_url ? `<img src="${esc(e.member.avatar_url)}" alt="" onerror="this.replaceWith(document.createTextNode('${initial}'))">` : initial;
  const by = e.actor?.name ? (e.kind === 'arrival' ? ` · invité par ${esc(e.actor.name)}` : ` · par ${esc(e.actor.name)}`) : '';
  return `<li class="cc-event cc-${esc(e.kind)}">
    <span class="cc-avatar">${avatar}<i>${sxIcon(FEED_ICON[e.kind] || 'activity', 'sx-icon sm')}</i></span>
    <div class="cc-event-copy"><b>${esc(e.title)}</b><span>${esc(who)}${by}${e.detail ? ` — ${esc(e.detail)}` : ''}</span></div>
    <time datetime="${new Date(e.at * 1000).toISOString()}" title="${esc(when(e.at))}">${esc(relativeTime(e.at))}</time>
  </li>`;
}

function attentionItems(d, guide) {
  const items = [];
  for (const issue of (guide?.issues || [])) items.push({ page: issue.tab || 'diagnostic', title: issue.title, detail: issue.detail || issue.fix || '', kind: issue.severity === 'error' ? 'bad' : 'warn' });
  for (const [key, mod] of Object.entries(d.modules || {})) {
    const code = moduleStatus(mod);
    if (code !== 'error' && code !== 'partial') continue;
    const ref = OVERVIEW_CARDS.find(x => x.key === key);
    if (ref && !items.some(x => x.page === ref.page)) items.push({ page: ref.page, title: `${ref.title} à compléter`, detail: mod?.detail || 'Configuration incomplète.', kind: code === 'error' ? 'bad' : 'warn' });
  }
  for (const r of (d.invalid_resources || []).slice(0, 4)) items.push({ page: 'diagnostic', title: r.field || r.type || 'Ressource introuvable', detail: r.reason || 'Salon ou rôle supprimé.', kind: 'bad' });
  return items;
}

function animateCommandCenter() {
  const root = content();
  const still = typeof REDUCED_MOTION === 'function' && REDUCED_MOTION();
  root.querySelectorAll('.cc-ring-value').forEach(c => { const t = c.dataset.target; if (still) c.style.transition = 'none'; requestAnimationFrame(() => { c.style.strokeDashoffset = t; }); });
  root.querySelectorAll('[data-count]').forEach(el => {
    const end = Number(el.dataset.count || 0);
    if (still || !end) { el.textContent = number(end); return; }
    const t0 = performance.now(), dur = 900;
    const tick = t => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.textContent = number(Math.round(end * e)); if (k < 1) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  });
}

async function renderOverview() {
  const [d, guide, activity, live] = await Promise.all([
    diagnostics(),
    guidanceDiagnostic().catch(() => null),
    activityData().catch(() => null),
    api(guildUrl('/live/metrics'), { background: true }).catch(() => null),
  ]);
  const mods = d.modules || {};
  const g = state.guild?.guild || {};
  const a = state.guild?.automod || {};
  const configured = Object.values(mods).some(m => m.configured || m.code === 'active');
  const activeCount = OVERVIEW_CARDS.filter(card => moduleStatus(mods[card.key]) === 'active').length;
  const protections = AUTOMOD.filter(([k]) => Boolean(a[k])).length;
  const score = Number(guide?.score ?? d.score ?? 0);
  const issues = attentionItems(d, guide);
  const [kind, label] = healthState(score, issues.some(x => x.kind === 'bad'));
  const online = live ? Boolean(live.online) : true;
  const latency = live?.latency_ms;
  const icon = g.icon_url ? `<img src="${esc(g.icon_url)}" alt="">` : esc(String(g.name || 'S').slice(0, 1).toUpperCase());
  const steps = Array.isArray(guide?.onboarding) ? guide.onboarding : [];
  const done = steps.filter(x => x.ready).length;
  const series = activity?.series || {};
  const commands24 = Number(live?.commands_24h ?? (series.commands || []).slice(-1)[0] ?? 0);
  const onboarding = !configured ? `<section class="card full cc-welcome"><div class="card-head"><div><h2>Bienvenue dans SentriX</h2><p>Configurez les fonctions principales en quelques étapes. Rien n’est modifié avant la dernière étape.</p></div><button class="btn primary" type="button" id="startWizard">Commencer</button></div></section>` : '';

  content().innerHTML = `<div class="grid sx-overview-layout cc">
    <section class="cc-hero full" aria-label="Centre de commande">
      <div class="cc-hero-glow" aria-hidden="true"></div>
      <div class="cc-identity">
        <span class="cc-server-icon">${icon}</span>
        <div>
          <span class="cc-eyebrow">Centre de commande</span>
          <h2>${esc(g.name || 'Serveur')}</h2>
          <span class="cc-live ${online ? 'on' : 'off'}"><i aria-hidden="true"></i>${online ? `SentriX en ligne${Number.isFinite(latency) ? ` · ${number(latency)} ms` : ''}` : 'SentriX se reconnecte à Discord'}</span>
        </div>
      </div>
      ${healthRing(score, kind, label)}
      <div class="cc-stats">
        <div class="cc-stat">${sxIcon('arrival')}<div><strong data-count="${Number(g.members || 0)}">0</strong><small>membres</small></div></div>
        <div class="cc-stat">${sxIcon('activity')}<div><strong>${number(activeCount)}<em>/${number(OVERVIEW_CARDS.length)}</em></strong><small>modules actifs</small></div></div>
        <div class="cc-stat">${sxIcon('automod')}<div><strong>${number(protections)}<em>/${number(AUTOMOD.length)}</em></strong><small>protections</small></div></div>
        <div class="cc-stat">${sxIcon('command')}<div><strong data-count="${commands24}">0</strong><small>commandes · 24 h</small></div></div>
      </div>
      <div class="cc-actions">
        ${issues.length ? `<button class="btn primary" type="button" data-go="diagnostic">${sxIcon('alert', 'sx-icon sm')} Corriger ${plural(issues.length, 'point')}</button>` : `<span class="badge ok">Aucun point bloquant</span>`}
        ${steps.length && done < steps.length ? `<button class="btn" type="button" data-go="onboarding">Démarrage guidé · ${done}/${steps.length}</button>` : ''}
        <button class="btn ghost" type="button" data-go="security">Sécurité</button>
      </div>
    </section>
    ${onboarding}
    <section class="card cc-activity" aria-labelledby="ccActivityTitle">
      <div class="card-head"><div><h2 id="ccActivityTitle">${sxIcon('activity', 'sx-icon sm')} Activité · 14 jours</h2><p>Commandes utilisées chaque jour. Survolez une barre pour le détail.</p></div></div>
      ${activity ? activityChart(activity) : emptyState('Activité indisponible', 'Les statistiques reviendront à la prochaine actualisation.')}
      ${activity ? `<div class="cc-tiles">${trendTile('arrival', 'Arrivées', series.arrivals)}${trendTile('automod', 'Blocages', series.automod)}${trendTile('sanction', 'Sanctions', series.sanctions)}${trendTile('ticket', 'Tickets', series.tickets)}</div>` : ''}
    </section>
    <section class="card cc-feed" aria-labelledby="ccFeedTitle">
      <div class="card-head"><div><h2 id="ccFeedTitle"><span class="cc-pulse" aria-hidden="true"></span> En direct</h2><p>Les derniers événements du serveur.</p></div><button class="btn sm ghost" type="button" data-go="logs">Logs</button></div>
      ${(activity?.feed || []).length ? `<ol class="cc-events">${activity.feed.map(feedItem).join('')}</ol>` : emptyState('Rien pour l’instant', 'Sanctions, blocages, arrivées et tickets apparaîtront ici dès qu’ils se produisent.')}
    </section>
    ${issues.length ? `<section class="card full cc-attention" aria-labelledby="ccAttentionTitle">
      <div class="card-head"><div><h2 id="ccAttentionTitle">${sxIcon('alert', 'sx-icon sm')} À corriger en priorité</h2><p>Les points qui peuvent réellement bloquer SentriX.</p></div><span class="badge warn">${number(issues.length)}</span></div>
      <div class="list">${issues.slice(0, 6).map(x => `<div class="row"><div class="row-main"><b>${esc(x.title)}</b><small>${esc(x.detail)}</small></div><div class="row-actions"><span class="badge ${x.kind}">${x.kind === 'bad' ? 'Bloquant' : 'À vérifier'}</span><button class="btn sm" type="button" data-go="${esc(x.page)}">Ouvrir</button></div></div>`).join('')}</div>
    </section>` : ''}
    <section class="sx-module-section full" aria-labelledby="sx-modules-title">
      <div class="sx-section-heading"><div><span class="sx-section-eyebrow">CONFIGURATION</span><h2 id="sx-modules-title">Modules de votre serveur</h2><p>Activez seulement ce dont vous avez besoin. Chaque carte mène à ses réglages.</p></div><span class="sx-section-counter">${number(activeCount)} / ${number(OVERVIEW_CARDS.length)} actifs</span></div>
      <div class="module-grid">${OVERVIEW_CARDS.map(card => moduleCard(card, mods[card.key])).join('')}</div>
    </section>
  </div>`;
  bindModuleButtons();
  if (activity) bindActivityChart(activity);
  animateCommandCenter();
  renderNav();
  const w = $('startWizard'); if (w) w.onclick = openWizard;
}

/* ---------- première configuration (assistant) ----------
   Les réponses sont gardées en mémoire et envoyées d'un bloc à la fin. */
const WIZARD_STEPS = [
  { id: 'welcome', title: 'Message de bienvenue', body: () => `<p>Un message envoyé quand quelqu’un rejoint le serveur.</p><div class="fields">${field('Salon', '', settings().welcome_channel, { id: 'wzWelcomeChannel', select: channelOptions(settings().welcome_channel), full: true })}${field('Message', '', settings().welcome_message || 'Bienvenue {user} sur {server} !', { id: 'wzWelcomeMessage', textarea: true, max: 2000, full: true })}</div>`,
    read: a => { const c = $('wzWelcomeChannel').value; if (c) { a.settings.welcome_channel = c; a.settings.welcome_message = $('wzWelcomeMessage').value; a.modules.push('welcome'); } } },
  { id: 'logs', title: 'Logs', body: () => `<p>Le salon où SentriX écrit ce qui se passe (messages supprimés, arrivées, sanctions…).</p><div class="fields">${field('Salon des logs', '', settings().log_channel, { id: 'wzLogChannel', select: channelOptions(settings().log_channel), full: true })}</div>`,
    read: a => { const c = $('wzLogChannel').value; if (c) { a.settings.log_channel = c; a.modules.push('logs'); } } },
  { id: 'staff', title: 'Rôle staff', body: () => `<p>Les membres de ce rôle peuvent utiliser les commandes de modération.</p><div class="fields">${field('Rôle modérateur', '', settings().mod_role, { id: 'wzModRole', select: roleOptions(settings().mod_role), full: true })}</div>`,
    read: a => { const r = $('wzModRole').value; if (r) a.settings.mod_role = r; } },
  { id: 'security', title: 'Sécurité', body: () => `<p>Protections recommandées. Vous pourrez affiner chaque règle plus tard.</p>${['antispam', 'antilink', 'antiinsult'].map(k => { const [, l, c] = AUTOMOD.find(x => x[0] === k); return `<label class="switch-row"><span class="switch-copy"><b>${esc(l)}</b><span>${esc(c)}</span></span><input class="switch" type="checkbox" data-wz-automod="${k}" checked></label>`; }).join('')}`,
    read: a => { document.querySelectorAll('[data-wz-automod]').forEach(el => { a.automod[el.dataset.wzAutomod] = el.checked; }); } },
  { id: 'tickets', title: 'Tickets', body: () => `<p>Les tickets s’ouvrent dans une catégorie dédiée.</p><div class="fields">${field('Catégorie des tickets', '', settings().ticket_category, { id: 'wzTicketCategory', select: channelOptions(settings().ticket_category, 'category', 'Aucune catégorie') })}${field('Salon des logs tickets', '', settings().ticket_log_channel, { id: 'wzTicketLog', select: channelOptions(settings().ticket_log_channel) })}</div>`,
    read: a => { const c = $('wzTicketCategory').value, l = $('wzTicketLog').value; if (c) { a.settings.ticket_category = c; a.modules.push('tickets'); } if (l) a.settings.ticket_log_channel = l; } },
];
async function openWizard() {
  const answers = { settings: {}, automod: {}, modules: [] };
  let i = 0;
  const show = () => {
    const step = WIZARD_STEPS[i], last = i === WIZARD_STEPS.length - 1;
    openModal({
      title: `${i + 1}/${WIZARD_STEPS.length} · ${step.title}`,
      body: step.body(),
      actions: [
        ...(i > 0 ? [{ label: 'Retour', keep: true, onClick: () => { i -= 1; show(); } }] : []),
        { label: 'Passer', keep: true, onClick: () => { if (last) return finish(); i += 1; show(); } },
        { label: last ? 'Terminer' : 'Continuer', kind: 'primary', keep: true, onClick: () => { step.read(answers); if (last) return finish(); i += 1; show(); } },
      ],
    });
  };
  const finish = async () => {
    closeModal();
    const changes = Object.keys(answers.settings).length + Object.keys(answers.automod).length;
    if (!changes) { toast('Aucune modification envoyée.'); return; }
    const ok = await confirmDialog({ title: 'Appliquer cette configuration ?', body: `${plural(changes, 'réglage')} seront enregistrés et ${answers.modules.length ? plural(answers.modules.length, 'module activé', 'modules activés') : 'aucun module activé'}.`, confirm: 'Appliquer' });
    if (!ok) return;
    try {
      await api(guildUrl('/settings'), { method: 'PUT', body: JSON.stringify({ settings: answers.settings, automod: answers.automod, ai: {} }) });
      for (const m of new Set(answers.modules)) { try { await gpost('/modules', { module: m, action: 'enable' }); } catch (_) {} }
      toast('Configuration appliquée.');
      await reloadGuild();
      await render();
    } catch (e) { toast(e.message, true); }
  };
  show();
}
