"""SentriX V63 — finition visuelle de l'application V62.

Cette couche ne réintroduit aucune ancienne page. Elle remplace les trois zones qui donnaient
encore une impression de brouillon (Vue d'ensemble, Économie, Design) et supprime les derniers
CTA « Ouvrir » hérités. Les actions restent dans la zone centrale de ``/app``.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-v63-polish")

CSS = r'''
/* SentriX V63 polish */
.sx-v63-hero{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr);gap:12px;margin-bottom:10px}.sx-v63-hero-main{background:linear-gradient(135deg,#2c333b,#263646);border:1px solid #3e6c94;border-radius:8px;padding:17px}.sx-v63-hero-main h3{margin:0 0 5px;font-size:19px}.sx-v63-hero-main p{margin:0;color:#aeb7c1;line-height:1.5;font-size:12px}.sx-v63-health{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.sx-v63-chip{display:inline-flex;align-items:center;gap:6px;padding:6px 8px;border:1px solid #46515c;background:#2b3137;border-radius:999px;color:#d3d7db;font-size:10px}.sx-v63-chip.blue{border-color:#35688f;background:#1d3045;color:#d8ebff}.sx-v63-modules{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.sx-v63-module{background:#2e3338;border:1px solid #484f55;border-radius:7px;padding:10px}.sx-v63-module b{font-size:11px;display:block}.sx-v63-module small{display:block;color:#979da2;margin-top:4px;font-size:9px;line-height:1.4}.sx-v63-module .sx-state{margin-top:7px}.sx-v63-palette{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.sx-v63-color{background:#2d3237;border:1px solid #484f55;border-radius:7px;padding:9px}.sx-v63-color input[type=color]{width:100%;height:42px;border:0;padding:0;background:transparent}.sx-v63-discord{background:#2b2d31;border-radius:7px;padding:14px;min-height:190px}.sx-v63-discord .embed{border-left:4px solid var(--demo,#4da3ff);background:#1e1f22;border-radius:4px;padding:11px 12px;margin-top:9px}.sx-v63-discord .embed h4{margin:0 0 6px}.sx-v63-discord .embed p{margin:0;color:#dbdee1;white-space:pre-wrap}.sx-v63-progress{font-size:17px;letter-spacing:1px;margin-top:10px;color:#dcecff}.sx-v63-save{display:flex;justify-content:flex-end;gap:8px;margin-top:11px}.sx-v63-economy{display:grid;grid-template-columns:minmax(0,1fr) repeat(2,minmax(190px,.45fr));gap:9px}.sx-v63-stat{background:#2d3237;border:1px solid #484f55;border-radius:7px;padding:13px}.sx-v63-stat small{display:block;color:#989ea4;text-transform:uppercase;font-size:9px;font-weight:900}.sx-v63-stat strong{display:block;font-size:24px;margin-top:4px}
@media(max-width:1050px){.sx-v63-modules{grid-template-columns:1fr 1fr}.sx-v63-palette{grid-template-columns:1fr 1fr}.sx-v63-economy{grid-template-columns:1fr 1fr}.sx-v63-economy>:first-child{grid-column:1/-1}}
@media(max-width:680px){.sx-v63-hero{grid-template-columns:1fr}.sx-v63-modules,.sx-v63-palette,.sx-v63-economy{grid-template-columns:1fr}.sx-v63-economy>:first-child{grid-column:auto}}
'''

JS = r'''
<script id="sentrix-v63-polish">
(() => {
  "use strict";
  if(window.__sentrixV63Polish)return;window.__sentrixV63Polish=true;
  function active(tab){document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab))}
  function hideSave(){ $('saveBar')?.classList.add('hidden');state.dirty=false }
  function stripLegacyOpeners(){
    document.querySelectorAll('#fields a,#fields button,#sxToolbar a,#sxToolbar button').forEach(el=>{
      const text=(el.textContent||'').trim().toLocaleLowerCase('fr');
      if(['ouvrir','configuration avancée','éditeur complet','etat du service','état du service'].includes(text))el.remove();
    });
    document.querySelectorAll('a[href="/setup-center"],a[href="/feature-suite"],a[href="/operations"],a[href="/community"]').forEach(a=>a.remove());
  }
  function statCode(item){return `<span class="sx-state ${esc(item?.code||'missing')}">${esc(item?.status||'NON CONFIGURÉ')}</span>`}

  async function renderOverviewV63(){
    $('tabTitle').textContent='Vue d’ensemble';$('tabDescription').textContent='Tout ce qui compte sur ce serveur, sans raccourci vers une autre interface.';active('overview');hideSave();$('fields').innerHTML='<div class="panel-section"><div class="empty">Analyse du serveur…</div></div>';
    try{const d=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/diagnostics`),g=state.guildData.guild||{},m=state.guildData.metrics||{},summary=d.summary||{},mods=d.modules||{};const chosen=['welcome','roles','tickets','automod','logs','moderation','notifications','ai'];$('fields').innerHTML=`<div class="panel-section"><div class="sx-v63-hero"><div class="sx-v63-hero-main"><h3>${esc(g.name||'Serveur')}</h3><p>Configuration vérifiée depuis les données Discord et SentriX. Les cartes ci-dessous sont des états, pas des liens vers d'anciens centres.</p><div class="sx-v63-health"><span class="sx-v63-chip blue">Score ${Number(d.score||0)}%</span><span class="sx-v63-chip">${Number(summary.active||0)} actif(s)</span><span class="sx-v63-chip">${Number(summary.errors||0)} erreur(s)</span><span class="sx-v63-chip">${Number(summary.missing||0)} à configurer</span></div></div><div class="sx-v62-kpis"><div class="sx-v62-kpi"><small>Membres</small><strong>${number(g.members)}</strong></div><div class="sx-v62-kpi"><small>Commandes 24h</small><strong>${number(m.commands_24h)}</strong></div><div class="sx-v62-kpi"><small>Tickets</small><strong>${number(m.open_tickets)}</strong></div><div class="sx-v62-kpi"><small>Avertissements</small><strong>${number(m.warnings)}</strong></div></div></div><div class="sx-v63-modules">${chosen.map(k=>`<div class="sx-v63-module"><b>${esc(({welcome:'Arrivées',roles:'Rôles',tickets:'Tickets',automod:'Auto-Modération',logs:'Logs',moderation:'Modération',notifications:'Notifications',ai:'IA'})[k]||k)}</b>${statCode(mods[k])}<small>${esc(mods[k]?.detail||'Aucune donnée')}</small></div>`).join('')}</div></div>`}catch(e){toast(e.message,true);$('fields').innerHTML=`<div class="panel-section"><div class="empty">${esc(e.message)}</div></div>`}
  }

  async function renderEconomyV63(){
    $('tabTitle').textContent='Économie';$('tabDescription').textContent='Activation et état économique directement dans le dashboard.';active('economy');hideSave();$('fields').innerHTML='<div class="panel-section"><div class="empty">Chargement…</div></div>';
    try{const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/systems`),systems=r.systems||r,m=state.guildData.metrics||{};const enabled=Boolean(systems.economy_enabled);$('fields').innerHTML=`<div class="panel-section"><div class="sx-v63-economy"><section class="sx-v62-card full info"><div class="sx-v62-head"><div><h3>Système économique</h3><p>Désactiver le système ne supprime aucun solde.</p></div><span class="sx-state ${enabled?'active':'inactive'}">${enabled?'ACTIF':'INACTIF'}</span></div><div class="switch-line"><div class="switch-copy"><b>Argent, banque et boutiques</b><span>Contrôle global du module économique.</span></div><input id="v63EconomyToggle" class="switch" type="checkbox" ${enabled?'checked':''}></div><div class="sx-v63-save"><button id="v63EconomySave" class="btn blue">Enregistrer</button></div></section><div class="sx-v63-stat"><small>Comptes enregistrés</small><strong>${number(m.economy_accounts)}</strong></div><div class="sx-v63-stat"><small>Membres</small><strong>${number(state.guildData.guild?.members)}</strong></div></div><div class="sx-v62-toolbar-note" style="margin-top:10px">Les restrictions par commande sont disponibles dans « Accès & commandes » dans cette même barre latérale.</div></div>`;$('v63EconomySave').onclick=async()=>{const next=$('v63EconomyToggle').checked;if(next===enabled)return toast('Aucune modification.');const saved=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/systems`,{method:'PUT',body:JSON.stringify({economy_enabled:next})});toast(saved.message||'Économie mise à jour.');renderEconomyV63()}}
    catch(e){toast(e.message,true)}
  }

  function h(v){return '#'+Number(v||0).toString(16).padStart(6,'0').slice(-6)}
  async function renderDesignV63(){
    $('tabTitle').textContent='Design';$('tabDescription').textContent='Personnalisez les messages SentriX avec un aperçu réel et une identité plus bleue.';active('design');hideSave();$('fields').innerHTML='<div class="panel-section"><div class="empty">Chargement du design…</div></div>';
    try{const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/design`),d=r.design||r,cols=[['primary_color','Principale'],['secondary_color','Secondaire'],['success_color','Succès'],['warning_color','Avertissement'],['danger_color','Erreur']];$('fields').innerHTML=`<div class="panel-section"><div class="sx-v62-grid"><section class="sx-v62-card full info"><h3>Palette SentriX</h3><p>Le bleu reste l'accent visuel du dashboard ; ces couleurs règlent les embeds envoyés sur Discord.</p><div class="sx-v63-palette">${cols.map(([k,l])=>`<div class="sx-v63-color"><label>${l}</label><input type="color" data-v63-colour="${k}" value="${h(d[k])}"><input data-v63="${k}" value="${h(d[k])}" maxlength="7"></div>`).join('')}</div></section><section class="sx-v62-card"><h3>Texte & progression</h3><div class="sx-v62-fields"><div class="field full"><label>Footer</label><input data-v63="footer" value="${esc(d.footer||'SentriX')}"></div><div class="field"><label>Longueur barre</label><input data-v63="progress_length" type="number" min="3" max="30" value="${esc(d.progress_length||10)}"></div><div class="field"><label>Symbole rempli</label><input data-v63="progress_filled" value="${esc(d.progress_filled||'■')}"></div><div class="field"><label>Symbole vide</label><input data-v63="progress_empty" value="${esc(d.progress_empty||'□')}"></div></div><div class="switch-line"><div class="switch-copy"><b>Avatars</b><span>Afficher les avatars quand le composant le permet.</span></div><input data-v63="show_avatars" class="switch" type="checkbox" ${d.show_avatars?'checked':''}></div><div class="switch-line"><div class="switch-copy"><b>Mode compact</b><span>Réduit les éléments secondaires.</span></div><input data-v63="compact_mode" class="switch" type="checkbox" ${d.compact_mode?'checked':''}></div><div class="switch-line"><div class="switch-copy"><b>Graphiques</b><span>Autoriser les visuels statistiques.</span></div><input data-v63="charts_enabled" class="switch" type="checkbox" ${d.charts_enabled?'checked':''}></div></section><section class="sx-v62-card"><h3>Aperçu Discord</h3><div class="sx-v63-discord"><b>SentriX <span class="app-badge">APP</span></b><div id="v63DemoEmbed" class="embed"><h4>Exemple SentriX</h4><p>Votre design est prévisualisé ici.</p><div id="v63DemoProgress" class="sx-v63-progress"></div><small id="v63DemoFooter"></small></div></div></section><div class="sx-v62-card full"><div class="sx-v63-save"><button id="v63DesignSave" class="btn blue">Enregistrer le design</button></div></div></div></div>`;
      const sync=()=>{const primary=document.querySelector('[data-v63="primary_color"]')?.value||'#4da3ff';$('v63DemoEmbed').style.setProperty('--demo',primary);$('v63DemoEmbed').style.borderLeftColor=primary;$('v63DemoFooter').textContent=document.querySelector('[data-v63="footer"]')?.value||'SentriX';const n=Math.max(3,Math.min(30,Number(document.querySelector('[data-v63="progress_length"]')?.value||10))),filled=document.querySelector('[data-v63="progress_filled"]')?.value||'■',empty=document.querySelector('[data-v63="progress_empty"]')?.value||'□';$('v63DemoProgress').textContent=filled.repeat(Math.ceil(n*.7))+empty.repeat(Math.floor(n*.3))};document.querySelectorAll('[data-v63-colour]').forEach(p=>p.oninput=()=>{const t=document.querySelector(`[data-v63="${p.dataset.v63Colour}"]`);t.value=p.value.toUpperCase();sync()});document.querySelectorAll('[data-v63]').forEach(i=>i.oninput=sync);sync();$('v63DesignSave').onclick=async()=>{const out={};document.querySelectorAll('[data-v63]').forEach(el=>out[el.dataset.v63]=el.type==='checkbox'?el.checked:el.value);const saved=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/design`,{method:'PUT',body:JSON.stringify(out)});toast(saved.message||'Design enregistré.');renderDesignV63()}}
    catch(e){toast(e.message,true)}
  }

  const before=renderTab;renderTab=function(){if(state.tab==='overview'){renderOverviewV63();return}if(state.tab==='economy'){renderEconomyV63();return}if(state.tab==='design'){renderDesignV63();return}const r=before();setTimeout(stripLegacyOpeners,0);return r};
  stripLegacyOpeners();
})();
</script>
'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v63-polish"' in html:
        return True
    if 'id="sentrix-v62-dense"' not in html:
        logger.error("V63 refusé : V62 dense absent.")
        return False
    html = html.replace("</style>", CSS + "\n</style>", 1).replace("</body>", JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    dashboard._sentrix_dashboard_version = "v63-polish"
    logger.info("Dashboard V63 polish installé : aperçu dense, économie inline, design enrichi, CTA legacy retirés.")
    return True


__all__ = ["install"]
