"""Advanced operational capabilities for the SentriX dashboard.

Completes the Ops Suite with role-based dashboard access tiers, filtered operational logs,
configuration previews and deeper live health checks.  The module is additive and must be
installed before aiohttp freezes the dashboard routes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from urllib.parse import urlencode

from aiohttp import ClientSession, ClientTimeout, web

logger = logging.getLogger("bot.dashboard.ops-suite-plus")
_INSTALLED = False

_TIER_RANK = {"viewer": 1, "operator": 2, "admin": 3}

PLUS_JS = r'''
<script id="sentrix-ops-suite-plus-js">
(() => {
  "use strict";
  if (window.__sentrixOpsSuitePlus) return;
  window.__sentrixOpsSuitePlus = true;
  const byId=id=>document.getElementById(id);
  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const S=()=>{try{return typeof state!=="undefined"?state:null}catch(_){return null}};
  const gid=()=>String(S()?.guildId||"");
  const csrf=()=>String(S()?.csrf||"");
  async function api(url,options={}){const headers={...(options.headers||{})};if(options.method&&options.method!=="GET")headers["X-CSRF-Token"]=csrf();if(options.body&&!headers["Content-Type"])headers["Content-Type"]="application/json";const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...options,headers});let d={};try{d=await r.json()}catch(_){}if(!r.ok)throw new Error(d.error||`Erreur HTTP ${r.status}`);return d}
  function currentOps(){try{return S()?.tab==="ops"}catch(_){return false}}
  async function refreshLogs(){const id=gid(),host=byId("sxPlusLogs");if(!id||!host)return;const kind=byId("sxPlusLogKind")?.value||"commands";const q=byId("sxPlusLogQuery")?.value||"";host.innerHTML='<div class="sx-ops-item"><small>Chargement…</small></div>';try{const data=await api(`/api/guilds/${encodeURIComponent(id)}/ops/logs?${new URLSearchParams({kind,q,limit:"80"})}`);host.innerHTML=(data.items||[]).map(item=>`<div class="sx-ops-item"><b>${esc(item.title||item.command_name||item.action||item.filter_name||"Événement")}</b><small>${esc(item.detail||item.reason||item.user_id||"")} · ${item.timestamp?new Date(Number(item.timestamp)*1000).toLocaleString("fr-FR"):""}</small></div>`).join("")||'<div class="sx-ops-item"><small>Aucun résultat.</small></div>'}catch(e){host.innerHTML=`<div class="sx-ops-item"><small>${esc(e.message)}</small></div>`}}
  async function previewImport(){const id=gid();if(!id)return;let config;try{config=JSON.parse(byId("sxConfigJson")?.value||"")}catch{return window.toast?.("JSON invalide.",true)}try{const data=await api(`/api/guilds/${encodeURIComponent(id)}/ops/preview`,{method:"POST",body:JSON.stringify(config)});const lines=(data.changes||[]).map(x=>`${x.section}.${x.key}: ${JSON.stringify(x.before)} → ${JSON.stringify(x.after)}`);byId("sxPlusPreview").textContent=lines.join("\n")||"Aucune modification détectée."}catch(e){window.toast?.(e.message,true)}}
  async function refreshHealth(){const id=gid(),host=byId("sxPlusHealth");if(!id||!host)return;try{const d=await api(`/api/guilds/${encodeURIComponent(id)}/ops/health`);const parts=[['Discord',d.discord?.ok,d.discord?.detail],['Base de données',d.database?.ok,d.database?.detail],['Redis',d.redis?.ok,d.redis?.detail],['Primary HA',d.primary?.ok,d.primary?.detail],['Standby HA',d.standby?.ok,d.standby?.detail]];host.innerHTML=parts.map(([n,ok,detail])=>`<div class="sx-ops-item"><b>${esc(n)}</b><small>${ok===true?'OK':ok===false?'Problème':'Inconnu'}${detail?` · ${esc(detail)}`:''}</small></div>`).join("")}catch(e){host.innerHTML=`<div class="sx-ops-item"><small>${esc(e.message)}</small></div>`}}
  async function refreshAccess(){const id=gid(),host=byId("sxPlusAccessList");if(!id||!host)return;try{const d=await api(`/api/guilds/${encodeURIComponent(id)}/ops/access`);host.innerHTML=(d.roles||[]).map(r=>`<div class="sx-ops-item"><b>${esc(r.role_name||r.role_id)}</b><small>${esc(r.tier)} · <button class="btn" data-sx-access-remove="${esc(r.role_id)}">Retirer</button></small></div>`).join("")||'<div class="sx-ops-item"><small>Aucun rôle supplémentaire.</small></div>';document.querySelectorAll('[data-sx-access-remove]').forEach(b=>b.addEventListener('click',()=>api(`/api/guilds/${encodeURIComponent(id)}/ops/access/${encodeURIComponent(b.dataset.sxAccessRemove)}`,{method:'DELETE',body:'{}'}).then(refreshAccess).catch(e=>window.toast?.(e.message,true))))}catch(e){host.innerHTML=`<div class="sx-ops-item"><small>${esc(e.message)}</small></div>`}}
  async function addAccess(){const id=gid(),role=byId("sxPlusAccessRole")?.value,tier=byId("sxPlusAccessTier")?.value;if(!id||!role)return window.toast?.("Choisis un rôle.",true);try{await api(`/api/guilds/${encodeURIComponent(id)}/ops/access`,{method:"POST",body:JSON.stringify({role_id:role,tier})});await refreshAccess()}catch(e){window.toast?.(e.message,true)}}
  function mount(){if(!currentOps())return;const root=document.querySelector('#fields .sx-ops-grid');if(!root||byId('sxOpsSuitePlus'))return;const roles=S()?.guildData?.roles||[];const section=document.createElement('section');section.id='sxOpsSuitePlus';section.className='sx-ops-card full';section.innerHTML=`<h3>Observabilité, prévisualisation et accès staff</h3><div class="sx-ops-grid" style="margin-top:10px">
    <div class="sx-ops-card"><h3>État avancé</h3><div id="sxPlusHealth" class="sx-ops-list"></div><div class="sx-ops-row"><button class="btn" id="sxPlusHealthRefresh">Actualiser</button></div></div>
    <div class="sx-ops-card"><h3>Accès dashboard par rôle</h3><select id="sxPlusAccessRole" class="sx-ops-select"><option value="">Choisir un rôle</option>${roles.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('')}</select><select id="sxPlusAccessTier" class="sx-ops-select"><option value="viewer">Lecture</option><option value="operator">Opérateur</option><option value="admin">Administrateur dashboard</option></select><div class="sx-ops-row"><button class="btn" id="sxPlusAccessAdd">Ajouter</button></div><div id="sxPlusAccessList" class="sx-ops-list"></div></div>
    <div class="sx-ops-card full"><h3>Logs filtrables</h3><div class="sx-ops-row"><select id="sxPlusLogKind" class="sx-ops-select" style="width:auto"><option value="commands">Commandes</option><option value="sanctions">Sanctions</option><option value="automod">AutoMod</option><option value="history">Dashboard</option></select><input id="sxPlusLogQuery" class="sx-ops-input" style="flex:1" placeholder="Utilisateur, commande, raison…"><button class="btn" id="sxPlusLogSearch">Rechercher</button></div><div id="sxPlusLogs" class="sx-ops-list"></div></div>
    <div class="sx-ops-card full"><h3>Prévisualisation avant import</h3><p>Valide le JSON et montre exactement les champs qui vont changer avant d'écrire en base.</p><div class="sx-ops-row"><button class="btn" id="sxPlusPreviewButton">Prévisualiser l'import</button></div><pre id="sxPlusPreview" style="white-space:pre-wrap;font-size:11px;color:var(--muted,#949db5)"></pre></div>
  </div>`;root.appendChild(section);byId('sxPlusHealthRefresh')?.addEventListener('click',refreshHealth);byId('sxPlusAccessAdd')?.addEventListener('click',addAccess);byId('sxPlusLogSearch')?.addEventListener('click',refreshLogs);byId('sxPlusLogKind')?.addEventListener('change',refreshLogs);byId('sxPlusPreviewButton')?.addEventListener('click',previewImport);refreshHealth();refreshAccess();refreshLogs()}
  const observer=new MutationObserver(()=>mount());const start=()=>{const f=byId('fields');if(f)observer.observe(f,{childList:true,subtree:true});document.addEventListener('click',e=>{if(e.target?.closest?.('[data-tab="ops"]'))setTimeout(mount,120)},true);setInterval(mount,600)};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
</script>
'''


async def _ensure_access_table(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_role_access (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            tier TEXT NOT NULL,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, role_id)
        )
    """)


async def _member(bot, guild, user_id: int):
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except Exception:
        return None


async def _effective_tier(bot, guild, user_id: int) -> str | None:
    member = await _member(bot, guild, user_id)
    if member is None:
        return None
    if guild.owner_id == user_id or member.guild_permissions.administrator:
        return "admin"
    await _ensure_access_table(bot.db)
    role_ids = [int(role.id) for role in member.roles]
    if not role_ids:
        return None
    placeholders = ",".join("?" for _ in role_ids)
    try:
        rows = await bot.db.fetchall(
            f"SELECT tier FROM sentrix_dashboard_role_access WHERE guild_id = ? AND role_id IN ({placeholders})",
            (guild.id, *role_ids),
        )
    except Exception:
        return None
    best = None
    for row in rows:
        tier = str(row["tier"] or "")
        if tier in _TIER_RANK and (best is None or _TIER_RANK[tier] > _TIER_RANK[best]):
            best = tier
    return best


def _write_allowed(tier: str | None, path: str, method: str) -> bool:
    if method in {"GET", "HEAD", "OPTIONS"}:
        return tier is not None
    if tier == "admin":
        return True
    if tier != "operator":
        return False
    return any(token in path for token in (
        "/sanctions/", "/ops/repair", "/ops/maintenance"
    ))


async def _log_items(db, guild_id: int, kind: str, query: str, limit: int) -> list[dict]:
    like = f"%{query}%"
    if kind == "sanctions":
        sql = "SELECT action AS title, reason AS detail, user_id, created_at AS timestamp FROM sanctions WHERE guild_id = ?"
        params: list = [guild_id]
        if query:
            sql += " AND (CAST(user_id AS TEXT) LIKE ? OR action LIKE ? OR COALESCE(reason,'') LIKE ?)"
            params += [like, like, like]
        sql += " ORDER BY id DESC LIMIT ?"
    elif kind == "automod":
        sql = "SELECT filter_name AS title, COALESCE(reason,action) AS detail, user_id, timestamp FROM automod_logs WHERE guild_id = ?"
        params = [guild_id]
        if query:
            sql += " AND (CAST(user_id AS TEXT) LIKE ? OR filter_name LIKE ? OR action LIKE ? OR COALESCE(reason,'') LIKE ?)"
            params += [like, like, like, like]
        sql += " ORDER BY id DESC LIMIT ?"
    elif kind == "history":
        sql = "SELECT username AS title, changed_json AS detail, user_id, created_at AS timestamp FROM sentrix_dashboard_history WHERE guild_id = ?"
        params = [guild_id]
        if query:
            sql += " AND (CAST(user_id AS TEXT) LIKE ? OR username LIKE ? OR changed_json LIKE ?)"
            params += [like, like, like]
        sql += " ORDER BY id DESC LIMIT ?"
    else:
        sql = "SELECT command_name AS title, CAST(user_id AS TEXT) AS detail, user_id, timestamp FROM command_logs WHERE guild_id = ?"
        params = [guild_id]
        if query:
            sql += " AND (CAST(user_id AS TEXT) LIKE ? OR command_name LIKE ?)"
            params += [like, like]
        sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    try:
        rows = await db.fetchall(sql, tuple(params))
        return [dict(row) for row in rows]
    except Exception:
        return []


async def _probe_url(url: str | None) -> dict:
    if not url:
        return {"ok": None, "detail": "non configuré"}
    target = url.rstrip("/") + "/health"
    try:
        async with ClientSession(timeout=ClientTimeout(total=1.5)) as session:
            async with session.get(target) as response:
                return {"ok": response.status == 200, "detail": f"HTTP {response.status}"}
    except Exception:
        return {"ok": False, "detail": "injoignable"}


def install(dashboard, ops) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-ops-suite-plus-js"' not in html:
        dashboard.INDEX_HTML = html.replace("</body>", PLUS_JS + "\n</body>", 1)

    original_manageable = dashboard._manageable_guild
    original_handle_guilds = dashboard.handle_guilds

    async def manageable_with_roles(request: web.Request, guild_id: int):
        session, error = dashboard._require_session(request)
        if error:
            return None, None, error
        guild = request.app["bot"].get_guild(guild_id)
        if guild is None:
            return session, None, dashboard._json_error("Serveur introuvable ou accès refusé.", 404)
        tier = await _effective_tier(request.app["bot"], guild, int(session["user"]["id"]))
        if tier is None:
            return session, None, dashboard._json_error("Serveur introuvable ou accès refusé.", 404)
        request["sentrix_dashboard_tier"] = tier
        return session, guild, None

    async def guilds_with_roles(request: web.Request):
        session, error = dashboard._require_session(request)
        if error:
            return error
        bot = request.app["bot"]
        user_id = int(session["user"]["id"])
        result = []
        seen = set()
        for guild in bot.guilds:
            tier = await _effective_tier(bot, guild, user_id)
            if tier is None:
                continue
            seen.add(guild.id)
            result.append({
                "id": str(guild.id), "name": guild.name,
                "icon_url": str(guild.icon.url) if guild.icon else None,
                "owner": guild.owner_id == user_id, "installed": True,
                "invite_url": None, "dashboard_tier": tier,
            })
        for item in session.get("guilds", []):
            gid = int(item["id"])
            if gid in seen or bot.get_guild(gid) is not None:
                continue
            result.append({**item, "installed": False, "invite_url": dashboard._invite_url(bot, gid), "dashboard_tier": "admin"})
        result.sort(key=lambda item: (not item["installed"], item["name"].casefold()))
        return web.json_response({"guilds": result})

    dashboard._manageable_guild = manageable_with_roles
    dashboard.handle_guilds = guilds_with_roles

    original_build = dashboard.build_app
    if not getattr(original_build, "_sentrix_ops_plus_routes", False):
        def build_app_with_plus(bot):
            app = original_build(bot)

            @web.middleware
            async def access_gate(request: web.Request, handler):
                if request.path.startswith("/api/guilds/"):
                    try:
                        guild_id = int(request.match_info.get("guild_id", "0"))
                    except (TypeError, ValueError):
                        guild_id = 0
                    if guild_id:
                        session, error = dashboard._require_session(request)
                        if error:
                            return error
                        guild = bot.get_guild(guild_id)
                        if guild is not None:
                            tier = await _effective_tier(bot, guild, int(session["user"]["id"]))
                            if tier is None:
                                return dashboard._json_error("Accès refusé.", 403)
                            request["sentrix_dashboard_tier"] = tier
                            if not _write_allowed(tier, request.path, request.method):
                                return dashboard._json_error("Ton niveau d'accès dashboard ne permet pas cette modification.", 403)
                return await handler(request)

            app.middlewares.append(access_gate)

            async def access_list(request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await manageable_with_roles(request, guild_id)
                if error:
                    return error
                tier = await _effective_tier(bot, guild, int(session["user"]["id"]))
                if tier != "admin":
                    return dashboard._json_error("Seuls les administrateurs dashboard peuvent gérer les accès.", 403)
                await _ensure_access_table(bot.db)
                rows = await bot.db.fetchall("SELECT role_id,tier,updated_by,updated_at FROM sentrix_dashboard_role_access WHERE guild_id = ? ORDER BY tier DESC, role_id", (guild_id,))
                roles = []
                for row in rows:
                    item = dict(row); role = guild.get_role(int(item["role_id"])); item["role_name"] = role.name if role else "Rôle supprimé"; roles.append(item)
                return web.json_response({"ok": True, "roles": roles, "tier": tier})

            async def access_set(request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await manageable_with_roles(request, guild_id)
                if error:
                    return error
                if await _effective_tier(bot, guild, int(session["user"]["id"])) != "admin":
                    return dashboard._json_error("Accès administrateur requis.", 403)
                csrf = dashboard._require_csrf(request, session)
                if csrf:
                    return csrf
                try:
                    payload = await request.json(); role_id = int(payload.get("role_id")); tier = str(payload.get("tier") or "viewer")
                except Exception:
                    return dashboard._json_error("Rôle ou niveau invalide.", 400)
                role = guild.get_role(role_id)
                if role is None or role.is_default() or role.managed:
                    return dashboard._json_error("Ce rôle ne peut pas recevoir un accès dashboard.", 400)
                if tier not in _TIER_RANK:
                    return dashboard._json_error("Niveau d'accès invalide.", 400)
                await _ensure_access_table(bot.db)
                await bot.db.execute("INSERT INTO sentrix_dashboard_role_access (guild_id,role_id,tier,updated_by,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(guild_id,role_id) DO UPDATE SET tier=excluded.tier,updated_by=excluded.updated_by,updated_at=excluded.updated_at", (guild_id, role_id, tier, int(session["user"]["id"]), int(time.time())))
                return web.json_response({"ok": True})

            async def access_delete(request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await manageable_with_roles(request, guild_id)
                if error:
                    return error
                if await _effective_tier(bot, guild, int(session["user"]["id"])) != "admin":
                    return dashboard._json_error("Accès administrateur requis.", 403)
                csrf = dashboard._require_csrf(request, session)
                if csrf:
                    return csrf
                try: role_id = int(request.match_info["role_id"])
                except ValueError: return dashboard._json_error("Rôle invalide.", 400)
                await _ensure_access_table(bot.db)
                await bot.db.execute("DELETE FROM sentrix_dashboard_role_access WHERE guild_id = ? AND role_id = ?", (guild_id, role_id))
                return web.json_response({"ok": True})

            async def logs(request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await manageable_with_roles(request, guild_id)
                if error:
                    return error
                kind = str(request.query.get("kind") or "commands").lower()
                if kind not in {"commands", "sanctions", "automod", "history"}:
                    return dashboard._json_error("Type de log invalide.", 400)
                q = str(request.query.get("q") or "").strip()[:100]
                try: limit = max(1, min(int(request.query.get("limit") or 80), 200))
                except ValueError: limit = 80
                return web.json_response({"ok": True, "items": await _log_items(bot.db, guild_id, kind, q, limit)})

            async def preview(request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await manageable_with_roles(request, guild_id)
                if error:
                    return error
                csrf = dashboard._require_csrf(request, session)
                if csrf:
                    return csrf
                try: payload = await request.json()
                except Exception: return dashboard._json_error("JSON invalide.", 400)
                settings = payload.get("settings") or {}; automod = payload.get("automod") or {}; ai = payload.get("ai") or {}
                clean_settings, msg = dashboard._validate_settings(guild, settings)
                if msg: return dashboard._json_error(msg, 400)
                clean_ai, msg = dashboard._validate_ai(ai)
                if msg: return dashboard._json_error(msg, 400)
                for key, value in automod.items():
                    if key not in dashboard.AUTOMOD_FIELDS or value not in (True, False, 0, 1):
                        return dashboard._json_error(f"Réglage AutoMod {key} invalide.", 400)
                current = await ops._snapshot(dashboard, bot.db, guild_id)
                changes = []
                for section, values in (("settings", clean_settings), ("automod", automod), ("ai", clean_ai)):
                    for key, value in values.items():
                        before = (current.get(section) or {}).get(key)
                        after = int(bool(value)) if section == "automod" else value
                        if before != after:
                            changes.append({"section": section, "key": key, "before": before, "after": after})
                return web.json_response({"ok": True, "changes": changes, "count": len(changes)})

            async def health(request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await manageable_with_roles(request, guild_id)
                if error:
                    return error
                database = {"ok": False, "detail": "indisponible"}
                try:
                    row = await bot.db.fetchone("SELECT 1 AS ok")
                    database = {"ok": bool(row), "detail": "SQLite/PostgreSQL bridge répond"}
                except Exception as exc:
                    database = {"ok": False, "detail": type(exc).__name__}
                redis = {"ok": None, "detail": "état non exposé"}
                redis_obj = next((getattr(bot, name, None) for name in ("redis", "_redis", "ha_redis") if getattr(bot, name, None) is not None), None)
                if redis_obj is not None and hasattr(redis_obj, "ping"):
                    try:
                        result = redis_obj.ping(); result = await result if asyncio.iscoroutine(result) else result
                        redis = {"ok": bool(result), "detail": "ping"}
                    except Exception as exc:
                        redis = {"ok": False, "detail": type(exc).__name__}
                elif os.getenv("REDIS_URL"):
                    redis = {"ok": None, "detail": "configuré, client non exposé"}
                primary_url = os.getenv("SENTRIX_HA_PRIMARY_INTERNAL_URL")
                standby_url = os.getenv("SENTRIX_HA_STANDBY_INTERNAL_URL")
                primary, standby = await asyncio.gather(_probe_url(primary_url), _probe_url(standby_url))
                return web.json_response({
                    "ok": True,
                    "discord": {"ok": bot.is_ready(), "detail": f"{round(bot.latency*1000)} ms" if bot.is_ready() else "non prêt"},
                    "database": database, "redis": redis, "primary": primary, "standby": standby,
                    "release": os.getenv("SENTRIX_RELEASE_SHA") or "", "role": os.getenv("SENTRIX_FAILOVER_ROLE") or "",
                })

            app.router.add_get("/api/guilds/{guild_id}/ops/access", access_list)
            app.router.add_post("/api/guilds/{guild_id}/ops/access", access_set)
            app.router.add_delete("/api/guilds/{guild_id}/ops/access/{role_id}", access_delete)
            app.router.add_get("/api/guilds/{guild_id}/ops/logs", logs)
            app.router.add_post("/api/guilds/{guild_id}/ops/preview", preview)
            app.router.add_get("/api/guilds/{guild_id}/ops/health", health)
            return app

        build_app_with_plus._sentrix_ops_plus_routes = True
        dashboard.build_app = build_app_with_plus

    _INSTALLED = True
    logger.info("SentriX dashboard Ops Suite Plus installed.")
    return True
