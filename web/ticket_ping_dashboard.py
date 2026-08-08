"""Réglage du rôle ping des tickets depuis le dashboard SentriX."""

from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard.ticket-ping-role")
_INSTALLED = False


async def _ensure_table(bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_ping_settings (
            guild_id INTEGER PRIMARY KEY,
            role_id INTEGER,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )


TICKET_PING_JS = r"""
<script id="sentrix-ticket-ping-dashboard">
(() => {
  "use strict";
  if (window.__sentrixTicketPingDashboard) return;
  window.__sentrixTicketPingDashboard = true;
  if (typeof state === "undefined" || typeof renderTab !== "function" || typeof json !== "function") return;

  async function renderTicketPingRole() {
    if (state.tab !== "tickets" || !state.guildId || !state.guildData) return;
    const fields = document.getElementById("fields");
    if (!fields || document.getElementById("ticketPingRoleField")) return;

    let data;
    try {
      data = await json(`/api/guilds/${state.guildId}/ticket-ping-role`);
    } catch (error) {
      if (typeof toast === "function") toast(error.message, true);
      return;
    }
    if (state.tab !== "tickets") return;

    const wrapper = document.createElement("div");
    wrapper.id = "ticketPingRoleField";
    wrapper.className = "field full";
    const current = String(data.role_id || "");
    const options = ['<option value="">Aucun rôle — ne rien ping</option>']
      .concat((state.guildData.roles || []).map(role =>
        `<option value="${esc(role.id)}" ${String(role.id)===current?"selected":""}>${esc(role.name)}</option>`
      )).join("");
    wrapper.innerHTML = `
      <label>🔔 Rôle à ping à l'ouverture d'un ticket</label>
      <select class="select" id="ticketPingRoleSelect">${options}</select>
      <div class="hint">Ce rôle est uniquement mentionné à l'ouverture. Il ne reçoit aucune permission supplémentaire dans le salon.</div>`;
    fields.insertBefore(wrapper, fields.firstChild);

    const select = document.getElementById("ticketPingRoleSelect");
    select.addEventListener("change", async () => {
      select.disabled = true;
      try {
        const result = await json(`/api/guilds/${state.guildId}/ticket-ping-role`, {
          method:"PUT",
          headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},
          body:JSON.stringify({role_id: select.value || null})
        });
        if (typeof toast === "function") toast(result.message);
      } catch (error) {
        if (typeof toast === "function") toast(error.message, true);
        await renderTicketPingRole();
      } finally {
        select.disabled = false;
      }
    });
  }

  const originalRenderTab = renderTab;
  renderTab = function sentrixTicketPingRenderTab() {
    const result = originalRenderTab();
    if (state.tab === "tickets") setTimeout(renderTicketPingRole, 0);
    return result;
  };

  const originalSelectGuild = selectGuild;
  selectGuild = async function sentrixTicketPingSelectGuild(value) {
    const result = await originalSelectGuild(value);
    if (state.tab === "tickets") setTimeout(renderTicketPingRole, 0);
    return result;
  };
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_build_app = dashboard.build_app

    async def get_ping_role(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError:
            return dashboard._json_error("Identifiant de serveur invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        await _ensure_table(request.app["bot"])
        row = await request.app["bot"].db.fetchone(
            "SELECT role_id FROM ticket_ping_settings WHERE guild_id = ?",
            (guild_id,),
        )
        role_id = int(row["role_id"]) if row and row["role_id"] else None
        if role_id and guild.get_role(role_id) is None:
            role_id = None
        return web.json_response({"ok": True, "role_id": str(role_id) if role_id else None})

    async def put_ping_role(request: web.Request):
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
            return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

        raw = payload.get("role_id")
        role_id = None
        if raw not in (None, "", 0, "0"):
            try:
                role_id = int(raw)
            except (TypeError, ValueError):
                return dashboard._json_error("Le rôle choisi est invalide.", 400)
            role = guild.get_role(role_id)
            if role is None or role.is_default() or role.managed:
                return dashboard._json_error("Ce rôle n'existe plus ou ne peut pas être utilisé.", 400)

        from database.db import now
        await _ensure_table(request.app["bot"])
        await request.app["bot"].db.execute(
            """
            INSERT INTO ticket_ping_settings (guild_id, role_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                role_id = excluded.role_id,
                updated_at = excluded.updated_at
            """,
            (guild_id, role_id, now()),
        )
        logger.info(
            "Dashboard : %s (%s) a défini le rôle ping tickets sur %s pour %s (%s).",
            session["user"].get("username"), session["user"].get("id"), role_id, guild.name, guild.id,
        )
        message = "Rôle de ping des tickets retiré." if role_id is None else "Rôle de ping des tickets enregistré."
        return web.json_response({"ok": True, "message": message, "role_id": str(role_id) if role_id else None})

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/ticket-ping-role", get_ping_role)
        app.router.add_put("/api/guilds/{guild_id}/ticket-ping-role", put_ping_role)
        return app

    dashboard.build_app = build_app
    if 'id="sentrix-ticket-ping-dashboard"' not in dashboard.INDEX_HTML:
        dashboard.INDEX_HTML = dashboard.INDEX_HTML.replace("</body>", TICKET_PING_JS + "\n</body>", 1)

    logger.info("Réglage du rôle ping tickets ajouté au dashboard.")
