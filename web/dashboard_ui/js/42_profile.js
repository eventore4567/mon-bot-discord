/* ---------- Espace global SentriX ----------
   Aucune route dépendante d'une guild n'est appelée ici : /app s'ouvre toujours sur
   le compte utilisateur, puis la configuration serveur commence seulement après un clic
   explicite sur un serveur de la colonne gauche ou de la page Mes serveurs. */

function applyGlobalPreferences() {
  let theme = 'sentrix';
  let reduced = false;
  try {
    theme = localStorage.getItem('sentrix:theme') || 'sentrix';
    reduced = localStorage.getItem('sentrix:reduce-motion') === '1';
  } catch (_) {}
  document.documentElement.dataset.theme = theme === 'oled' ? 'oled' : 'sentrix';
  state.reduceMotion = reduced;
}
applyGlobalPreferences();

function globalServerCard(g, add = false) {
  const initials = esc((g.name || 'S').slice(0, 2).toUpperCase());
  const icon = g.icon_url ? `<img src="${esc(g.icon_url)}" alt="">` : initials;
  const role = add ? 'SentriX n’est pas installé' : (g.owner ? 'Propriétaire' : 'Administrateur');
  return `<article class="global-server-card">
    <div class="global-server-main">
      <span class="global-server-icon">${icon}</span>
      <div class="row-main">
        <b>${esc(g.name || 'Serveur Discord')}</b>
        <small>${esc(role)}</small>
      </div>
    </div>
    <div class="toolbar">
      ${add
        ? `<a class="btn sm" href="${esc(g.invite_url || '#')}">Ajouter SentriX</a>`
        : `<span class="desktop-rail-hint">Sélectionnez-le à gauche</span><button class="btn sm primary mobile-server-select" type="button" data-global-guild="${esc(g.id)}">Ouvrir</button>`}
    </div>
  </article>`;
}

function bindGlobalServerCards(root = content()) {
  root.querySelectorAll('[data-global-guild]').forEach(b => b.onclick = () => selectGuild(b.dataset.globalGuild));
}

function renderProfile() {
  const user = state.user || {};
  const installed = state.guilds.filter(g => g.installed);
  const missing = state.guilds.filter(g => !g.installed);
  const display = user.global_name || user.username || 'Compte Discord';
  const avatar = user.avatar_url
    ? `<img src="${esc(user.avatar_url)}" alt="">`
    : esc(String(display).slice(0, 2).toUpperCase());

  content().innerHTML = `<div class="global-home">
    <section class="global-hero">
      <div class="global-profile-block">
        <span class="global-avatar">${avatar}</span>
        <div class="global-profile-copy">
          <span class="eyebrow">Mon espace SentriX</span>
          <h2>${esc(display)}</h2>
          <p>@${esc(user.username || display)} · compte Discord connecté</p>
          <div class="toolbar">
            <button class="btn primary" type="button" data-go="servers">Mes serveurs</button>
            <span class="profile-rail-tip">Pour configurer : choisissez un serveur dans la colonne à gauche.</span>
          </div>
        </div>
      </div>
      <div class="global-hero-stats">
        <div class="kpi"><small>Serveurs avec SentriX</small><strong>${number(installed.length)}</strong></div>
        <div class="kpi"><small>Serveurs administrables</small><strong>${number(state.guilds.length)}</strong></div>
        <div class="kpi"><small>À ajouter</small><strong>${number(missing.length)}</strong></div>
      </div>
    </section>

    <section class="card full">
      <div class="card-head">
        <div>
          <h2>Continuer sur un serveur</h2>
          <p>Vous restez dans votre espace personnel tant que vous n’avez pas choisi un serveur.</p>
        </div>
        <button class="btn ghost" type="button" data-go="servers">Tout afficher</button>
      </div>
      <div class="global-server-grid">
        ${installed.length
          ? installed.slice(0, 6).map(g => globalServerCard(g)).join('')
          : emptyState('Aucun serveur avec SentriX', 'Ajoutez SentriX à un serveur dont vous êtes administrateur.')}
      </div>
    </section>

    <section class="grid">
      <article class="card">
        <h2>Votre compte</h2>
        <div class="list compact">
          <div class="row"><div class="row-main"><b>Nom Discord</b><small>${esc(user.username || '—')}</small></div></div>
          <div class="row"><div class="row-main"><b>Identifiant</b><small>${esc(user.id || '—')}</small></div></div>
          <div class="row"><div class="row-main"><b>Session</b><small>Connectée et sécurisée par Discord OAuth2.</small></div></div>
        </div>
      </article>
      <article class="card">
        <h2>Profil communautaire</h2>
        <p>Bio, anniversaire, fond de carte, niveau et réputation appartiennent à chaque serveur.</p>
        <div class="notice">Choisissez un serveur pour modifier votre profil SentriX communautaire et voir vos statistiques locales.</div>
      </article>
      <article class="card">
        <h2>Préférences rapides</h2>
        <p>Le thème et les animations ne changent que ce navigateur.</p>
        <div class="toolbar"><button class="btn" type="button" data-go="preferences">Ouvrir les préférences</button></div>
      </article>
      <article class="card">
        <h2>Déconnexion</h2>
        <p>Ferme uniquement votre session dashboard. Le bot reste actif sur vos serveurs.</p>
        <div class="toolbar"><button class="btn danger" type="button" id="profileLogout">Se déconnecter</button></div>
      </article>
    </section>
  </div>`;

  bindGlobalServerCards();
  $('profileLogout').onclick = async () => {
    if (!(await confirmDialog({ title: 'Se déconnecter ?', body: 'Vous devrez vous reconnecter avec Discord pour revenir au dashboard.', confirm: 'Se déconnecter' }))) return;
    try { await api('/logout', { method: 'POST' }); } finally { location.href = '/'; }
  };
}

function renderServers() {
  const installed = state.guilds.filter(g => g.installed);
  const missing = state.guilds.filter(g => !g.installed);
  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head">
        <div><h2>Mes serveurs</h2><p>Cliquez sur Configurer pour entrer dans le dashboard d’un serveur.</p></div>
        <input class="search-input" id="globalServerSearch" type="search" placeholder="Rechercher un serveur…">
      </div>
      <div id="globalServerLists"></div>
    </section>
  </div>`;

  const paint = () => {
    const q = $('globalServerSearch').value.trim().toLocaleLowerCase('fr');
    const filter = list => list.filter(g => !q || String(g.name || '').toLocaleLowerCase('fr').includes(q));
    const have = filter(installed), add = filter(missing);
    $('globalServerLists').innerHTML = `
      <div class="global-section-title"><b>Avec SentriX</b><small>${plural(have.length, 'serveur')}</small></div>
      <div class="global-server-grid">${have.length ? have.map(g => globalServerCard(g)).join('') : emptyState('Aucun résultat', q ? 'Aucun serveur installé ne correspond à votre recherche.' : 'Aucun serveur avec SentriX.')}</div>
      ${add.length ? `<div class="global-section-title"><b>Ajouter SentriX</b><small>${plural(add.length, 'serveur')}</small></div><div class="global-server-grid">${add.map(g => globalServerCard(g, true)).join('')}</div>` : ''}
    `;
    bindGlobalServerCards($('globalServerLists'));
  };
  $('globalServerSearch').oninput = paint;
  paint();
}

function renderPreferences() {
  let theme = 'sentrix', reduce = false;
  try {
    theme = localStorage.getItem('sentrix:theme') || 'sentrix';
    reduce = localStorage.getItem('sentrix:reduce-motion') === '1';
  } catch (_) {}
  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head"><div><h2>Apparence</h2><p>Le bleu SentriX reste la couleur principale. Ces réglages sont locaux à ce navigateur.</p></div></div>
      <div class="fields">
        <div class="field">
          <label for="prefTheme">Thème</label>
          <select id="prefTheme">
            <option value="sentrix" ${theme === 'sentrix' ? 'selected' : ''}>Sombre SentriX</option>
            <option value="oled" ${theme === 'oled' ? 'selected' : ''}>Sombre OLED</option>
          </select>
        </div>
        <label class="switch-row">
          <span class="switch-copy"><b>Réduire les animations</b><span>Désactive les transitions de navigation même si macOS les autorise.</span></span>
          <input class="switch" id="prefReduceMotion" type="checkbox" ${reduce ? 'checked' : ''}>
        </label>
      </div>
    </section>
    <section class="card">
      <h2>Navigation</h2>
      <label class="switch-row"><span class="switch-copy"><b>Garder “Plus d’outils” ouvert</b><span>Uniquement dans la configuration d’un serveur.</span></span><input class="switch" id="prefMoreTools" type="checkbox" ${state.navMore ? 'checked' : ''}></label>
    </section>
    <section class="card">
      <h2>Comportement au démarrage</h2>
      <div class="notice ok">Le dashboard s’ouvre toujours sur Mon profil. Un serveur n’est chargé qu’après un clic explicite.</div>
    </section>
  </div>`;

  $('prefTheme').onchange = () => {
    try { localStorage.setItem('sentrix:theme', $('prefTheme').value); } catch (_) {}
    applyGlobalPreferences();
    toast('Thème appliqué.');
  };
  $('prefReduceMotion').onchange = () => {
    try { localStorage.setItem('sentrix:reduce-motion', $('prefReduceMotion').checked ? '1' : '0'); } catch (_) {}
    applyGlobalPreferences();
    toast('Préférence d’animation enregistrée.');
  };
  $('prefMoreTools').onchange = () => {
    state.navMore = $('prefMoreTools').checked;
    try { localStorage.setItem('sentrix:nav:more', state.navMore ? '1' : '0'); } catch (_) {}
    renderNav();
  };
}
