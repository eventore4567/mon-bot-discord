/* ---------- Centre de modération : sanctions réelles + dossier membre ----------
   Le backend appelle services.moderation ; aucune sanction fictive ni duplication du moteur. */
SUBS.security = [['protections', 'Protections'], ['verification', 'Vérification'], ['sanctions', 'Centre de modération']];

const moderationSearch = q => gget('/moderation/members?q=' + encodeURIComponent(q));
const moderationMember = id => gget('/moderation/members/' + encodeURIComponent(id));

function moderationActionLabel(action) {
  return ({ warn: 'Avertir', mute: 'Mute', kick: 'Expulser', ban: 'Bannir' })[action] || action;
}
function moderationActionClass(action) {
  return action === 'ban' || action === 'kick' ? 'danger' : action === 'mute' ? 'primary' : '';
}

async function openModerationAction(member, action) {
  const label = moderationActionLabel(action);
  const destructive = action === 'ban' || action === 'kick';
  openModal({
    title: `${label} — ${member.display_name || member.username || member.id}`,
    body: `<div class="fields">
      ${action === 'mute' ? '<div class="field"><label for="modDuration">Durée</label><input id="modDuration" value="10m" placeholder="10m, 1h, 1j"><small>Maximum Discord : 28 jours.</small></div>' : ''}
      <div class="field full"><label for="modReason">Raison</label><textarea id="modReason" maxlength="500" rows="5" placeholder="Raison obligatoire"></textarea></div>
    </div>
    <div class="notice ${destructive ? 'warn' : ''}" style="margin-top:10px">Cette action sera appliquée réellement sur Discord et enregistrée dans l’historique SentriX.</div>`,
    actions: [
      { label: 'Annuler' },
      { label, kind: destructive ? 'danger' : 'primary', keep: true, onClick: async () => {
        const reason = $('modReason').value.trim();
        if (!reason) return toast('Indiquez une raison.', true);
        const payload = { action, user_id: member.id, reason };
        if (action === 'mute') payload.duration = $('modDuration').value.trim() || '10m';
        try {
          const r = await gpost('/moderation/actions', payload);
          closeModal();
          toast(r.message || `${label} appliqué.`);
          invalidate('diagnostics');
          await renderSanctions();
        } catch (e) { toast(e.message, true); }
      } },
    ],
  });
}

renderSanctions = async function renderModerationCenter() {
  let history;
  try { history = await gget('/sanctions?limit=50'); } catch (e) { return errorView(e); }
  const rows = history.sanctions || [];
  const selectedId = state.moderationMemberId || null;

  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head">
        <div><h2>Centre de modération</h2><p>Recherchez un membre, consultez son dossier puis appliquez une action réelle avec confirmation.</p></div>
        <div class="toolbar"><button class="btn ghost" type="button" data-go="dm">Envoyer un message privé</button><span class="badge blue">${plural(Number(history.total ?? rows.length), 'sanction')}</span></div>
      </div>
      <div class="field full" style="margin-top:12px">
        <label for="moderationSearch">Rechercher un membre</label>
        <input class="search-input" id="moderationSearch" type="search" autocomplete="off" placeholder="Pseudo, nom affiché ou ID Discord">
        <small>La recherche utilise les membres actuellement présents sur le serveur.</small>
      </div>
      <div class="options hidden" id="moderationResults" style="margin-top:8px"></div>
    </section>

    <section class="card full" id="moderationMemberCard">
      ${selectedId ? '<div class="skeleton" style="min-height:180px"></div>' : emptyState('Aucun membre sélectionné', 'Recherchez un membre ci-dessus pour ouvrir son dossier et afficher les actions disponibles.')}
    </section>

    <section class="card full">
      <div class="card-head">
        <div><h2>Historique récent</h2><p>Les dernières sanctions enregistrées par SentriX sur ce serveur.</p></div>
        <div class="toolbar">
          <input class="search-input" id="historySearch" type="search" placeholder="Filtrer l’historique…">
          <select class="search-input" id="historyAction">
            <option value="">Toutes les actions</option>
            ${['warn','mute','kick','ban','unmute','unban','tempban'].map(x => `<option value="${x}">${x}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="list" id="sanctionList"></div>
    </section>
  </div>`;

  const renderHistory = () => {
    const q = $('historySearch').value.trim().toLowerCase();
    const action = $('historyAction').value;
    const items = rows.filter(x => {
      if (action && String(x.action || '') !== action) return false;
      if (!q) return true;
      return JSON.stringify(x).toLowerCase().includes(q);
    });
    $('sanctionList').innerHTML = items.length ? items.map(x => {
      const member = x.user || {};
      const moderator = x.moderator || {};
      const who = member.display_name || member.username || x.user_id || 'Utilisateur';
      const mod = moderator.display_name || moderator.username || x.moderator_id || 'Inconnu';
      const caseNo = x.case_number ? `Dossier #${x.case_number} · ` : '';
      const active = x.current_banned ? 'Banni actuellement' : x.current_muted ? 'Mute actuellement' : '';
      return `<div class="row">
        <div class="row-main">
          <b>${esc(caseNo + String(x.action || 'action'))} · ${esc(who)}</b>
          <small>${esc(x.reason || 'Aucune raison')}${x.created_at ? ' · ' + esc(when(x.created_at)) : ''} · par ${esc(mod)}${active ? ' · ' + esc(active) : ''}</small>
        </div>
        <div class="row-actions">
          ${x.current_banned ? `<button class="btn sm" type="button" data-reverse-sanction="unban" data-reverse-user="${esc(x.user_id)}">Débannir</button>` : ''}
          ${x.current_muted ? `<button class="btn sm" type="button" data-reverse-sanction="unmute" data-reverse-user="${esc(x.user_id)}">Lever le mute</button>` : ''}
          ${Number(x.warn_count || 0) > 0 ? `<button class="btn sm" type="button" data-reverse-sanction="clear-warnings" data-reverse-user="${esc(x.user_id)}">Effacer warns</button>` : ''}
          <button class="btn sm" type="button" data-open-member="${esc(x.user_id)}">Dossier</button>
        </div>
      </div>`;
    }).join('') : emptyState('Aucune sanction trouvée', 'Modifiez les filtres pour afficher d’autres résultats.');
    $('sanctionList').querySelectorAll('[data-open-member]').forEach(b => b.onclick = async () => {
      state.moderationMemberId = b.dataset.openMember;
      await paintMember();
      $('moderationMemberCard').scrollIntoView({ behavior: REDUCED_MOTION() ? 'auto' : 'smooth', block: 'start' });
    });
    $('sanctionList').querySelectorAll('[data-reverse-sanction]').forEach(b => b.onclick = async () => {
      const label = b.textContent;
      const reason = await promptDialog({ title: label, label: 'Raison', value: 'Action depuis le dashboard SentriX', confirm: label });
      if (!reason) return;
      try {
        const r = await gpost(`/sanctions/${encodeURIComponent(b.dataset.reverseUser)}/${encodeURIComponent(b.dataset.reverseSanction)}`, { reason });
        toast(r.message || 'Action appliquée.');
        await renderSanctions();
      } catch (e) { toast(e.message, true); }
    });
  };
  $('historySearch').oninput = renderHistory;
  $('historyAction').onchange = renderHistory;
  renderHistory();

  let timer = null;
  $('moderationSearch').oninput = () => {
    clearTimeout(timer);
    const q = $('moderationSearch').value.trim();
    if (!q) { $('moderationResults').classList.add('hidden'); $('moderationResults').innerHTML = ''; return; }
    timer = setTimeout(async () => {
      let result;
      try { result = await moderationSearch(q); } catch (e) { return toast(e.message, true); }
      const members = result.members || [];
      $('moderationResults').innerHTML = members.length ? members.map(m => `<button type="button" data-mod-member="${esc(m.id)}">
        <span class="avatar">${m.avatar_url ? `<img src="${esc(m.avatar_url)}" alt="">` : esc((m.display_name || m.username || '?').slice(0,2).toUpperCase())}</span>
        <span class="row-main"><b>${esc(m.display_name || m.username)}</b><small>@${esc(m.username)} · ${esc(m.id)}${m.bot ? ' · bot' : ''}</small></span>
      </button>`).join('') : '<div class="empty">Aucun membre trouvé.</div>';
      $('moderationResults').classList.remove('hidden');
      $('moderationResults').querySelectorAll('[data-mod-member]').forEach(b => b.onclick = async () => {
        state.moderationMemberId = b.dataset.modMember;
        $('moderationResults').classList.add('hidden');
        $('moderationSearch').value = '';
        await paintMember();
      });
    }, 180);
  };

  async function paintMember() {
    const id = state.moderationMemberId;
    if (!id) return;
    const holder = $('moderationMemberCard');
    holder.innerHTML = '<div class="skeleton" style="min-height:180px"></div>';
    let d;
    try { d = await moderationMember(id); } catch (e) {
      state.moderationMemberId = null;
      holder.innerHTML = emptyState('Membre introuvable', e.message || 'Le membre n’est plus présent sur le serveur.');
      return;
    }
    const m = d.member || {};
    const timeout = d.timed_out_until ? new Date(d.timed_out_until) : null;
    const muted = timeout && timeout.getTime() > Date.now();
    holder.innerHTML = `<div class="card-head">
      <div class="profile-line">
        <span class="avatar big">${m.avatar_url ? `<img src="${esc(m.avatar_url)}" alt="">` : esc((m.display_name || m.username || '?').slice(0,2).toUpperCase())}</span>
        <div><h2>${esc(m.display_name || m.username || m.id)}</h2><p>@${esc(m.username || '')} · ${esc(m.id || '')}</p></div>
      </div>
      <button class="btn ghost" type="button" id="closeModerationMember">Fermer le dossier</button>
    </div>
    <div class="kpis" style="margin-top:14px">
      <div class="kpi"><small>Avertissements</small><b>${number(d.warnings || 0)}</b></div>
      <div class="kpi"><small>Sanctions</small><b>${number(d.sanctions || 0)}</b></div>
      <div class="kpi"><small>État</small><b>${d.currently_banned ? 'Banni' : muted ? 'Mute' : m.present === false ? 'Hors serveur' : 'Actif'}</b></div>
      <div class="kpi"><small>Rôles</small><b>${number((m.roles || []).length)}</b></div>
    </div>
    <div class="toolbar" style="margin-top:14px">
      ${m.bot ? '<span class="notice warn">Les bots ne peuvent pas être sanctionnés depuis ce centre.</span>' : m.present === false ? (d.currently_banned ? '<button class="btn primary" type="button" data-member-reverse="unban">Débannir</button>' : '<span class="notice">Ce membre n’est plus présent sur le serveur.</span>') : ['warn','mute','kick','ban'].map(a => `<button class="btn ${moderationActionClass(a)}" type="button" data-mod-action="${a}">${moderationActionLabel(a)}</button>`).join('')}
      ${muted ? '<button class="btn" type="button" data-member-reverse="unmute">Lever le mute</button>' : ''}
      ${Number(d.warnings || 0) > 0 ? '<button class="btn" type="button" data-member-reverse="clear-warnings">Effacer les avertissements</button>' : ''}
    </div>
    <div style="margin-top:16px">
      <h3>Dernières sanctions de ce membre</h3>
      <div class="list compact" style="margin-top:8px">
        ${(d.recent || []).length ? d.recent.map(x => `<div class="row"><div class="row-main"><b>${esc((x.case_number ? 'Dossier #' + x.case_number + ' · ' : '') + (x.action || 'action'))}</b><small>${esc(x.reason || 'Aucune raison')}${x.created_at ? ' · ' + esc(when(x.created_at)) : ''}</small></div></div>`).join('') : '<p class="info">Aucune sanction enregistrée.</p>'}
      </div>
    </div>`;
    $('closeModerationMember').onclick = () => {
      state.moderationMemberId = null;
      holder.innerHTML = emptyState('Aucun membre sélectionné', 'Recherchez un membre ci-dessus pour ouvrir son dossier et afficher les actions disponibles.');
    };
    holder.querySelectorAll('[data-mod-action]').forEach(b => b.onclick = () => openModerationAction(m, b.dataset.modAction));
    holder.querySelectorAll('[data-member-reverse]').forEach(b => b.onclick = async () => {
      const label = b.textContent;
      const reason = await promptDialog({ title: label, label: 'Raison', value: 'Action depuis le dashboard SentriX', confirm: label });
      if (!reason) return;
      try {
        const r = await gpost(`/sanctions/${encodeURIComponent(m.id)}/${encodeURIComponent(b.dataset.memberReverse)}`, { reason });
        toast(r.message || 'Action appliquée.');
        await renderSanctions();
      } catch (e) { toast(e.message, true); }
    });
  }

  if (selectedId) await paintMember();
};


/* ---------- Expérience premium SentriX ----------
   Couche UX progressive : elle résume, guide et accélère les pages existantes sans
   créer de nouvelle source de vérité. Les écritures passent toujours par les APIs
   déjà utilisées par SentriX. */
const EXPERIENCE_META = {
  overview: ['Centre de contrôle', 'Santé, modules et raccourcis du serveur.'],
  welcome: ['Accueil des membres', 'Bienvenue, départs et aperçu Discord.'],
  levels: ['Progression', 'XP, annonces et récompenses de rôles.'],
  economy: ['Économie', 'Monnaie, boutique, jeux et gains.'],
  roles: ['Rôles', 'Autorôle, rôles interactifs et progression.'],
  moderation: ['Modération', 'Dossiers membres et sanctions réelles.'],
  security: ['Sécurité', 'Protections automatiques et vérification.'],
  logs: ['Logs', 'Routage précis et événements enregistrés.'],
  tickets: ['Tickets', 'Panneaux, types, actions staff et publication.'],
  games: ['Jeux', 'Compteur Infini, mini-jeux et règles d’accès.'],
  notifications: ['Notifications', 'Sources sociales et annonces automatiques.'],
  automation: ['Automatisation', 'Réactions, Starboard, sticky, planning et VoiceHub.'],
  embeds: ['Embeds', 'Composer, prévisualiser et publier dans Discord.'],
  ai: ['IA', 'Modèle, limites et mémoire de conversation.'],
};

const EXPERIENCE_QUICK = {
  overview: [['welcome','Accueil'],['security','Sécurité'],['tickets','Tickets'],['logs','Logs']],
  levels: [['levels','Général','general'],['levels','Récompenses','roles'],['roles','Rôles','niveau']],
  economy: [['economy','Boutique','boutique'],['economy','Jeux','jeux'],['economy','Gains','gains']],
  moderation: [['security','Sécurité','protections'],['logs','Logs'],['tickets','Tickets']],
  security: [['moderation','Centre de modération'],['logs','Logs'],['security','Vérification','verification']],
  logs: [['moderation','Modération'],['tickets','Tickets'],['diagnostic','Diagnostic']],
  tickets: [['roles','Rôles'],['logs','Logs'],['moderation','Modération']],
  games: [['games','Compteur Infini','infinite'],['economy','Économie','jeux'],['automation','Automatisation']],
  automation: [['notifications','Notifications'],['games','Jeux'],['advanced','Centre avancé','automations']],
  roles: [['levels','Niveaux','roles'],['security','Vérification','verification'],['welcome','Accueil']],
  embeds: [['welcome','Accueil'],['notifications','Notifications'],['tickets','Tickets']],
};

function experienceHealth(code) {
  const cls = code === 'active' ? 'ok' : code === 'error' ? 'bad' : code === 'partial' ? 'warn' : '';
  const label = code === 'active' ? 'Actif' : code === 'error' ? 'Erreur' : code === 'partial' ? 'À compléter' : 'Désactivé';
  return '<span class="badge ' + cls + '">' + esc(label) + '</span>';
}

function experienceModuleForPage(page) {
  const key = NAV_MODULE[page];
  if (!key || !state.guildId) return null;
  return state.cache.get(state.guildId + ':diagnostics')?.value?.modules?.[key] || null;
}

function experienceCommandBar() {
  const meta = EXPERIENCE_META[state.page] || pageMeta(state.page);
  const module = experienceModuleForPage(state.page);
  const quick = EXPERIENCE_QUICK[state.page] || [];
  return `<section class="experience-command full">
    <div class="experience-command-main">
      <div class="experience-breadcrumb">
        <button type="button" class="crumb" data-go="overview">${esc(state.guild?.guild?.name || 'Serveur')}</button>
        <span>/</span><strong>${esc(meta[0])}</strong>
      </div>
      <p>${esc(meta[1] || '')}</p>
    </div>
    <div class="experience-command-actions">
      ${module ? experienceHealth(moduleStatus(module)) : ''}
      ${quick.slice(0,4).map(([page,label,sub]) => `<button class="btn sm ghost" type="button" data-go="${esc(page)}" ${sub ? `data-go-sub="${esc(sub)}"` : ''}>${esc(label)}</button>`).join('')}
      <button class="btn sm" type="button" data-experience-search>Filtrer la page</button>
    </div>
  </section>`;
}

function experienceSummary(title, copy, stats, actions = []) {
  return `<section class="experience-summary full">
    <div class="experience-summary-copy">
      <span class="eyebrow">SentriX Control</span>
      <h2>${esc(title)}</h2>
      <p>${esc(copy || '')}</p>
      ${actions.length ? `<div class="toolbar">${actions.map(a => `<button class="btn ${a.primary ? 'primary' : ''}" type="button" data-go="${esc(a.page)}" ${a.sub ? `data-go-sub="${esc(a.sub)}"` : ''}>${esc(a.label)}</button>`).join('')}</div>` : ''}
    </div>
    <div class="experience-stat-grid">
      ${stats.map(s => `<div class="experience-stat"><small>${esc(s.label)}</small><strong>${esc(s.value)}</strong>${s.note ? `<span>${esc(s.note)}</span>` : ''}</div>`).join('')}
    </div>
  </section>`;
}

function experienceInsertAfterCommand(html) {
  const grid = content().querySelector('.grid');
  if (!grid) return;
  const command = grid.querySelector('.experience-command');
  if (command) command.insertAdjacentHTML('afterend', html);
  else grid.insertAdjacentHTML('afterbegin', html);
}

function bindExperienceFilter() {
  const trigger = content().querySelector('[data-experience-search]');
  if (!trigger) return;
  trigger.onclick = () => {
    if ($('experienceFilter')) { $('experienceFilter').focus(); return; }
    const bar = content().querySelector('.experience-command');
    const wrap = document.createElement('div');
    wrap.className = 'experience-filter';
    wrap.innerHTML = '<input id="experienceFilter" class="search-input" type="search" placeholder="Rechercher dans cette page…" autocomplete="off"><small id="experienceFilterCount"></small><button class="btn sm ghost" type="button" id="experienceFilterClose">Fermer</button>';
    bar.insertAdjacentElement('afterend', wrap);
    const targets = [...content().querySelectorAll('.card, .module-card, .row')].filter(x => !x.closest('.experience-command') && !x.closest('.experience-summary'));
    const apply = () => {
      const q = $('experienceFilter').value.trim().toLocaleLowerCase('fr');
      let visible = 0;
      for (const el of targets) {
        const hit = !q || el.textContent.toLocaleLowerCase('fr').includes(q);
        el.classList.toggle('experience-filtered', !hit);
        if (hit) visible += 1;
      }
      $('experienceFilterCount').textContent = q ? visible + ' résultat' + (visible > 1 ? 's' : '') : '';
    };
    $('experienceFilter').oninput = apply;
    $('experienceFilterClose').onclick = () => {
      for (const el of targets) el.classList.remove('experience-filtered');
      wrap.remove();
    };
    $('experienceFilter').focus();
  };
}

async function enhanceOverviewExperience() {
  let d; try { d = await diagnostics(); } catch (_) { return; }
  const mods = d.modules || {};
  const active = Object.values(mods).filter(m => m?.code === 'active').length;
  const errors = Object.values(mods).filter(m => m?.code === 'error').length;
  const partial = Object.values(mods).filter(m => m?.code === 'partial' || (m?.code === 'active' && m?.configured === false)).length;
  const invalid = (d.invalid_resources || []).length;
  const g = state.guild?.guild || {};
  experienceInsertAfterCommand(experienceSummary(
    g.name || 'Votre serveur',
    'Vue instantanée de la configuration réelle du serveur.',
    [
      { label:'Membres', value:number(g.members || 0), note:plural(g.channels_count || 0, 'salon') },
      { label:'Modules actifs', value:number(active), note:partial + ' à compléter' },
      { label:'Problèmes', value:number(errors + invalid), note:invalid ? invalid + ' ressource(s) cassée(s)' : 'aucune ressource cassée' },
      { label:'Santé', value:Number(d.score || 0) + ' %', note:errors ? errors + ' erreur(s)' : 'stable' },
    ],
    [
      { page:'welcome', label:'Configurer l’accueil', primary:true },
      { page:'security', label:'Sécuriser' },
      { page:'tickets', label:'Tickets' },
    ]
  ));
  const problems = [];
  for (const [key, mod] of Object.entries(mods)) {
    const code = moduleStatus(mod);
    if (code === 'error' || code === 'partial') {
      const ref = OVERVIEW_CARDS.find(x => x.key === key);
      problems.push({ page:ref?.page || 'diagnostic', label:ref?.title || key, detail:mod?.detail || 'Configuration à compléter.', code });
    }
  }
  for (const item of (d.invalid_resources || []).slice(0,5)) problems.push({ page:'diagnostic', label:item.field || item.type || 'Ressource', detail:item.reason || 'Ressource inaccessible.', code:'error' });
  if (problems.length) {
    const grid = content().querySelector('.grid');
    const section = document.createElement('section');
    section.className = 'card full experience-attention';
    section.innerHTML = `<div class="card-head"><div><h2>À corriger en priorité</h2><p>Les points qui peuvent réellement bloquer SentriX.</p></div><span class="badge warn">${number(problems.length)}</span></div><div class="list">${problems.slice(0,8).map(x => `<div class="row"><div class="row-main"><b>${esc(x.label)}</b><small>${esc(x.detail)}</small></div><div class="row-actions">${experienceHealth(x.code)}<button class="btn sm" type="button" data-go="${esc(x.page)}">Ouvrir</button></div></div>`).join('')}</div>`;
    const modules = grid.querySelector('.module-grid');
    if (modules) modules.insertAdjacentElement('beforebegin', section); else grid.appendChild(section);
  }
}

async function enhanceLevelsExperience() {
  let lv; try { lv = await levelsData(); } catch (_) { return; }
  const min = Number(lv.xp_min ?? 10), max = Number(lv.xp_max ?? 25), cd = Number(lv.xp_cooldown ?? 60);
  const avg = Math.round((min + max) / 2 * 10) / 10;
  experienceInsertAfterCommand(experienceSummary(
    'Progression des membres',
    'Réglages XP réels et récompenses branchés sur le moteur de niveaux.',
    [
      { label:'XP moyen', value:String(avg), note:'par gain' },
      { label:'Délai', value:cd ? cd + ' s' : 'aucun', note:'entre deux gains' },
      { label:'Récompenses', value:number((lv.roles || []).length), note:'rôle(s)' },
      { label:'Annonces', value:lv.level_announce_enabled ? 'Actives' : 'Coupées', note:state.guild?.settings?.level_channel ? (channelName(state.guild.settings.level_channel) || 'salon') : 'salon courant' },
    ]
  ));
  if (state.sub === 'general' && !$('xpSimulator')) {
    const grid = content().querySelector('.grid'); if (!grid) return;
    const sim = document.createElement('section'); sim.className='card full'; sim.id='xpSimulator';
    sim.innerHTML = '<div class="card-head"><div><h2>Simulateur de progression</h2><p>Estimation locale, sans modifier la configuration.</p></div></div><div class="fields"><div class="field"><label for="xpSimMessages">Messages valides par jour</label><input id="xpSimMessages" type="number" min="1" max="5000" value="80"></div><div class="field"><label for="xpSimDays">Période (jours)</label><input id="xpSimDays" type="number" min="1" max="365" value="7"></div></div><div class="kpis" style="margin-top:12px"><div class="kpi"><small>XP estimé</small><strong id="xpSimTotal">—</strong></div><div class="kpi"><small>Gains max/jour</small><strong id="xpSimCap">—</strong></div></div>';
    grid.appendChild(sim);
    const paint = () => {
      const msgs=Math.max(1,Number($('xpSimMessages').value||1)),days=Math.max(1,Number($('xpSimDays').value||1));
      const cap=cd>0?Math.min(msgs,Math.floor(86400/cd)):msgs;
      $('xpSimCap').textContent=number(cap); $('xpSimTotal').textContent='≈ '+number(Math.round(cap*avg*days))+' XP';
    };
    $('xpSimMessages').oninput=paint; $('xpSimDays').oninput=paint; paint();
  }
}

async function enhanceEconomyExperience() {
  let ec; try { ec = await economyData(); } catch (_) { return; }
  const shop=ec.shop||[],panels=ec.panels||[];
  experienceInsertAfterCommand(experienceSummary(
    'Économie du serveur',
    'Monnaie, boutique et jeux réunis autour des données réellement utilisées par SentriX.',
    [
      { label:'Articles', value:number(shop.length), note:shop.filter(i=>i.stock!==0).length+' disponible(s)' },
      { label:'Panneaux', value:number(panels.length), note:'publiés' },
      { label:'Comptes', value:number(metrics().economy_accounts||0), note:'membres avec solde' },
      { label:'Monnaie', value:ec.currency_symbol||ec.currency_plural||'—', note:ec.currency_plural||'' },
    ],
    [
      {page:'economy',sub:'boutique',label:'Boutique',primary:true},
      {page:'economy',sub:'jeux',label:'Jeux'},
      {page:'economy',sub:'gains',label:'Gains'},
    ]
  ));
}

async function enhanceRolesExperience() {
  let rp=null,lv=null; try{rp=await rolesData();}catch(_){} try{lv=await levelsData();}catch(_){}
  if(!rp&&!lv)return;
  const autorole=state.guild?.settings?.autorole;
  experienceInsertAfterCommand(experienceSummary(
    'Architecture des rôles',
    'Autorôle, réactions, notifications et récompenses de niveau au même endroit.',
    [
      {label:'Autorôle',value:autorole?(roleName(autorole)||'Configuré'):'Aucun',note:'à l’arrivée'},
      {label:'Réactions',value:number((rp?.reaction_roles||[]).length),note:(rp?.reaction_panels||[]).length+' panneau(x)'},
      {label:'Menus notif.',value:number((rp?.notification_panels||[]).length),note:'publiés'},
      {label:'Niveaux',value:number((lv?.roles||[]).length),note:'récompenses'},
    ]
  ));
}

async function enhanceLogsExperience() {
  let cfg; try{cfg=await logConfigData();}catch(_){return;}
  const routes=cfg.routes||[];
  experienceInsertAfterCommand(experienceSummary(
    'Journalisation',
    'Chaque famille de logs peut écrire dans son propre salon.',
    [
      {label:'Actifs',value:routes.filter(r=>r.enabled&&r.valid).length+'/'+routes.length,note:'routes valides'},
      {label:'À corriger',value:number(routes.filter(r=>r.enabled&&!r.valid).length),note:'routes invalides'},
      {label:'Salons utilisés',value:number(new Set(routes.filter(r=>r.channel_id).map(r=>String(r.channel_id))).size),note:'destinations'},
      {label:'Couverture',value:routes.length?Math.round(routes.filter(r=>r.enabled&&r.valid).length/routes.length*100)+' %':'0 %',note:'du routage'},
    ]
  ));
  if(state.sub!=='routage'||$('logPresets'))return;
  const grid=content().querySelector('.grid'); if(!grid)return;
  const preset=document.createElement('section'); preset.className='card full'; preset.id='logPresets';
  preset.innerHTML='<div class="card-head"><div><h2>Configuration rapide</h2><p>Un preset pour démarrer, puis vous pouvez séparer chaque catégorie.</p></div></div><div class="toolbar"><button class="btn primary" type="button" id="logsPresetEssential">Essentiels vers un salon</button><button class="btn" type="button" id="logsPresetAll">Tout vers un salon</button><button class="btn danger" type="button" id="logsPresetOff">Tout désactiver</button></div>';
  const summary=grid.querySelector('.experience-summary'); (summary||grid.firstElementChild).insertAdjacentElement('afterend',preset);
  const choose=title=>openModal({title,body:'<div class="field"><label for="logsPresetChannel">Salon</label><select id="logsPresetChannel">'+channelOptions('','text','Choisir un salon')+'</select></div>',actions:[{label:'Annuler',value:null},{label:'Appliquer',kind:'primary',keep:true,onClick:()=>{const v=$('logsPresetChannel').value;if(!v)return toast('Choisissez un salon.',true);closeModal(v);}}]});
  const apply=async(mode,ch)=>{
    const wanted=mode==='all'?new Set(routes.map(r=>r.key)):new Set(['moderation','messages','members','voice','tickets','automod','antispam','antiraid']);
    try{for(const r of routes){const on=wanted.has(r.key);await gpost('/logs/config',{category:r.key,channel_id:on?ch:(r.channel_id||null),enabled:on},'PUT');}invalidate('log-config-v2');toast('Preset de logs appliqué.');await render();}catch(e){toast(e.message,true);}
  };
  $('logsPresetEssential').onclick=async()=>{const ch=await choose('Logs essentiels');if(ch)await apply('essential',ch);};
  $('logsPresetAll').onclick=async()=>{const ch=await choose('Tous les logs');if(ch)await apply('all',ch);};
  $('logsPresetOff').onclick=async()=>{if(!(await confirmDialog({title:'Désactiver tous les logs ?',body:'Les salons restent mémorisés, mais aucun nouveau log ne sera envoyé.',confirm:'Désactiver',danger:true})))return;try{for(const r of routes)await gpost('/logs/config',{category:r.key,channel_id:r.channel_id||null,enabled:false},'PUT');invalidate('log-config-v2');toast('Tous les logs sont désactivés.');await render();}catch(e){toast(e.message,true);}};
}

async function enhanceTicketsExperience() {
  let data; try{data=await v62(true);}catch(_){return;}
  const panels=data.tickets?.panels||[],types=data.tickets?.types||[],buttons=data.tickets?.buttons||{};
  experienceInsertAfterCommand(experienceSummary(
    'Support & tickets',
    'Panneaux, types et actions staff dans un seul flux de configuration.',
    [
      {label:'Panneaux',value:number(panels.length),note:panels.filter(p=>p.message_id).length+' publié(s)'},
      {label:'Types',value:number(types.length),note:'options membres'},
      {label:'Actions staff',value:number(Object.values(buttons).filter(b=>b.enabled).length),note:'boutons visibles'},
      {label:'État',value:panels.length&&types.length?'Prêt':'À configurer',note:panels.length&&types.length?'base opérationnelle':'panneau ou type manquant'},
    ]
  ));
}

async function enhanceGamesExperience() {
  let inf=null,ec=null; try{inf=await infiniteData();}catch(_){} try{ec=await economyData();}catch(_){}
  const gs=ec?.games||ec?.game_settings||{};
  const disabled=gs.disabled_games||gs.disabled||[];
  experienceInsertAfterCommand(experienceSummary(
    'Jeux & engagement',
    'Le Compteur Infini garde sa propre progression, les autres jeux suivent les règles d’accès communes.',
    [
      {label:'Compteur Infini',value:inf?.enabled?'Actif':'Inactif',note:inf?.channel_id?(channelName(inf.channel_id)||'salon'):'aucun salon'},
      {label:'Prochain nombre',value:inf?.next_number!=null?number(inf.next_number):'—',note:inf?.last_user_id?'progression en cours':'aucun joueur'},
      {label:'Jeux coupés',value:number(Array.isArray(disabled)?disabled.length:0),note:'catalogue'},
      {label:'Accès',value:gs.enabled===false?'Désactivé':'Ouvert',note:'règles serveur'},
    ],
    [{page:'games',sub:'infinite',label:'Compteur Infini',primary:true},{page:'games',sub:'catalogue',label:'Mini-jeux'},{page:'economy',sub:'jeux',label:'Accès'}]
  ));
}

async function enhanceAutomationExperience() {
  let d; try{d=await automationPlus();}catch(_){return;}
  const star=d.starboard||d.starboard_config||null,sticky=d.sticky||d.stickies||[],scheduled=d.scheduled||d.scheduled_messages||[],voice=d.voicehub||d.voicehub_config||null;
  experienceInsertAfterCommand(experienceSummary(
    'Automatisations',
    'Tous les automatismes SentriX regroupés sans dupliquer leurs moteurs.',
    [
      {label:'Starboard',value:star?'Configuré':'Inactif',note:star?.threshold?star.threshold+' réactions':''},
      {label:'Sticky',value:number(Array.isArray(sticky)?sticky.length:(sticky?1:0)),note:'message(s)'},
      {label:'Programmés',value:number(Array.isArray(scheduled)?scheduled.length:0),note:'en attente'},
      {label:'VoiceHub',value:voice?'Configuré':'Inactif',note:voice?.lobby_channel_id?(channelName(voice.lobby_channel_id)||'lobby'):''},
    ]
  ));
}

function enhanceModerationExperience() {
  experienceInsertAfterCommand(experienceSummary(
    'Centre de modération',
    'Recherchez un membre, consultez son dossier puis utilisez le même moteur que les commandes Discord.',
    [
      {label:'Historique',value:number(content().querySelectorAll('#sanctionList .row').length),note:'sanctions chargées'},
      {label:'Actions',value:'4',note:'warn · mute · kick · ban'},
      {label:'Traçabilité',value:'Active',note:'dossiers et logs'},
      {label:'Hiérarchie',value:'Vérifiée',note:'permissions Discord'},
    ]
  ));
}

function enhanceEmbedsExperience() {
  if(!$('embedTitle')||$('embedTemplates'))return;
  const grid=content().querySelector('.grid');if(!grid)return;
  const s=document.createElement('section');s.className='card full';s.id='embedTemplates';
  s.innerHTML='<div class="card-head"><div><h2>Modèles rapides</h2><p>Chargez une base puis adaptez-la avant publication.</p></div></div><div class="template-grid"><button class="template-card" type="button" data-embed-template="announcement"><b>Annonce</b><small>Message important</small></button><button class="template-card" type="button" data-embed-template="rules"><b>Règlement</b><small>Champs structurés</small></button><button class="template-card" type="button" data-embed-template="event"><b>Événement</b><small>Date et inscription</small></button><button class="template-card" type="button" data-embed-template="maintenance"><b>Maintenance</b><small>État du service</small></button></div>';
  grid.insertBefore(s,grid.children[1]||null);
  const templates={
    announcement:{title:'Annonce',description:'Écrivez ici votre annonce importante.',color:'#4da3ff',fields:''},
    rules:{title:'Règlement du serveur',description:'Merci de lire les règles avant de participer.',color:'#55d69a',fields:'Respect | Restez respectueux envers tous les membres.\nContenu | Publiez dans les salons adaptés.\nStaff | Suivez les consignes de l’équipe.'},
    event:{title:'Nouvel événement',description:'Un événement arrive sur le serveur.',color:'#7c5cff',fields:'Date | À compléter\nLieu | À compléter\nInscription | Répondez à ce message.'},
    maintenance:{title:'Maintenance SentriX',description:'Une opération de maintenance est en cours.',color:'#f0b232',fields:'État | En cours\nImpact | À compléter\nRetour prévu | À compléter'},
  };
  s.querySelectorAll('[data-embed-template]').forEach(b=>b.onclick=()=>{const t=templates[b.dataset.embedTemplate];$('embedTitle').value=t.title;$('embedDescription').value=t.description;$('embedColor').value=t.color;$('embedFields').value=t.fields;$('embedTitle').dispatchEvent(new Event('input',{bubbles:true}));toast('Modèle chargé. Vérifiez l’aperçu avant l’envoi.');});
}


function enhanceWelcomeExperience() {
  const s=settings();
  experienceInsertAfterCommand(experienceSummary(
    'Accueil des membres',
    'Bienvenue et départs utilisent les mêmes réglages que les commandes /setup et +setup.',
    [
      {label:'Bienvenue',value:s.welcome_channel?(channelName(s.welcome_channel)||'Configuré'):'Aucun salon',note:s.welcome_mode==='text'?'message simple':'embed'},
      {label:'Départs',value:s.goodbye_channel?(channelName(s.goodbye_channel)||'Configuré'):'Aucun salon',note:s.goodbye_mode==='text'?'message simple':'embed'},
      {label:'Autorôle',value:s.autorole?(roleName(s.autorole)||'Configuré'):'Aucun',note:'à l’arrivée'},
      {label:'Vérification',value:s.verify_role?(roleName(s.verify_role)||'Configurée'):'Non configurée',note:'rôle final'},
    ],
    [{page:'welcome',sub:'bienvenue',label:'Bienvenue',primary:true},{page:'welcome',sub:'departs',label:'Départs'},{page:'roles',label:'Rôles'}]
  ));
}

function enhanceSecurityExperience() {
  const a=state.guild?.automod||{},s=settings();
  const active=AUTOMOD.filter(([k])=>Boolean(a[k])).length;
  experienceInsertAfterCommand(experienceSummary(
    'Sécurité du serveur',
    'Les protections actives sont appliquées par les moteurs AutoMod/anti-abus réels de SentriX.',
    [
      {label:'Protections',value:active+'/'+AUTOMOD.length,note:'activées'},
      {label:'Vérification',value:s.verify_role?'Configurée':'Inactive',note:s.verify_role?(roleName(s.verify_role)||'rôle défini'):'aucun rôle'},
      {label:'Anti-raid',value:a.antiraid?'Actif':'Inactif',note:'arrivées anormales'},
      {label:'Anti-nuke',value:a.antinuke?'Actif':'Inactif',note:'salons et rôles'},
    ],
    [{page:'moderation',label:'Centre de modération',primary:true},{page:'logs',label:'Logs'},{page:'security',sub:'verification',label:'Vérification'}]
  ));
}

function enhanceNotificationsExperience() {
  const items=state.guild?.social_notifications||[];
  const active=items.filter(x=>x.enabled!==0).length;
  const platforms=[...new Set(items.map(x=>String(x.platform||'').toLowerCase()).filter(Boolean))];
  experienceInsertAfterCommand(experienceSummary(
    'Notifications sociales',
    'Suivez vos sources et contrôlez où SentriX publie les nouvelles vidéos et lives.',
    [
      {label:'Sources',value:number(items.length),note:active+' active(s)'},
      {label:'Plateformes',value:number(platforms.length),note:platforms.slice(0,3).join(' · ')||'aucune'},
      {label:'Salons',value:number(new Set(items.map(x=>String(x.discord_channel_id||'')).filter(Boolean)).size),note:'destinations'},
      {label:'Mentions',value:number(items.filter(x=>x.role_id).length),note:'sources avec rôle'},
    ],
    [{page:'automation',label:'Automatisations',primary:true},{page:'roles',label:'Rôles'}]
  ));
}

function enhanceAIExperience() {
  const a=state.guild?.ai||{};
  experienceInsertAfterCommand(experienceSummary(
    'Intelligence artificielle',
    'Réglages du moteur IA réellement utilisés par SentriX.',
    [
      {label:'IA',value:a.enabled?'Active':'Inactive',note:a.default_model||'modèle par défaut'},
      {label:'Mémoire',value:a.memory_enabled?'Active':'Coupée',note:a.memory_minutes?String(a.memory_minutes)+' min':''},
      {label:'Limite/min',value:number(a.per_minute_limit||0),note:'requêtes'},
      {label:'Limite/jour',value:number(a.daily_limit||0),note:'requêtes'},
    ]
  ));
}

async function enhanceSentrixExperience() {
  if(!state.guildId||!state.guild)return;
  // La sous-page Actions staff de Tickets est volontairement une page d'édition
  // compacte. Aucun hero/KPI ne doit être injecté au-dessus.
  if(state.page==='tickets')return;
  const grid=content().querySelector('.grid');if(!grid)return;
  if(!grid.querySelector('.experience-command'))grid.insertAdjacentHTML('afterbegin',experienceCommandBar());
  try{
    if(state.page==='overview')await enhanceOverviewExperience();
    else if(state.page==='welcome')enhanceWelcomeExperience();
    else if(state.page==='levels')await enhanceLevelsExperience();
    else if(state.page==='economy')await enhanceEconomyExperience();
    else if(state.page==='roles')await enhanceRolesExperience();
    else if(state.page==='logs')await enhanceLogsExperience();
    else if(state.page==='tickets')await enhanceTicketsExperience();
    else if(state.page==='games')await enhanceGamesExperience();
    else if(state.page==='automation')await enhanceAutomationExperience();
    else if(state.page==='moderation')enhanceModerationExperience();
    else if(state.page==='security')enhanceSecurityExperience();
    else if(state.page==='notifications')enhanceNotificationsExperience();
    else if(state.page==='embeds')enhanceEmbedsExperience();
    else if(state.page==='ai')enhanceAIExperience();
  }catch(e){console.warn('SentriX experience enhancement skipped:',e?.message||e);}
  bindExperienceFilter();
  content().querySelectorAll('[data-go]').forEach(b=>{if(!b.onclick)b.onclick=()=>go(b.dataset.go,b.dataset.goSub||'');});
}
