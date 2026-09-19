/* ---------- Logs : source canonique log_config + événements V17 ---------- */
SUBS.logs = [['routage', 'Routage'], ['evenements', 'Événements']];

const logConfigData = (force = false) => cached('log-config-v2', () => gget('/logs/config'), { force });

const LOG_PRIMARY = new Set(['moderation', 'messages', 'members', 'voice', 'tickets', 'automod', 'spam', 'raid']);
const EVENT_GROUP = {
  message_delete: 'Messages', message_edit: 'Messages',
  member_join: 'Membres', member_leave: 'Membres', member_roles: 'Membres',
  member_timeout: 'Modération', member_ban: 'Modération', member_unban: 'Modération',
  voice_activity: 'Vocal',
  channel_create: 'Salons', channel_delete: 'Salons', channel_update: 'Salons',
  role_create: 'Rôles', role_delete: 'Rôles', role_update: 'Rôles',
  guild_update: 'Serveur',
};

renderLogs = async function renderCanonicalLogs() {
  let data;
  try { data = await logConfigData(); } catch (e) { return errorView(e); }

  if (state.sub === 'evenements') {
    const groups = {};
    for (const ev of data.events || []) {
      const group = EVENT_GROUP[ev.key] || 'Autres';
      (groups[group] = groups[group] || []).push(ev);
    }
    content().innerHTML = `<div class="grid">
      <section class="card full">
        <div class="card-head"><div><h2>Événements détaillés</h2><p>Désactivez seulement les événements que vous ne souhaitez pas journaliser. Les routes de salons se règlent dans l’onglet Routage.</p></div></div>
        <div class="list">
          ${Object.entries(groups).map(([group, events]) => `<div class="row" style="display:block">
            <div class="card-head" style="margin-bottom:8px"><div><b>${esc(group)}</b><small>${plural(events.length, 'événement')}</small></div></div>
            <div class="list compact">
              ${events.map(ev => `<label class="switch-row">
                <span class="switch-copy"><b>${esc(ev.label)}</b><span><code>${esc(ev.key)}</code></span></span>
                <input class="switch" type="checkbox" data-log-event="${esc(ev.key)}" ${ev.enabled ? 'checked' : ''}>
              </label>`).join('')}
            </div>
          </div>`).join('')}
        </div>
      </section>
    </div>`;
    content().querySelectorAll('[data-log-event]').forEach(sw => sw.onchange = async () => {
      sw.disabled = true;
      try {
        const r = await gpost('/logs/events', { event_key: sw.dataset.logEvent, enabled: sw.checked }, 'PUT');
        toast(r.message);
        invalidate('log-config-v2');
      } catch (e) {
        sw.checked = !sw.checked;
        toast(e.message, true);
      } finally { sw.disabled = false; }
    });
    return;
  }

  const routes = data.routes || [];
  const drawGroup = (title, list) => `<section class="card full">
    <div class="card-head"><div><h2>${esc(title)}</h2><p>${title === 'Essentiels' ? 'Les journaux les plus utilisés au quotidien.' : 'Routes spécialisées disponibles si votre serveur en a besoin.'}</p></div></div>
    <div class="list">
      ${list.map(r => `<div class="row" data-log-route="${esc(r.key)}">
        <div class="row-main" style="min-width:170px">
          <b>${esc(r.label)}</b>
          <small class="${r.enabled && !r.valid ? 'bad-text' : ''}">${r.enabled ? (r.valid ? 'Actif' : esc(r.problem || 'Configuration incomplète')) : 'Désactivé'}</small>
        </div>
        <div class="row-actions" style="flex:1;justify-content:flex-end">
          <select class="select" data-log-channel="${esc(r.key)}" style="min-width:220px">${channelOptions(r.channel_id || '', 'text', 'Choisir un salon')}</select>
          <label class="switch-row" style="padding:4px 6px"><input class="switch" type="checkbox" data-log-enabled="${esc(r.key)}" ${r.enabled ? 'checked' : ''} aria-label="Activer ${esc(r.label)}"></label>
        </div>
      </div>`).join('')}
    </div>
  </section>`;

  const primary = routes.filter(r => LOG_PRIMARY.has(r.key));
  const other = routes.filter(r => !LOG_PRIMARY.has(r.key));
  const configured = routes.filter(r => r.enabled && r.channel_id).length;
  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head"><div><h2>Routage des logs</h2><p>Chaque famille peut écrire dans son propre salon. Cette page écrit directement dans <code>log_config</code>, la source utilisée par le bot.</p></div><span class="badge blue">${configured}/${routes.length} configurés</span></div>
      <div class="notice">Choisissez un salon puis activez la ligne. Aucun identifiant Discord à copier.</div>
    </section>
    ${drawGroup('Essentiels', primary)}
    ${drawGroup('Autres', other)}
  </div>`;

  const saveRoute = async key => {
    const channel = content().querySelector(`[data-log-channel="${CSS.escape(key)}"]`);
    const enabled = content().querySelector(`[data-log-enabled="${CSS.escape(key)}"]`);
    if (enabled.checked && !channel.value) {
      enabled.checked = false;
      return toast('Choisissez un salon avant d’activer cette catégorie.', true);
    }
    channel.disabled = true; enabled.disabled = true;
    try {
      const r = await gpost('/logs/config', { category: key, channel_id: channel.value || null, enabled: enabled.checked }, 'PUT');
      toast(r.message);
      invalidate('log-config-v2');
      const fresh = await logConfigData(true);
      const item = (fresh.routes || []).find(x => x.key === key);
      const row = content().querySelector(`[data-log-route="${CSS.escape(key)}"] small`);
      if (row && item) {
        row.textContent = item.enabled ? (item.valid ? 'Actif' : item.problem || 'Configuration incomplète') : 'Désactivé';
      }
    } catch (e) {
      toast(e.message, true);
      invalidate('log-config-v2');
      await render();
    } finally { channel.disabled = false; enabled.disabled = false; }
  };

  content().querySelectorAll('[data-log-channel]').forEach(sel => sel.onchange = () => {
    const key = sel.dataset.logChannel;
    const sw = content().querySelector(`[data-log-enabled="${CSS.escape(key)}"]`);
    if (sel.value && !sw.checked) sw.checked = true;
    saveRoute(key);
  });
  content().querySelectorAll('[data-log-enabled]').forEach(sw => sw.onchange = () => saveRoute(sw.dataset.logEnabled));
};
