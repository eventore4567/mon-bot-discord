/* ---------- rendu ---------- */
const PAGES = {
  overview: renderOverview, welcome: renderWelcome, levels: renderLevels, economy: renderEconomy, roles: renderRoles,
  security: renderSecurity, logs: renderLogs, tickets: renderTickets, notifications: renderNotifications, automation: renderAutomation,
  settings: renderSettings, access: renderAccess, embeds: renderEmbeds, ai: renderAI, invites: renderInvites, backups: renderBackups,
  dm: renderDM, advanced: renderAdvanced, diagnostic: renderDiagnostic,
};
let renderToken = 0;
async function render() {
  if (!state.guild) return;
  const token = ++renderToken;
  setHead(); renderNav(); renderSubnav(); syncUrl();
  const el = content();
  el.setAttribute('aria-busy', 'true');
  try {
    await (PAGES[state.page] || renderOverview)();
    if (token !== renderToken) return;
    el.querySelectorAll('[data-go]').forEach(b => { if (!b.onclick) b.onclick = () => go(b.dataset.go, b.dataset.goSub || ''); });
  } catch (e) {
    if (token === renderToken) errorView(e);
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
    await render();
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
  renderServerRail();
  const installed = state.guilds.filter(g => g.installed);
  let wanted = new URLSearchParams(location.search).get('guild');
  if (!wanted) { try { wanted = localStorage.getItem('sentrix:guild') || ''; } catch (_) {} }
  if (!installed.some(g => String(g.id) === String(wanted))) wanted = installed.length === 1 ? installed[0].id : '';
  if (wanted) await selectGuild(wanted);
  else if (installed.length) { content().innerHTML = emptyState('Choisissez un serveur', 'Sélectionnez le serveur à configurer.', { id: 'pickGuild', label: 'Choisir un serveur' }); content().querySelector('[data-empty-action="pickGuild"]').onclick = openServerPicker; openServerPicker(); }
  else content().innerHTML = emptyState('Aucun serveur administrable', 'Vous devez être administrateur d’un serveur où SentriX est installé.');
}

/* ---------- session ---------- */
async function loadPublic() {
  try {
    const p = await api('/api/public');
    $('publicGuilds').textContent = number(p.guilds); $('publicMembers').textContent = number(p.members);
    $('publicLatency').textContent = p.latency_ms == null ? '—' : `${p.latency_ms} ms`; $('publicUptime').textContent = age(p.uptime_seconds);
    $('publicBadge').textContent = p.online ? 'En ligne' : 'Connexion'; $('publicBadge').className = `badge ${p.online ? 'ok' : 'warn'}`;
    setRuntime(Boolean(p.online), p.latency_ms);
  } catch (_) { $('publicBadge').textContent = 'Indisponible'; $('publicBadge').className = 'badge bad'; }
}
function showLanding() { $('landing').classList.remove('hidden'); $('dashboard').classList.add('hidden'); loadPublic(); }
async function loadSession() {
  try {
    const me = await api('/api/me');
    state.user = me.user; state.csrf = me.csrf; state.developer = Boolean(me.developer);
    $('landing').classList.add('hidden'); $('dashboard').classList.remove('hidden'); $('profileButton').classList.remove('hidden');
    $('userName').textContent = me.user?.username || 'Compte';
    if (me.user?.avatar_url) $('userAvatar').innerHTML = `<img src="${esc(me.user.avatar_url)}" alt="">`;
    renderNav();
    await loadGuilds();
    return true;
  } catch (e) {
    if (e.status === 503) { $('landing').classList.add('hidden'); $('dashboard').classList.add('hidden'); setRuntime(false); return false; }
    if (e.status === 401 && location.pathname.startsWith('/app')) { showLanding(); const n = $('authMessage'); n.textContent = 'Connectez-vous avec Discord pour ouvrir le dashboard.'; n.classList.remove('hidden'); return false; }
    showLanding();
    return false;
  }
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

async function boot() {
  const q = new URLSearchParams(location.search);
  let page = q.get('tab') || '';
  if (!page) { try { page = localStorage.getItem('sentrix:page') || ''; } catch (_) {} }
  if (LEGACY[page]) { state.sub = LEGACY[page][1] || ''; page = LEGACY[page][0]; }
  state.page = META[page] ? page : 'overview';
  if (q.get('sub')) state.sub = q.get('sub');
  try { state.navMore = localStorage.getItem('sentrix:nav:more') === '1'; } catch (_) {}
  if (q.get('auth') === 'missing') { const n = $('authMessage'); n.textContent = 'Connexion Discord indisponible pour le moment. Réessayez dans quelques instants ou contactez le support.'; n.classList.remove('hidden'); history.replaceState(null, '', location.pathname); }
  renderNav();
  await loadSession();
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
else boot();
