"""Gestion propriétaire de tous les serveurs où SentriX est installé.

Cette page ne dépend pas des permissions du compte connecté dans chaque serveur : le
propriétaire du bot peut donc faire quitter SentriX d'un serveur même s'il n'en est plus
membre. Aucun outil de collecte de données personnelles n'est exposé ici.
"""
from __future__ import annotations

import logging

import discord
from aiohttp import web

from utils.owner_access import is_bot_owner_id

logger = logging.getLogger("bot.dashboard.owner-servers")
_INSTALLED = False


def _owner_session(request: web.Request, dashboard):
    session = dashboard._session(request)
    if session is None:
        return None
    if not is_bot_owner_id(session.get("user", {}).get("id")):
        return None
    return session


def _guild_payload(guild: discord.Guild) -> dict:
    owner = guild.owner
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon_url": str(guild.icon.url) if guild.icon else None,
        "members": int(guild.member_count or 0),
        "channels": len(guild.channels),
        "roles": len(guild.roles),
        "owner": str(owner) if owner else "Inconnu",
        "owner_id": str(guild.owner_id),
    }


OWNER_PAGE_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#090b12"><title>SentriX — Serveurs du bot</title>
<style>
:root{color-scheme:dark;--bg:#090b12;--panel:#111522;--panel2:#161b2b;--line:#2a3150;--text:#f4f5ff;--muted:#9ba5bf;--brand:#7c6cff;--danger:#e33f54}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#372c7055,transparent 34%),var(--bg);color:var(--text);font:15px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}main{width:min(1180px,calc(100% - 32px));margin:32px auto 70px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px}.top h1{margin:0;font-size:30px}.top p{margin:7px 0 0;color:var(--muted)}a{color:inherit}.back{padding:10px 14px;border:1px solid var(--line);background:var(--panel);border-radius:11px;text-decoration:none;font-weight:800}.toolbar{display:grid;grid-template-columns:1fr auto;gap:12px;padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:18px;margin-bottom:18px}.toolbar input{width:100%;padding:13px 15px;border:1px solid var(--line);border-radius:12px;background:#0d111d;color:var(--text);font:inherit;outline:none}.toolbar input:focus{border-color:var(--brand);box-shadow:0 0 0 3px #7c6cff22}.count{display:flex;align-items:center;padding:0 10px;color:var(--muted);font-weight:800}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(315px,1fr));gap:14px}.card{padding:17px;background:var(--panel);border:1px solid var(--line);border-radius:17px}.head{display:flex;gap:12px;align-items:center}.icon{width:48px;height:48px;border-radius:14px;background:#20263a;object-fit:cover;display:grid;place-items:center;font-size:18px;font-weight:900}.name{min-width:0}.name b{display:block;font-size:17px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.name span{display:block;color:var(--muted);font-size:12px;margin-top:3px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:14px 0}.stat{padding:9px;background:var(--panel2);border-radius:10px;text-align:center}.stat b{display:block}.stat small{color:var(--muted)}.owner{color:var(--muted);font-size:12px;line-height:1.5;margin:0 0 14px}.danger{width:100%;padding:11px 13px;border:1px solid #7b2734;border-radius:11px;background:#35151b;color:#ffb7c1;font-weight:900;cursor:pointer}.danger:hover{background:#491b24}.danger:disabled{opacity:.55;cursor:not-allowed}.empty{padding:40px;text-align:center;color:var(--muted);background:var(--panel);border:1px dashed var(--line);border-radius:16px;grid-column:1/-1}.toast{position:fixed;right:20px;bottom:20px;padding:13px 16px;background:#16241d;border:1px solid #2e6545;border-radius:12px;box-shadow:0 16px 50px #0008;display:none}.toast.bad{background:#32161c;border-color:#7b2734}@media(max-width:650px){main{width:min(100% - 20px,1180px);margin-top:18px}.top{align-items:flex-start;flex-direction:column}.toolbar{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}
</style>
</head>
<body><main>
<div class="top"><div><h1>Serveurs du bot</h1><p>Vue propriétaire — tous les serveurs où SentriX est actuellement présent.</p></div><a class="back" href="/app">Retour au dashboard</a></div>
<div class="toolbar"><input id="search" autocomplete="off" placeholder="Rechercher par nom ou ID du serveur…"><div class="count" id="count">Chargement…</div></div>
<div class="grid" id="grid"><div class="empty">Chargement des serveurs…</div></div>
</main><div class="toast" id="toast"></div>
<script>
const $=id=>document.getElementById(id);let allGuilds=[],csrf="";
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function toast(text,bad=false){const el=$("toast");el.textContent=text;el.classList.toggle("bad",bad);el.style.display="block";clearTimeout(window.__t);window.__t=setTimeout(()=>el.style.display="none",3500);}
async function json(url,options={}){const r=await fetch(url,options);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||`Erreur ${r.status}`);return d;}
function card(g){const icon=g.icon_url?`<img class="icon" src="${esc(g.icon_url)}" alt="">`:`<div class="icon">${esc(g.name.slice(0,2).toUpperCase())}</div>`;return `<article class="card" data-name="${esc(g.name.toLowerCase())}" data-id="${esc(g.id)}"><div class="head">${icon}<div class="name"><b>${esc(g.name)}</b><span>ID : ${esc(g.id)}</span></div></div><div class="stats"><div class="stat"><b>${Number(g.members).toLocaleString("fr-FR")}</b><small>Membres</small></div><div class="stat"><b>${g.channels}</b><small>Salons</small></div><div class="stat"><b>${g.roles}</b><small>Rôles</small></div></div><p class="owner">Propriétaire Discord : ${esc(g.owner)}<br>ID propriétaire : ${esc(g.owner_id)}</p><button class="danger" data-leave="${esc(g.id)}" data-server-name="${esc(g.name)}">Faire quitter SentriX</button></article>`;}
function render(){const q=$("search").value.trim().toLowerCase();const rows=!q?allGuilds:allGuilds.filter(g=>g.name.toLowerCase().includes(q)||g.id.includes(q));$("count").textContent=`${rows.length} / ${allGuilds.length} serveur(s)`;$("grid").innerHTML=rows.length?rows.map(card).join(""):'<div class="empty">Aucun serveur ne correspond à cette recherche.</div>';$("grid").querySelectorAll("[data-leave]").forEach(b=>b.addEventListener("click",()=>leaveGuild(b)));}
async function leaveGuild(button){const id=button.dataset.leave,name=button.dataset.serverName;if(!confirm(`Faire quitter SentriX du serveur « ${name} » ?\n\nCette action retire immédiatement le bot de ce serveur.`))return;button.disabled=true;button.textContent="Retrait en cours…";try{const d=await json(`/api/owner/guilds/${id}/leave`,{method:"POST",headers:{"X-CSRF-Token":csrf}});toast(d.message);allGuilds=allGuilds.filter(g=>g.id!==id);render();}catch(e){toast(e.message,true);button.disabled=false;button.textContent="Faire quitter SentriX";}}
async function boot(){try{const me=await json("/api/me");csrf=me.csrf;const d=await json("/api/owner/guilds");allGuilds=d.guilds||[];render();}catch(e){$("grid").innerHTML=`<div class="empty">${esc(e.message)}</div>`;$("count").textContent="Accès impossible";}}
$("search").addEventListener("input",render);$("search").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();render();const first=$("grid").querySelector(".card");if(first)first.scrollIntoView({behavior:"smooth",block:"center"});}});boot();
</script></body></html>"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard.build_app

    async def owner_status(request: web.Request):
        session = _owner_session(request, dashboard)
        if session is None:
            return dashboard._json_error("Introuvable.", 404)
        return web.json_response({"ok": True, "owner": True})

    async def owner_page(request: web.Request):
        session = _owner_session(request, dashboard)
        if session is None:
            if dashboard._session(request) is None:
                raise web.HTTPFound("/login")
            raise web.HTTPNotFound()
        return web.Response(text=OWNER_PAGE_HTML, content_type="text/html", headers={"Cache-Control": "private, no-store"})

    async def owner_guilds(request: web.Request):
        session = _owner_session(request, dashboard)
        if session is None:
            return dashboard._json_error("Introuvable.", 404)
        guilds = [_guild_payload(g) for g in request.app["bot"].guilds]
        guilds.sort(key=lambda g: g["name"].casefold())
        return web.json_response({"ok": True, "guilds": guilds, "total": len(guilds)})

    async def owner_leave(request: web.Request):
        session = _owner_session(request, dashboard)
        if session is None:
            return dashboard._json_error("Introuvable.", 404)
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        guild = request.app["bot"].get_guild(guild_id)
        if guild is None:
            return dashboard._json_error("SentriX n'est plus présent sur ce serveur.", 404)
        guild_name = guild.name
        try:
            await guild.leave()
        except discord.HTTPException:
            logger.exception("Impossible de faire quitter SentriX du serveur %s (%s).", guild_name, guild_id)
            return dashboard._json_error("Discord a refusé le retrait du bot. Réessayez dans un instant.", 502)
        logger.warning(
            "Dashboard propriétaire : %s (%s) a fait quitter SentriX de %s (%s).",
            session["user"].get("username"), session["user"].get("id"), guild_name, guild_id,
        )
        return web.json_response({"ok": True, "message": f"SentriX a quitté {guild_name}."})

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/owner-servers", owner_page)
        app.router.add_get("/api/owner/status", owner_status)
        app.router.add_get("/api/owner/guilds", owner_guilds)
        app.router.add_post("/api/owner/guilds/{guild_id}/leave", owner_leave)
        return app

    dashboard.build_app = build_app

    # Le bouton n'est injecté dans le dashboard que si l'API propriétaire confirme l'accès.
    owner_link_script = r'''<script>(async()=>{try{const r=await fetch("/api/owner/status");if(!r.ok)return;const d=await r.json();if(!d.owner)return;const a=document.createElement("a");a.href="/owner-servers";a.textContent="Serveurs du bot";a.style.cssText="display:inline-flex;align-items:center;justify-content:center;margin:8px 0;padding:10px 13px;border:1px solid #343b59;border-radius:10px;background:#171c2c;color:#f2f4ff;text-decoration:none;font-weight:800";const nav=document.getElementById("navigation");if(nav)nav.appendChild(a);else{a.style.position="fixed";a.style.right="18px";a.style.bottom="18px";a.style.zIndex="9999";document.body.appendChild(a)}}catch{}})();</script>'''
    if owner_link_script not in dashboard.INDEX_HTML:
        dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace("</body>", owner_link_script + "</body>", 1)

    logger.info("Gestionnaire propriétaire des serveurs du bot activé.")
