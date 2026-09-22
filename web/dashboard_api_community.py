"""Routes « Communauté » du dashboard : Niveaux, Économie, Rôles.

Chaque route réutilise le stockage et les validations déjà employés par les commandes et
par ``/setup`` (``stats_settings_json``, ``level_roles``, ``economy_settings_v2``,
``shop_items``, ``self_role_panels``, ``reaction_roles``). Aucune table ni règle nouvelle :
le dashboard n'est qu'une autre entrée vers les mêmes données que Discord.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import discord
from aiohttp import web

logger = logging.getLogger("bot.dashboard-community")

LEVEL_SETTING_KEYS = ("xp_min", "xp_max", "xp_cooldown", "level_announce_enabled", "level_keep_old_roles", "xp_disabled_on_commands", "xp_excluded_role_ids")


def _int(value, minimum: int, maximum: int, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Le champ {field} doit être un nombre entier.")
    if not minimum <= number <= maximum:
        raise ValueError(f"Le champ {field} doit être compris entre {minimum} et {maximum}.")
    return number


def _role_ids(guild: discord.Guild, values) -> list[int]:
    ids: list[int] = []
    for raw in values or []:
        try:
            rid = int(raw)
        except (TypeError, ValueError):
            continue
        if guild.get_role(rid) is not None and rid not in ids:
            ids.append(rid)
    return ids


def register(app: web.Application, dashboard) -> None:
    bot = app["bot"]

    async def _guard(request: web.Request, *, write: bool = False):
        try:
            guild_id = int(request.match_info["guild_id"])
        except (TypeError, ValueError):
            return None, None, dashboard._json_error("Identifiant de serveur invalide.", 400)
        session, guild, error = await dashboard._manageable_guild(request, guild_id)
        if error:
            return None, None, error
        if write:
            csrf_error = dashboard._require_csrf(request, session)
            if csrf_error:
                return None, None, csrf_error
        return session, guild, None

    async def _payload(request: web.Request) -> dict:
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ Niveaux
    async def levels_get(request: web.Request):
        session, guild, error = await _guard(request)
        if error:
            return error
        settings = await bot.db.get_stats_settings(guild.id)
        conf = await bot.db.get_guild_config(guild.id)
        raw_channels = str((conf["xp_channel_disabled"] if conf and conf["xp_channel_disabled"] else "") or "")
        disabled_channels = [c.strip() for c in raw_channels.split(",") if c.strip()]
        rows = await bot.db.fetchall("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (guild.id,))
        return web.json_response({
            "ok": True,
            **{key: settings.get(key) for key in LEVEL_SETTING_KEYS},
            "xp_excluded_role_ids": [str(r) for r in settings.get("xp_excluded_role_ids", [])],
            "xp_channel_disabled": disabled_channels,
            "roles": [{"level": int(r["level"]), "role_id": str(r["role_id"])} for r in rows],
        })

    async def levels_put(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        updates: dict = {}
        try:
            if "xp_min" in payload:
                updates["xp_min"] = _int(payload["xp_min"], 1, 1000, "XP minimum")
            if "xp_max" in payload:
                updates["xp_max"] = _int(payload["xp_max"], 1, 1000, "XP maximum")
            if "xp_cooldown" in payload:
                updates["xp_cooldown"] = _int(payload["xp_cooldown"], 0, 3600, "délai entre deux gains")
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)
        current = await bot.db.get_stats_settings(guild.id)
        if updates.get("xp_min", current["xp_min"]) > updates.get("xp_max", current["xp_max"]):
            return dashboard._json_error("L'XP minimum doit être inférieur ou égal à l'XP maximum.", 400)
        for key in ("level_announce_enabled", "level_keep_old_roles", "xp_disabled_on_commands"):
            if key in payload:
                updates[key] = bool(payload[key])
        if "xp_excluded_role_ids" in payload:
            updates["xp_excluded_role_ids"] = _role_ids(guild, payload["xp_excluded_role_ids"])
        if updates:
            await bot.db.set_stats_settings(guild.id, updates)
        if "xp_channel_disabled" in payload:
            ids = []
            for raw in payload["xp_channel_disabled"] or []:
                try:
                    cid = int(raw)
                except (TypeError, ValueError):
                    continue
                if guild.get_channel(cid) is not None:
                    ids.append(str(cid))
            await bot.db.set_guild_config(guild.id, "xp_channel_disabled", ",".join(ids))
        return web.json_response({"ok": True, "message": "Réglages des niveaux enregistrés."})

    async def level_role_post(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        try:
            level = _int(payload.get("level"), 1, 1000, "niveau")
            role = guild.get_role(int(payload.get("role_id")))
        except (TypeError, ValueError) as exc:
            return dashboard._json_error(str(exc) if str(exc) else "Rôle invalide.", 400)
        from cogs.verification import role_grant_problem
        problem = role_grant_problem(guild, role)
        if problem:
            return dashboard._json_error(problem, 409)
        await bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (guild.id, level, role.id),
        )
        return web.json_response({"ok": True, "message": f"@{role.name} sera attribué au niveau {level}."})

    async def level_role_delete(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        try:
            level = int(request.match_info["level"])
        except (TypeError, ValueError):
            return dashboard._json_error("Niveau invalide.", 400)
        await bot.db.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (guild.id, level))
        return web.json_response({"ok": True, "message": f"Récompense du niveau {level} retirée."})

    # ------------------------------------------------------------------ Économie
    async def economy_get(request: web.Request):
        session, guild, error = await _guard(request)
        if error:
            return error
        from cogs import setup_v2_core as core
        from cogs import economy as economy_cog
        currency = await core.economy_settings(bot, guild.id)
        rows = await bot.db.fetchall("SELECT id, name, price, description, role_id FROM shop_items WHERE guild_id = ? ORDER BY price ASC, id ASC", (guild.id,))
        panels = await bot.db.fetchall("SELECT channel_id, message_id FROM shop_panels WHERE guild_id = ?", (guild.id,))
        rules: dict[int, dict] = {}
        try:
            for r in await bot.db.fetchall("SELECT item_id, stock, sale_price, sale_ends_at, available_from, available_until FROM v17_shop_rules WHERE guild_id = ?", (guild.id,)):
                rules[int(r["item_id"])] = {"stock": int(r["stock"]) if r["stock"] is not None else -1, "sale_price": r["sale_price"], "sale_ends_at": r["sale_ends_at"], "available_from": r["available_from"], "available_until": r["available_until"]}
        except Exception:
            rules = {}
        return web.json_response({
            "ok": True,
            **currency,
            "shop": [{"id": int(r["id"]), "name": r["name"], "price": int(r["price"]), "description": r["description"] or "", "role_id": str(r["role_id"]) if r["role_id"] else None, **rules.get(int(r["id"]), {"stock": -1, "sale_price": None, "sale_ends_at": None, "available_from": None, "available_until": None})} for r in rows],
            "panels": [{"channel_id": str(p["channel_id"]), "message_id": str(p["message_id"])} for p in panels],
            "gains": {
                "daily": int(getattr(economy_cog, "DAILY_AMOUNT", 0)),
                "weekly": int(getattr(economy_cog, "WEEKLY_AMOUNT", 0)),
                "work_cooldown": int(getattr(economy_cog, "WORK_COOLDOWN", 0)),
                "daily_cooldown": int(getattr(economy_cog, "DAILY_COOLDOWN", 0)),
            },
        })

    async def economy_put(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        from cogs import setup_v2_core as core
        await core.set_currency(
            bot, guild.id,
            str(payload.get("currency_singular") or ""), str(payload.get("currency_plural") or ""), str(payload.get("currency_symbol") or ""),
            actor_id=int(session["user"]["id"]),
        )
        return web.json_response({"ok": True, "message": "Monnaie du serveur enregistrée."})

    async def _refresh_shop(guild: discord.Guild) -> None:
        cog = bot.get_cog("Economy") if hasattr(bot, "get_cog") else None
        refresh = getattr(cog, "_refresh_shop_panels", None)
        if refresh is None:
            return
        try:
            await refresh(guild)
        except Exception:
            logger.warning("Rafraîchissement du panneau boutique impossible", exc_info=True)

    async def shop_post(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        try:
            role = guild.get_role(int(payload.get("role_id")))
            price = _int(payload.get("price"), 1, 1_000_000_000_000, "prix")
        except (TypeError, ValueError) as exc:
            return dashboard._json_error(str(exc) or "Rôle invalide.", 400)
        if role is None:
            return dashboard._json_error("Ce rôle n'existe plus.", 400)
        from cogs.economy import _self_assignable_role_error
        problem = _self_assignable_role_error(guild, role)
        if problem:
            return dashboard._json_error(problem, 409)
        description = str(payload.get("description") or "").strip()[:200]
        existing = await bot.db.fetchone("SELECT id FROM shop_items WHERE guild_id = ? AND role_id = ?", (guild.id, role.id))
        if existing:
            item_id = int(existing["id"])
            await bot.db.execute("UPDATE shop_items SET name = ?, price = ?, description = ? WHERE id = ?", (role.name, price, description, item_id))
        else:
            cur = await bot.db.execute("INSERT INTO shop_items (guild_id, name, price, description, role_id) VALUES (?, ?, ?, ?, ?)", (guild.id, role.name, price, description, role.id))
            item_id = int(cur.lastrowid)
        # Règles V17 (stock, promotion, période) : mêmes colonnes que les commandes +shoprule.
        if any(k in payload for k in ("stock", "sale_price", "sale_ends_at", "available_from", "available_until")):
            def _opt_int(key, minimum=0, maximum=10**12):
                raw = payload.get(key)
                if raw in (None, "", "null"):
                    return None
                return _int(raw, minimum, maximum, key)
            try:
                stock = payload.get("stock")
                stock = -1 if stock in (None, "", "-1", -1) else _int(stock, 0, 1_000_000, "stock")
                sale_price = _opt_int("sale_price", 1)
                sale_ends_at = _opt_int("sale_ends_at")
                available_from = _opt_int("available_from")
                available_until = _opt_int("available_until")
            except ValueError as exc:
                return dashboard._json_error(str(exc), 400)
            if sale_price is not None and sale_price >= price:
                return dashboard._json_error("Le prix promotionnel doit être inférieur au prix normal.", 400)
            import time as _time
            # Même DDL que cogs/v17_shared (créée au chargement du cog ; garantie ici pour un
            # dashboard démarré avant les cogs).
            await bot.db.execute(
                "CREATE TABLE IF NOT EXISTS v17_shop_rules (guild_id INTEGER NOT NULL, item_id INTEGER NOT NULL, stock INTEGER NOT NULL DEFAULT -1, "
                "sale_price INTEGER, sale_ends_at INTEGER, available_from INTEGER, available_until INTEGER, updated_at INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, item_id))"
            )
            await bot.db.execute(
                "INSERT INTO v17_shop_rules (guild_id,item_id,stock,sale_price,sale_ends_at,available_from,available_until,updated_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(guild_id,item_id) DO UPDATE SET stock=excluded.stock,sale_price=excluded.sale_price,sale_ends_at=excluded.sale_ends_at,available_from=excluded.available_from,available_until=excluded.available_until,updated_at=excluded.updated_at",
                (guild.id, item_id, stock, sale_price, sale_ends_at, available_from, available_until, int(_time.time())),
            )
        await _refresh_shop(guild)
        return web.json_response({"ok": True, "message": f"@{role.name} est en vente pour {price}."})

    async def shop_delete(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        try:
            item_id = int(request.match_info["item_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Article invalide.", 400)
        cursor = await bot.db.execute("DELETE FROM shop_items WHERE guild_id = ? AND id = ?", (guild.id, item_id))
        if getattr(cursor, "rowcount", 1) < 1:
            return dashboard._json_error("Cet article n'existe plus.", 404)
        await _refresh_shop(guild)
        return web.json_response({"ok": True, "message": "Article retiré de la boutique."})

    async def games_get(request: web.Request):
        session, guild, error = await _guard(request)
        if error:
            return error
        from utils import game_rewards
        from cogs.games_economy import GAME_CATALOG
        settings = await game_rewards.get_settings(bot, guild.id)
        return web.json_response({
            "ok": True,
            "settings": {k: ([str(x) for x in v] if isinstance(v, list) else v) for k, v in settings.items()},
            "catalog": [{"key": key, "label": label, "kind": kind} for key, (label, kind) in GAME_CATALOG.items()],
        })

    async def games_put(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        from utils import game_rewards
        from cogs.games_economy import GAME_CATALOG
        updates: dict = {}
        for key in ("enabled", "logs_enabled", "leaderboard_enabled", "dm_results", "compact_mode"):
            if key in payload:
                updates[key] = bool(payload[key])
        if "disabled_games" in payload:
            updates["disabled_games"] = sorted({str(g) for g in (payload["disabled_games"] or []) if str(g) in GAME_CATALOG})
        for key in ("allowed_role_ids", "blocked_role_ids"):
            if key in payload:
                updates[key] = _role_ids(guild, payload[key])
        for key in ("allowed_channel_ids", "blocked_channel_ids"):
            if key in payload:
                ids = []
                for raw in payload[key] or []:
                    try:
                        cid = int(raw)
                    except (TypeError, ValueError):
                        continue
                    if guild.get_channel(cid) is not None and cid not in ids:
                        ids.append(cid)
                updates[key] = ids
        try:
            if "daily_limit" in payload:
                updates["daily_limit"] = _int(payload["daily_limit"], 0, 10000, "limite journalière")
        except ValueError as exc:
            return dashboard._json_error(str(exc), 400)
        if "default_difficulty" in payload and str(payload["default_difficulty"]) in {"facile", "normal", "difficile", "easy", "hard"}:
            updates["default_difficulty"] = str(payload["default_difficulty"])
        await game_rewards.set_settings(bot, guild.id, updates)
        return web.json_response({"ok": True, "message": "Réglages des jeux enregistrés."})

    # ------------------------------------------------------------------ Rôles
    async def roles_get(request: web.Request):
        session, guild, error = await _guard(request)
        if error:
            return error
        from cogs.verification import _is_notification_role, _self_role_error
        notif_panels = await bot.db.fetchall("SELECT channel_id, message_id, title, created_at FROM self_role_panels WHERE guild_id = ? ORDER BY created_at DESC", (guild.id,))
        reaction_panels = await bot.db.fetchall(
            "SELECT p.channel_id, p.message_id, p.title, COUNT(r.message_id) AS role_count FROM reaction_role_panels p "
            "LEFT JOIN reaction_roles r ON r.guild_id = p.guild_id AND r.message_id = p.message_id "
            "WHERE p.guild_id = ? GROUP BY p.id ORDER BY p.id DESC", (guild.id,),
        )
        reactions = await bot.db.fetchall("SELECT channel_id, message_id, emoji, emoji_key, role_id, label FROM reaction_roles WHERE guild_id = ? ORDER BY message_id, rowid", (guild.id,))
        notification_roles = [{"id": str(r.id), "name": r.name} for r in reversed(guild.roles) if _is_notification_role(r) and not _self_role_error(guild, r)]
        return web.json_response({
            "ok": True,
            "notification_roles": notification_roles,
            "notification_panels": [{"channel_id": str(p["channel_id"]), "message_id": str(p["message_id"]), "title": p["title"], "created_at": p["created_at"]} for p in notif_panels],
            "reaction_panels": [{"channel_id": str(p["channel_id"]), "message_id": str(p["message_id"]), "title": p["title"], "role_count": int(p["role_count"] or 0)} for p in reaction_panels],
            "reaction_roles": [{"channel_id": str(r["channel_id"]) if r["channel_id"] else None, "message_id": str(r["message_id"]), "emoji": r["emoji"], "emoji_key": r["emoji_key"], "role_id": str(r["role_id"]), "label": r["label"]} for r in reactions],
        })

    async def roles_panels_refresh(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        cog = bot.get_cog("Verification") if hasattr(bot, "get_cog") else None
        if cog is None:
            return dashboard._json_error("Le module des rôles est indisponible.", 503)
        rows = await bot.db.fetchall("SELECT message_id FROM self_role_panels WHERE guild_id = ?", (guild.id,))
        for row in rows:
            await cog._refresh_self_role_panel(guild, int(row["message_id"]))
        return web.json_response({"ok": True, "message": f"{len(rows)} panneau(x) actualisé(s)."})

    async def reaction_post(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        from cogs.verification import _emoji_parts, _self_role_error
        try:
            channel = guild.get_channel(int(payload.get("channel_id")))
            message_id = int(payload.get("message_id"))
            role = guild.get_role(int(payload.get("role_id")))
        except (TypeError, ValueError):
            return dashboard._json_error("Salon, message ou rôle invalide.", 400)
        if not isinstance(channel, discord.TextChannel) or role is None:
            return dashboard._json_error("Salon ou rôle introuvable.", 400)
        problem = _self_role_error(guild, role)
        if problem:
            return dashboard._json_error(problem, 409)
        try:
            emoji_key, emoji_display, emoji = _emoji_parts(str(payload.get("emoji") or ""))
        except ValueError:
            return dashboard._json_error("Utilisez un emoji Unicode ou un emoji personnalisé du serveur.", 400)
        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return dashboard._json_error("Message introuvable dans ce salon (vérifiez l'identifiant et les permissions de SentriX).", 404)
        count_row = await bot.db.fetchone("SELECT COUNT(*) AS total FROM reaction_roles WHERE guild_id = ? AND message_id = ?", (guild.id, message.id))
        existing = await bot.db.fetchone("SELECT rowid FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji_key = ?", (guild.id, message.id, emoji_key))
        if not existing and count_row and int(count_row["total"] or 0) >= 20:
            return dashboard._json_error("Un message Discord accepte au maximum 20 réactions différentes.", 409)
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            return dashboard._json_error(f"Discord refuse cet emoji : {exc}", 409)
        cog = bot.get_cog("Verification") if hasattr(bot, "get_cog") else None
        pseudo_ctx = SimpleNamespace(guild=guild, author=SimpleNamespace(id=int(session["user"]["id"])))
        panel = None
        if cog is not None:
            panel = await cog._register_panel_if_needed(pseudo_ctx, message)
        await bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND (emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (guild.id, message.id, emoji_key, emoji_display),
        )
        await bot.db.execute(
            "INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji, emoji_key, role_id, label, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild.id, channel.id, message.id, emoji_display, emoji_key, role.id, (str(payload.get("label") or "").strip() or role.name)[:100], int(session["user"]["id"])),
        )
        if cog is not None and panel is not None:
            try:
                await cog._refresh_role_panel(guild, panel, message)
            except Exception:
                logger.warning("Rafraîchissement du panneau de rôles impossible", exc_info=True)
        return web.json_response({"ok": True, "message": f"{emoji_display} donnera ou retirera @{role.name}."})

    async def channel_messages(request: web.Request):
        """Messages récents d'un salon, pour choisir visuellement la cible d'un rôle par réaction."""
        session, guild, error = await _guard(request)
        if error:
            return error
        try:
            channel = guild.get_channel(int(request.query.get("channel_id") or 0))
        except (TypeError, ValueError):
            channel = None
        if not isinstance(channel, discord.TextChannel):
            return dashboard._json_error("Choisissez un salon textuel.", 400)
        items = []
        try:
            async for message in channel.history(limit=30):
                text = (message.content or "").strip()
                if not text and message.embeds:
                    embed = message.embeds[0]
                    text = (embed.title or embed.description or "").strip()
                items.append({
                    "id": str(message.id),
                    "author": message.author.display_name if message.author else "?",
                    "bot": bool(getattr(message.author, "bot", False)),
                    "mine": bool(bot.user and message.author and message.author.id == bot.user.id),
                    "text": text[:120] or ("(pièce jointe)" if message.attachments else "(message vide)"),
                    "created_at": int(message.created_at.timestamp()) if message.created_at else None,
                    "reactions": sum(int(r.count) for r in message.reactions),
                })
        except (discord.Forbidden, discord.HTTPException):
            return dashboard._json_error("SentriX ne peut pas lire l'historique de ce salon.", 409)
        except Exception:
            logger.warning("Lecture de l'historique impossible", exc_info=True)
            return dashboard._json_error("Impossible de lire les messages de ce salon pour le moment.", 409)
        return web.json_response({"ok": True, "items": items})

    async def reaction_panel_create(request: web.Request):
        """Publie un nouveau message-panneau (titre + description) et l'enregistre comme panneau de rôles."""
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        payload = await _payload(request)
        try:
            channel = guild.get_channel(int(payload.get("channel_id") or 0))
        except (TypeError, ValueError):
            channel = None
        if not isinstance(channel, discord.TextChannel):
            return dashboard._json_error("Choisissez un salon textuel.", 400)
        title = str(payload.get("title") or "Choisissez vos rôles").strip()[:256] or "Choisissez vos rôles"
        description = str(payload.get("description") or "Réagissez avec l'emoji correspondant pour recevoir ou retirer un rôle.").strip()[:2000]
        from utils import embeds as embeds_util
        try:
            message = await channel.send(embed=embeds_util.brand(title, description))
        except discord.Forbidden:
            return dashboard._json_error("SentriX ne peut pas écrire dans ce salon.", 409)
        except discord.HTTPException as exc:
            return dashboard._json_error(f"Discord a refusé l'envoi : {exc}", 502)
        cog = bot.get_cog("Verification") if hasattr(bot, "get_cog") else None
        if cog is not None:
            pseudo_ctx = SimpleNamespace(guild=guild, author=SimpleNamespace(id=int(session["user"]["id"])))
            try:
                await cog._register_panel_if_needed(pseudo_ctx, message)
                await bot.db.execute("UPDATE reaction_role_panels SET title = ? WHERE guild_id = ? AND message_id = ?", (title, guild.id, message.id))
            except Exception:
                logger.warning("Enregistrement du panneau de rôles impossible", exc_info=True)
        return web.json_response({"ok": True, "message": f"Panneau publié dans #{channel.name}. Ajoutez maintenant les réactions.", "message_id": str(message.id), "channel_id": str(channel.id)})

    async def reaction_delete(request: web.Request):
        session, guild, error = await _guard(request, write=True)
        if error:
            return error
        try:
            message_id = int(request.match_info["message_id"])
        except (TypeError, ValueError):
            return dashboard._json_error("Message invalide.", 400)
        emoji_key = str(request.match_info["emoji_key"])
        row = await bot.db.fetchone(
            "SELECT channel_id, emoji FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND (emoji_key = ? OR emoji = ?)",
            (guild.id, message_id, emoji_key, emoji_key),
        )
        if row is None:
            return dashboard._json_error("Association introuvable.", 404)
        await bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND (emoji_key = ? OR emoji = ?)",
            (guild.id, message_id, emoji_key, emoji_key),
        )
        channel = guild.get_channel(int(row["channel_id"])) if row["channel_id"] else None
        if isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(message_id)
                await message.clear_reaction(row["emoji"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError):
                pass
        return web.json_response({"ok": True, "message": "Association retirée."})

    app.router.add_get("/api/guilds/{guild_id}/levels", levels_get)
    app.router.add_put("/api/guilds/{guild_id}/levels", levels_put)
    app.router.add_post("/api/guilds/{guild_id}/levels/roles", level_role_post)
    app.router.add_delete("/api/guilds/{guild_id}/levels/roles/{level}", level_role_delete)
    app.router.add_get("/api/guilds/{guild_id}/economy", economy_get)
    app.router.add_put("/api/guilds/{guild_id}/economy", economy_put)
    app.router.add_post("/api/guilds/{guild_id}/economy/shop", shop_post)
    app.router.add_delete("/api/guilds/{guild_id}/economy/shop/{item_id}", shop_delete)
    app.router.add_get("/api/guilds/{guild_id}/economy/games", games_get)
    app.router.add_put("/api/guilds/{guild_id}/economy/games", games_put)
    app.router.add_get("/api/guilds/{guild_id}/roles", roles_get)
    app.router.add_get("/api/guilds/{guild_id}/roles/messages", channel_messages)
    app.router.add_post("/api/guilds/{guild_id}/roles/panels/reaction", reaction_panel_create)
    app.router.add_post("/api/guilds/{guild_id}/roles/panels/refresh", roles_panels_refresh)
    app.router.add_post("/api/guilds/{guild_id}/roles/reactions", reaction_post)
    app.router.add_delete("/api/guilds/{guild_id}/roles/reactions/{message_id}/{emoji_key}", reaction_delete)

    # Jeux serveur : le Compteur Infini conserve son backend dédié, sans faux renommage
    # d'un mini-jeu d'économie. Enregistrer ici garantit aussi les routes dans le recovery.
    from .dashboard_api_games import register as register_games_routes
    register_games_routes(app, dashboard)

    # Routage canonique des journaux : log_config + événements V17.
    from .dashboard_api_logs import register as register_log_routes
    register_log_routes(app, dashboard)

    # Automatisations SentriX Plus : Starboard, sticky, annonces programmées, VoiceHub.
    from .dashboard_api_automation import register as register_automation_routes
    register_automation_routes(app, dashboard)

    # Centre de modération et profil communautaire : mêmes moteurs que les commandes.
    from .dashboard_api_moderation import register as register_moderation_routes
    register_moderation_routes(app, dashboard)
    from .dashboard_api_profile import register as register_profile_routes
    register_profile_routes(app, dashboard)


__all__ = ["register", "LEVEL_SETTING_KEYS"]
