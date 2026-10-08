/* Aperçu isolé de la PR #450 : fonctions de sélection copiées sans modification
   du module réellement utilisé par SentriX. Aucun appel réseau / Discord. */
const state = { securityPickerOutsideHandler: null };
function esc(value) {
  return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;')
    .replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
}

function securityMultiPickerMarkup(id, optionsHtml, placeholder, label) {
  return `<div class="security-multi" data-security-multi="${esc(id)}">
    <select id="${esc(id)}" multiple hidden tabindex="-1" aria-hidden="true">${optionsHtml}</select>
    <button type="button" class="security-multi-trigger" data-security-trigger aria-label="${esc(label)} : ouvrir les choix" aria-expanded="false" aria-haspopup="true" aria-controls="${esc(id)}Choices">
      <span class="security-multi-trigger-text" data-security-trigger-text>${esc(placeholder)}</span>
      <span class="security-multi-chevron" aria-hidden="true">⌄</span>
    </button>
    <div class="security-multi-chips" data-security-chips role="group" aria-label="${esc(label)} sélectionnés"></div>
    <div class="security-multi-popover hidden" data-security-popover id="${esc(id)}Choices">
      <label class="security-multi-search-label" for="${esc(id)}Search">Rechercher un élément</label>
      <input class="security-multi-search" id="${esc(id)}Search" data-security-search type="search" placeholder="Rechercher par nom…" autocomplete="off">
      <div class="security-multi-options" data-security-options role="group" aria-label="Choisir : ${esc(label)}"></div>
      <div class="security-multi-footer"><small data-security-visible-count></small><button class="btn sm primary" type="button" data-security-done>Terminer</button></div>
    </div>
  </div>`;
}

function bindSecurityMultiPickers(root, onChange) {
  const widgets = Array.from(root.querySelectorAll('[data-security-multi]'));
  const close = widget => {
    const popup = widget.querySelector('[data-security-popover]');
    popup.classList.add('hidden');
    widget.querySelector('[data-security-trigger]').setAttribute('aria-expanded', 'false');
    widget.classList.remove('security-multi-open');
  };
  widgets.forEach(widget => {
    const select = widget.querySelector('select[multiple]');
    const trigger = widget.querySelector('[data-security-trigger]');
    const text = widget.querySelector('[data-security-trigger-text]');
    const chips = widget.querySelector('[data-security-chips]');
    const search = widget.querySelector('[data-security-search]');
    const options = widget.querySelector('[data-security-options]');
    const popup = widget.querySelector('[data-security-popover]');
    const counter = widget.querySelector('[data-security-visible-count]');
    const available = Array.from(select.options).filter(option => !option.disabled && option.value);
    const isRole = select.id === 'securityPolicyBypassRoles';
    const noun = isRole ? ['rôle', 'rôles'] : ['salon strict', 'salons stricts'];
    const create = (tag, className, label) => {
      const element = document.createElement(tag);
      element.className = className;
      if (label != null) element.textContent = label;
      return element;
    };
    const setSelected = (option, selected) => {
      if (option.selected === selected) return;
      option.selected = selected;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const paint = () => {
      const selected = available.filter(option => option.selected);
      text.textContent = selected.length
        ? `${selected.length} ${selected.length > 1 ? noun[1] : noun[0]} sélectionné${selected.length > 1 ? 's' : ''}`
        : (isRole ? 'Sélectionner les rôles bypass' : 'Sélectionner les salons stricts');
      chips.replaceChildren();
      if (!selected.length) {
        chips.appendChild(create('span', 'security-multi-empty', isRole ? 'Aucun rôle bypass' : 'Aucun salon strict'));
      }
      for (const option of selected) {
        const pill = create('span', 'security-multi-chip');
        pill.appendChild(create('span', 'security-multi-chip-label', option.textContent));
        const remove = create('button', 'security-multi-chip-remove', '×');
        remove.type = 'button';
        remove.setAttribute('aria-label', `Retirer ${option.textContent}`);
        remove.addEventListener('click', () => setSelected(option, false));
        pill.appendChild(remove);
        chips.appendChild(pill);
      }
      const query = search.value.trim().toLocaleLowerCase('fr');
      const matching = available.filter(option => !query || option.textContent.toLocaleLowerCase('fr').includes(query));
      options.replaceChildren();
      for (const option of matching) {
        const choice = create('button', 'security-multi-option', null);
        choice.type = 'button';
        choice.setAttribute('role', 'checkbox');
        choice.setAttribute('aria-checked', String(option.selected));
        choice.classList.toggle('security-multi-option-checked', option.selected);
        choice.appendChild(create('span', 'security-multi-check', option.selected ? '✓' : ''));
        choice.appendChild(create('span', 'security-multi-option-label', option.textContent));
        choice.addEventListener('click', () => setSelected(option, !option.selected));
        options.appendChild(choice);
      }
      if (!matching.length) {
        options.appendChild(create('div', 'security-multi-no-results', available.length ? 'Aucun résultat trouvé.' : 'Aucun élément disponible.'));
      }
      counter.textContent = `${selected.length} sélectionné${selected.length > 1 ? 's' : ''} · ${matching.length} disponibles`;
    };
    trigger.addEventListener('click', () => {
      const wasClosed = popup.classList.contains('hidden');
      widgets.forEach(close);
      if (wasClosed) {
        widget.classList.add('security-multi-open');
        popup.classList.remove('hidden');
        trigger.setAttribute('aria-expanded', 'true');
        search.focus();
      }
    });
    // La sélection native reste la source de vérité ; une modification par
    // bouton « Vider » met également à jour les pastilles et le brouillon.
    select.addEventListener('change', () => {
      paint();
      if (typeof onChange === 'function') onChange();
    });
    search.addEventListener('input', paint);
    popup.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(widget); trigger.focus(); }
    });
    widget.querySelector('[data-security-done]').addEventListener('click', () => { close(widget); trigger.focus(); });
    paint();
  });
  if (state.securityPickerOutsideHandler) {
    document.removeEventListener('pointerdown', state.securityPickerOutsideHandler);
  }
  const outside = event => {
    if (!root.isConnected) {
      document.removeEventListener('pointerdown', outside);
      if (state.securityPickerOutsideHandler === outside) state.securityPickerOutsideHandler = null;
      return;
    }
    for (const widget of widgets) if (!widget.contains(event.target)) close(widget);
  };
  state.securityPickerOutsideHandler = outside;
  document.addEventListener('pointerdown', outside);
}

function clearSecurityPickerSelection(select) {
  if (!select) return;
  let changed = false;
  for (const option of select.options) {
    if (!option.selected) continue;
    option.selected = false;
    changed = true;
  }
  // Identique à une suppression par pastille. N'appelle aucune API.
  if (changed) select.dispatchEvent(new Event('change', { bubbles: true }));
}


const roles = [
  ['101', '💠 [O] Owner'], ['102', '🤖 Bot'], ['103', '🛡️ Modérateur'],
  ['104', '✨ Designer'], ['105', '🎉 Animateur'], ['106', '👑 Administrateur']
];
const channels = [
  ['201', '🔄 trade'], ['202', '🏀 ✧giveaway✧'], ['203', '💬 général'],
  ['204', '📸 médias'], ['205', '📢 annonces'], ['206', '🎮 gaming'],
  ['207', '🔊 vocal-chat'], ['208', '📜 règlement']
];
const presets = {
  spam:{roles:['101','102'],channels:['201','202']},
  links:{roles:['101'],channels:['201','203']},
  mentions:{roles:['101','103'],channels:['203']},
  caps:{roles:['101'],channels:['203','205']}
};
let activePolicy = 'spam';
let draft = null;
const byId = id => document.getElementById(id);
const selected = select => [...select.selectedOptions].map(item => item.value).filter(Boolean);
function optionsMarkup(data, selectedIds) {
  return data.map(([id,label]) => `<option value="${esc(id)}" ${selectedIds.includes(id) ? 'selected' : ''}>${esc(label)}</option>`).join('');
}
function setFeedback(message, ok = false) {
  const result = byId('saveResult');
  result.textContent = message;
  result.classList.toggle('preview-feedback-ok',ok);
}
function draw() {
  const saved = presets[activePolicy];
  const value = draft?.policy === activePolicy ? draft : saved;
  byId('rolePicker').innerHTML = securityMultiPickerMarkup(
    'securityPolicyBypassRoles',
    optionsMarkup(roles, value.roles),
    'Sélectionner les rôles bypass',
    'Rôles bypass'
  );
  byId('channelPicker').innerHTML = securityMultiPickerMarkup(
    'securityPolicyStrictChannels',
    optionsMarkup(channels, value.channels),
    'Sélectionner les salons stricts',
    'Salons stricts'
  );
  const wrapper = document.querySelector('.preview-form-grid');
  bindSecurityMultiPickers(wrapper, () => {
    draft = {policy:activePolicy,roles:selected(byId('securityPolicyBypassRoles')),channels:selected(byId('securityPolicyStrictChannels'))};
    byId('draftState').classList.remove('hidden');
    setFeedback('Sélections modifiées : rien n’est enregistré tant que tu ne confirmes pas.');
  });
  const names = {spam:'Anti-spam',links:'Anti-liens',mentions:'Anti-mentions',caps:'Anti-majuscules'};
  byId('roleHelp').textContent = `Les rôles choisis peuvent contourner uniquement ${names[activePolicy]}.`;
  byId('draftState').classList.toggle('hidden',!draft||draft.policy!==activePolicy);
}
byId('protectionMode').addEventListener('change', event => {
  // Les brouillons de chaque filtre sont conservés pendant la démonstration.
  if(draft && draft.policy) {
    window.previewDrafts = window.previewDrafts || {};
    window.previewDrafts[draft.policy] = draft;
  }
  activePolicy = event.target.value;
  draft = (window.previewDrafts || {})[activePolicy] || null;
  setFeedback('Aucun changement n’a été envoyé à Discord.');
  draw();
});
byId('clearRoles').addEventListener('click', () =>
  clearSecurityPickerSelection(byId('securityPolicyBypassRoles')));
byId('clearChannels').addEventListener('click', () =>
  clearSecurityPickerSelection(byId('securityPolicyStrictChannels')));
byId('saveDemo').addEventListener('click', () => {
  if (draft?.policy === activePolicy) {
    presets[activePolicy] = {roles:[...draft.roles],channels:[...draft.channels]};
    delete (window.previewDrafts||{})[activePolicy];
    draft = null;
    byId('draftState').classList.add('hidden');
  }
  setFeedback('✓ Démo mise à jour sur cette page uniquement. Aucun changement n’a été enregistré sur Discord.',true);
});
draw();
