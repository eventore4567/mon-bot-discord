"""Centre V37 : configuration web des dix systèmes avancés SentriX.

La page est isolée de /app pour conserver la stabilité du dashboard principal, mais un
raccourci compact y est injecté. Toutes les écritures passent par OAuth admin + CSRF.
"""
from __future__ import annotations

import json
import logging
import time

import discord
from aiohttp import web

from cogs import feature_suite_v37 as runtime

logger = logging.getLogger("bot.dashboard.feature-suite-v37")
_INSTALLED = False


def _json_error(dashboard, message: str, status: int = 400):
    return dashboard._json_error(message, status)


async def _ctx(dashboard, request: web.Request, *, write: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, ValueError):
        return None, None, None, _json_error(dashboard, "Serveur invalide.")
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return None, None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, csrf_error
    return session, guild, request.app["bot"], None


async def _payload(request: web.Request) -> dict:
    try:
        value = await request.json()
    except Exception as exc:
        raise ValueError("Le formulaire envoyé est invalide.") from exc
    if not isinstance(value, dict):
        raise ValueError("Le formulaire envoyé est invalide.")
    return value


def _channel(guild: discord.Guild, raw, *, voice=False, category=False):
    if raw in (None, "", 0, "0"):
        return None
    try:
        channel = guild.get_channel(int(raw))
    except (TypeError, ValueError):
        return None
    if voice:
        return channel if isinstance(channel, discord.VoiceChannel) else None
    if category:
        return channel if isinstance(channel, discord.CategoryChannel) else None
    return channel if isinstance(channel, discord.TextChannel) else None


def _role(guild: discord.Guild, raw):
    if raw in (None, "", 0, "0"):
        return None
    try:
        role = guild.get_role(int(raw))
    except (TypeError, ValueError):
        return None
    return role if role and not role.is_default() and not role.managed else None


async def handle_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login?next=/feature-suite")
    return web.Response(
        text=PAGE_HTML,
        content_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


async def api_get(dashboard, request: web.Request):
    _session, guild, bot, error = await _ctx(dashboard, request)
    if error:
        return error
    await runtime.ensure_tables(bot)
    configs = {feature: await runtime.get_config(guild.id, feature, fresh=True) for feature in runtime.FEATURES}
    items = await runtime.list_items(guild.id)
    watch = await runtime.list_watch(guild.id)
    pending_row = await bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM feature_suite_applications WHERE guild_id=? AND status='pending'",
        (guild.id,),
    )
    applications = await bot.db.fetchall(
        "SELECT id,form_item_id,user_id,status,answers_json,review_note,created_at,updated_at "
        "FROM feature_suite_applications WHERE guild_id=? ORDER BY id DESC LIMIT 50",
        (guild.id,),
    )
    app_rows = []
    for row in applications:
        data = dict(row)
        try:
            data["answers"] = json.loads(data.pop("answers_json") or "[]")
        except Exception:
            data["answers"] = []
        member = guild.get_member(int(data["user_id"]))
        data["member_name"] = member.display_name if member else str(data["user_id"])
        app_rows.append(data)

    dangerous_roles = [r for r in guild.roles if not r.is_default() and not r.managed and r.permissions.administrator]
    admin_bots = [m for m in guild.members if m.bot and m.guild_permissions.administrator]
    issues = []
    if configs["temp_voice"].get("enabled") and not _channel(guild, configs["temp_voice"].get("lobby_channel_id"), voice=True):
        issues.append("Le système vocal temporaire est actif mais aucun salon d'entrée valide n'est configuré.")
    if configs["faq"].get("enabled") and not _channel(guild, configs["faq"].get("channel_id")):
        issues.append("La FAQ est active mais son salon n'est pas configuré.")
    if configs["surveillance"].get("enabled") and not _channel(guild, configs["surveillance"].get("log_channel_id")):
        issues.append("La surveillance est active sans salon de journalisation.")
    if dangerous_roles:
        issues.append(f"{len(dangerous_roles)} rôle(s) non géré(s) possèdent Administrateur.")
    if len(admin_bots) > 3:
        issues.append(f"{len(admin_bots)} bots possèdent Administrateur.")

    item_counts = {}
    for item in items:
        item_counts[item["kind"]] = item_counts.get(item["kind"], 0) + 1
    return web.json_response({
        "ok": True,
        "guild": {"id": str(guild.id), "name": guild.name, "members": guild.member_count or 0},
        "configs": configs,
        "items": items,
        "watchlist": watch,
        "applications": app_rows,
        "channels": [{"id": str(c.id), "name": c.name, "kind": "text"} for c in guild.text_channels]
                    + [{"id": str(c.id), "name": c.name, "kind": "voice"} for c in guild.voice_channels]
                    + [{"id": str(c.id), "name": c.name, "kind": "category"} for c in guild.categories],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default() and not r.managed],
        "health": {
            "latency_ms": max(0, round(float(bot.latency or 0) * 1000)),
            "dangerous_admin_roles": len(dangerous_roles),
            "admin_bots": len(admin_bots),
            "text_channels": len(guild.text_channels),
            "voice_channels": len(guild.voice_channels),
            "watched_members": len(watch),
            "pending_applications": int(pending_row["n"] if pending_row else 0),
            "issues": issues,
        },
        "counts": item_counts,
    })


async def api_config_put(dashboard, request: web.Request):
    session, guild, _bot, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        feature = str(data.get("feature") or "")
        enabled = bool(data.get("enabled"))
        config = data.get("data") or {}
        if feature not in runtime.FEATURES or not isinstance(config, dict):
            raise ValueError("Configuration inconnue.")

        # Validation des identifiants structurants pour éviter des configurations mortes.
        if feature == "temp_voice":
            lobby = config.get("lobby_channel_id")
            category = config.get("category_id")
            if lobby and not _channel(guild, lobby, voice=True):
                raise ValueError("Le salon d'entrée vocal est invalide.")
            if category and not _channel(guild, category, category=True):
                raise ValueError("La catégorie vocale est invalide.")
            config["default_limit"] = max(0, min(99, int(config.get("default_limit") or 0)))
            config["name_template"] = str(config.get("name_template") or "Vocal de {user}")[:90]
        elif feature in {"faq", "surveillance", "events", "recruitment"}:
            channel_keys = {
                "faq": ["channel_id"], "surveillance": ["log_channel_id"],
                "events": ["default_channel_id"], "recruitment": ["review_channel_id"],
            }[feature]
            for key in channel_keys:
                if config.get(key) and not _channel(guild, config.get(key)):
                    raise ValueError("Un salon configuré n'est pas un salon textuel valide.")
        if feature == "recruitment" and config.get("accepted_role_id") and not _role(guild, config.get("accepted_role_id")):
            raise ValueError("Le rôle attribué aux candidatures acceptées est invalide.")
        if feature == "sticky_roles":
            values = config.get("excluded_role_ids") or []
            if not isinstance(values, list):
                raise ValueError("La liste des rôles exclus est invalide.")
            config["excluded_role_ids"] = [int(x) for x in values if str(x).isdigit() and _role(guild, x)]

        saved = await runtime.save_config(guild.id, feature, enabled, config, int(session["user"]["id"]))
        return web.json_response({"ok": True, "config": saved, "message": "Configuration enregistrée immédiatement."})
    except (TypeError, ValueError) as exc:
        return _json_error(dashboard, str(exc))


async def api_action(dashboard, request: web.Request):
    session, guild, bot, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        action = str(data.get("action") or "")
        actor_id = int(session["user"]["id"])
        if action == "save_item":
            kind = str(data.get("kind") or "")
            name = str(data.get("name") or "").strip()
            payload = data.get("data") or {}
            item_id = int(data.get("item_id") or 0)
            if not name:
                raise ValueError("Donnez un nom à cet élément.")
            if not isinstance(payload, dict):
                raise ValueError("Configuration invalide.")
            # Validations de salons/rôles selon le type.
            if kind in {"recruitment", "event", "panel"}:
                if payload.get("channel_id") and not _channel(guild, payload.get("channel_id")):
                    raise ValueError("Choisissez un salon textuel valide.")
            if kind == "recruitment" and payload.get("review_channel_id") and not _channel(guild, payload.get("review_channel_id")):
                raise ValueError("Le salon de traitement des candidatures est invalide.")
            if kind == "automation":
                if payload.get("channel_id") and not _channel(guild, payload.get("channel_id")):
                    raise ValueError("Le salon de l'automatisation est invalide.")
                if payload.get("role_id") and not _role(guild, payload.get("role_id")):
                    raise ValueError("Le rôle de l'automatisation est invalide.")
            if kind == "panel":
                for button in payload.get("buttons") or []:
                    if button.get("role_id") and not _role(guild, button.get("role_id")):
                        raise ValueError("Un rôle utilisé par le panneau est invalide.")
            saved_id = await runtime.save_item(guild.id, kind, name, payload, actor_id, item_id=item_id, enabled=bool(data.get("enabled", True)))
            return web.json_response({"ok": True, "id": saved_id, "message": "Élément enregistré."})

        if action == "delete_item":
            await runtime.delete_item(guild.id, int(data.get("item_id") or 0))
            return web.json_response({"ok": True, "message": "Élément supprimé."})

        if action == "watch_add":
            user_id = int(str(data.get("user_id") or "0"))
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.HTTPException as exc:
                    raise ValueError("Membre introuvable sur ce serveur.") from exc
            await runtime.set_watch(guild.id, user_id, str(data.get("level") or "normal"), str(data.get("reason") or ""), actor_id)
            return web.json_response({"ok": True, "message": f"{member.display_name} est maintenant surveillé."})

        if action == "watch_remove":
            await runtime.remove_watch(guild.id, int(data.get("user_id") or 0))
            return web.json_response({"ok": True, "message": "Membre retiré de la surveillance."})

        if action in {"publish_recruitment", "publish_event", "publish_panel"}:
            item = await runtime.get_item(guild.id, int(data.get("item_id") or 0))
            expected = action.removeprefix("publish_")
            if not item or item["kind"] != expected:
                raise ValueError("Élément introuvable.")
            if action == "publish_recruitment":
                message_id = await runtime.publish_recruitment(guild, item)
            elif action == "publish_event":
                message_id = await runtime.publish_event(guild, item)
            else:
                message_id = await runtime.publish_panel(guild, item)
            return web.json_response({"ok": True, "message_id": str(message_id), "message": "Panel publié sur Discord."})

        if action == "application_status":
            application_id = int(data.get("application_id") or 0)
            status = str(data.get("status") or "pending")
            if status not in {"pending", "accepted", "refused", "interview"}:
                raise ValueError("Statut invalide.")
            row = await bot.db.fetchone(
                "SELECT user_id FROM feature_suite_applications WHERE guild_id=? AND id=?",
                (guild.id, application_id),
            )
            if not row:
                raise ValueError("Candidature introuvable.")
            note = str(data.get("note") or "")[:1000]
            await bot.db.execute(
                "UPDATE feature_suite_applications SET status=?, review_note=?, updated_at=? WHERE guild_id=? AND id=?",
                (status, note, int(time.time()), guild.id, application_id),
            )
            if status == "accepted":
                conf = await runtime.get_config(guild.id, "recruitment")
                role = _role(guild, conf.get("accepted_role_id"))
                member = guild.get_member(int(row["user_id"]))
                if role and member and guild.me and role < guild.me.top_role:
                    try:
                        await member.add_roles(role, reason="Candidature acceptée depuis le dashboard SentriX")
                    except discord.HTTPException:
                        pass
            return web.json_response({"ok": True, "message": "Candidature mise à jour."})

        raise ValueError("Action inconnue.")
    except (TypeError, ValueError) as exc:
        return _json_error(dashboard, str(exc))
    except discord.Forbidden:
        return _json_error(dashboard, "SentriX n'a pas les permissions Discord nécessaires.", 403)
    except discord.HTTPException:
        return _json_error(dashboard, "Discord a refusé l'action. Réessayez.", 502)


INJECT_CSS = r"""
<style id="sentrix-feature-suite-v37-link-css">
.sx-v37-entry{display:grid;grid-template-columns:1fr auto;align-items:center;gap:12px;padding:12px 13px;border:1px solid #2b3348;border-radius:10px;background:#10151f;margin:10px 0}.sx-v37-entry b{font-size:12px}.sx-v37-entry span{display:block;color:var(--muted,#8d96aa);font-size:10px;margin-top:3px}.sx-v37-entry a{padding:8px 10px;border:1px solid #6553c3;border-radius:8px;background:#251f42;color:#d4caff;text-decoration:none;font-size:10px;font-weight:850}
</style>
"""

INJECT_JS = r"""
<script id="sentrix-feature-suite-v37-link-js">
(() => {
  "use strict";
  if(window.__sentrixFeatureSuiteV37Link)return;window.__sentrixFeatureSuiteV37Link=true;
  const gid=()=>{try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):"";}catch(_){return"";}};
  function mount(){
    const id=gid(); if(!id)return;
    const href="/feature-suite?guild="+encodeURIComponent(id);
    const home=document.getElementById("sxSimpleHome");
    if(home&&!document.getElementById("sxV37SimpleEntry")){
      const box=document.createElement("div");box.id="sxV37SimpleEntry";box.className="sx-v37-entry";
      box.innerHTML='<div><b>Fonctions avancées configurables</b><span>Automatisations, recrutements, vocaux temporaires, surveillance, planning, événements, FAQ, santé, Sticky Roles et panneaux.</span></div><a href="'+href+'">Configurer</a>';
      const grid=home.querySelector(".sx-simple-grid"); if(grid)grid.insertAdjacentElement("afterend",box);else home.appendChild(box);
    }
    const fields=document.getElementById("fields");
    if(fields&&typeof state!=="undefined"&&state.tab==="general"&&!document.getElementById("sxV37AdvancedEntry")){
      const box=document.createElement("div");box.id="sxV37AdvancedEntry";box.className="sx-v37-entry";box.style.gridColumn="1/-1";
      box.innerHTML='<div><b>Feature Suite V37</b><span>Pilotez les dix systèmes avancés sans commandes Discord.</span></div><a href="'+href+'">Ouvrir</a>';
      fields.prepend(box);
    }
  }
  setInterval(mount,700);setTimeout(mount,180);window.addEventListener("pageshow",mount);
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-feature-suite-v37-link-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", INJECT_CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", INJECT_JS + "\n</body>", 1)
    return html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        runtime.install(bot)
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/feature-suite", handle_page)
        app.router.add_get("/api/guilds/{guild_id}/feature-suite-v37", lambda r: api_get(dashboard, r))
        app.router.add_put("/api/guilds/{guild_id}/feature-suite-v37/config", lambda r: api_config_put(dashboard, r))
        app.router.add_post("/api/guilds/{guild_id}/feature-suite-v37/action", lambda r: api_action(dashboard, r))
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Dashboard Feature Suite V37 installé.")


PAGE_HTML = r'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SentriX — Fonctions avancées</title><style>
:root{--bg:#090c12;--panel:#10151f;--panel2:#151b28;--line:#283147;--text:#f0f1f7;--muted:#8d96aa;--accent:#7664e8;--ok:#59c99b;--bad:#ef7183}*{box-sizing:border-box}body{margin:0;background:linear-gradient(180deg,#090c12,#0b0e15);color:var(--text);font:14px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}button,input,select,textarea{font:inherit}a{color:inherit}.top{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;gap:12px;align-items:center;padding:13px 3vw;border-bottom:1px solid var(--line);background:#090c12f2}.brand{font-weight:900}.top a,.btn{border:1px solid #343e57;background:#171d29;color:var(--text);border-radius:8px;padding:8px 11px;text-decoration:none;cursor:pointer;font-weight:800}.btn.primary{border-color:#7562db;background:#2a234a}.btn.danger{border-color:#6f3340;background:#2e171d;color:#ffb5c0}.shell{max-width:1380px;margin:auto;padding:22px}.head{display:grid;grid-template-columns:1fr minmax(240px,390px);gap:14px;align-items:end;margin-bottom:14px}.head h1{margin:0 0 5px;font-size:27px}.head p{margin:0;color:var(--muted)}select,input,textarea{width:100%;border:1px solid var(--line);background:#0b1018;color:var(--text);border-radius:8px;padding:9px 10px;outline:none}textarea{min-height:88px;resize:vertical}.tabs{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:7px;margin:15px 0}.tab{min-height:48px;border:1px solid var(--line);border-radius:9px;background:#111722;color:#c7ccda;cursor:pointer;font-size:11px;font-weight:800;padding:8px}.tab.active{border-color:#806eef;background:#2a234a;color:#fff}.panel{border:1px solid var(--line);background:var(--panel);border-radius:12px;overflow:hidden}.panel-head{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line)}.panel-head h2{margin:0;font-size:17px}.state{font-size:10px;padding:5px 8px;border-radius:999px;border:1px solid #4e5a72;color:#aeb7c7}.state.on{border-color:#35624f;background:#14261f;color:#8ed8b7}.content{padding:15px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}.full{grid-column:1/-1}.card{border:1px solid #252e43;background:#0d121b;border-radius:10px;padding:12px}.card h3{margin:0 0 9px;font-size:13px}.field{display:grid;gap:5px;margin-bottom:9px}.field label{font-size:9px;color:var(--muted);font-weight:850;text-transform:uppercase;letter-spacing:.04em}.checks{display:flex;gap:9px;flex-wrap:wrap}.check{display:flex;gap:7px;align-items:center;border:1px solid #2b344a;border-radius:8px;padding:8px 10px;background:#111722}.check input{width:auto}.row{display:flex;gap:8px;align-items:end;flex-wrap:wrap}.row>.field{flex:1 1 180px}.list{display:grid;gap:7px}.item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;border:1px solid #252e43;border-radius:9px;padding:10px;background:#0d121b}.item b{display:block;font-size:11px}.item span{display:block;color:var(--muted);font-size:9px;margin-top:3px;line-height:1.4}.actions{display:flex;gap:5px;flex-wrap:wrap;justify-content:flex-end}.mini{padding:6px 8px;font-size:9px}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.metric{border:1px solid #283147;border-radius:9px;background:#0d121b;padding:11px}.metric b{display:block;font-size:19px}.metric span{font-size:9px;color:var(--muted)}.issue{padding:9px;border:1px solid #59462a;background:#211b10;border-radius:8px;color:#d9b96f;font-size:10px;margin-top:7px}.toast{position:fixed;right:18px;bottom:18px;max-width:360px;padding:11px 13px;border:1px solid #35624f;background:#14261f;border-radius:9px;color:#a6e5c8;z-index:50}.toast.bad{border-color:#6f3340;background:#2e171d;color:#ffb5c0}.hidden{display:none!important}.muted{color:var(--muted);font-size:10px}.switch{display:flex;align-items:center;gap:8px}.switch input{width:auto}.savebar{display:flex;justify-content:flex-end;margin-top:10px}.app-answer{margin-top:6px;padding:7px;border-left:2px solid #3b455f;color:#b8bfce;font-size:9px}.button-builder{display:grid;grid-template-columns:1fr 160px 1fr;gap:7px;margin-bottom:7px}@media(max-width:900px){.tabs{grid-template-columns:repeat(2,1fr)}.grid,.head{grid-template-columns:1fr}.full{grid-column:auto}.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.shell{padding:12px}.tabs,.metrics{grid-template-columns:1fr}.item{grid-template-columns:1fr}.actions{justify-content:flex-start}.button-builder{grid-template-columns:1fr}}
</style></head><body><header class="top"><div class="brand">SentriX — Centre des fonctions</div><a href="/app">Dashboard</a></header><main class="shell"><div class="head"><div><h1>Tout configurer depuis le site</h1><p>Aucune commande Discord nécessaire pour ces dix systèmes.</p></div><div class="field"><label>Serveur</label><select id="guild"></select></div></div><div id="tabs" class="tabs"></div><section class="panel"><div class="panel-head"><h2 id="title">Chargement...</h2><span id="stateBadge" class="state">—</span></div><div id="content" class="content"><div class="muted">Chargement...</div></div></section></main><div id="toast" class="toast hidden"></div><script>
const FEATURES=[
 ["automations","Automatisations"],["recruitment","Recrutements"],["temp_voice","Vocaux temporaires"],["surveillance","Surveillance"],["staff_planning","Planning staff"],["events","Événements"],["faq","FAQ / connaissances"],["health","Santé serveur"],["sticky_roles","Sticky Roles"],["panels","Panneaux"]
];
const state={csrf:"",guilds:[],guildId:"",data:null,feature:"automations"};const $=id=>document.getElementById(id);const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(url,opt={}){const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...opt});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||"Action impossible.");return d}function note(t,b=false){const x=$("toast");x.textContent=t;x.className=`toast${b?" bad":""}`;x.classList.remove("hidden");clearTimeout(note.t);note.t=setTimeout(()=>x.classList.add("hidden"),3500)}
function channelOptions(value="",kind="text"){return '<option value="">Non configuré</option>'+(state.data?.channels||[]).filter(c=>c.kind===kind).map(c=>`<option value="${c.id}" ${String(value)===String(c.id)?"selected":""}>${esc(c.name)}</option>`).join("")}
function roleOptions(value=""){return '<option value="">Non configuré</option>'+(state.data?.roles||[]).map(r=>`<option value="${r.id}" ${String(value)===String(r.id)?"selected":""}>${esc(r.name)}</option>`).join("")}
function featureConfig(){return state.data?.configs?.[state.feature]||{enabled:false}}
function enabledHeader(){const c=featureConfig();$("stateBadge").textContent=c.enabled?"ACTIF":"INACTIF";$("stateBadge").className=`state${c.enabled?" on":""}`}
function toggleBox(){const c=featureConfig();return `<label class="check"><input id="featureEnabled" type="checkbox" ${c.enabled?"checked":""}><span><b>Activer ce système</b><span class="muted">Le changement s'applique à ce serveur uniquement.</span></span></label>`}
function fieldsSave(extra=""){return `<div class="card full"><div class="checks">${toggleBox()}</div>${extra}<div class="savebar"><button class="btn primary" id="saveConfig">Enregistrer</button></div></div>`}
function items(kind){return (state.data?.items||[]).filter(x=>x.kind===kind)}
function itemList(kind,publish=false){const list=items(kind);return `<div class="card full"><h3>Éléments enregistrés</h3><div class="list">${list.length?list.map(i=>`<div class="item"><div><b>${esc(i.name)}</b><span>#${i.id} · ${i.enabled?"Actif":"Inactif"}</span></div><div class="actions">${publish?`<button class="btn mini" data-publish="${kind}" data-id="${i.id}">Publier</button>`:""}<button class="btn danger mini" data-delete="${i.id}">Supprimer</button></div></div>`).join(""):'<div class="muted">Aucun élément pour le moment.</div>'}</div></div>`}
function render(){enabledHeader();$("title").textContent=FEATURES.find(x=>x[0]===state.feature)?.[1]||state.feature;const c=featureConfig();let h="";
if(state.feature==="automations")h=`<div class="grid">${fieldsSave()}<div class="card"><h3>Nouvelle automatisation</h3><div class="field"><label>Nom</label><input id="aName" placeholder="Arrivée nouveau membre"></div><div class="field"><label>Déclencheur</label><select id="aTrigger"><option value="member_join">Membre rejoint</option><option value="member_leave">Membre quitte</option><option value="message_keyword">Mot-clé dans un message</option></select></div><div class="field"><label>Mot-clé (si nécessaire)</label><input id="aKeyword"></div></div><div class="card"><h3>Action</h3><div class="field"><label>Action</label><select id="aAction"><option value="send_channel">Envoyer un message</option><option value="dm">Envoyer un MP</option><option value="add_role">Ajouter un rôle</option><option value="remove_role">Retirer un rôle</option></select></div><div class="field"><label>Salon</label><select id="aChannel">${channelOptions()}</select></div><div class="field"><label>Rôle</label><select id="aRole">${roleOptions()}</select></div><div class="field"><label>Message</label><textarea id="aMessage" placeholder="Bienvenue {member}"></textarea></div><button class="btn primary" id="saveAutomation">Ajouter</button></div>${itemList("automation")}</div>`;
else if(state.feature==="recruitment")h=`<div class="grid">${fieldsSave(`<div class="row"><div class="field"><label>Salon de traitement</label><select id="rReview">${channelOptions(c.review_channel_id)}</select></div><div class="field"><label>Rôle attribué si accepté</label><select id="rRole">${roleOptions(c.accepted_role_id)}</select></div></div>`)}<div class="card"><h3>Créer un recrutement</h3><div class="field"><label>Nom</label><input id="rName" placeholder="Recrutement Modérateur"></div><div class="field"><label>Salon du panel</label><select id="rChannel">${channelOptions()}</select></div><div class="field"><label>Salon staff des réponses</label><select id="rItemReview">${channelOptions(c.review_channel_id)}</select></div><div class="field"><label>Description</label><textarea id="rDesc"></textarea></div><div class="field"><label>Questions — une par ligne, maximum 5</label><textarea id="rQuestions">Pourquoi voulez-vous rejoindre le staff ?\nQuelle est votre expérience ?</textarea></div><button class="btn primary" id="saveRecruitment">Créer</button></div><div class="card"><h3>Candidatures reçues</h3><div class="list">${(state.data.applications||[]).length?(state.data.applications||[]).map(a=>`<div class="item"><div><b>${esc(a.member_name)} · ${esc(a.status)}</b><span>#${a.id}</span>${(a.answers||[]).slice(0,2).map(x=>`<div class="app-answer"><b>${esc(x.question)}</b><br>${esc(x.answer)}</div>`).join("")}</div><div class="actions"><button class="btn mini" data-app="${a.id}" data-status="interview">Entretien</button><button class="btn primary mini" data-app="${a.id}" data-status="accepted">Accepter</button><button class="btn danger mini" data-app="${a.id}" data-status="refused">Refuser</button></div></div>`).join(""):'<div class="muted">Aucune candidature.</div>'}</div></div>${itemList("recruitment",true)}</div>`;
else if(state.feature==="temp_voice")h=`<div class="grid">${fieldsSave(`<div class="row"><div class="field"><label>Salon « Créer un vocal »</label><select id="vLobby">${channelOptions(c.lobby_channel_id,"voice")}</select></div><div class="field"><label>Catégorie de création</label><select id="vCategory">${channelOptions(c.category_id,"category")}</select></div><div class="field"><label>Limite par défaut</label><input id="vLimit" type="number" min="0" max="99" value="${esc(c.default_limit||0)}"></div></div><div class="field"><label>Nom du vocal</label><input id="vTemplate" value="${esc(c.name_template||"Vocal de {user}")}"><span class="muted">Variable : {user}</span></div>`)}</div>`;
else if(state.feature==="surveillance")h=`<div class="grid">${fieldsSave(`<div class="row"><div class="field"><label>Salon de surveillance</label><select id="sLog">${channelOptions(c.log_channel_id)}</select></div><label class="check"><input id="sContent" type="checkbox" ${c.include_message_content?"checked":""}>Inclure le contenu des messages</label></div>`)}<div class="card"><h3>Mettre un membre sous surveillance</h3><div class="field"><label>ID Discord</label><input id="sUser"></div><div class="field"><label>Niveau</label><select id="sLevel"><option value="low">Faible</option><option value="normal" selected>Normal</option><option value="high">Élevé</option></select></div><div class="field"><label>Raison</label><textarea id="sReason"></textarea></div><button class="btn primary" id="watchAdd">Ajouter</button></div><div class="card"><h3>Membres surveillés</h3><div class="list">${(state.data.watchlist||[]).length?state.data.watchlist.map(w=>`<div class="item"><div><b>${w.user_id} · ${esc(w.level)}</b><span>${esc(w.reason||"Aucune raison")}</span></div><button class="btn danger mini" data-unwatch="${w.user_id}">Retirer</button></div>`).join(""):'<div class="muted">Aucun membre surveillé.</div>'}</div></div></div>`;
else if(state.feature==="staff_planning")h=`<div class="grid">${fieldsSave()}<div class="card"><h3>Ajouter au planning</h3><div class="field"><label>Membre (ID)</label><input id="pUser"></div><div class="field"><label>Type</label><select id="pKind"><option value="availability">Disponibilité</option><option value="absence">Absence</option><option value="goal">Objectif</option></select></div><div class="row"><div class="field"><label>Début</label><input id="pStart" type="datetime-local"></div><div class="field"><label>Fin</label><input id="pEnd" type="datetime-local"></div></div><div class="field"><label>Note / objectif</label><textarea id="pNote"></textarea></div><button class="btn primary" id="saveShift">Ajouter</button></div>${itemList("staff_shift")}</div>`;
else if(state.feature==="events")h=`<div class="grid">${fieldsSave(`<div class="row"><div class="field"><label>Salon par défaut</label><select id="eDefaultChannel">${channelOptions(c.default_channel_id)}</select></div><div class="field"><label>Rappel par défaut (minutes)</label><input id="eDefaultReminder" type="number" min="0" max="10080" value="${esc(c.default_reminder_minutes??30)}"></div></div>`)}<div class="card"><h3>Créer un événement</h3><div class="field"><label>Titre</label><input id="eName"></div><div class="field"><label>Salon</label><select id="eChannel">${channelOptions(c.default_channel_id)}</select></div><div class="field"><label>Date et heure</label><input id="eStart" type="datetime-local"></div><div class="row"><div class="field"><label>Places max (0 = illimité)</label><input id="eMax" type="number" min="0" max="10000" value="0"></div><div class="field"><label>Rappel (minutes)</label><input id="eReminder" type="number" min="0" max="10080" value="${esc(c.default_reminder_minutes??30)}"></div></div><div class="field"><label>Description</label><textarea id="eDesc"></textarea></div><button class="btn primary" id="saveEvent">Créer</button></div>${itemList("event",true)}</div>`;
else if(state.feature==="faq")h=`<div class="grid">${fieldsSave(`<div class="row"><div class="field"><label>Salon FAQ</label><select id="fChannel">${channelOptions(c.channel_id)}</select></div><div class="field"><label>Correspondances minimum</label><input id="fScore" type="number" min="1" max="10" value="${esc(c.minimum_score||1)}"></div></div>`)}<div class="card"><h3>Ajouter une réponse</h3><div class="field"><label>Question / titre</label><input id="fName"></div><div class="field"><label>Mots-clés</label><input id="fKeywords" placeholder="nitro paiement abonnement"></div><div class="field"><label>Réponse</label><textarea id="fAnswer"></textarea></div><button class="btn primary" id="saveFaq">Ajouter</button></div>${itemList("faq")}</div>`;
else if(state.feature==="health"){const hlt=state.data.health||{};h=`<div class="grid">${fieldsSave()}<div class="metrics full"><div class="metric"><b>${hlt.latency_ms||0} ms</b><span>Latence</span></div><div class="metric"><b>${hlt.dangerous_admin_roles||0}</b><span>Rôles administrateur</span></div><div class="metric"><b>${hlt.admin_bots||0}</b><span>Bots administrateur</span></div><div class="metric"><b>${hlt.pending_applications||0}</b><span>Candidatures en attente</span></div></div><div class="card full"><h3>Problèmes détectés</h3>${(hlt.issues||[]).length?hlt.issues.map(x=>`<div class="issue">${esc(x)}</div>`).join(""):'<div class="muted">Aucun problème important détecté par les contrôles V37.</div>'}</div></div>`}
else if(state.feature==="sticky_roles")h=`<div class="grid">${fieldsSave(`<div class="field"><label>Rôles à ne jamais restaurer</label><select id="srExcluded" multiple size="8">${(state.data.roles||[]).map(r=>`<option value="${r.id}" ${(c.excluded_role_ids||[]).map(String).includes(String(r.id))?"selected":""}>${esc(r.name)}</option>`).join("")}</select></div>`)}</div>`;
else if(state.feature==="panels")h=`<div class="grid">${fieldsSave()}<div class="card full"><h3>Créer un panneau</h3><div class="row"><div class="field"><label>Titre</label><input id="pnName"></div><div class="field"><label>Salon</label><select id="pnChannel">${channelOptions()}</select></div></div><div class="field"><label>Description</label><textarea id="pnDesc"></textarea></div><h3>Boutons</h3>${[1,2,3].map(n=>`<div class="button-builder"><input id="pnLabel${n}" placeholder="Texte bouton ${n}"><select id="pnAction${n}"><option value="message">Réponse privée</option><option value="toggle_role">Ajouter/retirer un rôle</option><option value="add_role">Ajouter un rôle</option><option value="remove_role">Retirer un rôle</option><option value="link">Lien</option></select><select id="pnRole${n}">${roleOptions()}</select><input id="pnValue${n}" class="full" placeholder="Message privé ou URL https://..."></div>`).join("")}<button class="btn primary" id="savePanel">Créer le panneau</button></div>${itemList("panel",true)}</div>`;
$("content").innerHTML=h;bind()}
function chosen(id){const e=$(id);return e?[...e.selectedOptions].map(o=>o.value):[]}
async function saveConfig(){const f=state.feature,c=featureConfig(),data={...c};delete data.enabled;if(f==="recruitment")Object.assign(data,{review_channel_id:$("rReview").value,accepted_role_id:$("rRole").value});if(f==="temp_voice")Object.assign(data,{lobby_channel_id:$("vLobby").value,category_id:$("vCategory").value,default_limit:Number($("vLimit").value||0),name_template:$("vTemplate").value});if(f==="surveillance")Object.assign(data,{log_channel_id:$("sLog").value,include_message_content:$("sContent").checked});if(f==="events")Object.assign(data,{default_channel_id:$("eDefaultChannel").value,default_reminder_minutes:Number($("eDefaultReminder").value||30)});if(f==="faq")Object.assign(data,{channel_id:$("fChannel").value,minimum_score:Number($("fScore").value||1)});if(f==="sticky_roles")data.excluded_role_ids=chosen("srExcluded");const r=await api(`/api/guilds/${state.guildId}/feature-suite-v37/config`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({feature:f,enabled:$("featureEnabled").checked,data})});state.data.configs[f]=r.config;note(r.message);render()}
async function action(body){const r=await api(`/api/guilds/${state.guildId}/feature-suite-v37/action`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(body)});note(r.message||"Action effectuée.");await loadGuild(state.guildId);return r}
function bind(){$("saveConfig")?.addEventListener("click",()=>saveConfig().catch(e=>note(e.message,true)));$("saveAutomation")?.addEventListener("click",()=>action({action:"save_item",kind:"automation",name:$("aName").value,data:{trigger:$("aTrigger").value,keyword:$("aKeyword").value,action:$("aAction").value,channel_id:$("aChannel").value,role_id:$("aRole").value,message:$("aMessage").value}}).catch(e=>note(e.message,true)));$("saveRecruitment")?.addEventListener("click",()=>action({action:"save_item",kind:"recruitment",name:$("rName").value,data:{channel_id:$("rChannel").value,review_channel_id:$("rItemReview").value,description:$("rDesc").value,questions:$("rQuestions").value.split(/\n+/).map(x=>x.trim()).filter(Boolean).slice(0,5),button_label:"Postuler"}}).catch(e=>note(e.message,true)));$("watchAdd")?.addEventListener("click",()=>action({action:"watch_add",user_id:$("sUser").value,level:$("sLevel").value,reason:$("sReason").value}).catch(e=>note(e.message,true)));$("saveShift")?.addEventListener("click",()=>action({action:"save_item",kind:"staff_shift",name:`${$("pKind").value} · ${$("pUser").value}`,data:{user_id:$("pUser").value,kind:$("pKind").value,start_at:$("pStart").value?Math.floor(new Date($("pStart").value).getTime()/1000):0,end_at:$("pEnd").value?Math.floor(new Date($("pEnd").value).getTime()/1000):0,note:$("pNote").value}}).catch(e=>note(e.message,true)));$("saveEvent")?.addEventListener("click",()=>action({action:"save_item",kind:"event",name:$("eName").value,data:{channel_id:$("eChannel").value,starts_at:$("eStart").value?Math.floor(new Date($("eStart").value).getTime()/1000):0,max_participants:Number($("eMax").value||0),reminder_minutes:Number($("eReminder").value||30),description:$("eDesc").value,participants:[]}}).catch(e=>note(e.message,true)));$("saveFaq")?.addEventListener("click",()=>action({action:"save_item",kind:"faq",name:$("fName").value,data:{question:$("fName").value,keywords:$("fKeywords").value,answer:$("fAnswer").value}}).catch(e=>note(e.message,true)));$("savePanel")?.addEventListener("click",()=>{const buttons=[];for(let n=1;n<=3;n++){const label=$(`pnLabel${n}`).value.trim();if(!label)continue;const act=$(`pnAction${n}`).value,val=$(`pnValue${n}`).value;buttons.push({label,action:act,role_id:$(`pnRole${n}`).value,message:act==="link"?"":val,url:act==="link"?val:""})}action({action:"save_item",kind:"panel",name:$("pnName").value,data:{channel_id:$("pnChannel").value,description:$("pnDesc").value,buttons}}).catch(e=>note(e.message,true))});document.querySelectorAll("[data-delete]").forEach(b=>b.onclick=()=>action({action:"delete_item",item_id:b.dataset.delete}).catch(e=>note(e.message,true)));document.querySelectorAll("[data-publish]").forEach(b=>b.onclick=()=>action({action:`publish_${b.dataset.publish}`,item_id:b.dataset.id}).catch(e=>note(e.message,true)));document.querySelectorAll("[data-unwatch]").forEach(b=>b.onclick=()=>action({action:"watch_remove",user_id:b.dataset.unwatch}).catch(e=>note(e.message,true)));document.querySelectorAll("[data-app]").forEach(b=>b.onclick=()=>action({action:"application_status",application_id:b.dataset.app,status:b.dataset.status,note:""}).catch(e=>note(e.message,true)))}
async function loadGuild(id){if(!id)return;state.guildId=String(id);$("content").innerHTML='<div class="muted">Chargement...</div>';state.data=await api(`/api/guilds/${id}/feature-suite-v37`);render()}
function buildTabs(){$("tabs").innerHTML=FEATURES.map(([id,label])=>`<button class="tab ${id===state.feature?"active":""}" data-feature="${id}">${label}</button>`).join("");document.querySelectorAll("[data-feature]").forEach(b=>b.onclick=()=>{state.feature=b.dataset.feature;buildTabs();render()})}
async function boot(){try{const me=await api('/api/me');state.csrf=me.csrf;const gs=await api('/api/guilds');state.guilds=gs.guilds.filter(g=>g.installed);$("guild").innerHTML=state.guilds.map(g=>`<option value="${g.id}">${esc(g.name)}</option>`).join("");const requested=new URLSearchParams(location.search).get("guild");const first=state.guilds.find(g=>String(g.id)===String(requested))||state.guilds[0];if(first){$("guild").value=first.id;await loadGuild(first.id)}else note("Aucun serveur administrable avec SentriX.",true);buildTabs()}catch(e){note(e.message,true)}}$("guild").addEventListener("change",()=>loadGuild($("guild").value).catch(e=>note(e.message,true)));boot();
</script></body></html>'''
