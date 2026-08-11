"""Dashboard Engagement V3 pour SentriX et Bot'Odboug.

La page et ses routes sont enregistrées avant le bind HTTP. Le bootstrap runtime reste
volontairement tolérant aux faux objets bot utilisés par les audits synthétiques.
"""
from __future__ import annotations

import html
import logging

import discord
from aiohttp import web

from utils.instance_identity import brand_label

logger = logging.getLogger("bot.dashboard.engagement-v3")
_INSTALLED = False


def _service(request: web.Request):
    bot = request.app.get("bot")
    getter = getattr(bot, "get_cog", None)
    return getter("EngagementSuite") if callable(getter) else None


async def _payload(request: web.Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:
        raise ValueError("Requête invalide.") from exc
    if not isinstance(data, dict):
        raise ValueError("Requête invalide.")
    return data


async def _admin_ctx(dashboard, request: web.Request, *, write: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, ValueError):
        return None, None, None, dashboard._json_error("Serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return None, None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, csrf_error
    service = _service(request)
    if service is None:
        return None, None, None, dashboard._json_error(
            "Engagement V3 démarre. Réessaie dans quelques secondes.", 503
        )
    return session, guild, service, None


async def _member_ctx(dashboard, request: web.Request, guild_id: int):
    session, error = dashboard._require_session(request)
    if error or not session:
        return None, None, None, error
    bot = request.app.get("bot")
    get_guild = getattr(bot, "get_guild", None)
    guild = get_guild(int(guild_id)) if callable(get_guild) else None
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
        return None, None, None, dashboard._json_error("Tu dois être membre de ce serveur.", 403)
    service = _service(request)
    if service is None:
        return None, None, None, dashboard._json_error("Engagement V3 démarre.", 503)
    return session, guild, service, None


async def handle_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login?next=/engagement")
    return web.Response(
        text=ENGAGEMENT_HTML,
        content_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


async def handle_profile_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound(f"/login?next={request.path}")
    return web.Response(
        text=PROFILE_HTML,
        content_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


async def api_options(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    settings = await service.get_settings(guild.id)
    return web.json_response({
        "ok": True,
        "brand": brand_label(),
        "settings": settings,
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels],
        "roles": [
            {"id": str(r.id), "name": r.name}
            for r in guild.roles
            if not r.is_default() and not r.managed
        ],
    })


async def api_settings_put(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        settings = await service.update_settings(guild, await _payload(request))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "settings": settings})


async def api_leaderboard(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    rows = await service.leaderboard(guild.id, 50)
    for row in rows:
        member = guild.get_member(row["user_id"])
        row["display_name"] = member.display_name if member else str(row["user_id"])
        row["avatar_url"] = member.display_avatar.url if member else ""
    return web.json_response({"ok": True, "leaderboard": rows})


async def api_profile_self(dashboard, request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return dashboard._json_error("Serveur invalide.", 400)
    session, guild, service, error = await _member_ctx(dashboard, request, guild_id)
    if error:
        return error
    profile = await service.profile(guild, int(session["user"]["id"]))
    return web.json_response({
        "ok": True,
        "brand": brand_label(),
        "guild_name": guild.name,
        "profile": profile,
    })


async def api_suggestions_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    status = str(request.query.get("status") or "all")
    if status not in {"all", "pending", "accepted", "refused", "in_progress", "done"}:
        status = "all"
    return web.json_response({
        "ok": True,
        "suggestions": await service.list_suggestions(guild.id, status),
    })


async def api_suggestion_review(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        suggestion = await service.review_suggestion(
            guild,
            int(request.match_info["suggestion_id"]),
            str(data.get("status") or "pending"),
            str(data.get("note") or ""),
        )
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "suggestion": suggestion})


async def api_reviews_get(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request)
    if error:
        return error
    status = str(request.query.get("status") or "pending")
    if status not in {"all", "pending", "ignored", "reviewed", "action_taken"}:
        status = "pending"
    return web.json_response({
        "ok": True,
        "reviews": await service.list_reviews(guild.id, status),
    })


async def api_review_resolve(dashboard, request: web.Request):
    _session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        await service.resolve_review(
            guild.id,
            int(request.match_info["review_id"]),
            str(data.get("status") or "reviewed"),
        )
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True})


async def api_ticket_summary(dashboard, request: web.Request):
    session, guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        channel = guild.get_channel(int(data.get("channel_id") or 0))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Choisis un salon textuel valide.")
        summary = await service.summarize_ticket(channel, int(session["user"]["id"]))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "summary": summary})


async def api_changelog_get(dashboard, request: web.Request):
    session, error = dashboard._require_session(request)
    if error or not session:
        return error
    service = _service(request)
    if service is None:
        return dashboard._json_error("Engagement V3 démarre.", 503)
    return web.json_response({"ok": True, "changelog": await service.list_changelog()})


async def api_changelog_post(dashboard, request: web.Request):
    _session, _guild, service, error = await _admin_ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        item_id = await service.add_changelog(
            str(data.get("version") or "Update"),
            str(data.get("title") or "Mise à jour"),
            str(data.get("body") or ""),
        )
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "id": item_id})


def _brand_html(source: str) -> str:
    return source.replace("{{BRAND}}", html.escape(brand_label()))


ENGAGEMENT_HTML = _brand_html(r'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{BRAND}} Engagement V3</title><style>
:root{--bg:#080a10;--panel:#10131b;--panel2:#151925;--line:#252b3a;--text:#f4f6fb;--muted:#949caf;--accent:#7d8cff;--danger:#ff7287}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 12% -10%,#20284c 0,transparent 34%),var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}.shell{max-width:1320px;margin:auto;padding:26px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:20px}.brand{font-size:25px;font-weight:900}.brand small{display:block;font-size:11px;color:var(--muted);letter-spacing:.11em;text-transform:uppercase}.toolbar{display:flex;gap:8px;flex-wrap:wrap}.btn,.back{border:1px solid var(--line);background:#171b27;color:var(--text);border-radius:11px;padding:10px 13px;font-weight:760;text-decoration:none;cursor:pointer}.btn.primary{background:var(--accent);border-color:var(--accent)}.btn.danger{background:#211116;border-color:#5b2931;color:#ffdbe1}.layout{display:grid;grid-template-columns:240px 1fr;gap:16px}.side,.card{border:1px solid var(--line);background:rgba(16,19,27,.94);border-radius:18px}.side{padding:11px;height:max-content;position:sticky;top:16px}.nav{display:block;width:100%;border:0;background:transparent;color:var(--muted);text-align:left;padding:11px;border-radius:10px;font-weight:740;cursor:pointer}.nav.active,.nav:hover{background:var(--panel2);color:var(--text)}.main{display:grid;gap:14px}.card{padding:19px}.card h2{font-size:18px;margin:0 0 6px}.card p{margin:0 0 15px;color:var(--muted);line-height:1.5}.row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.field{display:grid;gap:6px;margin-bottom:11px}label{font-size:11px;color:var(--muted);text-transform:uppercase;font-weight:800}input,select,textarea{width:100%;border:1px solid var(--line);background:#0b0e15;color:var(--text);border-radius:10px;padding:10px 11px}textarea{min-height:85px}.switch{display:flex;align-items:center;gap:8px;padding:8px 0}.switch input{width:auto}.hidden{display:none!important}.notice{border:1px solid #2a385d;background:#0d1422;color:#d4dcff;padding:11px 13px;border-radius:11px;margin-bottom:14px}.grid4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.metric,.item{border:1px solid var(--line);background:#0d1017;border-radius:13px;padding:13px}.metric b{display:block;font-size:20px}.metric span,.meta{color:var(--muted);font-size:12px}.list{display:grid;gap:9px}.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:4px 7px;font-size:10px;color:var(--muted)}pre{white-space:pre-wrap;background:#090c12;border:1px solid var(--line);padding:14px;border-radius:12px;color:#dce2ff}@media(max-width:900px){.shell{padding:14px}.layout{grid-template-columns:1fr}.side{position:static;display:flex;overflow:auto}.nav{white-space:nowrap}.grid4{grid-template-columns:repeat(2,1fr)}.row{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}@media(max-width:520px){.grid4{grid-template-columns:1fr}}
</style></head><body><div class="shell"><div class="top"><div class="brand">{{BRAND}}<small>Engagement V3</small></div><div class="toolbar"><a class="back" href="/app">Dashboard</a><a class="back" href="/community">Communauté</a></div></div><div id="notice" class="notice">Chargement...</div><div class="layout"><aside class="side"><button class="nav active" data-tab="overview">Vue d'ensemble</button><button class="nav" data-tab="onboarding">Onboarding</button><button class="nav" data-tab="quests">Quêtes & saisons</button><button class="nav" data-tab="suggestions">Suggestions</button><button class="nav" data-tab="starboard">Starboard</button><button class="nav" data-tab="moderation">Modération contextuelle</button><button class="nav" data-tab="tickets">IA tickets</button><button class="nav" data-tab="changelog">Changelog</button></aside><main class="main">
<section id="tab-overview" class="card"><h2>Centre d'engagement</h2><p>Profils, quêtes, saisons, suggestions, starboard, onboarding et outils IA du staff.</p><div class="field"><label>Serveur</label><select id="guild"></select></div><div class="grid4"><div class="metric"><b id="mSeason">—</b><span>Saison</span></div><div class="metric"><b id="mLeader">—</b><span>Top membre</span></div><div class="metric"><b>6</b><span>Quêtes actives</span></div><div class="metric"><b>10</b><span>Succès</span></div></div><h2 style="margin-top:20px">Classement saisonnier</h2><div id="leaderboard" class="list"></div></section>
<section id="tab-onboarding" class="card hidden"><h2>Onboarding V2</h2><p>Langue de profil, rôles d'intérêt et validation du règlement.</p><div class="switch"><input id="onboardingEnabled" type="checkbox"><label for="onboardingEnabled">Activer l'onboarding</label></div><div class="field"><label>Salon onboarding</label><select id="onboardingChannel"></select></div><div class="field"><label>Rôles proposés (Ctrl/Cmd pour plusieurs)</label><select id="onboardingRoles" multiple size="8"></select></div><button class="btn primary" id="saveOnboarding">Enregistrer</button></section>
<section id="tab-quests" class="card hidden"><h2>Profils, quêtes et saisons</h2><p>Points d'engagement, succès, quêtes quotidiennes/hebdomadaires et classement de saison.</p><div class="switch"><input id="profilesEnabled" type="checkbox"><label for="profilesEnabled">Profils membres</label></div><div class="switch"><input id="questsEnabled" type="checkbox"><label for="questsEnabled">Quêtes automatiques</label></div><div class="field"><label>Durée d'une saison (jours)</label><input id="seasonDays" type="number" min="7" max="120"></div><button class="btn primary" id="saveQuests">Enregistrer</button></section>
<section id="tab-suggestions" class="card hidden"><h2>Suggestions V2</h2><p>Le salon choisi devient un vrai système de suggestions avec votes, statuts et réponse staff.</p><div class="switch"><input id="suggestionsEnabled" type="checkbox"><label for="suggestionsEnabled">Activer les suggestions</label></div><div class="field"><label>Salon suggestions</label><select id="suggestionsChannel"></select></div><div class="toolbar"><button class="btn primary" id="saveSuggestions">Enregistrer</button><button class="btn" id="refreshSuggestions">Actualiser</button></div><div id="suggestions" class="list" style="margin-top:14px"></div></section>
<section id="tab-starboard" class="card hidden"><h2>Starboard</h2><p>Republie les messages populaires dans un salon dédié.</p><div class="switch"><input id="starboardEnabled" type="checkbox"><label for="starboardEnabled">Activer le starboard</label></div><div class="row"><div class="field"><label>Salon starboard</label><select id="starboardChannel"></select></div><div class="field"><label>Emoji</label><input id="starboardEmoji" value="⭐"></div></div><div class="field"><label>Seuil de réactions</label><input id="starboardThreshold" type="number" min="2" max="50"></div><button class="btn primary" id="saveStarboard">Enregistrer</button></section>
<section id="tab-moderation" class="card hidden"><h2>Modération contextuelle</h2><p>Détecte spam, répétitions agressives, mentions massives et messages à risque. Le staff décide toujours de la sanction.</p><div class="switch"><input id="contextEnabled" type="checkbox"><label for="contextEnabled">Activer la file de révision</label></div><div class="field"><label>Salon d'alertes staff</label><select id="contextChannel"></select></div><div class="toolbar"><button class="btn primary" id="saveContext">Enregistrer</button><button class="btn" id="refreshReviews">Actualiser</button></div><div id="reviews" class="list" style="margin-top:14px"></div></section>
<section id="tab-tickets" class="card hidden"><h2>IA dans les tickets</h2><p>Génère un résumé neutre du salon choisi avec la prochaine action conseillée.</p><div class="switch"><input id="ticketAiEnabled" type="checkbox"><label for="ticketAiEnabled">Activer le résumé IA</label></div><div class="field"><label>Salon à résumer</label><select id="ticketChannel"></select></div><div class="toolbar"><button class="btn" id="saveTicketAi">Enregistrer</button><button class="btn primary" id="summarizeTicket">Résumer ce ticket</button></div><pre id="ticketSummary">Aucun résumé généré.</pre></section>
<section id="tab-changelog" class="card hidden"><h2>Centre de mises à jour</h2><p>Journal des grosses nouveautés du bot.</p><div class="row"><div class="field"><label>Version</label><input id="changeVersion" placeholder="V3.1"></div><div class="field"><label>Titre</label><input id="changeTitle" placeholder="Nouvelle mise à jour"></div></div><div class="field"><label>Détails</label><textarea id="changeBody"></textarea></div><button class="btn primary" id="publishChange">Publier</button><div id="changelog" class="list" style="margin-top:14px"></div></section>
</main></div></div><script>
const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let csrf='',guildId='',opts={};
async function api(url,opt={}){opt.credentials='same-origin';opt.headers={'Content-Type':'application/json',...(opt.headers||{})};if(opt.method&&opt.method!=='GET')opt.headers['X-CSRF-Token']=csrf;const r=await fetch(url,opt);const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'Erreur serveur');return d}function notice(t,ok=true){$('notice').textContent=t;$('notice').style.borderColor=ok?'#294537':'#5b2931'}function fill(id,items,empty='Aucun'){const e=$(id);e.innerHTML=`<option value="">${esc(empty)}</option>`+items.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}function selectedValues(id){return [...$(id).selectedOptions].map(x=>x.value).filter(Boolean)}
async function boot(){const me=await api('/api/me');csrf=me.csrf;const g=await api('/api/guilds');const installed=g.guilds.filter(x=>x.installed);$('guild').innerHTML=installed.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('');if(!installed.length){notice('Aucun serveur administrable.',false);return}guildId=installed[0].id;await loadAll()}async function loadAll(){opts=await api(`/api/guilds/${guildId}/engagement/options`);const s=opts.settings||{};['onboardingChannel','suggestionsChannel','starboardChannel','contextChannel','ticketChannel'].forEach(id=>fill(id,opts.text_channels));$('onboardingRoles').innerHTML=opts.roles.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('');$('onboardingEnabled').checked=!!Number(s.onboarding_enabled);$('onboardingChannel').value=s.onboarding_channel_id||'';const roles=JSON.parse(s.onboarding_role_ids||'[]').map(String);[...$('onboardingRoles').options].forEach(o=>o.selected=roles.includes(o.value));$('profilesEnabled').checked=!!Number(s.profiles_enabled??1);$('questsEnabled').checked=!!Number(s.quests_enabled??1);$('seasonDays').value=s.season_length_days||30;$('suggestionsEnabled').checked=!!Number(s.suggestions_enabled);$('suggestionsChannel').value=s.suggestions_channel_id||'';$('starboardEnabled').checked=!!Number(s.starboard_enabled);$('starboardChannel').value=s.starboard_channel_id||'';$('starboardEmoji').value=s.starboard_emoji||'⭐';$('starboardThreshold').value=s.starboard_threshold||5;$('contextEnabled').checked=!!Number(s.context_review_enabled);$('contextChannel').value=s.context_review_channel_id||'';$('ticketAiEnabled').checked=!!Number(s.ticket_ai_enabled??1);await Promise.all([loadLeaderboard(),loadSuggestions(),loadReviews(),loadChangelog()]);notice(`Engagement V3 prêt pour ${opts.brand}.`)}async function save(data){await api(`/api/guilds/${guildId}/engagement/settings`,{method:'PUT',body:JSON.stringify(data)});await loadAll();notice('Réglages enregistrés.')}
async function loadLeaderboard(){const d=await api(`/api/guilds/${guildId}/engagement/leaderboard`);$('leaderboard').innerHTML=d.leaderboard.length?d.leaderboard.map((x,i)=>`<div class="item"><strong>#${i+1} ${esc(x.display_name)}</strong><span class="meta">${x.points} points</span></div>`).join(''):'<div class="meta">Aucun score pour le moment.</div>';$('mLeader').textContent=d.leaderboard[0]?.display_name||'—';$('mSeason').textContent=d.leaderboard.length?'Active':'Nouvelle'}async function loadSuggestions(){const d=await api(`/api/guilds/${guildId}/engagement/suggestions?status=all`);$('suggestions').innerHTML=d.suggestions.length?d.suggestions.map(x=>`<div class="item"><strong>#${x.id} <span class="pill">${esc(x.status)}</span></strong><p>${esc(x.text)}</p><textarea id="sn-${x.id}" placeholder="Réponse staff">${esc(x.staff_note||'')}</textarea><div class="toolbar"><button class="btn primary" onclick="reviewSuggestion(${x.id},'accepted')">Accepter</button><button class="btn" onclick="reviewSuggestion(${x.id},'in_progress')">En développement</button><button class="btn" onclick="reviewSuggestion(${x.id},'done')">Terminé</button><button class="btn danger" onclick="reviewSuggestion(${x.id},'refused')">Refuser</button></div></div>`).join(''):'<div class="meta">Aucune suggestion.</div>'}window.reviewSuggestion=async(id,status)=>{try{await api(`/api/guilds/${guildId}/engagement/suggestions/${id}/review`,{method:'POST',body:JSON.stringify({status,note:$('sn-'+id).value})});await loadSuggestions();notice('Suggestion mise à jour.')}catch(e){notice(e.message,false)}};
async function loadReviews(){const d=await api(`/api/guilds/${guildId}/engagement/reviews?status=pending`);$('reviews').innerHTML=d.reviews.length?d.reviews.map(x=>`<div class="item"><strong>#${x.id} · score ${x.score}</strong><div class="meta">Utilisateur ${x.user_id} · message ${x.message_id}</div><p>${x.reasons.map(esc).join(' · ')}</p><div class="toolbar"><button class="btn" onclick="resolveReview(${x.id},'reviewed')">Vu</button><button class="btn danger" onclick="resolveReview(${x.id},'action_taken')">Action prise</button><button class="btn" onclick="resolveReview(${x.id},'ignored')">Ignorer</button></div></div>`).join(''):'<div class="meta">Aucun message à réviser.</div>'}window.resolveReview=async(id,status)=>{try{await api(`/api/guilds/${guildId}/engagement/reviews/${id}/resolve`,{method:'POST',body:JSON.stringify({status})});await loadReviews();notice('Révision mise à jour.')}catch(e){notice(e.message,false)}};async function loadChangelog(){const d=await api('/api/engagement/changelog');$('changelog').innerHTML=d.changelog.map(x=>`<div class="item"><strong>${esc(x.version)} · ${esc(x.title)}</strong><p>${esc(x.body)}</p></div>`).join('')}
$('guild').onchange=async()=>{guildId=$('guild').value;await loadAll()};document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>{document.querySelectorAll('.nav').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('main section').forEach(x=>x.classList.add('hidden'));$('tab-'+b.dataset.tab).classList.remove('hidden')});$('saveOnboarding').onclick=()=>save({onboarding_enabled:$('onboardingEnabled').checked,onboarding_channel_id:$('onboardingChannel').value,onboarding_role_ids:selectedValues('onboardingRoles')}).catch(e=>notice(e.message,false));$('saveQuests').onclick=()=>save({profiles_enabled:$('profilesEnabled').checked,quests_enabled:$('questsEnabled').checked,season_length_days:Number($('seasonDays').value||30)}).catch(e=>notice(e.message,false));$('saveSuggestions').onclick=()=>save({suggestions_enabled:$('suggestionsEnabled').checked,suggestions_channel_id:$('suggestionsChannel').value}).catch(e=>notice(e.message,false));$('refreshSuggestions').onclick=()=>loadSuggestions().catch(e=>notice(e.message,false));$('saveStarboard').onclick=()=>save({starboard_enabled:$('starboardEnabled').checked,starboard_channel_id:$('starboardChannel').value,starboard_emoji:$('starboardEmoji').value,starboard_threshold:Number($('starboardThreshold').value||5)}).catch(e=>notice(e.message,false));$('saveContext').onclick=()=>save({context_review_enabled:$('contextEnabled').checked,context_review_channel_id:$('contextChannel').value}).catch(e=>notice(e.message,false));$('refreshReviews').onclick=()=>loadReviews().catch(e=>notice(e.message,false));$('saveTicketAi').onclick=()=>save({ticket_ai_enabled:$('ticketAiEnabled').checked}).catch(e=>notice(e.message,false));$('summarizeTicket').onclick=async()=>{try{$('ticketSummary').textContent='Résumé en cours...';const d=await api(`/api/guilds/${guildId}/engagement/ticket-summary`,{method:'POST',body:JSON.stringify({channel_id:$('ticketChannel').value})});$('ticketSummary').textContent=d.summary;notice('Résumé IA terminé.')}catch(e){$('ticketSummary').textContent=e.message;notice(e.message,false)}};$('publishChange').onclick=async()=>{try{await api(`/api/guilds/${guildId}/engagement/changelog`,{method:'POST',body:JSON.stringify({version:$('changeVersion').value,title:$('changeTitle').value,body:$('changeBody').value})});await loadChangelog();notice('Entrée publiée.')}catch(e){notice(e.message,false)}};boot().catch(e=>notice(e.message,false));
</script></body></html>''')


PROFILE_HTML = _brand_html(r'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mon profil · {{BRAND}}</title><style>:root{--bg:#080a10;--panel:#111520;--line:#272d3c;--text:#f5f6fa;--muted:#929bad;--accent:#7d8cff}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -20%,#202a50,transparent 42%),var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif}.wrap{max-width:900px;margin:0 auto;padding:30px 16px}.card{background:rgba(17,21,32,.96);border:1px solid var(--line);border-radius:20px;padding:22px;margin-bottom:14px}.head{display:flex;gap:14px;align-items:center}.avatar{width:72px;height:72px;border-radius:50%;object-fit:cover;background:#181d2b}.muted{color:var(--muted)}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:16px}.metric{border:1px solid var(--line);border-radius:12px;padding:12px}.metric b{display:block;font-size:19px}.quest{border:1px solid var(--line);border-radius:11px;padding:11px;margin:8px 0}.bar{height:7px;background:#202536;border-radius:99px;overflow:hidden;margin-top:8px}.bar span{display:block;height:100%;background:var(--accent)}.badges{display:flex;gap:7px;flex-wrap:wrap}.badge{border:1px solid var(--line);border-radius:999px;padding:7px 9px;font-size:12px}@media(max-width:650px){.metrics{grid-template-columns:repeat(2,1fr)}}</style></head><body><div class="wrap"><div id="notice" class="card muted">Chargement du profil...</div><div id="content" style="display:none"></div></div><script>const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const guild=location.pathname.split('/')[3];async function api(u){const r=await fetch(u,{credentials:'same-origin',cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.error||'Erreur');return d}async function boot(){const d=await api(`/api/engagement/profile/${guild}`),p=d.profile,m=p.member;document.getElementById('notice').remove();const c=document.getElementById('content');c.style.display='block';c.innerHTML=`<div class="card"><div class="head"><img class="avatar" src="${esc(p.avatar_url)}"><div><h1>${esc(p.display_name)}</h1><div class="muted">${esc(d.guild_name)} · ${esc(d.brand)}</div></div></div><div class="metrics"><div class="metric"><b>${m.points||0}</b><span>Points</span></div><div class="metric"><b>${m.message_count||0}</b><span>Messages</span></div><div class="metric"><b>${Math.floor((m.voice_seconds||0)/60)} min</b><span>Vocal</span></div><div class="metric"><b>#${p.season.rank||'—'}</b><span>Rang saison</span></div></div></div><div class="card"><h2>Quêtes</h2>${p.quests.map(q=>`<div class="quest"><b>${esc(q.label)}</b><div class="muted">${q.progress}/${q.target} · ${q.reward} points ${q.claimed?'· terminée':''}</div><div class="bar"><span style="width:${Math.min(100,Math.round(q.progress/q.target*100))}%"></span></div></div>`).join('')}</div><div class="card"><h2>Succès</h2><div class="badges">${p.achievements.length?p.achievements.map(a=>`<span class="badge">${esc(a.label)}</span>`).join(''):'<span class="muted">Aucun succès pour le moment.</span>'}</div></div>`}boot().catch(e=>document.getElementById('notice').textContent=e.message);</script></body></html>''')


def install(dashboard, community_module=None) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    if community_module is not None and isinstance(getattr(community_module, "COMMUNITY_HTML", None), str):
        marker = '<a class="back" href="/enterprise">Enterprise</a>'
        link = marker + '<a class="back" href="/engagement">Engagement V3</a>'
        if marker in community_module.COMMUNITY_HTML and 'href="/engagement"' not in community_module.COMMUNITY_HTML:
            community_module.COMMUNITY_HTML = community_module.COMMUNITY_HTML.replace(marker, link, 1)

    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard

        async def startup_engagement(_app):
            # Les audits E2E emploient un _DummyBot sans cogs/base de données. Dans ce cas
            # les routes doivent rester testables, mais aucun runtime Discord ne doit démarrer.
            getter = getattr(bot, "get_cog", None)
            if not callable(getter) or not hasattr(bot, "db"):
                return
            if getter("EngagementSuite") is not None:
                return
            try:
                from cogs import engagement_suite
                await engagement_suite.setup(bot)
            except Exception:
                logger.exception("Impossible de démarrer Engagement V3.")

        app.on_startup.append(startup_engagement)
        app.router.add_routes([
            web.get("/engagement", handle_page),
            web.get("/engagement/profile/{guild_id}", handle_profile_page),
            web.get("/api/guilds/{guild_id}/engagement/options", lambda r: api_options(dashboard, r)),
            web.put("/api/guilds/{guild_id}/engagement/settings", lambda r: api_settings_put(dashboard, r)),
            web.get("/api/guilds/{guild_id}/engagement/leaderboard", lambda r: api_leaderboard(dashboard, r)),
            web.get("/api/engagement/profile/{guild_id}", lambda r: api_profile_self(dashboard, r)),
            web.get("/api/guilds/{guild_id}/engagement/suggestions", lambda r: api_suggestions_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/engagement/suggestions/{suggestion_id}/review", lambda r: api_suggestion_review(dashboard, r)),
            web.get("/api/guilds/{guild_id}/engagement/reviews", lambda r: api_reviews_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/engagement/reviews/{review_id}/resolve", lambda r: api_review_resolve(dashboard, r)),
            web.post("/api/guilds/{guild_id}/engagement/ticket-summary", lambda r: api_ticket_summary(dashboard, r)),
            web.get("/api/engagement/changelog", lambda r: api_changelog_get(dashboard, r)),
            web.post("/api/guilds/{guild_id}/engagement/changelog", lambda r: api_changelog_post(dashboard, r)),
        ])
        return app

    dashboard.build_app = build_app
    logger.info("Dashboard Engagement V3 installé.")
