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

  const working = Object.fromEntries(entries.map(([key, cfg]) => [key, { ...cfg }]));
  const section = document.createElement('section');
  section.className = 'card full ticket-actions-compact';
  section.id = 'ticketStaffActions';

  const draw = () => {
    section.innerHTML = `<div class="card-head">
      <div><h2>Actions dans les tickets</h2><p>Activez seulement les actions dont votre staff a besoin.</p></div>
      <span class="badge">${entries.filter(([key]) => working[key]?.enabled).length}/${entries.length} actives</span>
    </div>
    <div class="ticket-action-list">
      ${entries.map(([key]) => {
        const cfg = working[key] || {};
        const label = cfg.label || TICKET_BUTTON_LABELS[key] || key;
        return `<div class="ticket-action-item">
          <div class="ticket-action-copy">
            <b><span>${esc(cfg.emoji || '')}</span> ${esc(label)}</b>
            <small>${esc(TICKET_BUTTON_LABELS[key] || key)}</small>
          </div>
          <div class="ticket-action-controls">
            <label class="ticket-mini-switch" title="${cfg.enabled ? 'Désactiver' : 'Activer'}">
              <input class="switch" type="checkbox" data-ticket-button-enabled="${esc(key)}" ${cfg.enabled ? 'checked' : ''} aria-label="Activer ${esc(label)}">
            </label>
            <button class="btn sm" type="button" data-ticket-button-edit="${esc(key)}">Modifier</button>
          </div>
        </div>`;
      }).join('')}
    </div>`;

    section.querySelectorAll('[data-ticket-button-enabled]').forEach(el => {
      el.onchange = async () => {
        const key = el.dataset.ticketButtonEnabled;
        const previous = Boolean(working[key]?.enabled);
        working[key].enabled = el.checked;
        el.disabled = true;
        try {
          await saveKey(key);
          toast(el.checked ? 'Action activée.' : 'Action désactivée.');
          draw();
        } catch (e) {
          working[key].enabled = previous;
          el.checked = previous;
          el.disabled = false;
          toast(e.message, true);
        }
      };
    });
    section.querySelectorAll('[data-ticket-button-edit]').forEach(button => {
      button.onclick = () => editKey(button.dataset.ticketButtonEdit);
    });
  };

  const saveKey = async key => {
    const cfg = working[key];
    return v62Action({
      action: 'ticket_button_save',
      key,
      enabled: Boolean(cfg.enabled),
      label: cfg.label || TICKET_BUTTON_LABELS[key] || key,
      emoji: cfg.emoji || '',
      style: cfg.style || 'bleu',
      role_id: cfg.role_id || null,
    });
  };

  const editKey = key => {
    const cfg = working[key] || {};
    openModal({
      title: `Configurer « ${cfg.label || TICKET_BUTTON_LABELS[key] || key} »`,
      body: `<div class="fields">
        <div class="field"><label for="ticketActionLabel">Nom du bouton</label><input id="ticketActionLabel" maxlength="80" value="${esc(cfg.label || TICKET_BUTTON_LABELS[key] || key)}"></div>
        <div class="field"><label for="ticketActionEmoji">Emoji</label><input id="ticketActionEmoji" maxlength="100" value="${esc(cfg.emoji || '')}"></div>
        <div class="field"><label for="ticketActionStyle">Couleur</label><select id="ticketActionStyle">${[['bleu','Bleu'],['gris','Gris'],['vert','Vert'],['rouge','Rouge']].map(([v,l]) => `<option value="${v}" ${(cfg.style || 'bleu') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
        <div class="field"><label for="ticketActionRole">Rôle requis</label><select id="ticketActionRole">${roleOptions(cfg.role_id || '', 'Tout le staff')}</select></div>
      </div>`,
      actions: [
        { label: 'Annuler' },
        { label: 'Enregistrer', kind: 'primary', keep: true, onClick: async () => {
          working[key] = {
            ...working[key],
            label: $('ticketActionLabel').value.trim() || TICKET_BUTTON_LABELS[key] || key,
            emoji: $('ticketActionEmoji').value.trim(),
            style: $('ticketActionStyle').value,
            role_id: $('ticketActionRole').value || null,
          };
          try {
            await saveKey(key);
            closeModal();
            draw();
            toast('Action mise à jour.');
          } catch (e) { toast(e.message, true); }
        } },
      ],
    });
  };

  grid.appendChild(section);
  draw();
}

renderTickets = async function renderTicketsWithActions() {
  await _renderTicketsBase();
  await appendTicketButtonSettings();
};
