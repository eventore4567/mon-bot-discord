"""Dashboard V35 — centre de gestion et éditeur des panels de tickets SentriX.

Le centre expose les panels déjà présents dans ticket_panels_v2 et permet de les modifier
sans les recréer : texte, apparence, types/boutons, rôles d'accès et rôles à ping.
Une sauvegarde tente aussi de mettre à jour le message Discord déjà envoyé.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import discord
from aiohttp import web

from database.db import now

logger = logging.getLogger("bot.dashboard.ticket-center-v35")
_INSTALLED = False

CSS = r"""
<style id="sentrix-ticket-center-v35-css">
#sentrixTicketCenterV35{grid-column:1/-1;margin-top:10px;display:grid;gap:10px}
.sx-ticket-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:6px;border-top:1px solid #252c3b}
.sx-ticket-head h3{margin:0;color:#f1eff6;font-size:15px}.sx-ticket-head p{margin:3px 0 0;color:#7e8799;font-size:10px}
.sx-ticket-refresh{min-height:32px;padding:0 11px;border:1px solid #31394d;border-radius:8px;background:#171d29;color:#e8e6ee;font-weight:750;cursor:pointer}
.sx-ticket-summary{display:flex;gap:7px;flex-wrap:wrap}.sx-ticket-summary span{padding:5px 8px;border:1px solid #283145;border-radius:8px;background:#101620;color:#98a2b4;font-size:9px}.sx-ticket-summary b{color:#eeeaf4}
.sx-ticket-section{border:1px solid #252d40;border-radius:11px;background:#0f141e;overflow:hidden}
.sx-ticket-section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 11px;border-bottom:1px solid #222a3a}.sx-ticket-section-head b{font-size:11px;color:#efedf5}.sx-ticket-section-head span{font-size:9px;color:#778095}
.sx-ticket-create{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;padding:8px 11px;border-bottom:1px solid #222a3a}.sx-ticket-create input{min-width:0}.sx-ticket-create button{min-height:34px;padding:0 11px;border:1px solid #725bd0;border-radius:8px;background:#765de0;color:#fff;font-weight:800;cursor:pointer}
.sx-ticket-list{display:grid}.sx-ticket-row{display:grid;grid-template-columns:minmax(170px,1.2fr) minmax(120px,.75fr) auto;gap:9px;align-items:center;min-height:48px;padding:7px 11px;border-top:1px solid #1e2533}.sx-ticket-row:first-child{border-top:0}
.sx-ticket-main{min-width:0}.sx-ticket-main b{display:block;color:#eceaf2;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sx-ticket-main span,.sx-ticket-cell{display:block;color:#7d8698;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sx-ticket-state{display:inline-flex;align-items:center;justify-content:center;padding:4px 7px;border:1px solid #343d52;border-radius:999px;background:#171d29;color:#b7bfd0;font-size:8px;font-weight:900;text-transform:uppercase}.sx-ticket-state.on{border-color:#3d6454;background:#15261f;color:#8ed8b4}
.sx-ticket-actions{display:flex;justify-content:flex-end;gap:5px;flex-wrap:wrap}.sx-ticket-actions button,.sx-ticket-actions a{display:inline-flex;align-items:center;justify-content:center;min-height:30px;padding:0 9px;border:1px solid #343d52;border-radius:8px;background:#171d29;color:#dcd9e4;font-size:9px;font-weight:800;text-decoration:none;cursor:pointer}.sx-ticket-actions .primary{border-color:#6c55c8;background:#271f45;color:#cbbdff}
.sx-ticket-empty{padding:15px 11px;color:#757e91;font-size:10px;text-align:center}.sx-ticket-error{padding:10px 11px;border:1px solid #67333a;border-radius:9px;background:#281519;color:#e99aa3;font-size:10px}
.sx-ticket-open-details>summary{cursor:pointer;padding:10px 11px;color:#aeb6c6;font-size:10px;font-weight:800;list-style:none}.sx-ticket-open-details>summary::-webkit-details-marker{display:none}.sx-ticket-open-details>summary::after{content:"Afficher";float:right;color:#7f899c;font-size:9px}.sx-ticket-open-details[open]>summary::after{content:"Masquer"}

.sx-ticket-editor-backdrop{position:fixed;inset:0;z-index:10000;display:grid;place-items:center;padding:18px;background:rgba(4,7,12,.76);backdrop-filter:blur(4px)}
.sx-ticket-editor{width:min(780px,100%);max-height:min(86vh,900px);display:flex;flex-direction:column;border:1px solid #39435a;border-radius:14px;background:#0b1019;box-shadow:0 24px 80px rgba(0,0,0,.55);overflow:hidden}
.sx-ticket-editor-head{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:12px 14px;border-bottom:1px solid #252d3e}.sx-ticket-editor-head h4{margin:0;font-size:14px;color:#f0edf5}.sx-ticket-editor-head p{margin:3px 0 0;color:#7f899c;font-size:9px}
.sx-editor-body{padding:11px;display:grid;gap:8px;overflow:auto}
.sx-editor-section{border:1px solid #273044;border-radius:10px;background:#0f151f;overflow:visible}.sx-editor-section>summary{cursor:pointer;list-style:none;padding:10px 11px;color:#e5e2eb;font-size:10px;font-weight:850}.sx-editor-section>summary::-webkit-details-marker{display:none}.sx-editor-section>summary::after{content:"+";float:right;color:#8a94a7;font-size:14px;line-height:10px}.sx-editor-section[open]>summary::after{content:"–"}.sx-editor-section-body{padding:0 11px 11px;display:grid;gap:9px}
.sx-editor-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.sx-editor-grid .full{grid-column:1/-1}.sx-editor-field label{display:block;margin:0 0 4px;color:#aeb6c6;font-size:9px;font-weight:800}.sx-editor-field small{display:block;margin-top:3px;color:#727d90;font-size:8px;line-height:1.35}.sx-editor-field input,.sx-editor-field textarea,.sx-editor-field select{width:100%;box-sizing:border-box;background:#111824;color:#eae8ef;border:1px solid #2c3548;border-radius:8px;padding:7px 8px;font:inherit;font-size:10px}.sx-editor-field textarea{min-height:68px;resize:vertical}
.sx-editor-note{padding:8px 9px;border:1px solid #2b3448;border-radius:8px;background:#111722;color:#8993a6;font-size:9px;line-height:1.45}

.sx-role-picker{position:relative}.sx-role-picker-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.sx-role-picker-title b{display:block;color:#b7c0d1;font-size:9px}.sx-role-picker-title span{display:block;margin-top:2px;color:#707b8e;font-size:8px;line-height:1.3}.sx-role-picker-button{min-height:31px;max-width:210px;padding:0 9px;border:1px solid #354057;border-radius:8px;background:#151c28;color:#e3e0e9;font-size:9px;font-weight:800;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sx-role-popover{margin-top:7px;border:1px solid #354057;border-radius:9px;background:#0b111b;padding:8px;box-shadow:0 12px 35px rgba(0,0,0,.35)}.sx-role-popover.sx-hidden{display:none}.sx-role-search{width:100%;box-sizing:border-box;margin-bottom:6px;background:#111824;color:#eeeaf4;border:1px solid #2f394e;border-radius:7px;padding:7px 8px;font-size:9px}.sx-role-list{max-height:170px;overflow:auto;display:grid;gap:2px}.sx-role-option{display:flex;align-items:center;gap:7px;padding:6px 7px;border-radius:7px;color:#c9cfda;font-size:9px;cursor:pointer}.sx-role-option:hover{background:#151d2a}.sx-role-option input{width:auto;margin:0}.sx-role-option.sx-filtered{display:none}.sx-role-footer{display:flex;justify-content:flex-end;gap:6px;margin-top:7px;padding-top:7px;border-top:1px solid #222b3d}.sx-role-footer button{min-height:28px;padding:0 8px;border:1px solid #354057;border-radius:7px;background:#151c28;color:#d9d6df;font-size:8px;font-weight:800;cursor:pointer}.sx-role-footer .done{background:#6651c3;border-color:#745ed3;color:#fff}
.sx-selected-roles{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}.sx-selected-role{padding:3px 6px;border:1px solid #33415a;border-radius:999px;background:#151d2a;color:#aeb9ca;font-size:8px}.sx-selected-role.more{color:#8d97a9}

.sx-type-wrap{display:grid;gap:7px}.sx-type-card{border:1px solid #293246;border-radius:9px;background:#0d131d;overflow:visible}.sx-type-card>summary{display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:pointer;list-style:none;padding:9px 10px}.sx-type-card>summary::-webkit-details-marker{display:none}.sx-type-card>summary b{display:block;color:#e7e4ed;font-size:10px}.sx-type-card>summary span{display:block;margin-top:2px;color:#768195;font-size:8px}.sx-type-card>summary em{font-style:normal;color:#8e98aa;font-size:8px}.sx-type-body{padding:0 10px 10px;display:grid;gap:8px}.sx-type-advanced{border-top:1px solid #222b3c;padding-top:3px}.sx-type-advanced>summary{cursor:pointer;color:#8792a5;font-size:8px;font-weight:800;padding:5px 0}.sx-inherit-row{display:flex!important;align-items:center;gap:7px;padding:7px 8px;border:1px solid #2b3549;border-radius:8px;background:#111824;color:#bdc5d3!important;font-size:9px!important;cursor:pointer}.sx-inherit-row input{width:auto!important;margin:0}.sx-type-role-overrides.sx-hidden{display:none}.sx-mini-danger{justify-self:start;border:1px solid #64343b;background:#26161a;color:#efa3ac;border-radius:7px;padding:5px 8px;font-size:8px;cursor:pointer}
.sx-editor-add{min-height:31px;padding:0 9px;border:1px solid #6550bd;border-radius:8px;background:#211b39;color:#cdbfff;font-size:9px;font-weight:800;cursor:pointer}
.sx-editor-footer{display:flex;justify-content:flex-end;gap:7px;padding:10px 12px;border-top:1px solid #252d3e;background:#0d121b}.sx-editor-footer button{min-height:33px;padding:0 11px;border-radius:8px;border:1px solid #343d52;background:#171d29;color:#e5e2ea;font-weight:800;font-size:9px;cursor:pointer}.sx-editor-footer .save{background:#6f57d4;border-color:#7e65e7;color:#fff}.sx-editor-footer .delete{margin-right:auto;background:#2b171b;border-color:#69343d;color:#f1a2aa}
@media(max-width:720px){.sx-ticket-editor-backdrop{padding:8px}.sx-ticket-editor{max-height:94vh}.sx-editor-grid{grid-template-columns:1fr}.sx-editor-grid .full{grid-column:auto}.sx-ticket-row{grid-template-columns:minmax(0,1fr) auto}.sx-ticket-cell{display:none}.sx-role-picker-top{align-items:flex-start;flex-direction:column}.sx-role-picker-button{max-width:100%;width:100%}.sx-ticket-create{grid-template-columns:1fr}.sx-ticket-create button{width:100%}}
</style>
"""

JS = r"""
<script id="sentrix-ticket-center-v35-js">
(() => {
"use strict";
if(window.__sentrixTicketCenterV35)return;window.__sentrixTicketCenterV35=true;
let loadedGuild="",loading=false,data=null,editingId=null,editorTypes=[],deletedTypeIds=[];
const $=id=>document.getElementById(id);
function guildId(){try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):""}catch(_){return""}}
function csrf(){try{return typeof state!=="undefined"?state.csrf||"":""}catch(_){return""}}
function active(){try{return typeof state!=="undefined"&&state.tab==="tickets"}catch(_){return false}}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function toast35(m,b=false){try{if(typeof toast==="function")return toast(m,b)}catch(_){}(b?console.error:console.info)(m)}
function age(ts){if(!ts)return"—";const s=Math.max(0,Math.floor(Date.now()/1000)-Number(ts));if(s<60)return`${s}s`;if(s<3600)return`${Math.floor(s/60)} min`;if(s<86400)return`${Math.floor(s/3600)} h`;return`${Math.floor(s/86400)} j`}
function root(){if(!active()){$("sentrixTicketCenterV35")?.remove();return null}const f=$("fields");if(!f)return null;let el=$("sentrixTicketCenterV35");if(!el){el=document.createElement("section");el.id="sentrixTicketCenterV35";f.appendChild(el)}return el}
function channelName(id){const x=data?.channels?.[String(id)];return x?`#${x.name}`:`ID ${id}`}
function singleRoleOptions(selected="",includeEmpty=true){const chosen=String(selected||"");let h=includeEmpty?'<option value="">Aucun rôle</option>':"";return h+(data?.roles||[]).map(r=>`<option value="${esc(r.id)}" ${chosen===String(r.id)?"selected":""}>@${esc(r.name)}</option>`).join("")}
function roleName(id){return data?.roles?.find(r=>String(r.id)===String(id))?.name||`ID ${id}`}
function roleSummary(ids=[]){const values=(ids||[]).map(String);if(!values.length)return"Choisir des rôles";const names=values.slice(0,2).map(id=>`@${roleName(id)}`);return names.join(", ")+(values.length>2?` +${values.length-2}`:"")}
function roleChips(ids=[]){const values=(ids||[]).map(String);if(!values.length)return'<span class="sx-selected-role more">Aucun rôle sélectionné</span>';return values.slice(0,4).map(id=>`<span class="sx-selected-role">@${esc(roleName(id))}</span>`).join("")+(values.length>4?`<span class="sx-selected-role more">+${values.length-4}</span>`:"")}
function rolePicker(key,selected,title,help){const chosen=new Set((selected||[]).map(String)),roles=data?.roles||[];return`<div class="sx-role-picker" data-role-picker="${esc(key)}"><div class="sx-role-picker-top"><div class="sx-role-picker-title"><b>${esc(title)}</b><span>${esc(help)}</span></div><button class="sx-role-picker-button" data-role-picker-button="${esc(key)}" type="button" aria-expanded="false">${esc(roleSummary(selected))}</button></div><div class="sx-selected-roles" data-role-chips="${esc(key)}">${roleChips(selected)}</div><div class="sx-role-popover sx-hidden" data-role-picker-popover="${esc(key)}"><input class="sx-role-search" data-role-search="${esc(key)}" type="search" placeholder="Rechercher un rôle"><div class="sx-role-list">${roles.length?roles.map(r=>`<label class="sx-role-option" data-role-row="${esc(key)}" data-role-text="${esc(String(r.name).toLowerCase())}"><input data-role-check="${esc(key)}" type="checkbox" value="${esc(r.id)}" ${chosen.has(String(r.id))?"checked":""}><span>@${esc(r.name)}</span></label>`).join(""):'<div class="sx-ticket-empty">Aucun rôle disponible.</div>'}</div><div class="sx-role-footer"><button data-role-clear="${esc(key)}" type="button">Tout retirer</button><button class="done" data-role-done="${esc(key)}" type="button">Terminer</button></div></div></div>`}
function pickerValues(key){return Array.from(document.querySelectorAll(`[data-role-check="${key}"]:checked`)).map(el=>el.value)}
function updatePicker(key){const values=pickerValues(key),button=document.querySelector(`[data-role-picker-button="${key}"]`),chips=document.querySelector(`[data-role-chips="${key}"]`);if(button)button.textContent=roleSummary(values);if(chips)chips.innerHTML=roleChips(values)}
function bindRolePickers(){document.querySelectorAll("[data-role-picker-button]").forEach(button=>button.addEventListener("click",()=>{const key=button.dataset.rolePickerButton,pop=document.querySelector(`[data-role-picker-popover="${key}"]`),opening=pop?.classList.contains("sx-hidden");document.querySelectorAll(".sx-role-popover").forEach(x=>x.classList.add("sx-hidden"));document.querySelectorAll("[data-role-picker-button]").forEach(x=>x.setAttribute("aria-expanded","false"));if(pop&&opening){pop.classList.remove("sx-hidden");button.setAttribute("aria-expanded","true");setTimeout(()=>document.querySelector(`[data-role-search="${key}"]`)?.focus(),0)}}));document.querySelectorAll("[data-role-check]").forEach(check=>check.addEventListener("change",()=>updatePicker(check.dataset.roleCheck)));document.querySelectorAll("[data-role-search]").forEach(input=>input.addEventListener("input",()=>{const key=input.dataset.roleSearch,q=input.value.trim().toLowerCase();document.querySelectorAll(`[data-role-row="${key}"]`).forEach(row=>row.classList.toggle("sx-filtered",q&&!String(row.dataset.roleText||"").includes(q)))}));document.querySelectorAll("[data-role-clear]").forEach(button=>button.addEventListener("click",()=>{const key=button.dataset.roleClear;document.querySelectorAll(`[data-role-check="${key}"]`).forEach(x=>x.checked=false);updatePicker(key)}));document.querySelectorAll("[data-role-done]").forEach(button=>button.addEventListener("click",()=>{const key=button.dataset.roleDone,pop=document.querySelector(`[data-role-picker-popover="${key}"]`),toggle=document.querySelector(`[data-role-picker-button="${key}"]`);pop?.classList.add("sx-hidden");toggle?.setAttribute("aria-expanded","false")}))}
function renderPanels(){const rows=data?.panels||[];if(!rows.length)return'<div class="sx-ticket-empty">Aucun panel. Créez votre premier panel ci-dessus.</div>';return`<div class="sx-ticket-list">${rows.map(p=>`<div class="sx-ticket-row"><div class="sx-ticket-main"><b>${esc(p.name)}</b><span>${esc(p.title||"Sans titre")} · ${Number(p.type_count||0)} bouton(s)</span></div><span class="sx-ticket-cell">${p.channel_id?esc(channelName(p.channel_id)):"Pas encore envoyé"}</span><div class="sx-ticket-actions"><span class="sx-ticket-state ${p.enabled?"on":""}">${p.enabled?"Actif":"Inactif"}</span><button class="primary" data-panel-edit="${p.id}" type="button">Modifier</button><button data-panel-toggle="${p.id}" type="button">${p.enabled?"Désactiver":"Activer"}</button></div></div>`).join("")}</div>`}
function renderOpen(){const rows=data?.open_tickets||[];if(!rows.length)return'<div class="sx-ticket-empty">Aucun ticket ouvert.</div>';return`<div class="sx-ticket-list">${rows.map(t=>`<div class="sx-ticket-row"><div class="sx-ticket-main"><b>Ticket #${esc(t.id)}</b><span>${esc(channelName(t.channel_id))} · ${esc(age(t.created_at))}</span></div><span class="sx-ticket-cell">${t.claimed_by?`Pris par ${esc(t.claimed_by)}`:"En attente"}</span><div class="sx-ticket-actions"><a href="https://discord.com/channels/${guildId()}/${t.channel_id}" target="_blank" rel="noopener">Ouvrir</a></div></div>`).join("")}</div>`}
function typeCard(t,i){const rr=t.role_rules||{configured:false,access_role_ids:[],ping_role_ids:[]},inherit=Boolean(t.inherit_roles);return`<details class="sx-type-card" data-type-index="${i}" ${i===0?"open":""}><summary><div><b>${esc(t.button_label||t.name||`Bouton ${i+1}`)}</b><span>${esc(t.name||"Support")}${t.id?` · #${t.id}`:" · nouveau"}</span></div><em>Configurer</em></summary><div class="sx-type-body"><div class="sx-editor-grid"><div class="sx-editor-field"><label>Nom du bouton</label><input data-t="button_label" value="${esc(t.button_label||"")}" maxlength="80"></div><div class="sx-editor-field"><label>Nom du type</label><input data-t="name" value="${esc(t.name||"Support")}" maxlength="80"></div><div class="sx-editor-field"><label>Emoji</label><input data-t="emoji" value="${esc(t.emoji||"")}" maxlength="100"></div><div class="sx-editor-field"><label>Couleur</label><select data-t="button_style">${["bleu","gris","vert","rouge"].map(x=>`<option ${String(t.button_style||"bleu")===x?"selected":""}>${x}</option>`).join("")}</select></div></div><label class="sx-inherit-row"><input data-t="inherit_roles" data-inherit-type="${i}" type="checkbox" ${inherit?"checked":""}> Utiliser les mêmes rôles que le panel</label><div class="sx-type-role-overrides ${inherit?"sx-hidden":""}" data-type-role-overrides="${i}">${rolePicker(`type-${i}-access`,t.access_role_ids||rr.access_role_ids||[],"Rôles avec accès","Peuvent voir et répondre à ce type de ticket.")}${rolePicker(`type-${i}-ping`,t.ping_role_ids||rr.ping_role_ids||[],"Rôles à notifier","Sont seulement ping à l'ouverture de ce type.")}</div><details class="sx-type-advanced"><summary>Options avancées</summary><div class="sx-editor-grid"><div class="sx-editor-field full"><label>Description courte</label><input data-t="description" value="${esc(t.description||"")}" maxlength="150"></div><div class="sx-editor-field full"><label>Message d'ouverture</label><textarea data-t="open_message" maxlength="1000">${esc(t.open_message||"")}</textarea></div><div class="sx-editor-field"><label>Rôle de gestion</label><select data-t="staff_role_id">${singleRoleOptions(t.staff_role_id||"")}</select><small>Ce rôle contrôle les boutons staff du ticket.</small></div><div class="sx-editor-field"><label>Position</label><input data-t="position" type="number" min="0" max="24" value="${Number(t.position??i)}"></div></div></details><button class="sx-mini-danger" data-remove-type="${i}" type="button">Supprimer ce bouton</button></div></details>`}
function captureTypes(){document.querySelectorAll(".sx-type-card").forEach(card=>{const i=Number(card.dataset.typeIndex),t=editorTypes[i];if(!t)return;card.querySelectorAll("[data-t]").forEach(el=>{const k=el.dataset.t;if(k==="inherit_roles")t.inherit_roles=el.checked;else t[k]=el.value});t.access_role_ids=pickerValues(`type-${i}-access`);t.ping_role_ids=pickerValues(`type-${i}-ping`)})}
function renderEditor(){const p=data?.panels?.find(x=>String(x.id)===String(editingId));if(!p)return"";const rr=p.role_rules||{access_role_ids:[],ping_role_ids:[]};return`<div class="sx-ticket-editor-backdrop" id="sxEditorBackdrop"><div class="sx-ticket-editor" role="dialog" aria-modal="true" aria-label="Modifier le panel ${esc(p.name)}"><div class="sx-ticket-editor-head"><div><h4>${esc(p.name)}</h4><p>Modifiez seulement ce dont vous avez besoin.</p></div><button id="sxCloseEditor" class="sx-ticket-refresh" type="button">Fermer</button></div><div class="sx-editor-body"><details class="sx-editor-section" open><summary>1. Contenu du panel</summary><div class="sx-editor-section-body"><div class="sx-editor-grid"><div class="sx-editor-field"><label>Nom du panel</label><input id="sxPanelName" maxlength="80" value="${esc(p.name)}"></div><div class="sx-editor-field"><label>Titre affiché</label><input id="sxPanelTitle" maxlength="256" value="${esc(p.title||"")}"></div><div class="sx-editor-field full"><label>Description</label><textarea id="sxPanelDescription" maxlength="2000">${esc(p.description||"")}</textarea></div><div class="sx-editor-field"><label>Affichage</label><select id="sxPanelStyle"><option value="select" ${p.style!=="button"?"selected":""}>Menu déroulant</option><option value="button" ${p.style==="button"?"selected":""}>Boutons</option></select></div><div class="sx-editor-field"><label>Tickets max par membre</label><input id="sxPanelMax" type="number" min="1" max="20" value="${Number(p.max_per_member||1)}"></div><div class="sx-editor-field"><label>État</label><select id="sxPanelEnabled"><option value="1" ${p.enabled?"selected":""}>Actif</option><option value="0" ${!p.enabled?"selected":""}>Inactif</option></select></div></div></div></details><details class="sx-editor-section"><summary>2. Apparence optionnelle</summary><div class="sx-editor-section-body"><div class="sx-editor-grid"><div class="sx-editor-field"><label>Couleur hex</label><input id="sxPanelColor" maxlength="7" value="${p.color?("#"+Number(p.color).toString(16).padStart(6,"0")):""}" placeholder="#5865F2"></div><div class="sx-editor-field"><label>Footer</label><input id="sxPanelFooter" maxlength="200" value="${esc(p.footer_text||"")}"></div><div class="sx-editor-field full"><label>Image / bannière</label><input id="sxPanelImage" type="url" value="${esc(p.image_url||"")}" placeholder="https://..."></div><div class="sx-editor-field full"><label>Miniature</label><input id="sxPanelThumbnail" type="url" value="${esc(p.thumbnail_url||"")}" placeholder="https://..."></div></div></div></details><details class="sx-editor-section" open><summary>3. Rôles d'accès et notifications</summary><div class="sx-editor-section-body"><div class="sx-editor-note">Vous pouvez choisir plusieurs rôles simplement en cochant les cases. Aucun Ctrl/Cmd nécessaire.</div>${rolePicker("panel-access",rr.access_role_ids||[],"Rôles avec accès","Ils peuvent voir et répondre aux tickets, sans permission de modération.")}${rolePicker("panel-ping",rr.ping_role_ids||[],"Rôles à notifier","Ils sont uniquement ping quand un nouveau ticket s'ouvre.")}</div></details><details class="sx-editor-section" open><summary>4. Boutons du panel (${editorTypes.length})</summary><div class="sx-editor-section-body"><div><button id="sxAddType" class="sx-editor-add" type="button">Ajouter un bouton</button></div><div class="sx-type-wrap">${editorTypes.map(typeCard).join("")||'<div class="sx-ticket-empty">Aucun bouton. Ajoutez-en un pour permettre l’ouverture de tickets.</div>'}</div></div></details></div><div class="sx-editor-footer"><button id="sxDeletePanel" class="delete" type="button">Supprimer</button><button id="sxCancelEditor" type="button">Annuler</button><button id="sxSavePanel" class="save" type="button">Enregistrer</button></div></div></div>`}
function bindEditor(){if(!editingId)return;$("sxCloseEditor")?.addEventListener("click",closeEditor);$("sxCancelEditor")?.addEventListener("click",closeEditor);$("sxSavePanel")?.addEventListener("click",savePanel);$("sxDeletePanel")?.addEventListener("click",deletePanel);$("sxEditorBackdrop")?.addEventListener("click",e=>{if(e.target.id==="sxEditorBackdrop")closeEditor()});$("sxAddType")?.addEventListener("click",()=>{captureTypes();editorTypes.push({id:null,name:"Support",description:"",emoji:"",button_label:"Ouvrir un ticket",button_style:"bleu",open_message:"",staff_role_id:"",position:editorTypes.length,inherit_roles:true,access_role_ids:[],ping_role_ids:[],role_rules:{configured:false,access_role_ids:[],ping_role_ids:[]}});render()});document.querySelectorAll("[data-remove-type]").forEach(b=>b.addEventListener("click",()=>{captureTypes();const i=Number(b.dataset.removeType),t=editorTypes[i];if(t?.id)deletedTypeIds.push(Number(t.id));editorTypes.splice(i,1);render()}));document.querySelectorAll("[data-inherit-type]").forEach(box=>box.addEventListener("change",()=>{const target=document.querySelector(`[data-type-role-overrides="${box.dataset.inheritType}"]`);target?.classList.toggle("sx-hidden",box.checked)}));bindRolePickers()}
function openEditor(id){editingId=String(id);deletedTypeIds=[];const types=(data?.types||[]).filter(t=>String(t.panel_id)===String(id));editorTypes=JSON.parse(JSON.stringify(types)).map(t=>({...t,inherit_roles:!(t.role_rules?.configured),access_role_ids:t.role_rules?.access_role_ids||[],ping_role_ids:t.role_rules?.ping_role_ids||[]}));render()}
function closeEditor(){editingId=null;editorTypes=[];deletedTypeIds=[];render()}
function render(){const el=root();if(!el||!data)return;const m=data.metrics||{};el.innerHTML=`<div class="sx-ticket-head"><div><h3>Tickets</h3><p>Choisissez un panel puis cliquez sur Modifier.</p></div><button class="sx-ticket-refresh" id="sxTicketRefresh" type="button">Actualiser</button></div><div class="sx-ticket-summary"><span><b>${Number(m.open||0)}</b> ouverts</span><span><b>${Number(m.unclaimed||0)}</b> en attente</span><span><b>${Number(data.panels?.length||0)}</b> panels</span></div><section class="sx-ticket-section"><div class="sx-ticket-section-head"><b>Panels</b><span>${Number(data.panels?.length||0)} configuré(s)</span></div><div class="sx-ticket-create"><input id="sxTicketPanelName" maxlength="80" placeholder="Nom du nouveau panel"><button id="sxTicketCreatePanel" type="button">Créer</button></div>${renderPanels()}</section><details class="sx-ticket-section sx-ticket-open-details"><summary>Tickets ouverts (${Number(data.open_tickets?.length||0)})</summary>${renderOpen()}</details>${editingId?renderEditor():""}`;$("sxTicketRefresh")?.addEventListener("click",()=>load(guildId(),true));$("sxTicketCreatePanel")?.addEventListener("click",createPanel);el.querySelectorAll("[data-panel-toggle]").forEach(b=>b.addEventListener("click",()=>togglePanel(b.dataset.panelToggle)));el.querySelectorAll("[data-panel-edit]").forEach(b=>b.addEventListener("click",()=>openEditor(b.dataset.panelEdit)));bindEditor()}
async function api(url,options={}){const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...options});const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.error||"Action impossible.");return b}
async function load(id,force=false){if(!id||loading)return;if(!force&&loadedGuild===id&&data){render();return}loading=true;try{const body=await api(`/api/guilds/${id}/ticket-center`);if(guildId()!==id||!active())return;loadedGuild=id;data=body;render()}catch(e){const el=root();if(el)el.innerHTML=`<div class="sx-ticket-error">${esc(e.message)}</div>`;toast35(e.message,true)}finally{loading=false}}
async function createPanel(){const id=guildId(),name=$("sxTicketPanelName")?.value.trim();if(!name)return toast35("Entrez un nom pour le panel.",true);try{const b=await api(`/api/guilds/${id}/ticket-center/panels`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({name})});toast35(b.message||"Panel créé.");data=null;await load(id,true);if(b.panel_id)openEditor(b.panel_id)}catch(e){toast35(e.message,true)}}
async function togglePanel(pid){try{const b=await api(`/api/guilds/${guildId()}/ticket-center/panels/${pid}/toggle`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:"{}"});toast35(b.message||"Panel mis à jour.");data=null;await load(guildId(),true)}catch(e){toast35(e.message,true)}}
async function savePanel(){captureTypes();const payload={name:$("sxPanelName").value,title:$("sxPanelTitle").value,description:$("sxPanelDescription").value,color:$("sxPanelColor").value,image_url:$("sxPanelImage").value,thumbnail_url:$("sxPanelThumbnail").value,footer_text:$("sxPanelFooter").value,style:$("sxPanelStyle").value,max_per_member:Number($("sxPanelMax").value),enabled:$("sxPanelEnabled").value==="1",access_role_ids:pickerValues("panel-access"),ping_role_ids:pickerValues("panel-ping"),deleted_type_ids:deletedTypeIds,types:editorTypes.map((t,i)=>({id:t.id||null,name:t.name,description:t.description,emoji:t.emoji,button_label:t.button_label,button_style:t.button_style,open_message:t.open_message,staff_role_id:t.staff_role_id||null,position:Number(t.position??i),inherit_roles:Boolean(t.inherit_roles),access_role_ids:t.access_role_ids||[],ping_role_ids:t.ping_role_ids||[]}))};try{const b=await api(`/api/guilds/${guildId()}/ticket-center/panels/${editingId}`,{method:"PATCH",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify(payload)});toast35(b.message||"Panel enregistré.");const keep=editingId;data=null;await load(guildId(),true);if(data?.panels?.some(p=>String(p.id)===String(keep)))openEditor(keep)}catch(e){toast35(e.message,true)}}
async function deletePanel(){const p=data?.panels?.find(x=>String(x.id)===String(editingId));if(!p||!confirm(`Supprimer le panel « ${p.name} » ? Les tickets déjà ouverts ne seront pas supprimés.`))return;try{const b=await api(`/api/guilds/${guildId()}/ticket-center/panels/${editingId}`,{method:"DELETE",headers:{"X-CSRF-Token":csrf()}});toast35(b.message||"Panel supprimé.");editingId=null;data=null;await load(guildId(),true)}catch(e){toast35(e.message,true)}}
let last="";const tick=()=>{const id=guildId(),key=`${id}:${active()?"tickets":"other"}`;if(!id||!active()){$("sentrixTicketCenterV35")?.remove();last=key;return}if(key!==last||loadedGuild!==id||!data){last=key;data=null;load(id,true);return}if(!$("sentrixTicketCenterV35"))render()};setInterval(tick,650);window.addEventListener("pageshow",tick);setTimeout(tick,150);
})();
</script>
"""

def _inject(html: str) -> str:
    if 'id="sentrix-ticket-center-v35-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    return html

def _safe_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:80]

def _safe_text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]

def _safe_url(value: object) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) > 500:
        raise ValueError("L'URL de l'image est trop longue.")
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Les images doivent utiliser une URL HTTPS valide.")
    return raw

def _parse_color(value: object) -> int | None:
    raw = str(value or "").strip().lstrip("#")
    if not raw:
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raise ValueError("La couleur doit être un code hexadécimal sur 6 caractères.")
    return int(raw, 16)

def _role_ids(guild: discord.Guild, values) -> list[int]:
    result: list[int] = []
    for value in values or []:
        try:
            role_id = int(value)
        except (TypeError, ValueError):
            raise ValueError("Un rôle sélectionné est invalide.")
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed:
            raise ValueError("Un rôle sélectionné n'existe plus ou ne peut pas être utilisé.")
        if role_id not in result:
            result.append(role_id)
    if len(result) > 25:
        raise ValueError("Vous pouvez sélectionner au maximum 25 rôles.")
    return result

def _role_snapshot(guild: discord.Guild) -> list[dict]:
    roles = [
        {"id": str(role.id), "name": role.name, "position": role.position}
        for role in guild.roles
        if not role.is_default() and not role.managed
    ]
    roles.sort(key=lambda item: (-item["position"], item["name"].casefold()))
    return roles

def _channel_snapshot(guild, channel_ids: set[int]) -> dict[str, dict]:
    result = {}
    for channel_id in channel_ids:
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if channel is not None:
            result[str(channel_id)] = {"id": str(channel_id), "name": channel.name}
    return result

async def _sync_panel_message(bot, guild: discord.Guild, panel_id: int) -> str:
    cog = bot.get_cog("Tickets")
    if cog is None:
        return "runtime_unavailable"
    panel = await cog.get_panel(panel_id)
    if not panel or not panel["channel_id"] or not panel["message_id"]:
        return "not_sent"
    channel = guild.get_channel(int(panel["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return "missing"
    try:
        message = await channel.fetch_message(int(panel["message_id"]))
    except (discord.NotFound, discord.Forbidden):
        return "missing"
    except discord.HTTPException:
        return "unavailable"
    types = await cog.get_panel_types(panel_id)
    try:
        from cogs.tickets import TicketPanelView
        view = TicketPanelView(panel, types) if types else None
        await message.edit(embed=cog.build_panel_embed(panel), view=view)
        return "updated"
    except discord.HTTPException:
        logger.exception("Impossible de synchroniser le panel #%s.", panel_id)
        return "unavailable"

async def _delete_panel_message(bot, guild: discord.Guild, panel) -> None:
    if not panel["channel_id"] or not panel["message_id"]:
        return
    channel = guild.get_channel(int(panel["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(int(panel["message_id"]))
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass

def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    async def get_ticket_center(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        bot = request.app["bot"]
        db = bot.db
        from cogs.ticket_ping_role import get_ticket_role_rules

        stamp = now()
        metrics = {}
        queries = {
            "open": ("SELECT COUNT(*) n FROM tickets WHERE guild_id=? AND status='ouvert'", (guild_id,)),
            "unclaimed": ("SELECT COUNT(*) n FROM tickets WHERE guild_id=? AND status='ouvert' AND claimed_by IS NULL", (guild_id,)),
            "closed_7d": ("SELECT COUNT(*) n FROM tickets WHERE guild_id=? AND status='ferme' AND closed_at>=?", (guild_id, stamp - 7 * 86400)),
            "average_rating": ("SELECT AVG(rating) n FROM tickets WHERE guild_id=? AND rating IS NOT NULL", (guild_id,)),
        }
        for key, (query, params) in queries.items():
            try:
                row = await db.fetchone(query, params)
                metrics[key] = row["n"] if row and row["n"] is not None else 0
            except Exception:
                metrics[key] = 0

        panels = [dict(x) for x in await db.fetchall(
            "SELECT p.*, (SELECT COUNT(*) FROM ticket_types t WHERE t.panel_id=p.id) AS type_count "
            "FROM ticket_panels_v2 p WHERE p.guild_id=? ORDER BY p.id DESC LIMIT 50",
            (guild_id,),
        )]
        types = [dict(x) for x in await db.fetchall(
            "SELECT * FROM ticket_types WHERE guild_id=? ORDER BY panel_id, position, id LIMIT 250",
            (guild_id,),
        )]
        opened = [dict(x) for x in await db.fetchall(
            "SELECT id,channel_id,user_id,category,priority,claimed_by,created_at,last_activity_at,type_id "
            "FROM tickets WHERE guild_id=? AND status='ouvert' ORDER BY created_at DESC LIMIT 50",
            (guild_id,),
        )]
        for panel in panels:
            panel["role_rules"] = await get_ticket_role_rules(bot, guild_id, int(panel["id"]), 0)
        for item in types:
            item["role_rules"] = await get_ticket_role_rules(bot, guild_id, int(item["panel_id"]), int(item["id"]))

        channel_ids = {int(x["channel_id"]) for x in opened + panels if x.get("channel_id")}
        return web.json_response({
            "ok": True,
            "metrics": metrics,
            "panels": panels,
            "types": types,
            "open_tickets": opened,
            "channels": _channel_snapshot(guild, channel_ids),
            "roles": _role_snapshot(guild),
        })

    async def create_panel(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        try:
            payload = await request.json()
        except Exception:
            return dashboard._json_error("Requête invalide.", 400)
        name = _safe_name(payload.get("name") if isinstance(payload, dict) else "")
        if len(name) < 2:
            return dashboard._json_error("Le nom du panel doit contenir au moins 2 caractères.", 400)
        db = request.app["bot"].db
        if await db.fetchone("SELECT id FROM ticket_panels_v2 WHERE guild_id=? AND LOWER(name)=LOWER(?)", (guild_id, name)):
            return dashboard._json_error("Un panel avec ce nom existe déjà.", 409)
        cur = await db.execute(
            "INSERT INTO ticket_panels_v2 (guild_id,name,title,description,created_at) VALUES (?,?,?,?,?)",
            (guild_id, name, f"Support — {name}", "Choisissez une option ci-dessous pour ouvrir un ticket.", now()),
        )
        return web.json_response({"ok": True, "panel_id": cur.lastrowid, "message": f"Panel « {name} » créé. Vous pouvez maintenant le modifier."})

    async def toggle_panel(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"]); panel_id = int(request.match_info["panel_id"])
        except ValueError:
            return dashboard._json_error("Identifiant invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        db = request.app["bot"].db
        panel = await db.fetchone("SELECT id,name,enabled FROM ticket_panels_v2 WHERE id=? AND guild_id=?", (panel_id, guild_id))
        if not panel:
            return dashboard._json_error("Panel introuvable.", 404)
        enabled = 0 if panel["enabled"] else 1
        await db.execute("UPDATE ticket_panels_v2 SET enabled=? WHERE id=? AND guild_id=?", (enabled, panel_id, guild_id))
        return web.json_response({"ok": True, "enabled": bool(enabled), "message": f"Panel « {panel['name']} » {'activé' if enabled else 'désactivé'}."})

    async def update_panel(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"]); panel_id = int(request.match_info["panel_id"])
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
        except Exception:
            return dashboard._json_error("Requête invalide.", 400)
        if not isinstance(payload, dict):
            return dashboard._json_error("Requête invalide.", 400)

        bot = request.app["bot"]; db = bot.db
        panel = await db.fetchone("SELECT * FROM ticket_panels_v2 WHERE id=? AND guild_id=?", (panel_id, guild_id))
        if not panel:
            return dashboard._json_error("Panel introuvable.", 404)
        try:
            name = _safe_name(payload.get("name"))
            title = _safe_text(payload.get("title"), 256)
            description = _safe_text(payload.get("description"), 2000)
            if len(name) < 2 or not title:
                raise ValueError("Le nom et le titre du panel sont obligatoires.")
            color = _parse_color(payload.get("color"))
            image_url = _safe_url(payload.get("image_url"))
            thumbnail_url = _safe_url(payload.get("thumbnail_url"))
            footer = _safe_text(payload.get("footer_text"), 200) or None
            style = payload.get("style")
            if style not in {"select", "button"}:
                raise ValueError("Le style du panel est invalide.")
            maximum = int(payload.get("max_per_member", 1))
            if not 1 <= maximum <= 20:
                raise ValueError("La limite doit être comprise entre 1 et 20.")
            access_ids = _role_ids(guild, payload.get("access_role_ids"))
            ping_ids = _role_ids(guild, payload.get("ping_role_ids"))
        except (TypeError, ValueError) as exc:
            return dashboard._json_error(str(exc), 400)

        duplicate = await db.fetchone(
            "SELECT id FROM ticket_panels_v2 WHERE guild_id=? AND LOWER(name)=LOWER(?) AND id<>?",
            (guild_id, name, panel_id),
        )
        if duplicate:
            return dashboard._json_error("Un autre panel porte déjà ce nom.", 409)

        await db.execute(
            """UPDATE ticket_panels_v2 SET name=?,title=?,description=?,color=?,image_url=?,
            thumbnail_url=?,footer_text=?,style=?,max_per_member=?,enabled=? WHERE id=? AND guild_id=?""",
            (name, title, description, color, image_url, thumbnail_url, footer, style, maximum, 1 if payload.get("enabled", True) else 0, panel_id, guild_id),
        )

        from cogs.ticket_ping_role import delete_ticket_role_rules, set_ticket_role_rules
        await set_ticket_role_rules(bot, guild_id, panel_id, type_id=0, access_role_ids=access_ids, ping_role_ids=ping_ids)

        existing_rows = await db.fetchall("SELECT id FROM ticket_types WHERE panel_id=? AND guild_id=?", (panel_id, guild_id))
        existing_ids = {int(row["id"]) for row in existing_rows}
        deleted_ids = set()
        for raw in payload.get("deleted_type_ids") or []:
            try:
                type_id = int(raw)
            except (TypeError, ValueError):
                continue
            if type_id in existing_ids:
                deleted_ids.add(type_id)
        for type_id in deleted_ids:
            await db.execute("DELETE FROM ticket_form_questions WHERE ticket_type_id=?", (type_id,))
            await delete_ticket_role_rules(bot, guild_id, panel_id, type_id)
            await db.execute("DELETE FROM ticket_types WHERE id=? AND panel_id=? AND guild_id=?", (type_id, panel_id, guild_id))

        type_payloads = payload.get("types") or []
        if not isinstance(type_payloads, list) or len(type_payloads) > 25:
            return dashboard._json_error("Un panel peut contenir au maximum 25 types/boutons.", 400)

        for index, item in enumerate(type_payloads):
            if not isinstance(item, dict):
                continue
            name_t = _safe_name(item.get("name"))
            if not name_t:
                return dashboard._json_error("Chaque bouton doit avoir un nom.", 400)
            label = _safe_text(item.get("button_label"), 80)
            desc = _safe_text(item.get("description"), 150)
            emoji = _safe_text(item.get("emoji"), 100) or None
            opening = _safe_text(item.get("open_message"), 1000)
            button_style = str(item.get("button_style") or "bleu")
            if button_style not in {"bleu", "gris", "vert", "rouge"}:
                return dashboard._json_error("Une couleur de bouton est invalide.", 400)
            try:
                position = max(0, min(24, int(item.get("position", index))))
                staff_id = item.get("staff_role_id")
                staff_id = _role_ids(guild, [staff_id])[0] if staff_id else None
                access_t = _role_ids(guild, item.get("access_role_ids"))
                ping_t = _role_ids(guild, item.get("ping_role_ids"))
            except (TypeError, ValueError) as exc:
                return dashboard._json_error(str(exc), 400)

            raw_id = item.get("id")
            type_id = None
            if raw_id:
                try:
                    type_id = int(raw_id)
                except (TypeError, ValueError):
                    return dashboard._json_error("Identifiant de type invalide.", 400)
                if type_id not in existing_ids or type_id in deleted_ids:
                    return dashboard._json_error("Un type de ticket ne fait pas partie de ce panel.", 400)
                await db.execute(
                    """UPDATE ticket_types SET name=?,description=?,emoji=?,button_label=?,button_style=?,
                    staff_role_id=?,open_message=?,position=? WHERE id=? AND panel_id=? AND guild_id=?""",
                    (name_t, desc, emoji, label, button_style, staff_id, opening, position, type_id, panel_id, guild_id),
                )
            else:
                cur = await db.execute(
                    """INSERT INTO ticket_types
                    (panel_id,guild_id,name,description,emoji,button_label,button_style,staff_role_id,open_message,position)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (panel_id, guild_id, name_t, desc, emoji, label, button_style, staff_id, opening, position),
                )
                type_id = int(cur.lastrowid)

            if item.get("inherit_roles", True):
                await delete_ticket_role_rules(bot, guild_id, panel_id, type_id)
            else:
                await set_ticket_role_rules(bot, guild_id, panel_id, type_id=type_id, access_role_ids=access_t, ping_role_ids=ping_t)

        sync_state = await _sync_panel_message(bot, guild, panel_id)
        suffix = {
            "updated": " Le message Discord existant a aussi été mis à jour.",
            "not_sent": " Le panel n'a pas encore été envoyé sur Discord.",
            "missing": " Le message Discord enregistré n'existe plus ; renvoyez le panel.",
            "runtime_unavailable": " La configuration est sauvegardée ; le moteur Tickets termine son démarrage.",
            "unavailable": " La configuration est sauvegardée, mais Discord n'a pas pu mettre le message à jour.",
        }.get(sync_state, "")
        return web.json_response({"ok": True, "sync": sync_state, "message": "Panel enregistré." + suffix})

    async def delete_panel(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"]); panel_id = int(request.match_info["panel_id"])
        except ValueError:
            return dashboard._json_error("Identifiant invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        bot = request.app["bot"]; db = bot.db
        panel = await db.fetchone("SELECT * FROM ticket_panels_v2 WHERE id=? AND guild_id=?", (panel_id, guild_id))
        if not panel:
            return dashboard._json_error("Panel introuvable.", 404)
        type_rows = await db.fetchall("SELECT id FROM ticket_types WHERE panel_id=? AND guild_id=?", (panel_id, guild_id))
        from cogs.ticket_ping_role import delete_ticket_role_rules
        for row in type_rows:
            await db.execute("DELETE FROM ticket_form_questions WHERE ticket_type_id=?", (int(row["id"]),))
        await delete_ticket_role_rules(bot, guild_id, panel_id)
        await db.execute("DELETE FROM ticket_types WHERE panel_id=? AND guild_id=?", (panel_id, guild_id))
        await _delete_panel_message(bot, guild, panel)
        await db.execute("DELETE FROM ticket_panels_v2 WHERE id=? AND guild_id=?", (panel_id, guild_id))
        return web.json_response({"ok": True, "message": f"Panel « {panel['name']} » supprimé. Les tickets déjà ouverts restent intacts."})

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/ticket-center", get_ticket_center)
        app.router.add_post("/api/guilds/{guild_id}/ticket-center/panels", create_panel)
        app.router.add_post("/api/guilds/{guild_id}/ticket-center/panels/{panel_id}/toggle", toggle_panel)
        app.router.add_patch("/api/guilds/{guild_id}/ticket-center/panels/{panel_id}", update_panel)
        app.router.add_delete("/api/guilds/{guild_id}/ticket-center/panels/{panel_id}", delete_panel)
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Dashboard V35 : éditeur compact et sélection multiple de rôles installés.")

__all__ = ["install"]
