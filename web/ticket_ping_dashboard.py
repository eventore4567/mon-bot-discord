"""Dashboard : rôle à ping à l'ouverture, séparé du rôle staff du ticket."""

from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("bot.dashboard.ticket-ping")
_INSTALLED = False


async def _ensure_column(bot) -> None:
    rows = await bot.db.fetchall("PRAGMA table_info(ticket_types)")
    names = set()
    for row in rows:
        try:
            names.add(row["name"])
        except (KeyError, IndexError, TypeError):
            names.add(row[1])
    if "ping_role_id" not in names:
        await bot.db.execute("ALTER TABLE ticket_types ADD COLUMN ping_role_id INTEGER")


async def _context(request: web.Request, *, write: bool = False):
    dashboard = request.app["dashboard_module"]
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        return dashboard, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return dashboard, None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return dashboard, None, None, csrf_error
    return dashboard, session, guild, None


async def handle_ticket_ping_list(request: web.Request) -> web.Response:
    dashboard, _session, guild, error = await _context(request)
    if error:
        return error
    bot = request.app["bot"]
    await _ensure_column(bot)
    rows = await bot.db.fetchall(
        "SELECT tt.id, tt.name, tt.staff_role_id, tt.ping_role_id, tt.mention_staff, "
        "p.name AS panel_name FROM ticket_types tt "
        "LEFT JOIN ticket_panels_v2 p ON p.id = tt.panel_id "
        "WHERE tt.guild_id = ? ORDER BY p.id, tt.position, tt.id",
        (guild.id,),
    )
    items = []
    for row in rows:
        item = dict(row)
        explicit = item.get("ping_role_id")
        staff = item.get("staff_role_id")
        item["effective_role_id"] = explicit or staff
        item["using_staff_fallback"] = explicit is None and staff is not None
        items.append(item)
    return web.json_response({"ok": True, "types": items})


async def handle_ticket_ping_update(request: web.Request) -> web.Response:
    dashboard, session, guild, error = await _context(request, write=True)
    if error:
        return error
    bot = request.app["bot"]
    await _ensure_column(bot)
    try:
        type_id = int(request.match_info["type_id"])
        payload = await request.json()
    except (TypeError, ValueError):
        return dashboard._json_error("Type de ticket invalide.", 400)
    except Exception:
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

    row = await bot.db.fetchone(
        "SELECT id FROM ticket_types WHERE id = ? AND guild_id = ?",
        (type_id, guild.id),
    )
    if row is None:
        return dashboard._json_error("Ce type de ticket n'existe plus.", 404)

    enabled = payload.get("enabled")
    if enabled not in (True, False, 0, 1):
        return dashboard._json_error("L'activation du ping est invalide.", 400)

    role_id = payload.get("role_id")
    if role_id in (None, "", 0, "0"):
        role_id = None
    else:
        try:
            role_id = int(role_id)
        except (TypeError, ValueError):
            return dashboard._json_error("Le rôle choisi est invalide.", 400)
        role = guild.get_role(role_id)
        if role is None or role.is_default():
            return dashboard._json_error("Le rôle choisi n'existe plus ou ne peut pas être utilisé.", 400)

    await bot.db.execute(
        "UPDATE ticket_types SET ping_role_id = ?, mention_staff = ? WHERE id = ? AND guild_id = ?",
        (role_id, int(bool(enabled)), type_id, guild.id),
    )
    logger.info(
        "Dashboard : %s (%s) a modifié le rôle ping du type ticket #%s sur %s (%s).",
        session["user"]["username"], session["user"]["id"], type_id, guild.name, guild.id,
    )
    return web.json_response({
        "ok": True,
        "message": "Rôle à ping enregistré. Le prochain ticket utilisera ce réglage.",
    })


TICKET_PING_CSS = r"""
<style id="sentrix-ticket-ping-css">
  .ticket-ping-section{grid-column:1/-1;border-top:1px solid #242b42;padding-top:18px;margin-top:4px}
  .ticket-ping-head{margin-bottom:12px}.ticket-ping-head h3{margin:0 0 5px;font-size:16px}.ticket-ping-head p{margin:0;color:var(--muted);font-size:12px;line-height:1.5}
  .ticket-ping-list{display:grid;gap:10px}.ticket-ping-card{padding:14px;border:1px solid #252d45;background:#0d111c;border-radius:13px;display:grid;grid-template-columns:minmax(180px,1.1fr) minmax(220px,1fr) auto;gap:12px;align-items:center}
  .ticket-ping-name b,.ticket-ping-name span{display:block}.ticket-ping-name span{color:var(--muted);font-size:12px;margin-top:4px}
  .ticket-ping-toggle{display:flex;align-items:center;gap:8px;white-space:nowrap}.ticket-ping-toggle input{width:auto}
  .ticket-ping-empty{padding:18px;border:1px dashed #343c58;border-radius:12px;color:var(--muted);text-align:center}
  @media(max-width:850px){.ticket-ping-card{grid-template-columns:1fr}.ticket-ping-toggle{justify-content:flex-start}}
</style>
"""


TICKET_PING_JS = r"""
<script id="sentrix-ticket-ping-js">
(() => {
  "use strict";
  if (window.__sentrixTicketPingLoaded) return;
  window.__sentrixTicketPingLoaded = true;
  if (typeof state === "undefined" || typeof renderTab !== "function" || typeof json !== "function") return;

  function roleName(id) {
    if (!id || !state.guildData) return "Aucun rôle";
    const role = (state.guildData.roles || []).find(item => String(item.id) === String(id));
    return role ? `@${role.name}` : "Rôle supprimé";
  }

  function roleOptions(item) {
    const selected = item.ping_role_id == null ? "" : String(item.ping_role_id);
    let html = `<option value="" ${selected === "" ? "selected" : ""}>Utiliser le rôle staff du type</option>`;
    for (const role of (state.guildData.roles || [])) {
      html += `<option value="${esc(role.id)}" ${selected === String(role.id) ? "selected" : ""}>@${esc(role.name)}</option>`;
    }
    return html;
  }

  async function renderTicketPingSettings() {
    if (state.tab !== "tickets" || !state.guildId || !state.guildData) return;
    const guildId = String(state.guildId);
    const fields = document.getElementById("fields");
    if (!fields) return;
    fields.querySelectorAll(".ticket-ping-section").forEach(node => node.remove());
    const section = document.createElement("div");
    section.className = "field full ticket-ping-section";
    section.innerHTML = `<div class="ticket-ping-head"><h3>🔔 Rôle à ping à l'ouverture</h3><p>Choisissez le rôle mentionné pour chaque type de ticket. Ce rôle est indépendant du rôle staff qui possède l'accès au salon.</p></div><div class="ticket-ping-empty">Chargement des types de tickets…</div>`;
    fields.appendChild(section);

    try {
      const data = await json(`/api/guilds/${guildId}/ticket-ping`);
      if (state.tab !== "tickets" || String(state.guildId) !== guildId || !section.isConnected) return;
      const items = data.types || [];
      if (!items.length) {
        section.innerHTML = `<div class="ticket-ping-head"><h3>🔔 Rôle à ping à l'ouverture</h3><p>Créez d'abord un type avec +ticketsetup.</p></div><div class="ticket-ping-empty">Aucun type de ticket configuré.</div>`;
        return;
      }
      section.innerHTML = `<div class="ticket-ping-head"><h3>🔔 Rôle à ping à l'ouverture</h3><p>Un rôle différent peut être choisi pour chaque type. Laissez “rôle staff” pour conserver le comportement actuel.</p></div><div class="ticket-ping-list">${items.map(item => {
        const status = Number(item.mention_staff) ? "Ping activé" : "Ping désactivé";
        const current = item.effective_role_id ? roleName(item.effective_role_id) : "Aucun rôle défini";
        const source = item.using_staff_fallback ? " • rôle staff utilisé par défaut" : "";
        return `<div class="ticket-ping-card" data-ticket-type="${esc(item.id)}"><div class="ticket-ping-name"><b>${esc(item.name || "Ticket")}</b><span>${esc(item.panel_name || "Panel")} • ${esc(status)} • ${esc(current)}${esc(source)}</span></div><select class="select" data-ticket-ping-role>${roleOptions(item)}</select><label class="ticket-ping-toggle"><input type="checkbox" data-ticket-ping-enabled ${Number(item.mention_staff) ? "checked" : ""}> Activer le ping</label><button class="btn primary" type="button" data-ticket-ping-save>Enregistrer</button></div>`;
      }).join("")}</div>`;

      section.querySelectorAll("[data-ticket-ping-save]").forEach(button => {
        button.addEventListener("click", async () => {
          const card = button.closest("[data-ticket-type]");
          if (!card) return;
          const typeId = card.dataset.ticketType;
          const roleId = card.querySelector("[data-ticket-ping-role]").value || null;
          const enabled = card.querySelector("[data-ticket-ping-enabled]").checked;
          button.disabled = true;
          try {
            const result = await json(`/api/guilds/${guildId}/ticket-ping/${typeId}`, {
              method:"PUT",
              headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},
              body:JSON.stringify({role_id:roleId, enabled})
            });
            if (typeof toast === "function") toast(result.message);
            await renderTicketPingSettings();
          } catch (error) {
            if (typeof toast === "function") toast(error.message, true);
          } finally {
            button.disabled = false;
          }
        });
      });
    } catch (error) {
      if (!section.isConnected) return;
      section.innerHTML = `<div class="ticket-ping-head"><h3>🔔 Rôle à ping à l'ouverture</h3></div><div class="ticket-ping-empty">${esc(error.message || "Chargement impossible")}</div>`;
    }
  }

  const originalRenderTab = renderTab;
  renderTab = function sentrixTicketPingRenderTab() {
    originalRenderTab();
    if (state.tab === "tickets") setTimeout(renderTicketPingSettings, 0);
  };
})();
</script>
"""


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    html = dashboard.INDEX_HTML
    if 'id="sentrix-ticket-ping-css"' not in html:
        html = html.replace("</head>", f"{TICKET_PING_CSS}\n</head>", 1)
    if 'id="sentrix-ticket-ping-js"' not in html:
        html = html.replace("</body>", f"{TICKET_PING_JS}\n</body>", 1)
    dashboard.INDEX_HTML = html

    original_build_app = dashboard.build_app

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/api/guilds/{guild_id}/ticket-ping", handle_ticket_ping_list)
        app.router.add_put("/api/guilds/{guild_id}/ticket-ping/{type_id}", handle_ticket_ping_update)
        return app

    dashboard.build_app = build_app
    logger.info("Réglage du rôle ping des tickets chargé dans le dashboard.")
