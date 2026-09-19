/* ---------- Tickets : actions staff configurables + aperçu ----------
   Le backend ticket_button_settings existait déjà ; cette couche l'expose dans le frontend
   unique au lieu d'imposer tous les boutons dans chaque ticket. */
const _renderTicketsBase = renderTickets;
const TICKET_BUTTON_LABELS = {
  claim: 'Prendre en charge', unclaim: 'Abandonner', add: 'Ajouter un membre',
  remove: 'Retirer un membre', rename: 'Renommer', transfer: 'Transférer',
  note: 'Ajouter une note', bump: 'Relancer', close: 'Fermer',
};

async function appendTicketButtonSettings() {
  let data;
  try { data = await v62(true); } catch (_) { return; }
  const buttons = data.tickets?.buttons || {};
  const entries = Object.entries(buttons);
  if (!entries.length) return;
  const grid = content().querySelector('.grid');
  if (!grid || $('ticketStaffActions')) return;

  const section = document.createElement('section');
  section.className = 'card full';
  section.id = 'ticketStaffActions';
  section.innerHTML = `<div class="card-head">
      <div><h2>Actions dans les tickets</h2><p>Choisissez les boutons réellement utiles au staff. Les changements s’appliquent aux nouveaux tickets.</p></div>
      <button class="btn" type="button" id="ticketButtonsRecommended">Configuration simple</button>
    </div>
    <div class="notice">Conseil : gardez 3 à 5 actions principales. Les actions rares peuvent rester désactivées.</div>
    <div class="list" id="ticketButtonRows" style="margin-top:10px">
      ${entries.map(([key, cfg]) => `<div class="row" data-ticket-button-row="${esc(key)}">
        <div class="row-main">
          <b><span data-ticket-button-preview-emoji="${esc(key)}">${esc(cfg.emoji || '')}</span> <span data-ticket-button-preview-label="${esc(key)}">${esc(cfg.label || TICKET_BUTTON_LABELS[key] || key)}</span></b>
          <small>${esc(TICKET_BUTTON_LABELS[key] || key)}</small>
        </div>
        <div class="row-actions" style="flex-wrap:wrap">
          <input class="search-input" style="width:150px" maxlength="80" data-ticket-button-label="${esc(key)}" value="${esc(cfg.label || TICKET_BUTTON_LABELS[key] || key)}" aria-label="Libellé">
          <input class="search-input" style="width:75px" maxlength="100" data-ticket-button-emoji="${esc(key)}" value="${esc(cfg.emoji || '')}" aria-label="Emoji">
          <select class="select" data-ticket-button-style="${esc(key)}" aria-label="Style">
            ${[['bleu','Bleu'],['gris','Gris'],['vert','Vert'],['rouge','Rouge']].map(([v,l]) => `<option value="${v}" ${cfg.style === v ? 'selected' : ''}>${l}</option>`).join('')}
          </select>
          <select class="select" data-ticket-button-role="${esc(key)}" aria-label="Rôle requis">${roleOptions(cfg.role_id || '', 'Tout le staff')}</select>
          <label class="switch-row" style="padding:4px 6px"><input class="switch" type="checkbox" data-ticket-button-enabled="${esc(key)}" ${cfg.enabled ? 'checked' : ''} aria-label="Activer"></label>
          <button class="btn sm" type="button" data-ticket-button-save="${esc(key)}">Enregistrer</button>
        </div>
      </div>`).join('')}
    </div>
    <div style="margin-top:14px">
      <h3>Aperçu des actions visibles</h3>
      <div class="toolbar" id="ticketButtonsPreview" style="margin-top:8px;flex-wrap:wrap"></div>
    </div>`;
  grid.appendChild(section);

  const paint = () => {
    const enabled = entries.filter(([key]) => content().querySelector(`[data-ticket-button-enabled="${CSS.escape(key)}"]`)?.checked);
    $('ticketButtonsPreview').innerHTML = enabled.length
      ? enabled.map(([key]) => {
          const label = content().querySelector(`[data-ticket-button-label="${CSS.escape(key)}"]`)?.value || TICKET_BUTTON_LABELS[key] || key;
          const emoji = content().querySelector(`[data-ticket-button-emoji="${CSS.escape(key)}"]`)?.value || '';
          return `<span class="btn sm">${esc(emoji)} ${esc(label)}</span>`;
        }).join('')
      : '<span class="info">Aucune action activée.</span>';
  };

  const saveKey = async key => {
    const enabled = content().querySelector(`[data-ticket-button-enabled="${CSS.escape(key)}"]`);
    const label = content().querySelector(`[data-ticket-button-label="${CSS.escape(key)}"]`);
    const emoji = content().querySelector(`[data-ticket-button-emoji="${CSS.escape(key)}"]`);
    const style = content().querySelector(`[data-ticket-button-style="${CSS.escape(key)}"]`);
    const role = content().querySelector(`[data-ticket-button-role="${CSS.escape(key)}"]`);
    try {
      const r = await v62Action({
        action: 'ticket_button_save', key,
        enabled: enabled.checked, label: label.value, emoji: emoji.value,
        style: style.value, role_id: role.value || null,
      });
      toast(r.message || 'Action enregistrée.');
      paint();
    } catch (e) { toast(e.message, true); }
  };

  content().querySelectorAll('[data-ticket-button-save]').forEach(b => b.onclick = () => saveKey(b.dataset.ticketButtonSave));
  content().querySelectorAll('[data-ticket-button-enabled],[data-ticket-button-label],[data-ticket-button-emoji]').forEach(el => {
    el.addEventListener(el.matches('input[type="checkbox"]') ? 'change' : 'input', paint);
  });
  $('ticketButtonsRecommended').onclick = async () => {
    const keep = new Set(['claim', 'add', 'close']);
    for (const [key] of entries) {
      const sw = content().querySelector(`[data-ticket-button-enabled="${CSS.escape(key)}"]`);
      sw.checked = keep.has(key);
    }
    paint();
    const button = $('ticketButtonsRecommended');
    button.disabled = true; button.textContent = 'Enregistrement…';
    try {
      for (const [key] of entries) await saveKey(key);
      toast('Configuration simple appliquée : Prendre en charge, Ajouter un membre, Fermer.');
    } finally { button.disabled = false; button.textContent = 'Configuration simple'; }
  };
  paint();
}

renderTickets = async function renderTicketsWithActions() {
  await _renderTicketsBase();
  await appendTicketButtonSettings();
};
