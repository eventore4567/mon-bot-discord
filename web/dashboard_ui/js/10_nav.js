/* ---------- navigation ----------
   NAV : groupes visibles. Chaque page a un titre, un sous-titre court et, si besoin,
   des sous-sections. « Plus d'outils » regroupe ce qui sert rarement. */
const NAV = [
  ['Accueil', [['overview', 'Vue d’ensemble']]],
  ['Communauté', [['welcome', 'Accueil & Départs'], ['levels', 'Niveaux'], ['economy', 'Économie'], ['roles', 'Rôles']]],
  ['Modération', [['security', 'Sécurité'], ['logs', 'Logs']]],
  ['Support', [['tickets', 'Tickets']]],
  ['Automatisation', [['notifications', 'Notifications'], ['automation', 'Automatisation']]],
];
const TOOLS = [
  ['settings', 'Paramètres'], ['access', 'Commandes & accès'], ['embeds', 'Envoyer un embed'], ['ai', 'Intelligence artificielle'],
  ['invites', 'Invitations & webhooks'], ['backups', 'Sauvegardes & historique'], ['dm', 'Message privé'], ['advanced', 'Centre avancé'], ['diagnostic', 'Diagnostic'],
];
/* Anciennes interfaces encore servies : reliées discrètement tant que leurs fonctions
   n'ont pas toutes été reprises ici (voir lot 7). */
const EXTERNAL_TOOLS = [['/setup-center', 'Centre Setup (ancien)'], ['/operations', 'Opérations (ancien)'], ['/feature-suite', 'Fonctions avancées (ancien)'], ['/enterprise', 'Enterprise (ancien)']];

const META = {
  overview: ['Configuration du serveur', 'Gérez les principales fonctionnalités de SentriX.'],
  welcome: ['Accueil & Départs', 'Messages envoyés quand un membre arrive ou quitte le serveur.'],
  levels: ['Niveaux', 'XP gagné en discutant, annonces et récompenses.'],
  economy: ['Économie', 'Monnaie du serveur, gains et boutique.'],
  roles: ['Rôles', 'Rôles donnés automatiquement ou choisis par les membres.'],
  security: ['Sécurité', 'Protections automatiques, vérification et sanctions.'],
  logs: ['Logs', 'Ce qui se passe sur le serveur, écrit dans vos salons.'],
  tickets: ['Tickets', 'Support des membres : panneaux, types et suivi.'],
  notifications: ['Notifications', 'Annonce les nouvelles vidéos et lives dans un salon.'],
  automation: ['Automatisation', 'Réactions automatiques et autres règles.'],
  settings: ['Paramètres', 'Préfixe, salons système et maintenance.'],
  access: ['Commandes & accès', 'Commandes désactivées, gestionnaires et accès au dashboard.'],
  embeds: ['Envoyer un embed', 'Composez un message et envoyez-le dans un salon.'],
  ai: ['Intelligence artificielle', 'Assistant SentriX sur ce serveur.'],
  invites: ['Invitations & webhooks', 'Inventaire en lecture seule.'],
  backups: ['Sauvegardes & historique', 'Exportez, importez ou restaurez une configuration.'],
  dm: ['Message privé', 'Envoyer un message à un membre au nom du serveur.'],
  advanced: ['Centre avancé', 'Membres, automations, templates, audit et accès délégué.'],
  diagnostic: ['Diagnostic', 'Permissions, ressources cassées et état technique.'],
};
const SUBS = {
  welcome: [['bienvenue', 'Bienvenue'], ['departs', 'Départs']],
  security: [['protections', 'Protections'], ['verification', 'Vérification'], ['sanctions', 'Sanctions']],
  advanced: [['actions', 'Actions'], ['members', 'Membres'], ['automations', 'Automations'], ['templates', 'Templates'], ['audit', 'Audit'], ['access', 'Accès dashboard']],
  invites: [['invites', 'Invitations'], ['webhooks', 'Webhooks']],
  backups: [['backups', 'Sauvegardes'], ['history', 'Historique']],
};
/* Anciennes adresses ?tab= : conservées pour les liens déjà partagés. */
const LEGACY = { moderation: ['security', 'sanctions'], verification: ['security', 'verification'], config: ['settings'], product: ['advanced'], autoreact: ['automation'], audit: ['backups', 'history'], maintenance: ['settings'], stats: ['diagnostic'], staffactivity: ['diagnostic'], integrations: ['invites', 'webhooks'], automations: ['automation'] };

function pageMeta(page) { return META[page] || META.overview; }
function moduleDot(key) {
  const d = state.cache.get(`${state.guildId}:diagnostics`)?.value;
  const m = d?.modules?.[key]; if (!m) return '';
  return `<span class="state-dot ${m.code === 'active' ? 'on' : m.code === 'error' ? 'err' : ''}" aria-hidden="true"></span>`;
}
const NAV_MODULE = { welcome: 'welcome', levels: 'levels', economy: 'economy', roles: 'roles', security: 'automod', logs: 'logs', tickets: 'tickets', notifications: 'notifications' };
function navButton(page, label) {
  return `<button type="button" data-tab="${page}" class="${state.page === page ? 'active' : ''}" ${state.page === page ? 'aria-current="page"' : ''}>${esc(label)}${NAV_MODULE[page] ? moduleDot(NAV_MODULE[page]) : ''}</button>`;
}
function renderNav() {
  const nav = $('navigation');
  const inTools = TOOLS.some(([p]) => p === state.page);
  let html = NAV.map(([group, items]) => `<div class="nav-group">${esc(group)}</div>` + items.map(([p, l]) => navButton(p, l)).join('')).join('');
  const tools = TOOLS.filter(([p]) => p !== 'diagnostic' || state.developer || state.guildOwner);
  html += `<details id="navMore" ${inTools || state.navMore ? 'open' : ''}><summary>Plus d’outils</summary>${tools.map(([p, l]) => navButton(p, l)).join('')}${EXTERNAL_TOOLS.map(([href, l]) => `<a class="nav-link ext" href="${href}" target="_blank" rel="noopener">${esc(l)}</a>`).join('')}</details>`;
  nav.innerHTML = html;
  nav.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => go(b.dataset.tab));
  const more = $('navMore');
  more.querySelector('summary').addEventListener('click', () => setTimeout(() => { state.navMore = more.open; try { localStorage.setItem('sentrix:nav:more', more.open ? '1' : '0'); } catch (_) {} }, 0));
}
function renderSubnav() {
  const subs = SUBS[state.page];
  const el = $('subnav');
  if (!subs) { el.classList.add('hidden'); el.innerHTML = ''; return; }
  if (!subs.some(([k]) => k === state.sub)) state.sub = subs[0][0];
  el.innerHTML = subs.map(([k, l]) => `<button type="button" data-sub="${k}" class="${state.sub === k ? 'active' : ''}">${esc(l)}</button>`).join('');
  el.classList.remove('hidden');
  el.querySelectorAll('[data-sub]').forEach(b => b.onclick = () => go(state.page, b.dataset.sub));
}
function setHead() {
  const [title, sub] = pageMeta(state.page);
  $('pageTitle').textContent = title;
  $('pageSubtitle').textContent = sub;
  document.title = `${title} · SentriX`;
}
function syncUrl() {
  try {
    const q = new URLSearchParams();
    q.set('tab', state.page);
    if (state.sub) q.set('sub', state.sub);
    if (state.guildId) q.set('guild', state.guildId);
    history.replaceState({}, '', `/app?${q}`);
  } catch (_) {}
}
async function go(page, sub = '') {
  if (LEGACY[page]) { const target = LEGACY[page]; page = target[0]; sub = target[1] || sub; }
  if (!META[page]) page = 'overview';
  if (page === state.page && (sub || '') === (state.sub || '') && content().children.length) return;
  if (!(await guardDirty())) return;
  state.page = page;
  state.sub = sub || (SUBS[page] ? SUBS[page][0][0] : '');
  try { localStorage.setItem('sentrix:page', page); } catch (_) {}
  closeSidebar();
  await render();
}
function openSidebar() { $('sidebar').classList.add('open'); $('mobileOverlay').classList.remove('hidden'); $('mobileMenu').setAttribute('aria-expanded', 'true'); }
function closeSidebar() { $('sidebar').classList.remove('open'); $('mobileOverlay').classList.add('hidden'); $('mobileMenu').setAttribute('aria-expanded', 'false'); }

/* ---------- palette ⌘K ---------- */
function paletteItems(q = '') {
  const n = q.toLocaleLowerCase('fr').trim();
  const items = [];
  for (const [group, pages] of NAV) for (const [p, l] of pages) items.push({ page: p, label: l, group });
  for (const [p, l] of TOOLS) items.push({ page: p, label: l, group: 'Plus d’outils' });
  for (const [p, subs] of Object.entries(SUBS)) for (const [k, l] of subs) items.push({ page: p, sub: k, label: `${pageMeta(p)[0]} › ${l}`, group: pageMeta(p)[0] });
  return items.filter(x => !n || `${x.label} ${x.group}`.toLocaleLowerCase('fr').includes(n));
}
function drawPalette() {
  const items = paletteItems($('paletteInput').value);
  $('paletteResults').innerHTML = items.length ? items.map((x, i) => `<button class="palette-item ${i === 0 ? 'active' : ''}" type="button" data-palette-page="${x.page}" data-palette-sub="${x.sub || ''}"><span>${esc(x.label)}</span><small>${esc(x.group)}</small></button>`).join('') : '<div class="empty">Aucun résultat.</div>';
  $('paletteResults').querySelectorAll('[data-palette-page]').forEach(b => b.onclick = () => { closePalette(); go(b.dataset.palettePage, b.dataset.paletteSub); });
}
function openPalette() { $('paletteBackdrop').classList.remove('hidden'); $('paletteInput').value = ''; drawPalette(); setTimeout(() => $('paletteInput').focus(), 0); }
function closePalette() { $('paletteBackdrop').classList.add('hidden'); }
$('globalSearch').onclick = openPalette;
$('paletteInput').oninput = drawPalette;
$('paletteInput').onkeydown = e => { if (e.key === 'Enter') { const first = $('paletteResults').querySelector('.palette-item'); if (first) first.click(); } };
$('paletteBackdrop').onclick = e => { if (e.target === $('paletteBackdrop')) closePalette(); };
