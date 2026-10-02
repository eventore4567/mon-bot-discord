/* ---------- Automatisation : hub sur les backends réellement chargés ----------
   Réactions auto = Growth V12. Starboard / sticky / annonces / VoiceHub = SentriXPlus. */
const _renderAutoReactions = renderAutomation;
SUBS.automation = [
  ['reactions', 'Réactions automatiques'],
  ['channel-rules', 'Règles de salons'],
  ['starboard', 'Starboard'],
  ['scheduled', 'Messages programmés'],
  ['sticky', 'Messages sticky'],
  ['voicehub', 'VoiceHub'],
  ['advanced', 'Automatisations avancées'],
];

const automationPlus = (force = false) => cached('automation-plus', () => gget('/automation/plus'), { force });

const channelMessageRules = (force = false) => cached(
  'automation-channel-rules',
  () => gget('/automation/channel-rules'),
  { force }
);

async function renderChannelMessageRules() {
  let d; try { d = await channelMessageRules(true); } catch (e) { return errorView(e); }
  const items = d.items || [];
  const modeLabel = mode => mode === 'images_only' ? 'Images uniquement' : 'Messages interdits';
  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head">
        <div>
          <h2>Règles de salons</h2>
          <p>Contrôlez ce que les membres ont le droit d’envoyer dans certains salons.</p>
        </div>
        <button class="btn primary" id="channelRuleAdd" type="button">Ajouter une règle</button>
      </div>
      <div class="list">
        ${items.length ? items.map(r => `<div class="row">
          <div class="row-main">
            <b>${esc(channelName(r.channel_id) || '#' + (r.channel_name || r.channel_id))}</b>
            <small>${esc(modeLabel(r.mode))} · le staff avec Gérer les messages passe outre</small>
          </div>
          <div class="row-actions">
            <label class="switch-row" style="padding:4px 8px"><input class="switch" type="checkbox" data-channel-rule-toggle="${esc(r.channel_id)}" ${r.enabled ? 'checked' : ''} aria-label="Activer la règle"></label>
            <button class="btn sm danger" type="button" data-channel-rule-del="${esc(r.channel_id)}">Supprimer</button>
          </div>
        </div>`).join('') : emptyState('Aucune règle de salon', 'Exemple : un salon où seuls les screenshots/images sont autorisés.')}
      </div>
    </section>
    <section class="card full">
      <h2>Modes disponibles</h2>
      <div class="list compact">
        <div class="row"><div class="row-main"><b>Messages interdits</b><small>Les messages des membres sont supprimés dans ce salon.</small></div></div>
        <div class="row"><div class="row-main"><b>Images uniquement</b><small>Il faut joindre au moins une vraie image et ne mettre aucun texte. Les autres fichiers sont refusés.</small></div></div>
      </div>
    </section>
  </div>`;

  $('channelRuleAdd').onclick = () => openModal({
    title: 'Nouvelle règle de salon',
    body: `<div class="fields">
      <div class="field"><label for="channelRuleChannel">Salon</label><select id="channelRuleChannel">${channelOptions('', 'text', 'Choisir un salon')}</select></div>
      <div class="field"><label for="channelRuleMode">Règle</label><select id="channelRuleMode">
        <option value="images_only">Images uniquement</option>
        <option value="blocked">Messages interdits</option>
      </select></div>
      <div class="field full"><small>SentriX ne crée aucun salon. Les bots, administrateurs, membres avec Gérer le serveur ou Gérer les messages ne sont pas bloqués.</small></div>
    </div>`,
    actions: [
      { label: 'Annuler' },
      { label: 'Enregistrer', kind: 'primary', keep: true, onClick: async () => {
        if (!$('channelRuleChannel').value) return toast('Choisissez un salon.', true);
        try {
          const r = await gpost('/automation/channel-rules', {
            action: 'save',
            channel_id: $('channelRuleChannel').value,
            mode: $('channelRuleMode').value,
          });
          closeModal();
          toast(r.message || 'Règle enregistrée.');
          invalidate('automation-channel-rules');
          await renderChannelMessageRules();
        } catch (e) { toast(e.message, true); }
      } },
    ],
  });

  content().querySelectorAll('[data-channel-rule-toggle]').forEach(x => x.onchange = async () => {
    try {
      await gpost('/automation/channel-rules', {
        action: 'toggle',
        channel_id: x.dataset.channelRuleToggle,
        enabled: x.checked,
      });
      invalidate('automation-channel-rules');
    } catch (e) {
      x.checked = !x.checked;
      toast(e.message, true);
    }
  });

  content().querySelectorAll('[data-channel-rule-del]').forEach(x => x.onclick = async () => {
    if (!(await confirmDialog({
      title: 'Supprimer cette règle ?',
      body: 'Les messages de ce salon ne seront plus filtrés par cette règle.',
      confirm: 'Supprimer',
      danger: true,
    }))) return;
    try {
      const r = await gpost('/automation/channel-rules', {
        action: 'delete',
        channel_id: x.dataset.channelRuleDel,
      });
      toast(r.message || 'Règle supprimée.');
      invalidate('automation-channel-rules');
      await renderChannelMessageRules();
    } catch (e) { toast(e.message, true); }
  });
}


async function renderStarboard() {
  let d; try { d = await automationPlus(); } catch (e) { return errorView(e); }
  const cfg = d.starboard || null;
  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head"><div><h2>Starboard</h2><p>Met en avant dans un salon les messages qui atteignent suffisamment de réactions ⭐.</p></div>${cfg ? '<span class="badge ok">ACTIF</span>' : '<span class="badge">NON CONFIGURÉ</span>'}</div>
      <div class="fields" style="margin-top:14px">
        <div class="field"><label for="starChannel">Salon Starboard</label><select id="starChannel">${channelOptions(cfg?.channel_id || '', 'text', 'Choisir un salon')}</select></div>
        <div class="field"><label for="starThreshold">Étoiles nécessaires</label><input id="starThreshold" type="number" min="2" max="25" value="${Number(cfg?.threshold || 3)}"><small>Entre 2 et 25 réactions ⭐.</small></div>
      </div>
      <div class="toolbar" style="margin-top:14px">
        <button class="btn primary" id="starSave" type="button">${cfg ? 'Enregistrer' : 'Activer le Starboard'}</button>
        ${cfg ? '<button class="btn danger" id="starOff" type="button">Désactiver</button>' : ''}
      </div>
    </section>
    <section class="card full">
      <h2>Fonctionnement</h2>
      <div class="list compact">
        <div class="row"><div class="row-main"><b>Emoji utilisé</b><small>⭐ — moteur SentriXPlus existant.</small></div></div>
        <div class="row"><div class="row-main"><b>Mise à jour automatique</b><small>Le message du Starboard suit le nombre d’étoiles et disparaît s’il repasse sous le seuil.</small></div></div>
      </div>
    </section>
  </div>`;
  $('starSave').onclick = async () => {
    if (!$('starChannel').value) return toast('Choisissez un salon.', true);
    try {
      const r = await gpost('/automation/starboard', { enabled: true, channel_id: $('starChannel').value, threshold: Number($('starThreshold').value || 3) }, 'PUT');
      toast(r.message); invalidate('automation-plus'); await render();
    } catch (e) { toast(e.message, true); }
  };
  const off = $('starOff'); if (off) off.onclick = async () => {
    if (!(await confirmDialog({ title: 'Désactiver le Starboard ?', body: 'Les futurs messages ne seront plus ajoutés au Starboard.', confirm: 'Désactiver', danger: true }))) return;
    try { const r = await gpost('/automation/starboard', { enabled: false }, 'PUT'); toast(r.message); invalidate('automation-plus'); await render(); } catch (e) { toast(e.message, true); }
  };
}

async function renderScheduledMessages() {
  let d; try { d = await automationPlus(true); } catch (e) { return errorView(e); }
  const items = d.scheduled || [];
  const now = Math.floor(Date.now() / 1000);
  const relative = due => {
    const sec = Math.max(0, Number(due || 0) - now);
    if (sec >= 86400) return `dans ${Math.floor(sec / 86400)} j`;
    if (sec >= 3600) return `dans ${Math.floor(sec / 3600)} h`;
    return `dans ${Math.max(1, Math.ceil(sec / 60))} min`;
  };
  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head"><div><h2>Messages programmés</h2><p>Un envoi unique entre 1 minute et 30 jours. Aucun système de répétition n’est ajouté ici.</p></div><button class="btn primary" id="scheduleAdd" type="button">Programmer un message</button></div>
      <div class="list" id="scheduledList">
        ${items.length ? items.map(x => `<div class="row">
          <div class="row-main"><b>${esc(channelName(x.channel_id) || 'Salon supprimé')} · ${esc(relative(x.due_at))}</b><small>${esc(String(x.content || '').replace(/\n/g,' ').slice(0,140))}</small></div>
          <div class="row-actions"><button class="btn sm danger" type="button" data-schedule-cancel="${esc(x.id)}">Annuler</button></div>
        </div>`).join('') : emptyState('Aucun message programmé', 'Programmez un message ponctuel dans un salon.')}
      </div>
    </section>
  </div>`;
  $('scheduleAdd').onclick = () => openModal({
    title: 'Programmer un message',
    body: `<div class="fields">
      <div class="field"><label for="scheduleChannel">Salon</label><select id="scheduleChannel">${channelOptions('', 'text', 'Choisir un salon')}</select></div>
      <div class="field"><label for="scheduleDelay">Envoyer dans</label><input id="scheduleDelay" placeholder="2h" value="1h"><small>Exemples : 10m, 2h, 1d. Minimum 1 minute, maximum 30 jours.</small></div>
      <div class="field full"><label for="scheduleContent">Message</label><textarea id="scheduleContent" maxlength="1900" rows="6" placeholder="Votre message…"></textarea></div>
    </div>`,
    actions: [
      { label: 'Annuler' },
      { label: 'Programmer', kind: 'primary', keep: true, onClick: async () => {
        if (!$('scheduleChannel').value) return toast('Choisissez un salon.', true);
        try {
          const r = await gpost('/automation/scheduled', { action: 'create', channel_id: $('scheduleChannel').value, delay: $('scheduleDelay').value, content: $('scheduleContent').value });
          closeModal(); toast(r.message); invalidate('automation-plus'); await renderScheduledMessages();
        } catch (e) { toast(e.message, true); }
      } },
    ],
  });
  content().querySelectorAll('[data-schedule-cancel]').forEach(b => b.onclick = async () => {
    if (!(await confirmDialog({ title: 'Annuler ce message ?', body: 'Il ne sera pas envoyé.', confirm: 'Annuler le message', danger: true }))) return;
    try { const r = await gpost('/automation/scheduled', { action: 'cancel', id: Number(b.dataset.scheduleCancel) }); toast(r.message); invalidate('automation-plus'); await renderScheduledMessages(); } catch (e) { toast(e.message, true); }
  });
}

async function renderStickyMessages() {
  let d; try { d = await automationPlus(true); } catch (e) { return errorView(e); }
  const items = d.sticky || [];
  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head"><div><h2>Messages sticky</h2><p>Un message reste au bas d’un salon et remonte après un nombre choisi de messages.</p></div><button class="btn primary" id="stickyAdd" type="button">Ajouter un sticky</button></div>
      <div class="list">
        ${items.length ? items.map(x => `<div class="row">
          <div class="row-main"><b>${esc(channelName(x.channel_id) || 'Salon supprimé')}</b><small>Tous les ${Number(x.every_messages || 5)} messages · ${esc(String(x.content || '').replace(/\n/g,' ').slice(0,120))}</small></div>
          <div class="row-actions"><button class="btn sm" type="button" data-sticky-edit="${esc(x.channel_id)}">Modifier</button><button class="btn sm danger" type="button" data-sticky-del="${esc(x.channel_id)}">Supprimer</button></div>
        </div>`).join('') : emptyState('Aucun sticky', 'Ajoutez un message persistant à un salon.')}
      </div>
    </section>
  </div>`;
  const openEditor = item => openModal({
    title: item ? 'Modifier le sticky' : 'Nouveau sticky',
    body: `<div class="fields">
      <div class="field"><label for="stickyChannel">Salon</label><select id="stickyChannel">${channelOptions(item?.channel_id || '', 'text', 'Choisir un salon')}</select></div>
      <div class="field"><label for="stickyEvery">Remonter tous les… messages</label><input id="stickyEvery" type="number" min="2" max="50" value="${Number(item?.every_messages || 5)}"></div>
      <div class="field full"><label for="stickyContent">Message</label><textarea id="stickyContent" maxlength="1700" rows="6">${esc(item?.content || '')}</textarea></div>
    </div>`,
    actions: [
      { label: 'Annuler' },
      { label: 'Enregistrer', kind: 'primary', keep: true, onClick: async () => {
        if (!$('stickyChannel').value) return toast('Choisissez un salon.', true);
        try {
          const r = await gpost('/automation/sticky', { action: 'save', channel_id: $('stickyChannel').value, every_messages: Number($('stickyEvery').value || 5), content: $('stickyContent').value });
          closeModal(); toast(r.message); invalidate('automation-plus'); await renderStickyMessages();
        } catch (e) { toast(e.message, true); }
      } },
    ],
  });
  $('stickyAdd').onclick = () => openEditor(null);
  content().querySelectorAll('[data-sticky-edit]').forEach(b => b.onclick = () => openEditor(items.find(x => String(x.channel_id) === String(b.dataset.stickyEdit))));
  content().querySelectorAll('[data-sticky-del]').forEach(b => b.onclick = async () => {
    if (!(await confirmDialog({ title: 'Supprimer ce sticky ?', body: 'Le message sticky actuellement publié sera également supprimé si SentriX y a accès.', confirm: 'Supprimer', danger: true }))) return;
    try { const r = await gpost('/automation/sticky', { action: 'delete', channel_id: b.dataset.stickyDel }); toast(r.message); invalidate('automation-plus'); await renderStickyMessages(); } catch (e) { toast(e.message, true); }
  });
}

async function renderVoiceHub() {
  let d; try { d = await automationPlus(true); } catch (e) { return errorView(e); }
  const cfg = d.voicehub || null;
  content().innerHTML = `<div class="grid">
    <section class="card full">
      <div class="card-head"><div><h2>VoiceHub</h2><p>Un salon vocal d’accueil crée automatiquement un vocal temporaire pour le membre qui le rejoint.</p></div>${cfg ? '<span class="badge ok">ACTIF</span>' : '<span class="badge">NON CONFIGURÉ</span>'}</div>
      ${cfg ? `<div class="list compact" style="margin-top:12px">
        <div class="row"><div class="row-main"><b>Salon d’accueil</b><small>${esc(channelName(cfg.lobby_channel_id) || 'Salon supprimé')}</small></div></div>
        <div class="row"><div class="row-main"><b>Catégorie des vocaux</b><small>${esc((state.guild?.channels || []).find(x => String(x.id) === String(cfg.category_id))?.name || 'Catégorie supprimée')}</small></div></div>
      </div>` : '<p class="info" style="margin-top:12px">Vous pouvez sélectionner vos propres ressources ou demander à SentriX de créer la catégorie et le lobby recommandés.</p>'}
    </section>
    <section class="card full">
      <h2>Configuration manuelle</h2>
      <p class="card-copy">Aucun salon n’est créé sans votre action.</p>
      <div class="fields" style="margin-top:12px">
        <div class="field"><label for="voiceLobby">Salon vocal d’accueil</label><select id="voiceLobby">${channelOptions(cfg?.lobby_channel_id || '', 'voice', 'Choisir un vocal')}</select></div>
        <div class="field"><label for="voiceCategory">Catégorie</label><select id="voiceCategory">${channelOptions(cfg?.category_id || '', 'category', 'Choisir une catégorie')}</select></div>
      </div>
      <div class="toolbar" style="margin-top:14px">
        <button class="btn primary" id="voiceSave" type="button">Enregistrer</button>
        <button class="btn" id="voiceCreate" type="button">Créer la configuration recommandée</button>
        ${cfg ? '<button class="btn danger" id="voiceOff" type="button">Désactiver</button>' : ''}
      </div>
    </section>
  </div>`;
  $('voiceSave').onclick = async () => {
    if (!$('voiceLobby').value || !$('voiceCategory').value) return toast('Choisissez le lobby et la catégorie.', true);
    try { const r = await gpost('/automation/voicehub', { action: 'configure', lobby_channel_id: $('voiceLobby').value, category_id: $('voiceCategory').value }, 'PUT'); toast(r.message); invalidate('automation-plus'); await render(); } catch (e) { toast(e.message, true); }
  };
  $('voiceCreate').onclick = async () => {
    if (!(await confirmDialog({ title: 'Créer VoiceHub ?', body: 'SentriX créera une catégorie « SENTRIX — VOCAUX » et un salon « ➕・Créer ton vocal » seulement s’ils n’existent pas déjà.', confirm: 'Créer' }))) return;
    try { const r = await gpost('/automation/voicehub', { action: 'create' }, 'PUT'); toast(r.message); invalidate('automation-plus'); await render(); } catch (e) { toast(e.message, true); }
  };
  const off = $('voiceOff'); if (off) off.onclick = async () => {
    if (!(await confirmDialog({ title: 'Désactiver VoiceHub ?', body: 'Les vocaux temporaires existants restent jusqu’à ce qu’ils soient vides.', confirm: 'Désactiver', danger: true }))) return;
    try { const r = await gpost('/automation/voicehub', { action: 'off' }, 'PUT'); toast(r.message); invalidate('automation-plus'); await render(); } catch (e) { toast(e.message, true); }
  };
}

renderAutomation = async function renderAutomationHub() {
  if (!SUBS.automation.some(([key]) => key === state.sub)) state.sub = 'reactions';
  if (state.sub === 'reactions') return _renderAutoReactions();
  if (state.sub === 'channel-rules') return renderChannelMessageRules();
  if (state.sub === 'starboard') return renderStarboard();
  if (state.sub === 'scheduled') return renderScheduledMessages();
  if (state.sub === 'sticky') return renderStickyMessages();
  if (state.sub === 'voicehub') return renderVoiceHub();
  if (state.sub === 'advanced') {
    content().innerHTML = `<div class="grid"><section class="card full">
      <h2>Automatisations avancées</h2>
      <p class="card-copy">Les déclencheurs/actions avancés existent déjà dans le Centre avancé natif du nouveau dashboard.</p>
      <div class="toolbar" style="margin-top:12px"><button class="btn primary" type="button" id="openAdvancedAutomations">Ouvrir les automations avancées</button></div>
    </section></div>`;
    $('openAdvancedAutomations').onclick = () => go('advanced', 'automations');
  }
};
