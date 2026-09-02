"""Dashboard V53 — éditeur spécialisé des boutons de tickets.

Complète ticket_center_v35 avec un éditeur dédié par panel pour les boutons d'ouverture,
leurs textes/options avancées, les formulaires et les boutons de gestion staff.
"""
from __future__ import annotations

import re

import discord
from aiohttp import web

_INSTALLED = False

CSS = r"""
<style id="sentrix-ticket-buttons-v53-css">
.sx53-open{border-color:#51438c!important;background:#1c1830!important;color:#d8ceff!important}
.sx53-backdrop{position:fixed;inset:0;z-index:10050;display:grid;place-items:center;padding:22px;background:rgba(3,6,11,.82);backdrop-filter:blur(5px)}
.sx53-modal{width:min(980px,100%);max-height:92vh;display:flex;flex-direction:column;overflow:hidden;border:1px solid #39445c;border-radius:15px;background:#0b1019;box-shadow:0 26px 90px rgba(0,0,0,.62)}
.sx53-head{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:15px 17px;border-bottom:1px solid #252e40}.sx53-head h3{margin:0;color:#f2eff7;font-size:16px}.sx53-head p{margin:4px 0 0;color:#8994a7;font-size:10px}.sx53-close{min-height:34px;padding:0 11px;border:1px solid #354056;border-radius:9px;background:#151c28;color:#e3e0e8;font-weight:800;cursor:pointer}
.sx53-body{overflow:auto;padding:14px;display:grid;gap:11px}.sx53-section{border:1px solid #273145;border-radius:11px;background:#0f151f;overflow:visible}.sx53-section>summary{cursor:pointer;list-style:none;padding:12px 13px;color:#e7e4ed;font-size:11px;font-weight:850}.sx53-section>summary::-webkit-details-marker{display:none}.sx53-section>summary::after{content:"+";float:right;color:#8792a5;font-size:15px}.sx53-section[open]>summary::after{content:"–"}.sx53-content{padding:0 13px 13px;display:grid;gap:10px}
.sx53-note{padding:9px 10px;border:1px solid #2c3549;border-radius:9px;background:#111823;color:#97a1b4;font-size:10px;line-height:1.45}.sx53-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.sx53-field.full{grid-column:1/-1}.sx53-field label{display:block;margin-bottom:5px;color:#b9c1cf;font-size:10px;font-weight:800}.sx53-field small{display:block;margin-top:4px;color:#7b8699;font-size:9px;line-height:1.35}.sx53-field input,.sx53-field textarea,.sx53-field select{width:100%;box-sizing:border-box;border:1px solid #2d374b;border-radius:8px;background:#111824;color:#ebe8f0;padding:8px 9px;font:inherit;font-size:10px}.sx53-field textarea{min-height:75px;resize:vertical}.sx53-check{display:flex!important;align-items:center;gap:7px;margin:0!important;padding:8px 9px;border:1px solid #2d374b;border-radius:8px;background:#111824;color:#c2cad6!important;cursor:pointer}.sx53-check input{width:auto!important;margin:0}
.sx53-type-list,.sx53-staff-list{display:grid;gap:8px}.sx53-type{border:1px solid #2a3448;border-radius:10px;background:#0c121c;overflow:hidden}.sx53-type>summary{display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:pointer;list-style:none;padding:10px 11px}.sx53-type>summary::-webkit-details-marker{display:none}.sx53-type-title b{display:block;color:#e8e5ed;font-size:11px}.sx53-type-title span{display:block;margin-top:3px;color:#7d8799;font-size:9px}.sx53-preview{display:inline-flex;align-items:center;gap:5px;max-width:250px;padding:5px 9px;border-radius:7px;font-size:9px;font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sx53-blue{background:#5865f2;color:#fff}.sx53-gray{background:#4e5058;color:#fff}.sx53-green{background:#248046;color:#fff}.sx53-red{background:#da373c;color:#fff}.sx53-type-body{padding:0 11px 11px;display:grid;gap:10px}.sx53-actions{display:flex;gap:7px;flex-wrap:wrap}.sx53-btn{min-height:32px;padding:0 10px;border:1px solid #354057;border-radius:8px;background:#151c28;color:#dedbe5;font-size:9px;font-weight:800;cursor:pointer}.sx53-btn.primary{border-color:#725bd0;background:#6c55c9;color:#fff}.sx53-btn.danger{border-color:#67353e;background:#29171b;color:#efa4ad}.sx53-btn:disabled{opacity:.6;cursor:wait}
.sx53-question-list{display:grid;gap:7px}.sx53-question{padding:9px;border:1px solid #293348;border-radius:9px;background:#0f1621}.sx53-question-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}.sx53-question-head b{font-size:9px;color:#bdc5d2}.sx53-question-head button{border:1px solid #60343b;border-radius:7px;background:#25171a;color:#e8a0a8;padding:5px 7px;font-size:8px;cursor:pointer}
.sx53-staff{display:grid;grid-template-columns:auto minmax(130px,1fr) 90px 120px minmax(140px,.8fr);gap:7px;align-items:end;padding:9px;border:1px solid #293348;border-radius:9px;background:#0d141e}.sx53-staff .sx53-field label{font-size:9px}.sx53-switch{align-self:center;display:flex;align-items:center;gap:6px;color:#bdc5d2;font-size:9px}.sx53-switch input{margin:0}.sx53-staff-name{align-self:center;min-width:105px}.sx53-staff-name b{display:block;color:#e5e2ea;font-size:10px}.sx53-staff-name span{display:block;color:#768195;font-size:8px;margin-top:2px}
.sx53-footer{display:flex;justify-content:flex-end;gap:8px;padding:12px 15px;border-top:1px solid #252e40;background:#0d121b}.sx53-status{min-height:18px;color:#8f9aae;font-size:9px;align-self:center;margin-right:4px}.sx53-status.bad{color:#e89da6}.sx53-status.ok{color:#8bd0ae}
@media(max-width:780px){.sx53-backdrop{padding:7px}.sx53-modal{max-height:96vh}.sx53-grid{grid-template-columns:1fr}.sx53-field.full{grid-column:auto}.sx53-staff{grid-template-columns:1fr 1fr}.sx53-staff-name{grid-column:1/-1}.sx53-footer{flex-wrap:wrap}}
</style>
"""

JS = r"""
<script id="sentrix-ticket-buttons-v53-js">
(() => {
"use strict";
if(window.__sentrixTicketButtonsV53)return;window.__sentrixTicketButtonsV53=true;
let panelId=null,model=null,busy=false;
const E=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const gid=()=>{try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):""}catch(_){return""}};
const csrf=()=>{try{return typeof state!=="undefined"?state.csrf||"":""}catch(_){return""}};
const toast53=(m,b=false)=>{try{if(typeof toast==="function")return toast(m,b)}catch(_){}(b?console.error:console.info)(m)};
async function api(url,opt={}){const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...opt});const b=await r.json().catch(()=>({}));if(!r.ok)throw new Error(b.error||"Action impossible.");return b}
function styleClass(v){return({bleu:"sx53-blue",gris:"sx53-gray",vert:"sx53-green",rouge:"sx53-red"})[v]||"sx53-blue"}
function roleOptions(selected=""){const chosen=String(selected||"");return '<option value="">Aucun rôle imposé</option>'+((model?.roles)||[]).map(r=>`<option value="${E(r.id)}" ${chosen===String(r.id)?"selected":""}>@${E(r.name)}</option>`).join("")}
function categoryOptions(selected=""){const chosen=String(selected||"");return '<option value="">Catégorie par défaut du serveur</option>'+((model?.categories)||[]).map(c=>`<option value="${E(c.id)}" ${chosen===String(c.id)?"selected":""}>${E(c.name)}</option>`).join("")}
function styleOptions(selected){return ["bleu","gris","vert","rouge"].map(v=>`<option value="${v}" ${v===selected?"selected":""}>${({bleu:"Bleu",gris:"Gris",vert:"Vert",rouge:"Rouge"})[v]}</option>`).join("")}
function question(q,ti,qi){return `<div class="sx53-question"><div class="sx53-question-head"><b>Question ${qi+1}</b><button data-qremove="${ti}:${qi}" type="button">Supprimer</button></div><div class="sx53-grid"><div class="sx53-field"><label>Question affichée</label><input data-qf="label" maxlength="45" value="${E(q.label||"")}"></div><div class="sx53-field"><label>Placeholder</label><input data-qf="placeholder" maxlength="100" value="${E(q.placeholder||"")}"></div><div class="sx53-field"><label>Type</label><select data-qf="style"><option value="court" ${q.style!=="long"?"selected":""}>Réponse courte</option><option value="long" ${q.style==="long"?"selected":""}>Réponse longue</option></select></div><div class="sx53-field"><label>Longueur min</label><input data-qf="min_length" type="number" min="0" max="4000" value="${Number(q.min_length||0)}"></div><div class="sx53-field"><label>Longueur max</label><input data-qf="max_length" type="number" min="1" max="4000" value="${Number(q.max_length||500)}"></div><div class="sx53-field full"><label class="sx53-check"><input data-qf="required" type="checkbox" ${q.required!==false?"checked":""}> Réponse obligatoire</label></div></div></div>`}
function typeCard(t,i){const label=t.button_label||t.name||`Bouton ${i+1}`;return `<details class="sx53-type" data-type="${i}" ${i===0?"open":""}><summary><div class="sx53-type-title"><b>${E(label)}</b><span>${E(t.description||"Aucune description")}</span></div><span class="sx53-preview ${styleClass(t.button_style)}">${E(t.emoji||"")} ${E(label)}</span></summary><div class="sx53-type-body"><div class="sx53-grid"><div class="sx53-field"><label>Texte du bouton</label><input data-tf="button_label" maxlength="80" value="${E(t.button_label||"")}" placeholder="Ouvrir un ticket"></div><div class="sx53-field"><label>Nom du type</label><input data-tf="name" maxlength="80" value="${E(t.name||"Support")}"></div><div class="sx53-field"><label>Emoji</label><input data-tf="emoji" maxlength="100" value="${E(t.emoji||"")}" placeholder="🎫 ou <:nom:id>"></div><div class="sx53-field"><label>Couleur</label><select data-tf="button_style">${styleOptions(t.button_style)}</select></div><div class="sx53-field full"><label>Description du choix</label><input data-tf="description" maxlength="150" value="${E(t.description||"")}" placeholder="Ex. Besoin d'aide avec une commande"></div><div class="sx53-field full"><label>Message envoyé dans le ticket</label><textarea data-tf="open_message" maxlength="1000" placeholder="Ex. Bonjour, expliquez votre demande ici.">${E(t.open_message||"")}</textarea></div></div><details class="sx53-section"><summary>Salon, limites et permissions</summary><div class="sx53-content"><div class="sx53-grid"><div class="sx53-field"><label>Catégorie Discord</label><select data-tf="category_id">${categoryOptions(t.category_id)}</select></div><div class="sx53-field"><label>Nom du salon</label><input data-tf="name_format" maxlength="90" value="${E(t.name_format||"ticket-{pseudo}")}"><small>{pseudo}, {username}, {numero}, {number}</small></div><div class="sx53-field"><label>Tickets max / membre</label><input data-tf="max_per_member" type="number" min="1" max="20" value="${Number(t.max_per_member||1)}"></div><div class="sx53-field"><label>Fermeture auto (heures)</label><input data-tf="autoclose_hours" type="number" min="0" max="720" value="${Number(t.autoclose_hours||0)}"></div><div class="sx53-field"><label>Rôle de gestion</label><select data-tf="staff_role_id">${roleOptions(t.staff_role_id)}</select></div><div class="sx53-field"><label>Position</label><input data-tf="position" type="number" min="0" max="24" value="${Number(t.position??i)}"></div><div class="sx53-field full"><label class="sx53-check"><input data-tf="mention_staff" type="checkbox" ${t.mention_staff!==false?"checked":""}> Ping du rôle support historique si aucun ping spécifique n'est configuré</label></div></div></div></details><details class="sx53-section" ${t.use_form?"open":""}><summary>Formulaire avant ouverture (${(t.questions||[]).length}/5)</summary><div class="sx53-content"><label class="sx53-check"><input data-tf="use_form" type="checkbox" ${t.use_form?"checked":""}> Demander un formulaire avant de créer le ticket</label><div class="sx53-question-list">${(t.questions||[]).map((q,qi)=>question(q,i,qi)).join("")||'<div class="sx53-note">Aucune question.</div>'}</div><div><button class="sx53-btn" data-qadd="${i}" type="button" ${(t.questions||[]).length>=5?"disabled":""}>Ajouter une question</button></div></div></details><div class="sx53-actions"><button class="sx53-btn" data-duplicate="${i}" type="button">Dupliquer</button><button class="sx53-btn danger" data-remove="${i}" type="button">Supprimer ce bouton</button></div></div></details>`}
function staffRow(key,cfg){const names={claim:"Prendre en charge",unclaim:"Abandonner",add:"Ajouter un membre",remove:"Retirer un membre",rename:"Renommer",transfer:"Transférer",note:"Ajouter une note",bump:"Relancer",close:"Fermer"};return `<div class="sx53-staff" data-staff="${E(key)}"><div class="sx53-staff-name"><b>${E(names[key]||key)}</b><span>${E(key)}</span></div><label class="sx53-switch"><input data-sf="enabled" type="checkbox" ${cfg.enabled?"checked":""}> Actif</label><div class="sx53-field"><label>Emoji</label><input data-sf="emoji" maxlength="100" value="${E(cfg.emoji||"")}"></div><div class="sx53-field"><label>Couleur</label><select data-sf="style">${styleOptions(cfg.style||"bleu")}</select></div><div class="sx53-field"><label>Texte du bouton</label><input data-sf="label" maxlength="80" value="${E(cfg.label||"")}"></div><div class="sx53-field"><label>Rôle autorisé</label><select data-sf="role_id">${roleOptions(cfg.role_id)}</select></div></div>`}
function render(){document.getElementById("sx53Backdrop")?.remove();const el=document.createElement("div");el.className="sx53-backdrop";el.id="sx53Backdrop";el.innerHTML=`<div class="sx53-modal" role="dialog" aria-modal="true"><div class="sx53-head"><div><h3>Boutons · ${E(model.panel?.name||"Panel")}</h3><p>Textes, couleurs, formulaires, salons et actions staff.</p></div><button class="sx53-close" id="sx53Close" type="button">Fermer</button></div><div class="sx53-body"><details class="sx53-section" open><summary>Boutons d'ouverture (${model.types.length})</summary><div class="sx53-content"><div class="sx53-note">Chaque bouton peut avoir ses propres textes, catégorie, limite et formulaire.</div><div class="sx53-type-list">${model.types.map(typeCard).join("")||'<div class="sx53-note">Aucun bouton.</div>'}</div><div><button class="sx53-btn primary" id="sx53AddType" type="button">Ajouter un bouton d'ouverture</button></div></div></details><details class="sx53-section"><summary>Boutons de gestion dans les tickets</summary><div class="sx53-content"><div class="sx53-note">Vous pouvez modifier le texte, l'emoji, la couleur, l'activation et le rôle autorisé.</div><div class="sx53-staff-list">${Object.entries(model.staff_buttons||{}).map(([k,v])=>staffRow(k,v)).join("")}</div></div></details></div><div class="sx53-footer"><button class="sx53-btn" id="sx53Cancel" type="button">Annuler</button><span class="sx53-status" id="sx53Status"></span><button class="sx53-btn primary" id="sx53Save" type="button">Enregistrer les boutons</button></div></div>`;document.body.appendChild(el);bind()}
function capture(){document.querySelectorAll(".sx53-type[data-type]").forEach(card=>{const i=Number(card.dataset.type),t=model.types[i];if(!t)return;card.querySelectorAll("[data-tf]").forEach(x=>{t[x.dataset.tf]=x.type==="checkbox"?x.checked:x.value});t.questions=[];card.querySelectorAll(".sx53-question").forEach(qel=>{const q={};qel.querySelectorAll("[data-qf]").forEach(x=>{q[x.dataset.qf]=x.type==="checkbox"?x.checked:x.value});t.questions.push(q)})});document.querySelectorAll("[data-staff]").forEach(row=>{const k=row.dataset.staff,cfg=model.staff_buttons[k]||{};row.querySelectorAll("[data-sf]").forEach(x=>{cfg[x.dataset.sf]=x.type==="checkbox"?x.checked:x.value});model.staff_buttons[k]=cfg})}
function bind(){document.getElementById("sx53Close")?.addEventListener("click",close);document.getElementById("sx53Cancel")?.addEventListener("click",close);document.getElementById("sx53Backdrop")?.addEventListener("click",e=>{if(e.target.id==="sx53Backdrop")close()});document.getElementById("sx53AddType")?.addEventListener("click",()=>{capture();model.types.push({id:null,name:"Support",description:"",emoji:"🎫",button_label:"Ouvrir un ticket",button_style:"bleu",category_id:null,name_format:"ticket-{pseudo}",open_message:"",max_per_member:1,autoclose_hours:0,staff_role_id:null,mention_staff:true,use_form:false,position:model.types.length,questions:[]});render()});document.querySelectorAll("[data-remove]").forEach(b=>b.addEventListener("click",()=>{capture();const i=Number(b.dataset.remove);if(confirm("Supprimer ce bouton/type de ticket ?")){model.types.splice(i,1);render()}}));document.querySelectorAll("[data-duplicate]").forEach(b=>b.addEventListener("click",()=>{capture();const i=Number(b.dataset.duplicate),copy=JSON.parse(JSON.stringify(model.types[i]));copy.id=null;copy.name=(copy.name||"Support")+" copie";copy.button_label=(copy.button_label||copy.name)+" copie";copy.position=model.types.length;model.types.push(copy);render()}));document.querySelectorAll("[data-qadd]").forEach(b=>b.addEventListener("click",()=>{capture();const i=Number(b.dataset.qadd),qs=model.types[i].questions||(model.types[i].questions=[]);if(qs.length<5){qs.push({label:`Question ${qs.length+1}`,placeholder:"",style:"court",required:true,min_length:0,max_length:500});render()}}));document.querySelectorAll("[data-qremove]").forEach(b=>b.addEventListener("click",()=>{capture();const [ti,qi]=b.dataset.qremove.split(":").map(Number);model.types[ti].questions.splice(qi,1);render()}));document.getElementById("sx53Save")?.addEventListener("click",save)}
function close(){if(busy)return;document.getElementById("sx53Backdrop")?.remove();panelId=null;model=null}
async function save(){if(busy)return;capture();const btn=document.getElementById("sx53Save"),status=document.getElementById("sx53Status");busy=true;if(btn){btn.disabled=true;btn.textContent="Enregistrement…"}try{const body=await api(`/api/guilds/${gid()}/ticket-button-editor/${panelId}`,{method:"PATCH",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({types:model.types,staff_buttons:model.staff_buttons})});if(status){status.className="sx53-status ok";status.textContent="Enregistré"}toast53(body.message||"Boutons enregistrés.");document.getElementById("sx53Backdrop")?.remove();panelId=null;model=null;setTimeout(()=>document.getElementById("sxTicketRefresh")?.click(),50)}catch(e){if(status){status.className="sx53-status bad";status.textContent=e.message||"Erreur"}toast53(e.message||"Impossible d'enregistrer.",true)}finally{busy=false;if(btn){btn.disabled=false;btn.textContent="Enregistrer les boutons"}}}
async function open(id){if(busy)return;panelId=String(id);try{model=await api(`/api/guilds/${gid()}/ticket-button-editor/${panelId}`);render()}catch(e){panelId=null;model=null;toast53(e.message||"Impossible d'ouvrir l'éditeur des boutons.",true)}}
function enhance(){if(!gid())return;document.querySelectorAll("[data-panel-edit]").forEach(edit=>{const actions=edit.closest(".sx-ticket-actions");if(!actions||actions.querySelector(`[data-sx53="${edit.dataset.panelEdit}"]`))return;const b=document.createElement("button");b.type="button";b.className="sx53-open";b.dataset.sx53=edit.dataset.panelEdit;b.textContent="Boutons";b.addEventListener("click",()=>open(b.dataset.sx53));actions.insertBefore(b,edit)})}
new MutationObserver(enhance).observe(document.documentElement,{subtree:true,childList:true});setInterval(enhance,900);setTimeout(enhance,200);
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-ticket-buttons-v53-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", JS + "\n</body>", 1)
    return html


def _safe_text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _style(value: object) -> str:
    raw = str(value or "").strip().casefold()
    aliases = {"blurple":"bleu","primary":"bleu","blue":"bleu","bleu":"bleu","secondary":"gris","gray":"gris","grey":"gris","gris":"gris","success":"vert","green":"vert","vert":"vert","danger":"rouge","red":"rouge","rouge":"rouge"}
    if raw not in aliases:
        raise ValueError("Couleur de bouton invalide.")
    return aliases[raw]


def _role_id(guild: discord.Guild, value) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        role_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Rôle invalide.") from exc
    role = guild.get_role(role_id)
    if role is None or role.is_default() or role.managed:
        raise ValueError("Un rôle sélectionné n'existe plus ou ne peut pas être utilisé.")
    return role_id


def _category_id(guild: discord.Guild, value) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        category_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Catégorie invalide.") from exc
    if not isinstance(guild.get_channel(category_id), discord.CategoryChannel):
        raise ValueError("La catégorie sélectionnée n'existe plus.")
    return category_id


def _int(value, minimum: int, maximum: int, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} doit être un nombre entier.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} doit être compris entre {minimum} et {maximum}.")
    return number


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    async def get_editor(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"]); panel_id = int(request.match_info["panel_id"])
        except ValueError:
            return dashboard._json_error("Identifiant invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        bot=request.app["bot"]; db=bot.db
        panel=await db.fetchone("SELECT * FROM ticket_panels_v2 WHERE id=? AND guild_id=?",(panel_id,guild_id))
        if not panel:
            return dashboard._json_error("Panel introuvable.",404)
        rows=await db.fetchall("SELECT * FROM ticket_types WHERE panel_id=? AND guild_id=? ORDER BY position,id",(panel_id,guild_id))
        types=[]
        for row in rows:
            item=dict(row)
            qs=await db.fetchall("SELECT * FROM ticket_form_questions WHERE ticket_type_id=? ORDER BY position,id LIMIT 5",(int(item["id"]),))
            item["questions"]=[dict(q) for q in qs]
            item["button_style"]=_style(item.get("button_style") or "bleu")
            item["mention_staff"]=bool(item.get("mention_staff",1)); item["use_form"]=bool(item.get("use_form",0))
            types.append(item)
        from cogs import tickets
        staff=await tickets.get_button_settings(bot,guild_id)
        for cfg in staff.values(): cfg["style"]=_style(cfg.get("style") or "bleu")
        roles=[{"id":str(r.id),"name":r.name,"position":r.position} for r in guild.roles if not r.is_default() and not r.managed]
        roles.sort(key=lambda x:(-x["position"],x["name"].casefold()))
        categories=[{"id":str(c.id),"name":c.name,"position":c.position} for c in guild.categories]
        categories.sort(key=lambda x:(x["position"],x["name"].casefold()))
        return web.json_response({"ok":True,"panel":dict(panel),"types":types,"staff_buttons":staff,"roles":roles,"categories":categories})

    async def save_editor(request: web.Request):
        try:
            guild_id=int(request.match_info["guild_id"]); panel_id=int(request.match_info["panel_id"])
        except ValueError:
            return dashboard._json_error("Identifiant invalide.",400)
        session,guild,error=await dashboard._manageable_guild(request,guild_id)
        if error: return error
        csrf_error=dashboard._require_csrf(request,session)
        if csrf_error: return csrf_error
        try: payload=await request.json()
        except Exception: return dashboard._json_error("Requête invalide.",400)
        if not isinstance(payload,dict): return dashboard._json_error("Requête invalide.",400)
        bot=request.app["bot"]; db=bot.db
        if not await db.fetchone("SELECT id FROM ticket_panels_v2 WHERE id=? AND guild_id=?",(panel_id,guild_id)):
            return dashboard._json_error("Panel introuvable.",404)
        from cogs import tickets
        from cogs.ticket_ping_role import delete_ticket_role_rules
        raw_types=payload.get("types") or []
        if not isinstance(raw_types,list) or len(raw_types)>25:
            return dashboard._json_error("Un panel peut contenir au maximum 25 boutons.",400)
        existing_ids={int(x["id"]) for x in await db.fetchall("SELECT id FROM ticket_types WHERE panel_id=? AND guild_id=?",(panel_id,guild_id))}
        seen_ids=set(); normalized=[]
        try:
            for index,raw in enumerate(raw_types):
                if not isinstance(raw,dict): raise ValueError("Un bouton contient des données invalides.")
                type_id=None; raw_id=raw.get("id")
                if raw_id not in (None,"",0,"0"):
                    type_id=int(raw_id)
                    if type_id not in existing_ids or type_id in seen_ids: raise ValueError("Un bouton ne fait pas partie de ce panel.")
                    seen_ids.add(type_id)
                name=_safe_text(raw.get("name"),80)
                if not name: raise ValueError("Chaque bouton doit avoir un nom de type.")
                label=_safe_text(raw.get("button_label"),80); description=_safe_text(raw.get("description"),150)
                raw_emoji=_safe_text(raw.get("emoji"),100); emoji=tickets.parse_component_emoji(raw_emoji,bot) if raw_emoji else None
                if raw_emoji and emoji is None: raise ValueError(f"L'emoji du bouton « {name} » n'est pas utilisable par SentriX.")
                questions=[]; questions_raw=raw.get("questions") or []
                if not isinstance(questions_raw,list) or len(questions_raw)>5: raise ValueError(f"Le formulaire « {name} » peut contenir au maximum 5 questions.")
                for qi,q in enumerate(questions_raw):
                    if not isinstance(q,dict): raise ValueError("Une question de formulaire est invalide.")
                    qlabel=_safe_text(q.get("label"),45)
                    if not qlabel: raise ValueError(f"La question {qi+1} de « {name} » doit avoir un texte.")
                    qmin=_int(q.get("min_length",0),0,4000,"La longueur minimale"); qmax=_int(q.get("max_length",500),1,4000,"La longueur maximale")
                    if qmin>qmax: raise ValueError("La longueur minimale d’une question ne peut pas dépasser sa longueur maximale.")
                    questions.append({"label":qlabel,"placeholder":_safe_text(q.get("placeholder"),100),"style":"long" if str(q.get("style") or "court")=="long" else "court","required":1 if q.get("required",True) else 0,"min_length":qmin,"max_length":qmax,"position":qi})
                normalized.append({"id":type_id,"name":name,"description":description,"emoji":str(emoji) if emoji else None,"button_label":label,"button_style":_style(raw.get("button_style") or "bleu"),"staff_role_id":_role_id(guild,raw.get("staff_role_id")),"category_id":_category_id(guild,raw.get("category_id")),"name_format":_safe_text(raw.get("name_format"),90) or "ticket-{pseudo}","open_message":_safe_text(raw.get("open_message"),1000),"max_per_member":_int(raw.get("max_per_member",1),1,20,"La limite de tickets"),"autoclose_hours":_int(raw.get("autoclose_hours",0),0,720,"La fermeture automatique"),"mention_staff":1 if raw.get("mention_staff",True) else 0,"use_form":1 if raw.get("use_form",False) else 0,"position":_int(raw.get("position",index),0,24,"La position"),"questions":questions})
            incoming_staff=payload.get("staff_buttons") or {}
            if not isinstance(incoming_staff,dict): raise ValueError("Configuration des boutons staff invalide.")
            saved_staff=tickets.default_button_settings()
            for key in tickets.STAFF_BUTTONS:
                source=incoming_staff.get(key) or saved_staff[key]
                label=_safe_text(source.get("label"),80)
                if bool(source.get("enabled",False)) and not label: raise ValueError("Un bouton staff actif doit avoir un texte.")
                raw_emoji=_safe_text(source.get("emoji"),100); emoji=tickets.parse_component_emoji(raw_emoji,bot) if raw_emoji else None
                if raw_emoji and emoji is None: raise ValueError(f"L'emoji du bouton staff « {label or key} » est invalide.")
                saved_staff[key]={"enabled":bool(source.get("enabled",False)),"label":label or tickets.STAFF_BUTTONS[key][0],"emoji":str(emoji) if emoji else "","style":_style(source.get("style") or "bleu"),"role_id":_role_id(guild,source.get("role_id"))}
        except (TypeError,ValueError) as exc:
            return dashboard._json_error(str(exc),400)
        for type_id in existing_ids-seen_ids:
            await db.execute("DELETE FROM ticket_form_questions WHERE ticket_type_id=?",(type_id,)); await delete_ticket_role_rules(bot,guild_id,panel_id,type_id); await db.execute("DELETE FROM ticket_types WHERE id=? AND panel_id=? AND guild_id=?",(type_id,panel_id,guild_id))
        for item in normalized:
            values=(item["name"],item["description"],item["emoji"],item["button_label"],item["button_style"],item["staff_role_id"],item["category_id"],item["name_format"],item["open_message"],item["max_per_member"],item["autoclose_hours"],item["mention_staff"],item["use_form"],item["position"])
            type_id=item["id"]
            if type_id is None:
                cur=await db.execute("INSERT INTO ticket_types (panel_id,guild_id,name,description,emoji,button_label,button_style,staff_role_id,category_id,name_format,open_message,max_per_member,autoclose_hours,mention_staff,use_form,position) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(panel_id,guild_id,*values)); type_id=int(cur.lastrowid)
            else:
                await db.execute("UPDATE ticket_types SET name=?,description=?,emoji=?,button_label=?,button_style=?,staff_role_id=?,category_id=?,name_format=?,open_message=?,max_per_member=?,autoclose_hours=?,mention_staff=?,use_form=?,position=? WHERE id=? AND panel_id=? AND guild_id=?",(*values,type_id,panel_id,guild_id))
            await db.execute("DELETE FROM ticket_form_questions WHERE ticket_type_id=?",(type_id,))
            for q in item["questions"]:
                await db.execute("INSERT INTO ticket_form_questions (ticket_type_id,position,label,placeholder,style,required,min_length,max_length) VALUES (?,?,?,?,?,?,?,?)",(type_id,q["position"],q["label"],q["placeholder"],q["style"],q["required"],q["min_length"],q["max_length"]))
        await tickets.save_button_settings(bot,guild_id,saved_staff)
        sync="not_sent"
        try:
            from . import ticket_center_v35
            sync=await ticket_center_v35._sync_panel_message(bot,guild,panel_id)
        except Exception:
            sync="unavailable"
        suffix={"updated":" Le panel déjà envoyé sur Discord a été actualisé.","not_sent":" Le panel n'a pas encore été envoyé sur Discord.","missing":" Le message du panel n'existe plus sur Discord.","unavailable":" Les réglages sont sauvegardés, mais Discord n'a pas pu actualiser le panel maintenant.","runtime_unavailable":" Les réglages sont sauvegardés ; le moteur Tickets termine son démarrage."}.get(sync,"")
        return web.json_response({"ok":True,"sync":sync,"message":"Boutons et textes enregistrés."+suffix})

    def build_app(bot)->web.Application:
        app=original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/ticket-button-editor/{panel_id}",get_editor)
        app.router.add_patch("/api/guilds/{guild_id}/ticket-button-editor/{panel_id}",save_editor)
        return app

    dashboard.build_app=build_app
    dashboard.INDEX_HTML=_inject(dashboard.INDEX_HTML)

__all__=["install"]
