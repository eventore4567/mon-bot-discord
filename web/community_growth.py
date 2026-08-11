"""Dashboard Community Growth V2 pour SentriX et Bot'Odboug."""
from __future__ import annotations

import html
import json
import logging

import discord
from aiohttp import web

from utils.instance_identity import brand_label

logger = logging.getLogger("bot.dashboard.community-growth")
_INSTALLED = False


def _service(request: web.Request):
    return request.app["bot"].get_cog("CommunityGrowth")


async def _payload(request: web.Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:
        raise ValueError("Le formulaire envoyé est invalide.") from exc
    if not isinstance(data, dict):
        raise ValueError("Le formulaire envoyé est invalide.")
    return data


async def _admin_ctx(dashboard, request: web.Request, *, write: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, ValueError):
        return None, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return None, None, None, error
    service = _service(request)
    if service is None:
        return None, None, None, dashboard._json_error("Le module Communauté démarre.", 503)
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, csrf_error
    return session, guild, service, None


async def _member_ctx(dashboard, request: web.Request, *, write: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, ValueError):
        return None, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
    session, error = dashboard._require_session(request)
    if error or not session:
        return None, None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, csrf_error
    guild = request.app["bot"].get_guild(guild_id)
    if guild is None:
        return None, None, None, dashboard._json_error("Serveur introuvable.", 404)
    user_id = int(session["user"]["id"])
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.HTTPException:
            member = None
    if member is None:
        return None, None, None, dashboard._json_error("Vous devez être membre de ce serveur.", 403)
    service = _service(request)
    if service is None:
        return None, None, None, dashboard._json_error("Le module Communauté démarre.", 503)
    return session, guild, service, None


async def handle_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login")
    return web.Response(text=COMMUNITY_HTML, content_type="text/html", headers={"Cache-Control": "no-store"})


async def handle_apply_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        destination = request.path
        raise web.HTTPFound(f"/login?next={destination}")
    return web.Response(text=APPLICATION_HTML, content_type="text/html", headers={"Cache-Control": "no-store"})


async def api_options(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    settings = await service.get_settings(guild.id)
    roles = [
        {"id": str(role.id), "name": role.name}
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)
        if not role.is_default() and not role.managed
    ]
    text_channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    voice_channels = [{"id": str(c.id), "name": c.name} for c in guild.voice_channels]
    categories = [{"id": str(c.id), "name": c.name} for c in guild.categories]
    return web.json_response({
        "ok": True,
        "settings": settings,
        "roles": roles,
        "text_channels": text_channels,
        "voice_channels": voice_channels,
        "categories": categories,
        "brand": brand_label(),
    })


async def api_settings_put(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        for key in ("application_review_channel_id", "temp_voice_lobby_id", "temp_voice_category_id"):
            value = data.get(key)
            if value not in (None, "", 0, "0"):
                channel = guild.get_channel(int(value))
                if key == "application_review_channel_id" and not isinstance(channel, discord.TextChannel):
                    raise ValueError("Choisissez un salon textuel valide pour les candidatures.")
                if key == "temp_voice_lobby_id" and not isinstance(channel, discord.VoiceChannel):
                    raise ValueError("Choisissez un salon vocal valide comme lobby.")
                if key == "temp_voice_category_id" and not isinstance(channel, discord.CategoryChannel):
                    raise ValueError("Choisissez une catégorie valide pour les vocaux temporaires.")
        settings = await service.update_settings(guild, **data)
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "settings": settings})


async def api_forms_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    return web.json_response({"ok": True, "forms": await service.list_forms(guild.id)})


async def api_forms_put(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        form_id = await service.save_form(guild, int(session["user"]["id"]), data)
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "id": form_id})


async def api_form_delete(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        form_id = int(request.match_info["form_id"])
        await service.delete_form(guild.id, form_id)
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True})


async def api_applications_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    status = str(request.query.get("status") or "all").casefold()
    if status not in {"all", "pending", "accepted", "refused", "more_info"}:
        status = "all"
    return web.json_response({"ok": True, "applications": await service.list_applications(guild.id, status)})


async def api_application_review(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        result = await service.review_application(
            guild,
            int(request.match_info["application_id"]),
            int(session["user"]["id"]),
            str(data.get("decision") or ""),
            str(data.get("note") or ""),
        )
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "application": result})


async def api_apply_form_get(dashboard, request: web.Request):
    _session, guild, service, error = await _member_ctx(dashboard, request)
    if error:
        return error
    try:
        form_id = int(request.match_info["form_id"])
    except ValueError:
        return dashboard._json_error("Formulaire invalide.", 400)
    form = await service.get_form(guild.id, form_id, enabled_only=True)
    if not form:
        return dashboard._json_error("Ce formulaire n'est plus disponible.", 404)
    settings = await service.get_settings(guild.id)
    if not int(settings.get("applications_enabled", 1)):
        return dashboard._json_error("Les candidatures sont actuellement fermées.", 403)
    public_form = {
        "id": form["id"], "title": form["title"], "description": form["description"],
        "questions": form["questions"], "guild_name": guild.name,
    }
    return web.json_response({"ok": True, "form": public_form, "brand": brand_label()})


async def api_apply_form_post(dashboard, request: web.Request):
    session, guild, service, error = await _member_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        answers = data.get("answers") if isinstance(data.get("answers"), list) else []
        application_id = await service.submit_application(
            guild, int(session["user"]["id"]), int(request.match_info["form_id"]), answers
        )
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "id": application_id})


async def api_automation_quickstart(dashboard, request: web.Request):
    session, guild, _service_growth, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    enterprise = request.app["bot"].get_cog("EnterpriseSuite")
    if enterprise is None:
        return dashboard._json_error("Le moteur d'automatisations n'est pas prêt.", 503)
    try:
        data = await _payload(request)
        actions = []
        role_id = data.get("role_id")
        channel_id = data.get("channel_id")
        content = str(data.get("content") or "Bienvenue {member} sur {server} !").strip()[:1500]
        if role_id not in (None, "", 0, "0"):
            role = guild.get_role(int(role_id))
            if role is None or role.managed:
                raise ValueError("Rôle automatique invalide.")
            actions.append({"type": "add_role", "role_id": int(role_id)})
        if channel_id not in (None, "", 0, "0"):
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                raise ValueError("Salon de bienvenue invalide.")
            actions.append({"type": "send_channel", "channel_id": int(channel_id), "content": content})
        if not actions:
            raise ValueError("Choisissez au moins un rôle ou un salon.")
        rule_id = await enterprise.save_automation(
            guild.id,
            int(session["user"]["id"]),
            {
                "name": str(data.get("name") or "Accueil automatique")[:80],
                "trigger_type": "member_join",
                "conditions": {},
                "actions": actions,
                "cooldown_seconds": 30,
                "enabled": True,
            },
        )
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "id": rule_id})


def _brand_html(source: str) -> str:
    brand = html.escape(brand_label())
    return source.replace("{{BRAND}}", brand)


COMMUNITY_HTML = _brand_html(r'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{BRAND}} Community</title>
<style>
:root{--bg:#080a10;--panel:#10131b;--panel2:#151925;--line:#252b3a;--text:#f4f6fb;--muted:#949caf;--accent:#7d8cff;--ok:#63d59a;--danger:#ff6f82;--warn:#e8bd67}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% -10%,#1a2140 0,transparent 34%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.shell{max-width:1260px;margin:0 auto;padding:28px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px}.brand{font-size:24px;font-weight:850;letter-spacing:-.04em}.brand small{display:block;color:var(--muted);font-size:12px;font-weight:650;letter-spacing:.08em;text-transform:uppercase;margin-top:5px}.back{color:var(--text);text-decoration:none;border:1px solid var(--line);background:#0d1017;border-radius:12px;padding:10px 14px}
.grid{display:grid;grid-template-columns:250px 1fr;gap:18px}.side,.card{background:rgba(16,19,27,.92);border:1px solid var(--line);border-radius:18px;box-shadow:0 16px 50px rgba(0,0,0,.22)}.side{padding:12px;height:max-content;position:sticky;top:18px}.nav{width:100%;text-align:left;border:0;background:transparent;color:var(--muted);padding:12px;border-radius:11px;font-weight:700;cursor:pointer}.nav.active,.nav:hover{background:var(--panel2);color:var(--text)}.main{display:grid;gap:16px}.card{padding:20px}.card h2{margin:0 0 6px;font-size:18px}.card p{margin:0 0 16px;color:var(--muted);line-height:1.5}.row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.field{display:grid;gap:7px;margin-bottom:12px}label{font-size:12px;color:var(--muted);font-weight:750;text-transform:uppercase;letter-spacing:.05em}input,select,textarea{width:100%;border:1px solid var(--line);background:#0b0e15;color:var(--text);border-radius:11px;padding:11px 12px;outline:none}textarea{min-height:92px;resize:vertical}input:focus,select:focus,textarea:focus{border-color:#5969d8}.btn{border:1px solid var(--line);background:#171b27;color:var(--text);border-radius:11px;padding:10px 14px;font-weight:750;cursor:pointer}.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}.btn.danger{color:#ffdbe0;border-color:#5b2931;background:#211116}.toolbar{display:flex;gap:9px;flex-wrap:wrap}.hidden{display:none!important}.list{display:grid;gap:10px}.item{border:1px solid var(--line);background:#0d1017;border-radius:13px;padding:14px}.item strong{display:block;margin-bottom:5px}.meta{color:var(--muted);font-size:12px}.status{padding:5px 8px;border-radius:999px;background:#181d2a;color:var(--muted);font-size:11px;font-weight:800}.notice{padding:12px 14px;border-radius:12px;background:#0d1422;border:1px solid #25375e;color:#cdd7ff;margin-bottom:14px}.switch{display:flex;align-items:center;gap:9px}.switch input{width:auto}.q{display:flex;gap:8px;margin-bottom:8px}.q input{flex:1}@media(max-width:820px){.shell{padding:16px}.grid{grid-template-columns:1fr}.side{position:static;display:flex;overflow:auto}.nav{white-space:nowrap}.row{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
</style></head><body><div class="shell">
<div class="top"><div class="brand">{{BRAND}}<small>Community Control Center</small></div><div class="toolbar"><a class="back" href="/app">Dashboard principal</a><a class="back" href="/enterprise">Enterprise</a></div></div>
<div id="notice" class="notice">Chargement du centre communautaire...</div>
<div class="grid"><aside class="side"><button class="nav active" data-tab="overview">Vue d'ensemble</button><button class="nav" data-tab="automations">Automatisations</button><button class="nav" data-tab="applications">Candidatures</button><button class="nav" data-tab="voice">Vocaux temporaires</button></aside>
<main class="main">
<section id="tab-overview" class="card"><h2>Centre communautaire</h2><p>Configure les fonctions qui font gagner du temps au staff sans ajouter de nouvelles commandes Discord.</p><div class="field"><label>Serveur</label><select id="guild"></select></div><div class="row"><div class="item"><strong>Automatisations rapides</strong><span class="meta">Accueil, rôle automatique et message de bienvenue.</span></div><div class="item"><strong>Candidatures staff</strong><span class="meta">Formulaires, revue, décision et rôle automatique.</span></div><div class="item"><strong>Vocaux temporaires</strong><span class="meta">Création automatique depuis un lobby puis suppression à vide.</span></div><div class="item"><strong>Même interface sur les deux bots</strong><span class="meta">La marque change par instance, le moteur et le design restent partagés.</span></div></div></section>
<section id="tab-automations" class="card hidden"><h2>Automatisation d'accueil</h2><p>Crée en quelques secondes une règle sûre dans le moteur Enterprise existant.</p><div class="row"><div class="field"><label>Rôle donné à l'arrivée</label><select id="autoRole"></select></div><div class="field"><label>Salon de bienvenue</label><select id="autoChannel"></select></div></div><div class="field"><label>Message</label><textarea id="autoMessage">Bienvenue {member} sur {server} !</textarea></div><button class="btn primary" id="createAutomation">Créer l'automatisation</button></section>
<section id="tab-applications" class="card hidden"><h2>Candidatures staff</h2><p>Crée un formulaire puis partage son lien. Les candidatures arrivent ici pour le staff.</p><div class="switch"><input type="checkbox" id="applicationsEnabled"><label for="applicationsEnabled">Candidatures ouvertes</label></div><div class="field"><label>Salon de notification staff</label><select id="reviewChannel"></select></div><div class="row"><div class="field"><label>Titre du formulaire</label><input id="formTitle" value="Candidature staff"></div><div class="field"><label>Rôle donné si accepté</label><select id="acceptRole"></select></div></div><div class="field"><label>Description</label><textarea id="formDescription" placeholder="Explique les conditions et ce que tu attends des candidats."></textarea></div><div class="field"><label>Questions</label><div id="questions"></div><button class="btn" id="addQuestion">Ajouter une question</button></div><div class="toolbar"><button class="btn primary" id="saveForm">Créer le formulaire</button><button class="btn" id="saveApplicationSettings">Enregistrer les réglages</button></div><h2 style="margin-top:24px">Formulaires</h2><div id="forms" class="list"></div><h2 style="margin-top:24px">Candidatures reçues</h2><div class="field"><label>Filtre</label><select id="appStatus"><option value="pending">En attente</option><option value="all">Toutes</option><option value="accepted">Acceptées</option><option value="refused">Refusées</option><option value="more_info">Informations demandées</option></select></div><div id="applications" class="list"></div></section>
<section id="tab-voice" class="card hidden"><h2>Vocaux temporaires</h2><p>Le membre rejoint le lobby, {{BRAND}} crée son vocal, le déplace dedans puis supprime le salon lorsqu'il est vide.</p><div class="switch"><input type="checkbox" id="voiceEnabled"><label for="voiceEnabled">Activer les vocaux temporaires</label></div><div class="row"><div class="field"><label>Lobby "Créer un vocal"</label><select id="voiceLobby"></select></div><div class="field"><label>Catégorie de création</label><select id="voiceCategory"></select></div></div><div class="row"><div class="field"><label>Nom du vocal</label><input id="voiceName" value="Vocal de {user}"></div><div class="field"><label>Limite de membres (0 = illimitée)</label><input id="voiceLimit" type="number" min="0" max="99" value="0"></div></div><button class="btn primary" id="saveVoice">Enregistrer</button></section>
</main></div></div>
<script>
const $=id=>document.getElementById(id);let csrf="",guildId="",options={};
async function api(url,opt={}){opt.credentials="same-origin";opt.headers={"Content-Type":"application/json",...(opt.headers||{})};if(opt.method&&opt.method!=="GET")opt.headers["X-CSRF-Token"]=csrf;const r=await fetch(url,opt);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||"Erreur serveur");return d}
function setNotice(text,ok=true){$("notice").textContent=text;$("notice").style.borderColor=ok?"#294537":"#5b2931"}
function fillSelect(id,items,placeholder="Aucun"){const el=$(id);el.innerHTML=`<option value="">${placeholder}</option>`+items.map(x=>`<option value="${x.id}">${x.name}</option>`).join("")}
function addQuestion(value="",required=true){const row=document.createElement("div");row.className="q";row.innerHTML=`<input class="questionText" placeholder="Question" value="${String(value).replaceAll('"','&quot;')}"><label style="display:flex;align-items:center;gap:5px;text-transform:none"><input class="questionRequired" type="checkbox" ${required?'checked':''}>Obligatoire</label><button class="btn danger" type="button">Retirer</button>`;row.querySelector("button").onclick=()=>row.remove();$("questions").appendChild(row)}
async function bootstrap(){const me=await api("/api/me");csrf=me.csrf;const gd=await api("/api/guilds");const installed=gd.guilds.filter(g=>g.installed);$("guild").innerHTML=installed.map(g=>`<option value="${g.id}">${g.name}</option>`).join("");if(!installed.length){setNotice("Aucun serveur administrable avec ce compte.",false);return}guildId=installed[0].id;$("guild").value=guildId;await loadAll()}
async function loadAll(){if(!guildId)return;options=await api(`/api/guilds/${guildId}/community/options`);fillSelect("autoRole",options.roles,"Pas de rôle");fillSelect("acceptRole",options.roles,"Pas de rôle automatique");fillSelect("autoChannel",options.text_channels,"Pas de message");fillSelect("reviewChannel",options.text_channels,"Pas de notification");fillSelect("voiceLobby",options.voice_channels,"Choisir le lobby");fillSelect("voiceCategory",options.categories,"Même catégorie que le lobby");const s=options.settings||{};$("applicationsEnabled").checked=!!Number(s.applications_enabled??1);$("reviewChannel").value=s.application_review_channel_id||"";$("voiceEnabled").checked=!!Number(s.temp_voice_enabled||0);$("voiceLobby").value=s.temp_voice_lobby_id||"";$("voiceCategory").value=s.temp_voice_category_id||"";$("voiceName").value=s.temp_voice_name_template||"Vocal de {user}";$("voiceLimit").value=s.temp_voice_user_limit||0;await Promise.all([loadForms(),loadApplications()]);setNotice(`Centre communautaire prêt pour ${options.brand}.`)}
async function saveSettings(part){await api(`/api/guilds/${guildId}/community/settings`,{method:"PUT",body:JSON.stringify(part)});options=await api(`/api/guilds/${guildId}/community/options`);setNotice("Réglages enregistrés.")}
async function loadForms(){const d=await api(`/api/guilds/${guildId}/community/forms`);$("forms").innerHTML=d.forms.length?d.forms.map(f=>`<div class="item"><strong>${f.title}</strong><div class="meta">${f.questions.length} question(s) · ${f.enabled?'actif':'désactivé'}</div><div class="toolbar" style="margin-top:9px"><button class="btn" onclick="copyLink(${f.id})">Copier le lien</button><button class="btn danger" onclick="deleteForm(${f.id})">Supprimer</button></div></div>`).join(""):"<div class='meta'>Aucun formulaire pour le moment.</div>"}
async function loadApplications(){const status=$("appStatus").value;const d=await api(`/api/guilds/${guildId}/community/applications?status=${status}`);$("applications").innerHTML=d.applications.length?d.applications.map(a=>`<div class="item"><div style="display:flex;justify-content:space-between;gap:8px"><strong>#${a.id} · ${a.form_title}</strong><span class="status">${a.status}</span></div><div class="meta">Utilisateur ${a.user_id}</div>${a.answers.map(x=>`<p><b>${x.question}</b><br>${x.answer||'<span class=meta>Sans réponse</span>'}</p>`).join('')}<textarea id="note-${a.id}" placeholder="Note au candidat"></textarea><div class="toolbar"><button class="btn primary" onclick="review(${a.id},'accepted')">Accepter</button><button class="btn" onclick="review(${a.id},'more_info')">Demander des infos</button><button class="btn danger" onclick="review(${a.id},'refused')">Refuser</button></div></div>`).join(""):"<div class='meta'>Aucune candidature dans ce filtre.</div>"}
window.copyLink=async id=>{const url=`${location.origin}/community/apply/${guildId}/${id}`;try{await navigator.clipboard.writeText(url);setNotice("Lien de candidature copié.")}catch{prompt("Copie ce lien :",url)}};
window.deleteForm=async id=>{if(!confirm("Supprimer ce formulaire ?"))return;try{await api(`/api/guilds/${guildId}/community/forms/${id}`,{method:"DELETE"});await loadForms();setNotice("Formulaire supprimé.")}catch(e){setNotice(e.message,false)}};
window.review=async(id,decision)=>{try{await api(`/api/guilds/${guildId}/community/applications/${id}/review`,{method:"POST",body:JSON.stringify({decision,note:$("note-"+id).value})});await loadApplications();setNotice("Décision enregistrée et candidat notifié.")}catch(e){setNotice(e.message,false)}};
document.querySelectorAll(".nav").forEach(b=>b.onclick=()=>{document.querySelectorAll(".nav").forEach(x=>x.classList.remove("active"));b.classList.add("active");document.querySelectorAll("main section").forEach(x=>x.classList.add("hidden"));$("tab-"+b.dataset.tab).classList.remove("hidden")});
$("guild").onchange=async()=>{guildId=$("guild").value;await loadAll()};$("addQuestion").onclick=()=>addQuestion();addQuestion("Pourquoi veux-tu rejoindre le staff ?");addQuestion("Quelle est ton expérience en modération ?");addQuestion("Quelles sont tes disponibilités ?");
$("createAutomation").onclick=async()=>{try{await api(`/api/guilds/${guildId}/community/automation-quickstart`,{method:"POST",body:JSON.stringify({role_id:$("autoRole").value,channel_id:$("autoChannel").value,content:$("autoMessage").value})});setNotice("Automatisation d'accueil créée.")}catch(e){setNotice(e.message,false)}};
$("saveApplicationSettings").onclick=()=>saveSettings({applications_enabled:$("applicationsEnabled").checked,application_review_channel_id:$("reviewChannel").value}).catch(e=>setNotice(e.message,false));
$("saveForm").onclick=async()=>{try{const questions=[...document.querySelectorAll("#questions .q")].map(r=>({text:r.querySelector(".questionText").value,required:r.querySelector(".questionRequired").checked}));await api(`/api/guilds/${guildId}/community/forms`,{method:"PUT",body:JSON.stringify({title:$("formTitle").value,description:$("formDescription").value,questions,accept_role_id:$("acceptRole").value,enabled:true})});await loadForms();setNotice("Formulaire créé.")}catch(e){setNotice(e.message,false)}};
$("appStatus").onchange=()=>loadApplications().catch(e=>setNotice(e.message,false));
$("saveVoice").onclick=()=>saveSettings({temp_voice_enabled:$("voiceEnabled").checked,temp_voice_lobby_id:$("voiceLobby").value,temp_voice_category_id:$("voiceCategory").value,temp_voice_name_template:$("voiceName").value,temp_voice_user_limit:Number($("voiceLimit").value||0)}).catch(e=>setNotice(e.message,false));
bootstrap().catch(e=>setNotice(e.message,false));
</script></body></html>''')


APPLICATION_HTML = _brand_html(r'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Candidature · {{BRAND}}</title><style>:root{--bg:#080a10;--panel:#111520;--line:#272d3c;--text:#f5f6fa;--muted:#929bad;--accent:#7d8cff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -20%,#202a50,transparent 42%),var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif}.wrap{max-width:760px;margin:0 auto;padding:34px 18px}.card{background:rgba(17,21,32,.95);border:1px solid var(--line);border-radius:20px;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,.3)}h1{margin:0 0 8px}p{color:var(--muted);line-height:1.55}label{display:block;margin:18px 0 7px;font-weight:750}textarea{width:100%;min-height:110px;border:1px solid var(--line);border-radius:12px;background:#0b0e15;color:var(--text);padding:12px;resize:vertical}.btn{margin-top:18px;border:0;border-radius:12px;padding:12px 16px;background:var(--accent);color:#fff;font-weight:800;cursor:pointer}.notice{margin-bottom:14px;color:var(--muted)}</style></head><body><div class="wrap"><div id="notice" class="notice">Chargement...</div><div id="card" class="card" style="display:none"><h1 id="title"></h1><p id="desc"></p><form id="form"></form><button id="submit" class="btn">Envoyer ma candidature</button></div></div><script>const parts=location.pathname.split('/');const guild=parts[3],formId=parts[4];let csrf="",data=null;async function api(url,opt={}){opt.credentials='same-origin';opt.headers={'Content-Type':'application/json',...(opt.headers||{})};if(opt.method&&opt.method!=='GET')opt.headers['X-CSRF-Token']=csrf;const r=await fetch(url,opt);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'Erreur serveur');return d}async function boot(){const me=await api('/api/me');csrf=me.csrf;data=await api(`/api/community/apply/${guild}/${formId}`);document.getElementById('title').textContent=data.form.title;document.getElementById('desc').textContent=data.form.description||`Formulaire ${data.brand}`;const f=document.getElementById('form');data.form.questions.forEach((q,i)=>{const l=document.createElement('label');l.textContent=`${i+1}. ${q.text}${q.required?' *':''}`;const t=document.createElement('textarea');t.dataset.index=i;t.required=!!q.required;f.append(l,t)});document.getElementById('card').style.display='block';document.getElementById('notice').textContent=`${data.form.guild_name} · ${data.brand}`}document.getElementById('submit').onclick=async()=>{try{const answers=[...document.querySelectorAll('textarea')].map(x=>x.value);const d=await api(`/api/community/apply/${guild}/${formId}`,{method:'POST',body:JSON.stringify({answers})});document.getElementById('card').innerHTML=`<h1>Candidature envoyée</h1><p>Merci. Ta candidature #${d.id} est maintenant en attente de traitement par le staff.</p>`}catch(e){document.getElementById('notice').textContent=e.message}};boot().catch(e=>document.getElementById('notice').textContent=e.message);</script></body></html>''')


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    dashboard._PRIVATE_PAGE_PATHS = getattr(dashboard, "_PRIVATE_PAGE_PATHS", set())
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        routes = [
            web.get("/community", handle_page),
            web.get("/community/apply/{guild_id}/{form_id}", handle_apply_page),
            web.get("/api/guilds/{guild_id}/community/options", lambda r: api_options(dashboard, r)),
            web.put("/api/guilds/{guild_id}/community/settings", lambda r: api_settings_put(dashboard, r)),
            web.get("/api/guilds/{guild_id}/community/forms", lambda r: api_forms_get(dashboard, r)),
            web.put("/api/guilds/{guild_id}/community/forms", lambda r: api_forms_put(dashboard, r)),
            web.delete("/api/guilds/{guild_id}/community/forms/{form_id}", lambda r: api_form_delete(dashboard, r)),
            web.get("/api/guilds/{guild_id}/community/applications", lambda r: api_applications_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/community/applications/{application_id}/review", lambda r: api_application_review(dashboard, r)),
            web.post("/api/guilds/{guild_id}/community/automation-quickstart", lambda r: api_automation_quickstart(dashboard, r)),
            web.get("/api/community/apply/{guild_id}/{form_id}", lambda r: api_apply_form_get(dashboard, r)),
            web.post("/api/community/apply/{guild_id}/{form_id}", lambda r: api_apply_form_post(dashboard, r)),
        ]
        for route in routes:
            app.router.add_routes([route])
        return app

    dashboard.build_app = build_app
    card = '<a class="quick-card" href="/community"><strong>Communauté</strong><span>Candidatures, automatisations et vocaux temporaires</span></a>'
    if "/community" not in dashboard.INDEX_HTML:
        marker = "</main>"
        if marker in dashboard.INDEX_HTML:
            dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace(marker, card + marker, 1)
        else:
            dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace("</body>", card + "</body>", 1)
    logger.info("Dashboard Community Growth V2 installé.")
