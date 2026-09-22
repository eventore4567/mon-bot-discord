/* ---------- navigation ----------
   NAV : groupes visibles. Chaque page a un titre, un sous-titre court et, si besoin,
   des sous-sections. « Plus d'outils » regroupe ce qui sert rarement. */
const NAV_GLOBAL = [
  ['Mon espace', [['profile', 'Mon profil'], ['servers', 'Mes serveurs'], ['preferences', 'Préférences']]],
];
const NAV_SERVER = [
  ['Accueil', [['overview', 'Vue d’ensemble']]],
  ['Communauté', [['welcome', 'Accueil & Départs'], ['roles', 'Rôles']]],
  ['Progression', [['levels', 'Niveaux'], ['economy', 'Économie']]],
  ['Modération', [['moderation', 'Centre de modération'], ['security', 'Sécurité'], ['logs', 'Logs'], ['tickets', 'Tickets']]],
  ['Jeux', [['games', 'Jeux']]],
  ['Musique', [['music', 'Musique']]],
  ['Automatisation', [['notifications', 'Notifications'], ['automation', 'Automatisation']]],
  ['Création & personnalisation', [['embeds', 'Embeds'], ['ai', 'Intelligence artificielle']]],
];
const NAV = NAV_SERVER;
/* Plus d'outils : trois groupes courts. Le groupe Développeur n'apparaît que pour le
   propriétaire du bot (/api/me.developer) ; il porte aussi, le temps de la migration, les
   anciennes interfaces dont toutes les fonctions ne sont pas encore reprises ici. */
const TOOL_GROUPS = [
  ['Outils', [['invites', 'Invitations & webhooks']]],
  ['Administration', [['settings', 'Paramètres'], ['backups', 'Sauvegardes & historique'], ['diagnostic', 'Diagnostic']]],
  ['Développeur', [['advanced', 'Centre avancé']]],
];
const TOOLS = TOOL_GROUPS.flatMap(([, items]) => items);
const MIGRATION_LINKS = [['/setup-center', 'Centre Setup'], ['/operations', 'Opérations'], ['/feature-suite', 'Fonctions avancées'], ['/enterprise', 'Enterprise']];

const META = {
  profile: ['Mon profil', 'Votre espace SentriX personnel. Choisissez ensuite un serveur à configurer.'],
  servers: ['Mes serveurs', 'Choisissez le serveur que vous voulez administrer avec SentriX.'],
  preferences: ['Préférences', 'Réglez uniquement l’apparence et le comportement de votre dashboard.'],
  overview: ['Vue d’ensemble', 'Gérez les principales fonctionnalités de ce serveur.'],
  welcome: ['Accueil & Départs', 'Messages envoyés quand un membre arrive ou quitte le serveur.'],
  levels: ['Niveaux', 'XP gagné en discutant, annonces et récompenses.'],
  economy: ['Économie', 'Monnaie du serveur, gains et boutique.'],
  games: ['Jeux', 'Mini-jeux, récompenses et accès.'],
  music: ['Musique', 'Lecteur vocal, file d’attente et playlists SentriX.'],
  roles: ['Rôles', 'Rôles donnés automatiquement ou choisis par les membres.'],
  moderation: ['Centre de modération', 'Recherchez un membre, consultez son dossier et gérez les sanctions.'],
  security: ['Sécurité', 'Protections automatiques et vérification du serveur.'],
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
  levels: [['general', 'Général'], ['levelup', 'Message de niveau'], ['roles', 'Récompenses'], ['avance', 'Avancé']],
  economy: [['general', 'Général'], ['boutique', 'Boutique'], ['jeux', 'Jeux'], ['gains', 'Gains'], ['avance', 'Avancé']],
  games: [['jeux', 'Catalogue & accès']],
  music: [['player', 'Lecteur'], ['queue', 'File d’attente'], ['playlists', 'Playlists']],
  roles: [['autoroles', 'Autorôle'], ['interactifs', 'Rôles interactifs'], ['niveau', 'Rôles de niveau'], ['avance', 'Avancé']],
  tickets: [['panneaux', 'Panneaux'], ['actions', 'Actions staff']],
  security: [['protections', 'Protections'], ['verification', 'Vérification']],
  advanced: [['actions', 'Actions'], ['members', 'Membres'], ['automations', 'Automations'], ['templates', 'Templates'], ['audit', 'Audit'], ['access', 'Accès dashboard']],
  invites: [['invites', 'Invitations'], ['webhooks', 'Webhooks']],
  backups: [['backups', 'Sauvegardes'], ['history', 'Historique']],
};
/* Anciennes adresses ?tab= : conservées pour les liens déjà partagés. */
const LEGACY = { verification: ['security', 'verification'], config: ['settings'], product: ['advanced'], autoreact: ['automation'], audit: ['backups', 'history'], maintenance: ['settings'], stats: ['diagnostic'], staffactivity: ['diagnostic'], integrations: ['invites', 'webhooks'], automations: ['automation'] };

function pageMeta(page) { return META[page] || META.overview; }
function moduleDot(key) {
  const d = state.cache.get(`${state.guildId}:diagnostics`)?.value;
  const m = d?.modules?.[key]; if (!m) return '';
  const code = String(m.code || 'inactive');
  const cls = code === 'active' ? 'on' : code === 'error' ? 'err' : code === 'partial' ? 'partial' : '';
  const label = code === 'active' ? 'Activé' : code === 'error' ? 'Erreur' : code === 'partial' ? 'Partiellement configuré' : 'Désactivé';
  return `<span class="state-dot ${cls}" title="${esc(label)}" aria-label="${esc(label)}"></span>`;
}
const NAV_MODULE = { welcome: 'welcome', levels: 'levels', economy: 'economy', games: 'economy', music: 'music', roles: 'roles', security: 'automod', logs: 'logs', tickets: 'tickets', notifications: 'notifications' };
function navButton(page, label) {
  return `<button type="button" data-tab="${page}" class="${state.page === page ? 'active' : ''}" ${state.page === page ? 'aria-current="page"' : ''}>${esc(label)}</button>`;
}
function renderNav() {
  const nav = $('navigation');
  const globalMode = !state.guildId || !state.guild;
  const activeNav = globalMode ? NAV_GLOBAL : NAV_SERVER;
  let html = activeNav.map(([group, items]) => `<div class="nav-group">${esc(group)}</div>` + items.map(([p, l]) => navButton(p, l)).join('')).join('');
  if (!globalMode) {
    html += TOOL_GROUPS.map(([g, items]) => {
      if (g === 'Développeur' && !state.developer) return '';
      const visible = items.filter(([p]) => p !== 'diagnostic' || state.developer || state.guildOwner);
      const links = g === 'Développeur' ? `<div class="nav-group">Migration</div>${MIGRATION_LINKS.map(([href, l]) => `<a class="nav-link ext" href="${href}" target="_blank" rel="noopener">${esc(l)}</a>`).join('')}` : '';
      return visible.length || links ? `<div class="nav-group">${esc(g)}</div>${visible.map(([p, l]) => navButton(p, l)).join('')}${links}` : '';
    }).join('');
  }
  nav.innerHTML = html;
  nav.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => go(b.dataset.tab));
}
function renderSubnav() {
  if (!state.guildId || !state.guild) { const el = $('subnav'); el.classList.add('hidden'); el.innerHTML = ''; return; }
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
  if (!META[page]) page = state.guildId ? 'overview' : 'profile';
  const globalTarget = ['profile', 'servers', 'preferences'].includes(page);
  if (globalTarget && state.guildId) return exitGuildToGlobal(page);
  if (!globalTarget && !state.guildId) page = 'servers';
  const targetSub = sub || (SUBS[page] ? SUBS[page][0][0] : '');
  const resetTicketEditor = page === 'tickets' && targetSub === 'panneaux' && Boolean(state.ticketEditorOpen || state.ticketCreate);
  if (page === state.page && targetSub === (state.sub || '') && content().children.length && !resetTicketEditor) return;
  if (!(await guardDirty())) return;
  state.page = page;
  state.sub = targetSub;
  if (page === 'tickets' && targetSub === 'panneaux') {
    state.ticketEditorOpen = false;
    state.ticketCreate = false;
  }
  if (page !== 'tickets') state.ticketEditorOpen = false;
  if (!globalTarget) { try { localStorage.setItem('sentrix:page', page); } catch (_) {} }
  closeSidebar();
  await render({ navigation: true });
}
function openSidebar() {
  const sidebar = $('sidebar'), overlay = $('mobileOverlay'), button = $('mobileMenu');
  if (!sidebar || !overlay || !button) return;
  sidebar.classList.add('open');
  overlay.classList.remove('hidden');
  button.setAttribute('aria-expanded', 'true');
  document.body.classList.add('nav-open');
}
function closeSidebar() {
  const sidebar = $('sidebar'), overlay = $('mobileOverlay'), button = $('mobileMenu');
  if (!sidebar || !overlay || !button) return;
  sidebar.classList.remove('open');
  overlay.classList.add('hidden');
  button.setAttribute('aria-expanded', 'false');
  document.body.classList.remove('nav-open');
}

/* ---------- palette ⌘K ---------- */
const PALETTE_KEYWORDS = {
  profile: 'profil compte avatar préférences apparence thème couleur',
  servers: 'serveur guild choisir sélectionner ajouter bot',
  preferences: 'thème theme couleur accent hex apparence animation densité glow oled midnight graphite',
  overview: 'accueil dashboard santé modules configuration résumé',
  welcome: 'bienvenue départ arrivée leave join message accueil',
  levels: 'niveau xp expérience récompense role rank classement',
  economy: 'économie argent monnaie banque boutique shop daily weekly work',
  roles: 'rôle role autorole réaction reaction notification niveau',
  moderation: 'modération warn mute timeout kick ban sanction membre dossier',
  security: 'sécurité antispam anti spam antilink anti lien antiraid anti raid automod verification',
  logs: 'logs journal audit message supprimé vocal rôle modération',
  tickets: 'ticket support panneau formulaire transcript staff bouton',
  games: 'jeu jeux compteur infini infinite number guess mini-jeu',
  music: 'musique music vocal voice playlist lecture play pause skip file queue spotify youtube deezer soundcloud',
  notifications: 'notification youtube twitch tiktok kick live vidéo',
  automation: 'automation automatisation reaction auto starboard sticky programmé voicehub vocal',
  embeds: 'embed message annonce aperçu discord builder',
  ai: 'ia ai modèle mémoire intelligence artificielle',
  diagnostic: 'diagnostic santé permissions erreur debug',
  backups: 'backup sauvegarde historique restaurer export import',
  settings: 'paramètre configuration serveur préfixe',
  access: 'accès commande permission staff',
  invites: 'invitation webhook croissance',
  advanced: 'avancé automation template audit accès',
};
function paletteItems(q = '') {
  const n = q.toLocaleLowerCase('fr').trim();
  const items = [];
  const globalMode = !state.guildId || !state.guild;
  const activeNav = globalMode ? NAV_GLOBAL : NAV_SERVER;
  for (const [group, pages] of activeNav) for (const [p, l] of pages) items.push({ page: p, label: l, group, keywords: PALETTE_KEYWORDS[p] || '' });
  if (!globalMode) {
    for (const [g, pages] of TOOL_GROUPS) {
      if (g === 'Développeur' && !state.developer) continue;
      for (const [p, l] of pages) items.push({ page: p, label: l, group: g, keywords: PALETTE_KEYWORDS[p] || '' });
    }
    for (const [p, subs] of Object.entries(SUBS)) {
      for (const [k, l] of subs) items.push({
        page: p, sub: k, label: `${pageMeta(p)[0]} › ${l}`, group: pageMeta(p)[0],
        keywords: `${PALETTE_KEYWORDS[p] || ''} ${k} ${l}`,
      });
    }
  }
  return items.filter(x => !n || `${x.label} ${x.group} ${x.keywords || ''}`.toLocaleLowerCase('fr').includes(n));
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
