"""SentriX Dashboard V19 — final product polish UI.

Extends the already verified V18 Centre avancé at response time.  No extra sidebar page is
created: the useful additions live as tabs inside the existing product center.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-product-ui-v19")
BUILD = "v19-final-polish"
MARKER = "sentrix-dashboard-product-ui-v19"
JS_MARKER = "__sentrixProductUiV19"

_STYLE = f'''<style id="{MARKER}">
.p19-live-dot{{display:inline-block;width:7px;height:7px;border-radius:50%;background:#69d8a7;margin-right:6px;box-shadow:0 0 0 3px rgba(105,216,167,.10)}}
.p19-progress{{height:7px;border-radius:999px;background:#0d1116;overflow:hidden;border:1px solid var(--line);margin:9px 0 14px}}.p19-progress>i{{display:block;height:100%;background:linear-gradient(90deg,#396f9d,#64a8de);border-radius:inherit}}
.p19-check{{display:flex;align-items:center;gap:10px;padding:10px;border-bottom:1px solid var(--line)}}.p19-check:last-child{{border-bottom:0}}.p19-check-copy{{min-width:0;flex:1}}.p19-check-copy b{{display:block;font-size:11px}}.p19-check-copy small{{display:block;color:var(--muted);font-size:9px;margin-top:2px}}
.p19-selector{{display:flex;align-items:flex-start;gap:9px;width:100%}}.p19-selector input[type=checkbox]{{width:16px!important;min-width:16px!important;height:16px!important;margin-top:2px!important}}
.p19-bulkbar{{position:sticky;bottom:10px;z-index:4;display:grid;grid-template-columns:minmax(130px,1fr) minmax(140px,1fr) auto;gap:8px;align-items:end;margin-top:12px;padding:10px;border:1px solid var(--line2);border-radius:10px;background:rgba(15,20,26,.96);backdrop-filter:blur(10px)}}
.p19-flow{{display:grid;grid-template-columns:1fr auto 1fr;gap:8px;align-items:center;margin:0 0 12px;padding:10px;border:1px solid var(--line);border-radius:9px;background:#10151b}}.p19-flow-box{{padding:9px;border:1px solid var(--line2);border-radius:8px;background:#131a21}}.p19-flow-box small{{display:block;color:var(--muted);font-size:8px;text-transform:uppercase;font-weight:900}}.p19-flow-box b{{display:block;margin-top:3px;font-size:11px}}.p19-flow-arrow{{color:var(--muted);font-weight:900}}
.p19-mobile-note{{display:none}}
@media(max-width:720px){{
 .p18-tabs{{overflow-x:auto;flex-wrap:nowrap;scrollbar-width:none;padding:4px}}.p18-tab{{white-space:nowrap;flex:0 0 auto}}
 .p18-result{{align-items:flex-start;flex-direction:column}}.p18-result .p18-actions{{width:100%}}.p18-result .p18-actions .btn{{flex:1}}
 .p19-bulkbar{{position:static;grid-template-columns:1fr}}.p19-flow{{grid-template-columns:1fr}}.p19-flow-arrow{{text-align:center;transform:rotate(90deg)}}
 .p18-table{{display:block;overflow-x:auto;white-space:nowrap}}.p19-mobile-note{{display:block;color:var(--muted);font-size:9px;margin-bottom:8px}}
}}
</style>'''

_JS = r'''
window.__sentrixProductUiV19=true;
let p19LiveTimer=null;
function p19StopLive(){if(p19LiveTimer){clearInterval(p19LiveTimer);p19LiveTimer=null}}
const p19TabsBase=p18Tabs;
p18Tabs=function(){const items=[['actions','Actions'],['live','Live'],['members','Membres'],['bulk','Actions groupées'],['automations','Automations'],['onboarding','Onboarding'],['templates','Templates'],['audit','Audit'],['access','Accès dashboard']];return `<div class="p18-tabs">${items.map(([id,label])=>`<button class="p18-tab ${p18Tab===id?'active':''}" data-p18-tab="${id}">${label}</button>`).join('')}</div>`}
function p19Ago(ts){const n=Number(ts||0);if(!n)return '—';const s=Math.max(0,Math.floor(Date.now()/1000-n));if(s<60)return `${s}s`;if(s<3600)return `${Math.floor(s/60)} min`;if(s<86400)return `${Math.floor(s/3600)} h`;return `${Math.floor(s/86400)} j`}
function p19PermLabel(k){return ({manage_roles:'Gérer les rôles',manage_channels:'Gérer les salons',manage_messages:'Gérer les messages',moderate_members:'Exclure temporairement',kick_members:'Expulser',ban_members:'Bannir',manage_webhooks:'Gérer les webhooks'})[k]||k}
async function p19RenderLive(){p19StopLive();const draw=async()=>{try{const d=await p18Get('/product/live');if(p18Tab!=='live')return p19StopLive();$('content').innerHTML=`${p18Tabs()}<div class="p18-kpis"><div class="p18-kpi"><small>Discord</small><strong>${d.discord_ready?'ONLINE':'OFFLINE'}</strong></div><div class="p18-kpi"><small>Latence</small><strong>${number(d.latency_ms)} ms</strong></div><div class="p18-kpi"><small>Membres</small><strong>${number(d.members)}</strong></div><div class="p18-kpi"><small>Incidents permissions</small><strong>${number((d.missing_permissions||[]).length)}</strong></div></div><div class="p18-grid"><section class="p18-card"><h3><span class="p19-live-dot"></span>État en direct</h3><p>Actualisation automatique toutes les 15 secondes.</p><div class="list"><div class="row"><div class="row-main"><b>Salons</b></div><strong>${number(d.channels)}</strong></div><div class="row"><div class="row-main"><b>Rôles</b></div><strong>${number(d.roles)}</strong></div><div class="row"><div class="row-main"><b>Commandes · 24 h</b></div><strong>${number(d.analytics?.commands_24h)}</strong></div><div class="row"><div class="row-main"><b>Automations · 24 h</b></div><strong>${number(d.analytics?.automation_runs_24h)}</strong></div></div></section><section class="p18-card"><h3>Permissions SentriX</h3><p>Permissions Discord critiques actuellement disponibles.</p><div class="list">${Object.entries(d.permissions||{}).map(([k,v])=>`<div class="row"><div class="row-main"><b>${esc(p19PermLabel(k))}</b></div><span class="badge ${v?'ok':'bad'}">${v?'OK':'MANQUANTE'}</span></div>`).join('')}</div></section><section class="p18-card full"><h3>Activité récente</h3><p>Commandes et exécutions d’automations réellement enregistrées.</p><div class="list">${(d.activity||[]).length?(d.activity||[]).map(x=>`<div class="row"><div class="row-main"><b>${esc(x.title)}</b><small>${esc(x.detail||x.type)}</small></div><span class="badge ${x.status==='error'?'bad':x.status==='success'?'ok':'blue'}">${p19Ago(x.created_at)}</span></div>`).join(''):'<div class="empty">Aucune activité récente enregistrée.</div>'}</div></section></div>`;p18WireTabs()}catch(e){p18Error(e)}};await draw();p19LiveTimer=setInterval(draw,15000)}
async function p19RenderOnboarding(){p19StopLive();try{const d=await p18Get('/product/checklist');$('content').innerHTML=`${p18Tabs()}<div class="p18-grid"><section class="p18-card full"><h3>Configuration du serveur · ${number(d.percent)}%</h3><p>Une checklist calculée depuis la vraie configuration et les permissions Discord.</p><div class="p19-progress"><i style="width:${Math.max(0,Math.min(100,Number(d.percent)||0))}%"></i></div><div class="list">${(d.items||[]).map(x=>`<div class="p19-check"><span class="badge ${x.done?'ok':'warn'}">${x.done?'FAIT':'À FAIRE'}</span><div class="p19-check-copy"><b>${esc(x.title)}</b><small>${esc(x.detail)}</small></div>${x.done?'':`<button class="btn" data-p19-check-tab="${esc(x.tab||'overview')}" data-p19-product-tab="${esc(x.product_tab||'')}">Configurer</button>`}</div>`).join('')}</div></section></div>`;p18WireTabs();document.querySelectorAll('[data-p19-check-tab]').forEach(b=>b.onclick=()=>{const pt=b.dataset.p19ProductTab;if(pt){p18Tab=pt;renderProductV18()}else go(b.dataset.p19CheckTab)})}catch(e){p18Error(e)}}
let p19BulkMembers=[];
function p19BulkSelected(){return [...document.querySelectorAll('[data-p19-member-check]:checked')].map(x=>x.value)}
async function p19RenderBulk(){p19StopLive();let live;try{live=await p18Get('/product/live')}catch(e){return p18Error(e)};$('content').innerHTML=`${p18Tabs()}<div class="p18-grid"><section class="p18-card full"><h3>Actions groupées sécurisées</h3><p>Maximum 25 membres. Pas de mass-ban ni mass-kick : uniquement timeout et rôles.</p><div class="p19-mobile-note">Sur mobile, sélectionne les membres puis utilise la zone d’action sous la liste.</div><div class="p18-search"><input id="p19BulkQ" placeholder="Rechercher des membres"><button class="btn" id="p19BulkSearch">Rechercher</button></div><div id="p19BulkMembers" class="p18-result-list"></div><div class="p19-bulkbar"><div class="field"><label>Action</label><select id="p19BulkAction"><option value="timeout">Timeout</option><option value="add_role">Ajouter un rôle</option><option value="remove_role">Retirer un rôle</option></select></div><div class="field" id="p19BulkExtra"></div><button class="btn primary" id="p19BulkRun">Appliquer à la sélection</button></div></section></div>`;p18WireTabs();const roles=live.manageable_roles||[];const drawExtra=()=>{const a=$('p19BulkAction').value;$('p19BulkExtra').innerHTML=a==='timeout'?'<label>Minutes</label><input id="p19BulkMinutes" type="number" min="1" max="10080" value="10">':`<label>Rôle</label><select id="p19BulkRole">${roles.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('')}</select>`};drawExtra();$('p19BulkAction').onchange=drawExtra;const search=async()=>{try{const d=await p18Get(`/product/members?q=${encodeURIComponent($('p19BulkQ').value.trim())}`);p19BulkMembers=d.members||[];$('p19BulkMembers').innerHTML=p19BulkMembers.length?p19BulkMembers.map(m=>`<div class="p18-result"><label class="p19-selector"><input type="checkbox" data-p19-member-check value="${m.id}" ${m.manageable?'':'disabled'}><div><b>${esc(m.display_name)} ${m.bot?'<span class="badge">BOT</span>':''}</b><small>${esc(m.id)} · ${m.manageable?'Gérable':'Hiérarchie insuffisante'}</small></div></label></div>`).join(''):'<div class="empty">Aucun membre trouvé.</div>'}catch(e){toast(e.message,true)}};$('p19BulkSearch').onclick=search;$('p19BulkQ').onkeydown=e=>{if(e.key==='Enter')search()};$('p19BulkRun').onclick=async()=>{const ids=p19BulkSelected();if(!ids.length)return toast('Sélectionne au moins un membre.',true);const action=$('p19BulkAction').value;const body={action,member_ids:ids,reason:'Action groupée depuis le dashboard SentriX'};if(action==='timeout')body.minutes=Number($('p19BulkMinutes')?.value||10);else body.role_id=$('p19BulkRole')?.value;if(!confirm(`Appliquer ${action} à ${ids.length} membre(s) ?`))return;try{const r=await p18Post('/product/members/bulk',body);toast(r.message||'Action groupée terminée.');await search()}catch(e){toast(e.message,true)}};await search()}
const p19AutomationBase=p18RenderAutomations;
p18RenderAutomations=async function(){p19StopLive();await p19AutomationBase();const tabs=document.querySelector('.p18-tabs');if(tabs&&!document.querySelector('.p19-flow'))tabs.insertAdjacentHTML('afterend','<div class="p19-flow"><div class="p19-flow-box"><small>Quand</small><b id="p19FlowTrigger">Un événement Discord arrive</b></div><div class="p19-flow-arrow">→</div><div class="p19-flow-box"><small>Alors</small><b id="p19FlowAction">SentriX exécute une action</b></div></div>');const t=$('p18Trigger'),a=$('p18Action');const sync=()=>{const ft=$('p19FlowTrigger'),fa=$('p19FlowAction');if(ft&&t)ft.textContent=t.options[t.selectedIndex]?.text||'Événement';if(fa&&a)fa.textContent=a.options[a.selectedIndex]?.text||'Action'};if(t)t.addEventListener('change',sync);if(a)a.addEventListener('change',sync);sync()}
const p19ProductBase=renderProductV18;
renderProductV18=async function(){if(p18Tab!=='live')p19StopLive();if(p18Tab==='live')return p19RenderLive();if(p18Tab==='bulk')return p19RenderBulk();if(p18Tab==='onboarding')return p19RenderOnboarding();return p19ProductBase()}
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
    if "__sentrixProductUiV18" not in body:
        return source
    anchor = "async function render(force=false)"
    if JS_MARKER not in body:
        if anchor not in body:
            return source
        body = body.replace(anchor, _JS + "\n" + anchor, 1)
    source = source[:body_start] + body + source[end:]
    if MARKER not in source and "</head>" in source:
        source = source.replace("</head>", _STYLE + "\n</head>", 1)
    if 'name="sentrix-dashboard-product-v19-build"' not in source and "</head>" in source:
        source = source.replace("</head>", f'<meta name="sentrix-dashboard-product-v19-build" content="{BUILD}">\n</head>', 1)
    return source


def install(dashboard) -> bool:
    from web import dashboard_live_response_v15
    from web import dashboard_product_v19

    dashboard_product_v19.install(dashboard)
    current = dashboard_live_response_v15.patch_html
    if not getattr(current, "_sentrix_product_ui_v19", False):
        previous_patch = current
        def v19_patch(html: str) -> str:
            return patch_html(previous_patch(html))
        v19_patch._sentrix_product_ui_v19 = True
        v19_patch._sentrix_previous_patch = previous_patch
        dashboard_live_response_v15.patch_html = v19_patch
    dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))
    ok = JS_MARKER in dashboard.INDEX_HTML and MARKER in dashboard.INDEX_HTML and "Actions groupées" in dashboard.INDEX_HTML and "Onboarding" in dashboard.INDEX_HTML
    logger.warning("Dashboard Product UI V19 installed=%s: live + safe bulk + onboarding + mobile polish.", ok)
    return ok


__all__ = ["install", "patch_html", "BUILD", "MARKER", "JS_MARKER"]
