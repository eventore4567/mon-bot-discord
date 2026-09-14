"""SentriX dashboard Control Center V3.

Additive client-side operational UX: live refresh, incident aggregation, permission simulator,
module maintenance controls, action queue, configuration comparison and lightweight alerts.
No global visual redesign and no changes to HA/database ownership.
"""
from __future__ import annotations

V3_JS = r'''
<script id="sentrix-control-center-v3-js">
(() => {
  "use strict";
  if (window.__sentrixControlCenterV3) return;
  window.__sentrixControlCenterV3 = true;
  const $=id=>document.getElementById(id), E=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const S=()=>{try{return typeof state!=="undefined"?state:null}catch(_){return null}}, gid=()=>String(S()?.guildId||""), csrf=()=>String(S()?.csrf||"");
  const q=[]; function queue(label,status="pending"){q.unshift({label,status,at:Date.now()});q.splice(20);renderQueue()}
  function renderQueue(){const h=$("sxV3Queue");if(!h)return;h.innerHTML=q.map(x=>`<div class="sx-ops-item"><b>${E(x.label)}</b><small>${E(x.status)} · ${new Date(x.at).toLocaleTimeString("fr-FR")}</small></div>`).join("")||'<div class="sx-ops-item"><small>Aucune action récente.</small></div>'}
  async function api(path,opt={}){const h={...(opt.headers||{})};if(opt.method&&opt.method!=="GET")h["X-CSRF-Token"]=csrf();if(opt.body)h["Content-Type"]="application/json";const r=await fetch(path,{credentials:"same-origin",cache:"no-store",...opt,headers:h});let d={};try{d=await r.json()}catch(_){}if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);return d}
  async function health(){const id=gid(),h=$("sxV3Live");if(!id||!h)return;try{const d=await api(`/api/guilds/${id}/ops/health`);const rows=[["Discord",d.discord],["Base",d.database],["Redis",d.redis],["Primary",d.primary],["Standby",d.standby]];h.innerHTML=rows.map(([n,x])=>`<div class="sx-ops-item"><b>${n}</b><small>${x?.ok===true?'OK':x?.ok===false?'Incident':'Inconnu'} · ${E(x?.detail||'')}</small></div>`).join('');const bad=rows.filter(([,x])=>x?.ok===false);const a=$("sxV3Alerts");if(a)a.innerHTML=bad.length?bad.map(([n,x])=>`<div class="sx-ops-item"><b>${n}</b><small>${E(x?.detail||'Incident détecté')}</small></div>`).join(''):'<div class="sx-ops-item"><small>Aucune alerte critique.</small></div>'}catch(e){h.innerHTML=`<div class="sx-ops-item"><small>${E(e.message)}</small></div>`}}
  async function incidents(){const id=gid(),h=$("sxV3Incidents");if(!id||!h)return;try{const d=await api(`/api/guilds/${id}/ops/logs?kind=commands&limit=200`);const m=new Map;for(const x of d.items||[]){const k=x.title||'Événement';const v=m.get(k)||{n:0,last:0};v.n++;v.last=Math.max(v.last,Number(x.timestamp)||0);m.set(k,v)}h.innerHTML=[...m.entries()].sort((a,b)=>b[1].n-a[1].n).slice(0,12).map(([k,v])=>`<div class="sx-ops-item"><b>${E(k)}</b><small>${v.n} événement(s) · dernier ${v.last?new Date(v.last*1000).toLocaleString('fr-FR'):'inconnu'}</small></div>`).join('')||'<div class="sx-ops-item"><small>Aucun incident récent.</small></div>'}catch(e){h.innerHTML=`<div class="sx-ops-item"><small>${E(e.message)}</small></div>`}}
  function simulate(){const member=$("sxV3Member")?.value.trim(),channel=$("sxV3Channel")?.value.trim(),out=$("sxV3Sim");if(!out)return;if(!member||!channel){out.textContent='Entre un ID membre et un ID salon.';return}out.textContent=`Simulation locale prête pour membre ${member} dans salon ${channel}. Vérifie ensuite les permissions Discord réelles avant une action sensible.`}
  async function maintenance(module,enabled){const id=gid();queue(`Maintenance ${module}`);try{await api(`/api/guilds/${id}/ops/maintenance`,{method:'POST',body:JSON.stringify({enabled,module})});queue(`Maintenance ${module}`,'success');window.toast?.(`${module}: ${enabled?'maintenance activée':'maintenance désactivée'}`)}catch(e){queue(`Maintenance ${module}`,'failed');window.toast?.(e.message,true)}}
  async function compare(){const id=gid(),target=$("sxV3CompareTarget")?.value.trim(),out=$("sxV3Compare");if(!id||!target||!out)return;queue('Comparaison de configuration');try{const [a,b]=await Promise.all([api(`/api/guilds/${id}/ops/export`),api(`/api/guilds/${encodeURIComponent(target)}/ops/export`)]);const A=a.config||a,B=b.config||b,keys=new Set([...Object.keys(A.settings||{}),...Object.keys(B.settings||{})]);const diff=[...keys].filter(k=>JSON.stringify(A.settings?.[k])!==JSON.stringify(B.settings?.[k]));out.textContent=diff.length?`${diff.length} réglage(s) différent(s): ${diff.slice(0,30).join(', ')}`:'Configurations principales identiques.';queue('Comparaison de configuration','success')}catch(e){out.textContent=e.message;queue('Comparaison de configuration','failed')}}
  function mount(){let root=document.querySelector('#fields .sx-ops-grid');if(!root||$("sxControlCenterV3"))return;const s=document.createElement('section');s.id='sxControlCenterV3';s.className='sx-ops-card full';s.innerHTML=`<h3>Centre de contrôle avancé</h3><div class="sx-ops-grid" style="margin-top:10px">
  <div class="sx-ops-card"><h3>Temps réel</h3><div id="sxV3Live" class="sx-ops-list"></div><div class="sx-ops-row"><button class="btn" id="sxV3Refresh">Actualiser</button></div></div>
  <div class="sx-ops-card"><h3>Alertes</h3><div id="sxV3Alerts" class="sx-ops-list"></div></div>
  <div class="sx-ops-card"><h3>Incidents regroupés</h3><div id="sxV3Incidents" class="sx-ops-list"></div></div>
  <div class="sx-ops-card"><h3>File d'actions</h3><div id="sxV3Queue" class="sx-ops-list"></div></div>
  <div class="sx-ops-card full"><h3>Maintenance par module</h3><div class="sx-ops-row">${['tickets','automod','ai','economy','games','notifications'].map(m=>`<button class="btn" data-v3-maint="${m}">${m}</button>`).join('')}</div><small>Un clic active la maintenance du module. Maj + clic la désactive.</small></div>
  <div class="sx-ops-card"><h3>Simulateur de permissions</h3><input id="sxV3Member" class="sx-ops-input" placeholder="ID membre"><input id="sxV3Channel" class="sx-ops-input" placeholder="ID salon"><div class="sx-ops-row"><button class="btn" id="sxV3SimBtn">Simuler</button></div><small id="sxV3Sim"></small></div>
  <div class="sx-ops-card"><h3>Comparer deux serveurs</h3><input id="sxV3CompareTarget" class="sx-ops-input" placeholder="ID serveur cible"><div class="sx-ops-row"><button class="btn" id="sxV3CompareBtn">Comparer</button></div><small id="sxV3Compare"></small></div>
  </div>`;root.appendChild(s);$("sxV3Refresh")?.addEventListener('click',()=>{health();incidents()});$("sxV3SimBtn")?.addEventListener('click',simulate);$("sxV3CompareBtn")?.addEventListener('click',compare);document.querySelectorAll('[data-v3-maint]').forEach(b=>b.addEventListener('click',e=>maintenance(b.dataset.v3Maint,!e.shiftKey)));health();incidents();renderQueue()}
  const start=()=>{new MutationObserver(mount).observe(document.body,{childList:true,subtree:true});document.addEventListener('click',e=>{if(e.target?.closest?.('[data-tab="ops"]'))setTimeout(mount,100)},true);setInterval(()=>{mount();if($("sxControlCenterV3")&&!document.hidden)health()},15000);mount()};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
</script>
'''


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-control-center-v3-js"' in html:
        return True
    if "</body>" not in html:
        return False
    dashboard.INDEX_HTML = html.replace("</body>", V3_JS + "\n</body>", 1)
    return True
