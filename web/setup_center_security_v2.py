"""Panneau Security V2 du Centre Setup SentriX.

Ajoute un onglet autonome au Centre Setup : état anti-nuke, seuil propriétaire-only,
incidents récents et sauvegardes de sécurité. Il ne modifie pas le JavaScript du dashboard
principal et réutilise uniquement les primitives sûres du Centre Setup.
"""
from __future__ import annotations

import json
import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.security-v2")
_INSTALLED = False


SECURITY_CSS = r"""
<style id="sentrix-security-v2-setup-css">
  .sx-sec-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}
  .sx-sec-stat{padding:15px;border:1px solid #2c3550;border-radius:10px;background:linear-gradient(180deg,#141b29,#0d121d);box-shadow:0 4px 0 #080b12}
  .sx-sec-stat b{display:block;font-size:22px;margin-top:6px}.sx-sec-stat span{font-size:11px;color:#8f99b0;font-weight:800;text-transform:uppercase;letter-spacing:.04em}
  .sx-sec-two{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}
  .sx-sec-box{padding:18px;border:1px solid #2a334b;border-radius:11px;background:linear-gradient(180deg,#121827,#0d121d);box-shadow:0 4px 0 #080b12}
  .sx-sec-box h3{margin:0 0 7px;font-size:15px}.sx-sec-box p{margin:0 0 14px;color:#929bb1;font-size:12px;line-height:1.55}
  .sx-sec-line{display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid #222a3e;font-size:12px}.sx-sec-line:last-child{border-bottom:0}
  .sx-sec-good{color:#77dfb8}.sx-sec-warn{color:#f0bd68}.sx-sec-bad{color:#ff8399}.sx-sec-owner{padding:10px 12px;border:1px solid #403a72;background:#17152a;border-radius:9px;color:#b9b1ff;font-size:11px;line-height:1.5;margin-bottom:13px}
  .sx-sec-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}.sx-sec-fields{display:grid;grid-template-columns:1fr 1fr;gap:10px}.sx-sec-incident{padding:11px 0;border-bottom:1px solid #222a3e}.sx-sec-incident:last-child{border-bottom:0}.sx-sec-incident b{font-size:12px}.sx-sec-incident small{display:block;color:#8993aa;margin-top:4px;line-height:1.45}
  @media(max-width:900px){.sx-sec-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.sx-sec-two{grid-template-columns:1fr}}
  @media(max-width:560px){.sx-sec-grid{grid-template-columns:1fr 1fr}.sx-sec-fields{grid-template-columns:1fr}}
</style>
"""


SECURITY_JS = r"""
<script id="sentrix-security-v2-setup-js">
(() => {
  "use strict";
  if (window.__sentrixSecurityV2Setup) return;
  window.__sentrixSecurityV2Setup = true;

  let securityData = null;
  let securityGuild = "";

  function incidentHtml(item){
    const actor = item.actor_id ? `&lt;@${esc(item.actor_id)}&gt;` : "Inconnu";
    return `<div class="sx-sec-incident"><b>#${esc(item.id)} · ${actor}</b><small>${esc(item.reason || "Incident anti-nuke")} · ${esc(item.when || "")}</small></div>`;
  }

  window.renderSecurityV2 = async function renderSecurityV2(){
    const guildId = String(state.guildId || "");
    if (!guildId) return;
    $("title").textContent = "Sécurité V2";
    $("description").textContent = "Anti-nuke, incidents, rollback et sauvegardes automatiques.";
    $("content").innerHTML = '<div class="muted">Chargement de la sécurité…</div>';
    try{
      const data = await api(`/api/guilds/${guildId}/security-v2`);
      if (String(state.guildId) !== guildId || state.tab !== "security") return;
      securityData = data;
      securityGuild = guildId;
      paintSecurityV2();
    }catch(error){
      message(error.message || "Impossible de charger la sécurité V2.", true);
      $("content").innerHTML = '<div class="muted">Sécurité V2 indisponible pour le moment.</div>';
    }
  };

  function paintSecurityV2(){
    if (!securityData || securityGuild !== String(state.guildId) || state.tab !== "security") return;
    const d = securityData;
    const policy = d.policy || {};
    const incidents = d.incidents || [];
    const ownerNote = d.is_owner
      ? "Tu es le propriétaire du serveur : tu peux modifier le seuil anti-nuke."
      : "Le seuil anti-nuke est visible ici, mais seul le propriétaire réel du serveur Discord peut le modifier.";
    $("content").innerHTML = `
      <div class="sx-sec-grid">
        <div class="sx-sec-stat"><span>Anti-nuke</span><b class="${d.antinuke_enabled ? "sx-sec-good" : "sx-sec-bad"}">${d.antinuke_enabled ? "ON" : "OFF"}</b></div>
        <div class="sx-sec-stat"><span>Incidents 24h</span><b>${esc(d.incidents_24h || 0)}</b></div>
        <div class="sx-sec-stat"><span>Rollback 24h</span><b>${esc(d.rollback_events_24h || 0)}</b></div>
        <div class="sx-sec-stat"><span>Latence</span><b>${esc(d.latency_ms || 0)} ms</b></div>
      </div>
      <div class="sx-sec-two">
        <section class="sx-sec-box">
          <h3>Seuil anti-nuke</h3>
          <p>Nombre d'actions destructrices tolérées dans une fenêtre courte avant sanction + restauration.</p>
          <div class="sx-sec-owner">${esc(ownerNote)}</div>
          <div class="sx-sec-fields">
            <div class="field"><label>Actions</label><input id="sxNukeThreshold" type="number" min="2" max="15" value="${esc(policy.action_threshold || 3)}" ${d.is_owner ? "" : "disabled"}></div>
            <div class="field"><label>Fenêtre (secondes)</label><input id="sxNukeWindow" type="number" min="5" max="120" value="${esc(policy.window_seconds || 30)}" ${d.is_owner ? "" : "disabled"}></div>
          </div>
          <div class="sx-sec-actions">
            <button class="btn primary" id="sxSaveNuke" ${d.is_owner ? "" : "disabled"}>Enregistrer le seuil</button>
            <button class="btn" id="sxRefreshSecurity">Actualiser</button>
          </div>
          <div class="sx-sec-line"><span>Restauration rôles</span><b class="sx-sec-good">Active</b></div>
          <div class="sx-sec-line"><span>Restauration salons/bans</span><b class="sx-sec-good">Active</b></div>
          <div class="sx-sec-line"><span>Sauvegarde auto</span><b class="sx-sec-good">Toutes les 6 h</b></div>
        </section>
        <section class="sx-sec-box">
          <h3>Sauvegarde de sécurité</h3>
          <p>Les serveurs avec anti-nuke actif reçoivent automatiquement une sauvegarde structurelle avec rétention limitée.</p>
          <div class="sx-sec-line"><span>Dernière sauvegarde</span><b>${d.last_backup ? `#${esc(d.last_backup.id)} · ${esc(d.last_backup.when)}` : "Aucune"}</b></div>
          <div class="sx-sec-line"><span>Rétention auto</span><b>5 sauvegardes</b></div>
          <div class="sx-sec-actions"><button class="btn primary" id="sxBackupNow">Créer une sauvegarde maintenant</button></div>
          <h3 style="margin-top:18px">Incidents récents</h3>
          <div>${incidents.length ? incidents.map(incidentHtml).join("") : '<div class="muted">Aucun incident enregistré.</div>'}</div>
        </section>
      </div>`;

    $("sxRefreshSecurity").onclick = renderSecurityV2;
    $("sxSaveNuke").onclick = saveNukePolicy;
    $("sxBackupNow").onclick = backupNow;
  }

  async function saveNukePolicy(){
    if (!securityData?.is_owner) return;
    const threshold = Number($("sxNukeThreshold").value);
    const windowSeconds = Number($("sxNukeWindow").value);
    try{
      const result = await api(`/api/guilds/${state.guildId}/security-v2`, {
        method:"PUT",
        headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},
        body:JSON.stringify({action_threshold:threshold, window_seconds:windowSeconds})
      });
      securityData.policy = result.policy;
      message(result.message || "Seuil anti-nuke enregistré.");
      paintSecurityV2();
    }catch(error){ message(error.message || "Modification impossible.", true); }
  }

  async function backupNow(){
    try{
      const result = await api(`/api/guilds/${state.guildId}/security-v2/backup`, {
        method:"POST", headers:{"X-CSRF-Token":state.csrf}
      });
      message(result.message || "Sauvegarde créée.");
      await renderSecurityV2();
    }catch(error){ message(error.message || "Sauvegarde impossible.", true); }
  }
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-security-v2-setup-js"' in html:
        return html
    old_tab = '<button class="btn tab" data-tab="advanced">⚙️ Setup avancé</button></div>'
    new_tab = '<button class="btn tab" data-tab="advanced">⚙️ Setup avancé</button><button class="btn tab" data-tab="security">🛡️ Sécurité V2</button></div>'
    html = html.replace(old_tab, new_tab, 1)
    old_render = 'function render(){if(!state.guildId)return;if(state.tab==="systems")renderSystems();else if(state.tab==="games")renderGames();else if(state.tab==="design")renderDesign();else renderAdvanced();}'
    new_render = 'function render(){if(!state.guildId)return;if(state.tab==="systems")renderSystems();else if(state.tab==="games")renderGames();else if(state.tab==="design")renderDesign();else if(state.tab==="security")renderSecurityV2();else renderAdvanced();}'
    html = html.replace(old_render, new_render, 1)
    if "</head>" in html:
        html = html.replace("</head>", SECURITY_CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", SECURITY_JS + "\n</body>", 1)
    return html


async def _ensure_dashboard_tables(bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS antinuke_policy (
            guild_id INTEGER PRIMARY KEY,
            action_threshold INTEGER NOT NULL DEFAULT 3,
            window_seconds INTEGER NOT NULL DEFAULT 30,
            updated_by INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS security_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            actor_id INTEGER,
            reason TEXT NOT NULL,
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL
        )
        """
    )


def install(dashboard, setup_center) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    setup_center.SETUP_CENTER_HTML = _inject(setup_center.SETUP_CENTER_HTML)
    original_build_app = dashboard.build_app

    async def get_security_v2(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        bot = request.app["bot"]
        await _ensure_dashboard_tables(bot)
        policy_row = await bot.db.fetchone(
            "SELECT action_threshold, window_seconds FROM antinuke_policy WHERE guild_id = ?",
            (guild_id,),
        )
        policy = {
            "action_threshold": int(policy_row["action_threshold"]) if policy_row else 3,
            "window_seconds": int(policy_row["window_seconds"]) if policy_row else 30,
        }
        conf = await bot.db.get_automod(guild_id)
        now_ts = int(time.time())
        incident_rows = await bot.db.fetchall(
            "SELECT id, actor_id, reason, summary_json, created_at FROM security_incidents "
            "WHERE guild_id = ? ORDER BY id DESC LIMIT 8",
            (guild_id,),
        )
        incidents = []
        for row in incident_rows:
            incidents.append({
                "id": int(row["id"]),
                "actor_id": int(row["actor_id"] or 0),
                "reason": str(row["reason"] or ""),
                "when": f"<t:{int(row['created_at'])}:R>",
            })
        count_row = await bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM security_incidents WHERE guild_id = ? AND created_at >= ?",
            (guild_id, now_ts - 86400),
        )
        rollback_row = await bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM antinuke_rollback_actions WHERE guild_id = ? AND created_at >= ?",
            (guild_id, now_ts - 86400),
        )
        backup = await bot.db.fetchone(
            "SELECT id, created_at FROM server_backups WHERE guild_id = ? AND label LIKE 'Auto Anti-Nuke%' "
            "ORDER BY created_at DESC LIMIT 1",
            (guild_id,),
        )
        user_id = int(session["user"].get("id") or 0)
        return web.json_response({
            "ok": True,
            "policy": policy,
            "antinuke_enabled": bool(conf and conf["antinuke"]),
            "incidents_24h": int(count_row["n"] if count_row else 0),
            "rollback_events_24h": int(rollback_row["n"] if rollback_row else 0),
            "latency_ms": max(0, round(float(bot.latency or 0) * 1000)),
            "is_owner": user_id == int(guild.owner_id),
            "incidents": incidents,
            "last_backup": ({"id": int(backup["id"]), "when": f"<t:{int(backup['created_at'])}:R>"} if backup else None),
        })

    async def put_security_v2(request: web.Request):
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
        if int(session["user"].get("id") or 0) != int(guild.owner_id):
            return dashboard._json_error("Seul le propriétaire réel du serveur peut modifier le seuil anti-nuke.", 403)
        try:
            payload = await request.json()
            threshold = int(payload.get("action_threshold", 3))
            window_seconds = int(payload.get("window_seconds", 30))
        except Exception:
            return dashboard._json_error("Valeurs anti-nuke invalides.", 400)
        if not 2 <= threshold <= 15 or not 5 <= window_seconds <= 120:
            return dashboard._json_error("Limites : 2-15 actions et 5-120 secondes.", 400)
        bot = request.app["bot"]
        await _ensure_dashboard_tables(bot)
        await bot.db.execute(
            """
            INSERT INTO antinuke_policy (guild_id, action_threshold, window_seconds, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
              action_threshold=excluded.action_threshold,
              window_seconds=excluded.window_seconds,
              updated_by=excluded.updated_by,
              updated_at=excluded.updated_at
            """,
            (guild_id, threshold, window_seconds, int(session["user"]["id"]), int(time.time())),
        )
        return web.json_response({
            "ok": True,
            "policy": {"action_threshold": threshold, "window_seconds": window_seconds},
            "message": "Seuil anti-nuke mis à jour immédiatement.",
        })

    async def post_backup(request: web.Request):
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
        runtime = request.app["bot"].get_cog("SecurityV2Runtime")
        if runtime is None:
            return dashboard._json_error("Le moteur Security V2 n'est pas encore prêt.", 503)
        backup_id = await runtime.create_auto_backup(guild)
        return web.json_response({"ok": True, "backup_id": backup_id, "message": f"Sauvegarde #{backup_id} créée."})

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/security-v2", get_security_v2)
        app.router.add_put("/api/guilds/{guild_id}/security-v2", put_security_v2)
        app.router.add_post("/api/guilds/{guild_id}/security-v2/backup", post_backup)
        return app

    dashboard.build_app = build_app
    logger.info("Onglet Security V2 ajouté au Centre Setup.")
