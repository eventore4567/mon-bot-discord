"""SentriX V62 — finition dense, entièrement intégrée à ``/app``.

V62 ne crée pas un nouveau centre : il complète V61 juste avant le snapshot final.
Les réglages Tickets utilisent les vraies tables du cog Tickets v2 et la vérification
publie le vrai ``VerifyView``. Aucun bouton « Ouvrir » ne renvoie vers une vieille page.
"""
from __future__ import annotations

import json
import logging
import time

import discord
from aiohttp import web

from database.db import now

logger = logging.getLogger("bot.dashboard-v62-dense")
_INSTALLED_BACKEND = False


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


async def _ensure_verification_table(db) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS dashboard_verification_panels ("
        "guild_id INTEGER PRIMARY KEY, rules_text TEXT NOT NULL DEFAULT '', "
        "image_url TEXT, message_id INTEGER, updated_at INTEGER NOT NULL DEFAULT 0)"
    )


def _row_dict(row) -> dict:
    return dict(row) if row is not None else {}


def _safe_https(value: object, *, max_length: int = 1000) -> str:
    raw = str(value or "").strip()[:max_length]
    if raw and not raw.lower().startswith("https://"):
        raise ValueError("L'image doit utiliser une URL HTTPS publique.")
    return raw


def _int_or_none(value):
    if value in (None, "", 0, "0"):
        return None
    return int(value)


def _bounded_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _colour(value: object) -> int:
    raw = str(value or "5865F2").strip().lstrip("#")[:6]
    try:
        return int(raw, 16)
    except ValueError:
        return 0x5865F2


async def handle_v62_get(request: web.Request) -> web.Response:
    dashboard, _session, guild, error = await _context(request)
    if error:
        return error
    bot = request.app["bot"]
    db = bot.db
    await _ensure_verification_table(db)

    conf = await db.get_guild_config(guild.id)
    verification_row = await db.fetchone(
        "SELECT rules_text, image_url, message_id FROM dashboard_verification_panels WHERE guild_id = ?",
        (guild.id,),
    )
    verification = _row_dict(verification_row)
    verification.update({
        "role_id": str((conf["verify_role"] or conf["verification_role"] or "") if conf else ""),
        "channel_id": str((conf["verification_channel"] or "") if conf else ""),
        "captcha_enabled": bool(conf["verify_captcha_enabled"]) if conf else True,
        "captcha_max_attempts": int(conf["verify_captcha_max_attempts"] or 3) if conf else 3,
    })

    panels = [dict(row) for row in await db.fetchall(
        "SELECT * FROM ticket_panels_v2 WHERE guild_id = ? ORDER BY id ASC", (guild.id,)
    )]
    types = [dict(row) for row in await db.fetchall(
        "SELECT * FROM ticket_types WHERE guild_id = ? ORDER BY panel_id ASC, position ASC, id ASC", (guild.id,)
    )]
    type_ids = [int(item["id"]) for item in types]
    questions = []
    if type_ids:
        placeholders = ",".join("?" for _ in type_ids)
        questions = [dict(row) for row in await db.fetchall(
            f"SELECT * FROM ticket_form_questions WHERE ticket_type_id IN ({placeholders}) ORDER BY ticket_type_id, position, id",
            tuple(type_ids),
        )]

    try:
        from cogs.tickets import get_button_settings
        buttons = await get_button_settings(bot, guild.id)
    except Exception:
        logger.exception("V62 : lecture des boutons Tickets impossible.")
        buttons = {}

    return web.json_response({
        "ok": True,
        "verification": verification,
        "tickets": {"panels": panels, "types": types, "questions": questions, "buttons": buttons},
    })


async def _publish_verification(bot, guild: discord.Guild, *, channel: discord.TextChannel, rules: str, image_url: str, old_message_id: int | None):
    from cogs.verification import VerifyView

    cog = bot.get_cog("Verification")
    description = rules.strip()
    if cog is not None and hasattr(cog, "_embed"):
        embed = await cog._embed(guild.id, title="Règlement & vérification", description=description)
    else:
        from utils import embeds
        embed = embeds.brand("Règlement & vérification", description)
    if image_url:
        embed.set_image(url=image_url)
    view = VerifyView()

    if old_message_id:
        try:
            message = await channel.fetch_message(int(old_message_id))
            await message.edit(embed=embed, view=view)
            return message.id, "mis à jour"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    message = await channel.send(embed=embed, view=view)
    return message.id, "publié"


async def _ticket_panel_send(bot, guild: discord.Guild, panel_id: int):
    from cogs.tickets import TicketPanelView

    cog = bot.get_cog("Tickets")
    if cog is None:
        raise RuntimeError("Le module Tickets n'est pas disponible.")
    panel = await cog.get_panel(panel_id)
    if not panel or int(panel["guild_id"]) != guild.id:
        raise ValueError("Panel introuvable.")
    channel_id = panel["channel_id"]
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if not isinstance(channel, discord.TextChannel):
        raise ValueError("Choisissez d'abord le salon où publier le panel.")
    ticket_types = await cog.get_panel_types(panel_id)
    if not ticket_types:
        raise ValueError("Ajoutez au moins un type de ticket avant de publier le panel.")
    embed = cog.build_panel_embed(panel)
    view = TicketPanelView(panel, ticket_types)
    message_id = panel["message_id"]
    if message_id:
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(embed=embed, view=view)
            return message.id, "mis à jour"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    message = await channel.send(embed=embed, view=view)
    await bot.db.execute("UPDATE ticket_panels_v2 SET message_id = ? WHERE id = ?", (message.id, panel_id))
    return message.id, "publié"


async def handle_v62_post(request: web.Request) -> web.Response:
    dashboard, session, guild, error = await _context(request, write=True)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)
    if not isinstance(payload, dict):
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

    bot = request.app["bot"]
    db = bot.db
    await _ensure_verification_table(db)
    action = str(payload.get("action") or "").strip().lower()
    actor_id = int(session["user"]["id"])

    # Limite légère commune aux actions écriture V62.
    key = (request.cookies.get(dashboard.SESSION_COOKIE), guild.id, f"v62:{action}")
    current = time.time()
    if current - request.app["write_limits"].get(key, 0) < 0.5:
        return dashboard._json_error("Attendez un instant avant de recommencer.", 429)
    request.app["write_limits"][key] = current

    if action == "verification_save":
        try:
            channel_id = int(payload.get("channel_id"))
            role_id = int(payload.get("role_id"))
        except (TypeError, ValueError):
            return dashboard._json_error("Choisissez le salon et le rôle de vérification.", 400)
        channel = guild.get_channel(channel_id)
        role = guild.get_role(role_id)
        if not isinstance(channel, discord.TextChannel):
            return dashboard._json_error("Le règlement doit être publié dans un salon textuel.", 400)
        if role is None or role.is_default() or role.managed:
            return dashboard._json_error("Choisissez un rôle attribuable.", 400)
        if guild.me is None or not guild.me.guild_permissions.manage_roles or role >= guild.me.top_role:
            return dashboard._json_error("Le rôle choisi doit être placé sous le rôle SentriX et SentriX doit pouvoir gérer les rôles.", 400)
        rules = str(payload.get("rules_text") or "").strip()[:3900]
        if not rules:
            return dashboard._json_error("Écrivez votre règlement avant d'enregistrer.", 400)
        try:
            image_url = _safe_https(payload.get("image_url"))
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)
        captcha_enabled = bool(payload.get("captcha_enabled", True))
        max_attempts = _bounded_int(payload.get("captcha_max_attempts"), 1, 10, 3)

        await db.set_guild_config(guild.id, "verify_role", role_id)
        await db.set_guild_config(guild.id, "verification_role", role_id)
        await db.set_guild_config(guild.id, "verification_channel", channel_id)
        await db.set_guild_config(guild.id, "verify_captcha_enabled", int(captcha_enabled))
        await db.set_guild_config(guild.id, "verify_captcha_max_attempts", max_attempts)
        old = await db.fetchone("SELECT message_id FROM dashboard_verification_panels WHERE guild_id = ?", (guild.id,))
        old_message_id = int(old["message_id"]) if old and old["message_id"] else None
        message_id = old_message_id
        publication = "enregistré"
        if bool(payload.get("publish", False)):
            try:
                message_id, publication = await _publish_verification(
                    bot, guild, channel=channel, rules=rules, image_url=image_url, old_message_id=old_message_id
                )
            except discord.Forbidden:
                return dashboard._json_error("SentriX n'a pas la permission d'envoyer le règlement dans ce salon.", 403)
            except discord.HTTPException:
                logger.exception("V62 : publication du règlement impossible.")
                return dashboard._json_error("Discord a refusé la publication du règlement.", 502)
        await db.execute(
            "INSERT INTO dashboard_verification_panels (guild_id, rules_text, image_url, message_id, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET rules_text=excluded.rules_text,image_url=excluded.image_url,message_id=excluded.message_id,updated_at=excluded.updated_at",
            (guild.id, rules, image_url or None, message_id, now()),
        )
        try:
            await db.add_setup_history(guild.id, actor_id, "verification", "Règlement / vérification", f"salon={channel_id}; rôle={role_id}; captcha={captcha_enabled}")
        except Exception:
            pass
        return web.json_response({"ok": True, "message": f"Vérification {publication}e dans #{channel.name}.", "message_id": str(message_id or "")})

    if action == "ticket_panel_save":
        panel_id = _int_or_none(payload.get("panel_id"))
        name = str(payload.get("name") or "Panel")[:80].strip() or "Panel"
        title = str(payload.get("title") or "Support")[:256].strip() or "Support"
        description = str(payload.get("description") or "Choisissez une option ci-dessous pour ouvrir un ticket.")[:2000]
        image_url = str(payload.get("image_url") or "").strip()[:300] or None
        thumbnail_url = str(payload.get("thumbnail_url") or "").strip()[:300] or None
        footer_text = str(payload.get("footer_text") or "").strip()[:200] or None
        for value in (image_url, thumbnail_url):
            if value and not value.lower().startswith("https://"):
                return dashboard._json_error("Les images Tickets doivent utiliser une URL HTTPS.", 400)
        channel_id = _int_or_none(payload.get("channel_id"))
        if channel_id is not None and not isinstance(guild.get_channel(channel_id), discord.TextChannel):
            return dashboard._json_error("Le salon du panel Tickets est invalide.", 400)
        style = "button" if str(payload.get("style")) == "button" else "select"
        maximum = _bounded_int(payload.get("max_per_member"), 1, 20, 1)
        enabled = int(bool(payload.get("enabled", True)))
        color = _colour(payload.get("color"))
        if panel_id:
            row = await db.fetchone("SELECT id FROM ticket_panels_v2 WHERE id = ? AND guild_id = ?", (panel_id, guild.id))
            if not row:
                return dashboard._json_error("Panel Tickets introuvable.", 404)
            await db.execute(
                "UPDATE ticket_panels_v2 SET name=?,title=?,description=?,color=?,image_url=?,thumbnail_url=?,footer_text=?,channel_id=?,style=?,max_per_member=?,enabled=? WHERE id=? AND guild_id=?",
                (name, title, description, color, image_url, thumbnail_url, footer_text, channel_id, style, maximum, enabled, panel_id, guild.id),
            )
        else:
            cur = await db.execute(
                "INSERT INTO ticket_panels_v2 (guild_id,name,title,description,color,image_url,thumbnail_url,footer_text,channel_id,style,max_per_member,enabled,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (guild.id, name, title, description, color, image_url, thumbnail_url, footer_text, channel_id, style, maximum, enabled, now()),
            )
            panel_id = int(cur.lastrowid)
        return web.json_response({"ok": True, "message": "Panel Tickets enregistré.", "panel_id": str(panel_id)})

    if action == "ticket_panel_delete":
        panel_id = _int_or_none(payload.get("panel_id"))
        if not panel_id:
            return dashboard._json_error("Panel Tickets invalide.", 400)
        type_rows = await db.fetchall("SELECT id FROM ticket_types WHERE guild_id = ? AND panel_id = ?", (guild.id, panel_id))
        for row in type_rows:
            await db.execute("DELETE FROM ticket_form_questions WHERE ticket_type_id = ?", (int(row["id"]),))
        await db.execute("DELETE FROM ticket_types WHERE guild_id = ? AND panel_id = ?", (guild.id, panel_id))
        await db.execute("DELETE FROM ticket_panels_v2 WHERE guild_id = ? AND id = ?", (guild.id, panel_id))
        return web.json_response({"ok": True, "message": "Panel Tickets supprimé."})

    if action == "ticket_type_save":
        type_id = _int_or_none(payload.get("type_id"))
        panel_id = _int_or_none(payload.get("panel_id"))
        if not panel_id or not await db.fetchone("SELECT id FROM ticket_panels_v2 WHERE id=? AND guild_id=?", (panel_id, guild.id)):
            return dashboard._json_error("Choisissez un panel Tickets valide.", 400)
        name = str(payload.get("name") or "Support")[:80].strip() or "Support"
        description = str(payload.get("description") or "")[:150]
        emoji = str(payload.get("emoji") or "🎫")[:100]
        button_label = str(payload.get("button_label") or name)[:80]
        button_style = str(payload.get("button_style") or "bleu")
        if button_style not in {"bleu", "gris", "vert", "rouge", "blurple"}:
            button_style = "bleu"
        staff_role_id = _int_or_none(payload.get("staff_role_id"))
        category_id = _int_or_none(payload.get("category_id"))
        log_channel_id = _int_or_none(payload.get("log_channel_id"))
        if staff_role_id is not None and guild.get_role(staff_role_id) is None:
            return dashboard._json_error("Le rôle support choisi n'existe plus.", 400)
        if category_id is not None and not isinstance(guild.get_channel(category_id), discord.CategoryChannel):
            return dashboard._json_error("La catégorie choisie est invalide.", 400)
        if log_channel_id is not None and not isinstance(guild.get_channel(log_channel_id), discord.TextChannel):
            return dashboard._json_error("Le salon de logs choisi est invalide.", 400)
        name_format = str(payload.get("name_format") or "ticket-{pseudo}")[:90]
        open_message = str(payload.get("open_message") or "")[:1000]
        maximum = _bounded_int(payload.get("max_per_member"), 1, 20, 1)
        autoclose = _bounded_int(payload.get("autoclose_hours"), 0, 720, 0)
        mention_staff = int(bool(payload.get("mention_staff", True)))
        use_form = int(bool(payload.get("use_form", False)))
        if type_id:
            row = await db.fetchone("SELECT id FROM ticket_types WHERE id=? AND guild_id=?", (type_id, guild.id))
            if not row:
                return dashboard._json_error("Type de ticket introuvable.", 404)
            await db.execute(
                "UPDATE ticket_types SET panel_id=?,name=?,description=?,emoji=?,button_label=?,button_style=?,staff_role_id=?,category_id=?,name_format=?,open_message=?,max_per_member=?,autoclose_hours=?,log_channel_id=?,mention_staff=?,use_form=? WHERE id=? AND guild_id=?",
                (panel_id, name, description, emoji, button_label, button_style, staff_role_id, category_id, name_format, open_message, maximum, autoclose, log_channel_id, mention_staff, use_form, type_id, guild.id),
            )
        else:
            position_row = await db.fetchone("SELECT COALESCE(MAX(position),-1)+1 AS p FROM ticket_types WHERE panel_id=?", (panel_id,))
            position = int(position_row["p"] if position_row else 0)
            cur = await db.execute(
                "INSERT INTO ticket_types (panel_id,guild_id,name,description,emoji,button_label,button_style,staff_role_id,category_id,name_format,open_message,max_per_member,autoclose_hours,log_channel_id,mention_staff,use_form,position) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (panel_id, guild.id, name, description, emoji, button_label, button_style, staff_role_id, category_id, name_format, open_message, maximum, autoclose, log_channel_id, mention_staff, use_form, position),
            )
            type_id = int(cur.lastrowid)
        return web.json_response({"ok": True, "message": "Type de ticket enregistré.", "type_id": str(type_id)})

    if action == "ticket_type_delete":
        type_id = _int_or_none(payload.get("type_id"))
        row = await db.fetchone("SELECT id FROM ticket_types WHERE id=? AND guild_id=?", (type_id, guild.id)) if type_id else None
        if not row:
            return dashboard._json_error("Type de ticket introuvable.", 404)
        await db.execute("DELETE FROM ticket_form_questions WHERE ticket_type_id=?", (type_id,))
        await db.execute("DELETE FROM ticket_types WHERE id=? AND guild_id=?", (type_id, guild.id))
        return web.json_response({"ok": True, "message": "Type de ticket supprimé."})

    if action == "ticket_question_save":
        question_id = _int_or_none(payload.get("question_id"))
        type_id = _int_or_none(payload.get("type_id"))
        type_row = await db.fetchone("SELECT id FROM ticket_types WHERE id=? AND guild_id=?", (type_id, guild.id)) if type_id else None
        if not type_row:
            return dashboard._json_error("Type de ticket introuvable.", 404)
        label = str(payload.get("label") or "Question")[:45].strip() or "Question"
        placeholder = str(payload.get("placeholder") or "")[:100]
        style = "long" if str(payload.get("style")) == "long" else "short"
        required = int(bool(payload.get("required", True)))
        min_length = _bounded_int(payload.get("min_length"), 0, 4000, 0)
        max_length = _bounded_int(payload.get("max_length"), max(1, min_length), 4000, 500)
        if question_id:
            await db.execute(
                "UPDATE ticket_form_questions SET label=?,placeholder=?,style=?,required=?,min_length=?,max_length=? WHERE id=? AND ticket_type_id=?",
                (label, placeholder, style, required, min_length, max_length, question_id, type_id),
            )
        else:
            position_row = await db.fetchone("SELECT COALESCE(MAX(position),-1)+1 AS p FROM ticket_form_questions WHERE ticket_type_id=?", (type_id,))
            position = int(position_row["p"] if position_row else 0)
            cur = await db.execute(
                "INSERT INTO ticket_form_questions (ticket_type_id,position,label,placeholder,style,required,min_length,max_length) VALUES (?,?,?,?,?,?,?,?)",
                (type_id, position, label, placeholder, style, required, min_length, max_length),
            )
            question_id = int(cur.lastrowid)
        await db.execute("UPDATE ticket_types SET use_form=1 WHERE id=? AND guild_id=?", (type_id, guild.id))
        return web.json_response({"ok": True, "message": "Question enregistrée.", "question_id": str(question_id)})

    if action == "ticket_question_delete":
        question_id = _int_or_none(payload.get("question_id"))
        if not question_id:
            return dashboard._json_error("Question invalide.", 400)
        row = await db.fetchone(
            "SELECT q.id FROM ticket_form_questions q JOIN ticket_types t ON t.id=q.ticket_type_id WHERE q.id=? AND t.guild_id=?",
            (question_id, guild.id),
        )
        if not row:
            return dashboard._json_error("Question introuvable.", 404)
        await db.execute("DELETE FROM ticket_form_questions WHERE id=?", (question_id,))
        return web.json_response({"ok": True, "message": "Question supprimée."})

    if action == "ticket_button_save":
        key_name = str(payload.get("key") or "").strip().lower()
        try:
            from cogs.tickets import STAFF_BUTTONS, get_button_settings, save_button_settings
        except Exception:
            return dashboard._json_error("Le module de boutons Tickets est indisponible.", 503)
        if key_name not in STAFF_BUTTONS:
            return dashboard._json_error("Bouton Tickets inconnu.", 400)
        settings = await get_button_settings(bot, guild.id)
        cfg = settings[key_name]
        cfg["enabled"] = bool(payload.get("enabled", cfg.get("enabled", True)))
        cfg["label"] = str(payload.get("label") or cfg.get("label") or STAFF_BUTTONS[key_name][0])[:80]
        cfg["emoji"] = str(payload.get("emoji") or cfg.get("emoji") or STAFF_BUTTONS[key_name][1])[:100]
        style = str(payload.get("style") or cfg.get("style") or "bleu")
        cfg["style"] = style if style in {"bleu", "gris", "vert", "rouge"} else "bleu"
        role_id = _int_or_none(payload.get("role_id"))
        if role_id is not None and guild.get_role(role_id) is None:
            return dashboard._json_error("Le rôle autorisé n'existe plus.", 400)
        cfg["role_id"] = role_id
        await save_button_settings(bot, guild.id, settings)
        return web.json_response({"ok": True, "message": "Bouton staff enregistré."})

    if action == "ticket_send":
        panel_id = _int_or_none(payload.get("panel_id"))
        if not panel_id:
            return dashboard._json_error("Choisissez un panel Tickets.", 400)
        try:
            message_id, state = await _ticket_panel_send(bot, guild, panel_id)
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)
        except RuntimeError as exc:
            return dashboard._json_error(str(exc), 503)
        except discord.Forbidden:
            return dashboard._json_error("SentriX n'a pas les permissions nécessaires pour publier ce panel.", 403)
        except discord.HTTPException:
            logger.exception("V62 : envoi panel Tickets impossible.")
            return dashboard._json_error("Discord a refusé la publication du panel Tickets.", 502)
        return web.json_response({"ok": True, "message": f"Panel Tickets {state}.", "message_id": str(message_id)})

    return dashboard._json_error("Action V62 inconnue.", 400)


V62_CSS = r'''
/* SentriX V62 — plus dense, moins de vide, identité bleue SentriX */
:root{--sx-blue:#4da3ff;--sx-blue2:#7cc0ff;--sx-blue-bg:#1d3045;--sx-blue-line:#35688f}
.workspace{padding:24px 30px 58px}.workspace-head{margin-bottom:16px}.metrics{margin-bottom:14px}.panel-section{padding:15px 16px 17px}.section-title{margin-bottom:12px}.content-head{margin-bottom:12px}.content-head h2{font-size:23px}.sx-toolbar{margin:-2px 0 12px}.sx-nav-group{padding-top:12px}.navigation button[data-tab].active{border-left-color:var(--sx-blue);color:#fff;background:#29323b}.navigation button[data-tab].active .nav-icon{color:var(--sx-blue2)}
.sx-v62-grid{display:grid;grid-template-columns:repeat(12,minmax(0,1fr));gap:10px}.sx-v62-card{grid-column:span 6;background:#30353a;border:1px solid #4a5057;border-radius:7px;padding:14px;min-width:0}.sx-v62-card.third{grid-column:span 4}.sx-v62-card.full{grid-column:1/-1}.sx-v62-card h3{margin:0 0 4px;font-size:15px}.sx-v62-card>p{margin:0 0 11px;color:#aeb3b7;font-size:11px;line-height:1.45}.sx-v62-card.info{border-color:var(--sx-blue-line);box-shadow:inset 3px 0 0 var(--sx-blue)}
.sx-v62-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}.sx-v62-head .sx-state{flex:0 0 auto}.sx-v62-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}.sx-v62-actions .btn.secondary{border-color:var(--sx-blue-line);background:var(--sx-blue-bg);color:#ddecff}.btn.blue{background:var(--sx-blue);border-color:var(--sx-blue);color:#07121d}.btn.blue:hover{background:var(--sx-blue2);border-color:var(--sx-blue2)}
.sx-v62-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.sx-v62-kpi{background:#2b3035;border:1px solid #474d53;border-radius:6px;padding:10px 11px}.sx-v62-kpi small{display:block;color:#92989e;font-size:9px;font-weight:900;text-transform:uppercase}.sx-v62-kpi strong{display:block;font-size:20px;margin-top:3px}
.sx-v62-split{display:grid;grid-template-columns:minmax(0,1fr) minmax(310px,.75fr);gap:12px}.sx-v62-list{display:grid;gap:7px;max-height:400px;overflow:auto}.sx-v62-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;background:#2b3035;border:1px solid #484e54;border-radius:6px;padding:9px 10px}.sx-v62-row b{display:block;font-size:12px}.sx-v62-row small{display:block;color:#9ca1a6;font-size:10px;margin-top:2px}.sx-v62-row.selected{border-color:var(--sx-blue);background:#263646}.sx-v62-badge{display:inline-flex;align-items:center;padding:4px 7px;border:1px solid var(--sx-blue-line);background:var(--sx-blue-bg);border-radius:999px;color:#cfe6ff;font-size:9px;font-weight:900}
.sx-v62-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.sx-v62-fields .full{grid-column:1/-1}.sx-v62-fields .field{min-width:0}.sx-v62-fields textarea{min-height:90px}.sx-v62-rules textarea{min-height:220px}.sx-v62-preview{background:#2b2d31;border-left:4px solid var(--sx-blue);padding:12px;border-radius:5px;white-space:pre-wrap;line-height:1.45;color:#ddd}.sx-v62-preview img{max-width:100%;max-height:260px;border-radius:5px;margin-top:10px;object-fit:contain}.sx-v62-toolbar-note{padding:8px 10px;background:var(--sx-blue-bg);border:1px solid var(--sx-blue-line);border-radius:6px;color:#cfe6ff;font-size:10px}
.sx-v62-button-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.sx-v62-button{background:#2b3035;border:1px solid #474d53;border-radius:6px;padding:9px}.sx-v62-button .switch-line{padding:7px 0}.sx-v62-button input[type=text],.sx-v62-button select{padding:8px 9px}
.sx-v62-question{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr) auto;gap:7px;align-items:end;padding:9px;border:1px solid #474d53;border-radius:6px;background:#2b3035}.sx-v62-empty{padding:20px;border:1px dashed #50575e;border-radius:6px;text-align:center;color:#9fa4a8}
/* Les vieux raccourcis « ouvrir un autre centre » ne doivent plus apparaître dans /app. */
#sxToolbar a[href],.action-card>a[href],.action-card button[data-open-old],a[href="/setup-center"],a[href="/feature-suite"],a[href="/community"],a[href="/operations"]{display:none!important}
@media(max-width:1100px){.sx-v62-card.third{grid-column:span 6}.sx-v62-split{grid-template-columns:1fr}.sx-v62-button-grid{grid-template-columns:1fr 1fr}}
@media(max-width:760px){.workspace{padding:18px 14px 45px}.sx-v62-card,.sx-v62-card.third{grid-column:1/-1}.sx-v62-kpis{grid-template-columns:1fr 1fr}.sx-v62-fields{grid-template-columns:1fr}.sx-v62-fields .full{grid-column:auto}.sx-v62-button-grid{grid-template-columns:1fr}.sx-v62-question{grid-template-columns:1fr}}
'''

V62_JS = r'''
<script id="sentrix-v62-dense">
(() => {
  "use strict";
  if(window.__sentrixV62Dense)return;window.__sentrixV62Dense=true;
  const v62={data:null,panelId:null,typeId:null};
  const V62_GROUPS=[
    ["Général",[["overview","Vue d’ensemble","▦"],["welcome","Arrivées et départs","▤"],["messages","Messages","☷"],["levels","Niveaux","↗"]]],
    ["Membres & rôles",[["roles","Rôles automatiques","▣"],["secure_roles","Rôles sécurisés","◆"],["reaction_roles","Rôles-réactions","☷"],["verification","Vérification & règlement","✓"]]],
    ["Modération",[["sanctions","Modération","⌁"],["security","Auto-Modération","◇"],["reports","Signalements","⚑"],["logs","Logs","◔"]]],
    ["Communauté",[["economy","Économie","$"],["suggestions","Suggestions","●"],["notifications","Notifications sociales","◖"]]],
    ["Outils",[["tickets","Tickets","▰"],["ai","Intelligence artificielle","AI"],["embeds","Embeds","E"],["games","Mini-jeux","◆"],["design","Design","◫"]]],
    ["Configuration",[["setup","Configuration serveur","⚙"],["access","Accès & commandes","⌘"],["dm","Messages privés","✉"],["status","Statut SentriX","●"]]],
  ];
  tabMeta.verification=['Vérification & règlement','Écrivez votre règlement, choisissez le rôle et publiez le vrai panneau de vérification.'];
  tabMeta.economy=['Économie','Activez le système économique et consultez ses données sans quitter le dashboard.'];

  function denseNav(){
    const nav=$('navigation');if(!nav)return;
    const search=$('sxNavSearch')?.value||'';
    nav.innerHTML='<div class="sx-nav-tools"><input id="sxNavSearch" class="sx-nav-search" type="search" placeholder="Rechercher une fonction…" aria-label="Rechercher une fonction"></div>'+V62_GROUPS.map(([label,items])=>`<div class="sx-nav-group">${label}</div>`+items.map(([tab,label,icon])=>`<button type="button" data-tab="${tab}" class="${state.tab===tab?'active':''}"><span class="nav-icon">${icon}</span>${label}</button>`).join('')).join('');
    $('sxNavSearch').value=search;
    $('sxNavSearch').oninput=e=>{const q=String(e.target.value||'').toLocaleLowerCase('fr').trim();nav.querySelectorAll('button[data-tab]').forEach(b=>b.classList.toggle('sx-empty-filter',q&&!b.textContent.toLocaleLowerCase('fr').includes(q)))};
  }
  function activate(tab){document.querySelectorAll('#navigation button[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab))}
  function field(label,id,value='',opts={}){const type=opts.type||'text',full=opts.full?' full':'',hint=opts.hint?`<div class="hint">${esc(opts.hint)}</div>`:'';if(opts.textarea)return `<div class="field${full}"><label>${esc(label)}</label><textarea id="${id}" maxlength="${opts.max||2000}" placeholder="${esc(opts.placeholder||'')}">${esc(value||'')}</textarea>${hint}</div>`;if(opts.select)return `<div class="field${full}"><label>${esc(label)}</label><select id="${id}">${opts.select}</select>${hint}</div>`;return `<div class="field${full}"><label>${esc(label)}</label><input id="${id}" type="${type}" value="${esc(value??'')}" ${opts.min!=null?`min="${opts.min}"`:''} ${opts.max!=null?`max="${opts.max}"`:''} placeholder="${esc(opts.placeholder||'')}">${hint}</div>`}
  function boolLine(label,id,on,hint=''){return `<div class="switch-line"><div class="switch-copy"><b>${esc(label)}</b><span>${esc(hint)}</span></div><input id="${id}" class="switch" type="checkbox" ${on?'checked':''}></div>`}
  async function loadV62(force=false){if(v62.data&&!force)return v62.data;v62.data=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/v62`);return v62.data}
  async function v62Action(payload){const r=await api(`/api/guilds/${encodeURIComponent(state.guildId)}/v62`,{method:'POST',body:JSON.stringify(payload)});toast(r.message||'Enregistré.');v62.data=null;return r}
  function noSave(){ $('saveBar').classList.add('hidden');state.dirty=false }
  function page(title,desc,tab){$('tabTitle').textContent=title;$('tabDescription').textContent=desc;activate(tab);noSave()}

  async function renderVerification(){
    page('Vérification & règlement','Le règlement est entièrement écrit par votre staff. SentriX ne génère aucun texte à votre place.','verification');$('fields').innerHTML='<div class="panel-section"><div class="empty">Chargement du règlement…</div></div>';
    try{const data=await loadV62(true),v=data.verification||{};$('fields').innerHTML=`<div class="panel-section"><div class="sx-v62-split"><section class="sx-v62-card full info sx-v62-rules"><div class="sx-v62-head"><div><h3>Votre règlement</h3><p>Écrivez exactement le texte que les membres doivent accepter.</p></div><span class="sx-v62-badge">PERSONNALISÉ</span></div><div class="sx-v62-fields">${field('Salon du règlement','v62VerifyChannel','',{select:channelOptions(v.channel_id||'')})}${field('Rôle donné après validation','v62VerifyRole','',{select:roleOptions(v.role_id||'')})}${field('Texte du règlement','v62Rules',v.rules_text||'',{textarea:true,full:true,max:3900,placeholder:'1. Respectez les membres…\n2. Pas de spam…'})}${field('Image / bannière HTTPS (facultatif)','v62VerifyImage',v.image_url||'',{type:'url',full:true,placeholder:'https://…'})}<div class="field">${boolLine('CAPTCHA','v62Captcha',Boolean(v.captcha_enabled),'Demande le code visuel avant de donner le rôle.')}</div>${field('Tentatives CAPTCHA','v62CaptchaTries',v.captcha_max_attempts||3,{type:'number',min:1,max:10})}</div><div class="sx-v62-actions"><button id="v62VerifySave" class="btn secondary" type="button">Enregistrer</button><button id="v62VerifyPublish" class="btn blue" type="button">Enregistrer et publier</button></div></section><aside class="sx-v62-card full"><h3>Aperçu</h3><p>Le vrai panneau Discord utilisera ce texte et le bouton persistant de SentriX.</p><div id="v62RulePreview" class="sx-v62-preview"></div></aside></div></div>`;
      const preview=()=>{$('v62RulePreview').innerHTML=esc($('v62Rules').value||'Votre règlement apparaîtra ici.').replaceAll('\n','<br>')+($('v62VerifyImage').value?`<br><img src="${esc($('v62VerifyImage').value)}" alt="">`:'' )};$('v62Rules').oninput=preview;$('v62VerifyImage').oninput=preview;preview();
      const save=publish=>v62Action({action:'verification_save',channel_id:$('v62VerifyChannel').value,role_id:$('v62VerifyRole').value,rules_text:$('v62Rules').value,image_url:$('v62VerifyImage').value,captcha_enabled:$('v62Captcha').checked,captcha_max_attempts:$('v62CaptchaTries').value,publish});$('v62VerifySave').onclick=()=>save(false);$('v62VerifyPublish').onclick=()=>save(true);
    }catch(e){toast(e.message,true);$('fields').innerHTML=`<div class="panel-section"><div class="empty">${esc(e.message)}</div></div>`}
  }

  async function renderEconomy(){
    page('Économie','Réglages et état de l’économie, directement dans SentriX.','economy');
    try{const systems=await getSystems(true),m=state.guildData.metrics||{};$('fields').innerHTML=`<div class="panel-section"><div class="sx-v62-grid"><section class="sx-v62-card info"><div class="sx-v62-head"><div><h3>Système économique</h3><p>Les soldes restent enregistrés lorsque vous désactivez le système.</p></div><span class="sx-state ${systems.economy_enabled?'active':'inactive'}">${systems.economy_enabled?'ACTIF':'INACTIF'}</span></div>${boolLine('Activer l’économie','v62Economy',Boolean(systems.economy_enabled),'Argent, banque et boutiques du serveur.')}<div class="sx-v62-actions"><button id="v62EconomySave" class="btn blue">Appliquer</button></div></section><section class="sx-v62-card"><h3>Données du serveur</h3><p>Comptes économiques actuellement enregistrés.</p><div class="sx-v62-kpis"><div class="sx-v62-kpi"><small>Comptes</small><strong>${number(m.economy_accounts)}</strong></div><div class="sx-v62-kpi"><small>Membres</small><strong>${number(state.guildData.guild?.members)}</strong></div></div></section><section class="sx-v62-card full"><h3>Accès aux commandes</h3><p>Les commandes économiques peuvent être activées/désactivées individuellement dans « Accès & commandes » sans ouvrir une autre page.</p><div class="sx-v62-toolbar-note">Utilisez la catégorie Accès & commandes dans la barre latérale pour les restrictions précises.</div></section></div></div>`;$('v62EconomySave').onclick=async()=>{const next=$('v62Economy').checked;if(Boolean(systems.economy_enabled)===next)return toast('Aucun changement.');await toggleSystem('economy_enabled')}
    }catch(e){toast(e.message,true)}
  }

  function panelOptions(items,current){return '<option value="">Nouveau panel</option>'+items.map(p=>`<option value="${esc(p.id)}" ${String(current)===String(p.id)?'selected':''}>#${esc(p.id)} · ${esc(p.name||p.title||'Panel')}</option>`).join('')}
  function typeOptions(items,current,panelId){return '<option value="">Nouveau type</option>'+items.filter(t=>!panelId||String(t.panel_id)===String(panelId)).map(t=>`<option value="${esc(t.id)}" ${String(current)===String(t.id)?'selected':''}>${esc(t.name)}</option>`).join('')}
  function panelById(data,id){return (data.tickets?.panels||[]).find(p=>String(p.id)===String(id))||null}
  function typeById(data,id){return (data.tickets?.types||[]).find(t=>String(t.id)===String(id))||null}

  async function renderTicketsV62(){
    page('Tickets','Panels, types, formulaires, rôles staff, logs et boutons — tout se configure ici.','tickets');$('fields').innerHTML='<div class="panel-section"><div class="empty">Chargement des tickets…</div></div>';
    try{const data=await loadV62(true),panels=data.tickets?.panels||[],types=data.tickets?.types||[];if(v62.panelId&&!panelById(data,v62.panelId))v62.panelId=null;if(v62.typeId&&!typeById(data,v62.typeId))v62.typeId=null;const p=panelById(data,v62.panelId)||{},t=typeById(data,v62.typeId)||{};$('fields').innerHTML=`<div class="panel-section"><div class="sx-v62-grid">
      <section class="sx-v62-card full info"><div class="sx-v62-head"><div><h3>Panel public</h3><p>Créez ou modifiez le vrai panel affiché aux membres.</p></div><span class="sx-v62-badge">${panels.length} PANEL(S)</span></div><div class="sx-v62-fields">${field('Panel','v62PanelPick','',{select:panelOptions(panels,v62.panelId)})}${field('Nom interne','v62PanelName',p.name||'Support')}${field('Titre','v62PanelTitle',p.title||'Support',{full:true})}${field('Description','v62PanelDescription',p.description||'Choisissez une option ci-dessous pour ouvrir un ticket.',{textarea:true,full:true,max:2000})}${field('Salon du panel','v62PanelChannel','',{select:channelOptions(p.channel_id||'')})}${field('Affichage','v62PanelStyle','',{select:`<option value="select" ${p.style!=='button'?'selected':''}>Menu déroulant</option><option value="button" ${p.style==='button'?'selected':''}>Boutons</option>`})}${field('Couleur','v62PanelColor',p.color?('#'+Number(p.color).toString(16).padStart(6,'0')):'#4DA3FF')}${field('Limite / membre','v62PanelMax',p.max_per_member||1,{type:'number',min:1,max:20})}${field('Image HTTPS','v62PanelImage',p.image_url||'',{type:'url'})}${field('Miniature HTTPS','v62PanelThumb',p.thumbnail_url||'',{type:'url'})}${field('Footer','v62PanelFooter',p.footer_text||'',{full:true})}<div class="field">${boolLine('Panel actif','v62PanelEnabled',p.enabled!==0,'Les membres peuvent utiliser ce panel.')}</div></div><div class="sx-v62-actions"><button id="v62PanelSave" class="btn blue">Enregistrer le panel</button>${p.id?'<button id="v62PanelSend" class="btn secondary">Publier / mettre à jour</button><button id="v62PanelDelete" class="btn danger">Supprimer</button>':''}</div></section>
      <section class="sx-v62-card full"><div class="sx-v62-head"><div><h3>Types de tickets</h3><p>Support, recrutement, achat… chaque type possède ses propres rôles, catégorie, logs et limites.</p></div><span class="sx-v62-badge">${types.filter(x=>!p.id||String(x.panel_id)===String(p.id)).length} TYPE(S)</span></div><div class="sx-v62-fields">${field('Type','v62TypePick','',{select:typeOptions(types,v62.typeId,p.id)})}${field('Nom','v62TypeName',t.name||'Support')}${field('Description courte','v62TypeDescription',t.description||'',{full:true})}${field('Emoji','v62TypeEmoji',t.emoji||'🎫')}${field('Texte bouton','v62TypeButtonLabel',t.button_label||t.name||'Support')}${field('Style bouton','v62TypeButtonStyle','',{select:`<option value="bleu" ${['bleu','blurple'].includes(t.button_style)?'selected':''}>Bleu</option><option value="gris" ${t.button_style==='gris'?'selected':''}>Gris</option><option value="vert" ${t.button_style==='vert'?'selected':''}>Vert</option><option value="rouge" ${t.button_style==='rouge'?'selected':''}>Rouge</option>`})}${field('Rôle support','v62TypeStaff','',{select:roleOptions(t.staff_role_id||'')})}${field('Catégorie des salons','v62TypeCategory','',{select:categoryOptions(t.category_id||'')})}${field('Salon de logs','v62TypeLogs','',{select:channelOptions(t.log_channel_id||'')})}${field('Format du salon','v62TypeFormat',t.name_format||'ticket-{pseudo}',{hint:'Variables : {pseudo}, {numero}'})}${field('Message d’ouverture','v62TypeOpen',t.open_message||'',{textarea:true,full:true,max:1000})}${field('Max tickets / membre','v62TypeMax',t.max_per_member||1,{type:'number',min:1,max:20})}${field('Fermeture auto (heures, 0 = non)','v62TypeAutoclose',t.autoclose_hours||0,{type:'number',min:0,max:720})}<div class="field">${boolLine('Mentionner le staff','v62TypeMention',t.mention_staff!==0,'Ping le rôle support à l’ouverture.')}${boolLine('Formulaire avant ouverture','v62TypeForm',Boolean(t.use_form),'Pose les questions configurées ci-dessous.')}</div></div><div class="sx-v62-actions"><button id="v62TypeSave" class="btn blue" ${p.id?'':'disabled'}>Enregistrer le type</button>${t.id?'<button id="v62TypeDelete" class="btn danger">Supprimer ce type</button>':''}</div></section>
      <section class="sx-v62-card full"><h3>Questions du formulaire</h3><p>Ajoutez les questions posées avant la création du ticket.</p><div id="v62Questions" class="sx-v62-list"></div>${t.id?'<div class="sx-v62-fields" style="margin-top:10px">'+field('Nouvelle question','v62QuestionLabel','',{placeholder:'Votre pseudo en jeu ?'})+field('Placeholder','v62QuestionPlaceholder','')+field('Style','v62QuestionStyle','',{select:'<option value="short">Réponse courte</option><option value="long">Réponse longue</option>'})+field('Longueur max','v62QuestionMax','500',{type:'number',min:1,max:4000})+'<div class="field">'+boolLine('Obligatoire','v62QuestionRequired',true,'')+'</div></div><div class="sx-v62-actions"><button id="v62QuestionAdd" class="btn blue">Ajouter la question</button></div>':'<div class="sx-v62-empty">Enregistrez d’abord un type de ticket.</div>'}</section>
      <section class="sx-v62-card full"><h3>Boutons staff</h3><p>Claim, ajout/retrait de membre, renommage, transfert, note, relance et fermeture.</p><div id="v62Buttons" class="sx-v62-button-grid"></div></section>
    </div></div>`;
      $('v62PanelPick').onchange=()=>{v62.panelId=$('v62PanelPick').value||null;v62.typeId=null;renderTicketsV62()};$('v62TypePick').onchange=()=>{v62.typeId=$('v62TypePick').value||null;renderTicketsV62()};
      $('v62PanelSave').onclick=async()=>{const r=await v62Action({action:'ticket_panel_save',panel_id:p.id||null,name:$('v62PanelName').value,title:$('v62PanelTitle').value,description:$('v62PanelDescription').value,channel_id:$('v62PanelChannel').value,style:$('v62PanelStyle').value,color:$('v62PanelColor').value,image_url:$('v62PanelImage').value,thumbnail_url:$('v62PanelThumb').value,footer_text:$('v62PanelFooter').value,max_per_member:$('v62PanelMax').value,enabled:$('v62PanelEnabled').checked});v62.panelId=r.panel_id;renderTicketsV62()};
      if(p.id){$('v62PanelSend').onclick=()=>v62Action({action:'ticket_send',panel_id:p.id});$('v62PanelDelete').onclick=async()=>{if(confirm('Supprimer ce panel et ses types ?')){await v62Action({action:'ticket_panel_delete',panel_id:p.id});v62.panelId=null;v62.typeId=null;renderTicketsV62()}}}
      $('v62TypeSave').onclick=async()=>{const r=await v62Action({action:'ticket_type_save',type_id:t.id||null,panel_id:p.id,name:$('v62TypeName').value,description:$('v62TypeDescription').value,emoji:$('v62TypeEmoji').value,button_label:$('v62TypeButtonLabel').value,button_style:$('v62TypeButtonStyle').value,staff_role_id:$('v62TypeStaff').value,category_id:$('v62TypeCategory').value,log_channel_id:$('v62TypeLogs').value,name_format:$('v62TypeFormat').value,open_message:$('v62TypeOpen').value,max_per_member:$('v62TypeMax').value,autoclose_hours:$('v62TypeAutoclose').value,mention_staff:$('v62TypeMention').checked,use_form:$('v62TypeForm').checked});v62.typeId=r.type_id;renderTicketsV62()};if(t.id)$('v62TypeDelete').onclick=async()=>{if(confirm('Supprimer ce type de ticket ?')){await v62Action({action:'ticket_type_delete',type_id:t.id});v62.typeId=null;renderTicketsV62()}};
      const qs=(data.tickets?.questions||[]).filter(q=>String(q.ticket_type_id)===String(t.id));$('v62Questions').innerHTML=qs.length?qs.map(q=>`<div class="sx-v62-row"><div><b>${esc(q.label)}</b><small>${q.style==='long'?'Réponse longue':'Réponse courte'} · ${q.required?'obligatoire':'facultatif'} · max ${q.max_length}</small></div><button class="btn danger sx-mini" data-q-delete="${esc(q.id)}">Supprimer</button></div>`).join(''):'<div class="sx-v62-empty">Aucune question.</div>';document.querySelectorAll('[data-q-delete]').forEach(b=>b.onclick=async()=>{await v62Action({action:'ticket_question_delete',question_id:b.dataset.qDelete});renderTicketsV62()});if(t.id)$('v62QuestionAdd').onclick=async()=>{await v62Action({action:'ticket_question_save',type_id:t.id,label:$('v62QuestionLabel').value,placeholder:$('v62QuestionPlaceholder').value,style:$('v62QuestionStyle').value,required:$('v62QuestionRequired').checked,max_length:$('v62QuestionMax').value});renderTicketsV62()};
      const buttons=data.tickets?.buttons||{};$('v62Buttons').innerHTML=Object.entries(buttons).map(([k,cfg])=>`<div class="sx-v62-button"><div class="sx-v62-head"><b>${esc(cfg.emoji||'')} ${esc(cfg.label||k)}</b><input class="switch" type="checkbox" data-btn-enabled="${esc(k)}" ${cfg.enabled?'checked':''}></div><input type="text" data-btn-label="${esc(k)}" value="${esc(cfg.label||'')}" placeholder="Libellé"><div class="sx-v62-fields" style="margin-top:7px"><div class="field"><select data-btn-style="${esc(k)}"><option value="bleu" ${cfg.style==='bleu'?'selected':''}>Bleu</option><option value="gris" ${cfg.style==='gris'?'selected':''}>Gris</option><option value="vert" ${cfg.style==='vert'?'selected':''}>Vert</option><option value="rouge" ${cfg.style==='rouge'?'selected':''}>Rouge</option></select></div><div class="field"><select data-btn-role="${esc(k)}">${roleOptions(cfg.role_id||'')}</select></div></div><button class="btn secondary sx-mini" data-btn-save="${esc(k)}" style="margin-top:7px">Enregistrer</button></div>`).join('');document.querySelectorAll('[data-btn-save]').forEach(b=>b.onclick=async()=>{const k=b.dataset.btnSave;await v62Action({action:'ticket_button_save',key:k,enabled:document.querySelector(`[data-btn-enabled="${k}"]`).checked,label:document.querySelector(`[data-btn-label="${k}"]`).value,style:document.querySelector(`[data-btn-style="${k}"]`).value,role_id:document.querySelector(`[data-btn-role="${k}"]`).value});renderTicketsV62()});
    }catch(e){toast(e.message,true);$('fields').innerHTML=`<div class="panel-section"><div class="empty">${esc(e.message)}</div></div>`}
  }

  const renderBeforeV62=renderTab;renderTab=function(){denseNav();document.querySelectorAll('#sxToolbar a[href],#sxToolbar button').forEach(el=>{if(/configuration avancée|ouvrir/i.test(el.textContent||''))el.remove()});if(state.tab==='verification'){renderVerification();return}if(state.tab==='economy'){renderEconomy();return}if(state.tab==='tickets'){renderTicketsV62();return}if(['recurring','community','features','infinity'].includes(state.tab))state.tab='overview';return renderBeforeV62()};
  const selectBeforeV62=selectGuild;selectGuild=async function(value){const changed=String(value)!==String(state.guildId);const result=await selectBeforeV62(value);if(changed){v62.data=null;v62.panelId=null;v62.typeId=null}return result};
  denseNav();
})();
</script>
'''


def _install_backend(dashboard) -> None:
    global _INSTALLED_BACKEND
    if _INSTALLED_BACKEND:
        return
    current = dashboard.build_app
    if getattr(current, "_sentrix_v62_routes", False):
        _INSTALLED_BACKEND = True
        return

    def build_app(bot) -> web.Application:
        app = current(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/api/guilds/{guild_id}/v62", handle_v62_get)
        app.router.add_post("/api/guilds/{guild_id}/v62", handle_v62_post)
        return app

    build_app._sentrix_v62_routes = True
    build_app._sentrix_original = current
    dashboard.build_app = build_app
    _INSTALLED_BACKEND = True


def install(dashboard) -> bool:
    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    if 'id="sentrix-v62-dense"' in html:
        _install_backend(dashboard)
        return True
    if 'id="sentrix-v61-unified"' not in html:
        logger.error("Dashboard V62 refusé : V61 n'est pas présent.")
        return False
    if "</style>" not in html or "</body>" not in html:
        return False
    html = html.replace("</style>", V62_CSS + "\n</style>", 1)
    html = html.replace("</body>", V62_JS + "\n</body>", 1)
    dashboard.INDEX_HTML = html
    dashboard._sentrix_dashboard_version = "v62-dense"
    _install_backend(dashboard)
    logger.info("Dashboard V62 dense installé : vérification personnalisée, tickets v2 inline, navigation sans anciens centres.")
    return True


__all__ = ["install", "handle_v62_get", "handle_v62_post"]
