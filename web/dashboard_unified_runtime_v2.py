"""Runtime hardening for the single SentriX unified dashboard.

The visual document remains owned by :mod:`web.dashboard_unified_v2`.  This module only
applies production contracts that historically lived in late dashboard layers: safe server
switching, HTTP-aware errors, owner-only DM controls, and auth boot behaviour.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.dashboard-unified-runtime-v2")

_MARKER = 'id="sentrix-unified-runtime-v2"'
_UNIFIED = 'id="sentrix-dashboard-unified-v2"'

_DM_STYLE = r'''
<style id="sentrix-dm-style">
.dm-shell{display:grid;gap:12px}.dm-card{border:1px solid var(--line);background:var(--panel);border-radius:var(--radius);padding:15px}.dm-card h2{margin:0;font-size:18px}.dm-hint{color:var(--muted);font-size:11px;margin:5px 0 12px}.dm-preview{white-space:pre-wrap;word-break:break-word;border:1px dashed var(--line2);background:#10151b;border-radius:8px;padding:11px;min-height:46px}.dm-confirm{display:flex;align-items:flex-start;gap:9px;margin-top:11px;color:var(--soft);font-size:11px}.dm-confirm input{margin-top:2px}.dm-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:11px}.dm-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:11px}.dm-stat{border:1px solid var(--line);background:#12171d;border-radius:8px;padding:9px}.dm-stat b{display:block;font-size:18px}.dm-stat span{display:block;color:var(--muted);font-size:9px;margin-top:2px}.dm-bar{height:7px;border-radius:99px;background:#252d37;overflow:hidden;margin-top:12px}.dm-bar>i{display:block;height:100%;background:var(--blue);transition:width .2s}.dm-row{display:grid;grid-template-columns:minmax(0,1fr);gap:9px}.dm-card textarea,.dm-card input{width:100%;border:1px solid var(--line2);background:#10151b;color:var(--text);border-radius:8px;padding:9px 10px;outline:0}.dm-card textarea{min-height:110px;resize:vertical}
@media(max-width:620px){.dm-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.dm-actions .btn{width:100%}}
</style>
'''

_DM_RUNTIME = r'''
let dmPoll=null;
function stopDmPoll(){if(dmPoll){clearInterval(dmPoll);dmPoll=null}}
async function dmCall(path,options={}){try{return{ok:true,status:200,data:await api(path,options)}}catch(e){return{ok:false,status:Number(e?.status||0),data:e?.data||{error:e?.message||'Erreur inconnue'}}}}
function dmStats(e={}){return `<div class="dm-stats"><div class="dm-stat"><b>${esc(e.envoyes||0)}</b><span>Envoyés</span></div><div class="dm-stat"><b>${esc(e.dms_fermes||0)}</b><span>MP fermés</span></div><div class="dm-stat"><b>${esc(e.echecs||0)}</b><span>Échecs</span></div><div class="dm-stat"><b>${esc(e.bots_ignores||0)}</b><span>Bots ignorés</span></div></div>`}
function showDmJob(e){const zone=$('dmAllProgress');if(!zone||!e)return;const total=Number(e.total||0),done=Number(e.traites||0),pct=total?Math.min(100,Math.round(done*100/total)):0;zone.innerHTML=`<div class="dm-bar"><i style="width:${pct}%"></i></div><p class="dm-hint">${done} / ${total} membre(s) traité(s)${e.termine?' — diffusion terminée.':'…'}</p>${dmStats(e)}`;const button=$('dmAllSend');if(button)button.disabled=!e.termine;if(e.termine)stopDmPoll()}
function followDmJob(guildId){stopDmPoll();dmPoll=setInterval(async()=>{const r=await dmCall(`/api/guilds/${guildId}/dm/job`);if(!r.ok){stopDmPoll();return}if(r.data.etat)showDmJob(r.data.etat);if(!r.data.actif)stopDmPoll()},1500)}
function dmPreview(sourceId,targetId){const source=$(sourceId),target=$(targetId);if(!source||!target)return;const sync=()=>{const v=source.value||'';target.textContent=v.trim()?v:"L’aperçu du message s’affichera ici."};source.addEventListener('input',sync);sync()}
async function envoyerTous(guildId){const bouton=$('dmAllSend'),message=$('dmAllMessage')?.value||'',confirme=Boolean($('dmAllConfirm')?.checked);if(!message.trim()){toast('Le message est vide.',true);return}if(!confirme){toast('Confirme la diffusion avant l’envoi.',true);return}if(bouton)bouton.disabled=true;const r=await dmCall(`/api/guilds/${guildId}/dm/all`,{method:'POST',body:JSON.stringify({message,confirme:true})});if(r.status===409){toast('Une diffusion est déjà en cours sur ce serveur.',true);if(r.data.etat)showDmJob(r.data.etat);followDmJob(guildId);return}if(!r.ok){toast(r.data.error||'Envoi refusé.',true);if(bouton)bouton.disabled=false;return}if(r.data.etat)showDmJob(r.data.etat);followDmJob(guildId)}
async function envoyerUn(guildId){const bouton=$('dmOneSend'),userId=($('dmOneUser')?.value||'').trim(),message=$('dmOneMessage')?.value||'';if(!userId){toast('Indique un ID de membre.',true);return}if(!message.trim()){toast('Le message est vide.',true);return}if(bouton)bouton.disabled=true;const r=await dmCall(`/api/guilds/${guildId}/dm/user`,{method:'POST',body:JSON.stringify({user_id:userId,message})});if(bouton)bouton.disabled=false;const zone=$('dmOneResult');if(zone)zone.innerHTML=`<div class="notice ${r.ok?'':'bad'}">${esc(r.data.message||r.data.error||'Échec de l’envoi.')}</div>`}
window.sentrixRenderDM=async function renderDM(){stopDmPoll();const guildId=state.guildId;if(!guildId)return;$('content').innerHTML='<div class="loading-screen"><div class="loading-block skeleton"></div></div>';const info=await dmCall(`/api/guilds/${guildId}/dm/apercu`);if(!info.ok){$('content').innerHTML=`<div class="grid"><section class="card full"><h2>Réservé au propriétaire du serveur</h2><p>${esc(info.data.error||"Tu n’as pas accès à cette section.")}</p></section></div>`;return}const d=info.data,minutes=Math.max(1,Math.round(Number(d.duree_estimee_secondes||0)/60));$('content').innerHTML=`<div class="dm-shell"><section class="dm-card"><h2>Message privé à tout le serveur</h2><p class="dm-hint">${esc(d.guild?.name||'Serveur')} — ${esc(d.destinataires||0)} membre(s) ciblé(s), ${esc(d.bots_ignores||0)} bot(s) ignoré(s). Durée estimée : environ ${minutes} min.</p><textarea id="dmAllMessage" maxlength="3500" placeholder="Message envoyé à chaque membre…"></textarea><p class="dm-hint">Aperçu</p><div class="dm-preview" id="dmAllPreview"></div><label class="dm-confirm"><input type="checkbox" id="dmAllConfirm"><span>Je confirme l’envoi à <b>${esc(d.destinataires||0)}</b> membre(s). Cette action est irréversible.</span></label><div class="dm-actions"><button class="btn primary" type="button" id="dmAllSend">Envoyer à tous</button></div><div id="dmAllProgress">${dmStats({bots_ignores:d.bots_ignores})}</div></section><section class="dm-card"><h2>Message privé à un membre</h2><p class="dm-hint">Indique un identifiant Discord ou colle une mention.</p><div class="dm-row"><input id="dmOneUser" type="text" inputmode="numeric" placeholder="ID du membre"><textarea id="dmOneMessage" maxlength="3500" placeholder="Message privé…"></textarea></div><p class="dm-hint">Aperçu</p><div class="dm-preview" id="dmOnePreview"></div><div class="dm-actions"><button class="btn primary" type="button" id="dmOneSend">Envoyer</button></div><div id="dmOneResult"></div></section></div>`;dmPreview('dmAllMessage','dmAllPreview');dmPreview('dmOneMessage','dmOnePreview');$('dmAllSend').onclick=()=>envoyerTous(guildId);$('dmOneSend').onclick=()=>envoyerUn(guildId);$('dmOneUser').oninput=e=>{const m=/(\d{15,22})/.exec(e.target.value||'');if(m&&e.target.value!==m[1])e.target.value=m[1]};const job=await dmCall(`/api/guilds/${guildId}/dm/job`);if(job.ok&&job.data.etat){showDmJob(job.data.etat);if(job.data.actif)followDmJob(guildId)}};
'''


def enhance_html(html: str) -> str:
    """Return the unified document with the production runtime contracts applied once."""
    html = str(html or "")
    if _UNIFIED not in html or _MARKER in html:
        return html

    html = html.replace(
        '<section class="landing" id="landing">',
        '<section class="landing hidden" id="landing">',
        1,
    )

    html = html.replace(
        'const state={user:null,csrf:"",guilds:[],guildId:"",guildData:null,diagnostics:null,v62:null,setupTools:null,tab:"overview",dirty:{settings:{},automod:{},ai:{}},loading:false,query:"",sanctionsPage:0};',
        'const state={user:null,csrf:"",guilds:[],guildId:"",guildData:null,diagnostics:null,v62:null,setupTools:null,tab:"overview",dirty:{settings:{},automod:{},ai:{}},loading:false,query:"",sanctionsPage:0,guildAbort:null};',
        1,
    )

    old_api = "async function api(url,options={}){const headers={Accept:'application/json',...(options.headers||{})};if(options.body&&!headers['Content-Type'])headers['Content-Type']='application/json';if(state.csrf&&options.method&&options.method!=='GET')headers['X-CSRF-Token']=state.csrf;const res=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,headers});let data={};try{data=await res.json()}catch(_){}if(!res.ok)throw new Error(data.error||`Erreur HTTP ${res.status}`);return data}"
    new_api = "async function api(url,options={}){const headers={Accept:'application/json',...(options.headers||{})};if(options.body&&!headers['Content-Type'])headers['Content-Type']='application/json';if(state.csrf&&options.method&&options.method!=='GET')headers['X-CSRF-Token']=state.csrf;const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,headers});let data={};try{data=await r.json()}catch(_){}if(!r.ok)throw Object.assign(new Error(data.error||`Erreur HTTP ${r.status}`),{status:r.status,data});return data}"
    html = html.replace(old_api, new_api, 1)

    old_session = "async function loadSession(){try{const me=await api('/api/me');state.user=me.user;state.csrf=me.csrf;$('landing').classList.add('hidden');$('dashboard').classList.remove('hidden');$('profileButton').classList.remove('hidden');$('userName').textContent=me.user?.username||'Compte';if(me.user?.avatar_url)$('userAvatar').innerHTML=`<img class=\"avatar\" src=\"${esc(me.user.avatar_url)}\" alt=\"\">`;await loadGuilds();return true}catch(e){if(!location.pathname.startsWith('/app'))return false;$('landing').classList.remove('hidden');$('dashboard').classList.add('hidden');return false}}"
    new_session = "async function loadSession(){try{const me=await api('/api/me');state.user=me.user;state.csrf=me.csrf;$('landing').classList.add('hidden');$('dashboard').classList.remove('hidden');$('profileButton').classList.remove('hidden');$('userName').textContent=me.user?.username||'Compte';if(me.user?.avatar_url)$('userAvatar').innerHTML=`<img class=\"avatar\" src=\"${esc(me.user.avatar_url)}\" alt=\"\">`;await loadGuilds();return true}catch(e){if(!location.pathname.startsWith('/app'))return false;if(e.status===503){$('landing').classList.add('hidden');$('dashboard').classList.add('hidden');$('runtimeText').textContent='Reconnexion Discord en cours';return false}if(e.status===401){$('landing').classList.remove('hidden');$('dashboard').classList.add('hidden');$('publicBadge').textContent='Votre session Discord a expiré';return false}$('landing').classList.remove('hidden');$('dashboard').classList.add('hidden');return false}}"
    html = html.replace(old_session, new_session, 1)

    old_select = "async function selectGuild(value){if(!value)return;state.guildId=String(value);state.guildData=null;state.diagnostics=null;state.v62=null;state.setupTools=null;clearDirty();renderServerRail();$('content').innerHTML=loading();try{const data=await api(`/api/guilds/${encodeURIComponent(state.guildId)}`);state.guildData=data;try{localStorage.setItem('sentrix:dashboard:guild',state.guildId)}catch(_){}updateChrome();renderServerRail();await render(true)}catch(e){errorView(e)}}"
    new_select = "async function selectGuild(value){if(!value)return;if(state.guildAbort)state.guildAbort.abort();const controller=new AbortController();state.guildAbort=controller;const requested=String(value);state.guildId=requested;state.guildData=null;state.diagnostics=null;state.v62=null;state.setupTools=null;clearDirty();renderServerRail();$('content').innerHTML=loading();try{const data=await api(`/api/guilds/${encodeURIComponent(requested)}`,{signal:controller.signal});if(controller!==state.guildAbort||requested!==state.guildId)return;state.guildData=data;try{localStorage.setItem('sentrix:dashboard:guild',state.guildId)}catch(_){}updateChrome();renderServerRail();await render(true)}catch(e){if(e?.name==='AbortError'||controller!==state.guildAbort)return;if(e.status===503)errorView({message:'Reconnexion Discord en cours. Réessayez dans quelques secondes.'});else if(e.status===401)errorView({message:'Votre session Discord a expiré. Reconnectez-vous.'});else errorView(e)}finally{if(controller===state.guildAbort)state.guildAbort=null}}"
    html = html.replace(old_select, new_select, 1)

    html = html.replace(
        '["Administration",[["config","Configuration","CF"],["access","Accès & commandes","AC"],["diagnostic","Diagnostic","DG"]]],',
        '["Administration",[["config","Configuration","CF"],["access","Accès & commandes","AC"],["dm","Messages privés","DM"],["diagnostic","Diagnostic","DG"]]],',
        1,
    )
    html = html.replace(
        'access:["Accès & commandes","Commandes désactivées, gestionnaires et portée de SentriX."],diagnostic:["Diagnostic","Permissions, ressources cassées et état des modules."],',
        'access:["Accès & commandes","Commandes désactivées, gestionnaires et portée de SentriX."],dm:["Messages privés","Diffusion à tout le serveur ou message individuel, réservée au propriétaire."],diagnostic:["Diagnostic","Permissions, ressources cassées et état des modules."],',
        1,
    )

    html = html.replace(
        "async function render(force=false){if(!state.guildData)return;$('content').innerHTML=loading();setPage();try{switch(state.tab){",
        "async function render(force=false){if(!state.guildData)return;$('content').innerHTML=loading();setPage();try{switch(state.tab){case'dm':await window.sentrixRenderDM();break;",
        1,
    )

    html = html.replace(
        "async function boot(){try{state.tab=new URLSearchParams(location.search).get('tab')||localStorage.getItem('sentrix:dashboard:tab')||'overview'}catch(_){state.tab='overview'}renderNav();loadPublic();setInterval(loadPublic,30000);await loadSession()}",
        "async function boot(){try{state.tab=new URLSearchParams(location.search).get('tab')||localStorage.getItem('sentrix:dashboard:tab')||'overview'}catch(_){state.tab='overview'}if(!META[state.tab])state.tab='overview';renderNav();loadPublic();setInterval(loadPublic,30000);await loadSession()}",
        1,
    )

    html = html.replace(
        "async function renderDiagnostic(){",
        _DM_RUNTIME + "\nasync function renderDiagnostic(){",
        1,
    )

    if 'id="sentrix-dm-style"' not in html:
        html = html.replace("</head>", _DM_STYLE + "\n</head>", 1)
    marker = '<script id="sentrix-unified-runtime-v2" type="application/json">{"runtime":"unified-v2"}</script>\n<script id="sentrix-dm-panel" type="application/json">{"ui":"owner-dm"}</script>'
    html = html.replace("</body>", marker + "\n</body>", 1)
    return html


__all__ = ["enhance_html"]
