"""Dashboard web Giveaway V101.

Une seule surface visuelle gere la creation et les actions courantes des giveaways.
Le module ne duplique pas le moteur de tirage : creation, fin, reroll et annulation
passent tous par ``cogs.giveaway_v2.GiveawayV2``.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict

import discord
from aiohttp import web

from cogs.giveaway_v2 import BuilderState, GiveawayV2
from utils import helpers

logger = logging.getLogger("bot.dashboard.giveaway-v101")

_MAX_RECENT = 50
_MAX_ROLES = 10
_MAX_COUNTER = 1_000_000


def _v2(bot) -> GiveawayV2 | None:
    cog = bot.get_cog("GiveawayV2")
    return cog if isinstance(cog, GiveawayV2) else None


async def _authorized(dashboard, request: web.Request, *, write: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, TypeError, ValueError):
        return None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)

    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, csrf_error
    return session, guild, None


def _clean_text(value, *, maximum: int, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError("champ obligatoire manquant")
    if len(text) > maximum:
        raise ValueError(f"texte trop long ({maximum} caractères maximum)")
    return text or None


def _counter(value, label: str, *, minimum: int = 0, maximum: int = _MAX_COUNTER) -> int:
    try:
        number = int(value if value not in (None, "") else 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} doit être un nombre entier") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} doit être compris entre {minimum} et {maximum}")
    return number


def _optional_id(value, label: str) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} est invalide") from exc


def _role_ids(guild: discord.Guild, value, label: str) -> list[int]:
    raw = value or []
    if not isinstance(raw, list):
        raise ValueError(f"{label} doit être une liste de rôles")
    if len(raw) > _MAX_ROLES:
        raise ValueError(f"{label} accepte au maximum {_MAX_ROLES} rôles")
    result: list[int] = []
    for item in raw:
        role_id = _optional_id(item, label)
        if role_id is None or role_id in result:
            continue
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed:
            raise ValueError(f"un rôle de {label} n'existe plus ou ne peut pas être utilisé")
        result.append(role_id)
    return result


def parse_create_payload(guild: discord.Guild, payload: dict, dashboard) -> BuilderState:
    """Valide le formulaire web puis produit exactement l'état attendu par GiveawayV2."""
    if not isinstance(payload, dict):
        raise ValueError("formulaire invalide")

    prize = _clean_text(payload.get("prize"), maximum=180, required=True)
    duration_text = _clean_text(payload.get("duration"), maximum=32, required=True)
    duration_seconds = helpers.parse_duration(duration_text or "")
    if not duration_seconds:
        raise ValueError("durée invalide (exemples : 30m, 2h, 3j)")

    winners = _counter(payload.get("winners", 1), "Le nombre de gagnants", minimum=1, maximum=50)
    channel_id = _optional_id(payload.get("channel_id"), "Le salon")
    channel = guild.get_channel(channel_id or 0)
    if channel is None or not isinstance(channel, discord.TextChannel):
        raise ValueError("le salon de publication doit être un salon textuel de ce serveur")

    ping_role_id = _optional_id(payload.get("ping_role_id"), "Le rôle à ping")
    if ping_role_id is not None:
        role = guild.get_role(ping_role_id)
        if role is None or role.is_default() or role.managed:
            raise ValueError("le rôle à ping n'existe plus ou ne peut pas être utilisé")

    required_roles = _role_ids(guild, payload.get("required_roles"), "rôles obligatoires")
    excluded_roles = _role_ids(guild, payload.get("excluded_roles"), "rôles interdits")
    bonus_roles = _role_ids(guild, payload.get("bonus_roles"), "rôles bonus")
    if set(required_roles) & set(excluded_roles):
        raise ValueError("un même rôle ne peut pas être obligatoire et interdit")

    description = _clean_text(payload.get("description"), maximum=900)
    custom_condition = _clean_text(payload.get("custom_condition"), maximum=500)
    image_url = _clean_text(payload.get("image_url"), maximum=500)
    if image_url and not dashboard._valid_https_url(image_url):
        raise ValueError("l'image doit utiliser une URL HTTPS valide")

    return BuilderState(
        author_id=0,
        guild_id=guild.id,
        prize=prize,
        duration_text=duration_text,
        duration_seconds=int(duration_seconds),
        winners=winners,
        channel_id=channel.id,
        description=description,
        image_url=image_url,
        ping_role_id=ping_role_id,
        required_roles=required_roles,
        excluded_roles=excluded_roles,
        bonus_roles=bonus_roles,
        bonus_multiplier=_counter(payload.get("bonus_multiplier", 2), "Le multiplicateur bonus", minimum=1, maximum=100),
        min_invites=_counter(payload.get("min_invites", 0), "Les invitations minimum"),
        min_account_age_days=_counter(payload.get("min_account_age_days", 0), "L'âge minimum du compte"),
        min_server_age_days=_counter(payload.get("min_server_age_days", 0), "L'ancienneté minimum sur le serveur"),
        custom_condition=custom_condition,
    )


class _DashboardContext:
    """Contexte minimal permettant au dashboard de réutiliser les handlers V2 existants."""

    def __init__(self, guild: discord.Guild):
        self.guild = guild
        self.messages: list[str] = []

    async def send(self, content=None, **_kwargs):
        if content:
            self.messages.append(str(content))
        return None


def _row_payload(row) -> dict:
    return {
        "message_id": str(row["message_id"]),
        "channel_id": str(row["channel_id"]),
        "prize": row["prize"],
        "winners": int(row["winners_count"] or 1),
        "end_at": int(row["end_at"]),
        "status": str(row["status"]),
        "created_at": int(row["created_at"]),
        "entries": int(row["entries"] or 0),
    }


def install(dashboard) -> None:
    """Ajoute les routes et la page Giveaway sans toucher aux routes OAuth existantes."""
    if getattr(dashboard, "_sentrix_giveaway_dashboard_v101", False):
        return

    async def page(request: web.Request):
        session, error = dashboard._require_session(request)
        if error or session is None:
            raise web.HTTPFound("/login")
        return web.Response(text=GIVEAWAY_HTML, content_type="text/html")

    async def list_giveaways(request: web.Request):
        _session, guild, error = await _authorized(dashboard, request)
        if error:
            return error
        cog = _v2(request.app["bot"])
        if cog is None:
            return dashboard._json_error("Le moteur Giveaway V2 n'est pas chargé.", 503)
        await cog.ensure_schema()
        rows = await request.app["bot"].db.fetchall(
            """
            SELECT g.*,
                   (SELECT COUNT(*) FROM giveaway_entries_v2 e WHERE e.giveaway_id=g.id) AS entries
            FROM giveaways_v2 g
            WHERE g.guild_id=?
            ORDER BY CASE g.status WHEN 'actif' THEN 0 WHEN 'termine' THEN 1 ELSE 2 END,
                     g.created_at DESC
            LIMIT ?
            """,
            (guild.id, _MAX_RECENT),
        )
        return web.json_response({"giveaways": [_row_payload(row) for row in rows]})

    async def create_giveaway(request: web.Request):
        session, guild, error = await _authorized(dashboard, request, write=True)
        if error:
            return error
        rate_key = (request.cookies.get(dashboard.SESSION_COOKIE), guild.id, "giveaway-create")
        if time.time() - request.app["write_limits"].get(rate_key, 0) < 1.5:
            return dashboard._json_error("Attendez un instant avant de créer un autre giveaway.", 429)
        try:
            payload = await request.json()
            state = parse_create_payload(guild, payload, dashboard)
        except ValueError as exc:
            return dashboard._json_error(str(exc).capitalize() + ".", 400)
        except Exception:
            return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

        cog = _v2(request.app["bot"])
        if cog is None:
            return dashboard._json_error("Le moteur Giveaway V2 n'est pas chargé.", 503)

        user_id = int(session["user"]["id"])
        author = guild.get_member(user_id)
        if author is None:
            try:
                author = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                author = discord.Object(id=user_id)
        state.author_id = user_id

        try:
            message = await cog.publish(guild, state, author)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Publication giveaway dashboard refusée guild=%s: %s", guild.id, exc)
            return dashboard._json_error(
                "Discord a refusé la publication. Vérifiez les permissions de SentriX dans le salon.", 502
            )
        except Exception:
            logger.exception("Création giveaway dashboard impossible guild=%s", guild.id)
            return dashboard._json_error("Le giveaway n'a pas pu être publié.", 500)

        request.app["write_limits"][rate_key] = time.time()
        return web.json_response(
            {
                "ok": True,
                "message": "Giveaway publié.",
                "message_id": str(message.id),
                "jump_url": message.jump_url,
            }
        )

    async def manage_giveaway(request: web.Request):
        _session, guild, error = await _authorized(dashboard, request, write=True)
        if error:
            return error
        action = str(request.match_info.get("action") or "").casefold()
        if action not in {"end", "reroll", "cancel"}:
            return dashboard._json_error("Action giveaway inconnue.", 404)
        try:
            message_id = int(request.match_info["message_id"])
        except (KeyError, TypeError, ValueError):
            return dashboard._json_error("Identifiant de giveaway invalide.", 400)

        rate_key = (request.cookies.get(dashboard.SESSION_COOKIE), guild.id, "giveaway-manage")
        if time.time() - request.app["write_limits"].get(rate_key, 0) < 1.0:
            return dashboard._json_error("Attendez un instant avant une autre action.", 429)

        cog = _v2(request.app["bot"])
        if cog is None:
            return dashboard._json_error("Le moteur Giveaway V2 n'est pas chargé.", 503)
        await cog.ensure_schema()
        row = await request.app["bot"].db.fetchone(
            "SELECT status FROM giveaways_v2 WHERE guild_id=? AND message_id=?",
            (guild.id, message_id),
        )
        if row is None:
            return dashboard._json_error("Giveaway introuvable sur ce serveur.", 404)
        status = str(row["status"])
        if action in {"end", "cancel"} and status != "actif":
            return dashboard._json_error("Ce giveaway n'est plus actif.", 409)
        if action == "reroll" and status != "termine":
            return dashboard._json_error("Terminez d'abord ce giveaway avant de refaire un tirage.", 409)

        ctx = _DashboardContext(guild)
        handler = {
            "end": cog.handle_end,
            "reroll": cog.handle_reroll,
            "cancel": cog.handle_cancel,
        }[action]
        try:
            handled = await handler(ctx, message_id)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Action giveaway dashboard refusée action=%s guild=%s", action, guild.id)
            return dashboard._json_error("Discord a refusé l'action. Vérifiez les permissions de SentriX.", 502)
        except Exception:
            logger.exception("Action giveaway dashboard échouée action=%s guild=%s", action, guild.id)
            return dashboard._json_error("L'action n'a pas pu être appliquée.", 500)
        if not handled:
            return dashboard._json_error("Giveaway introuvable sur ce serveur.", 404)

        request.app["write_limits"][rate_key] = time.time()
        labels = {"end": "Giveaway terminé.", "reroll": "Nouveau tirage effectué.", "cancel": "Giveaway annulé."}
        return web.json_response({"ok": True, "message": ctx.messages[-1] if ctx.messages else labels[action]})

    original_build_app = dashboard.build_app

    def build_app_with_giveaways(bot):
        app = original_build_app(bot)
        app.router.add_get("/giveaways", page)
        app.router.add_get("/api/guilds/{guild_id}/giveaways", list_giveaways)
        app.router.add_post("/api/guilds/{guild_id}/giveaways", create_giveaway)
        app.router.add_post(
            "/api/guilds/{guild_id}/giveaways/{message_id}/{action}", manage_giveaway
        )
        return app

    build_app_with_giveaways._sentrix_giveaway_dashboard_v101 = True
    build_app_with_giveaways._sentrix_original = original_build_app
    dashboard.build_app = build_app_with_giveaways

    nav_marker = '<button data-tab="tickets">Tickets</button>'
    nav_link = '<a class="gw-main-link" href="/giveaways">Giveaways</a>'
    if nav_link not in dashboard.INDEX_HTML:
        dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace(nav_marker, nav_marker + nav_link, 1)
        dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace(
            "</head>",
            "<style>.nav .gw-main-link{display:block;color:var(--muted);padding:11px 12px;border-radius:10px;margin:2px 0;font-weight:650}.nav .gw-main-link:hover{background:#7c6cff18;color:var(--text)}</style></head>",
            1,
        )

    dashboard._sentrix_giveaway_dashboard_v101 = True
    logger.info("Dashboard Giveaway V101 installé : panneau unique, création et gestion V2.")


GIVEAWAY_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentriX — Giveaways</title>
<style>
:root{--bg:#090b12;--panel:#111522;--panel2:#171c2c;--line:#262d43;--text:#f2f4ff;--muted:#949db5;--brand:#7c6cff;--bad:#ff667d;--ok:#44d39a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}.wrap{max-width:980px;margin:auto;padding:30px 18px 70px}.top{display:flex;justify-content:space-between;gap:14px;align-items:center;margin-bottom:20px}.top h1{margin:0;font-size:27px}.top p{margin:5px 0 0;color:var(--muted)}a{color:inherit;text-decoration:none}.btn{border:1px solid var(--line);background:var(--panel2);color:var(--text);padding:10px 13px;border-radius:10px;font-weight:700;cursor:pointer}.btn.primary{background:var(--brand);border-color:transparent}.btn.danger{color:#ff9aaa;border-color:#713044;background:#351722}.btn:disabled{opacity:.45;cursor:not-allowed}.select,input,textarea{width:100%;background:#0c101a;border:1px solid var(--line);color:var(--text);border-radius:10px;padding:10px 11px;outline:none}.select:focus,input:focus,textarea:focus{border-color:var(--brand)}textarea{min-height:84px;resize:vertical}.gw-card{background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden}.gw-head{padding:18px 20px;border-bottom:1px solid var(--line);display:flex;gap:14px;justify-content:space-between;align-items:center}.gw-head strong{font-size:17px}.gw-body{padding:20px}.mode{display:flex;gap:8px;margin-bottom:18px}.mode .btn.active{background:var(--brand);border-color:transparent}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.field label{display:block;font-weight:700;margin-bottom:6px}.field small{display:block;color:var(--muted);margin-top:5px}.full{grid-column:1/-1}.section-title{grid-column:1/-1;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:800;padding-top:12px;border-top:1px solid var(--line)}.actions{display:flex;gap:9px;flex-wrap:wrap;margin-top:18px}.hidden{display:none!important}.status{margin-left:auto;color:var(--muted);font-size:13px}.list{display:grid;gap:10px}.item{border:1px solid var(--line);border-radius:11px;padding:13px;background:#0d111c}.item-head{display:flex;justify-content:space-between;gap:12px}.item b{overflow-wrap:anywhere}.meta{color:var(--muted);font-size:12px;margin-top:6px}.item .actions{margin-top:10px}.badge{font-size:11px;font-weight:800;text-transform:uppercase}.badge.actif{color:var(--ok)}.badge.termine{color:#b8b8c8}.badge.annule{color:var(--bad)}.empty{padding:24px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:11px}.toast{position:fixed;right:20px;bottom:20px;background:var(--panel2);border:1px solid var(--line);padding:12px 14px;border-radius:10px;max-width:360px}.toast.bad{border-color:#713044}.checkrow{display:flex;align-items:center;gap:8px}.multi{min-height:112px}
@media(max-width:700px){.grid{grid-template-columns:1fr}.full,.section-title{grid-column:auto}.top,.gw-head{align-items:stretch;flex-direction:column}.status{margin-left:0}.actions .btn{flex:1 1 auto}}
</style>
</head>
<body><div class="wrap">
<div class="top"><div><h1>Giveaways</h1><p>Création et gestion dans un seul panneau.</p></div><a class="btn" href="/app">Retour au dashboard</a></div>
<main class="gw-card">
<header class="gw-head"><strong>Centre Giveaway</strong><select id="guild" class="select" style="max-width:330px"><option value="">Chargement…</option></select></header>
<div class="gw-body">
<div class="mode"><button class="btn active" id="createTab" type="button">Créer</button><button class="btn" id="manageTab" type="button">Gérer</button><span id="status" class="status"></span></div>
<form id="createForm" class="grid">
<div class="field"><label>Récompense</label><input id="prize" maxlength="180" required placeholder="Nitro, rôle VIP, item…"></div>
<div class="field"><label>Durée</label><input id="duration" maxlength="32" required placeholder="30m, 2h, 3j"></div>
<div class="field"><label>Nombre de gagnants</label><input id="winners" type="number" min="1" max="50" value="1" required></div>
<div class="field"><label>Salon</label><select id="channel" class="select" required></select></div>
<div class="section-title">Options facultatives</div>
<div class="field"><label>Rôle à ping</label><select id="pingRole" class="select"><option value="">Aucun</option></select></div>
<div class="field"><label>Image</label><input id="imageUrl" type="url" maxlength="500" placeholder="https://…"></div>
<div class="field full"><label>Description</label><textarea id="description" maxlength="900"></textarea></div>
<div class="field"><label>Rôles obligatoires</label><select id="requiredRoles" class="select multi" multiple></select><small>Ctrl/Cmd + clic pour plusieurs rôles.</small></div>
<div class="field"><label>Rôles interdits</label><select id="excludedRoles" class="select multi" multiple></select></div>
<div class="field"><label>Rôles bonus</label><select id="bonusRoles" class="select multi" multiple></select></div>
<div class="field"><label>Multiplicateur bonus</label><input id="bonusMultiplier" type="number" min="1" max="100" value="2"></div>
<div class="field"><label>Invitations minimum</label><input id="minInvites" type="number" min="0" max="1000000" value="0"></div>
<div class="field"><label>Âge minimum du compte (jours)</label><input id="accountAge" type="number" min="0" max="1000000" value="0"></div>
<div class="field"><label>Présence minimum serveur (jours)</label><input id="serverAge" type="number" min="0" max="1000000" value="0"></div>
<div class="field full"><label>Condition personnalisée</label><textarea id="customCondition" maxlength="500"></textarea><small>Information affichée aux participants ; les conditions automatiques sont revérifiées au tirage.</small></div>
<div class="actions full"><button class="btn primary" id="publish" type="submit">Publier le giveaway</button></div>
</form>
<section id="manageView" class="hidden"><div id="giveawayList" class="list"></div><div class="actions"><button class="btn" id="refresh" type="button">Actualiser</button></div></section>
</div></main></div><div id="toast" class="toast hidden"></div>
<script>
(() => {
"use strict";
const $=id=>document.getElementById(id);let csrf="",guildData=null;
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function toast(msg,bad=false){const el=$("toast");el.textContent=msg;el.className=`toast${bad?" bad":""}`;clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.add("hidden"),4000)}
async function api(url,opt={}){opt.credentials="same-origin";opt.headers=opt.headers||{};if(opt.method&&opt.method!=="GET"){opt.headers["Content-Type"]="application/json";opt.headers["X-CSRF-Token"]=csrf}const r=await fetch(url,opt);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||"Une erreur est survenue.");return d}
function selected(id){return Array.from($(id).selectedOptions).map(o=>o.value).filter(Boolean)}
function roleOptions(){const roles=guildData?.roles||[];return roles.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("")}
async function loadGuild(id){if(!id)return;$("status").textContent="Chargement…";guildData=await api(`/api/guilds/${id}`);const channels=(guildData.channels||[]).filter(c=>String(c.type).includes("text"));$("channel").innerHTML='<option value="">Choisir un salon</option>'+channels.map(c=>`<option value="${esc(c.id)}">#${esc(c.name)}</option>`).join("");$("pingRole").innerHTML='<option value="">Aucun</option>'+roleOptions();for(const id of ["requiredRoles","excludedRoles","bonusRoles"])$(id).innerHTML=roleOptions();$("status").textContent="";if(!$("manageView").classList.contains("hidden"))await loadList()}
async function loadList(){const id=$("guild").value;if(!id)return;$("status").textContent="Actualisation…";const d=await api(`/api/guilds/${id}/giveaways`);const list=$("giveawayList");if(!d.giveaways.length){list.innerHTML='<div class="empty">Aucun giveaway trouvé sur ce serveur.</div>'}else{list.innerHTML=d.giveaways.map(g=>{const active=g.status==="actif",done=g.status==="termine";return `<div class="item"><div class="item-head"><b>${esc(g.prize)}</b><span class="badge ${esc(g.status)}">${esc(g.status)}</span></div><div class="meta">#${esc(g.message_id)} · ${esc(g.entries)} participation(s) · ${esc(g.winners)} gagnant(s) · fin ${new Date(g.end_at*1000).toLocaleString("fr-FR")}</div><div class="actions">${active?`<button class="btn" data-action="end" data-id="${esc(g.message_id)}">Terminer</button><button class="btn danger" data-action="cancel" data-id="${esc(g.message_id)}">Annuler</button>`:""}${done?`<button class="btn" data-action="reroll" data-id="${esc(g.message_id)}">Reroll</button>`:""}</div></div>`}).join("")}$("status").textContent=""}
async function manage(action,id){if(!confirm(action==="cancel"?"Annuler ce giveaway ?":"Confirmer cette action ?"))return;const guild=$("guild").value;const d=await api(`/api/guilds/${guild}/giveaways/${id}/${action}`,{method:"POST",body:"{}"});toast(d.message||"Action appliquée.");await loadList()}
$("giveawayList").addEventListener("click",e=>{const b=e.target.closest("button[data-action]");if(b)manage(b.dataset.action,b.dataset.id).catch(x=>toast(x.message,true))});
$("createForm").addEventListener("submit",async e=>{e.preventDefault();const guild=$("guild").value;if(!guild)return toast("Choisissez un serveur.",true);const body={prize:$("prize").value,duration:$("duration").value,winners:$("winners").value,channel_id:$("channel").value,ping_role_id:$("pingRole").value,image_url:$("imageUrl").value,description:$("description").value,required_roles:selected("requiredRoles"),excluded_roles:selected("excludedRoles"),bonus_roles:selected("bonusRoles"),bonus_multiplier:$("bonusMultiplier").value,min_invites:$("minInvites").value,min_account_age_days:$("accountAge").value,min_server_age_days:$("serverAge").value,custom_condition:$("customCondition").value};$("publish").disabled=true;try{const d=await api(`/api/guilds/${guild}/giveaways`,{method:"POST",body:JSON.stringify(body)});toast(d.message||"Giveaway publié.");$("createForm").reset();$("winners").value=1;$("bonusMultiplier").value=2;$("minInvites").value=$("accountAge").value=$("serverAge").value=0;await loadGuild(guild)}catch(x){toast(x.message,true)}finally{$("publish").disabled=false}});
function mode(create){$("createForm").classList.toggle("hidden",!create);$("manageView").classList.toggle("hidden",create);$("createTab").classList.toggle("active",create);$("manageTab").classList.toggle("active",!create);if(!create)loadList().catch(x=>toast(x.message,true))}
$("createTab").onclick=()=>mode(true);$("manageTab").onclick=()=>mode(false);$("refresh").onclick=()=>loadList().catch(x=>toast(x.message,true));$("guild").onchange=e=>loadGuild(e.target.value).catch(x=>toast(x.message,true));
(async()=>{const me=await api("/api/me");csrf=me.csrf;const gs=await api("/api/guilds");const installed=gs.guilds.filter(g=>g.installed);$("guild").innerHTML='<option value="">Choisir un serveur</option>'+installed.map(g=>`<option value="${esc(g.id)}">${esc(g.name)}</option>`).join("");if(installed[0]){$("guild").value=installed[0].id;await loadGuild(installed[0].id)}})().catch(x=>{toast(x.message,true);if(String(x.message).includes("Connectez"))location.href="/login"});
})();
</script></body></html>"""


__all__ = ["install", "parse_create_payload", "GIVEAWAY_HTML"]
