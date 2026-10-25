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

const routes = (data.routes || []).map(route => ({ ...route }));
  const byKey = new Map(routes.map(route => [route.key, route]));
  const activeCount = () => routes.filter(route => route.enabled && route.valid).length;
  const issueCount = () => routes.filter(route => route.enabled && !route.valid).length;
  const disabledCount = () => routes.filter(route => !route.enabled).length;

  const examples = {
    moderation: ['Membre banni', 'Modérateur : @Équipe de modération', 'Membre : @Utilisateur · Raison : spam répété'],
    messages: ['Message modifié', 'Salon : #général · Auteur : @Utilisateur', 'Avant : Bonjour · Après : Bonsoir'],
    members: ['Membre arrivé', 'Membre : @Utilisateur', 'Compte rejoint le serveur · Identifiant : 123456789'],
    voice: ['Activité vocale', 'Membre : @Utilisateur', 'Salon vocal : Discussion · Action : connecté'],
    tickets: ['Ticket fermé', 'Ticket : #support-0042', 'Responsable : @Modérateur · Statut : fermé'],
    automod: ['Protection automatique', 'Membre : @Utilisateur', 'Protection : anti-spam · Action : avertissement'],
    spam: ['Spam détecté', 'Membre : @Utilisateur', 'Action : message supprimé'],
    raid: ['Activité suspecte', 'Protection : anti-raid', 'Plusieurs arrivées rapprochées détectées'],
  };

  const statusOf = route => !route.enabled ? 'off' : (route.valid ? 'ok' : 'warn');
  const statusText = route => !route.enabled ? 'Désactivé' : (route.valid ? 'En service' : 'À corriger');
  const renderRoute = route => `<article class="log-route-card log-route-${statusOf(route)}" data-log-card="${esc(route.key)}">
    <div class="log-route-top">
      <div class="log-route-name"><strong>${esc(route.label)}</strong><span class="log-route-key">${esc(route.key)}</span></div>
      <span class="log-route-state" data-log-status="${esc(route.key)}">${esc(statusText(route))}</span>
    </div>
    <p class="log-route-detail" data-log-detail="${esc(route.key)}">${route.enabled && !route.valid ? esc(route.problem || 'Vérifiez le salon ou les permissions du bot.') : (route.channel_id ? 'Destination enregistrée. Les messages iront dans le salon choisi.' : 'Aucun salon sélectionné pour cette catégorie.')}</p>
    <div class="log-route-controls">
      <label class="log-route-channel">Salon de destination
        <select class="select" data-log-channel="${esc(route.key)}" aria-label="Salon des logs ${esc(route.label)}">${channelOptions(route.channel_id || '', 'text', 'Choisir un salon')}</select>
      </label>
      <label class="log-route-toggle"><span data-log-toggle-label>${route.enabled ? 'Activé' : 'Inactif'}</span>
        <input class="switch" type="checkbox" data-log-enabled="${esc(route.key)}" ${route.enabled ? 'checked' : ''} aria-label="Activer les logs ${esc(route.label)}">
      </label>
    </div>
    <div class="log-route-foot">
      <button class="btn ghost sm" type="button" data-log-preview="${esc(route.key)}" aria-label="Voir un exemple de log ${esc(route.label)}">Voir un exemple</button>
      <small class="log-route-feedback" data-log-feedback="${esc(route.key)}" role="status" aria-live="polite"></small>
    </div>
  </article>`;

  const renderGroup = (title, entries, description) => entries.length ? `<section class="log-route-group" aria-label="${esc(title)}">
    <div class="log-group-head"><div><h2>${esc(title)}</h2><p>${esc(description)}</p></div><span class="log-group-count">${entries.length} catégories</span></div>
    <div class="log-route-grid">${entries.map(renderRoute).join('')}</div>
  </section>` : '';

  const primary = routes.filter(route => LOG_PRIMARY.has(route.key));
  const secondary = routes.filter(route => !LOG_PRIMARY.has(route.key));
  const sampleKey = routes.find(route => route.enabled)?.key || routes[0]?.key || '';
  content().innerHTML = `<div class="log-center">
    <section class="log-center-hero" aria-labelledby="logCenterTitle">
      <div class="log-center-intro">
        <span class="log-eyebrow">SENTRIX / JOURNAUX</span>
        <h2 id="logCenterTitle">Votre centre des logs</h2>
        <p>Un salon par catégorie, des états compréhensibles et des réglages sans commande. Les paramètres enregistrés sont utilisés directement par le bot.</p>
      </div>
      <div class="log-center-summary" role="group" aria-label="Résumé des journaux">
        <div class="log-stat log-stat-ok"><span>En service</span><strong data-log-count="active">${activeCount()}</strong></div>
        <div class="log-stat log-stat-warn"><span>À corriger</span><strong data-log-count="issue">${issueCount()}</strong></div>
        <div class="log-stat"><span>Désactivés</span><strong data-log-count="off">${disabledCount()}</strong></div>
      </div>
      <div class="log-summary-bottom"><span>${routes.length} catégories disponibles</span><span>Activez uniquement les catégories nécessaires à votre serveur.</span></div>
    </section>

    <div class="log-center-tools">
      <label class="log-search-label" for="logRouteSearch">Rechercher une catégorie
        <input class="input" id="logRouteSearch" type="search" placeholder="Messages, modération, vocal…" autocomplete="off">
      </label>
      <div class="log-filter-buttons" role="group" aria-label="Filtrer les catégories de logs">
        <button class="btn sm log-filter-selected" type="button" data-log-filter="all" aria-pressed="true">Toutes</button>
        <button class="btn sm" type="button" data-log-filter="active" aria-pressed="false">En service</button>
        <button class="btn sm" type="button" data-log-filter="issue" aria-pressed="false">À corriger</button>
        <button class="btn sm" type="button" data-log-filter="off" aria-pressed="false">Désactivées</button>
      </div>
    </div>

    <div class="log-center-layout">
      <div class="log-route-list">
        ${renderGroup('Essentiels', primary, 'Les événements importants à suivre au quotidien.')}
        ${renderGroup('Autres catégories', secondary, 'Activez ces catégories lorsque votre serveur en a besoin.')}
        <div class="empty hidden" id="logNoResults"><b>Aucune catégorie trouvée</b><span>Essayez un autre mot ou affichez toutes les catégories.</span></div>
      </div>
      <aside class="log-preview" aria-label="Aperçu d'un journal Discord">
        <div class="log-preview-head"><div><span class="log-eyebrow">APERÇU DISCORD</span><h2>À quoi ressemblera le log ?</h2></div><span class="log-sample-badge">Exemple fictif</span></div>
        <p>Choisissez « Voir un exemple » sur une catégorie. Aucun message n'est envoyé au serveur.</p>
        <div class="log-discord-sample" aria-live="polite">
          <div class="log-sample-author"><span class="log-sample-avatar">S</span><div><strong>SentriX <span class="log-sample-bot">BOT</span></strong><small>Exemple de notification</small></div></div>
          <div class="log-sample-embed">
            <strong data-log-example-title>Journal SentriX</strong>
            <span data-log-example-info>Catégorie sélectionnée</span>
            <span data-log-example-detail>Détails de l'événement</span>
            <small>Exemple uniquement · aucune donnée réelle</small>
          </div>
        </div>
        <div class="log-preview-tip">Une catégorie marquée « À corriger » doit avoir un salon valide et les permissions d'envoi nécessaires.</div>
      </aside>
    </div>
  </div>`;

  const root = content();
  const refreshSummary = () => {
    root.querySelector('[data-log-count="active"]').textContent = activeCount();
    root.querySelector('[data-log-count="issue"]').textContent = issueCount();
    root.querySelector('[data-log-count="off"]').textContent = disabledCount();
  };
  const preview = key => {
    const route = byKey.get(key);
    if (!route) return;
    const sample = examples[key] || [route.label, 'Journal de cette catégorie', 'Les informations affichées dépendent de l’événement'];
    root.querySelector('[data-log-example-title]').textContent = sample[0];
    root.querySelector('[data-log-example-info]').textContent = sample[1];
    root.querySelector('[data-log-example-detail]').textContent = sample[2];
    root.querySelectorAll('[data-log-preview]').forEach(button => {
      const selected = button.dataset.logPreview === key;
      button.classList.toggle('log-preview-selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
  };

  let currentFilter = 'all';
  const applyFilters = () => {
    const query = root.querySelector('#logRouteSearch').value.trim().toLocaleLowerCase('fr');
    let visible = 0;
    root.querySelectorAll('[data-log-card]').forEach(card => {
      const route = byKey.get(card.dataset.logCard);
      const text = `${route.label} ${route.key}`.toLocaleLowerCase('fr');
      const matchesText = !query || text.includes(query);
      const matchesStatus = currentFilter === 'all' || (
        currentFilter === 'active' ? (route.enabled && route.valid) :
        currentFilter === 'issue' ? (route.enabled && !route.valid) : !route.enabled
      );
      card.classList.toggle('hidden', !(matchesText && matchesStatus));
      if (matchesText && matchesStatus) visible += 1;
    });
    root.querySelectorAll('.log-route-group').forEach(group => {
      group.classList.toggle('hidden', !group.querySelector('[data-log-card]:not(.hidden)'));
    });
    root.querySelector('#logNoResults').classList.toggle('hidden', visible > 0);
  };
  root.querySelector('#logRouteSearch').addEventListener('input', applyFilters);
  root.querySelectorAll('[data-log-filter]').forEach(button => {
    button.addEventListener('click', () => {
      currentFilter = button.dataset.logFilter;
      root.querySelectorAll('[data-log-filter]').forEach(other => {
        const selected = other === button;
        other.classList.toggle('log-filter-selected', selected);
        other.setAttribute('aria-pressed', String(selected));
      });
      applyFilters();
    });
  });
  root.querySelectorAll('[data-log-preview]').forEach(button => button.addEventListener('click', () => preview(button.dataset.logPreview)));
  preview(sampleKey);

  const saveRoute = async key => {
    const route = byKey.get(key);
    const card = root.querySelector(`[data-log-card="${CSS.escape(key)}"]`);
    if (!route || !card) return;
    const channel = card.querySelector('[data-log-channel]');
    const enabled = card.querySelector('[data-log-enabled]');
    const feedback = card.querySelector('[data-log-feedback]');
    const previous = { ...route };
    if (enabled.checked && !channel.value) {
      enabled.checked = Boolean(previous.enabled);
      channel.value = String(previous.channel_id || '');
      feedback.textContent = 'Sélectionnez d’abord un salon.';
      return toast('Choisissez un salon avant d’activer cette catégorie.', true);
    }
    channel.disabled = true;
    enabled.disabled = true;
    feedback.textContent = 'Enregistrement…';
    card.classList.add('log-route-saving');
    try {
      const response = await gpost('/logs/config', {
        category: key,
        channel_id: channel.value || null,
        enabled: enabled.checked,
      }, 'PUT');
      invalidate('log-config-v2');
      const fresh = await logConfigData(true).catch(() => null);
      const updated = (fresh?.routes || []).find(item => item.key === key);
      Object.assign(route, updated || response.route || {
        channel_id: channel.value || null,
        enabled: enabled.checked,
        valid: Boolean(!enabled.checked || channel.value),
      });
      card.classList.remove('log-route-ok', 'log-route-warn', 'log-route-off');
      card.classList.add(`log-route-${statusOf(route)}`);
      card.querySelector('[data-log-status]').textContent = statusText(route);
      card.querySelector('[data-log-detail]').textContent = route.enabled && !route.valid
        ? (route.problem || 'Vérifiez le salon ou les permissions du bot.')
        : (route.channel_id ? 'Salon enregistré. Les logs utilisent cette destination.' : 'Aucun salon sélectionné pour cette catégorie.');
      card.querySelector('[data-log-toggle-label]').textContent = route.enabled ? 'Activé' : 'Inactif';
      feedback.textContent = 'Enregistré';
      refreshSummary();
      applyFilters();
      toast(response.message || 'Configuration enregistrée.');
    } catch (error) {
      channel.value = String(previous.channel_id || '');
      enabled.checked = Boolean(previous.enabled);
      feedback.textContent = 'Non enregistré';
      toast(error.message || 'Impossible d’enregistrer ce réglage.', true);
    } finally {
      channel.disabled = false;
      enabled.disabled = false;
      card.classList.remove('log-route-saving');
    }
  };

  root.querySelectorAll('[data-log-channel]').forEach(select => select.addEventListener('change', () => saveRoute(select.dataset.logChannel)));
  root.querySelectorAll('[data-log-enabled]').forEach(toggle => toggle.addEventListener('change', () => saveRoute(toggle.dataset.logEnabled)));
};
