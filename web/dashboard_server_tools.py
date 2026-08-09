"""Outils serveur directement dans le dashboard SentriX.

Expose deux opérations déjà disponibles côté bot sans dupliquer l'interface Discord :
- configuration d'un serveur à partir des modèles de +create-server ;
- wipe du serveur, strictement réservé au propriétaire réel Discord.

Les opérations longues sont exécutées en tâche de fond et suivies par polling pour éviter
qu'une requête HTTP reste ouverte pendant plusieurs minutes. Une seule opération destructive
peut être active à la fois par processus afin de garder le builder et les rate limits stables.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard.server-tools")
_INSTALLED = False


SERVER_TOOLS_CSS = r"""
<style id="sentrix-server-tools-css">
  #sentrixServerTools{margin:0 0 22px;border:1px solid #2b3150;border-radius:14px;background:linear-gradient(180deg,#111725,#0c1019);box-shadow:0 7px 0 #070910,0 22px 45px #0004;overflow:hidden}
  .sx-tools-head{padding:18px 20px;border-bottom:1px solid #252c43;background:linear-gradient(180deg,#161c2b,#111624)}
  .sx-tools-head h3{margin:0;font-size:18px;letter-spacing:-.02em}.sx-tools-head p{margin:6px 0 0;color:#929bb0;font-size:12px;line-height:1.55}
  .sx-tools-body{padding:18px 20px;display:grid;grid-template-columns:1fr 1fr;gap:14px}
  .sx-tool-card{border:1px solid #283149;border-radius:11px;background:linear-gradient(180deg,#121827,#0d121d);box-shadow:0 4px 0 #080b12;padding:17px;min-width:0}
  .sx-tool-card.danger{border-color:#55303c;background:linear-gradient(180deg,#1d141b,#120e13)}
  .sx-tool-card h4{margin:0 0 7px;font-size:14px}.sx-tool-card p{margin:0;color:#8f98ae;font-size:12px;line-height:1.55}
  .sx-tool-field{margin-top:14px}.sx-tool-field label{display:block;margin-bottom:6px;color:#aeb5c8;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.045em}
  .sx-tool-field select,.sx-tool-field input{width:100%;min-height:42px;border:1px solid #303952;border-radius:8px;background:#090e17;color:#eef0fa;padding:9px 11px;outline:none}
  .sx-tool-field select:focus,.sx-tool-field input:focus{border-color:#7769de;box-shadow:0 0 0 3px #7769de20}
  .sx-tool-meta{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:11px}.sx-tool-meta span{border:1px solid #262e44;border-radius:7px;background:#0a0f18;padding:7px;text-align:center;color:#9da6ba;font-size:10px}.sx-tool-meta b{display:block;color:#eef0fa;font-size:12px;margin-bottom:2px}
  .sx-tool-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.sx-tool-btn{min-height:39px;border:1px solid #3b4563;border-radius:8px;background:linear-gradient(180deg,#252e43,#171e2e);box-shadow:0 3px 0 #070910;color:#eef0fa;padding:9px 13px;font-weight:800;font-size:12px;cursor:pointer;transition:.12s}
  .sx-tool-btn:hover:not(:disabled){transform:translateY(-1px);border-color:#7569d5}.sx-tool-btn:active:not(:disabled){transform:translateY(2px);box-shadow:0 1px 0 #070910}.sx-tool-btn.primary{background:linear-gradient(180deg,#7768ed,#5848c9);border-color:#8e82f4}.sx-tool-btn.danger{background:linear-gradient(180deg,#5a2635,#391822);border-color:#804054}.sx-tool-btn:disabled{opacity:.42;cursor:not-allowed}
  .sx-tool-owner{margin-top:12px;padding:9px 10px;border:1px solid #3b344f;border-radius:8px;background:#14121d;color:#a9a1bf;font-size:11px;line-height:1.5}
  .sx-tool-job{grid-column:1/-1;border:1px solid #2a334a;border-radius:10px;background:#0a0f18;padding:13px 14px;display:none}.sx-tool-job.show{display:block}.sx-tool-job-top{display:flex;justify-content:space-between;gap:12px;align-items:center}.sx-tool-job b{font-size:12px}.sx-tool-job small{color:#8d96aa}.sx-tool-progress{height:5px;background:#1e2638;border-radius:99px;overflow:hidden;margin-top:10px}.sx-tool-progress i{display:block;height:100%;width:35%;background:#7768ed;border-radius:99px;animation:sxToolLoad 1.25s ease-in-out infinite alternate}.sx-tool-job.success .sx-tool-progress i{width:100%;animation:none}.sx-tool-job.error .sx-tool-progress i{width:100%;animation:none;background:#a94b62}@keyframes sxToolLoad{from{transform:translateX(-25%)}to{transform:translateX(215%)}}
  .sx-tool-result{margin-top:9px;color:#aeb6c8;font-size:11px;line-height:1.55;white-space:pre-wrap}
  .sx-wipe-dialog{border:1px solid #4e3440;border-radius:12px;background:#0d111b;color:#eef0fa;width:min(520px,calc(100vw - 28px));padding:0;box-shadow:0 30px 90px #000a}.sx-wipe-dialog::backdrop{background:#000a;backdrop-filter:blur(3px)}.sx-wipe-dialog header{padding:17px 19px;border-bottom:1px solid #2e2630}.sx-wipe-dialog header h3{margin:0;font-size:17px}.sx-wipe-dialog header p{margin:6px 0 0;color:#9c94a4;font-size:12px;line-height:1.55}.sx-wipe-dialog .body{padding:17px 19px}.sx-wipe-confirm{display:flex;align-items:flex-start;gap:8px;margin-top:12px;color:#aaa2ae;font-size:11px;line-height:1.45}.sx-wipe-confirm input{margin-top:2px}.sx-wipe-dialog footer{padding:0 19px 18px;display:flex;justify-content:flex-end;gap:8px}
  @media(max-width:850px){.sx-tools-body{grid-template-columns:1fr}.sx-tool-job{grid-column:auto}}
</style>
"""


SERVER_TOOLS_JS = r"""
<script id="sentrix-server-tools-js">
(() => {
  "use strict";
  if (window.__sentrixServerTools) return;
  window.__sentrixServerTools = true;

  let activeGuild = "";
  let info = null;
  let loading = false;
  let pollTimer = null;

  const esc = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

  function currentState(){
    try { return typeof state !== "undefined" ? state : null; }
    catch (_) { return null; }
  }

  async function apiCall(url, options={}){
    const response = await fetch(url, {credentials:"same-origin", cache:"no-store", ...options});
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(payload.error || `Erreur HTTP ${response.status}`);
    return payload;
  }

  function templateOptions(templates){
    return (templates || []).map(item => `<option value="${esc(item.key)}">${esc(item.label)}</option>`).join("");
  }

  function buildPanel(){
    const s = currentState();
    const host = document.getElementById("serverContent");
    if (!s || !host || !s.guildId || !s.guildData || host.classList.contains("hidden") || !info) return;

    let root = document.getElementById("sentrixServerTools");
    if (!root){
      root = document.createElement("section");
      root.id = "sentrixServerTools";
      const overview = document.getElementById("sentrixSafeOverview");
      if (overview && overview.parentNode === host) overview.insertAdjacentElement("afterend", root);
      else host.insertBefore(root, host.firstChild);
    }

    const first = (info.templates || [])[0] || null;
    root.innerHTML = `
      <div class="sx-tools-head">
        <h3>Outils serveur</h3>
        <p>Configurer la structure du serveur ou lancer un wipe sécurisé directement depuis le dashboard.</p>
      </div>
      <div class="sx-tools-body">
        <article class="sx-tool-card">
          <h4>Configurer le serveur</h4>
          <p>Utilise exactement le moteur de <code>+create-server</code>. Les éléments déjà présents sont réutilisés quand le modèle le permet.</p>
          <div class="sx-tool-field"><label>Modèle</label><select id="sxServerTemplate">${templateOptions(info.templates)}</select></div>
          <div class="sx-tool-meta" id="sxTemplateMeta"></div>
          <div class="sx-tool-actions"><button class="sx-tool-btn primary" id="sxCreateServer">Configurer avec ce modèle</button></div>
        </article>
        <article class="sx-tool-card danger">
          <h4>Wipe serveur</h4>
          <p>Supprime les salons, catégories et rôles que SentriX peut gérer. Une confirmation stricte du nom du serveur est obligatoire.</p>
          <div class="sx-tool-owner">${info.is_owner ? "Accès autorisé : tu es le propriétaire réel de ce serveur Discord." : "Accès verrouillé : seul le propriétaire réel du serveur Discord peut lancer un wipe."}</div>
          <div class="sx-tool-actions"><button class="sx-tool-btn danger" id="sxOpenWipe" ${info.is_owner ? "" : "disabled"}>Ouvrir la confirmation</button></div>
        </article>
        <div class="sx-tool-job" id="sxServerJob"><div class="sx-tool-job-top"><b id="sxJobTitle">Opération serveur</b><small id="sxJobState"></small></div><div class="sx-tool-progress"><i></i></div><div class="sx-tool-result" id="sxJobResult"></div></div>
      </div>
      <dialog class="sx-wipe-dialog" id="sxWipeDialog">
        <header><h3>Confirmation du wipe</h3><p>Cette opération est destructive. Recopie le nom exact du serveur pour débloquer le bouton final.</p></header>
        <div class="body">
          <div class="sx-tool-field"><label>Nom exact du serveur</label><input id="sxWipeGuildName" autocomplete="off" placeholder="${esc(info.guild_name)}"></div>
          <label class="sx-wipe-confirm"><input type="checkbox" id="sxWipeUnderstand"><span>Je comprends que les salons, catégories et rôles gérables seront supprimés et que l'opération ne peut pas être annulée depuis ce bouton.</span></label>
        </div>
        <footer><button class="sx-tool-btn" id="sxCancelWipe">Annuler</button><button class="sx-tool-btn danger" id="sxConfirmWipe" disabled>Lancer le wipe</button></footer>
      </dialog>`;

    const select = document.getElementById("sxServerTemplate");
    const renderMeta = () => {
      const item = (info.templates || []).find(t => t.key === select.value) || first;
      document.getElementById("sxTemplateMeta").innerHTML = item ? `<span><b>${esc(item.roles)}</b>rôles</span><span><b>${esc(item.categories)}</b>catégories</span><span><b>${esc(item.channels)}</b>salons</span>` : "";
    };
    select.onchange = renderMeta;
    renderMeta();

    document.getElementById("sxCreateServer").onclick = startCreate;
    const dialog = document.getElementById("sxWipeDialog");
    document.getElementById("sxOpenWipe").onclick = () => dialog.showModal();
    document.getElementById("sxCancelWipe").onclick = () => dialog.close();
    const nameInput = document.getElementById("sxWipeGuildName");
    const understand = document.getElementById("sxWipeUnderstand");
    const confirm = document.getElementById("sxConfirmWipe");
    const updateConfirm = () => { confirm.disabled = !(nameInput.value === info.guild_name && understand.checked); };
    nameInput.oninput = updateConfirm;
    understand.onchange = updateConfirm;
    confirm.onclick = startWipe;

    if (info.job && ["queued","running","success","error"].includes(info.job.status)) paintJob(info.job);
  }

  function paintJob(job){
    const box = document.getElementById("sxServerJob");
    if (!box) return;
    box.classList.add("show");
    box.classList.toggle("success", job.status === "success");
    box.classList.toggle("error", job.status === "error");
    document.getElementById("sxJobTitle").textContent = job.operation === "wipe" ? "Wipe serveur" : "Configuration du serveur";
    const labels = {queued:"En attente",running:"En cours",success:"Terminé",error:"Échec"};
    document.getElementById("sxJobState").textContent = labels[job.status] || job.status || "";
    const details = [];
    if (job.step) details.push(job.step);
    if (job.message) details.push(job.message);
    if (job.result?.description) details.push(job.result.description.replace(/\*\*/g, ""));
    document.getElementById("sxJobResult").textContent = details.filter(Boolean).join("\n");
  }

  async function startCreate(){
    const s = currentState();
    if (!s?.guildId || !info) return;
    const button = document.getElementById("sxCreateServer");
    const template = document.getElementById("sxServerTemplate").value;
    button.disabled = true;
    try{
      const result = await apiCall(`/api/guilds/${s.guildId}/server-tools/create`, {
        method:"POST",
        headers:{"Content-Type":"application/json","X-CSRF-Token":s.csrf},
        body:JSON.stringify({template})
      });
      paintJob(result.job);
      beginPolling();
    }catch(error){
      showLocalError("Configuration du serveur", error.message);
      button.disabled = false;
    }
  }

  async function startWipe(){
    const s = currentState();
    if (!s?.guildId || !info?.is_owner) return;
    const button = document.getElementById("sxConfirmWipe");
    const guildName = document.getElementById("sxWipeGuildName").value;
    button.disabled = true;
    try{
      const result = await apiCall(`/api/guilds/${s.guildId}/server-tools/wipe`, {
        method:"POST",
        headers:{"Content-Type":"application/json","X-CSRF-Token":s.csrf},
        body:JSON.stringify({guild_name:guildName})
      });
      document.getElementById("sxWipeDialog").close();
      paintJob(result.job);
      beginPolling();
    }catch(error){
      showLocalError("Wipe serveur", error.message);
      button.disabled = false;
    }
  }

  function showLocalError(title, text){
    const box = document.getElementById("sxServerJob");
    if (!box) return;
    paintJob({status:"error",operation:title.toLowerCase().includes("wipe")?"wipe":"create",message:text});
  }

  function beginPolling(){
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refreshJob, 1200);
    setTimeout(refreshJob, 200);
  }

  async function refreshJob(){
    const s = currentState();
    if (!s?.guildId) return;
    try{
      const data = await apiCall(`/api/guilds/${s.guildId}/server-tools/job`);
      if (data.job) paintJob(data.job);
      if (!data.job || ["success","error"].includes(data.job.status)){
        clearInterval(pollTimer); pollTimer = null;
        const create = document.getElementById("sxCreateServer");
        if (create) create.disabled = false;
        setTimeout(loadInfo, 500);
      }
    }catch(_){ }
  }

  async function loadInfo(){
    const s = currentState();
    const guildId = String(s?.guildId || "");
    const host = document.getElementById("serverContent");
    if (!guildId || !s?.guildData || !host || host.classList.contains("hidden")){
      activeGuild = ""; info = null;
      const old = document.getElementById("sentrixServerTools");
      if (old) old.remove();
      return;
    }
    if (loading) return;
    loading = true;
    try{
      const data = await apiCall(`/api/guilds/${guildId}/server-tools`);
      if (String(currentState()?.guildId || "") !== guildId) return;
      activeGuild = guildId;
      info = data;
      buildPanel();
      if (data.job && ["queued","running"].includes(data.job.status)) beginPolling();
    }catch(_){
      // Le dashboard principal affiche déjà les erreurs d'accès/session.
    }finally{ loading = false; }
  }

  setInterval(() => {
    const s = currentState();
    const guildId = String(s?.guildId || "");
    if (guildId && guildId !== activeGuild) loadInfo();
    else if (guildId && !document.getElementById("sentrixServerTools") && s?.guildData) loadInfo();
  }, 700);
  setTimeout(loadInfo, 350);
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-server-tools-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", SERVER_TOOLS_CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", SERVER_TOOLS_JS + "\n</body>", 1)
    return html


def _job_public(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {
        "status": job.get("status"),
        "operation": job.get("operation"),
        "step": job.get("step"),
        "message": job.get("message"),
        "result": job.get("result"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
    }


def _embed_result(embed: discord.Embed | None) -> dict[str, Any]:
    if embed is None:
        return {}
    return {
        "title": str(embed.title or ""),
        "description": str(embed.description or ""),
        "fields": [
            {"name": str(field.name), "value": str(field.value)}
            for field in list(embed.fields)[:12]
        ],
    }


async def _resolve_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(int(user_id))
    if member is not None:
        return member
    try:
        return await guild.fetch_member(int(user_id))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


def _pick_preserved_channel(guild: discord.Guild) -> discord.TextChannel | None:
    if isinstance(guild.system_channel, discord.TextChannel):
        return guild.system_channel
    for channel in sorted(guild.text_channels, key=lambda item: item.position):
        return channel
    return None


async def _perform_wipe(guild: discord.Guild, actor: discord.Member, job: dict[str, Any]) -> dict[str, Any]:
    me = guild.me
    if me is None:
        raise RuntimeError("SentriX n'est pas encore prêt sur ce serveur.")
    if not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
        raise RuntimeError("SentriX doit avoir Gérer les salons et Gérer les rôles pour lancer le wipe.")

    bot_role_ids = {role.id for role in me.roles}
    preserved = _pick_preserved_channel(guild)
    preserved_id = preserved.id if preserved is not None else None

    job["step"] = "Suppression des rôles gérables"
    roles_deleted = 0
    roles_failed = 0
    roles_protected = 0
    for role in reversed(guild.roles):
        if (
            role.is_default()
            or role.managed
            or role.id in bot_role_ids
            or role >= me.top_role
        ):
            roles_protected += 1
            continue
        try:
            await role.delete(reason=f"Wipe dashboard SentriX demandé par {actor} ({actor.id})")
            roles_deleted += 1
            await asyncio.sleep(0.25)
        except (discord.Forbidden, discord.HTTPException):
            roles_failed += 1

    job["step"] = "Suppression des salons et catégories"
    channels_deleted = 0
    channels_failed = 0
    # Les salons passent avant les catégories afin d'obtenir un résultat stable même si
    # Discord réordonne la liste pendant la suppression.
    channels = list(guild.channels)
    channels.sort(key=lambda channel: isinstance(channel, discord.CategoryChannel))
    for channel in channels:
        if preserved_id is not None and channel.id == preserved_id:
            continue
        try:
            await channel.delete(reason=f"Wipe dashboard SentriX demandé par {actor} ({actor.id})")
            channels_deleted += 1
            await asyncio.sleep(0.40)
        except (discord.Forbidden, discord.HTTPException):
            channels_failed += 1

    result = {
        "roles_deleted": roles_deleted,
        "roles_failed": roles_failed,
        "roles_protected": roles_protected,
        "channels_deleted": channels_deleted,
        "channels_failed": channels_failed,
        "preserved_channel": preserved.name if preserved is not None else None,
    }
    return result


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app["server_tool_jobs"] = {}
        app["server_tool_lock"] = asyncio.Lock()

        async def get_tools(request: web.Request):
            try:
                guild_id = int(request.match_info["guild_id"])
            except ValueError:
                return dashboard._json_error("Identifiant de serveur invalide.", 400)
            session, guild, error = await dashboard._manageable_guild(request, guild_id)
            if error:
                return error

            try:
                from cogs import server_builder as builder
            except Exception:
                logger.exception("Dashboard : import server_builder impossible.")
                return dashboard._json_error("Le module de configuration serveur n'est pas disponible.", 503)

            templates = []
            for key, data in builder.SERVER_TEMPLATES.items():
                categories = list(data.get("categories") or [])
                templates.append({
                    "key": str(key),
                    "label": str(data.get("label") or key),
                    "description": str(data.get("description") or ""),
                    "roles": len(data.get("roles") or []),
                    "categories": len(categories),
                    "channels": sum(len(item.get("channels") or []) for item in categories),
                })

            user_id = int(session["user"].get("id") or 0)
            job = app["server_tool_jobs"].get(guild_id)
            return web.json_response({
                "ok": True,
                "guild_name": guild.name,
                "guild_id": guild.id,
                "is_owner": user_id == int(guild.owner_id),
                "templates": templates,
                "job": _job_public(job),
            })

        async def get_job(request: web.Request):
            try:
                guild_id = int(request.match_info["guild_id"])
            except ValueError:
                return dashboard._json_error("Identifiant de serveur invalide.", 400)
            _session, _guild, error = await dashboard._manageable_guild(request, guild_id)
            if error:
                return error
            return web.json_response({"ok": True, "job": _job_public(app["server_tool_jobs"].get(guild_id))})

        async def post_create(request: web.Request):
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

            try:
                from cogs import server_builder as builder
            except Exception:
                logger.exception("Dashboard : import server_builder impossible.")
                return dashboard._json_error("Le module de configuration serveur n'est pas disponible.", 503)

            template_key = str(payload.get("template") or "").strip()
            if template_key not in builder.SERVER_TEMPLATES:
                return dashboard._json_error("Modèle de serveur invalide.", 400)
            existing = app["server_tool_jobs"].get(guild_id)
            if existing and existing.get("status") in {"queued", "running"}:
                return dashboard._json_error("Une opération serveur est déjà en cours.", 409)

            user_id = int(session["user"].get("id") or 0)
            actor = await _resolve_member(guild, user_id)
            if actor is None:
                return dashboard._json_error("Impossible de retrouver ton compte sur ce serveur.", 403)
            cog = bot.get_cog("ServerBuilder")
            if cog is None or not hasattr(cog, "build_server"):
                return dashboard._json_error("Le moteur +create-server n'est pas encore chargé.", 503)

            me = guild.me
            if me is None or not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
                return dashboard._json_error("SentriX doit avoir Gérer les salons et Gérer les rôles.", 403)

            job: dict[str, Any] = {
                "status": "queued",
                "operation": "create",
                "step": "Préparation du modèle",
                "message": None,
                "result": None,
                "started_at": int(time.time()),
                "finished_at": None,
            }
            app["server_tool_jobs"][guild_id] = job

            async def runner():
                async with app["server_tool_lock"]:
                    job["status"] = "running"
                    job["step"] = "Création et mise à jour de la structure"
                    try:
                        summary = await cog.build_server(guild, template_key, actor)
                        job["result"] = _embed_result(summary)
                        job["message"] = "Configuration terminée."
                        job["status"] = "success"
                    except Exception as exc:
                        logger.exception("Dashboard : create-server a échoué sur %s.", guild_id)
                        job["message"] = f"Configuration impossible : {type(exc).__name__}."
                        job["status"] = "error"
                    finally:
                        job["finished_at"] = int(time.time())

            asyncio.create_task(runner(), name=f"sentrix-dashboard-create-server-{guild_id}")
            return web.json_response({"ok": True, "job": _job_public(job)}, status=202)

        async def post_wipe(request: web.Request):
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

            user_id = int(session["user"].get("id") or 0)
            if user_id != int(guild.owner_id):
                return dashboard._json_error("Seul le propriétaire réel du serveur Discord peut lancer un wipe.", 403)
            try:
                payload = await request.json()
            except Exception:
                return dashboard._json_error("Requête invalide.", 400)
            typed_name = str(payload.get("guild_name") or "").strip()
            if typed_name != guild.name:
                return dashboard._json_error("Le nom du serveur ne correspond pas. Wipe annulé.", 400)

            existing = app["server_tool_jobs"].get(guild_id)
            if existing and existing.get("status") in {"queued", "running"}:
                return dashboard._json_error("Une opération serveur est déjà en cours.", 409)
            actor = await _resolve_member(guild, user_id)
            if actor is None:
                return dashboard._json_error("Impossible de retrouver le propriétaire sur le serveur.", 403)

            job: dict[str, Any] = {
                "status": "queued",
                "operation": "wipe",
                "step": "Préparation du wipe",
                "message": None,
                "result": None,
                "started_at": int(time.time()),
                "finished_at": None,
            }
            app["server_tool_jobs"][guild_id] = job

            async def runner():
                async with app["server_tool_lock"]:
                    job["status"] = "running"
                    try:
                        result = await _perform_wipe(guild, actor, job)
                        job["result"] = {
                            "title": "Wipe terminé",
                            "description": (
                                f"Salons et catégories supprimés : {result['channels_deleted']}\n"
                                f"Rôles supprimés : {result['roles_deleted']}\n"
                                f"Rôles protégés conservés : {result['roles_protected']}\n"
                                f"Échecs : {result['channels_failed'] + result['roles_failed']}\n"
                                f"Salon conservé : {result['preserved_channel'] or 'aucun'}"
                            ),
                            "fields": [],
                        }
                        job["message"] = "Wipe terminé."
                        job["status"] = "success"
                    except Exception as exc:
                        logger.exception("Dashboard : wipe a échoué sur %s.", guild_id)
                        job["message"] = f"Wipe impossible : {type(exc).__name__}."
                        job["status"] = "error"
                    finally:
                        job["finished_at"] = int(time.time())

            asyncio.create_task(runner(), name=f"sentrix-dashboard-wipe-{guild_id}")
            return web.json_response({"ok": True, "job": _job_public(job)}, status=202)

        app.router.add_get("/api/guilds/{guild_id}/server-tools", get_tools)
        app.router.add_get("/api/guilds/{guild_id}/server-tools/job", get_job)
        app.router.add_post("/api/guilds/{guild_id}/server-tools/create", post_create)
        app.router.add_post("/api/guilds/{guild_id}/server-tools/wipe", post_wipe)
        return app

    dashboard.build_app = build_app
    logger.info("Dashboard : outils create-server / wipe installés.")
