"""SentriX Dashboard V18 — single advanced control-center UI.

V18 intentionally adds ONE sidebar destination (Centre avancé) and keeps the product-grade
features inside that page. It patches the exact Unified V2 response program through the same
request-time authority used by the stable V16 hotfix.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-product-ui-v18")

BUILD = "v18-product-center"
MARKER = "sentrix-dashboard-product-ui-v18"
JS_MARKER = "__sentrixProductUiV18"

_STYLE = f'''<style id="{MARKER}">
.p18-tabs{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;padding:5px;border:1px solid var(--line);border-radius:10px;background:#101419}}
.p18-tab{{border:0;background:transparent;color:var(--muted);padding:8px 11px;border-radius:7px;cursor:pointer;font-size:11px;font-weight:850}}
.p18-tab:hover{{background:#171d24;color:var(--text)}}.p18-tab.active{{background:#1a3045;color:#cce8ff;box-shadow:inset 0 0 0 1px #356a98}}
.p18-grid{{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:12px}}.p18-card{{grid-column:span 6;border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:15px;min-width:0}}.p18-card.full{{grid-column:1/-1}}.p18-card.third{{grid-column:span 4}}
.p18-card h3{{margin:0;font-size:14px}}.p18-card>p{{margin:4px 0 12px;color:var(--muted);font-size:10px}}.p18-actions{{display:flex;gap:7px;flex-wrap:wrap}}.p18-kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin-bottom:12px}}
.p18-kpi{{border:1px solid var(--line);background:#12171d;border-radius:9px;padding:11px}}.p18-kpi small{{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;font-weight:900}}.p18-kpi strong{{display:block;font-size:21px;margin-top:2px}}
.p18-table{{width:100%;border-collapse:collapse}}.p18-table th,.p18-table td{{padding:9px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:10px;vertical-align:middle}}.p18-table th{{color:var(--muted);font-size:9px;text-transform:uppercase}}.p18-table tr:last-child td{{border-bottom:0}}
.p18-search{{display:flex;gap:8px;margin-bottom:10px}}.p18-search input{{flex:1;border:1px solid var(--line2);background:#10151b;color:var(--text);border-radius:8px;padding:9px 10px}}.p18-result-list{{display:grid;gap:7px}}.p18-result{{display:flex;align-items:center;justify-content:space-between;gap:10px;border:1px solid var(--line);background:#11171d;border-radius:9px;padding:9px 10px}}.p18-result b{{display:block;font-size:11px}}.p18-result small{{display:block;color:var(--muted);font-size:9px;margin-top:2px}}
.p18-form{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}}.p18-form .full{{grid-column:1/-1}}.p18-scope-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:8px}}.p18-scope{{display:flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:8px;padding:8px;background:#11171d;font-size:10px}}
.p18-diff{{display:grid;gap:6px;max-height:440px;overflow:auto}}.p18-diff-row{{display:grid;grid-template-columns:minmax(120px,.8fr) minmax(0,1fr) minmax(0,1fr);gap:8px;border-bottom:1px solid var(--line);padding:7px 0;font-size:9px}}.p18-diff-row code{{white-space:pre-wrap;word-break:break-word;color:#c8d2dd}}.p18-run.ok{{color:#8ee6bd}}.p18-run.error{{color:#ff9aaa}}
@media(max-width:900px){{.p18-card,.p18-card.third{{grid-column:1/-1}}.p18-kpis{{grid-template-columns:repeat(2,minmax(0,1fr))}}.p18-scope-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:620px){{.p18-kpis,.p18-form,.p18-scope-grid{{grid-template-columns:1fr}}.p18-diff-row{{grid-template-columns:1fr}}}}
</style>'''

_NATIVE_JS = r'''
let p18Tab='actions';
let p18Cache={analytics:null,ops:null,automations:null,templates:null,access:null};
const P18_SCOPES=['view','configuration','members','moderation','automations','audit','templates','dangerous','admin'];
function p18Tabs(){const items=[['actions','Actions'],['members','Membres'],['automations','Automations'],['templates','Templates'],['audit','Audit'],['access','Accès dashboard']];return `<div class="p18-tabs">${items.map(([id,label])=>`<button class="p18-tab ${p18Tab===id?'active':''}" data-p18-tab="${id}">${label}</button>`).join('')}</div>`}
function p18WireTabs(){document.querySelectorAll('[data-p18-tab]').forEach(b=>b.onclick=()=>{p18Tab=b.dataset.p18Tab;renderProductV18()})}
async function p18Get(path){return api(`/api/guilds/${encodeURIComponent(state.guildId)}${path}`)}
async function p18Post(path,body){return api(`/api/guilds/${encodeURIComponent(state.guildId)}${path}`,{method:'POST',body:JSON.stringify(body||{})})}
async function p18Delete(path){return api(`/api/guilds/${encodeURIComponent(state.guildId)}${path}`,{method:'DELETE'})}
function p18Kpis(a){return `<div class="p18-kpis"><div class="p18-kpi"><small>Membres</small><strong>${number(a.members)}</strong></div><div class="p18-kpi"><small>Commandes · 24 h</small><strong>${number(a.commands_24h)}</strong></div><div class="p18-kpi"><small>Tickets ouverts</small><strong>${number(a.open_tickets)}</strong></div><div class="p18-kpi"><small>Automations · 24 h</small><strong>${number(a.automation_runs_24h)}</strong></div></div>`}
function p18Error(e){$('content').innerHTML=`<div class="notice warn">Centre avancé indisponible : ${esc(e?.message||'Erreur inconnue')}</div>`}
async function p18Base(){const [an,ops]=await Promise.all([p18Get('/product/analytics'),p18Get('/ops/overview')]);p18Cache.analytics=an.analytics||{};p18Cache.ops=ops||{};return {a:p18Cache.analytics,o:p18Cache.ops}}
async function p18RenderActions(){const {a,o}=await p18Base();$('content').innerHTML=`${p18Tabs()}${p18Kpis(a)}<div class="p18-grid"><section class="p18-card full"><h3>Recherche universelle</h3><p>Pages, membres, salons et rôles du serveur.</p><div class="p18-search"><input id="p18Search" placeholder="Ex. anti raid, ticket, @membre, salon logs…"><button class="btn" id="p18SearchGo">Rechercher</button></div><div id="p18SearchResults" class="p18-result-list"></div></section><section class="p18-card"><h3>Staff rapide</h3><p>Actions déjà reliées aux vraies API SentriX.</p><div class="p18-actions"><button class="btn primary" id="p18Repair">Réparer la config</button><button class="btn" id="p18Export">Exporter JSON</button><button class="btn" data-p18-go="verification">Vérification Discord</button><button class="btn" data-p18-go="diagnostic">Diagnostic</button></div></section><section class="p18-card"><h3>État</h3><p>Résumé opérationnel du serveur.</p><div class="list"><div class="row"><div class="row-main"><b>Discord</b><small>${o.status?.discord_ready?'Connecté':'Hors ligne'}</small></div><span class="badge ${o.status?.discord_ready?'ok':'bad'}">${o.status?.latency_ms??'—'} ms</span></div><div class="row"><div class="row-main"><b>Diagnostics</b><small>${number((o.diagnostics||[]).length)} point(s)</small></div><span class="badge ${(o.diagnostics||[]).some(x=>x.severity==='error')?'bad':(o.diagnostics||[]).length?'warn':'ok'}">${(o.diagnostics||[]).length?'À VOIR':'SAIN'}</span></div></div></section><section class="p18-card full"><h3>Commandes les plus utilisées · 7 jours</h3><p>Basé sur les vrais logs de commandes.</p><div class="list">${(a.top_commands||[]).length?(a.top_commands||[]).map(x=>`<div class="row"><div class="row-main"><b>${esc(x.name)}</b><small>Utilisations enregistrées</small></div><strong>${number(x.count)}</strong></div>`).join(''):'<div class="empty">Pas encore assez de données.</div>'}</div></section></div>`;p18WireTabs();document.querySelectorAll('[data-p18-go]').forEach(b=>b.onclick=()=>go(b.dataset.p18Go));$('p18Repair').onclick=async()=>{try{const r=await p18Post('/ops/repair',{});toast(r.message||'Réparation terminée.');await p18RenderActions()}catch(e){toast(e.message,true)}};$('p18Export').onclick=async()=>{try{const d=await p18Get('/ops/export');const blob=new Blob([JSON.stringify(d.config,null,2)],{type:'application/json'}),u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=`sentrix-${state.guildId}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(u),800)}catch(e){toast(e.message,true)}};const runSearch=async()=>{const q=$('p18Search').value.trim();if(q.length<2)return;$('p18SearchResults').innerHTML='<div class="empty">Recherche…</div>';try{const d=await p18Get(`/product/search?q=${encodeURIComponent(q)}`);$('p18SearchResults').innerHTML=(d.results||[]).length?(d.results||[]).map(r=>`<div class="p18-result"><div><b>${esc(r.title)}</b><small>${esc(r.subtitle||r.type)}</small></div>${r.type==='page'?`<button class="btn" data-p18-open="${esc(r.id)}">Ouvrir</button>`:''}</div>`).join(''):'<div class="empty">Aucun résultat.</div>';document.querySelectorAll('[data-p18-open]').forEach(b=>b.onclick=()=>go(b.dataset.p18Open))}catch(e){$('p18SearchResults').innerHTML=`<div class="notice warn">${esc(e.message)}</div>`}};$('p18SearchGo').onclick=runSearch;$('p18Search').onkeydown=e=>{if(e.key==='Enter')runSearch()}}
async function p18RenderMembers(){const a=(await p18Get('/product/analytics')).analytics||{};$('content').innerHTML=`${p18Tabs()}${p18Kpis(a)}<div class="p18-grid"><section class="p18-card full"><h3>Gestion des membres</h3><p>Recherche puis action directe avec contrôle de hiérarchie Discord.</p><div class="p18-search"><input id="p18MemberQ" placeholder="Pseudo, nom ou ID"><button class="btn" id="p18MemberGo">Rechercher</button></div><div id="p18Members" class="p18-result-list"></div></section></div>`;p18WireTabs();const search=async()=>{try{const d=await p18Get(`/product/members?q=${encodeURIComponent($('p18MemberQ').value.trim())}`);$('p18Members').innerHTML=(d.members||[]).map(m=>`<div class="p18-result"><div><b>${esc(m.display_name)} ${m.bot?'<span class="badge">BOT</span>':''}</b><small>${esc(m.id)} · ${(m.roles||[]).slice(-3).map(r=>esc(r.name)).join(', ')||'Aucun rôle'}</small></div><div class="p18-actions">${m.manageable?`<button class="btn" data-p18-timeout="${m.id}">Timeout</button><button class="btn danger" data-p18-kick="${m.id}">Kick</button><button class="btn danger" data-p18-ban="${m.id}">Ban</button>`:'<span class="badge warn">NON GÉRABLE</span>'}</div></div>`).join('')||'<div class="empty">Aucun membre trouvé.</div>';document.querySelectorAll('[data-p18-timeout]').forEach(b=>b.onclick=()=>p18MemberAction(b.dataset.p18Timeout,'timeout'));document.querySelectorAll('[data-p18-kick]').forEach(b=>b.onclick=()=>p18MemberAction(b.dataset.p18Kick,'kick'));document.querySelectorAll('[data-p18-ban]').forEach(b=>b.onclick=()=>p18MemberAction(b.dataset.p18Ban,'ban'))}catch(e){toast(e.message,true)}};$('p18MemberGo').onclick=search;$('p18MemberQ').onkeydown=e=>{if(e.key==='Enter')search()};search()}
async function p18MemberAction(id,action){if(action!=='timeout'&&!confirm(`${action.toUpperCase()} ce membre ?`))return;let body={action,reason:'Action depuis le Centre avancé SentriX'};if(action==='timeout'){const minutes=Number(prompt('Durée du timeout en minutes :','10')||0);if(!minutes)return;body.minutes=minutes}try{const r=await p18Post(`/product/members/${encodeURIComponent(id)}/action`,body);toast(r.message||'Action appliquée.');await p18RenderMembers()}catch(e){toast(e.message,true)}}
async function p18RenderAutomations(){const d=await p18Get('/product/automations');p18Cache.automations=d;$('content').innerHTML=`${p18Tabs()}<div class="p18-grid"><section class="p18-card"><h3>Créer une automation</h3><p>Déclencheur réel → action réelle dans Discord.</p><div class="p18-form"><div class="field full"><label>Nom</label><input id="p18AutoName" value="Nouvelle automation"></div><div class="field"><label>Déclencheur</label><select id="p18Trigger"><option value="member_join">Membre rejoint</option><option value="member_leave">Membre quitte</option><option value="message_contains">Message contient…</option><option value="member_role_added">Rôle ajouté</option></select></div><div class="field"><label>Action</label><select id="p18Action"><option value="send_message">Envoyer un message</option><option value="add_role">Ajouter un rôle</option><option value="remove_role">Retirer un rôle</option></select></div><div class="field full" id="p18TriggerExtra"></div><div class="field full" id="p18ActionExtra"></div></div><button class="btn primary" id="p18AutoSave" style="margin-top:10px">Créer</button></section><section class="p18-card"><h3>Automations actives</h3><p>${number((d.automations||[]).length)} règle(s) configurée(s).</p><div class="list">${(d.automations||[]).map(x=>`<div class="row"><div class="row-main"><b>${esc(x.name)}</b><small>${esc(x.trigger_type)} → ${esc(x.action_type)}</small></div><button class="btn danger" data-p18-auto-del="${x.id}">Supprimer</button></div>`).join('')||'<div class="empty">Aucune automation.</div>'}</div></section><section class="p18-card full"><h3>Dernières exécutions</h3><p>Résultats réels du moteur d’automation.</p><table class="p18-table"><thead><tr><th>Automation</th><th>État</th><th>Détail</th><th>Date</th></tr></thead><tbody>${(d.runs||[]).map(r=>`<tr><td>#${esc(r.automation_id)}</td><td class="p18-run ${esc(r.status)}">${esc(r.status)}</td><td>${esc(r.detail||'')}</td><td>${r.created_at?new Date(Number(r.created_at)*1000).toLocaleString('fr-FR'):'—'}</td></tr>`).join('')||'<tr><td colspan="4">Aucune exécution.</td></tr>'}</tbody></table></section></div>`;p18WireTabs();const draw=()=>{const t=$('p18Trigger').value,a=$('p18Action').value;$('p18TriggerExtra').innerHTML=t==='message_contains'?'<label>Texte à détecter</label><input id="p18TriggerText" placeholder="mot ou phrase">':t==='member_role_added'?`<label>Rôle déclencheur</label><select id="p18TriggerRole">${roleOptions('')}</select>`:'';$('p18ActionExtra').innerHTML=a==='send_message'?`<div class="p18-form"><div class="field"><label>Salon</label><select id="p18ActionChannel">${channelOptions('')}</select></div><div class="field full"><label>Message</label><textarea id="p18ActionText" placeholder="Bienvenue {member} sur {guild} !"></textarea></div></div>`:`<label>Rôle</label><select id="p18ActionRole">${roleOptions('')}</select>`};$('p18Trigger').onchange=draw;$('p18Action').onchange=draw;draw();$('p18AutoSave').onclick=async()=>{const trigger_type=$('p18Trigger').value,action_type=$('p18Action').value;const trigger=trigger_type==='message_contains'?{text:$('p18TriggerText')?.value||''}:trigger_type==='member_role_added'?{role_id:$('p18TriggerRole')?.value||''}:{};const action=action_type==='send_message'?{channel_id:$('p18ActionChannel')?.value||'',text:$('p18ActionText')?.value||''}:{role_id:$('p18ActionRole')?.value||''};try{const r=await p18Post('/product/automations',{name:$('p18AutoName').value,trigger_type,trigger,action_type,action,enabled:true});toast(r.message||'Automation créée.');await p18RenderAutomations()}catch(e){toast(e.message,true)}};document.querySelectorAll('[data-p18-auto-del]').forEach(b=>b.onclick=async()=>{if(!confirm('Supprimer cette automation ?'))return;try{const r=await p18Delete(`/product/automations/${encodeURIComponent(b.dataset.p18AutoDel)}`);toast(r.message||'Supprimée.');await p18RenderAutomations()}catch(e){toast(e.message,true)}})}
async function p18RenderTemplates(){const d=await p18Get('/product/templates');p18Cache.templates=d;$('content').innerHTML=`${p18Tabs()}<div class="p18-grid"><section class="p18-card"><h3>Nouveau template</h3><p>Sauvegarde la configuration actuelle pour la réutiliser.</p><div class="field"><label>Nom</label><input id="p18TemplateName" placeholder="Ex. Serveur communautaire"></div><button class="btn primary" id="p18TemplateCreate" style="margin-top:10px">Créer depuis la config actuelle</button></section><section class="p18-card"><h3>Templates enregistrés</h3><p>${number((d.templates||[]).length)} template(s).</p><div class="list">${(d.templates||[]).map(t=>`<div class="row"><div class="row-main"><b>${esc(t.name)}</b><small>${t.created_at?new Date(Number(t.created_at)*1000).toLocaleString('fr-FR'):'—'}</small></div><button class="btn" data-p18-template="${t.id}">Appliquer</button></div>`).join('')||'<div class="empty">Aucun template.</div>'}</div></section></div>`;p18WireTabs();$('p18TemplateCreate').onclick=async()=>{try{const r=await p18Post('/product/templates',{name:$('p18TemplateName').value});toast(r.message||'Template créé.');await p18RenderTemplates()}catch(e){toast(e.message,true)}};document.querySelectorAll('[data-p18-template]').forEach(b=>b.onclick=async()=>{if(!confirm('Appliquer ce template à la configuration actuelle ?'))return;try{const r=await p18Post(`/product/templates/${encodeURIComponent(b.dataset.p18Template)}/apply`,{});toast(r.message||'Template appliqué.');await selectGuild(state.guildId);p18Tab='templates';await renderProductV18()}catch(e){toast(e.message,true)}})}
async function p18RenderAudit(){const o=await p18Get('/ops/overview');$('content').innerHTML=`${p18Tabs()}<div class="p18-grid"><section class="p18-card"><h3>Historique</h3><p>Sélectionne une version pour comparer avec la configuration actuelle.</p><div class="list">${(o.history||[]).slice(0,20).map(h=>`<div class="row"><div class="row-main"><b>${esc((h.changed_keys||[]).join(', ')||'Configuration')}</b><small>${h.created_at?new Date(Number(h.created_at)*1000).toLocaleString('fr-FR'):'—'} · ${esc(h.username||h.user_id||'Utilisateur')}</small></div><button class="btn" data-p18-diff="${h.id}">Comparer</button></div>`).join('')||'<div class="empty">Aucun historique.</div>'}</div></section><section class="p18-card"><h3>Diff visuel</h3><p>Ancienne valeur → valeur actuelle.</p><div id="p18Diff" class="p18-diff"><div class="empty">Choisis une version.</div></div></section></div>`;p18WireTabs();document.querySelectorAll('[data-p18-diff]').forEach(b=>b.onclick=async()=>{try{const d=await p18Get(`/product/audit/${encodeURIComponent(b.dataset.p18Diff)}/diff`);$('p18Diff').innerHTML=(d.diff||[]).length?(d.diff||[]).map(x=>`<div class="p18-diff-row"><b>${esc(x.path)}</b><code>${esc(JSON.stringify(x.before))}</code><code>${esc(JSON.stringify(x.after))}</code></div>`).join(''):'<div class="empty">Aucune différence avec la configuration actuelle.</div>'}catch(e){toast(e.message,true)}})}
async function p18RenderAccess(){let d;try{d=await p18Get('/product/access')}catch(e){$('content').innerHTML=`${p18Tabs()}<div class="notice warn">${esc(e.message)} Cette vue est réservée aux administrateurs Discord.</div>`;p18WireTabs();return}p18Cache.access=d;$('content').innerHTML=`${p18Tabs()}<div class="p18-grid"><section class="p18-card"><h3>Déléguer le dashboard</h3><p>Donne uniquement les permissions nécessaires à un rôle Discord.</p><div class="field"><label>Rôle</label><select id="p18AccessRole">${roleOptions('')}</select></div><div class="p18-scope-grid">${P18_SCOPES.map(s=>`<label class="p18-scope"><input type="checkbox" data-p18-scope="${s}" ${s==='view'?'checked':''}>${s}</label>`).join('')}</div><button class="btn primary" id="p18AccessSave" style="margin-top:10px">Enregistrer l’accès</button></section><section class="p18-card"><h3>Accès existants</h3><p>${number((d.grants||[]).length)} délégation(s).</p><div class="list">${(d.grants||[]).map(g=>`<div class="row"><div class="row-main"><b>${esc(g.name||g.principal_id)}</b><small>${esc((g.scopes||[]).join(', '))}</small></div><button class="btn danger" data-p18-access-del="${esc(g.principal_type)}:${esc(g.principal_id)}">Retirer</button></div>`).join('')||'<div class="empty">Aucun accès délégué.</div>'}</div></section></div>`;p18WireTabs();$('p18AccessSave').onclick=async()=>{const role_id=$('p18AccessRole').value,scopes=[...document.querySelectorAll('[data-p18-scope]:checked')].map(x=>x.dataset.p18Scope);try{const r=await p18Post('/product/access',{principal_type:'role',principal_id:role_id,scopes});toast(r.message||'Accès enregistré.');await p18RenderAccess()}catch(e){toast(e.message,true)}};document.querySelectorAll('[data-p18-access-del]').forEach(b=>b.onclick=async()=>{const [t,id]=b.dataset.p18AccessDel.split(':');if(!confirm('Retirer cet accès dashboard ?'))return;try{const r=await p18Delete(`/product/access/${encodeURIComponent(t)}/${encodeURIComponent(id)}`);toast(r.message||'Accès retiré.');await p18RenderAccess()}catch(e){toast(e.message,true)}})}
async function renderProductV18(){try{if(p18Tab==='members')return await p18RenderMembers();if(p18Tab==='automations')return await p18RenderAutomations();if(p18Tab==='templates')return await p18RenderTemplates();if(p18Tab==='audit')return await p18RenderAudit();if(p18Tab==='access')return await p18RenderAccess();return await p18RenderActions()}catch(e){p18Error(e)}}
'''


def patch_html(html: str) -> str:
    source = str(html or "")
    if JS_MARKER in source and MARKER in source:
        return source

    tag = '<script id="sentrix-dashboard-unified-v2">'
    start = source.find(tag)
    if start < 0:
        return source
    body_start = start + len(tag)
    end = source.find("</script>", body_start)
    if end < 0:
        return source
    body = source[body_start:end]

    old_admin = '["Administration",[["config","Configuration","CF"],["access","Accès & commandes","AC"],["diagnostic","Diagnostic","DG"]]]'
    new_admin = '["Administration",[["config","Configuration","CF"],["access","Accès & commandes","AC"],["diagnostic","Diagnostic","DG"],["product","Centre avancé","PX"]]]'
    if old_admin in body:
        body = body.replace(old_admin, new_admin, 1)
    elif '["product","Centre avancé","PX"]' not in body:
        return source

    meta_anchor = 'diagnostic:["Diagnostic","Permissions, ressources cassées et état des modules."],'
    product_meta = 'product:["Centre avancé","Actions staff, automations, membres, audit, templates et accès dashboard."],'
    if product_meta not in body:
        if meta_anchor not in body:
            return source
        body = body.replace(meta_anchor, meta_anchor + product_meta, 1)

    render_anchor = 'async function render(force=false)'
    if JS_MARKER not in body:
        if render_anchor not in body:
            return source
        body = body.replace(render_anchor, f'window.{JS_MARKER}=true;\n' + _NATIVE_JS + '\n' + render_anchor, 1)

    switch_anchor = "case'diagnostic':await renderDiagnostic();break;default:await renderOverview()"
    switch_product = "case'diagnostic':await renderDiagnostic();break;case'product':await renderProductV18();break;default:await renderOverview()"
    if switch_product not in body:
        if switch_anchor not in body:
            return source
        body = body.replace(switch_anchor, switch_product, 1)

    source = source[:body_start] + body + source[end:]
    if MARKER not in source and "</head>" in source:
        source = source.replace("</head>", _STYLE + "\n</head>", 1)
    if 'name="sentrix-dashboard-product-build"' not in source and "</head>" in source:
        source = source.replace("</head>", f'<meta name="sentrix-dashboard-product-build" content="{BUILD}">\n</head>', 1)
    return source


def install(dashboard) -> bool:
    from web import dashboard_live_response_v15
    from web import dashboard_product_v18

    dashboard_product_v18.install(dashboard)

    current = dashboard_live_response_v15.patch_html
    if not getattr(current, "_sentrix_product_ui_v18", False):
        previous_patch = current

        def v18_patch(html: str) -> str:
            return patch_html(previous_patch(html))

        v18_patch._sentrix_product_ui_v18 = True
        v18_patch._sentrix_previous_patch = previous_patch
        dashboard_live_response_v15.patch_html = v18_patch

    current_build = dashboard.build_app
    if not getattr(current_build, "_sentrix_product_runtime_v18", False):
        previous_build = current_build

        def build_with_v18_runtime(bot):
            dashboard_product_v18.install_runtime(bot)
            return previous_build(bot)

        build_with_v18_runtime._sentrix_product_runtime_v18 = True
        build_with_v18_runtime._sentrix_previous = previous_build
        dashboard.build_app = build_with_v18_runtime

    dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))
    ok = JS_MARKER in dashboard.INDEX_HTML and MARKER in dashboard.INDEX_HTML and '["product","Centre avancé","PX"]' in dashboard.INDEX_HTML
    logger.info("Dashboard Product UI V18 installed=%s: one advanced control-center page.", ok)
    return ok


__all__ = ["install", "patch_html", "BUILD", "MARKER", "JS_MARKER"]
