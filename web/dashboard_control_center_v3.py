"""SentriX dashboard Control Center V3.

Additive operational UX and backend routes.  It keeps the existing visual identity while adding
live health, alerts, incident aggregation, real permission simulation, per-module maintenance,
action feedback and cross-server configuration comparison.
"""
from __future__ import annotations

import time
from types import MethodType
from aiohttp import web

MODULES = ("tickets", "automod", "ai", "economy", "games", "notifications")


def _command_module(name: str) -> str | None:
    n = (name or "").strip().lower().replace("_", "-")
    root = n.split(" ", 1)[0]
    groups = {
        "tickets": ("ticket", "tickets", "claim", "close", "closeticket", "transcript"),
        "automod": ("automod", "anti-spam", "antispam", "anti-raid", "antiraid", "blacklist"),
        "ai": ("ai", "image", "imagine", "ask", "sentrix"),
        "economy": ("balance", "bal", "bank", "banque", "daily", "weekly", "work", "pay", "shop", "withdraw", "deposit"),
        "games": ("guess", "guessnumber", "crown", "crownrush", "game", "games"),
        "notifications": ("notif", "notifs", "notification", "notifications", "youtube", "tiktok", "twitch"),
    }
    for module, names in groups.items():
        if root in names or any(root.startswith(prefix + "-") for prefix in names):
            return module
    return None


async def _ensure_module_table(db) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS sentrix_dashboard_module_maintenance (
            guild_id INTEGER NOT NULL,
            module TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            updated_by INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, module)
        )
    """)


async def _module_states(db, guild_id: int) -> dict[str, dict]:
    await _ensure_module_table(db)
    rows = await db.fetchall(
        "SELECT module, enabled, reason, updated_by, updated_at FROM sentrix_dashboard_module_maintenance WHERE guild_id = ?",
        (guild_id,),
    )
    found = {str(row["module"]): dict(row) for row in rows}
    return {
        module: {
            "enabled": bool((found.get(module) or {}).get("enabled", 0)),
            "reason": str((found.get(module) or {}).get("reason") or ""),
            "updated_by": (found.get(module) or {}).get("updated_by"),
            "updated_at": int((found.get(module) or {}).get("updated_at") or 0),
        }
        for module in MODULES
    }


V3_JS = r'''
<script id="sentrix-control-center-v3-js">
(() => {
  "use strict";
  if (window.__sentrixControlCenterV3) return;
  window.__sentrixControlCenterV3 = true;
  const $=id=>document.getElementById(id), E=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const S=()=>{try{return typeof state!=="undefined"?state:null}catch(_){return null}}, gid=()=>String(S()?.guildId||""), csrf=()=>String(S()?.csrf||"");
  const queueItems=[]; let moduleState={};
  function queue(label,status="pending"){queueItems.unshift({label,status,at:Date.now()});queueItems.splice(20);renderQueue()}
  function renderQueue(){const h=$("sxV3Queue");if(!h)return;h.innerHTML=queueItems.map(x=>`<div class="sx-ops-item"><b>${E(x.label)}</b><small>${E(x.status)} · ${new Date(x.at).toLocaleTimeString("fr-FR")}</small></div>`).join("")||'<div class="sx-ops-item"><small>Aucune action récente.</small></div>'}
  async function api(path,opt={}){const h={...(opt.headers||{})};if(opt.method&&opt.method!=="GET")h["X-CSRF-Token"]=csrf();if(opt.body)h["Content-Type"]="application/json";const r=await fetch(path,{credentials:"same-origin",cache:"no-store",...opt,headers:h});let d={};try{d=await r.json()}catch(_){}if(!r.ok)throw new Error(d.error||`HTTP ${r.status}`);return d}
  async function health(){const id=gid(),h=$("sxV3Live");if(!id||!h)return;try{const d=await api(`/api/guilds/${id}/ops/health`);const rows=[["Discord",d.discord],["Base",d.database],["Redis",d.redis],["Primary",d.primary],["Standby",d.standby]];h.innerHTML=rows.map(([n,x])=>`<div class="sx-ops-item"><b>${n}</b><small>${x?.ok===true?'OK':x?.ok===false?'Incident':'Inconnu'} · ${E(x?.detail||'')}</small></div>`).join('');const bad=rows.filter(([,x])=>x?.ok===false);const a=$("sxV3Alerts");if(a)a.innerHTML=bad.length?bad.map(([n,x])=>`<div class="sx-ops-item"><b>${n}</b><small>${E(x?.detail||'Incident détecté')}</small></div>`).join(''):'<div class="sx-ops-item"><small>Aucune alerte critique.</small></div>'}catch(e){h.innerHTML=`<div class="sx-ops-item"><small>${E(e.message)}</small></div>`}}
  async function incidents(){const id=gid(),h=$("sxV3Incidents");if(!id||!h)return;try{const d=await api(`/api/guilds/${id}/ops/logs?kind=commands&limit=200`);const m=new Map;for(const x of d.items||[]){const k=x.title||'Événement';const v=m.get(k)||{n:0,last:0};v.n++;v.last=Math.max(v.last,Number(x.timestamp)||0);m.set(k,v)}h.innerHTML=[...m.entries()].sort((a,b)=>b[1].n-a[1].n).slice(0,12).map(([k,v])=>`<div class="sx-ops-item"><b>${E(k)}</b><small>${v.n} événement(s) · dernier ${v.last?new Date(v.last*1000).toLocaleString('fr-FR'):'inconnu'}</small></div>`).join('')||'<div class="sx-ops-item"><small>Aucun incident récent.</small></div>'}catch(e){h.innerHTML=`<div class="sx-ops-item"><small>${E(e.message)}</small></div>`}}
  async function simulate(){const id=gid(),member=$("sxV3Member")?.value.trim(),channel=$("sxV3Channel")?.value.trim(),out=$("sxV3Sim");if(!out)return;if(!member||!channel){out.textContent='Entre un ID membre et un ID salon.';return}queue('Simulation de permissions');try{const d=await api(`/api/guilds/${id}/ops/permissions/simulate?user_id=${encodeURIComponent(member)}&channel_id=${encodeURIComponent(channel)}`);const yes=(d.member?.allowed||[]).join(', ')||'aucune';const no=(d.member?.denied||[]).join(', ')||'aucune';const botNo=(d.bot?.denied||[]).join(', ')||'aucune';out.textContent=`Membre: autorisé [${yes}] · refusé [${no}] · SentriX manque [${botNo}]`;queue('Simulation de permissions','success')}catch(e){out.textContent=e.message;queue('Simulation de permissions','failed')}}
  function renderModules(){document.querySelectorAll('[data-v3-maint]').forEach(b=>{const x=moduleState[b.dataset.v3Maint]||{};b.textContent=`${b.dataset.v3Maint} · ${x.enabled?'ON':'OFF'}`;b.dataset.enabled=x.enabled?'1':'0';b.title=x.reason||''})}
  async function refreshModules(){const id=gid();if(!id)return;try{const d=await api(`/api/guilds/${id}/ops/maintenance/modules`);moduleState=d.modules||{};renderModules()}catch(_){}}
  async function maintenance(module){const id=gid(),enabled=!(moduleState[module]?.enabled);queue(`Maintenance ${module}`);try{const d=await api(`/api/guilds/${id}/ops/maintenance/modules`,{method:'POST',body:JSON.stringify({module,enabled,reason:`Maintenance ${module} depuis le dashboard`})});moduleState=d.modules||moduleState;renderModules();queue(`Maintenance ${module}`,'success');window.toast?.(`${module}: ${enabled?'maintenance activée':'maintenance désactivée'}`)}catch(e){queue(`Maintenance ${module}`,'failed');window.toast?.(e.message,true)}}
  async function compare(){const id=gid(),target=$("sxV3CompareTarget")?.value.trim(),out=$("sxV3Compare");if(!id||!target||!out)return;queue('Comparaison de configuration');try{const d=await api(`/api/guilds/${id}/ops/compare/${encodeURIComponent(target)}`);out.textContent=d.count?`${d.count} différence(s): ${(d.differences||[]).slice(0,30).map(x=>x.key).join(', ')}`:'Configurations principales identiques.';queue('Comparaison de configuration','success')}catch(e){out.textContent=e.message;queue('Comparaison de configuration','failed')}}
  function mount(){let root=document.querySelector('#fields .sx-ops-grid');if(!root||$("sxControlCenterV3"))return;const s=document.createElement('section');s.id='sxControlCenterV3';s.className='sx-ops-card full';s.innerHTML=`<h3>Centre de contrôle avancé</h3><div class="sx-ops-grid" style="margin-top:10px">
  <div class="sx-ops-card"><h3>Temps réel</h3><div id="sxV3Live" class="sx-ops-list"></div><div class="sx-ops-row"><button class="btn" id="sxV3Refresh">Actualiser</button></div></div>
  <div class="sx-ops-card"><h3>Alertes</h3><div id="sxV3Alerts" class="sx-ops-list"></div></div>
  <div class="sx-ops-card"><h3>Incidents regroupés</h3><div id="sxV3Incidents" class="sx-ops-list"></div></div>
  <div class="sx-ops-card"><h3>File d'actions</h3><div id="sxV3Queue" class="sx-ops-list"></div></div>
  <div class="sx-ops-card full"><h3>Maintenance par module</h3><div class="sx-ops-row">${['tickets','automod','ai','economy','games','notifications'].map(m=>`<button class="btn" data-v3-maint="${m}">${m}</button>`).join('')}</div><small>Chaque bouton coupe uniquement les commandes du module concerné. Les administrateurs Discord restent exemptés pour pouvoir réparer le serveur.</small></div>
  <div class="sx-ops-card"><h3>Simulateur de permissions</h3><input id="sxV3Member" class="sx-ops-input" placeholder="ID membre"><input id="sxV3Channel" class="sx-ops-input" placeholder="ID salon"><div class="sx-ops-row"><button class="btn" id="sxV3SimBtn">Simuler</button></div><small id="sxV3Sim"></small></div>
  <div class="sx-ops-card"><h3>Comparer deux serveurs</h3><input id="sxV3CompareTarget" class="sx-ops-input" placeholder="ID serveur cible"><div class="sx-ops-row"><button class="btn" id="sxV3CompareBtn">Comparer</button></div><small id="sxV3Compare"></small></div>
  </div>`;root.appendChild(s);$("sxV3Refresh")?.addEventListener('click',()=>{health();incidents();refreshModules()});$("sxV3SimBtn")?.addEventListener('click',simulate);$("sxV3CompareBtn")?.addEventListener('click',compare);document.querySelectorAll('[data-v3-maint]').forEach(b=>b.addEventListener('click',()=>maintenance(b.dataset.v3Maint)));health();incidents();refreshModules();renderQueue()}
  const start=()=>{new MutationObserver(mount).observe(document.body,{childList:true,subtree:true});document.addEventListener('click',e=>{if(e.target?.closest?.('[data-tab="ops"]'))setTimeout(mount,100)},true);setInterval(()=>{mount();if($("sxControlCenterV3")&&!document.hidden)health()},15000);mount()};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
</script>
'''


def _install_runtime_guard(bot) -> None:
    if getattr(bot, "_sentrix_module_maintenance_guard", False):
        return
    bot._sentrix_module_maintenance_guard = True
    cache: dict[int, tuple[float, dict[str, dict]]] = {}

    async def states(guild_id: int) -> dict[str, dict]:
        now = time.monotonic()
        item = cache.get(guild_id)
        if item and now - item[0] < 3:
            return item[1]
        try:
            value = await _module_states(bot.db, guild_id)
        except Exception:
            value = {module: {"enabled": False, "reason": ""} for module in MODULES}
        cache[guild_id] = (now, value)
        return value

    async def allowed(guild, member, command_name: str):
        if guild is None:
            return True, None
        if getattr(getattr(member, "guild_permissions", None), "administrator", False):
            return True, None
        module = _command_module(command_name)
        if not module:
            return True, None
        state = (await states(guild.id)).get(module) or {}
        if state.get("enabled"):
            return False, state.get("reason") or f"Le module {module} est temporairement en maintenance."
        return True, None

    async def prefix_check(ctx):
        command = getattr(ctx.command, "qualified_name", getattr(ctx.command, "name", ""))
        ok, message = await allowed(ctx.guild, ctx.author, command)
        if not ok:
            try:
                await ctx.send(message, delete_after=8)
            except Exception:
                pass
        return ok

    try:
        bot.add_check(prefix_check)
    except Exception:
        pass

    tree = getattr(bot, "tree", None)
    if tree is not None and not getattr(tree, "_sentrix_module_maintenance_guard", False):
        original = tree.interaction_check

        async def interaction_check(self, interaction):
            try:
                base = await original(interaction)
            except TypeError:
                base = await original(self, interaction)
            if base is False:
                return False
            command = getattr(interaction, "command", None)
            name = getattr(command, "qualified_name", getattr(command, "name", ""))
            ok, message = await allowed(interaction.guild, interaction.user, name)
            if not ok:
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(message, ephemeral=True)
                    else:
                        await interaction.response.send_message(message, ephemeral=True)
                except Exception:
                    pass
            return ok

        try:
            tree.interaction_check = MethodType(interaction_check, tree)
            tree._sentrix_module_maintenance_guard = True
        except Exception:
            pass


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-control-center-v3-js"' not in html:
        if "</body>" not in html:
            return False
        dashboard.INDEX_HTML = html.replace("</body>", V3_JS + "\n</body>", 1)

    original_build = dashboard.build_app
    if not getattr(original_build, "_sentrix_control_center_v3_routes", False):
        def build_app_v3(bot):
            app = original_build(bot)

            async def module_maintenance_get(request: web.Request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await dashboard._manageable_guild(request, guild_id)
                if error:
                    return error
                return web.json_response({"ok": True, "modules": await _module_states(bot.db, guild_id)})

            async def module_maintenance_post(request: web.Request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await dashboard._manageable_guild(request, guild_id)
                if error:
                    return error
                csrf_error = dashboard._require_csrf(request, session)
                if csrf_error:
                    return csrf_error
                try:
                    payload = await request.json()
                except Exception:
                    return dashboard._json_error("Formulaire invalide.", 400)
                module = str(payload.get("module") or "").strip().lower()
                if module not in MODULES:
                    return dashboard._json_error("Module invalide.", 400)
                enabled = 1 if payload.get("enabled") else 0
                reason = str(payload.get("reason") or f"Maintenance {module}").strip()[:180]
                await _ensure_module_table(bot.db)
                await bot.db.execute(
                    "INSERT INTO sentrix_dashboard_module_maintenance (guild_id,module,enabled,reason,updated_by,updated_at) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(guild_id,module) DO UPDATE SET enabled=excluded.enabled,reason=excluded.reason,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                    (guild_id, module, enabled, reason, int(session["user"]["id"]), int(time.time())),
                )
                return web.json_response({"ok": True, "modules": await _module_states(bot.db, guild_id)})

            async def permission_simulator(request: web.Request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await dashboard._manageable_guild(request, guild_id)
                if error:
                    return error
                try:
                    user_id = int(request.query.get("user_id") or 0)
                    channel_id = int(request.query.get("channel_id") or 0)
                except ValueError:
                    return dashboard._json_error("ID membre ou salon invalide.", 400)
                channel = guild.get_channel(channel_id)
                if channel is None:
                    return dashboard._json_error("Salon introuvable.", 404)
                member = guild.get_member(user_id)
                if member is None:
                    try:
                        member = await guild.fetch_member(user_id)
                    except Exception:
                        return dashboard._json_error("Membre introuvable.", 404)
                me = guild.me
                if me is None:
                    return dashboard._json_error("Impossible de résoudre les permissions de SentriX.", 503)
                important = (
                    "view_channel", "send_messages", "read_message_history", "embed_links", "attach_files",
                    "manage_messages", "manage_channels", "manage_roles", "moderate_members", "kick_members", "ban_members",
                    "connect", "speak", "move_members", "manage_webhooks",
                )
                def pack(perms):
                    allowed = [name for name in important if bool(getattr(perms, name, False))]
                    denied = [name for name in important if not bool(getattr(perms, name, False))]
                    return {"allowed": allowed, "denied": denied}
                return web.json_response({
                    "ok": True,
                    "member": {"id": str(member.id), "name": str(member), **pack(channel.permissions_for(member))},
                    "bot": {"id": str(me.id), "name": str(me), **pack(channel.permissions_for(me))},
                    "channel": {"id": str(channel.id), "name": getattr(channel, "name", str(channel.id))},
                })

            async def compare_configs(request: web.Request):
                guild_id = int(request.match_info["guild_id"])
                session, guild, error = await dashboard._manageable_guild(request, guild_id)
                if error:
                    return error
                try:
                    target_id = int(request.match_info["target_id"])
                except ValueError:
                    return dashboard._json_error("Serveur cible invalide.", 400)
                target = bot.get_guild(target_id)
                if target is None:
                    return dashboard._json_error("Serveur cible introuvable.", 404)
                user_id = int(session["user"]["id"])
                if await dashboard._administrator_member(target, user_id) is None:
                    return dashboard._json_error("Tu dois être administrateur du serveur cible pour le comparer.", 403)
                source = await bot.db.get_guild_config(guild_id)
                other = await bot.db.get_guild_config(target_id)
                a, b = (dict(source) if source else {}), (dict(other) if other else {})
                ignored = {"guild_id", "updated_at"}
                keys = sorted((set(a) | set(b)) - ignored)
                differences = [{"key": key, "source": a.get(key), "target": b.get(key)} for key in keys if a.get(key) != b.get(key)]
                return web.json_response({"ok": True, "count": len(differences), "differences": differences[:200]})

            app.router.add_get("/api/guilds/{guild_id}/ops/maintenance/modules", module_maintenance_get)
            app.router.add_post("/api/guilds/{guild_id}/ops/maintenance/modules", module_maintenance_post)
            app.router.add_get("/api/guilds/{guild_id}/ops/permissions/simulate", permission_simulator)
            app.router.add_get("/api/guilds/{guild_id}/ops/compare/{target_id}", compare_configs)
            _install_runtime_guard(bot)
            return app

        build_app_v3._sentrix_control_center_v3_routes = True
        dashboard.build_app = build_app_v3
    return True
