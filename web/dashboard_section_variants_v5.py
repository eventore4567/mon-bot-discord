"""SentriX dashboard section-specific visual variants.

Adds distinct presentation patterns per tab on top of Premium UI V4 without replacing
validated settings or backend behavior.
"""
from __future__ import annotations

VARIANT_CSS = r'''
<style id="sentrix-section-variants-v5-css">
#serverContent[data-sx-tab="logs"] .panel{border-radius:12px!important}#serverContent[data-sx-tab="logs"] .fields{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr))!important}#serverContent[data-sx-tab="logs"] .field-group{background:#091522!important}
#serverContent[data-sx-tab="security"] .panel{border-left:3px solid #e84d62!important}#serverContent[data-sx-tab="security"] .sentrix-premium-icon{background:linear-gradient(145deg,#4a1824,#221019)!important;border-color:#7d2a3c!important;color:#ff8b9c!important}#serverContent[data-sx-tab="security"] .field-group{background:linear-gradient(145deg,#181018,#0d151e)!important}
#serverContent[data-sx-tab="tickets"] .sentrix-premium-icon{background:linear-gradient(145deg,#1d3b38,#10231f)!important;border-color:#316a61!important;color:#7ae6cf!important}#serverContent[data-sx-tab="tickets"] .panel{box-shadow:inset 0 1px 0 #23594c55,0 10px 30px #0002!important}
#serverContent[data-sx-tab="ai"] .sentrix-premium-icon{background:linear-gradient(145deg,#35225d,#18132c)!important;border-color:#5d4592!important;color:#c2a7ff!important}#serverContent[data-sx-tab="ai"] .panel-head{background:linear-gradient(90deg,#241839,#101b2a)!important}#serverContent[data-sx-tab="ai"] .field-group{border-color:#3b315b!important}
#serverContent[data-sx-tab="notifications"] .sentrix-premium-icon{background:linear-gradient(145deg,#3f3117,#201a0e)!important;border-color:#6b5627!important;color:#ffd76b!important}#serverContent[data-sx-tab="notifications"] .panel{border-top:2px solid #6d5424!important}
#serverContent[data-sx-tab="welcome"] .sentrix-premium-icon{background:linear-gradient(145deg,#19385b,#102238)!important;border-color:#2d5d91!important;color:#89c8ff!important}#serverContent[data-sx-tab="welcome"] .field-group{border-radius:20px!important}
#serverContent[data-sx-tab="levels"] .sentrix-premium-icon{background:linear-gradient(145deg,#183c2d,#0e241c)!important;border-color:#2c6a50!important;color:#78efb7!important}#serverContent[data-sx-tab="levels"] .metric{min-height:116px!important}
#serverContent[data-sx-tab="roles"] .fields,#serverContent[data-sx-tab="staff"] .fields{grid-template-columns:repeat(3,minmax(0,1fr))!important}#serverContent[data-sx-tab="roles"] .field-group,#serverContent[data-sx-tab="staff"] .field-group{min-height:150px!important}
#serverContent[data-sx-tab="verification"] .sentrix-premium-icon{background:linear-gradient(145deg,#1e3a55,#122234)!important;border-color:#376589!important;color:#97d5ff!important}#serverContent[data-sx-tab="verification"] .panel{border-bottom:2px solid #255578!important}
#serverContent[data-sx-tab="community"] .sentrix-premium-icon{background:linear-gradient(145deg,#40311b,#201a10)!important;border-color:#6b552c!important;color:#ffda78!important}#serverContent[data-sx-tab="community"] .field-group{background:linear-gradient(180deg,#171d22,#0d171f)!important}
#serverContent[data-sx-tab="sanctions"] .sentrix-premium-icon{background:linear-gradient(145deg,#4a1e1e,#271111)!important;border-color:#783535!important;color:#ff8b8b!important}#serverContent[data-sx-tab="sanctions"] table tbody tr:nth-child(even){background:#100f13!important}
#serverContent[data-sx-tab="ops"] .sentrix-premium-icon{background:linear-gradient(145deg,#24304f,#11192d)!important;border-color:#425787!important;color:#aebeff!important}#serverContent[data-sx-tab="ops"] .sx-ops-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}
#serverContent[data-sx-tab="control"] .sentrix-control-card:nth-child(3n+1){transform:translateY(-3px)}#serverContent[data-sx-tab="control"] .sentrix-control-card:nth-child(4n+2){background:linear-gradient(145deg,#10263a,#0d1825)!important}
.sx-v5-context{margin:0 0 16px;padding:14px 16px;border:1px solid #20364a;border-radius:13px;background:#0a1622;display:flex;align-items:center;justify-content:space-between;gap:16px}.sx-v5-context strong{font-size:13px}.sx-v5-context span{font-size:12px;color:#8397ad}.sx-v5-mini{display:flex;gap:8px;flex-wrap:wrap}.sx-v5-chip{padding:6px 9px;border-radius:999px;border:1px solid #29445e;background:#0c1b28;color:#a9c0d5;font-size:11px;font-weight:800}
@media(max-width:1000px){#serverContent[data-sx-tab="roles"] .fields,#serverContent[data-sx-tab="staff"] .fields{grid-template-columns:repeat(2,minmax(0,1fr))!important}}@media(max-width:720px){#serverContent[data-sx-tab] .fields{grid-template-columns:1fr!important}.sx-v5-context{align-items:flex-start;flex-direction:column}}
</style>
'''

VARIANT_JS = r'''
<script id="sentrix-section-variants-v5-js">
(()=>{
"use strict";if(window.__sentrixSectionVariantsV5)return;window.__sentrixSectionVariantsV5=true;
const notes={logs:["Journalisation détaillée","Filtrage, destinations et erreurs"],security:["Protection active","Les protections sont regroupées par risque"],tickets:["Support structuré","Catégorie, transcripts et évaluations"],ai:["Moteur IA","Modèle, limites et mémoire"],notifications:["Diffusion sociale","Sources externes et destinations Discord"],welcome:["Parcours d'arrivée","Bienvenue, départ et autorôle"],levels:["Progression","XP et annonces de niveau"],roles:["Architecture Discord","Rôles et salons reliés aux modules"],community:["Animation serveur","Annonces, giveaways et suggestions"],verification:["Accès membre","Règlement, vérification et rôles"],staff:["Organisation équipe","Rôles internes et supervision"],sanctions:["Historique disciplinaire","Bans, mutes et avertissements"],ops:["Santé & exploitation","Maintenance, rollback et réparation"],control:["Vue globale","Raccourcis et pilotage"],general:["Fondations","Préfixe et paramètres essentiels"]};
function current(){try{return state?.tab||"general"}catch(_){return"general"}}
function apply(){const root=document.getElementById('serverContent');if(!root)return;const t=current();root.dataset.sxTab=t;let box=document.getElementById('sxV5Context');if(!box){box=document.createElement('div');box.id='sxV5Context';box.className='sx-v5-context';const tabs=document.getElementById('sentrixSectionTabs');(tabs||root.firstChild)?.insertAdjacentElement?.('afterend',box)}const n=notes[t]||['Configuration SentriX','Réglages adaptés à cette section'];const chips={logs:['Temps réel','Export','Filtres'],security:['AutoMod','Anti-raid','Anti-nuke'],tickets:['Support','Transcripts','Évaluations'],ai:['Modèle','Mémoire','Limites'],notifications:['YouTube','TikTok','Twitch'],ops:['Health','Rollback','Repair'],roles:['Rôles','Salons','Permissions']}[t]||['Configuration','Aperçu'];box.innerHTML=`<div><strong>${n[0]}</strong><br><span>${n[1]}</span></div><div class="sx-v5-mini">${chips.map(x=>`<span class="sx-v5-chip">${x}</span>`).join('')}</div>`}
const run=()=>{apply();setTimeout(apply,60)};document.addEventListener('click',e=>{if(e.target?.closest?.('[data-tab]'))setTimeout(run,0)},true);new MutationObserver(()=>apply()).observe(document.body,{subtree:true,childList:true});if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',run,{once:true});else run();
})();
</script>
'''

def install(dashboard) -> bool:
    html=str(getattr(dashboard,"INDEX_HTML","") or "")
    if not html or "</head>" not in html or "</body>" not in html:return False
    if 'id="sentrix-section-variants-v5-css"' not in html:html=html.replace("</head>",VARIANT_CSS+"\n</head>",1)
    if 'id="sentrix-section-variants-v5-js"' not in html:html=html.replace("</body>",VARIANT_JS+"\n</body>",1)
    dashboard.INDEX_HTML=html
    return True
