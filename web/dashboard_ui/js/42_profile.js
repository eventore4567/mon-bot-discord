/* ---------- Espace global SentriX ----------
   Aucune route dépendante d'une guild n'est appelée ici : /app s'ouvre toujours sur
   le compte utilisateur, puis la configuration serveur commence seulement après un clic
   explicite sur un serveur de la colonne gauche ou de la page Mes serveurs. */

const DASHBOARD_ACCENTS = [
  ['#4da3ff', 'Bleu SentriX'],
  ['#7c5cff', 'Violet'],
  ['#00b8d9', 'Cyan'],
  ['#34c78a', 'Émeraude'],
  ['#f0b232', 'Or'],
  ['#ff7a59', 'Corail'],
  ['#ff5ca8', 'Rose'],
  ['#a8b3c7', 'Argent'],
];

function normalizeAccent(value) {
  const raw = String(value || '').trim();
  if (!/^#[0-9a-f]{6}$/i.test(raw)) return '#4da3ff';
  return raw.toLowerCase();
}
function accentRgb(hex) {
  const value = normalizeAccent(hex).slice(1);
  return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16)];
}
function accentMix(hex, toward = 255, amount = .28) {
  const [r,g,b] = accentRgb(hex);
  const mix = n => Math.max(0, Math.min(255, Math.round(n + (toward - n) * amount)));
  return `rgb(${mix(r)} ${mix(g)} ${mix(b)})`;
}
function accentAlpha(hex, alpha = .18) {
  const [r,g,b] = accentRgb(hex);
  return `rgb(${r} ${g} ${b} / ${alpha})`;
}
function applyGlobalPreferences() {
  let theme = 'sentrix', accent = '#4da3ff', reduced = false, glow = true, density = 'comfortable', radius = 'rounded', banner = 'aurora';
  try {
    theme = localStorage.getItem('sentrix:theme') || 'sentrix';
    accent = normalizeAccent(localStorage.getItem('sentrix:accent') || '#4da3ff');
    reduced = localStorage.getItem('sentrix:reduce-motion') === '1';
    glow = localStorage.getItem('sentrix:glow') !== '0';
    density = localStorage.getItem('sentrix:density') || 'comfortable';
    radius = localStorage.getItem('sentrix:radius') || 'rounded';
    banner = localStorage.getItem('sentrix:banner') || 'aurora';
  } catch (_) {}
  const allowedThemes = new Set(['sentrix','oled','midnight','graphite']);
  const allowedDensity = new Set(['comfortable','compact']);
  const allowedRadius = new Set(['rounded','soft','sharp']);
  const allowedBanner = new Set(['aurora','mesh','minimal']);
  const root = document.documentElement;
  root.dataset.theme = allowedThemes.has(theme) ? theme : 'sentrix';
  root.dataset.glow = glow ? 'on' : 'off';
  root.dataset.density = allowedDensity.has(density) ? density : 'comfortable';
  root.dataset.radius = allowedRadius.has(radius) ? radius : 'rounded';
  root.dataset.banner = allowedBanner.has(banner) ? banner : 'aurora';
  root.style.setProperty('--blue', accent);
  root.style.setProperty('--blue2', accentMix(accent, 255, .30));
  root.style.setProperty('--blue-bg', accentAlpha(accent, .16));
  root.style.setProperty('--accent-glow', accentAlpha(accent, .22));
  root.style.setProperty('--accent-soft', accentAlpha(accent, .10));
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
  let theme = 'sentrix', accent = '#4da3ff', reduce = false, glow = true, density = 'comfortable', radius = 'rounded', banner = 'aurora';
  try {
    theme = localStorage.getItem('sentrix:theme') || 'sentrix';
    accent = normalizeAccent(localStorage.getItem('sentrix:accent') || '#4da3ff');
    reduce = localStorage.getItem('sentrix:reduce-motion') === '1';
    glow = localStorage.getItem('sentrix:glow') !== '0';
    density = localStorage.getItem('sentrix:density') || 'comfortable';
    radius = localStorage.getItem('sentrix:radius') || 'rounded';
    banner = localStorage.getItem('sentrix:banner') || 'aurora';
  } catch (_) {}

  const palette = DASHBOARD_ACCENTS.map(([hex, label]) =>
    `<button class="accent-swatch ${accent === hex ? 'active' : ''}" type="button" data-accent="${hex}" title="${esc(label)}" aria-label="${esc(label)}" style="--swatch:${hex}"></button>`
  ).join('');

  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head">
        <div><h2>Personnalisation du dashboard</h2><p>Couleurs, ambiance, densité et animations. Tout est appliqué instantanément sur ce navigateur.</p></div>
        <span class="badge blue">Aperçu en direct</span>
      </div>

      <div class="personalization-preview" id="personalizationPreview">
        <div class="personalization-preview-mark">S</div>
        <div class="row-main">
          <b>SentriX Dashboard</b>
          <small>Votre style, sans changer les couleurs du serveur Discord.</small>
        </div>
        <button class="btn primary sm" type="button">Action</button>
      </div>

      <div class="fields">
        <div class="field">
          <label for="prefTheme">Ambiance</label>
          <select id="prefTheme">
            <option value="sentrix" ${theme === 'sentrix' ? 'selected' : ''}>Sombre SentriX</option>
            <option value="oled" ${theme === 'oled' ? 'selected' : ''}>OLED noir profond</option>
            <option value="midnight" ${theme === 'midnight' ? 'selected' : ''}>Midnight bleu nuit</option>
            <option value="graphite" ${theme === 'graphite' ? 'selected' : ''}>Graphite neutre</option>
          </select>
        </div>
        <div class="field">
          <label for="prefBanner">Décor du profil</label>
          <select id="prefBanner">
            <option value="aurora" ${banner === 'aurora' ? 'selected' : ''}>Aurora</option>
            <option value="mesh" ${banner === 'mesh' ? 'selected' : ''}>Mesh lumineux</option>
            <option value="minimal" ${banner === 'minimal' ? 'selected' : ''}>Minimal</option>
          </select>
        </div>
        <div class="field full">
          <label>Couleur principale</label>
          <div class="accent-picker">
            <div class="accent-swatches">${palette}</div>
            <div class="accent-custom">
              <input id="prefAccentColor" type="color" value="${accent}">
              <input id="prefAccentHex" value="${accent}" maxlength="7" aria-label="Couleur hexadécimale">
            </div>
          </div>
          <small>Vous pouvez choisir une couleur proposée ou saisir n’importe quelle couleur HEX.</small>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Interface</h2>
      <div class="field">
        <label for="prefDensity">Densité</label>
        <select id="prefDensity">
          <option value="comfortable" ${density === 'comfortable' ? 'selected' : ''}>Confortable</option>
          <option value="compact" ${density === 'compact' ? 'selected' : ''}>Compacte</option>
        </select>
      </div>
      <div class="field">
        <label for="prefRadius">Coins</label>
        <select id="prefRadius">
          <option value="rounded" ${radius === 'rounded' ? 'selected' : ''}>Arrondis</option>
          <option value="soft" ${radius === 'soft' ? 'selected' : ''}>Discrets</option>
          <option value="sharp" ${radius === 'sharp' ? 'selected' : ''}>Carrés</option>
        </select>
      </div>
      <label class="switch-row">
        <span class="switch-copy"><b>Effets lumineux</b><span>Halo d’accent et profondeur du profil.</span></span>
        <input class="switch" id="prefGlow" type="checkbox" ${glow ? 'checked' : ''}>
      </label>
    </section>

    <section class="card">
      <h2>Animations</h2>
      <label class="switch-row">
        <span class="switch-copy"><b>Réduire les animations</b><span>Désactive les transitions de page tout en gardant les retours visuels essentiels.</span></span>
        <input class="switch" id="prefReduceMotion" type="checkbox" ${reduce ? 'checked' : ''}>
      </label>
      <div class="notice">Aucune animation périodique : les effets ne se déclenchent que lorsque vous naviguez.</div>
    </section>

    <section class="card">
      <h2>Navigation</h2>
      <label class="switch-row"><span class="switch-copy"><b>Garder “Plus d’outils” ouvert</b><span>Uniquement dans la configuration d’un serveur.</span></span><input class="switch" id="prefMoreTools" type="checkbox" ${state.navMore ? 'checked' : ''}></label>
      <div class="notice ok">Le dashboard s’ouvre toujours sur Mon profil. Un serveur n’est chargé qu’après un clic explicite.</div>
    </section>

    <section class="card">
      <h2>Réinitialiser</h2>
      <p>Revient au style SentriX d’origine sans toucher à votre compte ni à vos serveurs.</p>
      <div class="toolbar"><button class="btn danger" type="button" id="prefReset">Réinitialiser l’apparence</button></div>
    </section>
  </div>`;

  const save = (key, value) => { try { localStorage.setItem(key, value); } catch (_) {} applyGlobalPreferences(); };
  const setAccent = value => {
    const next = normalizeAccent(value);
    save('sentrix:accent', next);
    $('prefAccentColor').value = next;
    $('prefAccentHex').value = next;
    content().querySelectorAll('[data-accent]').forEach(b => b.classList.toggle('active', b.dataset.accent === next));
  };

  $('prefTheme').onchange = () => { save('sentrix:theme', $('prefTheme').value); toast('Ambiance appliquée.'); };
  $('prefBanner').onchange = () => { save('sentrix:banner', $('prefBanner').value); toast('Décor appliqué.'); };
  $('prefDensity').onchange = () => { save('sentrix:density', $('prefDensity').value); toast('Densité appliquée.'); };
  $('prefRadius').onchange = () => { save('sentrix:radius', $('prefRadius').value); toast('Style des coins appliqué.'); };
  $('prefGlow').onchange = () => { save('sentrix:glow', $('prefGlow').checked ? '1' : '0'); };
  $('prefReduceMotion').onchange = () => {
    save('sentrix:reduce-motion', $('prefReduceMotion').checked ? '1' : '0');
    toast('Préférence d’animation enregistrée.');
  };
  $('prefAccentColor').oninput = () => setAccent($('prefAccentColor').value);
  $('prefAccentHex').onchange = () => {
    const raw = String($('prefAccentHex').value || '').trim();
    if (!/^#[0-9a-f]{6}$/i.test(raw)) { $('prefAccentHex').value = normalizeAccent(localStorage.getItem('sentrix:accent')); return toast('Couleur HEX invalide.', true); }
    setAccent(raw);
  };
  content().querySelectorAll('[data-accent]').forEach(b => b.onclick = () => setAccent(b.dataset.accent));
  $('prefMoreTools').onchange = () => {
    state.navMore = $('prefMoreTools').checked;
    try { localStorage.setItem('sentrix:nav:more', state.navMore ? '1' : '0'); } catch (_) {}
    renderNav();
  };
  $('prefReset').onclick = async () => {
    if (!(await confirmDialog({ title: 'Réinitialiser l’apparence ?', body: 'Les couleurs, l’ambiance, la densité et les effets reviendront aux valeurs SentriX.', confirm: 'Réinitialiser' }))) return;
    for (const key of ['sentrix:theme','sentrix:accent','sentrix:glow','sentrix:density','sentrix:radius','sentrix:banner','sentrix:reduce-motion']) {
      try { localStorage.removeItem(key); } catch (_) {}
    }
    applyGlobalPreferences();
    renderPreferences();
    toast('Apparence réinitialisée.');
  };
}

