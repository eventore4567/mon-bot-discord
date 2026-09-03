"""Outils serveur directement dans le dashboard SentriX.

Expose la configuration d'un serveur à partir des modèles de +create-server, sans
dupliquer l'interface Discord.

Le wipe de serveur a été retiré de cette interface (aucun bouton, aucune confirmation,
aucune route HTTP) : c'est une opération destructive qui ne doit pouvoir être lancée que
depuis Discord lui-même (+wipe-server), jamais depuis un site web. Le moteur ci-dessous
(_perform_wipe) a été supprimé avec lui — il n'était utilisé que par cette interface et
+wipe-server garde sa propre implémentation dans son cog, intacte.

Les opérations longues sont exécutées en tâche de fond et suivies par polling pour éviter
qu'une requête HTTP reste ouverte pendant plusieurs minutes.
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
  /* Repliee par defaut : un outil ponctuel (configurer un serveur) ne doit pas
     occuper la place d'une section principale du dashboard. */
  #sentrixServerTools{margin:0 0 22px;border:1px solid #2b3150;border-radius:14px;background:linear-gradient(180deg,#111725,#0c1019);box-shadow:0 7px 0 #070910,0 18px 36px #0004;overflow:hidden}
  #sentrixServerTools>summary{list-style:none;cursor:pointer;padding:14px 18px;display:flex;align-items:center;gap:10px;user-select:none}
  #sentrixServerTools>summary::-webkit-details-marker{display:none}
  #sentrixServerTools>summary .sx-tools-chevron{transition:transform .15s ease;color:#8890a6;flex-shrink:0}
  #sentrixServerTools[open]>summary .sx-tools-chevron{transform:rotate(90deg)}
  #sentrixServerTools>summary .sx-tools-title{font-size:13px;font-weight:800;color:#eef0fa}
  #sentrixServerTools>summary .sx-tools-sub{font-size:11px;color:#8890a6;margin-left:auto}
  .sx-tools-body{padding:4px 18px 18px;display:grid;grid-template-columns:minmax(0,1fr);gap:14px;border-top:1px solid #1e2537}
  .sx-tool-card{border:1px solid #283149;border-radius:11px;background:linear-gradient(180deg,#121827,#0d121d);box-shadow:0 4px 0 #080b12;padding:17px;min-width:0;margin-top:14px}
  .sx-tool-card h4{margin:0 0 7px;font-size:14px}.sx-tool-card p{margin:0;color:#8f98ae;font-size:12px;line-height:1.55}
  .sx-tool-field{margin-top:14px}.sx-tool-field label{display:block;margin-bottom:6px;color:#aeb5c8;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.045em}
  .sx-tool-field select,.sx-tool-field input{width:100%;min-height:42px;border:1px solid #303952;border-radius:8px;background:#090e17;color:#eef0fa;padding:9px 11px;outline:none}
  .sx-tool-field select:focus,.sx-tool-field input:focus{border-color:#7769de;box-shadow:0 0 0 3px #7769de20}
  .sx-tool-meta{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:11px}.sx-tool-meta span{border:1px solid #262e44;border-radius:7px;background:#0a0f18;padding:7px;text-align:center;color:#9da6ba;font-size:10px}.sx-tool-meta b{display:block;color:#eef0fa;font-size:12px;margin-bottom:2px}
  .sx-tool-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.sx-tool-btn{min-height:39px;border:1px solid #3b4563;border-radius:8px;background:linear-gradient(180deg,#252e43,#171e2e);box-shadow:0 3px 0 #070910;color:#eef0fa;padding:9px 13px;font-weight:800;font-size:12px;cursor:pointer;transition:.12s}
  .sx-tool-btn:hover:not(:disabled){transform:translateY(-1px);border-color:#7569d5}.sx-tool-btn:active:not(:disabled){transform:translateY(2px);box-shadow:0 1px 0 #070910}.sx-tool-btn.primary{background:linear-gradient(180deg,#7768ed,#5848c9);border-color:#8e82f4}.sx-tool-btn:disabled{opacity:.42;cursor:not-allowed}
  .sx-tool-job{border:1px solid #2a334a;border-radius:10px;background:#0a0f18;padding:13px 14px;display:none;margin-top:14px}.sx-tool-job.show{display:block}.sx-tool-job-top{display:flex;justify-content:space-between;gap:12px;align-items:center}.sx-tool-job b{font-size:12px}.sx-tool-job small{color:#8d96aa}.sx-tool-progress{height:5px;background:#1e2638;border-radius:99px;overflow:hidden;margin-top:10px}.sx-tool-progress i{display:block;height:100%;width:35%;background:#7768ed;border-radius:99px;animation:sxToolLoad 1.25s ease-in-out infinite alternate}.sx-tool-job.success .sx-tool-progress i{width:100%;animation:none}.sx-tool-job.error .sx-tool-progress i{width:100%;animation:none;background:#a94b62}@keyframes sxToolLoad{from{transform:translateX(-25%)}to{transform:translateX(215%)}}
  .sx-tool-result{margin-top:9px;color:#aeb6c8;font-size:11px;line-height:1.55;white-space:pre-wrap}
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
      root = document.createElement("details");
      root.id = "sentrixServerTools";
      const overview = document.getElementById("sentrixSafeOverview");
      if (overview && overview.parentNode === host) overview.insertAdjacentElement("afterend", root);
      else host.insertBefore(root, host.firstChild);
    }

    const first = (info.templates || [])[0] || null;
    root.innerHTML = `
      <summary>
        <svg class="sx-tools-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M9 6l6 6-6 6"/></svg>
        <span class="sx-tools-title">Outils serveur</span>
        <span class="sx-tools-sub">Configurer la structure du serveur</span>
      </summary>
      <div class="sx-tools-body">
        <article class="sx-tool-card">
          <h4>Configurer le serveur</h4>
          <p>Utilise exactement le moteur de <code>+create-server</code>. Les éléments déjà présents sont réutilisés quand le modèle le permet.</p>
          <div class="sx-tool-field"><label>Modèle</label><select id="sxServerTemplate">${templateOptions(info.templates)}</select></div>
          <div class="sx-tool-meta" id="sxTemplateMeta"></div>
          <div class="sx-tool-actions"><button class="sx-tool-btn primary" id="sxCreateServer">Configurer avec ce modèle</button></div>
          <div class="sx-tool-job" id="sxServerJob"><div class="sx-tool-job-top"><b id="sxJobTitle">Configuration du serveur</b><small id="sxJobState"></small></div><div class="sx-tool-progress"><i></i></div><div class="sx-tool-result" id="sxJobResult"></div></div>
        </article>
      </div>`;

    const select = document.getElementById("sxServerTemplate");
    const renderMeta = () => {
      const item = (info.templates || []).find(t => t.key === select.value) || first;
      document.getElementById("sxTemplateMeta").innerHTML = item ? `<span><b>${esc(item.roles)}</b>rôles</span><span><b>${esc(item.categories)}</b>catégories</span><span><b>${esc(item.channels)}</b>salons</span>` : "";
    };
    select.onchange = renderMeta;
    renderMeta();

    document.getElementById("sxCreateServer").onclick = startCreate;

    if (info.job && ["queued","running","success","error"].includes(info.job.status)) paintJob(info.job);
  }

  function paintJob(job){
    const box = document.getElementById("sxServerJob");
    if (!box) return;
    box.classList.add("show");
    box.classList.toggle("success", job.status === "success");
    box.classList.toggle("error", job.status === "error");
    document.getElementById("sxJobTitle").textContent = "Configuration du serveur";
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

  function showLocalError(title, text){
    const box = document.getElementById("sxServerJob");
    if (!box) return;
    paintJob({status:"error",message:text});
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

        app.router.add_get("/api/guilds/{guild_id}/server-tools", get_tools)
        app.router.add_get("/api/guilds/{guild_id}/server-tools/job", get_job)
        app.router.add_post("/api/guilds/{guild_id}/server-tools/create", post_create)
        return app

    dashboard.build_app = build_app
    logger.info("Dashboard : outils create-server installés (wipe retiré du dashboard).")
