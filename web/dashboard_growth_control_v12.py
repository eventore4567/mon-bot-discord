"""SentriX Dashboard Growth Control V12.

Adds real, data-backed administration surfaces on top of the unified V2 dashboard:
statistics, invitations, configurable automatic reactions, automation overview, staff
activity, audit/history, backups, maintenance, and safe webhook inventory.

The module is late-bound and idempotent. It does not replace the unified dashboard and it
keeps Discord OAuth/admin/CSRF checks as the authority for every write route.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard-growth-control-v12")

CSS_MARKER = "sentrix-growth-v12-css"
JS_MARKER = "sentrix-growth-v12-js"

CSS = r'''
<style id="sentrix-growth-v12-css">
.sx12-page{display:grid;gap:14px}.sx12-hero{border:1px solid var(--line);background:linear-gradient(135deg,#151b23,#10151b);border-radius:14px;padding:18px;display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.sx12-hero h1{margin:0;font-size:27px;letter-spacing:-.035em}.sx12-hero p{margin:5px 0 0;color:var(--muted);max-width:760px}.sx12-badges{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.sx12-badge{border:1px solid #354353;background:#141b23;color:#b9c5d2;border-radius:999px;padding:5px 8px;font-size:9px;font-weight:900;white-space:nowrap}.sx12-badge.ok{border-color:#2f654d;background:#12271e;color:#8fe4b8}.sx12-badge.blue{border-color:#31618c;background:#12263a;color:#acd6ff}.sx12-badge.warn{border-color:#705c37;background:#302713;color:#f0cc82}.sx12-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.sx12-kpi{border:1px solid var(--line);background:var(--panel);border-radius:11px;padding:13px}.sx12-kpi small{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;font-weight:900;letter-spacing:.05em}.sx12-kpi strong{display:block;font-size:23px;margin-top:3px}.sx12-kpi span{display:block;color:#748193;font-size:10px;margin-top:2px}.sx12-grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:12px}.sx12-card{grid-column:span 6;border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:15px;min-width:0}.sx12-card.third{grid-column:span 4}.sx12-card.full{grid-column:1/-1}.sx12-card h2,.sx12-card h3{margin:0;letter-spacing:-.02em}.sx12-card h2{font-size:17px}.sx12-card h3{font-size:14px}.sx12-card>p{color:var(--muted);margin:5px 0 12px;font-size:11px}.sx12-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.sx12-field.full{grid-column:1/-1}.sx12-field label{display:block;color:#c8d0d9;font-size:10px;font-weight:850;margin-bottom:5px}.sx12-field input,.sx12-field select,.sx12-field textarea{width:100%;border:1px solid var(--line2);background:#10151b;color:var(--text);border-radius:8px;padding:9px 10px;outline:0}.sx12-field textarea{min-height:92px;resize:vertical}.sx12-field small{display:block;color:#748193;font-size:9px;margin-top:4px}.sx12-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.sx12-list{display:grid;gap:8px}.sx12-item{border:1px solid var(--line);background:#11171e;border-radius:9px;padding:10px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center}.sx12-item b{display:block;font-size:11px}.sx12-item small{display:block;color:var(--muted);font-size:9px;margin-top:2px}.sx12-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.sx12-table-wrap{overflow:auto}.sx12-table{width:100%;border-collapse:collapse}.sx12-table th,.sx12-table td{text-align:left;padding:9px;border-bottom:1px solid var(--line);font-size:10px;vertical-align:middle}.sx12-table th{color:#8996a6;text-transform:uppercase;font-size:8px;letter-spacing:.05em}.sx12-empty{border:1px dashed #34404d;border-radius:10px;padding:18px;color:var(--muted);text-align:center;font-size:11px}.sx12-emoji-box{min-height:74px;border:1px solid var(--line2);border-radius:9px;background:#10151b;padding:9px;display:flex;align-items:flex-start;align-content:flex-start;gap:6px;flex-wrap:wrap}.sx12-emoji-chip{border:1px solid #3c4b5c;background:#18212b;border-radius:8px;padding:5px 7px;font-size:18px;display:inline-flex;align-items:center;gap:5px}.sx12-emoji-chip button{border:0;background:transparent;color:#8090a1;cursor:pointer;font-size:12px;padding:0}.sx12-preview{border:1px solid #2c3947;background:#0e141b;border-radius:10px;padding:12px}.sx12-preview-msg{display:flex;gap:9px}.sx12-preview-avatar{width:32px;height:32px;border-radius:50%;background:#293747;display:grid;place-items:center;font-weight:900}.sx12-preview-copy b{font-size:11px}.sx12-preview-copy p{margin:3px 0 8px;color:#c0cad5;font-size:11px}.sx12-reactions{display:flex;gap:5px;flex-wrap:wrap}.sx12-reaction{border:1px solid #3c4c60;background:#17202b;border-radius:7px;padding:3px 6px;font-size:14px}.sx12-timeline{display:grid;gap:0}.sx12-event{position:relative;padding:0 0 16px 23px;border-left:1px solid #33404e;margin-left:6px}.sx12-event:before{content:"";position:absolute;left:-4px;top:2px;width:7px;height:7px;border-radius:50%;background:#4da3ff}.sx12-event:last-child{border-left-color:transparent}.sx12-event b{font-size:11px}.sx12-event small{display:block;color:var(--muted);font-size:9px;margin-top:3px}.sx12-switch{appearance:none;width:38px;height:22px;border-radius:999px;background:#343d48;border:1px solid #44505d;position:relative;cursor:pointer}.sx12-switch:before{content:"";position:absolute;width:16px;height:16px;border-radius:50%;background:#c4ccd5;left:2px;top:2px;transition:.15s}.sx12-switch:checked{background:#245e91;border-color:#357ebd}.sx12-switch:checked:before{left:18px;background:white}.sx12-nav-new .nav-icon{border-color:#38587a;color:#9bcfff}.sx12-json{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;min-height:210px!important;font-size:10px}.sx12-loading{padding:28px;text-align:center;color:var(--muted)}
@media(max-width:1000px){.sx12-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.sx12-card,.sx12-card.third{grid-column:1/-1}}
@media(max-width:650px){.sx12-kpis{grid-template-columns:1fr}.sx12-hero{display:block}.sx12-badges{justify-content:flex-start;margin-top:12px}.sx12-fields{grid-template-columns:1fr}.sx12-field.full{grid-column:auto}}
</style>
'''

JS = r'''
<script id="sentrix-growth-v12-js">
(() => {
"use strict";
if(window.__sentrixGrowthV12)return;window.__sentrixGrowthV12=true;
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const st=()=>window.state||window.__sentrixUnifiedRuntimeV10?.state||null;
const gid=()=>String(st()?.guildId||"");
const gd=()=>st()?.guildData||{};
const csrf=()=>String(st()?.csrf||"");
const fmt=n=>Number(n||0).toLocaleString("fr-FR");
const date=v=>{const n=Number(v||0);if(!n)return "—";return new Date(n>1e12?n:n*1000).toLocaleString("fr-FR")};
async function api(url,opt={}){const h={...(opt.headers||{})};if(opt.method&&opt.method!=="GET")h["X-CSRF-Token"]=csrf();if(opt.body&&!h["Content-Type"])h["Content-Type"]="application/json";const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...opt,headers:h});let d={};try{d=await r.json()}catch(_){}if(!r.ok)throw new Error(d.error||`Erreur HTTP ${r.status}`);return d}
function toast(msg,bad=false){if(typeof window.toast==="function")return window.toast(msg,bad);console[bad?"error":"log"](msg)}
function content(){return $("content")||document.querySelector(".workspace")}
const TABS={
 stats:{group:"Général",label:"Statistiques",icon:"ST",desc:"Activité et état réel du serveur."},
 invites:{group:"Communauté",label:"Invitations",icon:"IN",desc:"Invitations Discord actives et utilisation."},
 autoreact:{group:"Communauté",label:"Réactions automatiques",icon:"RA",desc:"Réactions choisies automatiquement sur les nouveaux messages."},
 automations:{group:"Outils",label:"Automatisations",icon:"AU",desc:"Vue centrale des règles automatiques SentriX."},
 staffactivity:{group:"Administration",label:"Activité staff",icon:"AS",desc:"Activité récente de l’équipe."},
 audit:{group:"Administration",label:"Historique & audit",icon:"HA",desc:"Versions de configuration et restauration."},
 backups:{group:"Administration",label:"Sauvegardes",icon:"SV",desc:"Exporter, importer et restaurer la configuration."},
 maintenance:{group:"Administration",label:"Maintenance",icon:"MT",desc:"Maintenance serveur et politiques de commandes."},
 integrations:{group:"Administration",label:"Webhooks & intégrations",icon:"WI",desc:"Inventaire sûr des webhooks Discord."}
};
function navRoot(){return document.querySelector(".nav")}
function groupNode(name){const nav=navRoot();if(!nav)return null;return [...nav.querySelectorAll(".nav-group")].find(x=>x.textContent.trim().toLowerCase()===name.toLowerCase())}
function ensureNav(){const nav=navRoot();if(!nav)return;for(const [key,t] of Object.entries(TABS)){if(nav.querySelector(`[data-sx12-tab="${key}"]`))continue;const g=groupNode(t.group);if(!g)continue;const btn=document.createElement("button");btn.type="button";btn.className="sx12-nav-new";btn.dataset.sx12Tab=key;btn.innerHTML=`<span class="nav-icon">${t.icon}</span><span>${esc(t.label)}</span>`;let cursor=g.nextElementSibling,last=g;while(cursor&&!cursor.classList.contains("nav-group")){last=cursor;cursor=cursor.nextElementSibling}last.after(btn)}syncActive()}
function syncActive(){const cur=st()?.tab||new URL(location.href).searchParams.get("tab")||"";document.querySelectorAll("[data-sx12-tab]").forEach(b=>b.classList.toggle("active",b.dataset.sx12Tab===cur))}
function setTab(tab){const s=st();if(s)s.tab=tab;const u=new URL(location.href);u.searchParams.set("tab",tab);if(gid())u.searchParams.set("guild",gid());history.replaceState({},"",u);document.querySelectorAll(".nav button").forEach(x=>x.classList.remove("active"));syncActive();render(tab)}
function channels(){return (gd().channels||[]).filter(c=>String(c.type||"").toLowerCase()!=="category")}
function channelOptions(selected=""){return `<option value="">Choisir un salon</option>`+channels().map(c=>`<option value="${esc(c.id)}" ${String(c.id)===String(selected)?"selected":""}># ${esc(c.name)}</option>`).join("")}
function hero(title,desc,badges=[]){return `<div class="sx12-hero"><div><h1>${esc(title)}</h1><p>${esc(desc)}</p></div><div class="sx12-badges">${badges.map(x=>`<span class="sx12-badge ${x[1]||""}">${esc(x[0])}</span>`).join("")}</div></div>`}
function kpi(label,value,note=""){return `<div class="sx12-kpi"><small>${esc(label)}</small><strong>${esc(value)}</strong><span>${esc(note)}</span></div>`}
function loading(title){const c=content();if(c)c.innerHTML=`<div class="sx12-page">${hero(title,TABS[st()?.tab]?.desc||"")}<div class="sx12-loading">Chargement des données réelles…</div></div>`}
async function ops(){return api(`/api/guilds/${encodeURIComponent(gid())}/ops/overview`)}

async function renderStats(){loading("Statistiques");try{const [o,x]=await Promise.all([ops(),api(`/api/guilds/${gid()}/growth/stats`)]);const c=content();c.innerHTML=`<div class="sx12-page">${hero("Statistiques","Vue synthétique de l’activité et de la santé du serveur.",[[x.discord_ready?"Discord en ligne":"Discord indisponible",x.discord_ready?"ok":"warn"],[`${x.latency_ms??"—"} ms","blue"]])}<div class="sx12-kpis">${kpi("Membres",fmt(x.members),"membres du serveur")}${kpi("Salons",fmt(x.channels),`${fmt(x.text_channels)} texte · ${fmt(x.voice_channels)} vocal`)}${kpi("Rôles",fmt(x.roles),"rôles Discord")}${kpi("Actions staff 24 h",fmt(x.staff_actions_24h),"commandes enregistrées")}</div><div class="sx12-grid"><section class="sx12-card"><h2>Santé SentriX</h2><p>État calculé depuis le bot actuellement connecté.</p><div class="sx12-list"><div class="sx12-item"><div><b>Discord</b><small>${x.discord_ready?"Gateway connecté":"Gateway non prêt"}</small></div><span class="sx12-badge ${x.discord_ready?"ok":"warn"}">${x.discord_ready?"OK":"À vérifier"}</span></div><div class="sx12-item"><div><b>Diagnostic</b><small>${fmt((o.diagnostics||[]).length)} point(s) détecté(s)</small></div><span class="sx12-badge ${(o.diagnostics||[]).length?"warn":"ok"}">${(o.diagnostics||[]).length?"Attention":"Sain"}</span></div></div></section><section class="sx12-card"><h2>Structure Discord</h2><p>Inventaire en temps réel du serveur.</p><div class="sx12-list"><div class="sx12-item"><div><b>Salons texte</b><small>${fmt(x.text_channels)}</small></div></div><div class="sx12-item"><div><b>Salons vocaux</b><small>${fmt(x.voice_channels)}</small></div></div><div class="sx12-item"><div><b>Catégories</b><small>${fmt(x.categories)}</small></div></div></div></section></div></div>`}catch(e){fail("Statistiques",e)}}
async function renderInvites(){loading("Invitations");try{const d=await api(`/api/guilds/${gid()}/growth/invitations`);const c=content();c.innerHTML=`<div class="sx12-page">${hero("Invitations","Invitations Discord réellement visibles par SentriX.",[[`${fmt(d.items.length)} liens","blue"],[`${fmt(d.total_uses)} utilisations`,"ok"]])}<section class="sx12-card full"><div class="sx12-table-wrap"><table class="sx12-table"><thead><tr><th>Code</th><th>Salon</th><th>Créateur</th><th>Utilisations</th><th>Limite</th><th>Expire</th></tr></thead><tbody>${d.items.length?d.items.map(i=>`<tr><td><b>${esc(i.code)}</b></td><td># ${esc(i.channel_name||"—")}</td><td>${esc(i.inviter_name||"—")}</td><td>${fmt(i.uses)}</td><td>${i.max_uses?fmt(i.max_uses):"∞"}</td><td>${i.max_age?`${fmt(Math.round(i.max_age/3600))} h`:"Jamais"}</td></tr>`).join(""):'<tr><td colspan="6">Aucune invitation accessible, ou permission Gérer le serveur manquante.</td></tr>'}</tbody></table></div></section></div>`}catch(e){fail("Invitations",e)}}
let emojiDraft=[];
function readEmojiInput(){const raw=$("sx12EmojiInput")?.value.trim();if(!raw)return;for(const token of raw.split(/[\s,]+/).filter(Boolean)){if(emojiDraft.length>=8)break;if(!emojiDraft.includes(token))emojiDraft.push(token)}$("sx12EmojiInput").value="";drawEmojiDraft()}
function drawEmojiDraft(){const box=$("sx12EmojiBox");if(box)box.innerHTML=emojiDraft.length?emojiDraft.map((e,i)=>`<span class="sx12-emoji-chip"><span>${esc(e)}</span><button data-rm-emoji="${i}" title="Retirer">×</button></span>`).join(""):'<small style="color:var(--muted)">Ajoute jusqu’à 8 emojis.</small>';const p=$("sx12PreviewReactions");if(p)p.innerHTML=emojiDraft.map(e=>`<span class="sx12-reaction">${esc(e)} 1</span>`).join("")}
async function renderAutoReact(){loading("Réactions automatiques");try{const d=await api(`/api/guilds/${gid()}/automation/reactions`);const c=content();c.innerHTML=`<div class="sx12-page">${hero("Réactions automatiques","Choisis toi-même les emojis que SentriX ajoutera aux nouveaux messages.",[[`${fmt(d.items.length)} règle(s)","blue"],["8 emojis max / règle","ok"]])}<div class="sx12-grid"><section class="sx12-card"><h2>Nouvelle règle</h2><p>Unicode ou emoji personnalisé du serveur au format Discord.</p><div class="sx12-fields"><div class="sx12-field full"><label>Salon</label><select id="sx12ReactChannel">${channelOptions()}</select></div><div class="sx12-field"><label>Mode</label><select id="sx12ReactMode"><option value="all">Tous les messages</option><option value="keyword">Mot-clé</option></select></div><div class="sx12-field"><label>Mot-clé (optionnel)</label><input id="sx12ReactKeyword" maxlength="80" placeholder="ex. gg"></div><div class="sx12-field full"><label>Emojis choisis</label><div class="sx12-row"><input id="sx12EmojiInput" style="flex:1;min-width:160px" placeholder="❤️ 🔥 <:custom:123…>"><button class="btn" id="sx12AddEmoji">Ajouter</button></div><small>Tu peux coller plusieurs emojis séparés par des espaces.</small><div id="sx12EmojiBox" class="sx12-emoji-box" style="margin-top:7px"></div></div><div class="sx12-field full"><label><input type="checkbox" id="sx12IgnoreBots" checked> Ignorer les messages des bots</label></div></div><div class="sx12-row" style="margin-top:12px"><button class="btn primary" id="sx12SaveReaction">Créer la règle</button></div></section><section class="sx12-card"><h2>Aperçu</h2><p>Exemple du rendu sous un message Discord.</p><div class="sx12-preview"><div class="sx12-preview-msg"><div class="sx12-preview-avatar">S</div><div class="sx12-preview-copy"><b>Membre</b><p>Voici un nouveau message dans le salon.</p><div class="sx12-reactions" id="sx12PreviewReactions"></div></div></div></div><h3 style="margin-top:16px">Règles actives</h3><div class="sx12-list" style="margin-top:8px">${d.items.length?d.items.map(r=>`<div class="sx12-item"><div><b># ${esc(r.channel_name||r.channel_id)} · ${r.mode==="keyword"?`mot-clé « ${esc(r.keyword)} »`:"tous les messages"}</b><small>${r.emojis.map(esc).join("  ")} · ${r.ignore_bots?"bots ignorés":"bots inclus"}</small></div><div class="sx12-actions"><label title="Activer/désactiver"><input class="sx12-switch" type="checkbox" data-toggle-reaction="${r.id}" ${r.enabled?"checked":""}></label><button class="btn danger" data-delete-reaction="${r.id}">Supprimer</button></div></div>`).join(""):'<div class="sx12-empty">Aucune réaction automatique configurée.</div>'}</div></section></div></div>`;emojiDraft=[];drawEmojiDraft();wireAutoReact()}catch(e){fail("Réactions automatiques",e)}}
function wireAutoReact(){$("sx12AddEmoji")?.addEventListener("click",readEmojiInput);$("sx12EmojiInput")?.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();readEmojiInput()}});$("sx12EmojiBox")?.addEventListener("click",e=>{const b=e.target.closest("[data-rm-emoji]");if(!b)return;emojiDraft.splice(Number(b.dataset.rmEmoji),1);drawEmojiDraft()});$("sx12SaveReaction")?.addEventListener("click",async()=>{readEmojiInput();const channel_id=$("sx12ReactChannel").value;if(!channel_id)return toast("Choisis un salon.",true);if(!emojiDraft.length)return toast("Choisis au moins un emoji.",true);try{await api(`/api/guilds/${gid()}/automation/reactions`,{method:"POST",body:JSON.stringify({action:"create",channel_id,emojis:emojiDraft,mode:$("sx12ReactMode").value,keyword:$("sx12ReactKeyword").value.trim(),ignore_bots:$("sx12IgnoreBots").checked})});toast("Règle créée.");renderAutoReact()}catch(e){toast(e.message,true)}});document.querySelectorAll("[data-toggle-reaction]").forEach(el=>el.addEventListener("change",async()=>{try{await api(`/api/guilds/${gid()}/automation/reactions`,{method:"POST",body:JSON.stringify({action:"toggle",id:Number(el.dataset.toggleReaction),enabled:el.checked})});toast("Règle mise à jour.")}catch(e){el.checked=!el.checked;toast(e.message,true)}}));document.querySelectorAll("[data-delete-reaction]").forEach(el=>el.addEventListener("click",async()=>{try{await api(`/api/guilds/${gid()}/automation/reactions`,{method:"POST",body:JSON.stringify({action:"delete",id:Number(el.dataset.deleteReaction)})});renderAutoReact()}catch(e){toast(e.message,true)}}))}
async function renderAutomations(){loading("Automatisations");try{const [o,r]=await Promise.all([ops(),api(`/api/guilds/${gid()}/automation/reactions`)]);const policies=o.policies||[];const c=content();c.innerHTML=`<div class="sx12-page">${hero("Automatisations","Toutes les règles automatiques importantes réunies au même endroit.",[[`${fmt(r.items.filter(x=>x.enabled).length)} réactions actives","blue"],[`${fmt(policies.length)} politique(s)",""],[o.maintenance?.enabled?"Maintenance active":"Production normale",o.maintenance?.enabled?"warn":"ok"]])}<div class="sx12-grid"><section class="sx12-card"><h2>Réactions automatiques</h2><p>Réactions configurées par salon ou mot-clé.</p><div class="sx12-list">${r.items.slice(0,5).map(x=>`<div class="sx12-item"><div><b># ${esc(x.channel_name||x.channel_id)}</b><small>${x.emojis.map(esc).join(" ")}</small></div><span class="sx12-badge ${x.enabled?"ok":""}">${x.enabled?"Active":"Pause"}</span></div>`).join("")||'<div class="sx12-empty">Aucune règle.</div>'}</div><div class="sx12-row" style="margin-top:10px"><button class="btn" data-sx12-go="autoreact">Configurer</button></div></section><section class="sx12-card"><h2>Politiques de commandes</h2><p>Restrictions déjà appliquées par le moteur Ops SentriX.</p><div class="sx12-list">${policies.slice(0,5).map(p=>`<div class="sx12-item"><div><b>${esc(p.command_name)}</b><small>${p.channel_id?`salon ${esc(p.channel_id)}`:"tous les salons"}</small></div><span class="sx12-badge ${p.enabled?"ok":"warn"}">${p.enabled?"Autorisé":"Bloqué"}</span></div>`).join("")||'<div class="sx12-empty">Aucune politique personnalisée.</div>'}</div></section></div></div>`;wireGo()}catch(e){fail("Automatisations",e)}}
async function renderStaff(){loading("Activité staff");try{const o=await ops(),staff=o.staff||[];const total=staff.reduce((a,x)=>a+Number(x.actions||0),0);const c=content();c.innerHTML=`<div class="sx12-page">${hero("Activité staff","Activité enregistrée par SentriX sur les dernières 24 heures.",[[`${fmt(total)} actions","blue"],[`${fmt(staff.length)} membre(s) actif(s)","ok"]])}<section class="sx12-card full"><div class="sx12-table-wrap"><table class="sx12-table"><thead><tr><th>#</th><th>Utilisateur</th><th>Actions 24 h</th><th>Part</th></tr></thead><tbody>${staff.length?staff.map((s,i)=>`<tr><td>${i+1}</td><td><b>${esc(s.username||s.user_id)}</b></td><td>${fmt(s.actions)}</td><td>${total?Math.round(Number(s.actions||0)/total*100):0}%</td></tr>`).join(""):'<tr><td colspan="4">Aucune activité staff enregistrée.</td></tr>'}</tbody></table></div></section></div>`}catch(e){fail("Activité staff",e)}}
async function renderAudit(){loading("Historique & audit");try{const o=await ops(),h=o.history||[];const c=content();c.innerHTML=`<div class="sx12-page">${hero("Historique & audit","Chaque version enregistrée peut être inspectée et restaurée.",[[`${fmt(h.length)} version(s)","blue"],["Rollback sécurisé","ok"]])}<section class="sx12-card full"><div class="sx12-timeline">${h.length?h.map(x=>`<div class="sx12-event"><b>${esc((x.changed_keys||[]).join(", ")||"Configuration")}</b><small>${date(x.created_at)} · ${esc(x.username||x.user_id||"utilisateur")}</small><div class="sx12-row" style="margin-top:7px"><button class="btn" data-sx12-rollback="${x.id}">Restaurer cette version</button></div></div>`).join(""):'<div class="sx12-empty">Aucun historique enregistré pour l’instant.</div>'}</div></section></div>`;document.querySelectorAll("[data-sx12-rollback]").forEach(b=>b.addEventListener("click",async()=>{if(!confirm("Restaurer cette version de configuration ?"))return;try{await api(`/api/guilds/${gid()}/ops/history/${b.dataset.sx12Rollback}/rollback`,{method:"POST",body:"{}"});toast("Configuration restaurée.");await window.refreshAll?.();renderAudit()}catch(e){toast(e.message,true)}}))}catch(e){fail("Historique & audit",e)}}
async function renderBackups(){loading("Sauvegardes");try{const o=await ops(),h=o.history||[];const c=content();c.innerHTML=`<div class="sx12-page">${hero("Sauvegardes","Export JSON complet, import validé et accès aux versions automatiques.",[[`${fmt(h.length)} version(s) récentes","blue"],["Validation avant import","ok"]])}<div class="sx12-grid"><section class="sx12-card"><h2>Exporter</h2><p>Récupère la configuration actuelle sans modifier le serveur.</p><button class="btn primary" id="sx12Export">Générer l’export JSON</button></section><section class="sx12-card"><h2>Importer</h2><p>L’import passe par les validateurs existants SentriX.</p><button class="btn" id="sx12Import">Importer le JSON ci-dessous</button></section><section class="sx12-card full"><div class="sx12-field"><label>Configuration JSON</label><textarea class="sx12-json" id="sx12BackupJson" placeholder="L’export apparaîtra ici, ou colle une sauvegarde à importer."></textarea></div></section></div></div>`;$("sx12Export")?.addEventListener("click",async()=>{try{const d=await api(`/api/guilds/${gid()}/ops/export`);$("sx12BackupJson").value=JSON.stringify(d.config,null,2);toast("Export généré.")}catch(e){toast(e.message,true)}});$("sx12Import")?.addEventListener("click",async()=>{let cfg;try{cfg=JSON.parse($("sx12BackupJson").value)}catch{return toast("JSON invalide.",true)}if(!confirm("Importer cette configuration sur le serveur ?"))return;try{await api(`/api/guilds/${gid()}/ops/import`,{method:"POST",body:JSON.stringify(cfg)});toast("Configuration importée.");await window.refreshAll?.()}catch(e){toast(e.message,true)}})}catch(e){fail("Sauvegardes",e)}}
async function renderMaintenance(){loading("Maintenance");try{const o=await ops(),m=o.maintenance||{},p=o.policies||[];const c=content();c.innerHTML=`<div class="sx12-page">${hero("Maintenance","Contrôle opérationnel sans couper le bot entier.",[[m.enabled?"Maintenance active":"Mode normal",m.enabled?"warn":"ok"],[`${fmt(p.length)} politique(s)","blue"]])}<div class="sx12-grid"><section class="sx12-card"><h2>Mode maintenance global</h2><p>Les administrateurs restent autorisés pendant la maintenance.</p><div class="sx12-field"><label>Raison</label><input id="sx12MaintenanceReason" maxlength="180" value="${esc(m.reason||"")}" placeholder="Maintenance SentriX"></div><div class="sx12-row" style="margin-top:10px"><button class="btn ${m.enabled?"danger":"primary"}" id="sx12MaintenanceToggle">${m.enabled?"Désactiver":"Activer"} la maintenance</button></div></section><section class="sx12-card"><h2>Règles de commandes</h2><p>Les politiques détaillées restent disponibles dans Diagnostic / Ops.</p><div class="sx12-list">${p.slice(0,7).map(x=>`<div class="sx12-item"><div><b>${esc(x.command_name)}</b><small>${x.channel_id?`salon ${esc(x.channel_id)}`:"global"}</small></div><span class="sx12-badge ${x.enabled?"ok":"warn"}">${x.enabled?"ON":"OFF"}</span></div>`).join("")||'<div class="sx12-empty">Aucune politique.</div>'}</div></section></div></div>`;$("sx12MaintenanceToggle")?.addEventListener("click",async()=>{try{await api(`/api/guilds/${gid()}/ops/maintenance`,{method:"POST",body:JSON.stringify({enabled:!m.enabled,reason:$("sx12MaintenanceReason").value})});renderMaintenance()}catch(e){toast(e.message,true)}})}catch(e){fail("Maintenance",e)}}
async function renderIntegrations(){loading("Webhooks & intégrations");try{const d=await api(`/api/guilds/${gid()}/growth/webhooks`);const c=content();c.innerHTML=`<div class="sx12-page">${hero("Webhooks & intégrations","Inventaire Discord sûr : aucun token ni URL de webhook n’est affiché.",[[`${fmt(d.items.length)} webhook(s)","blue"],["Secrets masqués","ok"]])}<section class="sx12-card full"><div class="sx12-list">${d.items.length?d.items.map(w=>`<div class="sx12-item"><div><b>${esc(w.name||"Webhook")}</b><small># ${esc(w.channel_name||"salon inconnu")} · ${esc(w.type||"incoming")}</small></div><span class="sx12-badge">${esc(w.id)}</span></div>`).join(""):'<div class="sx12-empty">Aucun webhook accessible.</div>'}</div></section></div>`}catch(e){fail("Webhooks & intégrations",e)}}
function fail(title,e){const c=content();if(c)c.innerHTML=`<div class="sx12-page">${hero(title,TABS[st()?.tab]?.desc||"")}<div class="sx12-empty">${esc(e?.message||"Données indisponibles")}</div></div>`}
const R={stats:renderStats,invites:renderInvites,autoreact:renderAutoReact,automations:renderAutomations,staffactivity:renderStaff,audit:renderAudit,backups:renderBackups,maintenance:renderMaintenance,integrations:renderIntegrations};
function render(tab=st()?.tab){if(!R[tab])return;syncActive();R[tab]()}
function wireGo(){document.querySelectorAll("[data-sx12-go]").forEach(b=>b.addEventListener("click",()=>setTab(b.dataset.sx12Go)))}
document.addEventListener("click",e=>{const b=e.target.closest("[data-sx12-tab]");if(!b)return;e.preventDefault();e.stopPropagation();setTab(b.dataset.sx12Tab)},true);
const obs=new MutationObserver(()=>{ensureNav();const q=new URL(location.href).searchParams.get("tab");if(R[q]&&st()?.guildId&&st()?.tab!==q){st().tab=q;render(q)}});obs.observe(document.documentElement,{childList:true,subtree:true});
let lastGuild="";setInterval(()=>{ensureNav();const s=st(),q=new URL(location.href).searchParams.get("tab");if(!s?.guildId)return;if(s.guildId!==lastGuild){lastGuild=s.guildId;if(R[s.tab]||R[q])render(R[s.tab]?s.tab:q)}},1000);
setTimeout(()=>{ensureNav();const q=new URL(location.href).searchParams.get("tab");if(R[q]&&st()?.guildId){st().tab=q;render(q)}},900);
})();
</script>
'''


def _row_dict(row: Any) -> dict:
    if not row:
        return {}
    try:
        return dict(row)
    except Exception:
        return {}


async def _ensure_tables(db) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_auto_reaction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            emojis_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            mode TEXT NOT NULL DEFAULT 'all',
            keyword TEXT NOT NULL DEFAULT '',
            ignore_bots INTEGER NOT NULL DEFAULT 1,
            created_by BIGINT,
            created_at BIGINT NOT NULL,
            updated_at BIGINT NOT NULL
        )
        """
    )
    try:
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_sentrix_auto_reaction_guild_channel ON sentrix_dashboard_auto_reaction(guild_id, channel_id)"
        )
    except Exception:
        pass


def _emoji_valid(token: str) -> bool:
    value = str(token or "").strip()
    if not value or len(value) > 100:
        return False
    if re.fullmatch(r"<a?:[A-Za-z0-9_]{2,32}:\d{5,25}>", value):
        return True
    # Unicode emoji/graphemes are deliberately permissive; Discord is the final validator.
    return not value.startswith("<") and not value.endswith(">")


async def _reaction_rows(db, guild: discord.Guild) -> list[dict]:
    await _ensure_tables(db)
    rows = await db.fetchall(
        "SELECT id,guild_id,channel_id,emojis_json,enabled,mode,keyword,ignore_bots,created_by,created_at,updated_at "
        "FROM sentrix_dashboard_auto_reaction WHERE guild_id = ? ORDER BY updated_at DESC, id DESC LIMIT 100",
        (guild.id,),
    )
    out: list[dict] = []
    for row in rows:
        item = _row_dict(row)
        try:
            emojis = json.loads(item.get("emojis_json") or "[]")
        except Exception:
            emojis = []
        channel = guild.get_channel(int(item.get("channel_id") or 0))
        out.append(
            {
                "id": int(item.get("id") or 0),
                "channel_id": str(item.get("channel_id") or ""),
                "channel_name": getattr(channel, "name", None),
                "emojis": [str(x) for x in emojis if str(x).strip()][:8],
                "enabled": bool(item.get("enabled")),
                "mode": item.get("mode") or "all",
                "keyword": item.get("keyword") or "",
                "ignore_bots": bool(item.get("ignore_bots")),
                "created_by": str(item.get("created_by") or ""),
                "created_at": int(item.get("created_at") or 0),
                "updated_at": int(item.get("updated_at") or 0),
            }
        )
    return out


def _install_listener(bot) -> None:
    if getattr(bot, "_sentrix_auto_reaction_v12", False):
        return
    bot._sentrix_auto_reaction_v12 = True
    cache: dict[tuple[int, int], tuple[float, list[dict]]] = {}

    async def rules(guild_id: int, channel_id: int) -> list[dict]:
        key = (guild_id, channel_id)
        now = time.monotonic()
        cached = cache.get(key)
        if cached and now - cached[0] < 2.5:
            return cached[1]
        try:
            await _ensure_tables(bot.db)
            rows = await bot.db.fetchall(
                "SELECT id,emojis_json,mode,keyword,ignore_bots FROM sentrix_dashboard_auto_reaction "
                "WHERE guild_id = ? AND channel_id = ? AND enabled = 1 ORDER BY id ASC LIMIT 20",
                (guild_id, channel_id),
            )
        except Exception:
            logger.exception("Unable to load automatic reaction rules.")
            return []
        values = [_row_dict(row) for row in rows]
        cache[key] = (now, values)
        return values

    async def on_message(message: discord.Message) -> None:
        if message.guild is None or message.author is None:
            return
        for rule in await rules(message.guild.id, message.channel.id):
            if bool(rule.get("ignore_bots")) and getattr(message.author, "bot", False):
                continue
            mode = str(rule.get("mode") or "all")
            keyword = str(rule.get("keyword") or "").strip().casefold()
            if mode == "keyword" and (not keyword or keyword not in str(message.content or "").casefold()):
                continue
            try:
                emojis = json.loads(rule.get("emojis_json") or "[]")
            except Exception:
                emojis = []
            for raw in emojis[:8]:
                token = str(raw).strip()
                if not token:
                    continue
                try:
                    emoji = discord.PartialEmoji.from_str(token) if token.startswith("<") else token
                    await message.add_reaction(emoji)
                except (discord.Forbidden, discord.NotFound):
                    break
                except discord.HTTPException:
                    continue
                except Exception:
                    logger.debug("Automatic reaction failed for guild=%s channel=%s", message.guild.id, message.channel.id, exc_info=True)

    bot.add_listener(on_message, "on_message")
    logger.info("Automatic reactions V12 listener installed.")


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if not html:
        return False
    if f'id="{CSS_MARKER}"' not in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if f'id="{JS_MARKER}"' not in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html

    original_build = dashboard.build_app
    if not getattr(original_build, "_sentrix_growth_v12_routes", False):
        def build_app_with_growth(bot):
            app = original_build(bot)
            from web import dashboard_ops_suite as ops

            async def require(request: web.Request):
                return await ops._require_manageable(dashboard, request)

            async def stats(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                try:
                    staff = await ops._staff_activity(bot.db, guild_id)
                except Exception:
                    staff = []
                text_channels = len(getattr(guild, "text_channels", []) or [])
                voice_channels = len(getattr(guild, "voice_channels", []) or [])
                categories = len(getattr(guild, "categories", []) or [])
                return web.json_response(
                    {
                        "ok": True,
                        "members": int(getattr(guild, "member_count", 0) or 0),
                        "channels": len(getattr(guild, "channels", []) or []),
                        "text_channels": text_channels,
                        "voice_channels": voice_channels,
                        "categories": categories,
                        "roles": max(0, len(getattr(guild, "roles", []) or []) - 1),
                        "staff_actions_24h": sum(int(x.get("actions") or 0) for x in staff),
                        "discord_ready": bool(bot.is_ready()),
                        "latency_ms": round(bot.latency * 1000) if bot.is_ready() else None,
                    }
                )

            async def invitations(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                items = []
                try:
                    invites = await guild.invites()
                except (discord.Forbidden, discord.HTTPException):
                    invites = []
                for invite in invites[:100]:
                    items.append(
                        {
                            "code": invite.code,
                            "uses": int(invite.uses or 0),
                            "max_uses": int(invite.max_uses or 0),
                            "max_age": int(invite.max_age or 0),
                            "temporary": bool(invite.temporary),
                            "channel_id": str(getattr(invite.channel, "id", "") or ""),
                            "channel_name": getattr(invite.channel, "name", None),
                            "inviter_id": str(getattr(invite.inviter, "id", "") or ""),
                            "inviter_name": str(invite.inviter) if invite.inviter else None,
                        }
                    )
                return web.json_response({"ok": True, "items": items, "total_uses": sum(x["uses"] for x in items)})

            async def webhooks(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                items = []
                try:
                    hooks = await guild.webhooks()
                except (discord.Forbidden, discord.HTTPException):
                    hooks = []
                for hook in hooks[:100]:
                    channel = guild.get_channel(int(hook.channel_id or 0)) if hook.channel_id else None
                    items.append(
                        {
                            "id": str(hook.id),
                            "name": hook.name,
                            "channel_id": str(hook.channel_id or ""),
                            "channel_name": getattr(channel, "name", None),
                            "type": str(getattr(hook.type, "name", hook.type)),
                        }
                    )
                return web.json_response({"ok": True, "items": items})

            async def reactions_get(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                return web.json_response({"ok": True, "items": await _reaction_rows(bot.db, guild)})

            async def reactions_post(request: web.Request):
                guild_id, session, guild, error = await require(request)
                if error:
                    return error
                csrf_error = ops._csrf(dashboard, request, session)
                if csrf_error:
                    return csrf_error
                try:
                    payload = await request.json()
                except Exception:
                    return dashboard._json_error("Formulaire invalide.", 400)
                action = str(payload.get("action") or "create").lower()
                await _ensure_tables(bot.db)
                user_id = int(session["user"]["id"])
                now = int(time.time())

                if action == "create":
                    try:
                        channel_id = int(payload.get("channel_id") or 0)
                    except (TypeError, ValueError):
                        channel_id = 0
                    channel = guild.get_channel(channel_id)
                    if channel is None or not hasattr(channel, "send"):
                        return dashboard._json_error("Salon texte introuvable.", 400)
                    raw_emojis = payload.get("emojis") or []
                    if not isinstance(raw_emojis, list):
                        return dashboard._json_error("Liste d'emojis invalide.", 400)
                    emojis: list[str] = []
                    for value in raw_emojis:
                        token = str(value or "").strip()
                        if token and token not in emojis:
                            if not _emoji_valid(token):
                                return dashboard._json_error(f"Emoji invalide : {token[:30]}", 400)
                            emojis.append(token)
                    emojis = emojis[:8]
                    if not emojis:
                        return dashboard._json_error("Choisis au moins un emoji.", 400)
                    mode = str(payload.get("mode") or "all").lower()
                    if mode not in {"all", "keyword"}:
                        return dashboard._json_error("Mode de réaction invalide.", 400)
                    keyword = str(payload.get("keyword") or "").strip()[:80]
                    if mode == "keyword" and not keyword:
                        return dashboard._json_error("Indique le mot-clé à détecter.", 400)
                    ignore_bots = 1 if payload.get("ignore_bots", True) else 0
                    await bot.db.execute(
                        "INSERT INTO sentrix_dashboard_auto_reaction "
                        "(guild_id,channel_id,emojis_json,enabled,mode,keyword,ignore_bots,created_by,created_at,updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (guild_id, channel_id, json.dumps(emojis, ensure_ascii=False), 1, mode, keyword, ignore_bots, user_id, now, now),
                    )
                    return web.json_response({"ok": True, "message": "Réaction automatique créée."})

                try:
                    rule_id = int(payload.get("id") or 0)
                except (TypeError, ValueError):
                    rule_id = 0
                row = await bot.db.fetchone(
                    "SELECT id FROM sentrix_dashboard_auto_reaction WHERE id = ? AND guild_id = ?",
                    (rule_id, guild_id),
                )
                if not row:
                    return dashboard._json_error("Règle introuvable.", 404)
                if action == "delete":
                    await bot.db.execute("DELETE FROM sentrix_dashboard_auto_reaction WHERE id = ? AND guild_id = ?", (rule_id, guild_id))
                    return web.json_response({"ok": True})
                if action == "toggle":
                    enabled = 1 if payload.get("enabled") else 0
                    await bot.db.execute(
                        "UPDATE sentrix_dashboard_auto_reaction SET enabled = ?, updated_at = ? WHERE id = ? AND guild_id = ?",
                        (enabled, now, rule_id, guild_id),
                    )
                    return web.json_response({"ok": True, "enabled": bool(enabled)})
                return dashboard._json_error("Action inconnue.", 400)

            app.router.add_get("/api/guilds/{guild_id}/growth/stats", stats)
            app.router.add_get("/api/guilds/{guild_id}/growth/invitations", invitations)
            app.router.add_get("/api/guilds/{guild_id}/growth/webhooks", webhooks)
            app.router.add_get("/api/guilds/{guild_id}/automation/reactions", reactions_get)
            app.router.add_post("/api/guilds/{guild_id}/automation/reactions", reactions_post)
            _install_listener(bot)
            return app

        build_app_with_growth._sentrix_growth_v12_routes = True
        dashboard.build_app = build_app_with_growth

    ok = CSS_MARKER in dashboard.INDEX_HTML and JS_MARKER in dashboard.INDEX_HTML
    logger.warning("Dashboard Growth Control V12 installed=%s: stats/invites/auto-reactions/ops/audit/backups/maintenance/webhooks.", ok)
    return ok


__all__ = ["install", "CSS_MARKER", "JS_MARKER"]
