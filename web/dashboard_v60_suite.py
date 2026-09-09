"""Suite de finition V60 MAX : diagnostics, accès commandes et recherche des sélecteurs."""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-v60-suite")

SUITE_CSS = r'''
/* SentriX V60 MAX suite */
.sx-config-hero{display:grid;grid-template-columns:180px minmax(0,1fr);gap:18px;align-items:center;padding:20px;background:#303439;border:1px solid #484d53;border-radius:8px;margin-bottom:14px}.sx-score{width:142px;height:142px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--accent) var(--score,0%),#25292e 0);position:relative;margin:auto}.sx-score:after{content:"";position:absolute;inset:12px;border-radius:50%;background:#303439}.sx-score strong,.sx-score span{position:relative;z-index:1;text-align:center}.sx-score strong{font-size:31px}.sx-score span{display:block;color:#aaa;font-size:10px;text-transform:uppercase}.sx-summary-line{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.sx-summary-chip{padding:6px 8px;border:1px solid #50555b;border-radius:999px;font-size:10px;color:#c4c6c8}.sx-module-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.sx-module-card{background:#2e3237;border:1px solid #484d53;border-radius:7px;padding:13px}.sx-module-card h4{margin:0 0 7px;font-size:14px}.sx-module-card p{margin:7px 0 0;color:#a9abad;font-size:11px;line-height:1.45}.sx-state{display:inline-flex;padding:4px 7px;border-radius:5px;font-size:9px;font-weight:950;letter-spacing:.03em;border:1px solid #555}.sx-state.active{color:#8ce0b2;border-color:#3f7057;background:#1d3a2c}.sx-state.inactive{color:#d0d2d4;background:#30353a}.sx-state.missing{color:#e4c484;border-color:#715f3d;background:#3a3120}.sx-state.error{color:#ff9da8;border-color:#7b4149;background:#422328}
.sx-permission-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.sx-permission{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:9px 10px;border:1px solid #474c52;border-radius:6px;background:#2c3035}.sx-permission span:first-child{font-size:12px}.sx-access-grid{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(300px,.8fr);gap:14px}.sx-command-tools{display:grid;grid-template-columns:minmax(0,1fr) 180px;gap:8px;margin-bottom:10px}.sx-command-list{display:grid;gap:6px;max-height:520px;overflow:auto;padding-right:4px}.sx-command-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;padding:10px;border:1px solid #454a50;border-radius:6px;background:#2d3136}.sx-command-row b{display:block;font-size:12px}.sx-command-row small{display:block;color:#9fa2a5;margin-top:3px;font-size:10px}.sx-command-row.disabled b{color:#d9a39a}.sx-command-row.protected{opacity:.72}.sx-manager-list{display:grid;gap:7px;margin-top:10px}.sx-manager-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:9px 10px;border:1px solid #454a50;border-radius:6px}.sx-manager-row small{display:block;color:#aaa;margin-top:2px}.sx-category-checks{display:flex;gap:7px;flex-wrap:wrap;margin:9px 0}.sx-category-check{display:flex;align-items:center;gap:5px;padding:6px 8px;border:1px solid #4b5056;border-radius:6px;font-size:10px}.sx-category-check input{width:auto}.sx-scope-list{display:grid;gap:7px;margin-top:10px}.sx-scope-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:9px 10px;border:1px solid #454a50;border-radius:6px}.sx-selector-search{width:100%;border:1px solid #40454a;background:#24282d;color:#ddd;border-radius:5px;padding:7px 9px;margin-bottom:5px;font-size:11px}.sx-selector-search:focus{border-color:var(--accent)}.sx-resource-list{display:grid;gap:6px}.sx-resource-error{padding:8px 10px;border:1px solid #704047;background:#3c2529;border-radius:6px;color:#f3b0b7;font-size:11px}
@media(max-width:1100px){.sx-module-grid{grid-template-columns:1fr 1fr}.sx-access-grid{grid-template-columns:1fr}}
@media(max-width:680px){.sx-config-hero{grid-template-columns:1fr}.sx-module-grid,.sx-permission-grid{grid-template-columns:1fr}.sx-command-tools{grid-template-columns:1fr}}
'''

SUITE_JS = r'''
<script id="sentrix-v60-suite">
(() => {
  "use strict";
  if(window.__sentrixV60Suite)return;window.__sentrixV60Suite=true;
  const suite={setup:null,diagnostics:null,loadingAccess:false};
  const moduleNames={welcome:'Arrivées et départs',levels:'Niveaux',suggestions:'Suggestions',reports:'Signalements',logs:'Logs',roles:'Rôles',tickets:'Tickets',automod:'Auto-Modération',ai:'Intelligence artificielle',notifications:'Notifications sociales',moderation:'Modération'};
  const categoryNames={configuration:'Configuration',tickets:'Tickets',moderation:'Modération',securite:'Sécurité',economie:'Économie et jeux',complete:'Accès complet'};

  function ensureSuiteNav(){
    const nav=$('navigation');if(!nav)return;
    if(!nav.querySelector('[data-tab="access"]')){
      const b=document.createElement('button');b.type='button';b.dataset.tab='access';b.innerHTML='<span class="nav-icon">⌘</span>Accès & commandes';
      const general=nav.querySelector('[data-tab="general"]');nav.insertBefore(b,general||null);
    }
    tabMeta.access=['Accès & commandes','Séparez les permissions Discord de SentriX et l’accès aux commandes du serveur.'];
  }

  function norm(value){return String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('fr').replace(/[^a-z0-9@#]+/g,' ').trim()}
  function fuzzyMatch(text,query){const t=norm(text),q=norm(query);if(!q)return true;if(t.includes(q))return true;const tokens=q.split(/\s+/).filter(Boolean);return tokens.every(token=>t.includes(token))}
  function decorateSearchableSelects(root=$('fields')){
    if(!root)return;
    root.querySelectorAll('select').forEach(select=>{
      if(select.dataset.sxSearchReady==='1'||select.options.length<6||select.id==='sanctionFilter')return;
      const labels=[...select.options].map(o=>o.textContent||'');
      const likelyResource=labels.some(label=>/^\s*[@#]/.test(label))||/channel|role|salon|rôle|category|categorie/i.test(select.id+' '+select.closest('.field')?.querySelector('label')?.textContent);
      if(!likelyResource)return;
      select.dataset.sxSearchReady='1';
      const input=document.createElement('input');input.type='search';input.className='sx-selector-search';input.placeholder='Rechercher dans la liste…';input.setAttribute('aria-label','Rechercher dans la liste');
      select.parentNode.insertBefore(input,select);
      input.addEventListener('input',()=>{const q=input.value;[...select.options].forEach((option,index)=>{option.hidden=index>0&&!fuzzyMatch(option.textContent,q)});const current=select.selectedOptions[0];if(current)current.hidden=false});
    });
  }

  function statusHtml(item){return `<span class="sx-state ${esc(item.code)}">${esc(item.status)}</span>`}
  async function loadDiagnostics(force=false){if(suite.diagnostics&&!force)return suite.diagnostics;suite.diagnostics=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/diagnostics`);return suite.diagnostics}
  async function loadSetup(force=false){if(suite.setup&&!force)return suite.setup;suite.setup=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/setup-tools`);return suite.setup}
  function resetSuiteCache(){suite.setup=null;suite.diagnostics=null}

  async function renderOverviewSuite(){
    $('tabTitle').textContent='Vue d’ensemble';$('tabDescription').textContent='Vérification réelle de la configuration, des ressources Discord et des permissions de SentriX.';document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='overview'));$('saveBar').classList.add('hidden');$('fields').innerHTML='<div class="panel-section"><div class="empty">Analyse de la configuration…</div></div>';state.dirty=false;
    try{
      const d=await loadDiagnostics(true),g=state.guildData.guild||{},s=d.summary||{};
      const modules=Object.entries(d.modules||{}).map(([key,item])=>`<div class="sx-module-card"><h4>${esc(moduleNames[key]||key)}</h4>${statusHtml(item)}<p>${esc(item.detail||'')}</p></div>`).join('');
      const invalid=(d.invalid_resources||[]).map(item=>`<div class="sx-resource-error">${esc(item.field)} · ${esc(item.type)} ${esc(item.id)} n’existe plus</div>`).join('');
      $('fields').innerHTML=`<div class="panel-section"><div class="sx-config-hero"><div class="sx-score" style="--score:${Number(d.score||0)}%"><div><strong>${Number(d.score||0)}%</strong><span>configuration</span></div></div><div><h3 style="margin:0 0 6px">${esc(g.name||'Serveur')}</h3><p style="margin:0;color:#aaa">Score calculé depuis la base et les ressources Discord actuellement disponibles.</p><div class="sx-summary-line"><span class="sx-summary-chip">${Number(s.active||0)} actif(s)</span><span class="sx-summary-chip">${Number(s.inactive||0)} inactif(s)</span><span class="sx-summary-chip">${Number(s.missing||0)} non configuré(s)</span><span class="sx-summary-chip">${Number(s.errors||0)} erreur(s)</span></div></div></div><div class="sx-module-grid">${modules}</div></div>`+section('Ressources à corriger',invalid?'Une ressource supprimée ne reste jamais considérée active.':'Aucune référence cassée détectée.',invalid?`<div class="sx-resource-list">${invalid}</div>`:'<div class="empty">Toutes les ressources configurées vérifiées existent encore.</div>')+section('Accès rapides','Continuez la configuration depuis le même serveur.',`<div class="action-grid"><div class="action-card"><h3>Accès & commandes</h3><p>Permissions du bot, commandes et gestionnaires SentriX.</p><button class="btn primary" type="button" data-open-tab="access">Ouvrir</button></div><div class="action-card"><h3>Logs</h3><p>Réparez rapidement les salons de journalisation.</p><button class="btn primary" type="button" data-open-tab="logs">Ouvrir</button></div><div class="action-card"><h3>Sécurité</h3><p>Vérifiez AutoMod et le niveau de sécurité.</p><button class="btn primary" type="button" data-open-tab="security">Ouvrir</button></div></div>`);
      $('fields').querySelectorAll('[data-open-tab]').forEach(b=>b.onclick=()=>{state.tab=b.dataset.openTab;renderTab()});
    }catch(e){$('fields').innerHTML=`<div class="panel-section"><div class="empty">${esc(e.message||'Diagnostics indisponibles')}</div></div>`;toast(e.message,true)}
  }

  function permissionGrid(d){return `<div class="sx-permission-grid">${(d.permissions||[]).map(p=>`<div class="sx-permission"><span>${esc(p.name)}</span><span class="sx-state ${p.granted?'active':'inactive'}">${p.granted?'ACCORDÉE':'MANQUANTE'}</span></div>`).join('')}</div>`}
  function commandRows(setup,query='',filter='all'){
    const disabled=new Set(setup.disabled_commands||[]);
    return (setup.commands||[]).filter(c=>fuzzyMatch(c.name+' '+(c.description||''),query)).filter(c=>filter==='all'||(filter==='disabled'&&disabled.has(c.name))||(filter==='enabled'&&!disabled.has(c.name))).map(c=>{const off=disabled.has(c.name);return `<div class="sx-command-row ${off?'disabled':''} ${c.protected?'protected':''}" data-command-row><div><b>+${esc(c.name)}</b><small>${esc(c.description||'Aucune description')}</small></div><button class="btn sx-mini ${off?'primary':''}" data-command-toggle="${esc(c.name)}" data-enabled="${off?'1':'0'}" ${c.protected?'disabled':''} type="button">${c.protected?'PROTÉGÉE':off?'Réactiver':'Désactiver'}</button></div>`}).join('')||'<div class="empty">Aucune commande ne correspond à la recherche.</div>'
  }
  function managerRows(setup){return (setup.managers||[]).length?(setup.managers||[]).map(m=>`<div class="sx-manager-row"><div><b>${esc(m.name)}</b><small>${esc(m.id)} · ${(m.categories||[]).map(c=>esc(categoryNames[c]||c)).join(', ')}</small></div><button class="btn danger sx-mini" data-remove-manager="${esc(m.id)}" type="button">Retirer</button></div>`).join(''):'<div class="empty">Aucun gestionnaire supplémentaire.</div>'}
  function ignoredRows(setup){const channels=state.guildData.channels||[];return (setup.ignored_channels||[]).length?(setup.ignored_channels||[]).map(id=>{const c=channels.find(x=>String(x.id)===String(id));return `<div class="sx-scope-row"><span>#${esc(c?.name||id)}</span><button class="btn sx-mini" data-toggle-ignore="${esc(id)}" data-ignore="0" type="button">Retirer</button></div>`}).join(''):'<div class="empty">Aucun salon ignoré.</div>'}

  async function setupAction(payload){try{const result=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/setup-tools`,{method:'POST',body:JSON.stringify(payload)});toast(result.message||'Configuration appliquée.');suite.setup=null;await renderAccess()}catch(e){toast(e.message,true)}}
  function bindAccess(setup){
    const refreshCommands=()=>{$('sxCommandList').innerHTML=commandRows(setup,$('sxCommandSearch').value,$('sxCommandFilter').value);$('sxCommandList').querySelectorAll('[data-command-toggle]').forEach(b=>b.onclick=()=>setupAction({action:'command',command:b.dataset.commandToggle,enabled:b.dataset.enabled==='1'}))};
    $('sxCommandSearch').addEventListener('input',refreshCommands);$('sxCommandFilter').addEventListener('change',refreshCommands);refreshCommands();
    $('sxAddManager').onclick=()=>{const id=$('sxManagerId').value.trim(),categories=[...document.querySelectorAll('[data-manager-cat]:checked')].map(x=>x.dataset.managerCat);if(!id)return toast('Entrez un ID Discord.',true);setupAction({action:'manager',user_id:id,enabled:true,categories})};
    document.querySelectorAll('[data-remove-manager]').forEach(b=>b.onclick=()=>setupAction({action:'manager',user_id:b.dataset.removeManager,enabled:false}));
    $('sxAddIgnored').onclick=()=>{const id=$('sxIgnoredChannel').value;if(id)setupAction({action:'ignored_channel',channel_id:id,ignored:true})};document.querySelectorAll('[data-toggle-ignore]').forEach(b=>b.onclick=()=>setupAction({action:'ignored_channel',channel_id:b.dataset.toggleIgnore,ignored:false}));
    $('sxAddExempt').onclick=()=>{const id=$('sxExemptRole').value;if(id)setupAction({action:'automod_exempt_role',role_id:id,exempt:true})};
    decorateSearchableSelects($('fields'));
  }
  async function renderAccess(){
    $('tabTitle').textContent='Accès & commandes';$('tabDescription').textContent='Permissions Discord de SentriX, commandes disponibles et gestionnaires autorisés.';document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab==='access'));$('saveBar').classList.add('hidden');state.dirty=false;$('fields').innerHTML='<div class="panel-section"><div class="empty">Chargement des permissions…</div></div>';
    try{
      const [d,setup]=await Promise.all([loadDiagnostics(true),loadSetup(true)]);suite.diagnostics=d;suite.setup=setup;
      const cats=Object.entries(setup.manager_categories||categoryNames).map(([key,label])=>`<label class="sx-category-check"><input type="checkbox" data-manager-cat="${esc(key)}" ${key==='complete'?'checked':''}>${esc(label)}</label>`).join('');
      const exemptSet=new Set((setup.automod_exempt_roles||[]).map(String));
      const exemptList=exemptSet.size?`<div class="sx-scope-list">${[...exemptSet].map(id=>{const r=(state.guildData.roles||[]).find(x=>String(x.id)===id);return `<div class="sx-scope-row"><span>@${esc(r?.name||id)}</span><span class="sx-state active">EXEMPTÉ</span></div>`}).join('')}</div>`:'<div class="empty">Aucun rôle exempté de l’AutoMod.</div>';
      $('fields').innerHTML=section('Permissions du bot','Ces permissions viennent directement du rôle actuel de SentriX sur Discord. Elles sont séparées de l’accès aux commandes.',permissionGrid(d))+section('Accès aux commandes','Désactivez une commande pour tout le serveur. Les commandes protégées restent accessibles afin d’éviter de verrouiller la configuration.',`<div class="sx-command-tools"><input id="sxCommandSearch" type="search" placeholder="Rechercher une commande…"><select id="sxCommandFilter"><option value="all">Toutes</option><option value="enabled">Actives</option><option value="disabled">Désactivées</option></select></div><div id="sxCommandList" class="sx-command-list"></div>`)+section('Gestionnaires SentriX','Accordez l’accès aux catégories du bot sans donner automatiquement toutes les permissions Discord.',`<div class="sx-access-grid"><div><div class="field"><label>ID Discord du membre</label><input id="sxManagerId" inputmode="numeric" placeholder="123456789…"></div><div class="sx-category-checks">${cats}</div><button id="sxAddManager" class="btn primary" type="button">Ajouter / mettre à jour</button></div><div><div class="sx-manager-list">${managerRows(setup)}</div></div></div>`)+section('Portée des commandes','Choisissez les salons ignorés et les exemptions AutoMod.',`<div class="sx-access-grid"><div><div class="field"><label>Salon à ignorer</label><select id="sxIgnoredChannel">${channelOptions('')}</select></div><button id="sxAddIgnored" class="btn" type="button">Ajouter le salon</button><div class="sx-scope-list">${ignoredRows(setup)}</div></div><div><div class="field"><label>Rôle exempté AutoMod</label><select id="sxExemptRole">${roleOptions('')}</select></div><button id="sxAddExempt" class="btn" type="button">Ajouter l’exemption</button>${exemptList}</div></div>`);
      bindAccess(setup);
    }catch(e){$('fields').innerHTML=`<div class="panel-section"><div class="empty">${esc(e.message||'Accès indisponible')}</div></div>`;toast(e.message,true)}
  }

  const baseSelectGuild=selectGuild;selectGuild=async function(value){const changed=String(value)!==String(state.guildId);const result=await baseSelectGuild(value);if(changed)resetSuiteCache();return result};
  const baseRenderTab=renderTab;renderTab=function(){ensureSuiteNav();if(state.tab==='overview'){renderOverviewSuite();return}if(state.tab==='access'){renderAccess();return}const result=baseRenderTab();setTimeout(()=>decorateSearchableSelects($('fields')),0);return result};
  ensureSuiteNav();
})();
</script>
'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v60-suite"' in html:
        return True
    if getattr(dashboard, "_sentrix_dashboard_version", None) != "v60-max":
        logger.error("Dashboard V60 suite refusée : V60 MAX n'est pas actif.")
        return False
    if "</style>" not in html or "</body>" not in html:
        return False
    dashboard.INDEX_HTML = html.replace("</style>", SUITE_CSS + "\n</style>", 1).replace("</body>", SUITE_JS + "\n</body>", 1)
    dashboard._sentrix_dashboard_version = "v60-max-suite"
    logger.info("Dashboard V60 MAX suite installée : diagnostics, accès commandes et recherche sélecteurs.")
    return True


__all__ = ["install", "SUITE_CSS", "SUITE_JS"]
