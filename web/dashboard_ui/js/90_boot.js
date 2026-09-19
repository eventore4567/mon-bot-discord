/* ---------- rendu ---------- */
const PAGES = {
  profile: renderProfile, overview: renderOverview, welcome: renderWelcome, levels: renderLevels, economy: renderEconomy, games: renderGames, roles: renderRoles,
  security: renderSecurity, logs: renderLogs, tickets: renderTickets, notifications: renderNotifications, automation: renderAutomation,
  settings: renderSettings, access: renderAccess, embeds: renderEmbeds, ai: renderAI, invites: renderInvites, backups: renderBackups,
  dm: renderDM, advanced: renderAdvanced, diagnostic: renderDiagnostic,
};
const GLOBAL_PAGES = new Set(['profile']);
let renderToken = 0;
const REDUCED_MOTION = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const SKELETON = '<div class="grid" aria-hidden="true"><div class="skeleton full" style="min-height:72px"></div><div class="skeleton" style="min-height:180px"></div><div class="skeleton" style="min-height:180px"></div></div>';
/* render({navigation:true}) = vraie navigation utilisateur (go) : légère sortie, squelette si
   la page met plus de 150 ms, puis entrée (160 ms). Tout autre appel (enregistrement,
   Actualiser, tick live) redessine sans transition et garde le contenu visible. */
async function render({ navigation = false } = {}) {
  if (!state.guild && !GLOBAL_PAGES.has(state.page)) return;
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
  $('serverRail').innerHTML = installed.map(g => `<button class="guild-btn ${String(g.id) === String(state.guildId) ? 'active' : ''}" type="button" data-guild="${esc(g.id)}" title="${esc(g.name)}" aria-label="${esc(g.name)}">${g.icon_url ? `<img src="${esc(g.icon_url)}" alt="">` : esc((g.name || 'S').slice(0, 2).toUpperCase())}</button>`).join('') + (missing[0] ? `<a class="guild-btn add" href="${esc(missing[0].invite_url || '#')}" title="Ajouter SentriX à un autre serveur">+</a>` : '');
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
async function selectGuild(value) {
  if (!value || String(value) === String(state.guildId) && state.guild) return;
  if (!(await guardDirty())) return;
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
async function loadGuilds() {
  const payload = await api('/api/guilds');
  state.guilds = payload.guilds || [];
  showOnly('dashboard');
  renderServerRail();
  const installed = state.guilds.filter(g => g.installed);
  let wanted = new URLSearchParams(location.search).get('guild');
  if (!wanted) { try { wanted = localStorage.getItem('sentrix:guild') || ''; } catch (_) {} }
  if (!installed.some(g => String(g.id) === String(wanted))) {
    // Sélection mémorisée périmée (serveur quitté, SentriX retiré) : on l'oublie.
    try { localStorage.removeItem('sentrix:guild'); } catch (_) {}
    wanted = installed.length === 1 ? installed[0].id : '';
  }
  if (wanted) { await selectGuild(wanted); return; }
  if (installed.length) {
    state.page = 'profile';
    state.sub = '';
    await render({ navigation: true });
    return;
  }
  const invite = state.guilds.find(g => g.invite_url)?.invite_url;
  state.page = 'profile';
  state.sub = '';
  await render({ navigation: true });
  const b = content().querySelector('[data-empty-action="inviteBot"]'); if (b) b.onclick = () => { location.href = invite; };
}

/* ---------- session & états de démarrage ----------
   booting → auth_required | error | loading_guilds → ready.
   Aucun état intermédiaire ne laisse la page vide : soit le dashboard, soit la page de
   connexion, soit un panneau d'erreur avec « Réessayer » / « Se reconnecter ». */
const boot = { state: 'booting', watchdog: null };
function showOnly(id) {
  for (const k of ['landing', 'bootState', 'dashboard']) $(k).classList.toggle('hidden', k !== id);
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
  let me;
  try { me = await api('/api/me'); }
  catch (e) {
    if (e.status === 401 && location.pathname.startsWith('/app')) { const n = $('authMessage'); n.textContent = 'Connectez-vous avec Discord pour ouvrir le dashboard.'; n.classList.remove('hidden'); }
    bootError(e, 'AUTH');
    return false;
  }
  state.user = me.user; state.csrf = me.csrf; state.developer = Boolean(me.developer);
  $('profileButton').classList.remove('hidden');
  $('userName').textContent = me.user?.username || 'Compte';
  if (me.user?.avatar_url) $('userAvatar').innerHTML = `<img src="${esc(me.user.avatar_url)}" alt="">`;
  renderNav();
  boot.state = 'loading_guilds';
  try { await loadGuilds(); }
  catch (e) { bootError(e, 'GUILDS'); return false; }
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
$('refreshButton').onclick = async () => { if (!state.guildId) return; if (!(await guardDirty())) return; state.cache.clear(); await reloadGuild(); await render(); toast('Données actualisées.'); };
$('saveButton').onclick = saveDirty;
$('discardButton').onclick = () => { clearDirty(); render(); };
$('profileButton').onclick = async () => { if (!(await confirmDialog({ title: 'Se déconnecter ?', body: 'Vous devrez vous reconnecter avec Discord pour revenir.', confirm: 'Se déconnecter' }))) return; try { await api('/logout', { method: 'POST' }); } finally { location.href = '/'; } };
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveDirty(); }
  if (e.key === 'Escape') { closePalette(); closeModal(); closeSidebar(); }
});
window.addEventListener('beforeunload', e => { if (hasDirty()) { e.preventDefault(); e.returnValue = ''; } });
window.addEventListener('offline', () => $('netNotice').classList.remove('hidden'));
window.addEventListener('online', () => $('netNotice').classList.add('hidden'));
window.addEventListener('popstate', () => { const q = new URLSearchParams(location.search); const p = q.get('tab'); if (p && p !== state.page) go(p, q.get('sub') || ''); });

async function bootstrap() {
  const q = new URLSearchParams(location.search);
  let page = q.get('tab') || '';
  if (!page) { try { page = localStorage.getItem('sentrix:page') || ''; } catch (_) {} }
  if (LEGACY[page]) { state.sub = LEGACY[page][1] || ''; page = LEGACY[page][0]; }
  state.page = META[page] ? page : 'overview';
  if (q.get('sub')) state.sub = q.get('sub');
  try { state.navMore = localStorage.getItem('sentrix:nav:more') === '1'; } catch (_) {}
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
