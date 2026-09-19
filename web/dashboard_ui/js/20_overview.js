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
  ['antispam', 'Anti-spam', 'Bloque les rafales de messages.'], ['antilink', 'Anti-liens', 'Supprime les liens non autorisés.'], ['antiinvite', 'Anti-invitations', 'Filtre les invitations Discord.'],
  ['antimention', 'Anti-mentions', 'Limite les mentions de masse.'], ['anticaps', 'Anti-majuscules', 'Réduit les messages tout en majuscules.'], ['antiemoji', 'Anti-emoji', 'Limite les répétitions d’emoji.'],
  ['antiraid', 'Anti-raid', 'Réagit aux arrivées anormales.'], ['antibot', 'Anti-bot', 'Contrôle les ajouts de bots.'], ['antiaccount', 'Anti-comptes récents', 'Détecte les comptes trop récents.'],
  ['antiscam', 'Anti-scam', 'Filtre les contenus à risque.'], ['antinuke', 'Anti-nuke', 'Protège salons et rôles.'], ['antiinsult', 'Anti-insultes', 'Filtre les insultes (timeout 10 min).'],
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
function moduleCard({ key, title, page, info }, m) {
  const code = moduleStatus(m);
  const sw = MODULE_SWITCH[key];
  const off = code === 'missing' || code === 'inactive';
  const toggle = sw ? (off ? `<button class="btn sm" type="button" data-module="${sw}" data-action="enable">Activer</button>` : `<button class="btn sm ghost" type="button" data-module="${sw}" data-action="disable">Désactiver</button>`) : '';
  let line = ''; try { line = info(m) || ''; } catch (_) {}
  return `<article class="module-card"><div class="card-head"><h3>${esc(title)}</h3>${badge(code)}</div><p class="info">${esc(line)}</p><div class="toolbar"><button class="btn sm primary" type="button" data-go="${page}">${off ? 'Configurer' : 'Gérer'}</button>${toggle}</div></article>`;
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

async function renderOverview() {
  const d = await diagnostics();
  const mods = d.modules || {};
  const configured = Object.values(mods).some(m => m.configured || m.code === 'active');
  const cards = OVERVIEW_CARDS.map(c => moduleCard(c, mods[c.key])).join('');
  const onboarding = !configured ? `<section class="card full"><div class="card-head"><div><h2>Bienvenue dans SentriX</h2><p>Configurez les fonctions principales de votre serveur en quelques étapes. Rien n’est modifié avant la dernière étape.</p></div><button class="btn primary" type="button" id="startWizard">Commencer</button></div></section>` : '';
  const problems = (d.invalid_resources || []).length;
  content().innerHTML = `<div class="grid">${onboarding}${problems ? `<div class="notice warn full">${plural(problems, 'ressource', 'ressources')} à corriger (salon ou rôle supprimé). <button class="btn link" type="button" data-go="diagnostic">Voir</button></div>` : ''}<div class="module-grid full">${cards}</div></div>`;
  bindModuleButtons();
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
