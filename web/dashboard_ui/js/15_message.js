/* ---------- éditeur de message partagé ----------
   Variables réellement remplacées par le bot (cogs/control_center_v3.render_member_template),
   insertion au curseur, aperçu Discord recalculé à la frappe. Utilisé par Bienvenue, Départs
   et, dans les lots suivants, Niveaux, Tickets et Notifications. */
const MESSAGE_VARIABLES = [
  ['Membre', [['{member}', 'Mention du membre'], ['{username}', 'Nom d’utilisateur'], ['{display_name}', 'Nom affiché']]],
  ['Serveur', [['{server}', 'Nom du serveur'], ['{member_count}', 'Nombre de membres']]],
];
function variablesButton(targetId, extra = []) {
  return `<button class="btn sm ghost" type="button" data-variables-for="${esc(targetId)}" data-variables-extra="${esc(JSON.stringify(extra))}">Variables</button>`;
}
function insertAtCursor(el, text) {
  const start = el.selectionStart ?? el.value.length, end = el.selectionEnd ?? el.value.length;
  el.value = el.value.slice(0, start) + text + el.value.slice(end);
  el.selectionStart = el.selectionEnd = start + text.length;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  el.focus();
}
function bindVariables(root = content()) {
  root.querySelectorAll('[data-variables-for]').forEach(b => b.onclick = () => {
    const target = document.getElementById(b.dataset.variablesFor) || root.querySelector(`[data-setting="${b.dataset.variablesFor}"]`);
    if (!target) return;
    let extra = []; try { extra = JSON.parse(b.dataset.variablesExtra || '[]'); } catch (_) {}
    const groups = extra.length ? [...MESSAGE_VARIABLES, ['Autres', extra]] : MESSAGE_VARIABLES;
    openModal({
      title: 'Insérer une variable',
      body: groups.map(([g, items]) => `<div><div class="nav-group" style="padding-left:0">${esc(g)}</div><div class="chips">${items.map(([v, l]) => `<button class="chip" type="button" data-insert="${esc(v)}" title="${esc(l)}"><code>${esc(v)}</code> ${esc(l)}</button>`).join('')}</div></div>`).join(''),
      actions: [{ label: 'Fermer' }],
      onOpen: () => $('modalBody').querySelectorAll('[data-insert]').forEach(c => c.onclick = () => { closeModal(); insertAtCursor(target, c.dataset.insert); }),
    });
  });
}
/* Zone d'aperçu : ``compute`` renvoie {content, embed} à partir des champs courants. */
function previewBlock(id, label = 'Aperçu') { return `<div class="field full"><div class="label-row"><span class="label">${esc(label)}</span></div><div id="${esc(id)}"></div></div>`; }
function bindPreview(root, id, compute) {
  const box = document.getElementById(id); if (!box) return () => {};
  const paint = () => { try { box.innerHTML = discordMessage(compute()); } catch (e) { box.innerHTML = notice(e.message, 'warn'); } };
  root.querySelectorAll('input,textarea,select').forEach(el => { el.addEventListener('input', paint); el.addEventListener('change', paint); });
  paint();
  return paint;
}
/* Avertissement sous un champ salon quand SentriX ne peut pas y écrire. */
function channelWarning(channelId, { embed = true } = {}) {
  if (!channelId) return '';
  const c = (state.guild?.channels || []).find(x => String(x.id) === String(channelId));
  if (!c) return `<span class="error">Ce salon n’existe plus. Choisissez-en un autre.</span>`;
  const p = c.perms; if (!p) return '';
  if (!p.view) return `<span class="error">SentriX ne voit pas ce salon.</span>`;
  if (!p.send) return `<span class="error">SentriX ne peut pas envoyer de messages dans ce salon.</span>`;
  if (embed && !p.embed) return `<span class="error">SentriX ne peut pas intégrer de liens (embeds) dans ce salon.</span>`;
  return '';
}
function bindChannelWarnings(root = content()) {
  root.querySelectorAll('select[data-channel-check]').forEach(sel => {
    const slot = sel.closest('.field')?.querySelector('[data-channel-warning]'); if (!slot) return;
    const paint = () => { slot.innerHTML = channelWarning(sel.value, { embed: sel.dataset.channelCheck !== 'text' }); sel.closest('.field').classList.toggle('invalid', Boolean(slot.innerHTML)); };
    sel.addEventListener('change', paint); paint();
  });
}
function channelField(label, key, value, opts = {}) {
  const id = opts.id || `f-${key}`;
  const attr = key ? `data-setting="${esc(key)}"` : '';
  return `<div class="field${opts.full ? ' full' : ''}"><div class="label-row"><label for="${esc(id)}">${esc(label)}</label></div><select id="${esc(id)}" ${attr} data-channel-check="${opts.embed === false ? 'text' : 'embed'}">${channelOptions(value, 'text', opts.placeholder || 'Choisir un salon')}</select><span data-channel-warning></span>${opts.hint ? `<small>${esc(opts.hint)}</small>` : ''}</div>`;
}
