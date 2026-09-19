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
        <span class="badge blue">${plural(Number(history.total ?? rows.length), 'sanction')}</span>
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
            ${['warn','mute','kick','ban','unmute','unban','tempban','clearwarnings'].map(x => `<option value="${x}">${x}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="list" id="moderationHistory"></div>
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
    $('moderationHistory').innerHTML = items.length ? items.map(x => {
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
        <div class="row-actions"><button class="btn sm" type="button" data-open-member="${esc(x.user_id)}">Dossier</button></div>
      </div>`;
    }).join('') : emptyState('Aucune sanction trouvée', 'Modifiez les filtres pour afficher d’autres résultats.');
    $('moderationHistory').querySelectorAll('[data-open-member]').forEach(b => b.onclick = async () => {
      state.moderationMemberId = b.dataset.openMember;
      await paintMember();
      $('moderationMemberCard').scrollIntoView({ behavior: REDUCED_MOTION() ? 'auto' : 'smooth', block: 'start' });
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
      <div class="kpi"><small>État</small><b>${muted ? 'Mute' : 'Actif'}</b></div>
      <div class="kpi"><small>Rôles</small><b>${number((m.roles || []).length)}</b></div>
    </div>
    <div class="toolbar" style="margin-top:14px">
      ${m.bot ? '<span class="notice warn">Les bots ne peuvent pas être sanctionnés depuis ce centre.</span>' : ['warn','mute','kick','ban'].map(a => `<button class="btn ${moderationActionClass(a)}" type="button" data-mod-action="${a}">${moderationActionLabel(a)}</button>`).join('')}
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
  }

  if (selectedId) await paintMember();
};
