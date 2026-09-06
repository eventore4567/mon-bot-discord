"""Dashboard Tickets V65 — interface simple en 4 étapes.

Cette couche ne remplace ni la base de données ni le moteur Discord. Elle s'appuie sur les
API V35/V53 existantes pour conserver les panels, types, formulaires, rôles et boutons staff,
puis ajoute uniquement les ressources nécessaires à la publication du panel.
"""
from __future__ import annotations

import logging

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard.ticket-simple-v65")
_INSTALLED = False

CSS = r"""
<style id="sentrix-ticket-simple-v65-css">
#fields.sx-ticket-simple-mode> :not(#sentrixTicketSimpleV65){display:none!important}
#sentrixTicketSimpleV65{grid-column:1/-1;display:grid;gap:14px;width:100%}
.sx65-shell{display:grid;grid-template-columns:230px minmax(0,1fr);gap:14px}
.sx65-side,.sx65-step{border:1px solid #283246;border-radius:14px;background:#0e141e;overflow:hidden}
.sx65-side-head,.sx65-step-head{padding:14px 15px;border-bottom:1px solid #232c3d}
.sx65-side-head h3,.sx65-step-head h3{margin:0;color:#f2eff7;font-size:14px}.sx65-side-head p,.sx65-step-head p{margin:4px 0 0;color:#8490a4;font-size:10px;line-height:1.45}
.sx65-side-body{padding:10px;display:grid;gap:7px}.sx65-panel{width:100%;text-align:left;border:1px solid #29344a;border-radius:10px;background:#121925;color:#dcd9e4;padding:10px;cursor:pointer}.sx65-panel.active{border-color:#755ee0;background:#201a38}.sx65-panel b{display:block;font-size:10px}.sx65-panel span{display:block;margin-top:3px;color:#8792a5;font-size:9px}
.sx65-new{min-height:36px;border:1px solid #765fe0;border-radius:9px;background:#7058d5;color:white;font-weight:850;cursor:pointer}
.sx65-main{display:grid;gap:12px}.sx65-step-body{padding:14px;display:grid;gap:12px}.sx65-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.sx65-full{grid-column:1/-1}
.sx65-field label{display:block;margin-bottom:5px;color:#c0c7d4;font-size:10px;font-weight:800}.sx65-field small{display:block;margin-top:4px;color:#768296;font-size:9px;line-height:1.4}.sx65-field input,.sx65-field textarea,.sx65-field select{width:100%;box-sizing:border-box;border:1px solid #303b50;border-radius:9px;background:#111925;color:#ece9f1;padding:9px 10px;font:inherit;font-size:10px}.sx65-field textarea{min-height:90px;resize:vertical}
.sx65-switch{display:flex;align-items:center;gap:8px;padding:10px;border:1px solid #2c374b;border-radius:9px;background:#111925;color:#c5ccd8;font-size:10px}.sx65-switch input{width:auto;margin:0}
.sx65-role-box{max-height:150px;overflow:auto;border:1px solid #2d384d;border-radius:9px;background:#101722;padding:6px;display:grid;gap:2px}.sx65-role{display:flex;align-items:center;gap:7px;padding:7px;border-radius:7px;color:#c4ccd8;font-size:9px}.sx65-role:hover{background:#171f2c}.sx65-role input{width:auto;margin:0}
.sx65-types{display:grid;gap:8px}.sx65-type{border:1px solid #2b364b;border-radius:11px;background:#0d141e;padding:11px;display:grid;gap:9px}.sx65-type-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.sx65-type-head b{font-size:10px;color:#e9e5ef}.sx65-remove{border:1px solid #663842;border-radius:8px;background:#28191e;color:#efa6ae;padding:6px 8px;font-size:9px;cursor:pointer}
.sx65-advanced{border:1px solid #29344a;border-radius:10px;background:#101722}.sx65-advanced>summary{cursor:pointer;padding:10px 11px;color:#aeb7c6;font-size:9px;font-weight:850}.sx65-advanced-body{padding:0 11px 11px}
.sx65-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.sx65-btn{min-height:36px;padding:0 12px;border:1px solid #354158;border-radius:9px;background:#151d29;color:#e1dee7;font-size:10px;font-weight:850;cursor:pointer}.sx65-btn.primary{border-color:#7961e0;background:#7058d5;color:#fff}.sx65-btn.danger{border-color:#653842;background:#29191e;color:#efa4ad}.sx65-btn:disabled{opacity:.55;cursor:wait}
.sx65-preview{border:1px solid #303b52;border-left:4px solid #5865f2;border-radius:8px;background:#111824;padding:12px}.sx65-preview h4{margin:0 0 7px;color:#f0edf5;font-size:13px}.sx65-preview p{margin:0;color:#aeb7c5;font-size:10px;line-height:1.5;white-space:pre-wrap}.sx65-preview-types{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.sx65-preview-types span{padding:6px 8px;border-radius:7px;background:#5865f2;color:white;font-size:9px;font-weight:800}
.sx65-status{font-size:9px;color:#8f9bad}.sx65-empty{padding:28px 18px;text-align:center;border:1px dashed #344057;border-radius:13px;background:#101722}.sx65-empty h3{margin:0;color:#eeebf4}.sx65-empty p{color:#8793a6;font-size:10px}.sx65-loading{padding:22px;text-align:center;color:#8e99ac;font-size:10px}
@media(max-width:820px){.sx65-shell{grid-template-columns:1fr}.sx65-grid{grid-template-columns:1fr}.sx65-full{grid-column:auto}}
</style>
"""

JS = r"""
<script id="sentrix-ticket-simple-v65-js">
(() => {
"use strict";
if(window.__sentrixTicketSimpleV65)return;window.__sentrixTicketSimpleV65=true;
let guild="",selected="",center=null,editor=null,resources=null,busy=false;
const E=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const gid=()=>{try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):""}catch(_){return""}};
const active=()=>{try{return typeof state!=="undefined"&&state.tab==="tickets"}catch(_){return false}};
const csrf=()=>{try{return typeof state!=="undefined"?state.csrf||"":""}catch(_){return""}};
const notify=(m,b=false)=>{try{if(typeof toast==="function")return toast(m,b)}catch(_){}(b?console.error:console.info)(m)};
async function api(url,opt={}){const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...opt});const body=await r.json().catch(()=>({}));if(!r.ok)throw new Error(body.error||`Erreur HTTP ${r.status}`);return body}
function fieldRoot(){const f=document.getElementById("fields");if(!f)return null;if(!active()){f.classList.remove("sx-ticket-simple-mode");document.getElementById("sentrixTicketSimpleV65")?.remove();return null}f.classList.add("sx-ticket-simple-mode");let r=document.getElementById("sentrixTicketSimpleV65");if(!r){r=document.createElement("section");r.id="sentrixTicketSimpleV65";f.appendChild(r)}return r}
function panel(){return (center?.panels||[]).find(p=>String(p.id)===String(selected))||null}
function roleOptions(value=""){const v=String(value||"");return '<option value="">Aucun rôle</option>'+((editor?.roles)||center?.roles||[]).map(r=>`<option value="${E(r.id)}" ${String(r.id)===v?"selected":""}>@${E(r.name)}</option>`).join("")}
function categoryOptions(value=""){const v=String(value||"");return '<option value="">Aucune catégorie imposée</option>'+((editor?.categories)||[]).map(c=>`<option value="${E(c.id)}" ${String(c.id)===v?"selected":""}>${E(c.name)}</option>`).join("")}
function channelOptions(value=""){const v=String(value||"");return '<option value="">Choisir le salon de publication</option>'+((resources?.channels)||[]).map(c=>`<option value="${E(c.id)}" ${String(c.id)===v?"selected":""}>#${E(c.name)}</option>`).join("")}
function roleChecks(key,selectedIds=[]){const chosen=new Set((selectedIds||[]).map(String));return `<div class="sx65-role-box" data-rolebox="${E(key)}">${((editor?.roles)||center?.roles||[]).map(r=>`<label class="sx65-role"><input type="checkbox" value="${E(r.id)}" ${chosen.has(String(r.id))?"checked":""}> @${E(r.name)}</label>`).join("")||'<span class="sx65-status">Aucun rôle disponible.</span>'}</div>`}
function checkedRoles(key){return [...document.querySelectorAll(`[data-rolebox="${key}"] input:checked`)].map(x=>x.value)}
function typeCard(t,i){return `<div class="sx65-type" data-type-index="${i}"><div class="sx65-type-head"><b>Type ${i+1} · ${E(t.name||"Support")}</b><button class="sx65-remove" type="button" data-remove-type="${i}">Supprimer</button></div><div class="sx65-grid"><div class="sx65-field"><label>Nom du type</label><input data-tf="name" maxlength="80" value="${E(t.name||"Support")}"></div><div class="sx65-field"><label>Texte du bouton</label><input data-tf="button_label" maxlength="80" value="${E(t.button_label||t.name||"Ouvrir un ticket")}"></div><div class="sx65-field"><label>Emoji</label><input data-tf="emoji" maxlength="100" value="${E(t.emoji||"🎫")}"></div><div class="sx65-field"><label>Couleur du bouton</label><select data-tf="button_style"><option value="bleu" ${t.button_style==="bleu"?"selected":""}>Bleu</option><option value="gris" ${t.button_style==="gris"?"selected":""}>Gris</option><option value="vert" ${t.button_style==="vert"?"selected":""}>Vert</option><option value="rouge" ${t.button_style==="rouge"?"selected":""}>Rouge</option></select></div><div class="sx65-field sx65-full"><label>Description courte</label><input data-tf="description" maxlength="150" value="${E(t.description||"")}" placeholder="Ex. Besoin d'aide avec une commande"></div></div><details class="sx65-advanced"><summary>Options avancées de ce type</summary><div class="sx65-advanced-body sx65-grid"><div class="sx65-field"><label>Catégorie Discord</label><select data-tf="category_id">${categoryOptions(t.category_id)}</select></div><div class="sx65-field"><label>Nom du salon</label><input data-tf="name_format" maxlength="90" value="${E(t.name_format||"ticket-{pseudo}")}"><small>{pseudo} et {numero} sont disponibles.</small></div><div class="sx65-field"><label>Tickets max / membre</label><input data-tf="max_per_member" type="number" min="1" max="20" value="${Number(t.max_per_member||1)}"></div><div class="sx65-field"><label>Fermeture auto (heures)</label><input data-tf="autoclose_hours" type="number" min="0" max="720" value="${Number(t.autoclose_hours||0)}"></div><div class="sx65-field sx65-full"><label>Message d'ouverture</label><textarea data-tf="open_message" maxlength="1000">${E(t.open_message||"")}</textarea></div><div class="sx65-status sx65-full">${(t.questions||[]).length?`Formulaire existant conservé : ${(t.questions||[]).length} question(s).`:"Aucun formulaire configuré pour ce type."}</div></div></details></div>`}
function preview(){const p=panel();if(!p)return"";const types=editor?.types||[];return `<div class="sx65-preview" id="sx65PreviewBox"><h4>${E(document.getElementById("sx65Title")?.value||p.title||"Support")}</h4><p>${E(document.getElementById("sx65Description")?.value||p.description||"")}</p><div class="sx65-preview-types">${types.map(t=>`<span>${E(t.emoji||"🎫")} ${E(t.button_label||t.name||"Ticket")}</span>`).join("")}</div></div>`}
function render(){const r=fieldRoot();if(!r)return;if(!center){r.innerHTML='<div class="sx65-loading">Chargement du système de tickets…</div>';return}const panels=center.panels||[];if(!panels.length){r.innerHTML=`<div class="sx65-empty"><h3>Tickets</h3><p>Aucun panel n'est encore configuré. Créez le premier panel, puis SentriX vous guide en 4 étapes.</p><button class="sx65-btn primary" id="sx65FirstPanel" type="button">Créer mon premier panel</button></div>`;document.getElementById("sx65FirstPanel")?.addEventListener("click",createPanel);return}const p=panel()||panels[0];if(String(p.id)!==String(selected)){selected=String(p.id);loadEditor().catch(error=>notify(error.message,true));return}if(!editor){r.innerHTML='<div class="sx65-loading">Chargement du panel…</div>';return}const rules=p.role_rules||{access_role_ids:[],ping_role_ids:[]};const support=String((editor.types||[]).find(t=>t.staff_role_id)?.staff_role_id||"");r.innerHTML=`<div class="sx65-actions"><div><b style="color:#f2eff7">Tickets</b><div class="sx65-status">Configuration guidée · 4 étapes</div></div><button class="sx65-btn" id="sx65SaveTop" type="button">Enregistrer</button><button class="sx65-btn danger" id="sx65DeletePanel" type="button">Supprimer ce panel</button></div><div class="sx65-shell"><aside class="sx65-side"><div class="sx65-side-head"><h3>Panels</h3><p>Choisissez le panel à modifier.</p></div><div class="sx65-side-body">${panels.map(x=>`<button class="sx65-panel ${String(x.id)===String(selected)?"active":""}" data-panel="${E(x.id)}" type="button"><b>${E(x.name)}</b><span>${x.enabled?"Actif":"Désactivé"} · ${Number(x.type_count||0)} type(s)</span></button>`).join("")}<button class="sx65-new" id="sx65NewPanel" type="button">+ Nouveau panel</button></div></aside><main class="sx65-main"><section class="sx65-step"><div class="sx65-step-head"><h3>1 · Général</h3><p>Le minimum nécessaire pour que les tickets soient propres.</p></div><div class="sx65-step-body sx65-grid"><div class="sx65-field"><label>Nom du panel</label><input id="sx65Name" maxlength="80" value="${E(p.name)}"></div><div class="sx65-field"><label>Tickets max / membre</label><input id="sx65Max" type="number" min="1" max="20" value="${Number(p.max_per_member||1)}"></div><label class="sx65-switch sx65-full"><input id="sx65Enabled" type="checkbox" ${p.enabled?"checked":""}> Panel actif</label></div></section><section class="sx65-step"><div class="sx65-step-head"><h3>2 · Équipe</h3><p>Qui voit les tickets, qui les gère et qui est ping à l'ouverture.</p></div><div class="sx65-step-body sx65-grid"><div class="sx65-field"><label>Rôle de gestion</label><select id="sx65Support">${roleOptions(support)}</select><small>Ce rôle reçoit les permissions staff dans les salons de ticket.</small></div><div></div><div class="sx65-field"><label>Rôles qui ont accès aux tickets</label>${roleChecks("access",rules.access_role_ids||[])}</div><div class="sx65-field"><label>Rôles à ping à l'ouverture</label>${roleChecks("ping",rules.ping_role_ids||[])}</div></div></section><section class="sx65-step"><div class="sx65-step-head"><h3>3 · Panel</h3><p>Ce que les membres voient avant d'ouvrir un ticket.</p></div><div class="sx65-step-body"><div class="sx65-grid"><div class="sx65-field"><label>Titre</label><input id="sx65Title" maxlength="256" value="${E(p.title||"")}"></div><div class="sx65-field"><label>Affichage</label><select id="sx65Style"><option value="button" ${p.style==="button"?"selected":""}>Boutons</option><option value="select" ${p.style==="select"?"selected":""}>Menu déroulant</option></select></div><div class="sx65-field sx65-full"><label>Description</label><textarea id="sx65Description" maxlength="2000">${E(p.description||"")}</textarea></div></div><div class="sx65-types" id="sx65Types">${(editor.types||[]).map(typeCard).join("")||'<div class="sx65-status">Aucun type. Ajoutez au moins un bouton avant de publier.</div>'}</div><button class="sx65-btn" id="sx65AddType" type="button">+ Ajouter un type de ticket</button><details class="sx65-advanced"><summary>Options avancées du panel</summary><div class="sx65-advanced-body sx65-grid"><div class="sx65-field"><label>Couleur hex</label><input id="sx65Color" maxlength="7" value="${p.color?"#"+Number(p.color).toString(16).padStart(6,"0"):"#5865F2"}"></div><div class="sx65-field"><label>Footer</label><input id="sx65Footer" maxlength="200" value="${E(p.footer_text||"")}"></div><div class="sx65-field sx65-full"><label>Image</label><input id="sx65Image" maxlength="2000" value="${E(p.image_url||"")}" placeholder="https://…"></div><div class="sx65-field sx65-full"><label>Miniature</label><input id="sx65Thumb" maxlength="2000" value="${E(p.thumbnail_url||"")}" placeholder="https://…"></div></div></details></div></section><section class="sx65-step"><div class="sx65-step-head"><h3>4 · Publication</h3><p>Prévisualisez puis publiez. Si le panel existe déjà, le bouton le met à jour sans créer de doublon.</p></div><div class="sx65-step-body">${preview()}<div class="sx65-grid"><div class="sx65-field"><label>Salon du panel</label><select id="sx65PublishChannel">${channelOptions(p.channel_id||"")}</select></div><div class="sx65-actions" style="align-self:end"><button class="sx65-btn" id="sx65RefreshPreview" type="button">Actualiser l'aperçu</button><button class="sx65-btn primary" id="sx65Publish" type="button">${p.message_id?"Mettre à jour le panel":"Publier le panel"}</button></div></div><div class="sx65-status" id="sx65Status">Les tickets déjà ouverts ne sont jamais supprimés par cette page.</div></div></section></main></div>`;bind()}
function captureTypes(){document.querySelectorAll("[data-type-index]").forEach(card=>{const i=Number(card.dataset.typeIndex),t=editor.types[i];if(!t)return;card.querySelectorAll("[data-tf]").forEach(x=>{let v=x.value;if(x.type==="number")v=Number(v);t[x.dataset.tf]=v});t.position=i});const support=document.getElementById("sx65Support")?.value||null;(editor.types||[]).forEach(t=>{t.staff_role_id=support||null;t.mention_staff=true})}
async function save(showToast=true){if(busy)return false;captureTypes();const p=panel();if(!p)return false;busy=true;document.querySelectorAll(".sx65-btn").forEach(b=>b.disabled=true);try{const panelBody={name:document.getElementById("sx65Name")?.value||p.name,title:document.getElementById("sx65Title")?.value||p.title,description:document.getElementById("sx65Description")?.value||"",color:document.getElementById("sx65Color")?.value||null,image_url:document.getElementById("sx65Image")?.value||"",thumbnail_url:document.getElementById("sx65Thumb")?.value||"",footer_text:document.getElementById("sx65Footer")?.value||"",style:document.getElementById("sx65Style")?.value||"button",max_per_member:Number(document.getElementById("sx65Max")?.value||1),enabled:!!document.getElementById("sx65Enabled")?.checked,access_role_ids:checkedRoles("access"),ping_role_ids:checkedRoles("ping"),types:[],deleted_type_ids:[]};await api(`/api/guilds/${gid()}/ticket-center/panels/${selected}`,{method:"PATCH",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify(panelBody)});await api(`/api/guilds/${gid()}/ticket-button-editor/${selected}`,{method:"PATCH",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({types:editor.types,staff_buttons:editor.staff_buttons})});if(showToast)notify("Configuration tickets enregistrée.");await load(true);return true}catch(e){notify(e.message||"Impossible d'enregistrer les tickets.",true);return false}finally{busy=false;document.querySelectorAll(".sx65-btn").forEach(b=>b.disabled=false)}}
async function publish(){const channel=document.getElementById("sx65PublishChannel")?.value;if(!channel)return notify("Choisissez le salon où publier le panel.",true);const ok=await save(false);if(!ok)return;busy=true;try{const body=await api(`/api/guilds/${gid()}/ticket-simple/panels/${selected}/publish`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({channel_id:channel})});notify(body.message||"Panel publié.");await load(true)}catch(e){notify(e.message||"Publication impossible.",true)}finally{busy=false}}
async function createPanel(){if(busy)return;const name=prompt("Nom du nouveau panel :","Support");if(!name?.trim())return;busy=true;try{const made=await api(`/api/guilds/${gid()}/ticket-center/panels`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({name:name.trim()})});const id=String(made.panel_id);const fresh=await api(`/api/guilds/${gid()}/ticket-button-editor/${id}`);await api(`/api/guilds/${gid()}/ticket-button-editor/${id}`,{method:"PATCH",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({types:[{id:null,name:"Support",description:"Besoin d'aide",emoji:"🎫",button_label:"Ouvrir un ticket",button_style:"bleu",category_id:null,name_format:"ticket-{pseudo}",open_message:"Bonjour, expliquez votre demande ici.",max_per_member:1,autoclose_hours:0,staff_role_id:null,mention_staff:true,use_form:false,position:0,questions:[]}],staff_buttons:fresh.staff_buttons})});selected=id;notify("Panel créé. Configurez maintenant les 4 étapes.");await load(true)}catch(e){notify(e.message||"Création impossible.",true)}finally{busy=false}}
async function removePanel(){const p=panel();if(!p||!confirm(`Supprimer le panel « ${p.name} » ? Les tickets déjà ouverts resteront intacts.`))return;busy=true;try{await api(`/api/guilds/${gid()}/ticket-center/panels/${selected}`,{method:"DELETE",headers:{"X-CSRF-Token":csrf()}});selected="";notify("Panel supprimé.");await load(true)}catch(e){notify(e.message||"Suppression impossible.",true)}finally{busy=false}}
function bind(){document.querySelectorAll("[data-panel]").forEach(b=>b.addEventListener("click",()=>{selected=String(b.dataset.panel);editor=null;render();loadEditor().catch(e=>notify(e.message,true))}));document.getElementById("sx65NewPanel")?.addEventListener("click",createPanel);document.getElementById("sx65SaveTop")?.addEventListener("click",()=>save(true));document.getElementById("sx65DeletePanel")?.addEventListener("click",removePanel);document.getElementById("sx65AddType")?.addEventListener("click",()=>{captureTypes();editor.types.push({id:null,name:"Support",description:"",emoji:"🎫",button_label:"Ouvrir un ticket",button_style:"bleu",category_id:null,name_format:"ticket-{pseudo}",open_message:"",max_per_member:1,autoclose_hours:0,staff_role_id:null,mention_staff:true,use_form:false,position:editor.types.length,questions:[]});render()});document.querySelectorAll("[data-remove-type]").forEach(b=>b.addEventListener("click",()=>{captureTypes();const i=Number(b.dataset.removeType);if((editor.types||[]).length<=1)return notify("Gardez au moins un type de ticket.",true);editor.types.splice(i,1);render()}));document.getElementById("sx65RefreshPreview")?.addEventListener("click",()=>{captureTypes();const box=document.getElementById("sx65PreviewBox");if(box){const holder=document.createElement("div");holder.innerHTML=preview();box.replaceWith(holder.firstElementChild)}});document.getElementById("sx65Publish")?.addEventListener("click",publish)}
async function loadEditor(){if(!selected){editor=null;render();return}editor=await api(`/api/guilds/${gid()}/ticket-button-editor/${selected}`);render()}
async function load(force=false){if(!active())return;const g=gid();if(!g)return;fieldRoot();if(!force&&guild===g&&center)return render();guild=g;center=null;editor=null;resources=null;render();try{const [c,res]=await Promise.all([api(`/api/guilds/${g}/ticket-center`),api(`/api/guilds/${g}/ticket-simple/resources`)]);if(!active()||gid()!==g)return;center=c;resources=res;if(!selected||(center.panels||[]).every(p=>String(p.id)!==String(selected)))selected=center.panels?.[0]?String(center.panels[0].id):"";if(selected)editor=await api(`/api/guilds/${g}/ticket-button-editor/${selected}`);render()}catch(e){const r=fieldRoot();if(r)r.innerHTML=`<div class="sx65-empty"><h3>Impossible de charger les tickets</h3><p>${E(e.message||"Erreur inconnue")}</p><button class="sx65-btn" id="sx65Retry" type="button">Réessayer</button></div>`;document.getElementById("sx65Retry")?.addEventListener("click",()=>load(true));notify(e.message||"Chargement tickets impossible.",true)}}
function activate(){if(!active()){fieldRoot();return}setTimeout(()=>load(false),30)}
if(typeof renderTab==="function"){const old=renderTab;renderTab=function(...args){const out=old.apply(this,args);activate();return out}}
if(typeof selectGuild==="function"){const oldSelect=selectGuild;selectGuild=async function(...args){const out=await oldSelect.apply(this,args);guild="";center=null;editor=null;resources=null;selected="";activate();return out}}
new MutationObserver(()=>{if(active())fieldRoot()}).observe(document.documentElement,{subtree:true,childList:true});
activate();
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-ticket-simple-v65-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    else:
        html += CSS + JS
    return html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    async def resources(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        channels = [
            {"id": str(channel.id), "name": channel.name, "position": channel.position}
            for channel in guild.text_channels
        ]
        channels.sort(key=lambda item: (item["position"], item["name"].casefold()))
        return web.json_response({"ok": True, "channels": channels})

    async def publish(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
            panel_id = int(request.match_info["panel_id"])
        except ValueError:
            return dashboard._json_error("Identifiant invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        try:
            payload = await request.json()
            channel_id = int(payload.get("channel_id"))
        except (TypeError, ValueError, AttributeError):
            return dashboard._json_error("Choisissez un salon de publication valide.", 400)

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return dashboard._json_error("Le salon choisi doit être un salon textuel de ce serveur.", 400)

        bot = request.app["bot"]
        db = bot.db
        panel = await db.fetchone(
            "SELECT * FROM ticket_panels_v2 WHERE id = ? AND guild_id = ?",
            (panel_id, guild_id),
        )
        if not panel:
            return dashboard._json_error("Panel introuvable.", 404)
        cog = bot.get_cog("Tickets")
        if cog is None:
            return dashboard._json_error("Le moteur Tickets termine son démarrage. Réessayez dans quelques secondes.", 503)
        types = await cog.get_panel_types(panel_id)
        if not types:
            return dashboard._json_error("Ajoutez au moins un type de ticket avant de publier le panel.", 400)

        old_channel_id = int(panel["channel_id"]) if panel["channel_id"] else None
        old_message_id = int(panel["message_id"]) if panel["message_id"] else None
        await db.execute(
            "UPDATE ticket_panels_v2 SET channel_id = ?, enabled = 1 WHERE id = ? AND guild_id = ?",
            (channel_id, panel_id, guild_id),
        )

        # Même salon + message existant : on édite au lieu de supprimer/recréer, pour ne
        # jamais produire deux panels lors d'un simple clic sur « Mettre à jour ».
        if old_message_id and old_channel_id == channel_id:
            try:
                from . import ticket_center_v35
                sync = await ticket_center_v35._sync_panel_message(bot, guild, panel_id)
                if sync == "updated":
                    return web.json_response({
                        "ok": True,
                        "message": f"Panel mis à jour dans #{channel.name}.",
                        "state": "updated",
                    })
            except Exception:
                logger.exception("Mise à jour directe du panel #%s impossible ; nouvel envoi tenté.", panel_id)

        # Déplacement vers un autre salon : l'ancien message du panel est retiré, mais les
        # tickets déjà ouverts ne sont évidemment jamais touchés.
        if old_message_id and old_channel_id:
            old_channel = guild.get_channel(old_channel_id)
            if isinstance(old_channel, discord.TextChannel):
                try:
                    old_message = await old_channel.fetch_message(old_message_id)
                    await old_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        await db.execute(
            "UPDATE ticket_panels_v2 SET message_id = NULL, channel_id = ?, enabled = 1 WHERE id = ? AND guild_id = ?",
            (channel_id, panel_id, guild_id),
        )
        fresh_panel = await db.fetchone(
            "SELECT * FROM ticket_panels_v2 WHERE id = ? AND guild_id = ?",
            (panel_id, guild_id),
        )
        try:
            from cogs.tickets import TicketPanelView
            from utils import sentrix_panels as sx_panels
            message = await sx_panels.envoyer(
                channel,
                sx_panels.avec_composants(
                    sx_panels.depuis_embed(cog.build_panel_embed(fresh_panel)),
                    TicketPanelView(fresh_panel, types),
                ),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Publication du panel #%s refusée dans %s : %s", panel_id, channel_id, exc)
            return dashboard._json_error(
                "SentriX ne peut pas publier dans ce salon. Vérifiez Envoyer des messages, Voir le salon et Intégrer des liens.",
                403,
            )

        await db.execute(
            "UPDATE ticket_panels_v2 SET message_id = ?, channel_id = ?, enabled = 1 WHERE id = ? AND guild_id = ?",
            (message.id, channel_id, panel_id, guild_id),
        )
        logger.info(
            "Dashboard : %s (%s) a publié le panel ticket #%s dans %s (%s).",
            session["user"].get("username"),
            session["user"].get("id"),
            panel_id,
            channel.name,
            channel.id,
        )
        return web.json_response({
            "ok": True,
            "message": f"Panel publié dans #{channel.name}.",
            "state": "published",
            "message_id": str(message.id),
        })

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/ticket-simple/resources", resources)
        app.router.add_post("/api/guilds/{guild_id}/ticket-simple/panels/{panel_id}/publish", publish)
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Dashboard Tickets V65 installé : Général → Équipe → Panel → Publication.")


__all__ = ["install"]