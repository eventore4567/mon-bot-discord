"""SentriX Dashboard V17 — useful actions instead of technical menu clutter.

V17 runs after the live-response V15 + UI V16 chain and patches the exact native V2
browser program returned by /app.  It keeps the existing operational APIs as the source
of truth, but replaces the separate Staff activity / Audit / Backups / Maintenance /
Integrations navigation entries with one action-oriented page.

Every primary control on the page either calls an existing SentriX API or navigates to an
existing functional dashboard page.  No decorative/fake backend actions are introduced.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-action-hub-v17")

BUILD = "v17-useful-actions"
MARKER = "__sentrixActionHubV17"
STYLE_MARKER = "sentrix-dashboard-action-hub-v17"

_STYLE = f'''<style id="{STYLE_MARKER}">
.sx17-hero{{grid-column:1/-1;border:1px solid #315d87;background:linear-gradient(135deg,#15283a,#15191f 62%);border-radius:14px;padding:18px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:center}}
.sx17-hero h2{{margin:0;font-size:21px;letter-spacing:-.03em}}.sx17-hero p{{margin:5px 0 0;color:var(--muted);max-width:720px;font-size:12px}}
.sx17-status{{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}}
.sx17-zone{{grid-column:1/-1;display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:12px}}
.sx17-panel{{grid-column:span 8;border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:15px;min-width:0}}
.sx17-panel.side{{grid-column:span 4}}.sx17-panel.full{{grid-column:1/-1}}
.sx17-panel-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:12px}}.sx17-panel-head h3{{margin:0;font-size:15px}}.sx17-panel-head p{{margin:4px 0 0;color:var(--muted);font-size:10px}}
.sx17-actions{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}
.sx17-action{{border:1px solid var(--line);background:#11171e;border-radius:10px;padding:12px;display:flex;flex-direction:column;align-items:flex-start;gap:8px;min-height:112px}}
.sx17-action strong{{font-size:12px}}.sx17-action small{{color:var(--muted);font-size:10px;line-height:1.45;flex:1}}.sx17-action .btn{{min-height:32px}}
.sx17-shortcuts{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}}
.sx17-shortcut{{min-height:82px;border:1px solid var(--line);background:#11171e;border-radius:10px;padding:11px;text-align:left;cursor:pointer;color:var(--text)}}
.sx17-shortcut:hover{{border-color:#416c92;background:#16202a}}.sx17-shortcut b{{display:block;font-size:11px}}.sx17-shortcut span{{display:block;color:var(--muted);font-size:9px;margin-top:4px;line-height:1.4}}
.sx17-result{{border:1px solid var(--line);background:#0f141a;border-radius:10px;padding:11px;min-height:72px}}.sx17-result b{{display:block;font-size:11px}}.sx17-result span{{display:block;color:var(--muted);font-size:10px;margin-top:4px;line-height:1.45;word-break:break-word}}
.sx17-result.ok{{border-color:#34624e}}.sx17-result.bad{{border-color:#703640}}
.sx17-policy{{display:grid;grid-template-columns:minmax(140px,1fr) minmax(180px,1fr);gap:8px;margin-top:8px}}.sx17-policy .field.full{{grid-column:1/-1}}
.sx17-history{{display:grid;gap:7px}}.sx17-history .row{{background:#10161c}}
@media(max-width:980px){{.sx17-panel,.sx17-panel.side{{grid-column:1/-1}}.sx17-shortcuts{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:700px){{.sx17-hero{{grid-template-columns:1fr}}.sx17-status{{justify-content:flex-start}}.sx17-actions,.sx17-shortcuts,.sx17-policy{{grid-template-columns:1fr}}}}
</style>'''

_NATIVE_JS = r'''
let v17LastAction={title:'Prêt',detail:'Choisis une action. SentriX affichera ici le résultat réel.',ok:null};
function v17SetResult(title,detail,ok=true){v17LastAction={title,detail,ok};const box=$('v17LastAction');if(box){box.className=`sx17-result ${ok===true?'ok':ok===false?'bad':''}`;box.innerHTML=`<b>${esc(title)}</b><span>${esc(detail)}</span>`}}
function v17ApplyResult(){v17SetResult(v17LastAction.title,v17LastAction.detail,v17LastAction.ok)}
async function v17Run(button,label,work,{refresh=false}={}){if(button)button.disabled=true;try{const data=await work();const detail=data?.message||'Action terminée.';v17SetResult(label,detail,true);toast(detail);if(refresh){await renderActionsV17();v17ApplyResult()}return data}catch(e){const msg=e?.message||'Action impossible.';v17SetResult(label,msg,false);toast(msg,true);return null}finally{if(button&&document.body.contains(button))button.disabled=false}}
function v17Download(name,data){const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function v17Shortcut(id,title,copy){return `<button type="button" class="sx17-shortcut" data-v17-go="${esc(id)}"><b>${esc(title)}</b><span>${esc(copy)}</span></button>`}
async function renderActionsV17(){
  const o=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/overview`);
  const diagnostics=o.diagnostics||[], history=o.history||[], maintenance=o.maintenance||{}, policies=o.policies||[];
  const severe=diagnostics.filter(x=>x.severity==='error').length;
  $('content').innerHTML=`<div class="grid">
    <section class="sx17-hero"><div><h2>Actions utiles</h2><p>Les commandes qu’on utilise vraiment, au même endroit. Chaque bouton ci-dessous agit sur SentriX ou ouvre un outil déjà fonctionnel.</p></div><div class="sx17-status"><span class="badge ${diagnostics.length?(severe?'bad':'warn'):'ok'}">${diagnostics.length?number(diagnostics.length)+' diagnostic(s)':'CONFIG SAINE'}</span><span class="badge ${maintenance.enabled?'warn':'ok'}">${maintenance.enabled?'MAINTENANCE ACTIVE':'MODE NORMAL'}</span></div></section>
    <div class="sx17-zone">
      <section class="sx17-panel"><div class="sx17-panel-head"><div><h3>Staff rapide</h3><p>Actions immédiates, sans chercher dans cinq pages.</p></div><span class="badge blue">ACTIONS RÉELLES</span></div>
        <div class="sx17-actions">
          <div class="sx17-action"><strong>Réparer la configuration</strong><small>Nettoie automatiquement les références cassées détectées par SentriX, sans modifier les réglages sains.</small><button class="btn primary" id="v17Repair">Lancer la réparation</button></div>
          <div class="sx17-action"><strong>Sauvegarder la configuration</strong><small>Génère tout de suite un fichier JSON de la configuration actuelle du serveur.</small><button class="btn" id="v17Export">Télécharger le JSON</button></div>
          <div class="sx17-action"><strong>Restaurer un fichier</strong><small>Importe une vraie sauvegarde JSON SentriX après confirmation.</small><button class="btn" id="v17ImportButton">Choisir un fichier</button><input id="v17ImportFile" type="file" accept=".json,application/json" hidden></div>
          <div class="sx17-action"><strong>Vérification Discord</strong><small>Ouvre le panneau réel avec règlement, rôle et CAPTCHA V96.</small><button class="btn" data-v17-go="verification">Ouvrir la vérification</button></div>
        </div>
      </section>
      <aside class="sx17-panel side"><div class="sx17-panel-head"><div><h3>Maintenance</h3><p>Active-la seulement quand tu travailles sur le serveur.</p></div></div><div class="field"><label>Raison</label><input id="v17MaintenanceReason" maxlength="180" value="${esc(maintenance.reason||'')}" placeholder="Maintenance SentriX"></div><button id="v17Maintenance" class="btn ${maintenance.enabled?'danger':'primary'}" style="margin-top:10px">${maintenance.enabled?'Désactiver':'Activer'} la maintenance</button><div style="margin-top:12px" id="v17LastAction" class="sx17-result"></div></aside>
      <section class="sx17-panel full"><div class="sx17-panel-head"><div><h3>Fun & communauté</h3><p>Pas de faux Giveaway ou de faux Quiz : uniquement les outils déjà branchés au bot.</p></div></div><div class="sx17-shortcuts">${v17Shortcut('autoreact','Réactions automatiques','Choisir les emojis que SentriX ajoute aux messages.')}${v17Shortcut('embeds','Créer un embed','Préparer et publier un vrai message embed.')}${v17Shortcut('tickets','Tickets','Configurer les panneaux et le fonctionnement des tickets.')}${v17Shortcut('economy','Économie','Gérer l’économie, les récompenses et les rôles boutique.')}${v17Shortcut('notifications','Notifications','Configurer les notifications du serveur.')}${v17Shortcut('welcome','Arrivées & départs','Personnaliser ce que SentriX fait quand un membre arrive ou part.')}</div></section>
      <section class="sx17-panel"><div class="sx17-panel-head"><div><h3>Contrôle des commandes</h3><p>Bloque ou réactive une commande dans un salon précis.</p></div><span class="badge">${number(policies.length)} règle(s)</span></div><div class="sx17-policy"><div class="field"><label>Commande</label><input id="v17PolicyCommand" maxlength="120" placeholder="moderation ban"></div><div class="field"><label>Salon</label><select id="v17PolicyChannel"><option value="0">Tous les salons</option>${channelOptions('')}</select></div><div class="field full"><div class="toolbar"><button class="btn danger" id="v17PolicyOff">Bloquer</button><button class="btn" id="v17PolicyOn">Réactiver</button><button class="btn ghost" data-v17-go="access">Gestion complète</button></div></div></div></section>
      <section class="sx17-panel side"><div class="sx17-panel-head"><div><h3>Retour rapide</h3><p>Dernières versions de configuration disponibles.</p></div></div><div class="sx17-history">${history.length?history.slice(0,3).map(h=>`<div class="row"><div class="row-main"><b>${esc((h.changed_keys||[]).join(', ')||'Configuration')}</b><small>${h.created_at?new Date(Number(h.created_at)*1000).toLocaleString('fr-FR'):'—'} · ${esc(h.username||h.user_id||'utilisateur')}</small></div><button class="btn" data-v17-rollback="${h.id}">Restaurer</button></div>`).join(''):'<div class="empty">Aucune version à restaurer.</div>'}</div></section>
    </div>
  </div>`;
  v17ApplyResult();
  $('content').querySelectorAll('[data-v17-go]').forEach(b=>b.onclick=()=>go(b.dataset.v17Go));
  $('v17Repair').onclick=()=>v17Run($('v17Repair'),'Réparation',()=>api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/repair`,{method:'POST',body:'{}'}),{refresh:true});
  $('v17Export').onclick=()=>v17Run($('v17Export'),'Sauvegarde',async()=>{const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/export`);v17Download(`sentrix-${state.guildId}-config.json`,d.config);return {message:'Sauvegarde JSON téléchargée.'}});
  $('v17ImportButton').onclick=()=>$('v17ImportFile').click();
  $('v17ImportFile').onchange=async()=>{const file=$('v17ImportFile').files?.[0];if(!file)return;let cfg;try{cfg=JSON.parse(await file.text())}catch(_){v17SetResult('Import','Le fichier JSON est invalide.',false);return toast('Fichier JSON invalide.',true)}if(!confirm('Importer cette configuration sur ce serveur ?'))return;await v17Run($('v17ImportButton'),'Import',async()=>{const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/import`,{method:'POST',body:JSON.stringify(cfg)});await selectGuild(state.guildId);return d},{refresh:true})};
  $('v17Maintenance').onclick=()=>v17Run($('v17Maintenance'),'Maintenance',()=>api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/maintenance`,{method:'POST',body:JSON.stringify({enabled:!maintenance.enabled,reason:$('v17MaintenanceReason').value.trim()})}),{refresh:true});
  const setPolicy=enabled=>{const command=$('v17PolicyCommand').value.trim();if(!command){v17SetResult('Commande','Indique une commande à modifier.',false);return toast('Indique une commande.',true)}const channel=Number($('v17PolicyChannel').value)||null;return v17Run(enabled?$('v17PolicyOn'):$('v17PolicyOff'),enabled?'Commande réactivée':'Commande bloquée',()=>api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/policies`,{method:'POST',body:JSON.stringify({command_name:command,channel_id:channel,enabled})}),{refresh:true})};
  $('v17PolicyOff').onclick=()=>setPolicy(false);$('v17PolicyOn').onclick=()=>setPolicy(true);
  $('content').querySelectorAll('[data-v17-rollback]').forEach(b=>b.onclick=async()=>{if(!confirm('Restaurer cette version de configuration ?'))return;await v17Run(b,'Restauration',async()=>{const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/ops/history/${encodeURIComponent(b.dataset.v17Rollback)}/rollback`,{method:'POST',body:'{}'});await selectGuild(state.guildId);return d},{refresh:true})});
}
'''


def patch_html(html: str) -> str:
    """Patch the browser-visible Unified V2 program after V15/V16."""
    source = str(html or "")
    if MARKER in source:
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

    # V15 exposed several internal/technical pages separately. Keep their renderers and
    # deep links for compatibility, but replace the visible menu entries with one useful hub.
    technical_nav = '["diagnostic","Diagnostic","DG"],["staffactivity","Activité staff","AS"],["audit","Historique & audit","HA"],["backups","Sauvegardes","SV"],["maintenance","Maintenance","MT"],["integrations","Webhooks & intégrations","WI"]'
    useful_nav = '["diagnostic","Diagnostic","DG"],["actions","Actions utiles","UT"]'
    if technical_nav in body:
        body = body.replace(technical_nav, useful_nav, 1)
    elif '["actions","Actions utiles","UT"]' not in body:
        diagnostic_nav = '["diagnostic","Diagnostic","DG"]'
        if diagnostic_nav in body:
            body = body.replace(diagnostic_nav, diagnostic_nav + ',["actions","Actions utiles","UT"]', 1)

    # The old Automations page only summarized other pages. The actual auto-reaction page
    # remains visible and the action hub links to it directly.
    redundant_automation = '["embeds","Embeds & design","EM"],["automations","Automatisations","AU"]'
    if redundant_automation in body:
        body = body.replace(redundant_automation, '["embeds","Embeds & design","EM"]', 1)

    meta_needle = 'diagnostic:["Diagnostic","Permissions, ressources cassées et état des modules."],'
    if 'actions:["Actions utiles"' not in body and meta_needle in body:
        body = body.replace(meta_needle, meta_needle + 'actions:["Actions utiles","Staff rapide, maintenance, sauvegardes et outils communauté vraiment utilisables."],', 1)

    render_needle = "async function render(){"
    if render_needle not in body:
        return source
    body = body.replace(render_needle, f"window.{MARKER}=true;\n" + _NATIVE_JS + "\n" + render_needle, 1)

    # Add the native renderer without removing the old technical cases, so bookmarks to old
    # tabs keep working even though those tabs no longer clutter the sidebar.
    action_case = "case'actions':await renderActionsV17();break;"
    if action_case not in body:
        diagnostic_case = "case'diagnostic':await renderDiagnostic();break;"
        if diagnostic_case in body:
            body = body.replace(diagnostic_case, diagnostic_case + action_case, 1)
        else:
            return source

    source = source[:body_start] + body + source[end:]
    if STYLE_MARKER not in source and "</head>" in source:
        source = source.replace("</head>", _STYLE + "\n</head>", 1)
    if 'name="sentrix-dashboard-action-build"' not in source and "</head>" in source:
        source = source.replace("</head>", f'<meta name="sentrix-dashboard-action-build" content="{BUILD}">\n</head>', 1)
    return source


def install(dashboard) -> bool:
    """Wrap the current request-time patch chain after V16."""
    from web import dashboard_live_response_v15

    current = dashboard_live_response_v15.patch_html
    if getattr(current, "_sentrix_action_hub_v17", False):
        dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))
        return MARKER in dashboard.INDEX_HTML and STYLE_MARKER in dashboard.INDEX_HTML

    previous_patch = current

    def v17_patch(html: str) -> str:
        return patch_html(previous_patch(html))

    v17_patch._sentrix_action_hub_v17 = True
    v17_patch._sentrix_previous_patch = previous_patch
    dashboard_live_response_v15.patch_html = v17_patch

    dashboard.INDEX_HTML = patch_html(str(getattr(dashboard, "INDEX_HTML", "") or ""))
    ok = (
        MARKER in dashboard.INDEX_HTML
        and STYLE_MARKER in dashboard.INDEX_HTML
        and '["actions","Actions utiles","UT"]' in dashboard.INDEX_HTML
    )
    logger.warning(
        "Dashboard Action Hub V17 installed=%s: useful staff/community actions replace technical menu clutter.",
        ok,
    )
    return ok


__all__ = ["install", "patch_html", "BUILD", "MARKER", "STYLE_MARKER"]
