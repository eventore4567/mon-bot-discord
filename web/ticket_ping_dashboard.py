"""Configuration guidée Tickets du dashboard SentriX.

Cette couche conserve l'API historique du rôle de ping, puis transforme l'éditeur de
panels V35 en parcours clair : Général -> Équipe -> Panel -> Publication. Elle ajoute
aussi une publication fiable dans un salon Discord sans recréer les panels ni toucher
aux tickets/transcripts existants.
"""

from __future__ import annotations

import logging

import discord
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


TICKET_WIZARD_CSS = r"""
<style id="sentrix-ticket-wizard-v2-css">
.sx-ticket-wizard-v2{display:grid;gap:9px;padding:0 0 2px}
.sx-ticket-wizard-nav{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;padding:5px;border:1px solid #293348;border-radius:11px;background:#0c121b}
.sx-ticket-wizard-nav button{min-height:36px;border:1px solid transparent;border-radius:8px;background:transparent;color:#7f899b;font-size:9px;font-weight:850;cursor:pointer;white-space:nowrap}
.sx-ticket-wizard-nav button.active{border-color:#6653bd;background:#241d40;color:#ded5ff}
.sx-ticket-wizard-nav button.done:not(.active){color:#9fb2a8}
.sx-ticket-wizard-help{padding:9px 11px;border:1px solid #283247;border-radius:9px;background:#101722;color:#929db0;font-size:9px;line-height:1.5}
.sx-ticket-publication-v2{border:1px solid #273044;border-radius:11px;background:#0f151f;padding:12px;display:grid;gap:11px}
.sx-ticket-publication-v2 h5{margin:0;color:#e9e6ee;font-size:11px}.sx-ticket-publication-v2 p{margin:3px 0 0;color:#8490a3;font-size:9px;line-height:1.45}
.sx-ticket-publish-grid{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:end}
.sx-ticket-publish-grid label{display:block;margin-bottom:5px;color:#b9c1cf;font-size:10px;font-weight:800}
.sx-ticket-publish-grid select{width:100%;box-sizing:border-box;background:#111824;color:#eae8ef;border:1px solid #2c3548;border-radius:9px;padding:9px 10px;font-size:10px}
.sx-ticket-publish-grid button{min-height:36px;padding:0 13px;border:1px solid #725bd0;border-radius:9px;background:#6f57d4;color:#fff;font-size:10px;font-weight:850;cursor:pointer}
.sx-ticket-publish-grid button:disabled{opacity:.55;cursor:wait}
.sx-ticket-publish-status{padding:8px 10px;border:1px solid #2a3448;border-radius:8px;background:#0d141e;color:#929daf;font-size:9px;line-height:1.45}
.sx-ticket-publish-status.ok{border-color:#315645;color:#8dd1ae}.sx-ticket-publish-status.bad{border-color:#64343b;color:#e99da6}
.sx-ticket-team-advanced{border:1px solid #273044;border-radius:9px;background:#0d141e}.sx-ticket-team-advanced>summary{cursor:pointer;list-style:none;padding:9px 10px;color:#8f9aab;font-size:9px;font-weight:800}.sx-ticket-team-advanced>summary::-webkit-details-marker{display:none}.sx-ticket-team-advanced>div{padding:0 10px 10px;display:grid;gap:6px}.sx-ticket-team-advanced label{color:#b8c0ce;font-size:9px;font-weight:800}.sx-ticket-team-advanced select{width:100%;box-sizing:border-box;background:#111824;color:#eae8ef;border:1px solid #2c3548;border-radius:8px;padding:8px 9px;font-size:10px}
.sx-ticket-team-hint{color:#778397;font-size:8px;line-height:1.4}
@media(max-width:680px){.sx-ticket-wizard-nav{grid-template-columns:repeat(2,minmax(0,1fr))}.sx-ticket-publish-grid{grid-template-columns:1fr}.sx-ticket-publish-grid button{width:100%}}
</style>
"""


TICKET_PING_JS = r"""
<script id="sentrix-ticket-ping-dashboard">
(() => {
  "use strict";
  if (window.__sentrixTicketWizardV2) return;
  window.__sentrixTicketWizardV2 = true;

  const E = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const S = () => { try { return typeof state !== "undefined" ? state : null; } catch (_) { return null; } };
  const gid = () => String(S()?.guildId || "");
  const csrf = () => String(S()?.csrf || "");
  const toast2 = (message, bad=false) => { try { if (typeof toast === "function") return toast(message, bad); } catch (_) {} (bad ? console.error : console.info)(message); };
  let currentStep = "general";
  let publicationLoading = false;

  async function api(url, options={}) {
    const response = await fetch(url, {credentials:"same-origin", cache:"no-store", ...options});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || body.message || "Action impossible.");
    return body;
  }

  function panelIdFromEditor(editor) {
    if (window.__sentrixTicketEditingPanelId) return String(window.__sentrixTicketEditingPanelId);
    const name = String(editor?.querySelector(".sx-ticket-editor-head h4")?.textContent || "").trim();
    if (!name) return "";
    for (const row of document.querySelectorAll(".sx-ticket-row")) {
      const rowName = String(row.querySelector(".sx-ticket-main b")?.textContent || "").trim();
      const button = row.querySelector("[data-panel-edit]");
      if (button && rowName === name) return String(button.dataset.panelEdit || "");
    }
    return "";
  }

  function wizardHelp(step) {
    return ({
      general:"Réglez le nom, le titre, l'état et les limites générales du panel.",
      team:"Choisissez qui peut voir/répondre aux tickets et quels rôles doivent être notifiés.",
      panel:"Personnalisez l'apparence, les types de tickets, les boutons et leurs options avancées.",
      publication:"Choisissez le salon Discord puis publiez ou mettez à jour le panel enregistré."
    })[step] || "";
  }

  function showStep(editor, step) {
    currentStep = step;
    editor.querySelectorAll("[data-sx-ticket-step]").forEach(node => {
      const values = String(node.dataset.sxTicketStep || "").split(" ");
      node.hidden = !values.includes(step);
      if (!node.hidden && node.tagName === "DETAILS") node.open = true;
    });
    editor.querySelectorAll("[data-sx-wizard-button]").forEach(button => {
      button.classList.toggle("active", button.dataset.sxWizardButton === step);
      const order = ["general","team","panel","publication"];
      button.classList.toggle("done", order.indexOf(button.dataset.sxWizardButton) < order.indexOf(step));
    });
    const help = editor.querySelector("[data-sx-wizard-help]");
    if (help) help.textContent = wizardHelp(step);
    if (step === "publication") loadPublication(editor);
  }

  async function loadGlobalPing(teamSection) {
    if (!teamSection || teamSection.querySelector("#sxTicketGlobalPingRole")) return;
    const guild = gid();
    if (!guild) return;
    let result;
    try { result = await api(`/api/guilds/${guild}/ticket-ping-role`); }
    catch (_) { return; }

    const roles = S()?.guildData?.roles || [];
    const selected = String(result.role_id || "");
    const details = document.createElement("details");
    details.className = "sx-ticket-team-advanced";
    details.innerHTML = `<summary>Réglage avancé — ping de secours</summary><div><label for="sxTicketGlobalPingRole">Rôle ping global</label><select id="sxTicketGlobalPingRole"><option value="">Aucun — utiliser les rôles du panel</option>${roles.map(role => `<option value="${E(role.id)}" ${String(role.id)===selected?"selected":""}>@${E(role.name)}</option>`).join("")}</select><span class="sx-ticket-team-hint">Utilisé uniquement comme fallback si aucun rôle de notification spécifique n'est défini pour le panel/type.</span></div>`;
    const body = teamSection.querySelector(".sx-editor-section-body");
    body?.appendChild(details);
    const select = details.querySelector("select");
    select?.addEventListener("change", async () => {
      const oldValue = selected;
      select.disabled = true;
      try {
        const body = await api(`/api/guilds/${guild}/ticket-ping-role`, {
          method:"PUT",
          headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},
          body:JSON.stringify({role_id:select.value || null})
        });
        toast2(body.message || "Rôle de ping enregistré.");
      } catch (error) {
        select.value = oldValue;
        toast2(error.message, true);
      } finally { select.disabled = false; }
    });
  }

  function publicationShell(editor, panelId) {
    let section = editor.querySelector("#sxTicketPublicationV2");
    if (section) return section;
    section = document.createElement("section");
    section.id = "sxTicketPublicationV2";
    section.className = "sx-ticket-publication-v2";
    section.dataset.sxTicketStep = "publication";
    section.dataset.panelId = panelId;
    section.hidden = true;
    section.innerHTML = `<div><h5>4. Publication</h5><p>Le panel est envoyé dans le salon choisi. S'il existe déjà dans ce même salon, SentriX le met à jour au lieu d'en créer un doublon.</p></div><div class="sx-ticket-publish-status" id="sxTicketPublishStatus">Chargement des salons…</div>`;
    const body = editor.querySelector(".sx-editor-body");
    body?.appendChild(section);
    return section;
  }

  async function loadPublication(editor) {
    if (publicationLoading) return;
    const panelId = panelIdFromEditor(editor);
    const section = publicationShell(editor, panelId);
    if (!panelId) {
      section.innerHTML = `<div><h5>4. Publication</h5><p>Enregistrez ce nouveau panel, puis rouvrez-le avec Modifier pour choisir son salon.</p></div><div class="sx-ticket-publish-status bad">Impossible d'identifier le panel tant qu'il n'a pas été enregistré.</div>`;
      return;
    }
    publicationLoading = true;
    try {
      const body = await api(`/api/guilds/${gid()}/ticket-center/panels/${panelId}/publication`);
      if (!document.body.contains(editor) || currentStep !== "publication") return;
      const channels = body.channels || [];
      const selected = String(body.channel_id || "");
      section.innerHTML = `<div><h5>4. Publication</h5><p>Choisissez le salon où les membres verront le panel. La publication utilise la dernière version enregistrée.</p></div><div class="sx-ticket-publish-grid"><div><label for="sxTicketPublishChannel">Salon du panel</label><select id="sxTicketPublishChannel"><option value="">Choisir un salon…</option>${channels.map(c => `<option value="${E(c.id)}" ${String(c.id)===selected?"selected":""}>#${E(c.name)}${c.usable?"":" — permissions manquantes"}</option>`).join("")}</select></div><button id="sxTicketPublishButton" type="button">${body.message_id?"Mettre à jour":"Publier"}</button></div><div class="sx-ticket-publish-status ${body.message_id?"ok":""}" id="sxTicketPublishStatus">${body.message_id?`Panel publié${body.channel_name?` dans #${E(body.channel_name)}`:""}.`:`${Number(body.type_count||0)} type(s) configuré(s). Le panel n'est pas encore publié.`}</div>`;
      section.querySelector("#sxTicketPublishButton")?.addEventListener("click", () => publishPanel(editor, panelId));
    } catch (error) {
      section.innerHTML = `<div><h5>4. Publication</h5></div><div class="sx-ticket-publish-status bad">${E(error.message)}</div>`;
    } finally { publicationLoading = false; }
  }

  async function publishPanel(editor, panelId) {
    const select = editor.querySelector("#sxTicketPublishChannel");
    const button = editor.querySelector("#sxTicketPublishButton");
    const status = editor.querySelector("#sxTicketPublishStatus");
    if (!select?.value) return toast2("Choisissez d'abord un salon pour le panel.", true);
    if (button) { button.disabled = true; button.textContent = "Publication…"; }
    try {
      const body = await api(`/api/guilds/${gid()}/ticket-center/panels/${panelId}/publish`, {
        method:"POST",
        headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},
        body:JSON.stringify({channel_id:select.value})
      });
      if (status) { status.className = "sx-ticket-publish-status ok"; status.textContent = body.message || "Panel publié."; }
      if (button) button.textContent = "Mettre à jour";
      toast2(body.message || "Panel publié.");
      // Le centre V35 garde son cache : son bouton Actualiser récupère le nouveau salon.
      document.getElementById("sxTicketRefresh")?.click();
    } catch (error) {
      if (status) { status.className = "sx-ticket-publish-status bad"; status.textContent = error.message; }
      if (button) button.textContent = "Publier";
      toast2(error.message, true);
    } finally { if (button) button.disabled = false; }
  }

  function enhanceEditor() {
    const editor = document.querySelector("#sxEditorBackdrop .sx-ticket-editor");
    if (!editor || editor.dataset.sxWizardReady === "1") return;
    editor.dataset.sxWizardReady = "1";
    const body = editor.querySelector(".sx-editor-body");
    if (!body) return;
    const sections = Array.from(body.querySelectorAll(":scope > details.sx-editor-section"));
    if (sections.length < 4) return;

    // V35 : contenu, apparence, rôles, boutons. On garde exactement les mêmes champs/API,
    // mais on les range dans le parcours demandé au lieu d'exposer quatre blocs techniques.
    sections[0].dataset.sxTicketStep = "general";
    sections[1].dataset.sxTicketStep = "panel";
    sections[2].dataset.sxTicketStep = "team";
    sections[3].dataset.sxTicketStep = "panel";
    const summaries = [
      [sections[0], "Général"],
      [sections[1], "Apparence du panel"],
      [sections[2], "Équipe"],
      [sections[3], "Types de tickets et boutons"]
    ];
    summaries.forEach(([section,label]) => { const summary=section.querySelector(":scope > summary"); if(summary) summary.textContent=label; });

    const wizard = document.createElement("div");
    wizard.className = "sx-ticket-wizard-v2";
    wizard.innerHTML = `<div class="sx-ticket-wizard-nav"><button type="button" data-sx-wizard-button="general">1. Général</button><button type="button" data-sx-wizard-button="team">2. Équipe</button><button type="button" data-sx-wizard-button="panel">3. Panel</button><button type="button" data-sx-wizard-button="publication">4. Publication</button></div><div class="sx-ticket-wizard-help" data-sx-wizard-help></div>`;
    body.insertBefore(wizard, body.firstChild);
    wizard.querySelectorAll("[data-sx-wizard-button]").forEach(button => button.addEventListener("click", () => showStep(editor, button.dataset.sxWizardButton)));

    const panelId = panelIdFromEditor(editor);
    publicationShell(editor, panelId);
    loadGlobalPing(sections[2]);
    showStep(editor, currentStep || "general");
  }

  document.addEventListener("click", event => {
    const edit = event.target?.closest?.("[data-panel-edit]");
    if (edit) {
      window.__sentrixTicketEditingPanelId = String(edit.dataset.panelEdit || "");
      currentStep = "general";
      setTimeout(enhanceEditor, 0);
    }
  }, true);

  const observer = new MutationObserver(() => {
    if (document.querySelector("#sxEditorBackdrop .sx-ticket-editor")) setTimeout(enhanceEditor, 0);
  });
  const start = () => {
    observer.observe(document.body, {childList:true, subtree:true});
    setTimeout(enhanceEditor, 0);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, {once:true});
  else start();
})();
</script>
"""


def _text_channels(guild: discord.Guild) -> list[dict]:
    bot_member = guild.me
    result: list[dict] = []
    for channel in guild.text_channels:
        usable = True
        if bot_member is not None:
            permissions = channel.permissions_for(bot_member)
            usable = bool(permissions.view_channel and permissions.send_messages and permissions.embed_links)
        result.append(
            {
                "id": str(channel.id),
                "name": channel.name,
                "category": channel.category.name if channel.category else None,
                "usable": usable,
                "position": channel.position,
            }
        )
    result.sort(key=lambda item: (not item["usable"], item["position"], item["name"].casefold()))
    return result


async def _publish_panel(bot, guild: discord.Guild, panel_id: int, channel: discord.TextChannel) -> tuple[int, bool]:
    """Publie un panel en conservant le même message quand c'est possible."""
    cog = bot.get_cog("Tickets")
    if cog is None:
        raise RuntimeError("Le moteur Tickets n'est pas encore disponible.")
    panel = await cog.get_panel(panel_id)
    if not panel or int(panel["guild_id"]) != guild.id:
        raise LookupError("Panel introuvable.")
    types = await cog.get_panel_types(panel_id)
    if not types:
        raise ValueError("Ajoutez au moins un type de ticket avant de publier le panel.")

    old_message = None
    old_channel = guild.get_channel(int(panel["channel_id"])) if panel["channel_id"] else None
    if panel["message_id"] and isinstance(old_channel, discord.TextChannel):
        try:
            old_message = await old_channel.fetch_message(int(panel["message_id"]))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            old_message = None

    from cogs.tickets import TicketPanelView
    view = TicketPanelView(panel, types)
    embed = cog.build_panel_embed(panel)
    reused = False

    if old_message is not None and old_channel.id == channel.id:
        try:
            await old_message.edit(embed=embed, view=view)
            message = old_message
            reused = True
        except discord.HTTPException:
            message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
    else:
        message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        if old_message is not None:
            try:
                await old_message.delete()
            except discord.HTTPException:
                pass

    await bot.db.execute(
        "UPDATE ticket_panels_v2 SET channel_id=?, message_id=? WHERE id=? AND guild_id=?",
        (channel.id, message.id, panel_id, guild.id),
    )
    return int(message.id), reused


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
        if role_id:
            role = guild.get_role(role_id)
            if role is None or role.is_default() or role.managed:
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

    async def get_publication(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
            panel_id = int(request.match_info["panel_id"])
        except ValueError:
            return dashboard._json_error("Identifiant invalide.", 400)
        _session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        bot = request.app["bot"]
        panel = await bot.db.fetchone(
            "SELECT id,channel_id,message_id FROM ticket_panels_v2 WHERE id=? AND guild_id=?",
            (panel_id, guild_id),
        )
        if not panel:
            return dashboard._json_error("Panel introuvable.", 404)
        count = await bot.db.fetchone(
            "SELECT COUNT(*) n FROM ticket_types WHERE panel_id=? AND guild_id=?",
            (panel_id, guild_id),
        )
        channel = guild.get_channel(int(panel["channel_id"])) if panel["channel_id"] else None
        return web.json_response(
            {
                "ok": True,
                "channel_id": str(panel["channel_id"]) if panel["channel_id"] else None,
                "channel_name": channel.name if isinstance(channel, discord.TextChannel) else None,
                "message_id": str(panel["message_id"]) if panel["message_id"] else None,
                "type_count": int(count["n"] if count else 0),
                "channels": _text_channels(guild),
            }
        )

    async def publish_panel(request: web.Request):
        try:
            guild_id = int(request.match_info["guild_id"])
            panel_id = int(request.match_info["panel_id"])
        except ValueError:
            return dashboard._json_error("Identifiant invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return error
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return csrf_error
        try:
            payload = await request.json()
            channel_id = int(payload.get("channel_id"))
        except (TypeError, ValueError, AttributeError):
            return dashboard._json_error("Choisissez un salon valide.", 400)

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return dashboard._json_error("Le salon choisi n'existe plus ou n'est pas un salon textuel.", 400)
        bot_member = guild.me
        if bot_member is not None:
            permissions = channel.permissions_for(bot_member)
            missing = []
            if not permissions.view_channel:
                missing.append("Voir le salon")
            if not permissions.send_messages:
                missing.append("Envoyer des messages")
            if not permissions.embed_links:
                missing.append("Intégrer des liens")
            if missing:
                return dashboard._json_error(
                    "SentriX n'a pas les permissions nécessaires dans ce salon : " + ", ".join(missing) + ".",
                    400,
                )

        try:
            message_id, reused = await _publish_panel(request.app["bot"], guild, panel_id, channel)
        except LookupError as exc:
            return dashboard._json_error(str(exc), 404)
        except (ValueError, RuntimeError) as exc:
            return dashboard._json_error(str(exc), 400)
        except discord.Forbidden:
            return dashboard._json_error("Discord refuse la publication : vérifiez les permissions de SentriX dans ce salon.", 403)
        except discord.HTTPException:
            logger.exception("Échec Discord lors de la publication du panel #%s sur %s.", panel_id, guild_id)
            return dashboard._json_error("Discord n'a pas pu publier le panel. Réessayez dans un instant.", 502)

        logger.info(
            "Dashboard : %s (%s) a %s le panel ticket #%s dans #%s (%s), message=%s.",
            session["user"].get("username"),
            session["user"].get("id"),
            "mis à jour" if reused else "publié",
            panel_id,
            channel.name,
            channel.id,
            message_id,
        )
        action = "mis à jour" if reused else "publié"
        return web.json_response(
            {
                "ok": True,
                "message_id": str(message_id),
                "channel_id": str(channel.id),
                "message": f"Panel {action} dans #{channel.name}.",
            }
        )

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app.router.add_get("/api/guilds/{guild_id}/ticket-ping-role", get_ping_role)
        app.router.add_put("/api/guilds/{guild_id}/ticket-ping-role", put_ping_role)
        app.router.add_get(
            "/api/guilds/{guild_id}/ticket-center/panels/{panel_id}/publication",
            get_publication,
        )
        app.router.add_post(
            "/api/guilds/{guild_id}/ticket-center/panels/{panel_id}/publish",
            publish_panel,
        )
        return app

    dashboard.build_app = build_app
    html = str(dashboard.INDEX_HTML)
    if 'id="sentrix-ticket-wizard-v2-css"' not in html:
        html = html.replace("</head>", TICKET_WIZARD_CSS + "\n</head>", 1)
    if 'id="sentrix-ticket-ping-dashboard"' not in html:
        html = html.replace("</body>", TICKET_PING_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html

    logger.info("Dashboard Tickets V2 : Général > Équipe > Panel > Publication actif.")
