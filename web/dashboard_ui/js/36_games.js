/* ---------- Jeux : vraie configuration serveur ----------
   Le Compteur Infini utilise directement infinite_counter_config via dashboard_api_games.py.
   Le catalogue reprend les réglages existants de games_economy sans renommer artificiellement
   un autre mini-jeu en « Compteur Infini ». */
SUBS.games = [['infinite', 'Compteur Infini'], ['catalogue', 'Mini-jeux & accès']];

const infiniteData = (force = false) => cached('infinite-counter', () => gget('/games/infinite'), { force });

async function renderInfiniteCounter() {
  let d;
  try { d = await infiniteData(); } catch (e) { return errorView(e); }
  const configured = Boolean(d.configured);
  const enabled = Boolean(d.enabled);
  const status = configured ? (enabled ? '<span class="badge ok">ACTIF</span>' : '<span class="badge">SUSPENDU</span>') : '<span class="badge">NON CONFIGURÉ</span>';
  const channel = d.channel_id ? (channelName(d.channel_id) || 'Salon supprimé') : 'Aucun salon';
  const last = d.last_user_name || (d.last_user_id ? `Utilisateur ${d.last_user_id}` : 'Personne');
  const next = Number(d.next_number || 1);
  const current = Number(d.current_number || 0);

  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head">
        <div>
          <h2>Compteur Infini</h2>
          <p>Les membres écrivent 1, 2, 3… sans fin. Deux nombres consécutifs ne peuvent pas venir du même membre.</p>
        </div>
        ${status}
      </div>
      ${configured ? `<div class="kpis" style="margin-top:14px">
        <div class="kpi"><small>Salon</small><b>#${esc(channel)}</b></div>
        <div class="kpi"><small>Nombre actuel</small><b>${number(current)}</b></div>
        <div class="kpi"><small>Prochain nombre</small><b>${number(next)}</b></div>
        <div class="kpi"><small>Dernier joueur</small><b>${esc(last)}</b></div>
      </div>` : '<p class="info" style="margin-top:12px">Choisissez un salon et un nombre de départ pour lancer le compteur.</p>'}
    </section>

    <section class="card full">
      <h2>Configuration</h2>
      <p class="card-copy">Changer de salon conserve la progression. Une remise à zéro est toujours une action séparée.</p>
      <div class="fields" style="margin-top:14px">
        <div class="field">
          <label for="infChannel">Salon</label>
          <select id="infChannel">${channelOptions(d.channel_id || '', 'text', 'Choisir un salon')}</select>
        </div>
        ${configured ? '' : `<div class="field">
          <label for="infStart">Premier nombre attendu</label>
          <input id="infStart" type="number" min="1" value="1">
        </div>`}
      </div>
      <div class="toolbar" style="margin-top:14px">
        <button class="btn primary" type="button" id="infSave">${configured ? 'Enregistrer le salon' : 'Activer le compteur'}</button>
        ${configured ? `<button class="btn" type="button" id="infToggle">${enabled ? 'Suspendre' : 'Reprendre'}</button>
        <button class="btn ghost" type="button" id="infReset">Réinitialiser</button>` : ''}
      </div>
    </section>

    <section class="card full">
      <h2>Règles appliquées par SentriX</h2>
      <div class="list compact">
        <div class="row"><div class="row-main"><b>Ordre strict</b><small>Le message doit être exactement le prochain nombre attendu.</small></div></div>
        <div class="row"><div class="row-main"><b>Pas deux fois à la suite</b><small>Un membre doit laisser quelqu’un d’autre jouer avant de recompter.</small></div></div>
        <div class="row"><div class="row-main"><b>Progression persistante</b><small>Le prochain nombre est enregistré après chaque validation.</small></div></div>
      </div>
    </section>
  </div>`;

  $('infSave').onclick = async () => {
    const channelId = $('infChannel').value;
    if (!channelId) return toast('Choisissez un salon.', true);
    try {
      const payload = { channel_id: channelId };
      if (!configured) {
        payload.start_number = Number($('infStart').value || 1);
        payload.enabled = true;
        payload.reset_progression = true;
      }
      const r = await gpost('/games/infinite', payload, 'PUT');
      toast(r.message);
      invalidate('infinite-counter');
      await render();
    } catch (e) { toast(e.message, true); }
  };

  if (configured) {
    $('infToggle').onclick = async () => {
      try {
        const r = await gpost('/games/infinite/action', { action: enabled ? 'pause' : 'resume' });
        toast(r.message);
        invalidate('infinite-counter');
        await render();
      } catch (e) { toast(e.message, true); }
    };
    $('infReset').onclick = () => openModal({
      title: 'Réinitialiser le compteur',
      body: '<div class="field"><label for="infResetStart">Nouveau nombre de départ</label><input id="infResetStart" type="number" min="1" value="1"><div class="hint">Le dernier joueur sera oublié. Le salon et l’état actif/suspendu restent inchangés.</div></div>',
      actions: [
        { label: 'Annuler' },
        { label: 'Réinitialiser', kind: 'danger', keep: true, onClick: async () => {
          const value = Number($('infResetStart').value || 1);
          if (!Number.isInteger(value) || value < 1) return toast('Entrez un nombre entier supérieur ou égal à 1.', true);
          try {
            const r = await gpost('/games/infinite/action', { action: 'reset', start_number: value });
            closeModal();
            toast(r.message);
            invalidate('infinite-counter');
            await render();
          } catch (e) { toast(e.message, true); }
        } },
      ],
    });
  }
}

async function renderGameCatalogue() {
  let gd;
  try { gd = await cached('games', () => gget('/economy/games')); } catch (e) { return errorView(e); }
  const gs = gd.settings || {};
  const catalog = gd.catalog || [];
  const disabled = new Set(gs.disabled_games || []);

  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head">
        <div><h2>Mini-jeux</h2><p>Activez les jeux réellement présents dans SentriX et choisissez où ils sont accessibles.</p></div>
        <label class="switch-row" style="padding:0"><span class="switch-copy"><b>${gs.enabled ? 'Activés' : 'Désactivés'}</b></span><input class="switch" id="gmEnabled2" type="checkbox" ${gs.enabled ? 'checked' : ''}></label>
      </div>
      <div class="fields" style="margin-top:14px"><div class="field"><label for="gmDaily2">Manches récompensées par membre et par jour</label><input id="gmDaily2" type="number" min="0" max="10000" value="${Number(gs.daily_limit ?? 50)}"></div></div>
    </section>

    <section class="card full">
      <h2>Jeux disponibles</h2>
      <p class="card-copy">Le Compteur Infini a sa propre sous-page : cette liste ne le remplace pas.</p>
      <div class="chips" id="gmCatalog2" style="margin-top:12px">
        ${catalog.map(g => `<label class="chip ${disabled.has(g.key) ? '' : 'on'}"><input type="checkbox" data-game2="${esc(g.key)}" ${disabled.has(g.key) ? '' : 'checked'}> ${esc(g.label)}</label>`).join('') || '<span class="info">Aucun mini-jeu déclaré par le backend.</span>'}
      </div>
    </section>

    <section class="card full">
      <h2>Accès</h2>
      <p class="card-copy">Laissez une liste vide pour ne pas appliquer de restriction.</p>
      <div class="field"><span class="label">Salons autorisés</span>${multiChannelPicker('gmAllowedCh2', gs.allowed_channel_ids)}</div>
      <div class="field" style="margin-top:10px"><span class="label">Salons bloqués</span>${multiChannelPicker('gmBlockedCh2', gs.blocked_channel_ids)}</div>
      <div class="field" style="margin-top:10px"><span class="label">Rôles autorisés</span>${multiRolePicker('gmAllowedRoles2', gs.allowed_role_ids)}</div>
      <div class="field" style="margin-top:10px"><span class="label">Rôles bloqués</span>${multiRolePicker('gmBlockedRoles2', gs.blocked_role_ids)}</div>
    </section>
  </div>`;

  const save = values => gpost('/economy/games', values, 'PUT')
    .then(r => { invalidate('games'); toast(r.message); })
    .catch(e => toast(e.message, true));

  $('gmEnabled2').onchange = () => save({ enabled: $('gmEnabled2').checked });
  $('gmDaily2').onchange = () => save({ daily_limit: $('gmDaily2').value });
  content().querySelectorAll('[data-game2]').forEach(cb => cb.onchange = () => {
    cb.closest('.chip').classList.toggle('on', cb.checked);
    save({ disabled_games: [...content().querySelectorAll('[data-game2]')].filter(x => !x.checked).map(x => x.dataset.game2) });
  });
  bindMultiPickers(content(), () => save({
    allowed_channel_ids: readMulti('gmAllowedCh2'),
    blocked_channel_ids: readMulti('gmBlockedCh2'),
    allowed_role_ids: readMulti('gmAllowedRoles2'),
    blocked_role_ids: readMulti('gmBlockedRoles2'),
  }));
}

renderGames = async function renderGamesPage() {
  if (!['infinite', 'catalogue'].includes(state.sub)) state.sub = 'infinite';
  if (state.sub === 'catalogue') return renderGameCatalogue();
  return renderInfiniteCounter();
};
