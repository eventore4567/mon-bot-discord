/* ---------- rendu ---------- */
const PAGES = {
  profile: renderProfile, servers: renderServers, preferences: renderPreferences,
  overview: renderOverview, welcome: renderWelcome, levels: renderLevels, economy: renderEconomy, games: renderGames, music: renderMusic, roles: renderRoles,
  moderation: renderSanctions, security: renderSecurity, logs: renderLogs, tickets: renderTickets, notifications: renderNotifications, automation: renderAutomation,
  settings: renderSettings, access: renderAccess, embeds: renderEmbeds, ai: renderAI, invites: renderInvites, backups: renderBackups,
  dm: renderDM, advanced: renderAdvanced, diagnostic: renderDiagnostic,
};
const GLOBAL_PAGES = new Set(['profile', 'servers', 'preferences']);
let renderToken = 0;
const REDUCED_MOTION = () => Boolean(state.reduceMotion) || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
const SKELETON = '<div class="grid" aria-hidden="true"><div class="skeleton full" style="min-height:72px"></div><div class="skeleton" style="min-height:180px"></div><div class="skeleton" style="min-height:180px"></div></div>';
/* render({navigation:true}) = vraie navigation utilisateur (go) : légère sortie, squelette si
   la page met plus de 150 ms, puis entrée (160 ms). Tout autre appel (enregistrement,
   Actualiser, tick live) redessine sans transition et garde le contenu visible. */
async function render({ navigation = false } = {}) {
  if (!state.guild && !GLOBAL_PAGES.has(state.page)) {
    state.page = 'servers';
    state.sub = '';
  }
  const token = ++renderToken;
  setHead(); renderNav(); renderSubnav(); syncUrl();
  const el = content();
  const animate = navigation && !REDUCED_MOTION();
  el.classList.remove('page-enter');
  if (animate && el.children.length) el.classList.add('page-leave');
  let painted = false;
  const skeleton = navigation ? setTimeout(() => { if (!painted && token === renderToken) { el.classList.remove('page-leave'); el.innerHTML = SKELETON; } }, 150) : null;
  el.setAttribute('aria-busy', 'true');
  try {
    await (PAGES[state.page] || renderOverview)();
    if (typeof enhanceSentrixExperience === 'function') await enhanceSentrixExperience();
    painted = true; clearTimeout(skeleton);
    if (token !== renderToken) return;
    el.querySelectorAll('[data-go]').forEach(b => { if (!b.onclick) b.onclick = () => go(b.dataset.go, b.dataset.goSub || ''); });
    el.classList.remove('page-leave');
    if (animate) { el.classList.add('page-enter'); const clear = () => el.classList.remove('page-enter'); el.addEventListener('animationend', clear, { once: true }); setTimeout(clear, 260); }
  } catch (e) {
    painted = true; clearTimeout(skeleton);
    if (token === renderToken) { el.classList.remove('page-leave'); errorView(e); }
  } finally {
    if (token === renderToken) el.setAttribute('aria-busy', 'false');
  }
}

/* ---------- serveurs ---------- */
function renderServerRail() {
  const installed = state.guilds.filter(g => g.installed), missing = state.guilds.filter(g => !g.installed);
  const user = state.user || {};
  const avatar = user.avatar_url
    ? `<img src="${esc(user.avatar_url)}" alt="">`
    : esc(String(user.global_name || user.username || 'ME').slice(0, 2).toUpperCase());
  $('serverRail').innerHTML =
    `<button class="guild-btn account ${state.guildId ? '' : 'active'}" type="button" id="globalHomeRail" title="Mon espace SentriX" aria-label="Mon espace SentriX">${avatar}</button>
     <span class="rail-separator" aria-hidden="true"></span>` +
    installed.map(g => `<button class="guild-btn ${String(g.id) === String(state.guildId) ? 'active' : ''}" type="button" data-guild="${esc(g.id)}" title="${esc(g.name)}" aria-label="${esc(g.name)}">${g.icon_url ? `<img src="${esc(g.icon_url)}" alt="">` : esc((g.name || 'S').slice(0, 2).toUpperCase())}</button>`).join('') +
    (missing[0] ? `<a class="guild-btn add" href="${esc(missing[0].invite_url || '#')}" title="Ajouter SentriX à un autre serveur">+</a>` : '');
  $('globalHomeRail').onclick = () => exitGuildToGlobal('profile');
  $('serverRail').querySelectorAll('[data-guild]').forEach(b => b.onclick = () => selectGuild(b.dataset.guild));
}
function openServerPicker() {
  const installed = state.guilds.filter(g => g.installed), missing = state.guilds.filter(g => !g.installed);
  openModal({
    title: 'Choisir un serveur',
    body: `<input class="input" id="pickSearch" type="search" placeholder="Rechercher un serveur…" autocomplete="off"><div class="options" id="pickOptions"></div>`,
    actions: [{ label: 'Fermer' }],
    onOpen: () => {
      const paint = q => {
        const n = String(q || '').toLocaleLowerCase('fr');
        const rows = g => g.filter(x => !n || x.name.toLocaleLowerCase('fr').includes(n));
        const item = (g, add) => `<${add ? 'a' : 'button'} ${add ? `href="${esc(g.invite_url || '#')}"` : `type="button" data-pick-guild="${esc(g.id)}"`}><span class="server-icon">${g.icon_url ? `<img src="${esc(g.icon_url)}" alt="">` : esc((g.name || 'S').slice(0, 2).toUpperCase())}</span><span class="row-main"><b>${esc(g.name)}</b><small>${add ? 'SentriX n’est pas encore sur ce serveur — inviter' : (String(g.id) === String(state.guildId) ? 'Serveur actuel' : 'Configurer')}</small></span></${add ? 'a' : 'button'}>`;
        $('pickOptions').innerHTML = `<div class="nav-group">Vos serveurs avec SentriX</div>${rows(installed).map(g => item(g)).join('') || '<div class="empty">Aucun serveur.</div>'}${rows(missing).length ? `<div class="nav-group">Ajouter SentriX</div>${rows(missing).map(g => item(g, true)).join('')}` : ''}`;
        $('pickOptions').querySelectorAll('[data-pick-guild]').forEach(b => b.onclick = () => { closeModal(); selectGuild(b.dataset.pickGuild); });
      };
      paint(''); $('pickSearch').oninput = () => paint($('pickSearch').value);
    },
  });
}
async function exitGuildToGlobal(page = 'profile') {
  if (!(await guardDirty())) return;
  if (state.guildAbort) state.guildAbort.abort();
  state.guildAbort = null;
  stopLive();
  state.guildId = '';
  state.guild = null;
  state.guildOwner = false;
  state.cache.clear();
  state.ticketCreate = false;
  state.page = GLOBAL_PAGES.has(page) ? page : 'profile';
  state.sub = '';
  updateChrome();
  renderServerRail();
  closeSidebar();
  await render({ navigation: true });
}

async function selectGuild(value) {
  const preservePage = Boolean(state.preserveGuildPage);
  state.preserveGuildPage = false;
  if (!value || String(value) === String(state.guildId) && state.guild) return;
  if (!(await guardDirty())) return;
  if (!preservePage || GLOBAL_PAGES.has(state.page)) {
    state.page = 'overview';
    state.sub = '';
  }
  if (state.guildAbort) state.guildAbort.abort();
  const controller = new AbortController();
  state.guildAbort = controller;
  const requested = String(value);
  state.guildId = requested; state.guild = null; state.cache.clear(); state.ticketCreate = false;
  const meta = state.guilds.find(g => String(g.id) === requested) || {};
  state.guildOwner = Boolean(meta.owner);
  renderServerRail();
  if (!content().children.length) content().innerHTML = '<div class="skeleton" aria-hidden="true"></div>';
  try {
    const data = await api(guildUrl(''), { signal: controller.signal });
    if (controller !== state.guildAbort || requested !== state.guildId) return;
    state.guild = data;
    try { localStorage.setItem('sentrix:guild', requested); } catch (_) {}
    updateChrome(); renderServerRail();
    await render({ navigation: true });
    startLive();
  } catch (e) {
    if (e?.name === 'AbortError' || controller !== state.guildAbort) return;
    if (e.status === 503) errorView({ message: 'Reconnexion Discord en cours. Réessayez dans quelques secondes.' }, () => selectGuild(requested));
    else if (e.status === 401) errorView({ message: 'Votre session Discord a expiré. Reconnectez-vous.' }, () => location.reload());
    else errorView(e, () => selectGuild(requested));
  } finally { if (controller === state.guildAbort) state.guildAbort = null; }
}
function isHardReloadNavigation() {
  try {
    const entry = performance?.getEntriesByType?.('navigation')?.[0];
    if (entry?.type) return entry.type === 'reload';
    // Compatibilité anciens navigateurs.
    return Number(performance?.navigation?.type) === 1;
  } catch (_) {
    return false;
  }
}

async function loadGuilds() {
  const payload = await api('/api/guilds');
  state.guilds = payload.guilds || [];
  showOnly('dashboard');
  const installed = state.guilds.filter(g => g.installed);
  const hardReload = isHardReloadNavigation();
  const wanted = hardReload ? '' : (new URLSearchParams(location.search).get('guild') || '');
  renderServerRail();

  // Un lien direct vers une guild reste possible, mais F5 / ⌘R ramène toujours
  // à Mon profil. On évite ainsi qu'un rechargement restaure un serveur actif.
  if (wanted && installed.some(g => String(g.id) === String(wanted))) {
    state.preserveGuildPage = true;
    await selectGuild(wanted);
    return;
  }

  state.guildId = '';
  state.guild = null;
  state.guildOwner = false;
  state.page = 'profile';
  state.sub = '';
  state.ticketEditorOpen = false;
  state.ticketCreate = false;
  updateChrome();
  renderServerRail();
  await render({ navigation: true });
}

/* ---------- session & états de démarrage ----------
   booting → auth_required | error | loading_guilds → ready.
   Aucun état intermédiaire ne laisse la page vide : soit le dashboard, soit la page de
   connexion, soit un panneau d'erreur avec « Réessayer » / « Se reconnecter ». */
const boot = { state: 'booting', watchdog: null };
const startupStartedAt = performance.now();
let startupFinished = false;
let startupPercent = 4;
let startupTarget = 4;
let startupFrame = null;
let startupLastFrame = 0;
let startupDrip = null;

function paintStartupProgress(value) {
  startupPercent = Math.max(0, Math.min(100, Number(value) || 0));
  const bar = $('startupProgressBar');
  const wrap = $('startupProgress');
  if (bar) bar.style.width = `${startupPercent.toFixed(2)}%`;
  if (wrap) wrap.setAttribute('aria-valuenow', String(Math.round(startupPercent)));
}

function startupProgressFrame(now) {
  if (!startupLastFrame) startupLastFrame = now;
  const dt = Math.min(48, Math.max(0, now - startupLastFrame));
  startupLastFrame = now;
  const remaining = startupTarget - startupPercent;

  if (remaining > 0.015) {
    // Vitesse volontairement régulière : environ 2,4 s pour parcourir toute la barre.
    // Les jalons réseau déplacent seulement la cible ; la barre n'effectue jamais de saut.
    const maxStep = (dt / 1000) * (startupTarget >= 100 ? 46 : 39);
    const easedStep = Math.max(0.035, Math.min(maxStep, remaining * 0.16));
    paintStartupProgress(Math.min(startupTarget, startupPercent + easedStep));
  } else if (startupPercent !== startupTarget) {
    paintStartupProgress(startupTarget);
  }

  if (!startupFinished || startupPercent < 99.98) {
    startupFrame = requestAnimationFrame(startupProgressFrame);
  } else {
    startupFrame = null;
  }
}

function ensureStartupProgressFrame() {
  if (startupFrame == null) {
    startupLastFrame = 0;
    startupFrame = requestAnimationFrame(startupProgressFrame);
  }
}

function setStartupProgress(value) {
  if (startupFinished && Number(value) < 100) return;
  startupTarget = Math.max(startupTarget, Math.min(100, Number(value) || 0));
  ensureStartupProgressFrame();
}

function startStartupProgress() {
  paintStartupProgress(4);
  startupTarget = 4;
  ensureStartupProgressFrame();
  clearInterval(startupDrip);
  startupDrip = setInterval(() => {
    if (startupFinished || startupTarget >= 90) return;
    const step = startupTarget < 35 ? 1.1 : startupTarget < 70 ? 0.75 : 0.38;
    setStartupProgress(Math.min(90, startupTarget + step));
  }, 180);
}

function finishStartupScreen({ immediate = false } = {}) {
  if (startupFinished) return;
  startupFinished = true;
  clearInterval(startupDrip);

  if (immediate) {
    startupTarget = 100;
    paintStartupProgress(100);
  } else {
    setStartupProgress(100);
  }

  const finishWhenSmooth = () => {
    const elapsed = performance.now() - startupStartedAt;
    const visuallyComplete = startupPercent >= 99.7;
    const minimumShown = elapsed >= 2200;
    if (!immediate && (!visuallyComplete || !minimumShown)) {
      setTimeout(finishWhenSmooth, 45);
      return;
    }
    document.body.classList.remove('startup-loading');
    document.body.classList.add('startup-done');
    setTimeout(() => $('startupScreen')?.remove(), 450);
  };
  finishWhenSmooth();
}
function showOnly(id) {
  for (const k of ['landing', 'bootState', 'dashboard']) $(k).classList.toggle('hidden', k !== id);
  document.body.classList.toggle('dashboard-locked', id === 'dashboard');
  if (id === 'dashboard') finishStartupScreen();
  else if (id === 'landing' || id === 'bootState') finishStartupScreen({ immediate: true });
}
function setBootState(state, { title, message, ref, retry = true, reconnect = false } = {}) {
  boot.state = state;
  if (state === 'ready') { clearTimeout(boot.watchdog); showOnly('dashboard'); return; }
  if (state === 'auth_required') { clearTimeout(boot.watchdog); showOnly('landing'); loadPublic(); return; }
  if (state === 'error') {
    clearTimeout(boot.watchdog);
    $('bootTitle').textContent = title || 'Une erreur empêche le dashboard de charger.';
    $('bootMessage').textContent = message || '';
    $('bootRef').textContent = ref ? `Référence : ${ref}` : '';
    $('bootRetry').classList.toggle('hidden', !retry);
    $('bootLogin').classList.toggle('hidden', !reconnect);
    showOnly('bootState');
  }
}
function bootError(e, context) {
  const status = Number(e?.status || 0);
  if (status === 401) return setBootState('auth_required');
  if (status === 503) return setBootState('error', { title: 'SentriX se reconnecte à Discord.', message: 'Le dashboard sera de nouveau disponible dans quelques secondes.', ref: `SXD-${context}-503` });
  setBootState('error', {
    title: context === 'GUILDS' ? 'Impossible de charger vos serveurs.' : 'Impossible de charger votre session.',
    message: e?.message || 'Erreur inconnue.',
    ref: `SXD-${context}-${status || 'JS'}`,
    reconnect: true,
  });
}
async function loadPublic() {
  try {
    const p = await api('/api/public');
    $('publicGuilds').textContent = number(p.guilds); $('publicMembers').textContent = number(p.members);
    $('publicLatency').textContent = p.latency_ms == null ? '—' : `${p.latency_ms} ms`; $('publicUptime').textContent = age(p.uptime_seconds);
    $('publicBadge').textContent = p.online ? 'En ligne' : 'Connexion'; $('publicBadge').className = `badge ${p.online ? 'ok' : 'warn'}`;
    setRuntime(Boolean(p.online), p.latency_ms);
  } catch (_) { $('publicBadge').textContent = 'Indisponible'; $('publicBadge').className = 'badge bad'; }
}
function showLanding() { setBootState('auth_required'); }
async function loadSession() {
  setStartupProgress(18);
  let me;
  try { me = await api('/api/me'); }
  catch (e) {
    if (e.status === 401 && location.pathname.startsWith('/app')) { const n = $('authMessage'); n.textContent = 'Connectez-vous avec Discord pour ouvrir le dashboard.'; n.classList.remove('hidden'); }
    bootError(e, 'AUTH');
    return false;
  }
  setStartupProgress(43);
  state.user = me.user; state.csrf = me.csrf; state.developer = Boolean(me.developer);
  $('profileButton').classList.remove('hidden');
  $('userName').textContent = me.user?.username || 'Compte';
  if (me.user?.avatar_url) $('userAvatar').innerHTML = `<img src="${esc(me.user.avatar_url)}" alt="">`;
  renderNav();
  boot.state = 'loading_guilds';
  setStartupProgress(62);
  try { await loadGuilds(); }
  catch (e) { bootError(e, 'GUILDS'); return false; }
  setStartupProgress(92);
  setBootState('ready');
  return true;
}

/* ---------- métriques live : texte seul, jamais de re-rendu ---------- */
let liveAt = 0;
async function liveTick(force = false) {
  if (!state.guildId || (!force && document.hidden)) return;
  liveAt = Date.now();
  try { const m = await api(guildUrl('/live/metrics'), { background: true }); setRuntime(Boolean(m.online), m.latency_ms); }
  catch (e) { if (e.status === 401) stopLive(); }
}
function startLive() {
  stopLive();
  state.live = setInterval(() => liveTick(false), 30000);
  liveTick(true);
}
function stopLive() { if (state.live) clearInterval(state.live); state.live = null; }
document.addEventListener('visibilitychange', () => { if (!document.hidden && state.live && Date.now() - liveAt > 30000) liveTick(true); });

/* ---------- événements globaux ---------- */
$('mobileMenu').onclick = () => ($('sidebar').classList.contains('open') ? closeSidebar() : openSidebar());
$('mobileOverlay').onclick = closeSidebar;
$('serverSwitch').onclick = openServerPicker;
$('refreshButton').onclick = async () => {
    if (!(await guardDirty())) return;
    state.cache.clear();
    if (!state.guildId) {
      try {
        const payload = await api('/api/guilds');
        state.guilds = payload.guilds || [];
        renderServerRail();
        await render();
        toast('Espace actualisé.');
      } catch (e) { toast(e.message, true); }
      return;
    }
    await reloadGuild();
    await render();
    toast('Données actualisées.');
  };
$('saveButton').onclick = saveDirty;
$('discardButton').onclick = () => { clearDirty(); render(); };
$('profileButton').onclick = () => exitGuildToGlobal('profile');
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveDirty(); }
  if (e.key === 'Escape') { closePalette(); closeModal(); closeSidebar(); }
});
/* ---------- responsive universel : synchronisation menu ---------- */
const responsiveNavMq = typeof window.matchMedia === 'function' ? window.matchMedia('(max-width: 1024px)') : null;
function syncResponsiveNav() {
  if (responsiveNavMq && !responsiveNavMq.matches) closeSidebar();
}
if (responsiveNavMq) {
  if (typeof responsiveNavMq.addEventListener === 'function') responsiveNavMq.addEventListener('change', syncResponsiveNav);
  else if (typeof responsiveNavMq.addListener === 'function') responsiveNavMq.addListener(syncResponsiveNav);
}
window.addEventListener('orientationchange', () => setTimeout(syncResponsiveNav, 120));

window.addEventListener('beforeunload', e => { if (hasDirty()) { e.preventDefault(); e.returnValue = ''; } });
window.addEventListener('offline', () => $('netNotice').classList.remove('hidden'));
window.addEventListener('online', () => $('netNotice').classList.add('hidden'));
window.addEventListener('popstate', () => { const q = new URLSearchParams(location.search); const p = q.get('tab'); if (p && p !== state.page) go(p, q.get('sub') || ''); });

async function bootstrap() {
  startStartupProgress();
  setStartupProgress(8);
  const q = new URLSearchParams(location.search);
  let page = q.get('tab') || '';
  if (!page) { try { page = localStorage.getItem('sentrix:page') || ''; } catch (_) {} }
  if (LEGACY[page]) { state.sub = LEGACY[page][1] || ''; page = LEGACY[page][0]; }
  state.page = META[page] ? page : 'profile';
  if (q.get('sub')) state.sub = q.get('sub');
  try { state.navMore = localStorage.getItem('sentrix:nav:more') === '1'; } catch (_) {}
  if (typeof applyGlobalPreferences === 'function') applyGlobalPreferences();
  if (q.get('auth') === 'missing') { const n = $('authMessage'); n.textContent = 'Connexion Discord indisponible pour le moment. Réessayez dans quelques instants ou contactez le support.'; n.classList.remove('hidden'); history.replaceState(null, '', location.pathname); }
  renderNav();
  // Filet : si rien n'a abouti après 20 s (réseau muet, exception avalée), on le dit.
  boot.watchdog = setTimeout(() => { if (boot.state === 'booting' || boot.state === 'loading_guilds') setBootState('error', { title: 'Le dashboard met trop de temps à charger.', message: 'Le serveur ne répond pas. Réessayez, ou reconnectez-vous si le problème persiste.', ref: 'SXD-BOOT-TIMEOUT', reconnect: true }); }, 20000);
  await loadSession();
}
$('bootRetry').onclick = () => { boot.state = 'booting'; showOnly('bootState'); $('bootTitle').textContent = 'Nouvelle tentative…'; $('bootMessage').textContent = ''; $('bootRef').textContent = ''; loadSession(); };
window.addEventListener('error', e => { if (boot.state !== 'ready') setBootState('error', { title: 'Une erreur empêche le dashboard de charger.', message: String(e?.message || 'Erreur JavaScript.'), ref: 'SXD-BOOT-JS', reconnect: true }); });
window.addEventListener('unhandledrejection', e => { if (boot.state !== 'ready') setBootState('error', { title: 'Une erreur empêche le dashboard de charger.', message: String(e?.reason?.message || e?.reason || 'Erreur inattendue.'), ref: 'SXD-BOOT-PROMISE', reconnect: true }); });
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bootstrap, { once: true });
else bootstrap();
