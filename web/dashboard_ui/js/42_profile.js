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
const DASHBOARD_THEME_BASES = {
  sentrix: { bg:'#0b0d10', bg2:'#101318', rail:'#101318', sidebar:'#101318', panel:'#15191f', panel2:'#1a1f27', panel3:'#202630', line:'#2a313c', line2:'#343d49', text:'#f2f5f8', muted:'#929dac', soft:'#bac3cf', hover:'#1a1f27', success:'#55d69a', warning:'#efbd61', danger:'#ff7081' },
  oled: { bg:'#000000', bg2:'#050607', rail:'#020304', sidebar:'#020304', panel:'#0b0d10', panel2:'#101318', panel3:'#15191f', line:'#1c222a', line2:'#29313b', text:'#f7f7f8', muted:'#9ba3ad', soft:'#c8ced6', hover:'#101318', success:'#55d69a', warning:'#efbd61', danger:'#ff7081' },
  midnight: { bg:'#070b14', bg2:'#0b111d', rail:'#080d17', sidebar:'#0b111d', panel:'#111827', panel2:'#162033', panel3:'#1d2a40', line:'#23324a', line2:'#31435f', text:'#f1f6ff', muted:'#8fa0b8', soft:'#c0ccda', hover:'#162033', success:'#4ed69d', warning:'#f0bd66', danger:'#ff7485' },
  graphite: { bg:'#0d0e10', bg2:'#121417', rail:'#101214', sidebar:'#121417', panel:'#181b1f', panel2:'#1e2227', panel3:'#252a30', line:'#30363d', line2:'#3b434c', text:'#f3f4f6', muted:'#9aa1aa', soft:'#c6cbd1', hover:'#1e2227', success:'#58d39a', warning:'#eebd67', danger:'#ff7586' },
};

const DASHBOARD_CURATED_PALETTES = {
  rose: {
    label:'Rose OLED', note:'Noir profond, rose néon et surfaces légèrement violettes.', theme:'oled', accent:'#ff4fa3',
    colors:{bg:'#000000',bg2:'#080509',rail:'#09050a',sidebar:'#0d080e',panel:'#120b13',panel2:'#18101a',panel3:'#211623',hover:'#1b111d',line:'#2f2032',line2:'#49304c',text:'#fff7fb',muted:'#aa93a2',soft:'#d7c2cf',success:'#55d69a',warning:'#f0bd61',danger:'#ff7081'}
  },
  blue: {
    label:'SentriX Azure', note:'Bleu propre, lisible et équilibré pour tous les écrans.', theme:'sentrix', accent:'#4da3ff',
    colors:{bg:'#090c11',bg2:'#0d1218',rail:'#0c1117',sidebar:'#0e131a',panel:'#141a22',panel2:'#1a222c',panel3:'#222d39',hover:'#1b2530',line:'#293645',line2:'#3a4a5d',text:'#f4f8fc',muted:'#91a0b2',soft:'#bdc9d7',success:'#55d69a',warning:'#efbd61',danger:'#ff7081'}
  },
  violet: {
    label:'Cosmos Violet', note:'Dégradé nuit avec violet lumineux et contrastes doux.', theme:'midnight', accent:'#8a6cff',
    colors:{bg:'#070611',bg2:'#0d0b19',rail:'#0a0815',sidebar:'#0d0b19',panel:'#141023',panel2:'#1a1530',panel3:'#231d3d',hover:'#1c1734',line:'#30284a',line2:'#463a68',text:'#f7f3ff',muted:'#9d94b5',soft:'#cbc3df',success:'#57d9a2',warning:'#f0bd66',danger:'#ff7485'}
  },
  emerald: {
    label:'Emerald Graphite', note:'Graphite sombre avec accent vert premium et discret.', theme:'graphite', accent:'#45d69a',
    colors:{bg:'#090b0b',bg2:'#0e1211',rail:'#0d1110',sidebar:'#101513',panel:'#161c1a',panel2:'#1c2421',panel3:'#25302c',hover:'#1e2925',line:'#2d3a35',line2:'#3d5049',text:'#f3f8f6',muted:'#94a59f',soft:'#c3d0cc',success:'#55d69a',warning:'#efbd61',danger:'#ff7081'}
  },
};

const DASHBOARD_COLOR_FIELDS = [
  ['bg','Fond général','--bg'],
  ['bg2','Fond secondaire','--bg2'],
  ['rail','Colonne serveurs','--rail-bg'],
  ['sidebar','Sidebar','--sidebar-bg'],
  ['panel','Cartes','--panel'],
  ['panel2','Cartes secondaires','--panel2'],
  ['panel3','Surfaces profondes','--panel3'],
  ['hover','Survol','--hover-bg'],
  ['line','Bordures','--line'],
  ['line2','Bordures fortes','--line2'],
  ['text','Texte principal','--text'],
  ['muted','Texte secondaire','--muted'],
  ['soft','Texte doux','--soft'],
  ['success','Succès','--green'],
  ['warning','Avertissement','--amber'],
  ['danger','Erreur / danger','--red'],
];

function normalizeHex(value, fallback = '#4da3ff') {
  const raw = String(value || '').trim();
  return /^#[0-9a-f]{6}$/i.test(raw) ? raw.toLowerCase() : fallback;
}
function hexRgb(hex) {
  const value = normalizeHex(hex, '#000000').slice(1);
  return [parseInt(value.slice(0,2),16),parseInt(value.slice(2,4),16),parseInt(value.slice(4,6),16)];
}
function colorLuminance(hex) {
  const [r,g,b]=hexRgb(hex).map(v=>v/255).map(v=>v<=.03928?v/12.92:Math.pow((v+.055)/1.055,2.4));
  return .2126*r+.7152*g+.0722*b;
}
function contrastRatio(a,b) {
  const [hi,lo]=[colorLuminance(a),colorLuminance(b)].sort((x,y)=>y-x);
  return (hi+.05)/(lo+.05);
}
function readThemeColors(theme = 'sentrix') {
  let custom = {};
  try { custom = JSON.parse(localStorage.getItem('sentrix:theme-colors') || '{}') || {}; } catch (_) {}
  const base = DASHBOARD_THEME_BASES[theme] || DASHBOARD_THEME_BASES.sentrix;
  const clean = {};
  for (const [key] of DASHBOARD_COLOR_FIELDS) clean[key] = normalizeHex(custom[key], base[key]);
  return clean;
}
function writeThemeColors(colors) {
  try { localStorage.setItem('sentrix:theme-colors', JSON.stringify(colors)); } catch (_) {}
}
function readSavedThemes() {
  try {
    const value = JSON.parse(localStorage.getItem('sentrix:saved-themes') || '[]');
    return Array.isArray(value) ? value.slice(0, 20) : [];
  } catch (_) { return []; }
}
function writeSavedThemes(items) {
  try { localStorage.setItem('sentrix:saved-themes', JSON.stringify(items.slice(0,20))); } catch (_) {}
}
function contrastStatus(colors) {
  const pairs = [
    ['Texte / fond', colors.text, colors.bg, 4.5],
    ['Texte / cartes', colors.text, colors.panel, 4.5],
    ['Texte secondaire / fond', colors.muted, colors.bg, 3],
  ];
  const bad = pairs.filter(([,a,b,min]) => contrastRatio(a,b) < min);
  return { ok: !bad.length, bad };
}
function captureThemeSnapshot(name='') {
  const theme = (()=>{try{return localStorage.getItem('sentrix:theme')||'sentrix';}catch(_){return 'sentrix';}})();
  return {
    id: String(Date.now()),
    name: String(name||'').trim().slice(0,32) || 'Mon thème',
    theme,
    accent: normalizeAccent((()=>{try{return localStorage.getItem('sentrix:accent')||'#4da3ff';}catch(_){return '#4da3ff';}})()),
    colors: readThemeColors(theme),
    banner:(()=>{try{return localStorage.getItem('sentrix:banner')||'aurora';}catch(_){return 'aurora';}})(),
    density:(()=>{try{return localStorage.getItem('sentrix:density')||'comfortable';}catch(_){return 'comfortable';}})(),
    radius:(()=>{try{return localStorage.getItem('sentrix:radius')||'rounded';}catch(_){return 'rounded';}})(),
    glow:(()=>{try{return localStorage.getItem('sentrix:glow')!=='0';}catch(_){return true;}})(),
    reduceMotion:(()=>{try{return localStorage.getItem('sentrix:reduce-motion')==='1';}catch(_){return false;}})(),
  };
}
function applyThemeSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return;
  try {
    localStorage.setItem('sentrix:theme', snapshot.theme || 'sentrix');
    localStorage.setItem('sentrix:accent', normalizeAccent(snapshot.accent || '#4da3ff'));
    localStorage.setItem('sentrix:theme-colors', JSON.stringify(snapshot.colors || {}));
    localStorage.setItem('sentrix:banner', snapshot.banner || 'aurora');
    localStorage.setItem('sentrix:density', snapshot.density || 'comfortable');
    localStorage.setItem('sentrix:radius', snapshot.radius || 'rounded');
    localStorage.setItem('sentrix:glow', snapshot.glow === false ? '0' : '1');
    localStorage.setItem('sentrix:reduce-motion', snapshot.reduceMotion ? '1' : '0');
  } catch (_) {}
  applyGlobalPreferences();
}
function applyGlobalPreferences() {
  let theme='sentrix',accent='#4da3ff',reduced=false,glow=true,density='comfortable',radius='rounded',banner='aurora';
  try {
    theme=localStorage.getItem('sentrix:theme')||'sentrix';
    accent=normalizeAccent(localStorage.getItem('sentrix:accent')||'#4da3ff');
    reduced=localStorage.getItem('sentrix:reduce-motion')==='1';
    glow=localStorage.getItem('sentrix:glow')!=='0';
    density=localStorage.getItem('sentrix:density')||'comfortable';
    radius=localStorage.getItem('sentrix:radius')||'rounded';
    banner=localStorage.getItem('sentrix:banner')||'aurora';
  } catch (_) {}
  const allowedThemes=new Set(['sentrix','oled','midnight','graphite']);
  const allowedDensity=new Set(['comfortable','compact']);
  const allowedRadius=new Set(['rounded','soft','sharp']);
  const allowedBanner=new Set(['aurora','mesh','minimal']);
  if(!allowedThemes.has(theme)) theme='sentrix';
  const colors=readThemeColors(theme);
  const root=document.documentElement;
  root.dataset.theme=theme;
  root.dataset.glow=glow?'on':'off';
  root.dataset.density=allowedDensity.has(density)?density:'comfortable';
  root.dataset.radius=allowedRadius.has(radius)?radius:'rounded';
  root.dataset.banner=allowedBanner.has(banner)?banner:'aurora';
  for(const [key,,cssVar] of DASHBOARD_COLOR_FIELDS) root.style.setProperty(cssVar,colors[key]);
  root.style.setProperty('--green-bg',accentAlpha(colors.success,.16));
  root.style.setProperty('--amber-bg',accentAlpha(colors.warning,.16));
  root.style.setProperty('--red-bg',accentAlpha(colors.danger,.16));
  root.style.setProperty('--blue',accent);
  root.style.setProperty('--blue2',accentMix(accent,255,.30));
  root.style.setProperty('--blue-bg',accentAlpha(accent,.16));
  root.style.setProperty('--accent-glow',accentAlpha(accent,.22));
  root.style.setProperty('--accent-soft',accentAlpha(accent,.10));
  state.reduceMotion=reduced;
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
  let theme='sentrix',accent='#4da3ff',reduce=false,glow=true,density='comfortable',radius='rounded',banner='aurora';
  try {
    theme=localStorage.getItem('sentrix:theme')||'sentrix';
    accent=normalizeAccent(localStorage.getItem('sentrix:accent')||'#4da3ff');
    reduce=localStorage.getItem('sentrix:reduce-motion')==='1';
    glow=localStorage.getItem('sentrix:glow')!=='0';
    density=localStorage.getItem('sentrix:density')||'comfortable';
    radius=localStorage.getItem('sentrix:radius')||'rounded';
    banner=localStorage.getItem('sentrix:banner')||'aurora';
  } catch (_) {}
  let colors=readThemeColors(theme);
  const savedThemes=readSavedThemes();
  const palette=DASHBOARD_ACCENTS.map(([hex,label]) =>
    `<button class="accent-swatch ${accent===hex?'active':''}" type="button" data-accent="${hex}" title="${esc(label)}" aria-label="${esc(label)}" style="--swatch:${hex}"></button>`
  ).join('');
  const curatedPaletteHtml=Object.entries(DASHBOARD_CURATED_PALETTES).map(([key,preset]) => `
    <button class="theme-preset-card" type="button" data-curated-theme="${key}" style="--preset-bg:${preset.colors.bg};--preset-bg2:${preset.colors.bg2};--preset-panel:${preset.colors.panel};--preset-accent:${preset.accent}">
      <span class="theme-preset-art" aria-hidden="true"></span>
      <span class="theme-preset-copy"><b>${esc(preset.label)}</b><small>${esc(preset.note)}</small></span>
      <span class="theme-preset-apply">Appliquer</span>
    </button>`).join('');
  const colorControls=DASHBOARD_COLOR_FIELDS.map(([key,label]) => `
    <div class="theme-color-row" data-theme-color-row="${key}">
      <div class="theme-color-copy"><b>${esc(label)}</b><small>${esc(key)}</small></div>
      <input class="theme-color-picker" type="color" value="${colors[key]}" data-theme-color-picker="${key}" aria-label="${esc(label)}">
      <input class="theme-color-hex" value="${colors[key]}" maxlength="7" data-theme-color-hex="${key}" aria-label="${esc(label)} HEX">
    </div>`).join('');
  const savedHtml=savedThemes.length ? savedThemes.map(t => `
    <div class="saved-theme-row">
      <div class="saved-theme-preview" style="--t-bg:${esc(t.colors?.bg||'#0b0d10')};--t-panel:${esc(t.colors?.panel||'#15191f')};--t-accent:${esc(t.accent||'#4da3ff')}"></div>
      <div class="row-main"><b>${esc(t.name||'Thème')}</b><small>${esc(t.theme||'sentrix')} · ${esc(t.accent||'#4da3ff')}</small></div>
      <div class="row-actions"><button class="btn sm" type="button" data-load-theme="${esc(t.id)}">Charger</button><button class="btn sm danger" type="button" data-delete-theme="${esc(t.id)}">Supprimer</button></div>
    </div>`).join('') : '<div class="notice">Aucun thème personnalisé enregistré.</div>';

  content().innerHTML=`<div class="grid">
    <section class="card full">
      <div class="card-head">
        <div><h2>Personnalisation du dashboard</h2><p>Changez l’ambiance ou construisez votre propre palette complète. Tout est appliqué en direct sur ce navigateur.</p></div>
        <span class="badge blue">Aperçu en direct</span>
      </div>
      <div class="personalization-preview" id="personalizationPreview">
        <div class="personalization-preview-mark">S</div>
        <div class="row-main"><b>SentriX Dashboard</b><small>Fond, sidebar, cartes, textes, bordures, états et accent utilisent votre thème.</small></div>
        <button class="btn primary sm" type="button">Action</button>
      </div>
      <div class="fields">
        <div class="field">
          <label for="prefTheme">Preset</label>
          <select id="prefTheme">
            <option value="sentrix" ${theme==='sentrix'?'selected':''}>Sombre SentriX</option>
            <option value="oled" ${theme==='oled'?'selected':''}>OLED noir profond</option>
            <option value="midnight" ${theme==='midnight'?'selected':''}>Midnight bleu nuit</option>
            <option value="graphite" ${theme==='graphite'?'selected':''}>Graphite neutre</option>
          </select>
          <small>Choisir un preset remet les couleurs avancées sur sa palette d’origine.</small>
        </div>
        <div class="field">
          <label for="prefBanner">Décor du profil</label>
          <select id="prefBanner">
            <option value="aurora" ${banner==='aurora'?'selected':''}>Aurora</option>
            <option value="mesh" ${banner==='mesh'?'selected':''}>Mesh lumineux</option>
            <option value="minimal" ${banner==='minimal'?'selected':''}>Minimal</option>
          </select>
        </div>
        <div class="field full">
          <label>Accent / boutons principaux</label>
          <div class="accent-picker">
            <div class="accent-swatches">${palette}</div>
            <div class="accent-custom"><input id="prefAccentColor" type="color" value="${accent}"><input id="prefAccentHex" value="${accent}" maxlength="7" aria-label="Couleur principale HEX"></div>
          </div>
          <small>Choisissez une couleur proposée ou n’importe quelle couleur HEX.</small>
        </div>
      </div>
    </section>

    <section class="card full theme-palette-card">
      <div class="card-head">
        <div><h2>Palettes prêtes</h2><p>Des combinaisons déjà équilibrées : fond, cartes, textes, bordures et accent sont accordés automatiquement.</p></div>
        <span class="badge blue">Dégradés prêts</span>
      </div>
      <div class="theme-preset-grid">${curatedPaletteHtml}</div>
      <details class="advanced theme-advanced-editor">
        <summary><span>Éditeur de couleurs avancé</span><small>Pour modifier une couleur précise uniquement.</small></summary>
        <div class="advanced-body">
          <div class="toolbar"><button class="btn sm" id="prefResetColors" type="button">Revenir aux couleurs de base</button></div>
          <div class="theme-color-grid">${colorControls}</div>
          <div id="themeContrastStatus" class="notice"></div>
        </div>
      </details>
    </section>

    <section class="card">
      <h2>Interface</h2>
      <div class="field"><label for="prefDensity">Densité</label><select id="prefDensity"><option value="comfortable" ${density==='comfortable'?'selected':''}>Confortable</option><option value="compact" ${density==='compact'?'selected':''}>Compacte</option></select></div>
      <div class="field"><label for="prefRadius">Coins</label><select id="prefRadius"><option value="rounded" ${radius==='rounded'?'selected':''}>Arrondis</option><option value="soft" ${radius==='soft'?'selected':''}>Discrets</option><option value="sharp" ${radius==='sharp'?'selected':''}>Carrés</option></select></div>
      <label class="switch-row"><span class="switch-copy"><b>Effets lumineux</b><span>Halo d’accent et profondeur.</span></span><input class="switch" id="prefGlow" type="checkbox" ${glow?'checked':''}></label>
    </section>

    <section class="card">
      <h2>Animations</h2>
      <label class="switch-row"><span class="switch-copy"><b>Réduire les animations</b><span>Désactive les transitions de page non essentielles.</span></span><input class="switch" id="prefReduceMotion" type="checkbox" ${reduce?'checked':''}></label>
      <div class="notice">Aucune animation périodique : les effets ne se déclenchent que lorsque vous naviguez.</div>
    </section>

    <section class="card full">
      <div class="card-head"><div><h2>Mes thèmes</h2><p>Enregistrez plusieurs palettes et rechargez-les quand vous voulez.</p></div></div>
      <div class="theme-save-row"><input id="themeSaveName" class="input" maxlength="32" placeholder="Ex. Red OLED"><button class="btn primary" id="themeSaveButton" type="button">Enregistrer le thème actuel</button></div>
      <div class="saved-theme-list" id="savedThemeList">${savedHtml}</div>
    </section>

    <section class="card">
      <h2>Navigation</h2>
      <label class="switch-row"><span class="switch-copy"><b>Garder “Plus d’outils” ouvert</b><span>Uniquement dans la configuration d’un serveur.</span></span><input class="switch" id="prefMoreTools" type="checkbox" ${state.navMore?'checked':''}></label>
    </section>

    <section class="card">
      <h2>Réinitialiser</h2><p>Revient au style SentriX d’origine sans toucher à votre compte ni à vos serveurs.</p>
      <div class="toolbar"><button class="btn danger" type="button" id="prefReset">Réinitialiser toute l’apparence</button></div>
    </section>
  </div>`;

  const save=(key,value)=>{try{localStorage.setItem(key,value);}catch(_){} applyGlobalPreferences();};
  const refreshContrast=()=>{
    colors=readThemeColors((()=>{try{return localStorage.getItem('sentrix:theme')||'sentrix';}catch(_){return 'sentrix';}})());
    const status=contrastStatus(colors),el=$('themeContrastStatus');
    if(status.ok){el.className='notice ok';el.textContent='Contraste lisible : texte principal et secondaire restent suffisamment visibles.';}
    else {el.className='notice warn';el.textContent='Contraste faible : '+status.bad.map(x=>x[0]).join(', ')+'. Ajustez les couleurs avant d’enregistrer ce thème.';}
  };
  const setAccent=value=>{
    const next=normalizeAccent(value);save('sentrix:accent',next);$('prefAccentColor').value=next;$('prefAccentHex').value=next;
    content().querySelectorAll('[data-accent]').forEach(b=>b.classList.toggle('active',b.dataset.accent===next));
  };
  const setThemeColor=(key,value)=>{
    const field=DASHBOARD_COLOR_FIELDS.find(([k])=>k===key);if(!field)return;
    const next=normalizeHex(value,readThemeColors(theme)[key]);colors=readThemeColors(theme);colors[key]=next;writeThemeColors(colors);applyGlobalPreferences();
    const pick=content().querySelector(`[data-theme-color-picker="${key}"]`),hex=content().querySelector(`[data-theme-color-hex="${key}"]`);
    if(pick)pick.value=next;if(hex)hex.value=next;refreshContrast();
  };

  content().querySelectorAll('[data-curated-theme]').forEach(b=>b.onclick=()=>{
    const preset=DASHBOARD_CURATED_PALETTES[b.dataset.curatedTheme];if(!preset)return;
    try{
      localStorage.setItem('sentrix:theme',preset.theme);
      localStorage.setItem('sentrix:accent',preset.accent);
      localStorage.setItem('sentrix:theme-colors',JSON.stringify(preset.colors));
      localStorage.setItem('sentrix:glow','1');
      localStorage.setItem('sentrix:banner','aurora');
    }catch(_){}
    applyGlobalPreferences();renderPreferences();toast(preset.label+' appliqué.');
  });
  $('prefTheme').onchange=()=>{theme=$('prefTheme').value;try{localStorage.setItem('sentrix:theme',theme);localStorage.removeItem('sentrix:theme-colors');}catch(_){}applyGlobalPreferences();renderPreferences();toast('Preset appliqué.');};
  $('prefBanner').onchange=()=>{save('sentrix:banner',$('prefBanner').value);toast('Décor appliqué.');};
  $('prefDensity').onchange=()=>{save('sentrix:density',$('prefDensity').value);toast('Densité appliquée.');};
  $('prefRadius').onchange=()=>{save('sentrix:radius',$('prefRadius').value);toast('Style des coins appliqué.');};
  $('prefGlow').onchange=()=>save('sentrix:glow',$('prefGlow').checked?'1':'0');
  $('prefReduceMotion').onchange=()=>{save('sentrix:reduce-motion',$('prefReduceMotion').checked?'1':'0');toast('Préférence d’animation enregistrée.');};
  $('prefAccentColor').oninput=()=>setAccent($('prefAccentColor').value);
  $('prefAccentHex').onchange=()=>{const raw=String($('prefAccentHex').value||'').trim();if(!/^#[0-9a-f]{6}$/i.test(raw)){ $('prefAccentHex').value=accent;return toast('Couleur HEX invalide.',true);}setAccent(raw);};
  content().querySelectorAll('[data-accent]').forEach(b=>b.onclick=()=>setAccent(b.dataset.accent));
  content().querySelectorAll('[data-theme-color-picker]').forEach(el=>el.oninput=()=>setThemeColor(el.dataset.themeColorPicker,el.value));
  content().querySelectorAll('[data-theme-color-hex]').forEach(el=>el.onchange=()=>{const raw=String(el.value||'').trim();if(!/^#[0-9a-f]{6}$/i.test(raw)){const now=readThemeColors(theme)[el.dataset.themeColorHex];el.value=now;return toast('Couleur HEX invalide.',true);}setThemeColor(el.dataset.themeColorHex,raw);});
  $('prefResetColors').onclick=()=>{try{localStorage.removeItem('sentrix:theme-colors');}catch(_){}applyGlobalPreferences();renderPreferences();toast('Couleurs du preset restaurées.');};
  $('themeSaveButton').onclick=()=>{
    const name=String($('themeSaveName').value||'').trim();if(!name)return toast('Donnez un nom au thème.',true);
    const snapshot=captureThemeSnapshot(name),status=contrastStatus(snapshot.colors);
    if(!status.ok)return toast('Contraste trop faible : corrigez les couleurs signalées avant d’enregistrer.',true);
    const items=readSavedThemes().filter(x=>String(x.name).toLowerCase()!==name.toLowerCase());items.unshift(snapshot);writeSavedThemes(items);renderPreferences();toast('Thème enregistré.');
  };
  content().querySelectorAll('[data-load-theme]').forEach(b=>b.onclick=()=>{const t=readSavedThemes().find(x=>String(x.id)===String(b.dataset.loadTheme));if(!t)return;applyThemeSnapshot(t);renderPreferences();toast('Thème chargé.');});
  content().querySelectorAll('[data-delete-theme]').forEach(b=>b.onclick=async()=>{const t=readSavedThemes().find(x=>String(x.id)===String(b.dataset.deleteTheme));if(!t)return;if(!(await confirmDialog({title:'Supprimer ce thème ?',body:t.name||'Thème personnalisé',confirm:'Supprimer',danger:true})))return;writeSavedThemes(readSavedThemes().filter(x=>String(x.id)!==String(b.dataset.deleteTheme)));renderPreferences();toast('Thème supprimé.');});
  $('prefMoreTools').onchange=()=>{state.navMore=$('prefMoreTools').checked;try{localStorage.setItem('sentrix:nav:more',state.navMore?'1':'0');}catch(_){}renderNav();};
  $('prefReset').onclick=async()=>{if(!(await confirmDialog({title:'Réinitialiser toute l’apparence ?',body:'Les couleurs, thèmes, effets et préférences locales reviendront aux valeurs SentriX. Vos thèmes enregistrés resteront disponibles.',confirm:'Réinitialiser',danger:true})))return;
    for(const key of ['sentrix:theme','sentrix:accent','sentrix:theme-colors','sentrix:glow','sentrix:density','sentrix:radius','sentrix:banner','sentrix:reduce-motion']){try{localStorage.removeItem(key);}catch(_){}}
    applyGlobalPreferences();renderPreferences();toast('Apparence réinitialisée.');
  };
  refreshContrast();
}



/* Premium global home enhancement */
const _renderProfileSentrixBase = renderProfile;
renderProfile = function renderProfilePremium() {
  _renderProfileSentrixBase();
  const home = content().querySelector('.global-home');
  const hero = home?.querySelector('.global-hero');
  if (!home || !hero || home.querySelector('.global-quick-hub')) return;

  let theme='sentrix',accent='#4da3ff',density='comfortable';
  try {
    theme=localStorage.getItem('sentrix:theme')||'sentrix';
    accent=normalizeAccent(localStorage.getItem('sentrix:accent')||'#4da3ff');
    density=localStorage.getItem('sentrix:density')||'comfortable';
  } catch (_) {}
  const names={sentrix:'Sombre SentriX',oled:'OLED',midnight:'Midnight',graphite:'Graphite'};
  const lastId=(()=>{try{return localStorage.getItem('sentrix:guild')||'';}catch(_){return '';}})();
  const last=state.guilds.find(g=>g.installed&&String(g.id)===String(lastId));
  const hub=document.createElement('section');
  hub.className='global-quick-hub';
  hub.innerHTML=`
    <article class="global-quick-card accent">
      <div class="global-quick-icon" style="--quick-accent:${esc(accent)}">S</div>
      <div><span class="eyebrow">Apparence</span><h3>${esc(names[theme]||'SentriX')}</h3><p>${esc(accent)} · ${density==='compact'?'compacte':'confortable'}</p></div>
      <button class="btn sm" type="button" data-go="preferences">Personnaliser</button>
    </article>
    <article class="global-quick-card">
      <div class="global-quick-icon">#</div>
      <div><span class="eyebrow">Dernier espace</span><h3>${esc(last?.name||'Aucun serveur récent')}</h3><p>${last?'Reprendre votre configuration.':'Choisissez un serveur pour commencer.'}</p></div>
      ${last? `<button class="btn sm primary" type="button" data-global-guild="${esc(last.id)}">Continuer</button>` : '<button class="btn sm primary" type="button" data-go="servers">Choisir</button>'}
    </article>
    <article class="global-quick-card">
      <div class="global-quick-icon">⌘</div>
      <div><span class="eyebrow">Recherche</span><h3>Commande rapide</h3><p>Une fois dans un serveur, utilisez ⌘K pour trouver tickets, anti-spam, Compteur Infini…</p></div>
      <button class="btn sm" type="button" data-go="servers">Mes serveurs</button>
    </article>`;
  hero.insertAdjacentElement('afterend',hub);
  bindGlobalServerCards(hub);
  hub.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>go(b.dataset.go,b.dataset.goSub||''));
};
