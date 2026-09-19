/* ---------- Centre avancé (repris de l'ancienne couche V18 ; fusion décidée au lot 6) ---------- */
const ADV_SCOPES = ['view', 'configuration', 'members', 'moderation', 'automations', 'audit', 'templates', 'dangerous', 'admin'];

async function renderAdvanced() {
  const sub = state.sub || 'actions';
  try {
    if (sub === 'members') return await advMembers();
    if (sub === 'automations') return await advAutomations();
    if (sub === 'templates') return await advTemplates();
    if (sub === 'audit') return await advAudit();
    if (sub === 'access') return await advAccess();
    return await advActions();
  } catch (e) { errorView(e); }
}

async function advActions() {
  const [an, o] = await Promise.all([gget('/product/analytics'), opsOverview()]);
  const a = an.analytics || {};
  content().innerHTML = `<div class="grid"><div class="kpis full">${kpi('Membres', number(a.members))}${kpi('Commandes · 24 h', number(a.commands_24h))}${kpi('Tickets ouverts', number(a.open_tickets))}${kpi('Automations · 24 h', number(a.automation_runs_24h))}</div>${card('Recherche universelle', 'Pages, membres, salons et rôles du serveur.', `<div class="toolbar"><input class="search-input" id="advSearch" placeholder="Ex. anti raid, ticket, @membre, salon logs…" style="flex:1"><button class="btn" type="button" id="advSearchGo">Rechercher</button></div><div class="list" id="advSearchResults"></div>`, 'full')}${card('État', 'Résumé opérationnel du serveur.', `<div class="list"><div class="row"><div class="row-main"><b>Discord</b><small>${o.status?.discord_ready ? 'Connecté' : 'Hors ligne'}</small></div><span class="badge ${o.status?.discord_ready ? 'ok' : 'bad'}">${o.status?.latency_ms ?? '—'} ms</span></div><div class="row"><div class="row-main"><b>Diagnostics</b><small>${plural((o.diagnostics || []).length, 'point')}</small></div><span class="badge ${(o.diagnostics || []).some(x => x.severity === 'error') ? 'bad' : (o.diagnostics || []).length ? 'warn' : 'ok'}">${(o.diagnostics || []).length ? 'À voir' : 'Sain'}</span></div></div>`)}${card('Commandes les plus utilisées · 7 jours', '', `<div class="list">${(a.top_commands || []).length ? a.top_commands.map(x => `<div class="row"><div class="row-main"><b>${esc(x.name)}</b></div><strong>${number(x.count)}</strong></div>`).join('') : emptyState('Pas encore assez de données')}</div>`)}</div>`;
  const runSearch = async () => {
    const q = $('advSearch').value.trim(); if (q.length < 2) return;
    $('advSearchResults').innerHTML = '<div class="empty">Recherche…</div>';
    try {
      const d = await gget(`/product/search?q=${encodeURIComponent(q)}`);
      $('advSearchResults').innerHTML = (d.results || []).length ? d.results.map(r => `<div class="row"><div class="row-main"><b>${esc(r.title)}</b><small>${esc(r.subtitle || r.type)}</small></div>${r.type === 'page' ? `<button class="btn sm" type="button" data-adv-open="${esc(r.id)}">Ouvrir</button>` : ''}</div>`).join('') : emptyState('Aucun résultat');
      $('advSearchResults').querySelectorAll('[data-adv-open]').forEach(b => b.onclick = () => go(b.dataset.advOpen));
    } catch (e) { $('advSearchResults').innerHTML = notice(e.message, 'warn'); }
  };
  $('advSearchGo').onclick = runSearch;
  $('advSearch').onkeydown = e => { if (e.key === 'Enter') runSearch(); };
}

async function advMembers() {
  content().innerHTML = `<div class="grid">${card('Gestion des membres', 'Recherche puis action directe, avec contrôle de la hiérarchie Discord.', `<div class="toolbar"><input class="search-input" id="advMemberQ" placeholder="Pseudo, nom ou ID" style="flex:1"><button class="btn" type="button" id="advMemberGo">Rechercher</button></div><div class="list" id="advMembers"></div>`, 'full')}</div>`;
  const search = async () => {
    try {
      const d = await gget(`/product/members?q=${encodeURIComponent($('advMemberQ').value.trim())}`);
      $('advMembers').innerHTML = (d.members || []).length ? d.members.map(m => `<div class="row"><div class="row-main"><b>${esc(m.display_name)} ${m.bot ? '<span class="badge">Bot</span>' : ''}</b><small>${esc(m.id)} · ${(m.roles || []).slice(-3).map(r => esc(r.name)).join(', ') || 'Aucun rôle'}</small></div><div class="row-actions">${m.manageable ? `<button class="btn sm" type="button" data-member-action="timeout" data-member="${m.id}">Timeout</button><button class="btn sm danger" type="button" data-member-action="kick" data-member="${m.id}">Expulser</button><button class="btn sm danger" type="button" data-member-action="ban" data-member="${m.id}">Bannir</button>` : '<span class="badge warn">Non gérable</span>'}</div></div>`).join('') : emptyState('Aucun membre trouvé');
      $('advMembers').querySelectorAll('[data-member-action]').forEach(b => b.onclick = () => memberAction(b.dataset.member, b.dataset.memberAction));
    } catch (e) { toast(e.message, true); }
  };
  $('advMemberGo').onclick = search;
  $('advMemberQ').onkeydown = e => { if (e.key === 'Enter') search(); };
  search();
}
async function memberAction(id, action) {
  const body = { action, reason: 'Action depuis le dashboard SentriX' };
  if (action === 'timeout') {
    const minutes = Number(await promptDialog({ title: 'Durée du timeout', label: 'Minutes', value: '10', type: 'number', confirm: 'Appliquer' }) || 0);
    if (!minutes) return; body.minutes = minutes;
  } else if (!(await confirmDialog({ title: action === 'ban' ? 'Bannir ce membre ?' : 'Expulser ce membre ?', body: `Membre ${id}.`, confirm: action === 'ban' ? 'Bannir' : 'Expulser', danger: true }))) return;
  try { const r = await gpost(`/product/members/${encodeURIComponent(id)}/action`, body); toast(r.message || 'Action appliquée.'); await advMembers(); } catch (e) { toast(e.message, true); }
}

async function advAutomations() {
  const d = await gget('/product/automations');
  content().innerHTML = `<div class="grid">${card('Créer une automation', 'Un déclencheur réel → une action réelle dans Discord.', `<div class="fields"><div class="field full"><label for="advAutoName">Nom</label><input id="advAutoName" value="Nouvelle automation"></div><div class="field"><label for="advTrigger">Déclencheur</label><select id="advTrigger"><option value="member_join">Membre rejoint</option><option value="member_leave">Membre quitte</option><option value="message_contains">Message contient…</option><option value="member_role_added">Rôle ajouté</option></select></div><div class="field"><label for="advAction">Action</label><select id="advAction"><option value="send_message">Envoyer un message</option><option value="add_role">Ajouter un rôle</option><option value="remove_role">Retirer un rôle</option></select></div><div class="field full" id="advTriggerExtra"></div><div class="field full" id="advActionExtra"></div></div><div class="toolbar"><button class="btn primary" type="button" id="advAutoSave">Créer</button></div>`)}${card('Automations actives', plural((d.automations || []).length, 'règle'), `<div class="list">${(d.automations || []).map(x => `<div class="row"><div class="row-main"><b>${esc(x.name)}</b><small>${esc(x.trigger_type)} → ${esc(x.action_type)}</small></div><button class="btn sm danger" type="button" data-auto-del="${x.id}">Supprimer</button></div>`).join('') || emptyState('Aucune automation')}</div>`)}${card('Dernières exécutions', '', `<div class="table-wrap"><table class="table"><thead><tr><th>Automation</th><th>État</th><th>Détail</th><th>Date</th></tr></thead><tbody>${(d.runs || []).map(r => `<tr><td>#${esc(r.automation_id)}</td><td>${esc(r.status)}</td><td>${esc(r.detail || '')}</td><td>${when(r.created_at)}</td></tr>`).join('') || '<tr><td colspan="4">Aucune exécution.</td></tr>'}</tbody></table></div>`, 'full')}</div>`;
  const draw = () => {
    const t = $('advTrigger').value, a = $('advAction').value;
    $('advTriggerExtra').innerHTML = t === 'message_contains' ? '<label for="advTriggerText">Texte à détecter</label><input id="advTriggerText" placeholder="mot ou phrase">' : t === 'member_role_added' ? `<label for="advTriggerRole">Rôle déclencheur</label><select id="advTriggerRole">${roleOptions('')}</select>` : '';
    $('advActionExtra').innerHTML = a === 'send_message' ? `<div class="fields"><div class="field"><label for="advActionChannel">Salon</label><select id="advActionChannel">${channelOptions('')}</select></div><div class="field full"><label for="advActionText">Message</label><textarea id="advActionText" placeholder="Bienvenue {member} sur {guild} !"></textarea></div></div>` : `<label for="advActionRole">Rôle</label><select id="advActionRole">${roleOptions('')}</select>`;
  };
  $('advTrigger').onchange = draw; $('advAction').onchange = draw; draw();
  $('advAutoSave').onclick = async () => {
    const trigger_type = $('advTrigger').value, action_type = $('advAction').value;
    const trigger = trigger_type === 'message_contains' ? { text: $('advTriggerText')?.value || '' } : trigger_type === 'member_role_added' ? { role_id: $('advTriggerRole')?.value || '' } : {};
    const action = action_type === 'send_message' ? { channel_id: $('advActionChannel')?.value || '', text: $('advActionText')?.value || '' } : { role_id: $('advActionRole')?.value || '' };
    try { const r = await gpost('/product/automations', { name: $('advAutoName').value, trigger_type, trigger, action_type, action, enabled: true }); toast(r.message || 'Automation créée.'); await advAutomations(); } catch (e) { toast(e.message, true); }
  };
  content().querySelectorAll('[data-auto-del]').forEach(b => b.onclick = async () => { if (!(await confirmDialog({ title: 'Supprimer cette automation ?', body: 'Elle ne s’exécutera plus.', confirm: 'Supprimer', danger: true }))) return; try { await gdel(`/product/automations/${encodeURIComponent(b.dataset.autoDel)}`); await advAutomations(); } catch (e) { toast(e.message, true); } });
}

async function advTemplates() {
  const d = await gget('/product/templates');
  content().innerHTML = `<div class="grid">${card('Nouveau template', 'Sauvegarde la configuration actuelle pour la réutiliser sur un autre serveur.', `<div class="fields"><div class="field full"><label for="advTemplateName">Nom</label><input id="advTemplateName" placeholder="Ex. Serveur communautaire"></div></div><div class="toolbar"><button class="btn primary" type="button" id="advTemplateCreate">Créer depuis la configuration actuelle</button></div>`)}${card('Templates enregistrés', plural((d.templates || []).length, 'template'), `<div class="list">${(d.templates || []).map(t => `<div class="row"><div class="row-main"><b>${esc(t.name)}</b><small>${when(t.created_at)}</small></div><button class="btn sm" type="button" data-template="${t.id}">Appliquer</button></div>`).join('') || emptyState('Aucun template')}</div>`)}</div>`;
  $('advTemplateCreate').onclick = async () => { try { const r = await gpost('/product/templates', { name: $('advTemplateName').value }); toast(r.message || 'Template créé.'); await advTemplates(); } catch (e) { toast(e.message, true); } };
  content().querySelectorAll('[data-template]').forEach(b => b.onclick = async () => { if (!(await confirmDialog({ title: 'Appliquer ce template ?', body: 'La configuration actuelle sera remplacée. Une version restaurable est conservée.', confirm: 'Appliquer', danger: true }))) return; try { const r = await gpost(`/product/templates/${encodeURIComponent(b.dataset.template)}/apply`, {}); toast(r.message || 'Template appliqué.'); invalidate(); await reloadGuild(); await advTemplates(); } catch (e) { toast(e.message, true); } });
}

async function advAudit() {
  const o = await opsOverview(true);
  content().innerHTML = `<div class="grid">${card('Historique', 'Sélectionnez une version pour la comparer à la configuration actuelle.', `<div class="list">${(o.history || []).slice(0, 20).map(h => `<div class="row"><div class="row-main"><b>${esc((h.changed_keys || []).join(', ') || 'Configuration')}</b><small>${when(h.created_at)} · ${esc(h.username || h.user_id || 'Utilisateur')}</small></div><button class="btn sm" type="button" data-adv-diff="${h.id}">Comparer</button></div>`).join('') || emptyState('Aucun historique')}</div>`)}${card('Différences', 'Ancienne valeur → valeur actuelle.', `<div id="advDiff">${emptyState('Choisissez une version')}</div>`)}</div>`;
  content().querySelectorAll('[data-adv-diff]').forEach(b => b.onclick = async () => { try { const d = await gget(`/product/audit/${encodeURIComponent(b.dataset.advDiff)}/diff`); $('advDiff').innerHTML = (d.diff || []).length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Réglage</th><th>Avant</th><th>Maintenant</th></tr></thead><tbody>${d.diff.map(x => `<tr><td>${esc(x.path)}</td><td><code>${esc(JSON.stringify(x.before))}</code></td><td><code>${esc(JSON.stringify(x.after))}</code></td></tr>`).join('')}</tbody></table></div>` : emptyState('Aucune différence'); } catch (e) { toast(e.message, true); } });
}

async function advAccess() {
  let d; try { d = await gget('/product/access'); } catch (e) { content().innerHTML = notice(`${e.message} Cette vue est réservée aux administrateurs Discord.`, 'warn'); return; }
  content().innerHTML = `<div class="grid">${card('Déléguer le dashboard', 'Donnez uniquement les permissions nécessaires à un rôle Discord.', `<div class="fields"><div class="field full"><label for="advAccessRole">Rôle</label><select id="advAccessRole">${roleOptions('', 'Choisir un rôle')}</select></div></div><div class="chips">${ADV_SCOPES.map(s => `<label class="chip"><input type="checkbox" data-adv-scope="${s}" ${s === 'view' ? 'checked' : ''}> ${s}</label>`).join('')}</div><div class="toolbar"><button class="btn primary" type="button" id="advAccessSave">Enregistrer l’accès</button></div>`)}${card('Accès existants', plural((d.grants || []).length, 'délégation'), `<div class="list">${(d.grants || []).map(g => `<div class="row"><div class="row-main"><b>${esc(g.name || g.principal_id)}</b><small>${esc((g.scopes || []).join(', '))}</small></div><button class="btn sm danger" type="button" data-adv-access-del="${esc(g.principal_type)}:${esc(g.principal_id)}">Retirer</button></div>`).join('') || emptyState('Aucun accès délégué')}</div>`)}</div>`;
  $('advAccessSave').onclick = async () => { const role_id = $('advAccessRole').value; if (!role_id) return toast('Choisissez un rôle.', true); const scopes = [...content().querySelectorAll('[data-adv-scope]:checked')].map(x => x.dataset.advScope); try { const r = await gpost('/product/access', { principal_type: 'role', principal_id: role_id, scopes }); toast(r.message || 'Accès enregistré.'); await advAccess(); } catch (e) { toast(e.message, true); } };
  content().querySelectorAll('[data-adv-access-del]').forEach(b => b.onclick = async () => { const [t, id] = b.dataset.advAccessDel.split(':'); if (!(await confirmDialog({ title: 'Retirer cet accès ?', body: 'Ce rôle perdra ses droits sur le dashboard.', confirm: 'Retirer', danger: true }))) return; try { const r = await gdel(`/product/access/${encodeURIComponent(t)}/${encodeURIComponent(id)}`); toast(r.message || 'Accès retiré.'); await advAccess(); } catch (e) { toast(e.message, true); } });
}
