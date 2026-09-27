"""SentriX dashboard assistance: feedback, diagnostics and short onboarding.

This module is intentionally isolated from the core dashboard. It adds read-only diagnostics,
a four-step onboarding flow and a minimal feedback form. Automatic repair is restricted to
already-broken, reversible states and never creates Discord channels, roles or panels.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import discord
from aiohttp import web

import config
from utils import log_service

logger = logging.getLogger("bot.dashboard.guidance-v56")
_INSTALLED = False

AUTOMOD_KEYS = (
    "antispam", "antilink", "antiinvite", "antimention", "anticaps", "antiemoji",
    "antiraid", "antibot", "antiaccount", "antiscam", "antinuke", "escalation",
)
ROLE_FIELDS = (
    "mod_role", "admin_role", "mute_role", "verification_role", "verify_role",
    "autorole", "warn_role", "member_role", "booster_role",
)
CHANNEL_FIELDS = (
    "log_channel", "welcome_channel", "goodbye_channel", "rules_channel",
    "verification_channel", "ticket_log_channel", "level_channel", "suggest_channel",
    "announce_channel", "giveaway_channel", "bot_commands_channel", "report_channel",
    "partner_channel", "stats_channel", "afk_channel", "error_channel", "log_messages",
    "log_members", "log_voice", "log_roles", "log_server", "log_automod", "log_moderation",
)
PERMISSION_CHECKS = (
    ("manage_roles", "Gérer les rôles"),
    ("manage_channels", "Gérer les salons"),
    ("manage_messages", "Gérer les messages"),
    ("ban_members", "Bannir des membres"),
    ("kick_members", "Expulser des membres"),
    ("moderate_members", "Exclure temporairement des membres"),
    ("view_audit_log", "Voir le journal d'audit"),
    ("send_messages", "Envoyer des messages"),
    ("embed_links", "Intégrer des liens"),
    ("attach_files", "Joindre des fichiers"),
)


def _json_error(dashboard, message: str, status: int = 400):
    return dashboard._json_error(message, status)


async def _ctx(dashboard, request: web.Request, *, write: bool = False):
    try:
        guild_id = int(request.match_info["guild_id"])
    except (KeyError, TypeError, ValueError):
        return None, None, None, _json_error(dashboard, "Serveur invalide.", 400)
    session, guild, error = await dashboard._manageable_guild(request, guild_id)
    if error:
        return None, None, None, error
    if write:
        csrf_error = dashboard._require_csrf(request, session)
        if csrf_error:
            return None, None, None, csrf_error
    return session, guild, request.app["bot"], None


async def _ensure_tables(bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_feedback_v1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            rating INTEGER,
            page TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL,
            technical_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'new',
            created_at INTEGER NOT NULL
        )
        """
    )


def _clean(value: Any, maximum: int) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:maximum]


def _snowflake(value: Any) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


async def api_feedback(dashboard, request: web.Request):
    session, guild, bot, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    await _ensure_tables(bot)
    try:
        payload = await request.json()
    except Exception:
        return _json_error(dashboard, "Le formulaire est invalide.", 400)
    if not isinstance(payload, dict):
        return _json_error(dashboard, "Le formulaire est invalide.", 400)

    kind = str(payload.get("kind") or "").strip().casefold()
    if kind not in {"bug", "opinion"}:
        return _json_error(dashboard, "Choisissez Bug ou Avis.", 400)
    message = _clean(payload.get("message"), 1800)
    if len(message) < 8:
        return _json_error(dashboard, "Ajoutez un peu plus de détails.", 400)

    rating = None
    if kind == "opinion" and payload.get("rating") not in (None, ""):
        try:
            rating = int(payload.get("rating"))
        except (TypeError, ValueError):
            return _json_error(dashboard, "La note doit être comprise entre 1 et 5.", 400)
        if not 1 <= rating <= 5:
            return _json_error(dashboard, "La note doit être comprise entre 1 et 5.", 400)

    user_id = int(session["user"]["id"])
    now_ts = int(time.time())
    recent = await bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM dashboard_feedback_v1 "
        "WHERE guild_id=? AND user_id=? AND created_at>=?",
        (guild.id, user_id, now_ts - 60),
    )
    if recent and int(recent["n"] or 0) >= 3:
        return _json_error(dashboard, "Trop de retours envoyés. Réessayez dans une minute.", 429)

    technical = payload.get("technical") if isinstance(payload.get("technical"), dict) else {}
    safe_technical = {
        "tab": _clean(technical.get("tab"), 40),
        "error": _clean(technical.get("error"), 240),
        "viewport": _clean(technical.get("viewport"), 40),
    }
    cur = await bot.db.execute(
        "INSERT INTO dashboard_feedback_v1 "
        "(guild_id,user_id,kind,rating,page,message,technical_json,status,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            guild.id, user_id, kind, rating, _clean(payload.get("page"), 120), message,
            json.dumps(safe_technical, ensure_ascii=False, separators=(",", ":")),
            "new", now_ts,
        ),
    )
    feedback_id = int(getattr(cur, "lastrowid", 0) or 0)
    logger.info("Dashboard feedback guild=%s user=%s kind=%s id=%s", guild.id, user_id, kind, feedback_id)
    return web.json_response({"ok": True, "id": feedback_id, "message": "Merci. Votre retour a bien été enregistré."})


async def _ticket_state(bot, guild: discord.Guild) -> dict:
    try:
        rows = await bot.db.fetchall(
            "SELECT p.id,p.name,p.channel_id,p.enabled,"
            "(SELECT COUNT(*) FROM ticket_types t WHERE t.panel_id=p.id) AS type_count "
            "FROM ticket_panels_v2 p WHERE p.guild_id=? ORDER BY p.id DESC LIMIT 100",
            (guild.id,),
        )
    except Exception:
        rows = []
    ready = 0
    orphan = []
    for raw in rows:
        row = dict(raw)
        channel_id = _snowflake(row.get("channel_id"))
        channel_ok = bool(channel_id and guild.get_channel(channel_id))
        if channel_id and not channel_ok:
            orphan.append(int(row["id"]))
        if bool(row.get("enabled")) and int(row.get("type_count") or 0) > 0 and channel_ok:
            ready += 1
    return {"count": len(rows), "ready": ready > 0, "ready_count": ready, "orphan_ids": orphan}


async def _log_state(bot, guild: discord.Guild) -> dict:
    configured = 0
    invalid = []
    total = 0
    for category in log_service.LOG_TYPES:
        total += 1
        try:
            row = await log_service.get_log_config(bot, guild.id, category, fresh=True)
        except Exception:
            row = None
        channel_id = _snowflake(row.get("channel_id") if row else None)
        if not channel_id:
            continue
        if guild.get_channel(channel_id) is None:
            invalid.append(category)
        elif bool(row.get("enabled", True)):
            configured += 1
    return {"configured": configured, "total": total, "invalid": invalid}


async def _diagnostic(bot, guild: discord.Guild) -> dict:
    conf_row = await bot.db.get_guild_config(guild.id)
    automod_row = await bot.db.get_automod(guild.id)
    conf = dict(conf_row) if conf_row else {}
    automod = dict(automod_row) if automod_row else {}

    try:
        ai_row = await bot.db.fetchone("SELECT enabled FROM ai_settings WHERE guild_id=?", (guild.id,))
    except Exception:
        ai_row = None
    ai_enabled = bool(ai_row and int(ai_row["enabled"] or 0))
    ai_provider_ready = bool(getattr(config, "OPENAI_API_KEY", None))

    me = guild.me
    if me is None:
        missing_permissions = [label for _, label in PERMISSION_CHECKS]
    else:
        missing_permissions = [
            label for attr, label in PERMISSION_CHECKS
            if not bool(getattr(me.guild_permissions, attr, False))
        ]

    role_issues = []
    if me is not None:
        for field in ROLE_FIELDS:
            role_id = _snowflake(conf.get(field))
            if not role_id:
                continue
            role = guild.get_role(role_id)
            if role is None:
                role_issues.append(field + " : rôle supprimé")
            elif role.managed or role.is_default() or role >= me.top_role:
                role_issues.append(role.name + " : au-dessus de SentriX ou non modifiable")

    channel_issues = []
    for field in CHANNEL_FIELDS:
        channel_id = _snowflake(conf.get(field))
        if channel_id and guild.get_channel(channel_id) is None:
            channel_issues.append(field + " : salon supprimé")

    logs = await _log_state(bot, guild)
    tickets = await _ticket_state(bot, guild)
    active_security = sum(1 for key in AUTOMOD_KEYS if int(automod.get(key) or 0) == 1)
    security_ready = active_security >= 3
    welcome_id = _snowflake(conf.get("welcome_channel"))
    welcome_ready = bool(welcome_id and guild.get_channel(welcome_id))
    logs_ready = logs["configured"] > 0
    tickets_ready = bool(tickets["ready"])
    latency_ms = max(0, round(float(getattr(bot, "latency", 0) or 0) * 1000))

    issues = []

    def issue(key, severity, title, detail, tab=None, fix=None):
        issues.append({
            "key": key, "severity": severity, "title": title, "detail": detail,
            "tab": tab, "fix": fix,
        })

    if missing_permissions:
        detail = "Manquantes : " + ", ".join(missing_permissions[:6])
        if len(missing_permissions) > 6:
            detail += "…"
        issue("permissions", "bad", "Permissions Discord incomplètes", detail, "roles")
    if role_issues:
        detail = role_issues[0]
        if len(role_issues) > 1:
            detail += " et " + str(len(role_issues) - 1) + " autre(s)."
        issue("roles", "bad", "Hiérarchie des rôles à corriger", detail, "roles")
    if channel_issues:
        issue("channels", "warn", "Références vers des salons supprimés",
              str(len(channel_issues)) + " réglage(s) pointent vers un salon supprimé.", "general")
    if logs["invalid"]:
        issue("logs-invalid", "warn", "Routes de logs cassées",
              str(len(logs["invalid"])) + " catégorie(s) utilisent un salon supprimé.",
              "logs", "disable_invalid_logs")
    elif not logs_ready:
        issue("logs-empty", "warn", "Logs non configurés",
              "Aucune catégorie de logs n'est reliée à un salon.", "logs")
    if tickets["orphan_ids"]:
        issue("tickets-orphan", "warn", "Panel de tickets relié à un salon supprimé",
              str(len(tickets["orphan_ids"])) + " panel(s) n'ont plus de salon valide.",
              "tickets", "disable_orphan_ticket_panels")
    elif not tickets_ready:
        issue("tickets-empty", "warn", "Tickets à terminer",
              "Il faut un panel actif, au moins un type et un salon de publication valide.", "tickets")
    if ai_enabled and not ai_provider_ready:
        issue("ai-provider", "bad", "IA activée mais fournisseur indisponible",
              "La clé du fournisseur IA n'est pas chargée sur cette instance.", "ai")
    if not security_ready:
        issue("security", "warn", "Sécurité de base incomplète",
              str(active_security) + "/" + str(len(AUTOMOD_KEYS)) + " protections actives.", "security")
    if not welcome_ready:
        issue("welcome", "warn", "Accueil non configuré",
              "Aucun salon de bienvenue valide n'est configuré.", "welcome")
    if latency_ms > 450:
        issue("latency", "warn", "Latence Discord élevée", "Latence actuelle : " + str(latency_ms) + " ms.")

    bad_count = sum(1 for item in issues if item["severity"] == "bad")
    warn_count = sum(1 for item in issues if item["severity"] == "warn")
    score = max(0, min(100, 100 - bad_count * 18 - warn_count * 7))

    onboarding = [
        {"key": "security", "title": "Sécurité", "ready": security_ready,
         "detail": str(active_security) + "/" + str(len(AUTOMOD_KEYS)) + " protections actives",
         "href": "/app?guild=" + str(guild.id) + "&tab=security"},
        {"key": "logs", "title": "Logs", "ready": logs_ready and not logs["invalid"],
         "detail": str(logs["configured"]) + "/" + str(logs["total"]) + " catégories reliées",
         "href": "/app?guild=" + str(guild.id) + "&tab=logs"},
        {"key": "tickets", "title": "Tickets", "ready": tickets_ready and not tickets["orphan_ids"],
         "detail": (str(tickets["ready_count"]) + " panel(s) prêt(s)") if tickets_ready else "Panel, type et publication à terminer",
         "href": "/app?guild=" + str(guild.id) + "&tab=tickets"},
        {"key": "welcome", "title": "Bienvenue", "ready": welcome_ready,
         "detail": "Salon d'accueil configuré" if welcome_ready else "Salon d'accueil à choisir",
         "href": "/app?guild=" + str(guild.id) + "&tab=welcome"},
    ]

    systems = [
        {"name": "SentriX", "status": "ok" if bot.is_ready() else "bad",
         "detail": "Connecté à Discord" if bot.is_ready() else "Connexion Discord indisponible"},
        {"name": "Permissions", "status": "ok" if not missing_permissions else "bad",
         "detail": "Toutes les permissions principales sont disponibles" if not missing_permissions else str(len(missing_permissions)) + " permission(s) manquante(s)"},
        {"name": "Hiérarchie des rôles", "status": "ok" if not role_issues else "bad",
         "detail": "Rôles configurés modifiables" if not role_issues else str(len(role_issues)) + " problème(s)"},
        {"name": "Logs", "status": "ok" if logs_ready and not logs["invalid"] else "warn",
         "detail": str(logs["configured"]) + "/" + str(logs["total"]) + " catégories opérationnelles"},
        {"name": "Tickets", "status": "ok" if tickets_ready and not tickets["orphan_ids"] else "warn",
         "detail": "Panel publié et utilisable" if tickets_ready else "Configuration incomplète"},
        {"name": "IA", "status": "ok" if (not ai_enabled or ai_provider_ready) else "bad",
         "detail": "Activée et disponible" if ai_enabled and ai_provider_ready else ("Désactivée" if not ai_enabled else "Fournisseur absent")},
        {"name": "Bienvenue", "status": "ok" if welcome_ready else "warn",
         "detail": "Salon valide" if welcome_ready else "À configurer"},
    ]
    return {
        "ok": True,
        "guild": {"id": str(guild.id), "name": guild.name, "members": guild.member_count or 0},
        "score": score, "latency_ms": latency_ms, "issues": issues, "systems": systems,
        "onboarding": onboarding,
        "summary": {
            "bad": bad_count,
            "warn": warn_count,
            "ok": sum(1 for item in systems if item["status"] == "ok"),
        },
    }


async def api_diagnostic(dashboard, request: web.Request):
    _session, guild, bot, error = await _ctx(dashboard, request)
    if error:
        return error
    return web.json_response(await _diagnostic(bot, guild))


async def api_fix(dashboard, request: web.Request):
    _session, guild, bot, error = await _ctx(dashboard, request, write=True)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        return _json_error(dashboard, "Action invalide.", 400)
    action = str(payload.get("action") or "") if isinstance(payload, dict) else ""

    if action == "disable_invalid_logs":
        repaired = 0
        for category in log_service.LOG_TYPES:
            try:
                row = await log_service.get_log_config(bot, guild.id, category, fresh=True)
            except Exception:
                continue
            channel_id = _snowflake(row.get("channel_id") if row else None)
            if channel_id and guild.get_channel(channel_id) is None:
                await log_service.set_log_config(bot, guild.id, category, channel_id=None, enabled=False)
                repaired += 1
        return web.json_response({
            "ok": True, "repaired": repaired,
            "message": str(repaired) + " route(s) de logs cassée(s) ont été désactivées sans créer de salon.",
        })

    if action == "disable_orphan_ticket_panels":
        try:
            rows = await bot.db.fetchall(
                "SELECT id,channel_id FROM ticket_panels_v2 WHERE guild_id=? AND enabled=1",
                (guild.id,),
            )
        except Exception:
            rows = []
        repaired = 0
        for row in rows:
            channel_id = _snowflake(row["channel_id"])
            if channel_id and guild.get_channel(channel_id) is None:
                await bot.db.execute(
                    "UPDATE ticket_panels_v2 SET enabled=0 WHERE guild_id=? AND id=?",
                    (guild.id, int(row["id"])),
                )
                repaired += 1
        return web.json_response({
            "ok": True, "repaired": repaired,
            "message": str(repaired) + " panel(s) orphelin(s) ont été désactivés. Rien n'a été supprimé.",
        })

    return _json_error(dashboard, "Cette réparation automatique n'est pas autorisée.", 400)


async def handle_diagnostic_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login?next=/diagnostic")
    return web.Response(text=DIAGNOSTIC_HTML, content_type="text/html",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


async def handle_onboarding_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login?next=/onboarding")
    return web.Response(text=ONBOARDING_HTML, content_type="text/html",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


async def handle_feedback_page(request: web.Request):
    dashboard = request.app["dashboard_module"]
    session, error = dashboard._require_session(request)
    if error or not session:
        raise web.HTTPFound("/login?next=/feedback")
    return web.Response(text=FEEDBACK_HTML, content_type="text/html",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


INJECT_CSS = r"""
<style id="sentrix-guidance-v56-css">
.sx-guide-strip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:14px 0 4px}
.sx-guide-card{display:flex;flex-direction:column;justify-content:space-between;gap:13px;min-height:142px;padding:16px;border:1px solid #293249;border-radius:15px;background:linear-gradient(150deg,#111824,#0c111b);box-shadow:0 16px 36px #0004}
.sx-guide-card b{font-size:14px;color:#f0f3fb}.sx-guide-card p{margin:6px 0 0;color:#8894aa;font-size:11px;line-height:1.55}
.sx-guide-card button{align-self:flex-start;border:1px solid #3a4661;border-radius:9px;background:#171f2d;color:#eef2fb;padding:8px 10px;font-size:10px;font-weight:850;cursor:pointer}
.sx-guide-card .primary{border-color:#4c8cce;background:#16304e;color:#cfe8ff}
.sx-feedback-fab{position:fixed;right:20px;bottom:20px;z-index:96;border:1px solid #3b4963;border-radius:11px;background:#111a28;color:#eaf1fb;padding:9px 12px;font:800 10px Inter,system-ui,sans-serif;box-shadow:0 14px 35px #0008;cursor:pointer}
.sx-feedback-backdrop{position:fixed;inset:0;z-index:220;display:grid;place-items:center;padding:18px;background:#050810c7;backdrop-filter:blur(7px)}
.sx-feedback-backdrop.hidden{display:none!important}.sx-feedback-modal{width:min(560px,100%);border:1px solid #34415a;border-radius:16px;background:#0c121c;box-shadow:0 28px 80px #000b;overflow:hidden}
.sx-feedback-head{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:16px 17px;border-bottom:1px solid #252e40}.sx-feedback-head h3{margin:0;font-size:16px}.sx-feedback-close{border:0;background:transparent;color:#aeb8ca;font-size:20px;cursor:pointer}
.sx-feedback-body{display:grid;gap:12px;padding:16px}.sx-feedback-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.sx-feedback-body label{display:grid;gap:5px;color:#aab4c5;font-size:10px;font-weight:800}.sx-feedback-body select,.sx-feedback-body textarea{width:100%;border:1px solid #303a50;border-radius:9px;background:#111925;color:#eef2f8;padding:9px 10px;font:inherit}.sx-feedback-body textarea{min-height:120px;resize:vertical}.sx-feedback-tech{display:flex!important;grid-template-columns:auto 1fr!important;align-items:flex-start;gap:8px!important;font-weight:600!important}.sx-feedback-tech input{margin-top:2px}.sx-feedback-actions{display:flex;justify-content:flex-end;gap:8px}.sx-feedback-actions button{border:1px solid #3a465e;border-radius:9px;background:#171f2d;color:#edf1f8;padding:9px 12px;font-weight:850;cursor:pointer}.sx-feedback-actions .primary{background:#286fb4;border-color:#4298e8;color:#07131f}.sx-feedback-status{min-height:18px;color:#8ea0b8;font-size:10px}.sx-feedback-status.bad{color:#f196a3}
@media(max-width:800px){.sx-guide-strip{grid-template-columns:1fr}.sx-feedback-fab{right:12px;bottom:12px}.sx-feedback-grid{grid-template-columns:1fr}}
</style>
"""


INJECT_JS = r"""
<script id="sentrix-guidance-v56-js">
(function(){
  "use strict";
  if(window.__sentrixGuidanceV56)return;
  window.__sentrixGuidanceV56=true;
  var latestError="";
  function gid(){try{return typeof state!=="undefined"&&state.guildId?String(state.guildId):""}catch(e){return""}}
  function csrf(){try{return typeof state!=="undefined"?String(state.csrf||""):""}catch(e){return""}}
  function tab(){try{return typeof state!=="undefined"?String(state.tab||""):""}catch(e){return""}}
  function remember(value){var text=String(value&&value.message?value.message:value||"").replace(/\s+/g," ").trim();if(text)latestError=text.slice(0,240)}
  window.addEventListener("error",function(event){remember(event.message)});
  window.addEventListener("unhandledrejection",function(event){remember(event.reason)});
  function needGuild(){var id=gid();if(id)return id;try{if(typeof toast==="function")toast("Choisissez d'abord un serveur.",true)}catch(e){}return""}
  function go(path){var id=needGuild();if(id)location.href=path+"?guild="+encodeURIComponent(id)}

  function ensureModal(){
    if(document.getElementById("sxFeedbackModal"))return;
    var backdrop=document.createElement("div");
    backdrop.id="sxFeedbackModal";backdrop.className="sx-feedback-backdrop hidden";
    backdrop.innerHTML='<section class="sx-feedback-modal" role="dialog" aria-modal="true" aria-labelledby="sxFeedbackTitle">'+
      '<div class="sx-feedback-head"><h3 id="sxFeedbackTitle">Signaler un bug ou donner un avis</h3><button class="sx-feedback-close" type="button" aria-label="Fermer">×</button></div>'+
      '<div class="sx-feedback-body"><div class="sx-feedback-grid">'+
      '<label>Type<select id="sxFeedbackKind"><option value="bug">Bug</option><option value="opinion">Avis</option></select></label>'+
      '<label>Note<select id="sxFeedbackRating"><option value="">Sans note</option><option value="5">5 / 5</option><option value="4">4 / 5</option><option value="3">3 / 5</option><option value="2">2 / 5</option><option value="1">1 / 5</option></select></label></div>'+
      '<label>Votre message<textarea id="sxFeedbackText" maxlength="1800" placeholder="Expliquez ce qui s est passé ou ce que vous aimeriez améliorer."></textarea></label>'+
      '<label class="sx-feedback-tech"><input id="sxFeedbackTech" type="checkbox" checked><span>Inclure uniquement le contexte technique minimal : page, onglet, taille de fenêtre et dernier message d erreur. Aucun cookie, token, contenu Discord ou secret n est envoyé.</span></label>'+
      '<div class="sx-feedback-status" id="sxFeedbackStatus"></div><div class="sx-feedback-actions"><button type="button" data-sx-feedback-cancel>Annuler</button><button class="primary" id="sxFeedbackSend" type="button">Envoyer</button></div></div></section>';
    document.body.appendChild(backdrop);
    function close(){backdrop.classList.add("hidden")}
    var closeButton=backdrop.querySelector(".sx-feedback-close");if(closeButton)closeButton.addEventListener("click",close);
    var cancel=backdrop.querySelector("[data-sx-feedback-cancel]");if(cancel)cancel.addEventListener("click",close);
    backdrop.addEventListener("click",function(event){if(event.target===backdrop)close()});
    var send=document.getElementById("sxFeedbackSend");if(send)send.addEventListener("click",sendFeedback);
  }

  function openFeedback(){
    if(!needGuild())return;ensureModal();
    var status=document.getElementById("sxFeedbackStatus");if(status){status.textContent="";status.className="sx-feedback-status"}
    var modal=document.getElementById("sxFeedbackModal");if(modal)modal.classList.remove("hidden");
    setTimeout(function(){var text=document.getElementById("sxFeedbackText");if(text)text.focus()},20);
  }

  async function sendFeedback(){
    var id=needGuild();if(!id)return;
    var button=document.getElementById("sxFeedbackSend"),status=document.getElementById("sxFeedbackStatus");
    var kind=document.getElementById("sxFeedbackKind").value||"bug";
    var rating=document.getElementById("sxFeedbackRating").value||"";
    var message=document.getElementById("sxFeedbackText").value||"";
    var include=document.getElementById("sxFeedbackTech").checked;
    if(message.trim().length<8){if(status){status.textContent="Ajoutez un peu plus de détails.";status.className="sx-feedback-status bad"}return}
    if(button)button.disabled=true;
    try{
      var response=await fetch("/api/guilds/"+id+"/feedback-v1",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf()},body:JSON.stringify({kind:kind,rating:rating||null,message:message,page:location.pathname,technical:include?{tab:tab(),error:latestError,viewport:String(innerWidth)+"x"+String(innerHeight)}:{}})});
      var data=await response.json().catch(function(){return{}});
      if(!response.ok)throw new Error(data.error||"Envoi impossible.");
      if(status){status.textContent=data.message||"Retour enregistré.";status.className="sx-feedback-status"}
      document.getElementById("sxFeedbackText").value="";
      setTimeout(function(){var modal=document.getElementById("sxFeedbackModal");if(modal)modal.classList.add("hidden")},900);
    }catch(error){
      if(status){status.textContent=error.message||"Envoi impossible.";status.className="sx-feedback-status bad"}
    }finally{if(button)button.disabled=false}
  }

  function mount(){
    ensureModal();
    if(!document.getElementById("sxFeedbackFab")){
      var fab=document.createElement("button");fab.id="sxFeedbackFab";fab.className="sx-feedback-fab";fab.type="button";fab.textContent="Bug / Avis";fab.addEventListener("click",openFeedback);document.body.appendChild(fab);
    }
    var home=document.getElementById("sxSimpleHome");
    if(home&&!document.getElementById("sxGuidanceStrip")){
      var strip=document.createElement("section");strip.id="sxGuidanceStrip";strip.className="sx-guide-strip";
      strip.innerHTML='<article class="sx-guide-card"><div><b>Centre de diagnostic</b><p>Permissions, rôles, logs, tickets, IA et configurations cassées en un seul écran.</p></div><button class="primary" type="button" data-sx-guide="diagnostic">Analyser le serveur</button></article>'+
        '<article class="sx-guide-card"><div><b>Configuration guidée</b><p>Parcours court : Sécurité, Logs, Tickets, Bienvenue.</p></div><button type="button" data-sx-guide="onboarding">Commencer</button></article>'+
        '<article class="sx-guide-card"><div><b>Votre avis</b><p>Signalez un bug ou proposez une amélioration sans envoyer de données sensibles.</p></div><button type="button" data-sx-guide="feedback">Envoyer un retour</button></article>';
      var grid=home.querySelector(".sx-simple-grid");if(grid)grid.insertAdjacentElement("beforebegin",strip);else home.appendChild(strip);
      strip.querySelector('[data-sx-guide="diagnostic"]').addEventListener("click",function(){go("/diagnostic")});
      strip.querySelector('[data-sx-guide="onboarding"]').addEventListener("click",function(){go("/onboarding")});
      strip.querySelector('[data-sx-guide="feedback"]').addEventListener("click",openFeedback);
    }
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",mount,{once:true});else mount();
  var observer=new MutationObserver(function(){mount();if(document.getElementById("sxGuidanceStrip"))observer.disconnect()});
  if(document.body)observer.observe(document.body,{childList:true,subtree:true});
})();
</script>
"""


def _inject(html: str) -> str:
    if 'id="sentrix-guidance-v56-js"' in html:
        return html
    if "</head>" in html:
        html = html.replace("</head>", INJECT_CSS + "\n</head>", 1)
    if "</body>" in html:
        html = html.replace("</body>", INJECT_JS + "\n</body>", 1)
    return html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    original_build_app = dashboard.build_app

    def build_app(bot):
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/diagnostic", handle_diagnostic_page)
        app.router.add_get("/onboarding", handle_onboarding_page)
        app.router.add_get("/feedback", handle_feedback_page)
        app.router.add_get("/api/guilds/{guild_id}/diagnostic-v1", lambda r: api_diagnostic(dashboard, r))
        app.router.add_post("/api/guilds/{guild_id}/diagnostic-v1/fix", lambda r: api_fix(dashboard, r))
        app.router.add_post("/api/guilds/{guild_id}/feedback-v1", lambda r: api_feedback(dashboard, r))
        return app

    dashboard.build_app = build_app
    dashboard.INDEX_HTML = _inject(dashboard.INDEX_HTML)
    logger.info("Dashboard Guidance V56 installé.")


COMMON_STYLE = r"""
:root{--bg:#080b12;--panel:#0f151f;--line:#29344a;--text:#f1f4f9;--muted:#8e9aaf;--ok:#62d4a5;--warn:#e9bb67;--bad:#ef7e91}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(900px 500px at 80% -10%,#17345755,transparent 60%),linear-gradient(180deg,#080b12,#0a0f18);color:var(--text);font:14px Inter,system-ui,-apple-system,"Segoe UI",sans-serif}a{color:inherit;text-decoration:none}button{font:inherit}.top{position:sticky;top:0;z-index:10;display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 4vw;border-bottom:1px solid var(--line);background:#080b12ed;backdrop-filter:blur(16px)}.brand{font-weight:900;font-size:17px}.top a,.btn{border:1px solid #36435a;border-radius:9px;background:#141b27;color:#eef2f8;padding:8px 11px;font-weight:800}.shell{max-width:1180px;margin:auto;padding:34px 22px 70px}.head{display:flex;justify-content:space-between;gap:18px;align-items:flex-end;margin-bottom:18px}.head h1{margin:0;font-size:34px;letter-spacing:-.04em}.head p{margin:7px 0 0;color:var(--muted)}.score{min-width:126px;border:1px solid #34445d;border-radius:16px;padding:14px;text-align:center;background:#0d1520}.score strong{display:block;font-size:30px}.score span{display:block;margin-top:4px;color:var(--muted);font-size:10px;text-transform:uppercase;font-weight:850}.grid{display:grid;gap:11px}.summary{grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:14px}.summary .box,.system,.issue,.step{border:1px solid var(--line);border-radius:13px;background:linear-gradient(150deg,var(--panel),#0c121b);padding:15px}.summary small,.system small{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;font-weight:850}.summary b{display:block;margin-top:7px;font-size:22px}.systems{grid-template-columns:repeat(2,minmax(0,1fr));margin:14px 0}.system{display:flex;justify-content:space-between;gap:14px;align-items:center}.system b{display:block}.system span{display:block;margin-top:4px;color:var(--muted);font-size:11px}.pill{padding:5px 8px;border-radius:999px;font-size:9px;font-weight:900;text-transform:uppercase}.pill.ok{background:#14372c;color:#8be0bd}.pill.warn{background:#392f18;color:#f0c978}.pill.bad{background:#3b1d25;color:#f5a0ae}.issues{display:grid;gap:9px}.issue{display:grid;grid-template-columns:1fr auto;gap:14px;align-items:center}.issue h3{margin:0 0 5px;font-size:13px}.issue p{margin:0;color:var(--muted);font-size:11px;line-height:1.5}.issue-actions{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}.issue-actions a,.issue-actions button{border:1px solid #384760;border-radius:8px;background:#151e2b;color:#eaf0f7;padding:7px 9px;font-size:9px;font-weight:850;cursor:pointer}.issue-actions .fix{border-color:#3f7bb2;background:#15304a}.empty{padding:24px;border:1px solid #264232;border-radius:13px;background:#0e2018;color:#a6e3c7}.progress{height:9px;border-radius:999px;background:#1b2432;overflow:hidden;margin:18px 0}.progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#4da3ff,#79bfff,#62d4a5);border-radius:999px}.steps{grid-template-columns:repeat(2,minmax(0,1fr))}.step{display:grid;grid-template-columns:42px 1fr auto;gap:12px;align-items:center}.step-num{width:42px;height:42px;display:grid;place-items:center;border:1px solid #35445d;border-radius:12px;background:#111a27;font-weight:900}.step h3{margin:0;font-size:14px}.step p{margin:4px 0 0;color:var(--muted);font-size:10px}.step a{border:1px solid #3b4a62;border-radius:8px;padding:7px 9px;background:#151e2a;font-size:9px;font-weight:850}.step.done{border-color:#285440}.step.done .step-num{background:#123225;border-color:#2c634b;color:#8be0bd}.notice{margin-top:16px;color:var(--muted);font-size:11px;line-height:1.55}.status{min-height:18px;margin-top:12px;color:#9bacc0;font-size:10px}.status.bad{color:#ef98a6}
@media(max-width:760px){.head{align-items:flex-start;flex-direction:column}.score{width:100%}.summary,.systems,.steps{grid-template-columns:1fr}.issue{grid-template-columns:1fr}.issue-actions{justify-content:flex-start}.step{grid-template-columns:42px 1fr}.step a{grid-column:2}}
"""


DIAGNOSTIC_HTML = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SentriX — Diagnostic</title><style>""" + COMMON_STYLE + """</style></head><body>
<header class="top"><div class="brand">SentriX · Diagnostic</div><a href="/app">Retour au dashboard</a></header>
<main class="shell"><div class="head"><div><h1 id="title">Analyse du serveur</h1><p>Permissions, rôles, logs, tickets, IA et réglages.</p></div><div class="score"><strong id="score">—</strong><span>Santé</span></div></div>
<section class="grid summary"><div class="box"><small>Opérationnel</small><b id="okCount">—</b></div><div class="box"><small>Attention</small><b id="warnCount">—</b></div><div class="box"><small>Bloquant</small><b id="badCount">—</b></div></section>
<section class="grid systems" id="systems"></section><section><h2>Points à corriger</h2><div class="issues" id="issues"><div class="issue">Chargement…</div></div></section><div class="status" id="status"></div></main>
<script>
(function(){
"use strict";
var gid=new URLSearchParams(location.search).get("guild")||"",csrf="";
function esc(v){return String(v==null?"":v).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
async function load(){
 if(!/^\\d{10,24}$/.test(gid)){document.getElementById("issues").innerHTML='<div class="issue"><div><h3>Serveur manquant</h3><p>Ouvrez ce centre depuis le dashboard après avoir choisi un serveur.</p></div></div>';return}
 try{
  var mr=await fetch("/api/me",{credentials:"same-origin",cache:"no-store"}),md=await mr.json().catch(function(){return{}});
  if(!mr.ok)throw new Error(md.error||"Session invalide");csrf=md.csrf||"";
  var r=await fetch("/api/guilds/"+gid+"/diagnostic-v1",{credentials:"same-origin",cache:"no-store"}),d=await r.json().catch(function(){return{}});
  if(!r.ok)throw new Error(d.error||"Diagnostic impossible");paint(d);
 }catch(e){var s=document.getElementById("status");s.textContent=e.message;s.className="status bad"}
}
function paint(d){
 document.getElementById("title").textContent="Diagnostic · "+d.guild.name;document.getElementById("score").textContent=d.score+"%";
 document.getElementById("okCount").textContent=d.summary.ok;document.getElementById("warnCount").textContent=d.summary.warn;document.getElementById("badCount").textContent=d.summary.bad;
 document.getElementById("systems").innerHTML=d.systems.map(function(x){var label=x.status==="ok"?"OK":x.status==="warn"?"Attention":"Erreur";return'<article class="system"><div><b>'+esc(x.name)+'</b><span>'+esc(x.detail)+'</span></div><span class="pill '+esc(x.status)+'">'+label+'</span></article>'}).join("");
 var root=document.getElementById("issues");
 if(!d.issues.length){root.innerHTML='<div class="empty">Aucun problème important détecté sur ce serveur.</div>';return}
 root.innerHTML=d.issues.map(function(x){var a=x.tab?'<a href="/app?guild='+encodeURIComponent(gid)+'&tab='+encodeURIComponent(x.tab)+'">Configurer</a>':"";var f=x.fix?'<button class="fix" data-fix="'+esc(x.fix)+'">Réparer sans risque</button>':"";return'<article class="issue"><div><h3>'+esc(x.title)+'</h3><p>'+esc(x.detail)+'</p></div><div class="issue-actions">'+a+f+'</div></article>'}).join("");
 root.querySelectorAll("[data-fix]").forEach(function(b){b.addEventListener("click",function(){fix(b,b.dataset.fix)})});
}
async function fix(button,action){
 button.disabled=true;var s=document.getElementById("status");
 try{var r=await fetch("/api/guilds/"+gid+"/diagnostic-v1/fix",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify({action:action})}),d=await r.json().catch(function(){return{}});if(!r.ok)throw new Error(d.error||"Réparation impossible");s.textContent=d.message||"Réparation terminée.";s.className="status";await load()}catch(e){s.textContent=e.message;s.className="status bad"}finally{button.disabled=false}
}
load();
})();
</script></body></html>"""


ONBOARDING_HTML = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SentriX — Configuration guidée</title><style>""" + COMMON_STYLE + """</style></head><body>
<header class="top"><div class="brand">SentriX · Configuration guidée</div><a href="/app">Retour au dashboard</a></header>
<main class="shell"><div class="head"><div><h1 id="title">Configurer un nouveau serveur</h1><p>Quatre étapes courtes. Rien n'est créé automatiquement.</p></div><div class="score"><strong id="progressText">0/4</strong><span>Étapes</span></div></div><div class="progress"><i id="progressBar"></i></div><section class="grid steps" id="steps"><div class="step">Chargement…</div></section><div class="notice">L'état est recalculé directement depuis le serveur : vous pouvez quitter et revenir plus tard.</div><div class="status" id="status"></div></main>
<script>
(function(){
"use strict";
var gid=new URLSearchParams(location.search).get("guild")||"";
function esc(v){return String(v==null?"":v).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
async function load(){
 if(!/^\\d{10,24}$/.test(gid)){document.getElementById("status").textContent="Choisissez d'abord un serveur dans le dashboard.";return}
 try{
  var r=await fetch("/api/guilds/"+gid+"/diagnostic-v1",{credentials:"same-origin",cache:"no-store"}),d=await r.json().catch(function(){return{}});
  if(!r.ok)throw new Error(d.error||"Chargement impossible");
  document.getElementById("title").textContent="Configurer · "+d.guild.name;
  var done=d.onboarding.filter(function(x){return x.ready}).length;
  document.getElementById("progressText").textContent=String(done)+"/4";document.getElementById("progressBar").style.width=String(done*25)+"%";
  document.getElementById("steps").innerHTML=d.onboarding.map(function(x,i){return'<article class="step '+(x.ready?"done":"")+'"><div class="step-num">'+String(i+1)+'</div><div><h3>'+esc(x.title)+(x.ready?" · Terminé":"")+'</h3><p>'+esc(x.detail)+'</p></div><a href="'+esc(x.href)+'">'+(x.ready?"Vérifier":"Configurer")+'</a></article>'}).join("");
  if(done===4)document.getElementById("status").innerHTML='Configuration essentielle terminée. <a href="/diagnostic?guild='+encodeURIComponent(gid)+'">Ouvrir le diagnostic complet</a>.';
 }catch(e){var s=document.getElementById("status");s.textContent=e.message;s.className="status bad"}
}
load();
})();
</script></body></html>"""


FEEDBACK_HTML = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SentriX — Bug / Avis</title><style>""" + COMMON_STYLE + """
<style>.feedback{max-width:720px;margin:0 auto;border:1px solid var(--line);border-radius:16px;background:linear-gradient(150deg,var(--panel),#0c121b);padding:18px}.feedback label{display:grid;gap:6px;margin-bottom:12px;color:#aab4c5;font-size:11px;font-weight:800}.feedback select,.feedback textarea{width:100%;border:1px solid #303a50;border-radius:9px;background:#111925;color:#eef2f8;padding:10px 11px;font:inherit}.feedback textarea{min-height:150px;resize:vertical}.feedback .row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.feedback .actions{display:flex;justify-content:flex-end;gap:8px}.feedback button{border:1px solid #3a465e;border-radius:9px;background:#286fb4;color:#07131f;padding:9px 12px;font-weight:850;cursor:pointer}.privacy{margin:8px 0 14px;color:var(--muted);font-size:10px;line-height:1.5}@media(max-width:620px){.feedback .row{grid-template-columns:1fr}}</style></head><body>
<header class="top"><div class="brand">SentriX · Bug / Avis</div><a href="/app">Retour au dashboard</a></header>
<main class="shell"><div class="head"><div><h1>Votre retour</h1><p>Signalez un bug ou proposez une amélioration sans exposer de données sensibles.</p></div></div>
<section class="feedback"><div class="row"><label>Type<select id="kind"><option value="bug">Bug</option><option value="opinion">Avis</option></select></label><label>Note<select id="rating"><option value="">Sans note</option><option value="5">5 / 5</option><option value="4">4 / 5</option><option value="3">3 / 5</option><option value="2">2 / 5</option><option value="1">1 / 5</option></select></label></div><label>Message<textarea id="message" maxlength="1800" placeholder="Expliquez ce qui s'est passé ou ce que vous aimeriez améliorer."></textarea></label><div class="privacy">Contexte envoyé : serveur choisi, cette page, taille de fenêtre et éventuellement le dernier message d'erreur. Aucun cookie, token, secret ou contenu de message Discord.</div><div class="actions"><button id="send" type="button">Envoyer</button></div><div class="status" id="status"></div></section></main>
<script>(function(){"use strict";var gid=new URLSearchParams(location.search).get("guild")||"",csrf="";async function load(){try{var r=await fetch("/api/me",{credentials:"same-origin",cache:"no-store"}),d=await r.json().catch(function(){return{}});if(!r.ok)throw new Error(d.error||"Session invalide");csrf=d.csrf||""}catch(e){var s=document.getElementById("status");s.textContent=e.message;s.className="status bad"}}async function send(){var s=document.getElementById("status"),b=document.getElementById("send"),m=document.getElementById("message").value||"";if(!/^\\d{10,24}$/.test(gid)){s.textContent="Choisissez d'abord un serveur dans le dashboard.";s.className="status bad";return}if(m.trim().length<8){s.textContent="Ajoutez un peu plus de détails.";s.className="status bad";return}b.disabled=true;try{var r=await fetch("/api/guilds/"+gid+"/feedback-v1",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","X-CSRF-Token":csrf},body:JSON.stringify({kind:document.getElementById("kind").value,rating:document.getElementById("rating").value||null,message:m,page:location.pathname,technical:{tab:"feedback",viewport:String(innerWidth)+"x"+String(innerHeight),error:""}})}),d=await r.json().catch(function(){return{}});if(!r.ok)throw new Error(d.error||"Envoi impossible");s.textContent=d.message||"Retour enregistré.";s.className="status";document.getElementById("message").value=""}catch(e){s.textContent=e.message;s.className="status bad"}finally{b.disabled=false}}document.getElementById("send").addEventListener("click",send);load()})();</script></body></html>"""
