"""Operations Center du dashboard SentriX.

Page secondaire isolée : aucune fonction critique de /app n'est remplacée. Les routes
s'appuient sur les contrôles OAuth/admin/CSRF du dashboard principal et sur le service
cogs.operations_center, qui reste la source des opérations Discord/SQLite.
"""
from __future__ import annotations

import json
import logging
import time

from aiohttp import web

logger = logging.getLogger("bot.dashboard.operations")
_INSTALLED = False


def _service(request: web.Request):
    service = request.app["bot"].get_cog("OperationsCenter")
    return service


async def _ctx(dashboard, request: web.Request, *, write: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, ValueError):
        return None, None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return None, None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, csrf_error
    service = _service(request)
    if service is None:
        return None, None, None, dashboard._json_error("Operations Center n'est pas encore prêt.", 503)
    return session, guild, service, None


async def _payload(request: web.Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:
        raise ValueError("Le formulaire envoyé est invalide.") from exc
    if not isinstance(data, dict):
        raise ValueError("Le formulaire envoyé est invalide.")
    return data


async def _audit(request: web.Request, guild_id: int, user_id: int, action: str, target: str = "", details: dict | None = None):
    try:
        await request.app["bot"].db.execute(
            "INSERT INTO dashboard_audit_log (guild_id, user_id, action, target, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, action[:120], target[:300], json.dumps(details or {}, ensure_ascii=False)[:6000], int(time.time())),
        )
    except Exception:
        logger.exception("Impossible de journaliser une action du dashboard Operations.")


async def handle_operations_page(request: web.Request) -> web.Response:
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login")
    return web.Response(
        text=OPERATIONS_HTML,
        content_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


async def api_summary(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request)
    if error:
        return error
    db = request.app["bot"].db
    now_ts = int(time.time())
    queries = {
        "open_tickets": ("SELECT COUNT(*) AS n FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (guild.id,)),
        "sanctions_24h": ("SELECT COUNT(*) AS n FROM sanctions WHERE guild_id = ? AND created_at >= ?", (guild.id, now_ts - 86400)),
        "security_24h": ("SELECT COUNT(*) AS n FROM security_incidents WHERE guild_id = ? AND created_at >= ?", (guild.id, now_ts - 86400)),
        "errors_24h": ("SELECT COUNT(*) AS n FROM runtime_errors WHERE (guild_id = ? OR guild_id IS NULL) AND created_at >= ?", (guild.id, now_ts - 86400)),
        "custom_commands": ("SELECT COUNT(*) AS n FROM custom_commands_v2 WHERE guild_id = ? AND enabled = 1", (guild.id,)),
    }
    metrics = {}
    for key, (sql, params) in queries.items():
        try:
            row = await db.fetchone(sql, params)
            metrics[key] = int(row["n"] if row else 0)
        except Exception:
            metrics[key] = 0
    checks = await db.fetchall(
        "SELECT check_name, status, details, checked_at FROM component_checks WHERE guild_id = ? ORDER BY check_name",
        (guild.id,),
    )
    errors = await db.fetchall(
        "SELECT id, source, error_type, message, created_at FROM runtime_errors WHERE guild_id = ? OR guild_id IS NULL ORDER BY created_at DESC LIMIT 20",
        (guild.id,),
    )
    audit = await db.fetchall(
        "SELECT id, user_id, action, target, created_at FROM dashboard_audit_log WHERE guild_id = ? ORDER BY created_at DESC LIMIT 20",
        (guild.id,),
    )
    return web.json_response({
        "ok": True,
        "runtime": {
            "online": request.app["bot"].is_ready(),
            "latency_ms": round(request.app["bot"].latency * 1000) if request.app["bot"].is_ready() else None,
            "guild_members": guild.member_count or 0,
        },
        "metrics": metrics,
        "checks": [dict(row) for row in checks],
        "errors": [dict(row) for row in errors],
        "audit": [dict(row) for row in audit],
    })


async def api_access_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request)
    if error:
        return error
    rules = await service.get_module_roles(guild.id, fresh=True)
    return web.json_response({
        "ok": True,
        "modules": service.__class__.__module__ and __import__("cogs.operations_center", fromlist=["MODULE_LABELS"]).MODULE_LABELS,
        "rules": {key: sorted(value) for key, value in rules.items()},
    })


async def api_access_put(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        module = str(data.get("module") or "").casefold()
        role_id = int(data.get("role_id") or 0)
        enabled = data.get("enabled")
        if enabled not in (True, False, 0, 1):
            raise ValueError("État invalide.")
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed:
            raise ValueError("Rôle introuvable ou non utilisable.")
        await service.set_module_role(guild.id, module, role_id, bool(enabled), int(session["user"]["id"]))
        await _audit(request, guild.id, int(session["user"]["id"]), "module_permission", f"{module}:{role_id}", {"enabled": bool(enabled)})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return await api_access_get(dashboard, request)


async def api_member_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request)
    if error:
        return error
    try:
        user_id = int(request.match_info["user_id"])
    except ValueError:
        return dashboard._json_error("ID membre invalide.", 400)
    profile = await service.member_profile(guild, user_id)
    return web.json_response({"ok": True, "profile": profile})


async def api_member_note_post(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        user_id = int(request.match_info["user_id"])
        data = await _payload(request)
        note_id = await service.add_staff_note(guild.id, user_id, int(session["user"]["id"]), str(data.get("note") or ""))
        await _audit(request, guild.id, int(session["user"]["id"]), "staff_note_add", str(user_id), {"note_id": note_id})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "note_id": note_id})


async def api_member_note_delete(dashboard, request: web.Request):
    session, guild, _service_obj, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        note_id = int(request.match_info["note_id"])
    except ValueError:
        return dashboard._json_error("Note invalide.", 400)
    row = await request.app["bot"].db.fetchone(
        "SELECT user_id FROM staff_notes WHERE id = ? AND guild_id = ?", (note_id, guild.id)
    )
    if not row:
        return dashboard._json_error("Note introuvable.", 404)
    await request.app["bot"].db.execute("DELETE FROM staff_notes WHERE id = ? AND guild_id = ?", (note_id, guild.id))
    await _audit(request, guild.id, int(session["user"]["id"]), "staff_note_delete", str(row["user_id"]), {"note_id": note_id})
    return web.json_response({"ok": True})


async def api_case_get(dashboard, request: web.Request):
    _session, guild, service, error = await _ctx(dashboard, request)
    if error:
        return error
    try:
        case_number = int(request.match_info["case_number"])
    except ValueError:
        return dashboard._json_error("Numéro de dossier invalide.", 400)
    case = await service.case_details(guild.id, case_number)
    if not case:
        return dashboard._json_error("Dossier introuvable.", 404)
    return web.json_response({"ok": True, "case": case})


async def api_case_post(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        case_number = int(request.match_info["case_number"])
        data = await _payload(request)
        event_type = str(data.get("event_type") or "")
        value = str(data.get("value") or "")
        await service.add_case_event(guild.id, case_number, int(session["user"]["id"]), event_type, value)
        await _audit(request, guild.id, int(session["user"]["id"]), "case_update", str(case_number), {"event_type": event_type})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return await api_case_get(dashboard, request)


async def api_scopes_get(dashboard, request: web.Request):
    _session, guild, _service_obj, error = await _ctx(dashboard, request)
    if error:
        return error
    rows = await request.app["bot"].db.fetchall(
        "SELECT target_type, target_id, enabled, updated_at FROM automod_scope_rules WHERE guild_id = ? ORDER BY target_type, target_id",
        (guild.id,),
    )
    rules = []
    for row in rows:
        target = guild.get_channel(int(row["target_id"]))
        rules.append({**dict(row), "name": target.name if target else str(row["target_id"])})
    targets = [
        {"id": str(ch.id), "name": ch.name, "type": "category" if ch.__class__.__name__ == "CategoryChannel" else "channel"}
        for ch in guild.channels
    ]
    return web.json_response({"ok": True, "rules": rules, "targets": targets})


async def api_scopes_put(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        target_type = str(data.get("target_type") or "")
        target_id = int(data.get("target_id") or 0)
        enabled = data.get("enabled")
        if enabled not in (True, False, 0, 1):
            raise ValueError("État invalide.")
        await service.set_automod_scope(guild, target_type, target_id, bool(enabled), int(session["user"]["id"]))
        await _audit(request, guild.id, int(session["user"]["id"]), "automod_scope", f"{target_type}:{target_id}", {"enabled": bool(enabled)})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return await api_scopes_get(dashboard, request)


async def api_backups_get(dashboard, request: web.Request):
    _session, guild, _service_obj, error = await _ctx(dashboard, request)
    if error:
        return error
    rows = await request.app["bot"].db.fetchall(
        "SELECT id, label, created_by, created_at FROM server_backups WHERE guild_id = ? ORDER BY created_at DESC, id DESC LIMIT 30",
        (guild.id,),
    )
    return web.json_response({"ok": True, "backups": [dict(row) for row in rows]})


async def api_backups_post(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        backup_id = await service.create_rich_backup(guild, str(data.get("label") or "Backup complet"), int(session["user"]["id"]))
        await _audit(request, guild.id, int(session["user"]["id"]), "backup_create", str(backup_id))
    except ValueError as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "backup_id": backup_id})


async def api_backup_restore(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        backup_id = int(request.match_info["backup_id"])
        data = await _payload(request)
        part = str(data.get("part") or "")
        result = await service.restore_backup_part(guild, backup_id, part)
        await _audit(request, guild.id, int(session["user"]["id"]), "backup_restore", str(backup_id), result)
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "result": result})


async def api_custom_get(dashboard, request: web.Request):
    _session, guild, _service_obj, error = await _ctx(dashboard, request)
    if error:
        return error
    rows = await request.app["bot"].db.fetchall(
        "SELECT id, name, response, allowed_role_id, enabled, created_by, created_at, updated_at FROM custom_commands_v2 WHERE guild_id = ? ORDER BY name",
        (guild.id,),
    )
    return web.json_response({"ok": True, "commands": [dict(row) for row in rows]})


async def api_custom_put(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        allowed_role = data.get("allowed_role_id")
        allowed_role_id = int(allowed_role) if allowed_role not in (None, "", 0, "0") else None
        if allowed_role_id is not None and guild.get_role(allowed_role_id) is None:
            raise ValueError("Le rôle requis n'existe plus.")
        await service.save_custom_command(
            guild.id, str(data.get("name") or ""), str(data.get("response") or ""),
            int(session["user"]["id"]), allowed_role_id, bool(data.get("enabled", True)),
        )
        await _audit(request, guild.id, int(session["user"]["id"]), "custom_command_save", str(data.get("name") or ""))
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return await api_custom_get(dashboard, request)


async def api_custom_delete(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        command_id = int(request.match_info["command_id"])
    except ValueError:
        return dashboard._json_error("Commande invalide.", 400)
    row = await request.app["bot"].db.fetchone("SELECT name FROM custom_commands_v2 WHERE id = ? AND guild_id = ?", (command_id, guild.id))
    if not row:
        return dashboard._json_error("Commande introuvable.", 404)
    await request.app["bot"].db.execute("DELETE FROM custom_commands_v2 WHERE id = ? AND guild_id = ?", (command_id, guild.id))
    service._custom_cache.pop(guild.id, None)
    await _audit(request, guild.id, int(session["user"]["id"]), "custom_command_delete", str(row["name"]))
    return web.json_response({"ok": True})


async def api_forms_get(dashboard, request: web.Request):
    _session, guild, _service_obj, error = await _ctx(dashboard, request)
    if error:
        return error
    types = await request.app["bot"].db.fetchall(
        "SELECT tt.id, tt.panel_id, tt.name, tt.use_form, tp.name AS panel_name FROM ticket_types tt "
        "LEFT JOIN ticket_panels_v2 tp ON tp.id = tt.panel_id WHERE tt.guild_id = ? ORDER BY tt.panel_id, tt.position, tt.id",
        (guild.id,),
    )
    questions = await request.app["bot"].db.fetchall(
        "SELECT q.id, q.ticket_type_id, q.position, q.label, q.placeholder, q.style, q.required, q.min_length, q.max_length "
        "FROM ticket_form_questions q JOIN ticket_types tt ON tt.id = q.ticket_type_id WHERE tt.guild_id = ? ORDER BY q.ticket_type_id, q.position, q.id",
        (guild.id,),
    )
    return web.json_response({"ok": True, "types": [dict(r) for r in types], "questions": [dict(r) for r in questions]})


async def api_form_question_put(dashboard, request: web.Request):
    session, guild, _service_obj, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        data = await _payload(request)
        type_id = int(data.get("ticket_type_id") or 0)
        question_id = int(data.get("id") or 0) or None
        ticket_type = await request.app["bot"].db.fetchone("SELECT id FROM ticket_types WHERE id = ? AND guild_id = ?", (type_id, guild.id))
        if not ticket_type:
            raise ValueError("Type de ticket introuvable.")
        label = str(data.get("label") or "").strip()
        placeholder = str(data.get("placeholder") or "").strip()
        style = str(data.get("style") or "short")
        required = int(bool(data.get("required", True)))
        min_length = int(data.get("min_length") or 0)
        max_length = int(data.get("max_length") or 500)
        if not label or len(label) > 45 or len(placeholder) > 100 or style not in {"short", "paragraph"}:
            raise ValueError("Question invalide ou trop longue.")
        if min_length < 0 or max_length < max(1, min_length) or max_length > 4000:
            raise ValueError("Bornes de longueur invalides.")
        if question_id:
            exists = await request.app["bot"].db.fetchone(
                "SELECT q.id FROM ticket_form_questions q JOIN ticket_types tt ON tt.id = q.ticket_type_id WHERE q.id = ? AND tt.guild_id = ?",
                (question_id, guild.id),
            )
            if not exists:
                raise ValueError("Question introuvable.")
            await request.app["bot"].db.execute(
                "UPDATE ticket_form_questions SET ticket_type_id=?, label=?, placeholder=?, style=?, required=?, min_length=?, max_length=? WHERE id=?",
                (type_id, label, placeholder, style, required, min_length, max_length, question_id),
            )
        else:
            pos = await request.app["bot"].db.fetchone("SELECT COALESCE(MAX(position), -1) + 1 AS n FROM ticket_form_questions WHERE ticket_type_id = ?", (type_id,))
            await request.app["bot"].db.execute(
                "INSERT INTO ticket_form_questions (ticket_type_id, position, label, placeholder, style, required, min_length, max_length) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (type_id, int(pos["n"] if pos else 0), label, placeholder, style, required, min_length, max_length),
            )
        await request.app["bot"].db.execute("UPDATE ticket_types SET use_form = 1 WHERE id = ? AND guild_id = ?", (type_id, guild.id))
        await _audit(request, guild.id, int(session["user"]["id"]), "ticket_form_question_save", str(type_id), {"question_id": question_id})
    except (TypeError, ValueError) as exc:
        return dashboard._json_error(str(exc), 400)
    return await api_forms_get(dashboard, request)


async def api_form_question_delete(dashboard, request: web.Request):
    session, guild, _service_obj, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        question_id = int(request.match_info["question_id"])
    except ValueError:
        return dashboard._json_error("Question invalide.", 400)
    row = await request.app["bot"].db.fetchone(
        "SELECT q.id, q.ticket_type_id FROM ticket_form_questions q JOIN ticket_types tt ON tt.id=q.ticket_type_id WHERE q.id=? AND tt.guild_id=?",
        (question_id, guild.id),
    )
    if not row:
        return dashboard._json_error("Question introuvable.", 404)
    await request.app["bot"].db.execute("DELETE FROM ticket_form_questions WHERE id = ?", (question_id,))
    await _audit(request, guild.id, int(session["user"]["id"]), "ticket_form_question_delete", str(row["ticket_type_id"]), {"question_id": question_id})
    return web.json_response({"ok": True})


async def api_transcripts_get(dashboard, request: web.Request):
    _session, guild, _service_obj, error = await _ctx(dashboard, request)
    if error:
        return error
    q = str(request.query.get("q") or "").strip()
    if q:
        like = f"%{q[:200]}%"
        rows = await request.app["bot"].db.fetchall(
            "SELECT id, ticket_id, channel_id, user_id, generated_by, generated_at FROM ticket_transcripts_v2 "
            "WHERE guild_id = ? AND (search_text LIKE ? OR CAST(ticket_id AS TEXT) LIKE ? OR CAST(user_id AS TEXT) LIKE ?) "
            "ORDER BY generated_at DESC LIMIT 50",
            (guild.id, like, like, like),
        )
    else:
        rows = await request.app["bot"].db.fetchall(
            "SELECT id, ticket_id, channel_id, user_id, generated_by, generated_at FROM ticket_transcripts_v2 WHERE guild_id = ? ORDER BY generated_at DESC LIMIT 50",
            (guild.id,),
        )
    tickets = await request.app["bot"].db.fetchall(
        "SELECT id, channel_id, user_id, status FROM tickets WHERE guild_id = ? ORDER BY id DESC LIMIT 100", (guild.id,)
    )
    return web.json_response({"ok": True, "transcripts": [dict(r) for r in rows], "tickets": [dict(r) for r in tickets]})


async def api_transcript_generate(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        ticket_id = int(request.match_info["ticket_id"])
        result = await service.generate_ticket_transcript(guild, ticket_id, int(session["user"]["id"]))
        await _audit(request, guild.id, int(session["user"]["id"]), "ticket_transcript_generate", str(ticket_id), result)
    except ValueError as exc:
        return dashboard._json_error(str(exc), 400)
    return web.json_response({"ok": True, "transcript": result})


async def api_transcript_html(dashboard, request: web.Request):
    _session, guild, _service_obj, error = await _ctx(dashboard, request)
    if error:
        return error
    try:
        transcript_id = int(request.match_info["transcript_id"])
    except ValueError:
        return dashboard._json_error("Transcript invalide.", 400)
    row = await request.app["bot"].db.fetchone(
        "SELECT html_content FROM ticket_transcripts_v2 WHERE id = ? AND guild_id = ?", (transcript_id, guild.id)
    )
    if not row:
        return dashboard._json_error("Transcript introuvable.", 404)
    return web.Response(text=row["html_content"], content_type="text/html", headers={"Cache-Control": "private, no-store"})


async def api_diagnostics_post(dashboard, request: web.Request):
    session, guild, service, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    result = await service.run_diagnostics(guild, deep=True)
    await _audit(request, guild.id, int(session["user"]["id"]), "diagnostics", str(guild.id), {"ok": result["ok"]})
    return web.json_response({"ok": True, "diagnostics": result})


async def api_audit_get(dashboard, request: web.Request):
    _session, guild, _service_obj, error = await _ctx(dashboard, request)
    if error:
        return error
    rows = await request.app["bot"].db.fetchall(
        "SELECT id, user_id, action, target, details_json, created_at FROM dashboard_audit_log WHERE guild_id = ? ORDER BY created_at DESC LIMIT 100",
        (guild.id,),
    )
    return web.json_response({"ok": True, "entries": [dict(r) for r in rows]})


async def api_errors_get(dashboard, request: web.Request):
    _session, guild, _service_obj, error = await _ctx(dashboard, request)
    if error:
        return error
    rows = await request.app["bot"].db.fetchall(
        "SELECT id, source, error_type, message, created_at FROM runtime_errors WHERE guild_id = ? OR guild_id IS NULL ORDER BY created_at DESC LIMIT 100",
        (guild.id,),
    )
    return web.json_response({"ok": True, "errors": [dict(r) for r in rows]})


OPS_LINK_JS = r"""
<script id="sentrix-operations-link">
(() => {
  "use strict";
  if (window.__sentrixOperationsLink) return;
  window.__sentrixOperationsLink = true;
  const guildId = () => {
    try { return typeof state !== "undefined" && state.guildId ? String(state.guildId) : ""; }
    catch (_) { return ""; }
  };
  function install(){
    const host = document.querySelector(".side-bottom") || document.querySelector(".nav");
    if (!host) return;
    let link = document.getElementById("sentrixOperationsLink");
    if (!link) {
      link = document.createElement("a");
      link.id = "sentrixOperationsLink";
      link.className = "btn ghost";
      link.textContent = "Operations";
      host.appendChild(link);
    }
    const id = guildId();
    link.href = "/operations" + (id ? "?guild=" + encodeURIComponent(id) : "");

    if (!document.getElementById("sentrixGlobalSearch")) {
      const box = document.createElement("div");
      box.style.marginTop = "10px";
      const input = document.createElement("input");
      input.id = "sentrixGlobalSearch";
      input.placeholder = "Rechercher un réglage";
      input.setAttribute("aria-label", "Recherche globale du dashboard");
      input.addEventListener("keydown", event => {
        if (event.key !== "Enter") return;
        const q = input.value.trim();
        if (!q) return;
        const low = q.toLowerCase();
        const setupWords = ["bienvenue","welcome","logs","niveau","xp","economie","économie","design","setup","autorole"];
        const base = setupWords.some(word => low.includes(word)) ? "/setup-center" : "/operations";
        location.href = base + "?guild=" + encodeURIComponent(guildId()) + "&q=" + encodeURIComponent(q);
      });
      box.appendChild(input);
      host.appendChild(box);
    }
  }
  setInterval(install, 1000);
  setTimeout(install, 100);
})();
</script>
"""


def _inject_main(html: str) -> str:
    if 'id="sentrix-operations-link"' in html:
        return html
    return html.replace("</body>", OPS_LINK_JS + "\n</body>", 1)


def _wrap_existing_writes(dashboard):
    for name, action in {
        "handle_update_guild": "settings_update",
        "handle_sanction_action": "sanction_action",
        "handle_create_social_notification": "social_notification_create",
        "handle_delete_social_notification": "social_notification_delete",
    }.items():
        original = getattr(dashboard, name, None)
        if original is None or getattr(original, "_sentrix_ops_audit", False):
            continue

        async def wrapper(request: web.Request, _original=original, _action=action):
            session = dashboard._session(request)
            response = await _original(request)
            if session and getattr(response, "status", 500) < 400:
                try:
                    guild_id = int(request.match_info.get("guild_id", "0"))
                    if guild_id:
                        await _audit(
                            request, guild_id, int(session["user"]["id"]),
                            _action, request.path,
                        )
                except Exception:
                    pass
            return response

        wrapper._sentrix_ops_audit = True
        setattr(dashboard, name, wrapper)


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    _wrap_existing_writes(dashboard)
    try:
        from . import admin_only_dashboard
        admin_only_dashboard._PRIVATE_PAGE_PATHS.add("/operations")
    except Exception:
        logger.exception("Impossible d'ajouter /operations aux pages privées.")

    original_build_app = dashboard.build_app

    def bind(fn):
        async def handler(request: web.Request):
            return await fn(dashboard, request)
        return handler

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/operations", handle_operations_page)

        app.router.add_get("/api/guilds/{guild_id}/ops/summary", bind(api_summary))
        app.router.add_get("/api/guilds/{guild_id}/ops/access", bind(api_access_get))
        app.router.add_put("/api/guilds/{guild_id}/ops/access", bind(api_access_put))
        app.router.add_get("/api/guilds/{guild_id}/ops/member/{user_id}", bind(api_member_get))
        app.router.add_post("/api/guilds/{guild_id}/ops/member/{user_id}/notes", bind(api_member_note_post))
        app.router.add_delete("/api/guilds/{guild_id}/ops/notes/{note_id}", bind(api_member_note_delete))
        app.router.add_get("/api/guilds/{guild_id}/ops/cases/{case_number}", bind(api_case_get))
        app.router.add_post("/api/guilds/{guild_id}/ops/cases/{case_number}", bind(api_case_post))

        app.router.add_get("/api/guilds/{guild_id}/ops/automod-scopes", bind(api_scopes_get))
        app.router.add_put("/api/guilds/{guild_id}/ops/automod-scopes", bind(api_scopes_put))

        app.router.add_get("/api/guilds/{guild_id}/ops/backups", bind(api_backups_get))
        app.router.add_post("/api/guilds/{guild_id}/ops/backups", bind(api_backups_post))
        app.router.add_post("/api/guilds/{guild_id}/ops/backups/{backup_id}/restore", bind(api_backup_restore))

        app.router.add_get("/api/guilds/{guild_id}/ops/custom-commands", bind(api_custom_get))
        app.router.add_put("/api/guilds/{guild_id}/ops/custom-commands", bind(api_custom_put))
        app.router.add_delete("/api/guilds/{guild_id}/ops/custom-commands/{command_id}", bind(api_custom_delete))

        app.router.add_get("/api/guilds/{guild_id}/ops/ticket-forms", bind(api_forms_get))
        app.router.add_put("/api/guilds/{guild_id}/ops/ticket-forms/questions", bind(api_form_question_put))
        app.router.add_delete("/api/guilds/{guild_id}/ops/ticket-forms/questions/{question_id}", bind(api_form_question_delete))

        app.router.add_get("/api/guilds/{guild_id}/ops/transcripts", bind(api_transcripts_get))
        app.router.add_post("/api/guilds/{guild_id}/ops/tickets/{ticket_id}/transcript", bind(api_transcript_generate))
        app.router.add_get("/api/guilds/{guild_id}/ops/transcripts/{transcript_id}", bind(api_transcript_html))

        app.router.add_post("/api/guilds/{guild_id}/ops/diagnostics", bind(api_diagnostics_post))
        app.router.add_get("/api/guilds/{guild_id}/ops/audit", bind(api_audit_get))
        app.router.add_get("/api/guilds/{guild_id}/ops/errors", bind(api_errors_get))
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject_main(dashboard.INDEX_HTML)
    logger.info("Operations Center ajouté au dashboard stable.")


OPERATIONS_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#090b12"><title>SentriX — Operations</title>
<style>
:root{--bg:#090b12;--panel:#111522;--panel2:#171c2c;--line:#283049;--text:#f2f4ff;--muted:#97a0b7;--brand:#7c6cff;--ok:#44d39a;--bad:#ff667d;--warn:#f2bd5a}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 12% -10%,#33266b55,transparent 34%),var(--bg);color:var(--text);font:14px Inter,system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh}button,input,select,textarea{font:inherit}a{color:inherit;text-decoration:none}
.top{position:sticky;top:0;z-index:20;padding:14px 4vw;border-bottom:1px solid var(--line);background:#090b12ee;backdrop-filter:blur(12px);display:flex;align-items:center;gap:12px;justify-content:space-between}.brand{font-size:18px;font-weight:900}.top-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn{border:1px solid var(--line);border-radius:10px;padding:9px 13px;background:var(--panel2);color:var(--text);cursor:pointer;font-weight:780}.btn:hover{border-color:#596485}.btn.primary{background:var(--brand);border-color:transparent}.btn.danger{background:#35151f;border-color:#713044;color:#ff9aaa}.btn:disabled{opacity:.45;cursor:not-allowed}
main{max-width:1380px;margin:auto;padding:26px 24px 70px}.head{display:grid;grid-template-columns:1fr 300px;gap:16px;align-items:end}.head h1{font-size:32px;margin:0 0 6px}.head p{margin:0;color:var(--muted);line-height:1.5}
input,select,textarea{width:100%;border:1px solid var(--line);border-radius:10px;background:#0b0f18;color:var(--text);padding:10px 11px;outline:none}input:focus,select:focus,textarea:focus{border-color:var(--brand)}textarea{min-height:90px;resize:vertical}.field label{display:block;font-weight:800;margin:0 0 6px}.field small,.muted{color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin:20px 0}.metric{padding:14px;background:var(--panel);border:1px solid var(--line);border-radius:13px}.metric span{color:var(--muted);font-size:11px;display:block}.metric b{font-size:22px;display:block;margin-top:5px}
.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;overflow:hidden}.card.full{grid-column:1/-1}.card-head{padding:17px 18px;border-bottom:1px solid var(--line)}.card-head h2{margin:0 0 5px;font-size:16px}.card-head p{margin:0;color:var(--muted);font-size:12px;line-height:1.5}.body{padding:17px 18px}.row{display:flex;gap:8px;align-items:end;flex-wrap:wrap}.row .field{flex:1 1 160px}.list{display:grid;gap:7px;margin-top:12px;max-height:330px;overflow:auto}.item{display:flex;gap:10px;align-items:center;justify-content:space-between;background:#0d111b;border:1px solid #252d43;border-radius:10px;padding:10px}.item .grow{min-width:0;flex:1}.item b{display:block}.meta{color:var(--muted);font-size:11px;line-height:1.45;margin-top:3px;overflow-wrap:anywhere}.pill{display:inline-flex;padding:4px 7px;border:1px solid #345f52;background:#13342b;color:#8ce3c4;border-radius:999px;font-size:10px;font-weight:900}.pill.warn{border-color:#6e5830;background:#302713;color:#f2cf82}.pill.bad{border-color:#713044;background:#34151f;color:#ff9aaa}.status{margin:14px 0;padding:10px 12px;border-radius:10px;border:1px solid #315b4e;background:#12332b;color:#8be4c3}.status.bad{border-color:#713044;background:#2c141c;color:#ff9aaa}.hidden{display:none!important}.search{min-width:260px}.split{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:1000px){.metrics{grid-template-columns:repeat(3,1fr)}.cards,.split{grid-template-columns:1fr}.card.full{grid-column:auto}.head{grid-template-columns:1fr}}@media(max-width:620px){.metrics{grid-template-columns:repeat(2,1fr)}main{padding:18px 12px 50px}.top{padding:12px}.search{min-width:0}}
</style>
</head><body>
<header class="top"><div class="brand">SentriX / Operations</div><div class="top-actions"><input id="search" class="search" placeholder="Rechercher un réglage"><a class="btn" href="/app">Dashboard</a><button class="btn" id="refresh">Actualiser</button></div></header>
<main>
<div class="head"><div><h1>Centre Operations</h1><p>Permissions, profils staff, dossiers, AutoMod, backups, tickets et santé du bot au même endroit.</p></div><div class="field"><label>Serveur</label><select id="guild"><option>Chargement</option></select></div></div>
<div id="status" class="status hidden"></div>
<div class="metrics"><div class="metric"><span>Latence</span><b id="mLatency">-</b></div><div class="metric"><span>Tickets ouverts</span><b id="mTickets">0</b></div><div class="metric"><span>Sanctions 24 h</span><b id="mSanctions">0</b></div><div class="metric"><span>Incidents sécurité</span><b id="mSecurity">0</b></div><div class="metric"><span>Erreurs 24 h</span><b id="mErrors">0</b></div><div class="metric"><span>Commandes custom</span><b id="mCustom">0</b></div></div>
<div class="cards" id="cards">
<section class="card" id="permissions" data-search="permissions roles modules moderation securite tickets economie ia niveaux">
<div class="card-head"><h2>Permissions par module</h2><p>Restreint un module à certains rôles sans donner Administrateur. Les checks Discord existants restent obligatoires.</p></div>
<div class="body"><div class="row"><div class="field"><label>Module</label><select id="accessModule"></select></div><div class="field"><label>Rôle</label><select id="accessRole"></select></div><button class="btn primary" id="accessAdd">Autoriser</button><button class="btn danger" id="accessRemove">Retirer</button></div><div class="list" id="accessList"></div></div>
</section>

<section class="card" id="member" data-search="membre profil sanctions warns tickets notes staff invites activite">
<div class="card-head"><h2>Profil membre complet</h2><p>Sanctions, avertissements, tickets, notes privées staff, niveau, argent, invites et AutoMod.</p></div>
<div class="body"><div class="row"><div class="field"><label>ID membre</label><input id="memberId" inputmode="numeric" placeholder="123456789"></div><button class="btn primary" id="memberLoad">Charger</button></div><div id="memberResult" class="list"></div><div class="field" style="margin-top:12px"><label>Note staff privée</label><textarea id="memberNote" maxlength="1500"></textarea></div><button class="btn" id="memberNoteAdd">Ajouter la note</button></div>
</section>

<section class="card" id="cases" data-search="case dossier moderation raison annuler sanction note">
<div class="card-head"><h2>Dossiers de modération</h2><p>Ajoute une nouvelle raison, une note, annule logiquement ou restaure le statut d'un dossier sans effacer l'historique.</p></div>
<div class="body"><div class="row"><div class="field"><label>Numéro de dossier</label><input id="caseNumber" type="number" min="1"></div><button class="btn primary" id="caseLoad">Charger</button></div><div id="caseResult" class="list"></div><div class="row" style="margin-top:12px"><div class="field"><label>Action</label><select id="caseAction"><option value="reason">Nouvelle raison</option><option value="note">Ajouter une note</option><option value="void">Annuler logiquement</option><option value="restore">Restaurer le statut</option></select></div><div class="field"><label>Texte</label><input id="caseValue" maxlength="1500"></div><button class="btn" id="caseSave">Appliquer</button></div></div>
</section>

<section class="card" id="automod" data-search="automod salon categorie exception antilink spam scope">
<div class="card-head"><h2>AutoMod par salon et catégorie</h2><p>Les cibles exemptées ignorent les filtres de contenu AutoMod. L'anti-nuke reste indépendant.</p></div>
<div class="body"><div class="row"><div class="field"><label>Salon ou catégorie à exempter</label><select id="scopeTarget"></select></div><button class="btn primary" id="scopeAdd">Exempter</button></div><div class="list" id="scopeList"></div></div>
</section>

<section class="card" id="backups" data-search="backup sauvegarde restore restauration roles salons permissions">
<div class="card-head"><h2>Sauvegardes partielles</h2><p>Crée un snapshot riche puis restaure seulement les rôles, les salons ou les permissions.</p></div>
<div class="body"><div class="row"><div class="field"><label>Nom du backup</label><input id="backupLabel" maxlength="80" value="Backup complet"></div><button class="btn primary" id="backupCreate">Créer</button></div><div class="list" id="backupList"></div></div>
</section>

<section class="card" id="custom" data-search="commande custom personnalisee faq reglement reseaux">
<div class="card-head"><h2>Commandes personnalisées</h2><p>Crée des réponses simples comme +reglement ou +reseaux sans modifier le code du bot.</p></div>
<div class="body"><div class="row"><div class="field"><label>Nom</label><input id="customName" maxlength="32" placeholder="reglement"></div><div class="field"><label>Rôle requis (optionnel)</label><select id="customRole"></select></div></div><div class="field" style="margin-top:10px"><label>Réponse</label><textarea id="customResponse" maxlength="2000" placeholder="Texte de la commande"></textarea></div><button class="btn primary" id="customSave">Enregistrer</button><div class="list" id="customList"></div></div>
</section>

<section class="card full" id="tickets" data-search="tickets formulaires questions transcript html recherche support">
<div class="card-head"><h2>Tickets avancés et transcripts HTML</h2><p>Questions personnalisables et archives consultables/recherchables depuis le dashboard.</p></div>
<div class="body split">
<div><h3>Formulaire</h3><div class="row"><div class="field"><label>Type de ticket</label><select id="formType"></select></div><div class="field"><label>Question</label><input id="formLabel" maxlength="45"></div></div><div class="row" style="margin-top:8px"><div class="field"><label>Placeholder</label><input id="formPlaceholder" maxlength="100"></div><div class="field"><label>Style</label><select id="formStyle"><option value="short">Courte</option><option value="paragraph">Paragraphe</option></select></div><div class="field"><label>Min / Max</label><div class="row"><input id="formMin" type="number" min="0" max="4000" value="0"><input id="formMax" type="number" min="1" max="4000" value="500"></div></div></div><label style="display:block;margin:10px 0"><input id="formRequired" type="checkbox" checked style="width:auto"> Question obligatoire</label><button class="btn primary" id="formSave">Ajouter la question</button><div class="list" id="formList"></div></div>
<div><h3>Transcripts</h3><div class="row"><div class="field"><label>Ticket</label><select id="transcriptTicket"></select></div><button class="btn primary" id="transcriptGenerate">Générer</button></div><div class="field" style="margin-top:10px"><label>Recherche dans les archives</label><input id="transcriptSearch" placeholder="ID, membre ou texte"></div><div class="list" id="transcriptList"></div></div>
</div>
</section>

<section class="card" id="health" data-search="health sante erreurs diagnostic permissions boutons panels persistent raid latence">
<div class="card-head"><h2>Santé et diagnostic</h2><p>Vérifie les permissions du bot, la hiérarchie, les vues persistantes et les panneaux enregistrés.</p></div>
<div class="body"><button class="btn primary" id="diagRun">Lancer un diagnostic complet</button><div class="list" id="healthList"></div><h3>Erreurs récentes</h3><div class="list" id="errorList"></div></div>
</section>

<section class="card" id="audit" data-search="audit dashboard historique changement admin qui a modifie">
<div class="card-head"><h2>Journal du dashboard</h2><p>Qui a changé quoi depuis l'interface web, avec heure et cible.</p></div>
<div class="body"><div class="list" id="auditList"></div></div>
</section>

</div>
</main>
<script>
const state={csrf:"",guildId:"",guildData:null,summary:null,access:null,scopes:null,custom:null,forms:null,transcripts:null,memberId:"",caseNumber:""};
const $=id=>document.getElementById(id);
const esc=v=>String(v??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
async function api(url,options={}){const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...options});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||"Une erreur est survenue.");return d}
function msg(text,bad=false){const b=$("status");b.textContent=text;b.className="status"+(bad?" bad":"");b.classList.remove("hidden");clearTimeout(msg.t);msg.t=setTimeout(()=>b.classList.add("hidden"),5000)}
function ts(v){return v?new Date(Number(v)*1000).toLocaleString("fr-FR"):"-"}
function roleOptions(blank=true){const roles=state.guildData?.roles||[];return (blank?'<option value="">Aucun rôle</option>':"")+roles.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("")}
async function boot(){try{const me=await api("/api/me");state.csrf=me.csrf;const gs=await api("/api/guilds");const installed=gs.guilds.filter(g=>g.installed);$("guild").innerHTML='<option value="">Choisissez un serveur</option>'+installed.map(g=>`<option value="${esc(g.id)}">${esc(g.name)}</option>`).join("");const q=new URLSearchParams(location.search);const wanted=q.get("guild");const id=installed.some(g=>String(g.id)===String(wanted))?wanted:(installed[0]?.id||"");if(id){$("guild").value=id;await loadGuild(id)}const search=q.get("q");if(search){$("search").value=search;filterCards(search)}}catch(e){msg(e.message,true);setTimeout(()=>location.href="/app",1200)}}
async function loadGuild(id){if(!id)return;state.guildId=String(id);try{const [guildData,summary,access,scopes,custom,forms,transcripts]=await Promise.all([api(`/api/guilds/${id}`),api(`/api/guilds/${id}/ops/summary`),api(`/api/guilds/${id}/ops/access`),api(`/api/guilds/${id}/ops/automod-scopes`),api(`/api/guilds/${id}/ops/custom-commands`),api(`/api/guilds/${id}/ops/ticket-forms`),api(`/api/guilds/${id}/ops/transcripts`)]);state.guildData=guildData;state.summary=summary;state.access=access;state.scopes=scopes;state.custom=custom;state.forms=forms;state.transcripts=transcripts;renderAll()}catch(e){msg(e.message,true)}}
function renderAll(){renderSummary();renderAccess();renderScopes();renderCustom();renderForms();renderTranscripts()}
function renderSummary(){const s=state.summary||{},m=s.metrics||{};$("mLatency").textContent=s.runtime?.latency_ms==null?"-":s.runtime.latency_ms+" ms";$("mTickets").textContent=m.open_tickets??0;$("mSanctions").textContent=m.sanctions_24h??0;$("mSecurity").textContent=m.security_24h??0;$("mErrors").textContent=m.errors_24h??0;$("mCustom").textContent=m.custom_commands??0;$("healthList").innerHTML=(s.checks||[]).map(c=>`<div class="item"><div class="grow"><b>${esc(c.check_name)}</b><div class="meta">${esc(c.details)} · ${ts(c.checked_at)}</div></div><span class="pill ${c.status==="ok"?"":"warn"}">${esc(c.status)}</span></div>`).join("")||'<div class="muted">Aucun diagnostic enregistré.</div>';$("errorList").innerHTML=(s.errors||[]).map(e=>`<div class="item"><div class="grow"><b>${esc(e.error_type)} · ${esc(e.source)}</b><div class="meta">${esc(e.message)}<br>${ts(e.created_at)}</div></div></div>`).join("")||'<div class="muted">Aucune erreur récente.</div>';$("auditList").innerHTML=(s.audit||[]).map(a=>`<div class="item"><div class="grow"><b>${esc(a.action)}</b><div class="meta">Utilisateur ${esc(a.user_id)} · ${esc(a.target||"-")} · ${ts(a.created_at)}</div></div></div>`).join("")||'<div class="muted">Aucune action enregistrée.</div>'}
function renderAccess(){const a=state.access||{};$("accessModule").innerHTML=Object.entries(a.modules||{}).map(([k,v])=>`<option value="${esc(k)}">${esc(v)}</option>`).join("");$("accessRole").innerHTML=roleOptions(false);$("customRole").innerHTML=roleOptions(true);const lines=[];for(const [module,ids] of Object.entries(a.rules||{})){if(!ids.length)continue;const names=ids.map(id=>(state.guildData?.roles||[]).find(r=>String(r.id)===String(id))?.name||id);lines.push(`<div class="item"><div class="grow"><b>${esc(a.modules?.[module]||module)}</b><div class="meta">${names.map(esc).join(", ")}</div></div></div>`)}$("accessList").innerHTML=lines.join("")||'<div class="muted">Aucune restriction : les permissions normales de SentriX s’appliquent.</div>'}
function renderScopes(){$("scopeTarget").innerHTML=(state.scopes?.targets||[]).map(t=>`<option value="${esc(t.type)}:${esc(t.id)}">${esc(t.name)} · ${esc(t.type)}</option>`).join("");$("scopeList").innerHTML=(state.scopes?.rules||[]).map(r=>`<div class="item"><div class="grow"><b>${esc(r.name)}</b><div class="meta">${esc(r.target_type)}</div></div><button class="btn danger" data-scope-remove="${esc(r.target_type)}:${esc(r.target_id)}">Retirer</button></div>`).join("")||'<div class="muted">Aucune exception AutoMod.</div>';document.querySelectorAll("[data-scope-remove]").forEach(b=>b.onclick=()=>saveScope(b.dataset.scopeRemove,false))}
function renderCustom(){$("customList").innerHTML=(state.custom?.commands||[]).map(c=>`<div class="item"><div class="grow"><b>+${esc(c.name)}</b><div class="meta">${esc(c.response.slice(0,140))}${c.allowed_role_id?`<br>Rôle : ${esc(c.allowed_role_id)}`:""}</div></div><button class="btn danger" data-custom-delete="${esc(c.id)}">Supprimer</button></div>`).join("")||'<div class="muted">Aucune commande personnalisée.</div>';document.querySelectorAll("[data-custom-delete]").forEach(b=>b.onclick=()=>deleteCustom(b.dataset.customDelete))}
function renderForms(){const f=state.forms||{};$("formType").innerHTML=(f.types||[]).map(t=>`<option value="${esc(t.id)}">${esc(t.panel_name||"Panel")} / ${esc(t.name)}</option>`).join("");$("formList").innerHTML=(f.questions||[]).map(q=>`<div class="item"><div class="grow"><b>${esc(q.label)}</b><div class="meta">Type ${esc(q.ticket_type_id)} · ${esc(q.style)} · ${q.required?"obligatoire":"optionnelle"} · ${esc(q.min_length)}-${esc(q.max_length)}</div></div><button class="btn danger" data-question-delete="${esc(q.id)}">Supprimer</button></div>`).join("")||'<div class="muted">Aucune question configurée.</div>';document.querySelectorAll("[data-question-delete]").forEach(b=>b.onclick=()=>deleteQuestion(b.dataset.questionDelete))}
function renderTranscripts(){const t=state.transcripts||{};$("transcriptTicket").innerHTML=(t.tickets||[]).map(x=>`<option value="${esc(x.id)}">Ticket #${esc(x.id)} · membre ${esc(x.user_id)} · ${esc(x.status)}</option>`).join("");$("transcriptList").innerHTML=(t.transcripts||[]).map(x=>`<div class="item"><div class="grow"><b>Ticket #${esc(x.ticket_id)}</b><div class="meta">Membre ${esc(x.user_id)} · ${ts(x.generated_at)}</div></div><a class="btn" target="_blank" rel="noopener" href="/api/guilds/${encodeURIComponent(state.guildId)}/ops/transcripts/${encodeURIComponent(x.id)}">Ouvrir</a></div>`).join("")||'<div class="muted">Aucun transcript généré.</div>'}
async function refreshSummary(){if(!state.guildId)return;try{state.summary=await api(`/api/guilds/${state.guildId}/ops/summary`);renderSummary()}catch{}}
async function saveAccess(enabled){const module=$("accessModule").value,role_id=$("accessRole").value;if(!role_id)return msg("Choisissez un rôle.",true);try{state.access=await api(`/api/guilds/${state.guildId}/ops/access`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({module,role_id,enabled})});renderAccess();msg("Permission mise à jour.")}catch(e){msg(e.message,true)}}
async function loadMember(){const id=$("memberId").value.trim();if(!id)return;try{const d=await api(`/api/guilds/${state.guildId}/ops/member/${encodeURIComponent(id)}`);state.memberId=id;const p=d.profile,u=p.user;$("memberResult").innerHTML=`<div class="item"><div class="grow"><b>${esc(u.display_name)} · ${esc(u.id)}</b><div class="meta">Sanctions ${p.sanctions.length} · warns ${p.warnings.length} · tickets ${p.tickets.length} · notes ${p.notes.length} · niveau ${esc(p.level.level)} · argent ${Number(p.economy.cash||0)+Number(p.economy.bank||0)} · invites ${esc(p.invites.total)}</div></div></div>`+p.notes.slice(0,8).map(n=>`<div class="item"><div class="grow"><b>Note staff</b><div class="meta">${esc(n.note)} · auteur ${esc(n.author_id)} · ${ts(n.created_at)}</div></div><button class="btn danger" data-note-delete="${esc(n.id)}">Supprimer</button></div>`).join("");document.querySelectorAll("[data-note-delete]").forEach(b=>b.onclick=()=>deleteNote(b.dataset.noteDelete))}catch(e){msg(e.message,true)}}
async function addNote(){if(!state.memberId)return msg("Chargez un membre.",true);try{await api(`/api/guilds/${state.guildId}/ops/member/${state.memberId}/notes`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({note:$("memberNote").value})});$("memberNote").value="";await loadMember();msg("Note ajoutée.")}catch(e){msg(e.message,true)}}
async function deleteNote(id){try{await api(`/api/guilds/${state.guildId}/ops/notes/${id}`,{method:"DELETE",headers:{"X-CSRF-Token":state.csrf}});await loadMember();msg("Note supprimée.")}catch(e){msg(e.message,true)}}
async function loadCase(){const n=$("caseNumber").value;if(!n)return;try{const d=await api(`/api/guilds/${state.guildId}/ops/cases/${n}`);state.caseNumber=n;const c=d.case;$("caseResult").innerHTML=`<div class="item"><div class="grow"><b>Dossier #${esc(c.case_number)} · ${esc(c.action)}</b><div class="meta">Membre ${esc(c.user_id)} · modérateur ${esc(c.moderator_id)} · statut ${esc(c.status)}<br>Raison : ${esc(c.effective_reason||"-")}</div></div><span class="pill ${c.status==="void"?"bad":""}">${esc(c.status)}</span></div>`+(c.events||[]).map(e=>`<div class="item"><div class="grow"><b>${esc(e.event_type)}</b><div class="meta">${esc(e.value||"")} · auteur ${esc(e.actor_id)} · ${ts(e.created_at)}</div></div></div>`).join("")}catch(e){msg(e.message,true)}}
async function saveCase(){if(!state.caseNumber)return msg("Chargez un dossier.",true);const event_type=$("caseAction").value,value=$("caseValue").value;try{await api(`/api/guilds/${state.guildId}/ops/cases/${state.caseNumber}`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({event_type,value})});$("caseValue").value="";await loadCase();msg("Dossier mis à jour.")}catch(e){msg(e.message,true)}}
async function saveScope(raw,enabled=true){const value=raw||$("scopeTarget").value;if(!value)return;const [target_type,target_id]=value.split(":");try{state.scopes=await api(`/api/guilds/${state.guildId}/ops/automod-scopes`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({target_type,target_id,enabled})});renderScopes();msg("Exception AutoMod mise à jour.")}catch(e){msg(e.message,true)}}
async function createBackup(){try{await api(`/api/guilds/${state.guildId}/ops/backups`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({label:$("backupLabel").value})});await loadBackups();msg("Backup créé.")}catch(e){msg(e.message,true)}}
async function loadBackups(){const d=await api(`/api/guilds/${state.guildId}/ops/backups`);$("backupList").innerHTML=(d.backups||[]).map(b=>`<div class="item"><div class="grow"><b>#${esc(b.id)} · ${esc(b.label)}</b><div class="meta">${ts(b.created_at)}</div></div><select data-restore-part="${esc(b.id)}" style="max-width:130px"><option value="roles">Rôles</option><option value="channels">Salons</option><option value="permissions">Permissions</option></select><button class="btn" data-restore="${esc(b.id)}">Restaurer</button></div>`).join("")||'<div class="muted">Aucun backup.</div>';document.querySelectorAll("[data-restore]").forEach(btn=>btn.onclick=()=>restoreBackup(btn.dataset.restore))}
async function restoreBackup(id){const sel=document.querySelector(`[data-restore-part="${CSS.escape(String(id))}"]`);const part=sel?.value;if(!confirm(`Restaurer ${part} depuis le backup #${id} ?`))return;try{const d=await api(`/api/guilds/${state.guildId}/ops/backups/${id}/restore`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({part})});msg(`${d.result.restored} élément(s) restauré(s).`)}catch(e){msg(e.message,true)}}
async function saveCustom(){try{state.custom=await api(`/api/guilds/${state.guildId}/ops/custom-commands`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({name:$("customName").value,response:$("customResponse").value,allowed_role_id:$("customRole").value||null,enabled:true})});renderCustom();msg("Commande enregistrée.")}catch(e){msg(e.message,true)}}
async function deleteCustom(id){if(!confirm("Supprimer cette commande personnalisée ?"))return;try{await api(`/api/guilds/${state.guildId}/ops/custom-commands/${id}`,{method:"DELETE",headers:{"X-CSRF-Token":state.csrf}});state.custom=await api(`/api/guilds/${state.guildId}/ops/custom-commands`);renderCustom();msg("Commande supprimée.")}catch(e){msg(e.message,true)}}
async function saveQuestion(){try{state.forms=await api(`/api/guilds/${state.guildId}/ops/ticket-forms/questions`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify({ticket_type_id:$("formType").value,label:$("formLabel").value,placeholder:$("formPlaceholder").value,style:$("formStyle").value,required:$("formRequired").checked,min_length:$("formMin").value,max_length:$("formMax").value})});$("formLabel").value="";renderForms();msg("Question ajoutée.")}catch(e){msg(e.message,true)}}
async function deleteQuestion(id){try{await api(`/api/guilds/${state.guildId}/ops/ticket-forms/questions/${id}`,{method:"DELETE",headers:{"X-CSRF-Token":state.csrf}});state.forms=await api(`/api/guilds/${state.guildId}/ops/ticket-forms`);renderForms();msg("Question supprimée.")}catch(e){msg(e.message,true)}}
async function generateTranscript(){const id=$("transcriptTicket").value;if(!id)return;try{await api(`/api/guilds/${state.guildId}/ops/tickets/${id}/transcript`,{method:"POST",headers:{"X-CSRF-Token":state.csrf}});await searchTranscripts();msg("Transcript HTML généré.")}catch(e){msg(e.message,true)}}
async function searchTranscripts(){const q=$("transcriptSearch").value.trim();state.transcripts=await api(`/api/guilds/${state.guildId}/ops/transcripts?q=${encodeURIComponent(q)}`);renderTranscripts()}
async function runDiag(){try{const d=await api(`/api/guilds/${state.guildId}/ops/diagnostics`,{method:"POST",headers:{"X-CSRF-Token":state.csrf}});msg(d.diagnostics.ok?"Diagnostic terminé : aucun problème critique.":"Diagnostic terminé : vérifiez les alertes.",!d.diagnostics.ok);await refreshSummary()}catch(e){msg(e.message,true)}}
function filterCards(q){const text=String(q||"").trim().toLowerCase();document.querySelectorAll("#cards .card").forEach(card=>{const hay=(card.dataset.search+" "+card.textContent).toLowerCase();card.classList.toggle("hidden",Boolean(text)&&!hay.includes(text))})}
$("guild").onchange=()=>loadGuild($("guild").value);$("refresh").onclick=()=>loadGuild(state.guildId);$("search").oninput=()=>filterCards($("search").value);$("accessAdd").onclick=()=>saveAccess(true);$("accessRemove").onclick=()=>saveAccess(false);$("memberLoad").onclick=loadMember;$("memberNoteAdd").onclick=addNote;$("caseLoad").onclick=loadCase;$("caseSave").onclick=saveCase;$("scopeAdd").onclick=()=>saveScope(null,true);$("backupCreate").onclick=createBackup;$("customSave").onclick=saveCustom;$("formSave").onclick=saveQuestion;$("transcriptGenerate").onclick=generateTranscript;$("transcriptSearch").oninput=()=>{clearTimeout(searchTranscripts.t);searchTranscripts.t=setTimeout(()=>searchTranscripts().catch(()=>{}),350)};$("diagRun").onclick=runDiag;
setInterval(refreshSummary,5000);boot().then(()=>loadBackups().catch(()=>{}));
</script>
</body></html>"""
