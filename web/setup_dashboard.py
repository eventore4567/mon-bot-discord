"""Extension du dashboard SentriX : centre Setup complet et configuration des mini-jeux."""

from __future__ import annotations

import logging
import time

import discord
from aiohttp import web

from database.db import now
from utils import game_rewards

logger = logging.getLogger("bot.dashboard.setup")
_INSTALLED = False

PROTECTED_COMMANDS = {
    "help", "setup", "enablecommand", "disablecommand", "config-reset",
    "config-view", "dashboard",
}
MANAGER_CATEGORIES = {
    "configuration": "Configuration",
    "tickets": "Tickets",
    "moderation": "Modération",
    "securite": "Sécurité",
    "economie": "Économie et jeux",
    "complete": "Accès complet",
}


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


def _member_data(guild: discord.Guild, user_id: int) -> dict:
    member = guild.get_member(user_id)
    return {
        "id": str(user_id),
        "name": member.display_name if member else f"Utilisateur {user_id}",
        "avatar_url": str(member.display_avatar.url) if member else None,
    }


def _command_catalog(bot) -> list[dict]:
    commands = {}
    for command in bot.walk_commands():
        name = command.qualified_name.strip().lower()
        if not name or command.hidden:
            continue
        commands[name] = {
            "name": name,
            "description": (command.description or command.help or "Aucune description")[:180],
            "protected": name in PROTECTED_COMMANDS,
        }
    return sorted(commands.values(), key=lambda item: item["name"])


async def handle_setup_data(request: web.Request) -> web.Response:
    dashboard, session, guild, error = await _context(request)
    if error:
        return error
    bot = request.app["bot"]
    db = bot.db
    guild_id = guild.id

    disabled_rows = await db.fetchall(
        "SELECT command_name FROM disabled_commands WHERE guild_id = ? ORDER BY command_name",
        (guild_id,),
    )
    ignored_rows = await db.fetchall(
        "SELECT channel_id FROM ignored_channels WHERE guild_id = ? ORDER BY channel_id",
        (guild_id,),
    )
    exempt_rows = await db.fetchall(
        "SELECT role_id FROM automod_exempt_roles WHERE guild_id = ? ORDER BY role_id",
        (guild_id,),
    )
    whitelist_rows = await db.fetchall(
        "SELECT user_id FROM antinuke_whitelist WHERE guild_id = ? ORDER BY user_id",
        (guild_id,),
    )
    manager_rows = await db.fetchall(
        "SELECT user_id, added_by, added_at FROM bot_managers WHERE guild_id = ? ORDER BY added_at DESC",
        (guild_id,),
    )
    managers = []
    for row in manager_rows:
        categories = await db.get_manager_categories(guild_id, int(row["user_id"]))
        managers.append({
            **_member_data(guild, int(row["user_id"])),
            "categories": categories or ["complete"],
            "added_at": row["added_at"],
        })

    history_rows = await db.list_setup_history(guild_id, limit=20)
    history = []
    for row in history_rows:
        item = dict(row)
        item["user"] = _member_data(guild, int(item.get("user_id") or 0))
        history.append(item)

    games = await game_rewards.get_settings(bot, guild_id)
    try:
        from cogs.games_economy import GAME_CATALOG
        game_names = sorted(GAME_CATALOG.keys())
    except Exception:
        game_names = sorted(set(games.get("disabled_games", [])))

    conf = await db.get_guild_config(guild_id)
    return web.json_response({
        "ok": True,
        "commands": _command_catalog(bot),
        "disabled_commands": [row["command_name"] for row in disabled_rows],
        "ignored_channels": [str(row["channel_id"]) for row in ignored_rows],
        "automod_exempt_roles": [str(row["role_id"]) for row in exempt_rows],
        "antinuke_whitelist": [_member_data(guild, int(row["user_id"])) for row in whitelist_rows],
        "managers": managers,
        "manager_categories": MANAGER_CATEGORIES,
        "games": games,
        "game_names": game_names,
        "history": history,
        "verification": {
            "role_id": str(conf["verify_role"] or conf["verification_role"] or "") if conf else "",
            "channel_id": str(conf["verification_channel"] or "") if conf else "",
        },
    })


async def _rate_limit(request: web.Request, dashboard, guild_id: int, action: str):
    key = (request.cookies.get(dashboard.SESSION_COOKIE), guild_id, f"setup:{action}")
    current = time.time()
    if current - request.app["write_limits"].get(key, 0) < 0.8:
        return dashboard._json_error("Attendez un instant avant de recommencer.", 429)
    request.app["write_limits"][key] = current
    return None


async def handle_setup_action(request: web.Request) -> web.Response:
    dashboard, session, guild, error = await _context(request, write=True)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)
    if not isinstance(payload, dict):
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

    action = str(payload.get("action") or "").strip().lower()
    limited = await _rate_limit(request, dashboard, guild.id, action)
    if limited:
        return limited

    bot = request.app["bot"]
    db = bot.db
    guild_id = guild.id
    actor_id = int(session["user"]["id"])

    if action == "command":
        command_name = str(payload.get("command") or "").strip().lower()
        enabled = bool(payload.get("enabled"))
        catalog = {item["name"]: item for item in _command_catalog(bot)}
        if command_name not in catalog:
            return dashboard._json_error("Cette commande n'existe pas.", 404)
        if command_name in PROTECTED_COMMANDS:
            return dashboard._json_error("Cette commande est protégée pour éviter de bloquer la configuration du bot.", 400)
        if enabled:
            await db.execute(
                "DELETE FROM disabled_commands WHERE guild_id = ? AND command_name = ?",
                (guild_id, command_name),
            )
            message = f"La commande +{command_name} est de nouveau activée."
        else:
            await db.execute(
                "INSERT OR IGNORE INTO disabled_commands (guild_id, command_name) VALUES (?, ?)",
                (guild_id, command_name),
            )
            message = f"La commande +{command_name} est désactivée sur ce serveur."

    elif action == "ignored_channel":
        try:
            channel_id = int(payload.get("channel_id"))
        except (TypeError, ValueError):
            return dashboard._json_error("Choisissez un salon valide.", 400)
        channel = guild.get_channel(channel_id)
        if channel is None:
            return dashboard._json_error("Ce salon n'existe plus.", 404)
        ignored = bool(payload.get("ignored"))
        if ignored:
            await db.execute(
                "INSERT OR IGNORE INTO ignored_channels (guild_id, channel_id) VALUES (?, ?)",
                (guild_id, channel_id),
            )
            message = f"#{channel.name} est maintenant ignoré par les commandes configurables."
        else:
            await db.execute(
                "DELETE FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
                (guild_id, channel_id),
            )
            message = f"#{channel.name} n'est plus ignoré."

    elif action == "automod_exempt_role":
        try:
            role_id = int(payload.get("role_id"))
        except (TypeError, ValueError):
            return dashboard._json_error("Choisissez un rôle valide.", 400)
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed:
            return dashboard._json_error("Ce rôle ne peut pas être utilisé.", 400)
        exempt = bool(payload.get("exempt"))
        if exempt:
            await db.add_automod_exempt_role(guild_id, role_id)
            message = f"Le rôle {role.name} est maintenant exempté de l'AutoMod."
        else:
            await db.remove_automod_exempt_role(guild_id, role_id)
            message = f"Le rôle {role.name} n'est plus exempté de l'AutoMod."

    elif action == "antinuke_whitelist":
        try:
            user_id = int(str(payload.get("user_id") or "").strip())
        except (TypeError, ValueError):
            return dashboard._json_error("Entrez un ID Discord valide.", 400)
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return dashboard._json_error("Ce membre est introuvable sur le serveur.", 404)
        allowed = bool(payload.get("allowed"))
        if allowed:
            await db.execute(
                "INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            message = f"{member.display_name} est ajouté à la liste blanche anti-nuke."
        else:
            await db.execute(
                "DELETE FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            message = f"{member.display_name} est retiré de la liste blanche anti-nuke."

    elif action == "manager":
        try:
            user_id = int(str(payload.get("user_id") or "").strip())
        except (TypeError, ValueError):
            return dashboard._json_error("Entrez un ID Discord valide.", 400)
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return dashboard._json_error("Ce membre est introuvable sur le serveur.", 404)
        enabled = bool(payload.get("enabled"))
        if enabled:
            categories = payload.get("categories") or ["complete"]
            if not isinstance(categories, list):
                return dashboard._json_error("Les permissions du gestionnaire sont invalides.", 400)
            categories = [str(item) for item in categories if str(item) in MANAGER_CATEGORIES]
            if not categories:
                categories = ["complete"]
            if "complete" in categories:
                categories = ["complete"]
            await db.add_bot_manager(guild_id, user_id, actor_id)
            await db.set_manager_categories(guild_id, user_id, categories, actor_id)
            message = f"{member.display_name} peut maintenant gérer SentriX depuis les catégories choisies."
        else:
            await db.remove_bot_manager(guild_id, user_id)
            message = f"{member.display_name} n'est plus gestionnaire de SentriX."

    elif action == "create_logs":
        cog = bot.get_cog("Configuration")
        actor = guild.get_member(actor_id)
        if cog is None or actor is None or not hasattr(cog, "create_log_channels"):
            return dashboard._json_error("Le module de création des logs est indisponible.", 503)
        try:
            created = await cog.create_log_channels(guild, actor)
        except discord.Forbidden:
            return dashboard._json_error("SentriX n'a pas la permission de créer les salons de logs.", 403)
        message = (
            f"{len(created)} salon(s) de logs ont été créés et configurés."
            if created else "Tous les salons de logs étaient déjà configurés."
        )

    elif action == "verify_panel":
        try:
            channel_id = int(payload.get("channel_id"))
            role_id = int(payload.get("role_id"))
        except (TypeError, ValueError):
            return dashboard._json_error("Choisissez le salon et le rôle de vérification.", 400)
        channel = guild.get_channel(channel_id)
        role = guild.get_role(role_id)
        if not isinstance(channel, discord.TextChannel):
            return dashboard._json_error("Le panneau doit être envoyé dans un salon textuel.", 400)
        if role is None or role.is_default() or role.managed or (guild.me and role >= guild.me.top_role):
            return dashboard._json_error("Le rôle de vérification doit être un rôle attribuable placé sous SentriX.", 400)
        await db.set_guild_config(guild_id, "verify_role", role_id)
        await db.set_guild_config(guild_id, "verification_role", role_id)
        await db.set_guild_config(guild_id, "verification_channel", channel_id)
        from cogs.verification import VerifyView
        cog = bot.get_cog("Verification")
        if cog is not None and hasattr(cog, "_embed"):
            embed = await cog._embed(
                guild_id,
                title="Vérification",
                description="Cliquez sur le bouton ci-dessous après avoir lu les règles du serveur pour obtenir l'accès complet.",
            )
        else:
            from utils import embeds
            embed = embeds.brand(
                "Vérification",
                "Cliquez sur le bouton ci-dessous après avoir lu les règles du serveur pour obtenir l'accès complet.",
            )
        await channel.send(embed=embed, view=VerifyView())
        message = f"Le panneau de vérification a été publié dans #{channel.name}."

    elif action == "self_role_panel":
        try:
            channel_id = int(payload.get("channel_id"))
        except (TypeError, ValueError):
            return dashboard._json_error("Choisissez un salon textuel.", 400)
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return dashboard._json_error("Le panneau doit être envoyé dans un salon textuel.", 400)
        title = str(payload.get("title") or "Choisissez vos notifications").strip()[:256]
        cog = bot.get_cog("Verification")
        if cog is None:
            return dashboard._json_error("Le module des rôles est indisponible.", 503)
        from cogs.verification import SelfRolePublicView
        options = await cog._self_role_options(guild, 0)
        temporary_panel = {"title": title}
        embed = await cog._self_role_embed(guild, temporary_panel, options)
        sent = await channel.send(embed=embed, view=SelfRolePublicView(options))
        await db.execute(
            "INSERT INTO self_role_panels (guild_id, channel_id, message_id, title, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, message_id) DO NOTHING",
            (guild_id, channel_id, sent.id, title, actor_id, now()),
        )
        message = f"Le panneau de rôles a été publié dans #{channel.name}."

    elif action == "reset":
        scope = str(payload.get("scope") or "").strip().lower()
        confirmation = str(payload.get("confirmation") or "").strip()
        if confirmation != guild.name:
            return dashboard._json_error("Écrivez exactement le nom du serveur pour confirmer.", 400)
        if scope == "commands":
            await db.execute("DELETE FROM disabled_commands WHERE guild_id = ?", (guild_id,))
            message = "Toutes les commandes ont été réactivées."
        elif scope == "ignored":
            await db.execute("DELETE FROM ignored_channels WHERE guild_id = ?", (guild_id,))
            message = "Tous les salons ignorés ont été retirés."
        elif scope == "games":
            await db.execute("DELETE FROM game_settings WHERE guild_id = ?", (guild_id,))
            message = "La configuration des mini-jeux a été réinitialisée."
        elif scope == "security":
            await db.execute("DELETE FROM automod_settings WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM automod_exempt_roles WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM antinuke_whitelist WHERE guild_id = ?", (guild_id,))
            await db.ensure_guild(guild_id)
            message = "La sécurité, les exemptions et la liste blanche ont été réinitialisées."
        elif scope == "all":
            for table in (
                "guild_config", "automod_settings", "disabled_commands", "ignored_channels",
                "automod_exempt_roles", "antinuke_whitelist", "game_settings", "log_settings",
            ):
                await db.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
            cache = getattr(db, "_guild_config_cache", None)
            if isinstance(cache, dict):
                cache.pop(guild_id, None)
            await db.ensure_guild(guild_id)
            message = "Toute la configuration générale de SentriX a été réinitialisée pour ce serveur."
        else:
            return dashboard._json_error("Choisissez une section valide à réinitialiser.", 400)
    else:
        return dashboard._json_error("Cette action Setup n'est pas reconnue.", 400)

    try:
        await db.log_setup_history(guild_id, actor_id, "dashboard", action, None, message)
    except Exception:
        pass
    logger.info(
        "Dashboard Setup : %s (%s) a exécuté %s sur %s (%s).",
        session["user"]["username"], actor_id, action, guild.name, guild_id,
    )
    return web.json_response({"ok": True, "message": message})


async def handle_save_games(request: web.Request) -> web.Response:
    dashboard, session, guild, error = await _context(request, write=True)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)
    if not isinstance(payload, dict):
        return dashboard._json_error("Le formulaire envoyé est invalide.", 400)

    bool_fields = {"enabled", "logs_enabled", "leaderboard_enabled", "dm_results", "compact_mode"}
    list_fields = {"disabled_games", "allowed_channel_ids", "blocked_channel_ids", "allowed_role_ids", "blocked_role_ids"}
    updates = {}
    for field in bool_fields:
        if field in payload:
            updates[field] = bool(payload[field])
    for field in list_fields:
        value = payload.get(field, [])
        if not isinstance(value, list) or len(value) > 100:
            return dashboard._json_error(f"Le réglage {field} est invalide.", 400)
        if field == "disabled_games":
            updates[field] = sorted({str(item).strip() for item in value if str(item).strip()})
        else:
            clean_ids = []
            for item in value:
                try:
                    item_id = int(item)
                except (TypeError, ValueError):
                    return dashboard._json_error(f"Le réglage {field} contient un identifiant invalide.", 400)
                if field.endswith("channel_ids") and guild.get_channel(item_id) is None:
                    return dashboard._json_error("Un salon sélectionné n'existe plus.", 400)
                if field.endswith("role_ids") and guild.get_role(item_id) is None:
                    return dashboard._json_error("Un rôle sélectionné n'existe plus.", 400)
                clean_ids.append(item_id)
            updates[field] = sorted(set(clean_ids))

    try:
        daily_limit = int(payload.get("daily_limit", 50))
        event_multiplier = float(payload.get("event_multiplier", 1))
        minimum = float(payload.get("min_reward_multiplier", 1))
        maximum = float(payload.get("max_reward_multiplier", 1))
    except (TypeError, ValueError):
        return dashboard._json_error("Les limites et multiplicateurs doivent être des nombres.", 400)
    if not 0 <= daily_limit <= 10000:
        return dashboard._json_error("La limite journalière doit être comprise entre 0 et 10 000.", 400)
    if not 0 <= event_multiplier <= 100 or not 0 <= minimum <= 100 or not 0 <= maximum <= 100:
        return dashboard._json_error("Les multiplicateurs doivent être compris entre 0 et 100.", 400)
    if minimum > maximum:
        return dashboard._json_error("Le multiplicateur minimum ne peut pas dépasser le maximum.", 400)
    difficulty = str(payload.get("default_difficulty") or "normal").lower()
    if difficulty not in {"facile", "normal", "difficile"}:
        return dashboard._json_error("La difficulté doit être facile, normale ou difficile.", 400)
    updates.update({
        "daily_limit": daily_limit,
        "event_multiplier": event_multiplier,
        "min_reward_multiplier": minimum,
        "max_reward_multiplier": maximum,
        "default_difficulty": difficulty,
    })
    saved = await game_rewards.set_settings(request.app["bot"], guild.id, updates)
    await request.app["bot"].db.log_setup_history(
        guild.id, int(session["user"]["id"]), "games", "Mise à jour depuis le dashboard", None, "gamesetup",
    )
    return web.json_response({"ok": True, "message": "Configuration des mini-jeux enregistrée.", "games": saved})


SETUP_CSS = r"""
    .setup-grid{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;width:100%}
    .setup-card{background:#0d111c;border:1px solid #252d43;border-radius:15px;padding:17px;display:grid;gap:12px;align-content:start;min-width:0}
    .setup-card.full{grid-column:1/-1}.setup-card h3{margin:0;font-size:16px}.setup-card p{margin:0;color:var(--muted);font-size:12px;line-height:1.55}
    .setup-row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.setup-row>*{flex:1 1 170px}.setup-row .btn{flex:0 0 auto}
    .setup-list{display:grid;gap:7px;max-height:270px;overflow:auto}.setup-item{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 10px;border:1px solid #242c40;background:#111725;border-radius:10px;min-width:0}.setup-item span{min-width:0;overflow:hidden;text-overflow:ellipsis}.setup-item small{display:block;color:var(--muted);margin-top:2px}.setup-item .btn{padding:7px 10px;font-size:12px;flex:0 0 auto}
    .setup-empty{padding:10px;border:1px dashed #394158;border-radius:10px;color:var(--muted);font-size:12px}.setup-checks{display:flex;gap:7px;flex-wrap:wrap}.setup-check{display:flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid #2d3650;border-radius:9px;background:#111725;font-size:12px}.setup-check input{width:auto}
    .setup-danger{border-color:#713044;background:#24131a}.setup-history{font-size:12px}.games-grid{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;width:100%}.games-grid .full{grid-column:1/-1}.multi-select{min-height:145px}.setup-badge{display:inline-flex;padding:4px 8px;border-radius:999px;background:#16283d;border:1px solid #345a82;color:#b8d8ff;font-size:11px;font-weight:800}
    @media(max-width:850px){.setup-grid,.games-grid{grid-template-columns:1fr}.setup-card.full,.games-grid .full{grid-column:auto}}
"""


SETUP_JS = r"""
    state.setupTools=null;
    async function loadSetupTools(force=false){
      if(!state.guildId)return null;
      if(!state.setupTools||force)state.setupTools=await json(`/api/guilds/${state.guildId}/setup-tools`);
      return state.setupTools;
    }
    function setupChannelOptions(selected="",types=["text","news","voice","category"]){return '<option value="">Choisissez un salon</option>'+state.guildData.channels.filter(c=>types.includes(c.type)).map(c=>`<option value="${esc(c.id)}" ${String(c.id)===String(selected)?"selected":""}>${esc(c.name)} — ${esc(c.type)}</option>`).join("");}
    function setupRoleOptions(selected=""){return '<option value="">Choisissez un rôle</option>'+state.guildData.roles.map(r=>`<option value="${esc(r.id)}" ${String(r.id)===String(selected)?"selected":""}>${esc(r.name)}</option>`).join("");}
    function setupMultiOptions(items,selected=[]){const set=new Set((selected||[]).map(String));return items.map(item=>`<option value="${esc(item.id)}" ${set.has(String(item.id))?"selected":""}>${esc(item.name)}</option>`).join("");}
    function setupList(items,render,empty="Aucun élément configuré."){return items.length?`<div class="setup-list">${items.map(render).join("")}</div>`:`<div class="setup-empty">${esc(empty)}</div>`;}
    async function setupAction(payload){
      $("settingsForm").classList.add("loading");
      try{const result=await json(`/api/guilds/${state.guildId}/setup-tools`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(payload)});toast(result.message);await loadSetupTools(true);if(state.tab==="setupTools")renderSetupTools();else if(state.tab==="gamesSetup")renderGamesSetup();return result;}
      catch(e){toast(e.message,true);throw e;}finally{$("settingsForm").classList.remove("loading");}
    }
    function bindSetupButtons(){
      document.querySelectorAll("[data-setup-action]").forEach(button=>button.addEventListener("click",async()=>{
        const action=button.dataset.setupAction;
        if(action==="disable-command"){const value=$("setupCommand").value;if(value)await setupAction({action:"command",command:value,enabled:false});}
        else if(action==="enable-command")await setupAction({action:"command",command:button.dataset.value,enabled:true});
        else if(action==="ignore-channel"){const value=$("setupIgnoredChannel").value;if(value)await setupAction({action:"ignored_channel",channel_id:value,ignored:true});}
        else if(action==="unignore-channel")await setupAction({action:"ignored_channel",channel_id:button.dataset.value,ignored:false});
        else if(action==="exempt-role"){const value=$("setupExemptRole").value;if(value)await setupAction({action:"automod_exempt_role",role_id:value,exempt:true});}
        else if(action==="remove-exempt-role")await setupAction({action:"automod_exempt_role",role_id:button.dataset.value,exempt:false});
        else if(action==="whitelist-user"){const value=$("setupWhitelistUser").value;if(value)await setupAction({action:"antinuke_whitelist",user_id:value,allowed:true});}
        else if(action==="remove-whitelist")await setupAction({action:"antinuke_whitelist",user_id:button.dataset.value,allowed:false});
        else if(action==="add-manager"){const value=$("setupManagerUser").value;const categories=[...document.querySelectorAll(".setupManagerCategory:checked")].map(el=>el.value);if(value)await setupAction({action:"manager",user_id:value,enabled:true,categories});}
        else if(action==="remove-manager")await setupAction({action:"manager",user_id:button.dataset.value,enabled:false});
        else if(action==="create-logs")await setupAction({action:"create_logs"});
        else if(action==="verify-panel"){await setupAction({action:"verify_panel",channel_id:$("setupVerifyChannel").value,role_id:$("setupVerifyRole").value});}
        else if(action==="role-panel"){await setupAction({action:"self_role_panel",channel_id:$("setupRolePanelChannel").value,title:$("setupRolePanelTitle").value});}
        else if(action==="reset"){await setupAction({action:"reset",scope:$("setupResetScope").value,confirmation:$("setupResetConfirm").value});await selectGuild(state.guildId);}
        else if(action==="open-tab"){state.tab=button.dataset.value;document.querySelectorAll("#navigation button").forEach(b=>b.classList.toggle("active",b.dataset.tab===state.tab));renderTab();}
      }));
    }
    async function renderSetupTools(){
      $("fields").innerHTML='<div class="setup-empty">Chargement du centre Setup…</div>';
      const d=await loadSetupTools();if(state.tab!=="setupTools")return;
      const disabled=new Set(d.disabled_commands),ignored=new Set(d.ignored_channels),exempt=new Set(d.automod_exempt_roles);
      const availableCommands=d.commands.filter(c=>!c.protected&&!disabled.has(c.name));
      const availableChannels=state.guildData.channels.filter(c=>!ignored.has(String(c.id)));
      const availableRoles=state.guildData.roles.filter(r=>!exempt.has(String(r.id)));
      const disabledList=setupList(d.disabled_commands,name=>`<div class="setup-item"><span><b>+${esc(name)}</b><small>Commande désactivée</small></span><button type="button" class="btn" data-setup-action="enable-command" data-value="${esc(name)}">Réactiver</button></div>`);
      const ignoredList=setupList(d.ignored_channels,id=>{const c=state.guildData.channels.find(x=>String(x.id)===String(id));return `<div class="setup-item"><span><b>#${esc(c?.name||id)}</b><small>Salon ignoré</small></span><button type="button" class="btn" data-setup-action="unignore-channel" data-value="${esc(id)}">Retirer</button></div>`;});
      const exemptList=setupList(d.automod_exempt_roles,id=>{const r=state.guildData.roles.find(x=>String(x.id)===String(id));return `<div class="setup-item"><span><b>${esc(r?.name||id)}</b><small>Exempté de l'AutoMod</small></span><button type="button" class="btn" data-setup-action="remove-exempt-role" data-value="${esc(id)}">Retirer</button></div>`;});
      const whitelistList=setupList(d.antinuke_whitelist,u=>`<div class="setup-item"><span><b>${esc(u.name)}</b><small>${esc(u.id)}</small></span><button type="button" class="btn" data-setup-action="remove-whitelist" data-value="${esc(u.id)}">Retirer</button></div>`);
      const managerList=setupList(d.managers,m=>`<div class="setup-item"><span><b>${esc(m.name)}</b><small>${esc(m.categories.map(c=>d.manager_categories[c]||c).join(", "))}</small></span><button type="button" class="btn danger" data-setup-action="remove-manager" data-value="${esc(m.id)}">Retirer</button></div>`);
      const history=setupList(d.history,h=>`<div class="setup-item setup-history"><span><b>${esc(h.module||"Setup")} — ${esc(h.action||"")}</b><small>${esc(h.user?.name||h.user_id||"")}${h.new_value?" · "+esc(h.new_value):""}</small></span></div>`,"Aucune modification récente.");
      $("fields").innerHTML=`<div class="setup-grid">
        <section class="setup-card full"><h3>Centre Setup complet</h3><p>Les onglets déjà présents restent séparés pour être plus clairs. Les boutons ci-dessous ouvrent directement la bonne section.</p><div class="setup-row">${[["general","Général"],["security","Sécurité"],["logs","Logs"],["welcome","Accueil"],["levels","Niveaux"],["tickets","Tickets"],["roles","Rôles et salons"],["gamesSetup","Mini-jeux"]].map(x=>`<button type="button" class="btn" data-setup-action="open-tab" data-value="${x[0]}">${x[1]}</button>`).join("")}</div></section>
        <section class="setup-card"><h3>Commandes désactivées</h3><p>Équivalent de +disablecommand et +enablecommand.</p><div class="setup-row"><select class="select" id="setupCommand"><option value="">Choisissez une commande</option>${availableCommands.map(c=>`<option value="${esc(c.name)}">+${esc(c.name)}</option>`).join("")}</select><button type="button" class="btn danger" data-setup-action="disable-command">Désactiver</button></div>${disabledList}</section>
        <section class="setup-card"><h3>Salons ignorés</h3><p>Équivalent de +ignorechannel et +unignorechannel.</p><div class="setup-row"><select class="select" id="setupIgnoredChannel"><option value="">Choisissez un salon</option>${availableChannels.map(c=>`<option value="${esc(c.id)}">${esc(c.name)} — ${esc(c.type)}</option>`).join("")}</select><button type="button" class="btn" data-setup-action="ignore-channel">Ignorer</button></div>${ignoredList}</section>
        <section class="setup-card"><h3>Rôles exemptés de l'AutoMod</h3><p>Les membres ayant ces rôles ne seront pas filtrés par l'AutoMod.</p><div class="setup-row"><select class="select" id="setupExemptRole"><option value="">Choisissez un rôle</option>${availableRoles.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("")}</select><button type="button" class="btn" data-setup-action="exempt-role">Exempter</button></div>${exemptList}</section>
        <section class="setup-card"><h3>Liste blanche anti-nuke</h3><p>Ajoutez uniquement des personnes de confiance par leur ID Discord.</p><div class="setup-row"><input id="setupWhitelistUser" inputmode="numeric" placeholder="ID Discord du membre"><button type="button" class="btn" data-setup-action="whitelist-user">Ajouter</button></div>${whitelistList}</section>
        <section class="setup-card"><h3>Création automatique des logs</h3><p>Équivalent de +create-logs. Les salons existants sont conservés et seuls les manquants sont créés.</p><button type="button" class="btn primary" data-setup-action="create-logs">Créer/configurer tous les logs</button></section>
        <section class="setup-card"><h3>Panneau de vérification</h3><p>Équivalent de +verify-setup puis +verify-panel.</p><select class="select" id="setupVerifyChannel">${setupChannelOptions(d.verification.channel_id,["text","news"])}</select><select class="select" id="setupVerifyRole">${setupRoleOptions(d.verification.role_id)}</select><button type="button" class="btn primary" data-setup-action="verify-panel">Enregistrer et publier</button></section>
        <section class="setup-card"><h3>Panneau des rôles de notification</h3><p>Publie un menu avec les rôles contenant Ping ou Notifications dans leur nom.</p><select class="select" id="setupRolePanelChannel">${setupChannelOptions("",["text","news"])}</select><input id="setupRolePanelTitle" maxlength="256" value="Choisissez vos notifications"><button type="button" class="btn primary" data-setup-action="role-panel">Publier le panneau</button></section>
        <section class="setup-card"><h3>Gestionnaires du bot</h3><p>Autorisez un membre sans lui donner accès aux autres serveurs.</p><input id="setupManagerUser" inputmode="numeric" placeholder="ID Discord du membre"><div class="setup-checks">${Object.entries(d.manager_categories).map(([key,label])=>`<label class="setup-check"><input class="setupManagerCategory" type="checkbox" value="${esc(key)}" ${key==="complete"?"checked":""}>${esc(label)}</label>`).join("")}</div><button type="button" class="btn primary" data-setup-action="add-manager">Ajouter / mettre à jour</button>${managerList}</section>
        <section class="setup-card full"><h3>Historique du Setup</h3><p>Dernières modifications enregistrées depuis Discord et le dashboard.</p>${history}</section>
        <section class="setup-card full setup-danger"><h3>Réinitialiser une configuration</h3><p>Équivalent de +config-reset. Cette action est irréversible. Écrivez exactement le nom du serveur pour confirmer.</p><div class="setup-row"><select class="select" id="setupResetScope"><option value="commands">Commandes désactivées</option><option value="ignored">Salons ignorés</option><option value="games">Mini-jeux</option><option value="security">Sécurité</option><option value="all">Toute la configuration SentriX</option></select><input id="setupResetConfirm" placeholder="${esc(state.guildData.guild.name)}"><button type="button" class="btn danger" data-setup-action="reset">Réinitialiser</button></div></section>
      </div>`;
      bindSetupButtons();$("saveStatus").textContent="Configuration chargée";state.dirty=false;
    }
    async function renderGamesSetup(){
      $("fields").innerHTML='<div class="setup-empty">Chargement des mini-jeux…</div>';
      const d=await loadSetupTools();if(state.tab!=="gamesSetup")return;const g=d.games;
      const gameOptions=d.game_names.map(name=>`<option value="${esc(name)}" ${(g.disabled_games||[]).includes(name)?"selected":""}>${esc(name)}</option>`).join("");
      const channels=state.guildData.channels.filter(c=>["text","news"].includes(c.type));
      $("fields").innerHTML=`<div class="games-grid">
        <label class="switch full"><input data-game-key="enabled" type="checkbox" ${g.enabled?"checked":""}><span></span><b>Activer le système de mini-jeux</b></label>
        <div class="field"><label>Limite quotidienne par joueur</label><input data-game-key="daily_limit" type="number" min="0" max="10000" value="${esc(g.daily_limit)}"><div class="hint">0 = illimitée.</div></div>
        <div class="field"><label>Difficulté par défaut</label><select data-game-key="default_difficulty" class="select"><option value="facile" ${g.default_difficulty==="facile"?"selected":""}>Facile</option><option value="normal" ${g.default_difficulty==="normal"?"selected":""}>Normale</option><option value="difficile" ${g.default_difficulty==="difficile"?"selected":""}>Difficile</option></select></div>
        <div class="field"><label>Multiplicateur d'événement</label><input data-game-key="event_multiplier" type="number" min="0" max="100" step="0.1" value="${esc(g.event_multiplier)}"></div>
        <div class="field"><label>Récompense minimum</label><input data-game-key="min_reward_multiplier" type="number" min="0" max="100" step="0.1" value="${esc(g.min_reward_multiplier)}"></div>
        <div class="field"><label>Récompense maximum</label><input data-game-key="max_reward_multiplier" type="number" min="0" max="100" step="0.1" value="${esc(g.max_reward_multiplier)}"></div>
        <div class="field full"><label>Jeux désactivés</label><select data-game-key="disabled_games" class="select multi-select" multiple>${gameOptions}</select><div class="hint">Maintenez Ctrl/Cmd pour sélectionner plusieurs jeux.</div></div>
        <div class="field"><label>Salons autorisés uniquement</label><select data-game-key="allowed_channel_ids" class="select multi-select" multiple>${setupMultiOptions(channels,g.allowed_channel_ids)}</select></div>
        <div class="field"><label>Salons bloqués</label><select data-game-key="blocked_channel_ids" class="select multi-select" multiple>${setupMultiOptions(channels,g.blocked_channel_ids)}</select></div>
        <div class="field"><label>Rôles autorisés uniquement</label><select data-game-key="allowed_role_ids" class="select multi-select" multiple>${setupMultiOptions(state.guildData.roles,g.allowed_role_ids)}</select></div>
        <div class="field"><label>Rôles bloqués</label><select data-game-key="blocked_role_ids" class="select multi-select" multiple>${setupMultiOptions(state.guildData.roles,g.blocked_role_ids)}</select></div>
        ${[["logs_enabled","Journaliser les récompenses"],["leaderboard_enabled","Activer le classement"],["dm_results","Envoyer les résultats en MP"],["compact_mode","Mode d'affichage compact"]].map(([key,label])=>`<label class="switch"><input data-game-key="${key}" type="checkbox" ${g[key]?"checked":""}><span></span><b>${label}</b></label>`).join("")}
      </div>`;
      $("fields").querySelectorAll("[data-game-key]").forEach(el=>el.addEventListener("input",()=>{state.dirty=true;$("saveStatus").textContent="Modifications non enregistrées";}));
    }
    function collectGamePayload(){const out={};document.querySelectorAll("[data-game-key]").forEach(el=>{const key=el.dataset.gameKey;if(el.type==="checkbox")out[key]=el.checked;else if(el.multiple)out[key]=[...el.selectedOptions].map(o=>o.value);else out[key]=el.value;});return out;}
    async function saveGamesSetup(){
      $("settingsForm").classList.add("loading");try{const result=await json(`/api/guilds/${state.guildId}/games`,{method:"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(collectGamePayload())});toast(result.message);state.setupTools.games=result.games;state.dirty=false;$("saveStatus").textContent="Mini-jeux configurés";renderGamesSetup();}catch(e){toast(e.message,true);}finally{$("settingsForm").classList.remove("loading");}
    }
"""


def _replace_once(html: str, old: str, new: str, label: str) -> str:
    if old not in html:
        logger.warning("Dashboard Setup : point d'insertion introuvable (%s).", label)
        return html
    return html.replace(old, new, 1)


def _patch_html(html: str) -> str:
    html = _replace_once(html, "  </style>", SETUP_CSS + "\n  </style>", "css")
    html = _replace_once(
        html,
        '        <button data-tab="roles">Rôles et salons</button>\n',
        '        <button data-tab="roles">Rôles et salons</button>\n        <button data-tab="gamesSetup">Mini-jeux</button>\n        <button data-tab="setupTools">Setup avancé</button>\n',
        "navigation",
    )
    old_tabs_end = '      ].map(x=>({key:x[0],label:x[1],type:x[2]}))}\n    };'
    new_tabs_end = '''      ].map(x=>({key:x[0],label:x[1],type:x[2]}))},
      gamesSetup:{title:"Configuration des mini-jeux",description:"Toutes les options de +gamesetup directement depuis le dashboard.",gamesSetup:true,fields:[]},
      setupTools:{title:"Setup avancé",description:"Commandes de configuration absentes des autres onglets.",setupTools:true,fields:[]}
    };'''
    html = _replace_once(html, old_tabs_end, new_tabs_end, "tabs")
    html = _replace_once(html, "    function renderTab(){", SETUP_JS + "\n    function renderTab(){", "javascript")

    old_render = '    function renderTab(){if(!state.guildData)return;const tab=tabs[state.tab];$("tabTitle").textContent=tab.title;$("tabDescription").textContent=tab.description;if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();else if(tab.embeds)renderEmbeds();else $("fields").innerHTML=tab.fields.map(fieldHTML).join("");$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions));$("saveButton").textContent=tab.notifications?"Ajouter la notification":tab.embeds?"Envoyer l\'embed":"Enregistrer";$("saveStatus").textContent=tab.notifications?"Surveillance toutes les 5 minutes":tab.embeds?"Aperçu en direct":"Aucune modification";state.dirty=false;$("fields").querySelectorAll("input,select,textarea").forEach(el=>el.addEventListener("input",()=>{if(tab.sanctions)return;state.dirty=true;if(!tab.embeds)$("saveStatus").textContent="Modifications non enregistrées";}));}\n'
    new_render = '''    function renderTab(){if(!state.guildData)return;const tab=tabs[state.tab];$("tabTitle").textContent=tab.title;$("tabDescription").textContent=tab.description;if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();else if(tab.embeds)renderEmbeds();else if(tab.gamesSetup)renderGamesSetup();else if(tab.setupTools)renderSetupTools();else $("fields").innerHTML=tab.fields.map(fieldHTML).join("");$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions||tab.setupTools));$("saveButton").textContent=tab.notifications?"Ajouter la notification":tab.embeds?"Envoyer l'embed":tab.gamesSetup?"Enregistrer les mini-jeux":"Enregistrer";$("saveStatus").textContent=tab.notifications?"Surveillance toutes les 5 minutes":tab.embeds?"Aperçu en direct":tab.gamesSetup?"Configuration complète":"Aucune modification";state.dirty=false;$("fields").querySelectorAll("input,select,textarea").forEach(el=>el.addEventListener("input",()=>{if(tab.sanctions||tab.setupTools)return;state.dirty=true;if(!tab.embeds)$("saveStatus").textContent="Modifications non enregistrées";}));}\n'''
    html = _replace_once(html, old_render, new_render, "renderTab")
    old_save = '    async function save(event){event.preventDefault();if(!state.guildId||!state.guildData)return;const tab=tabs[state.tab];if(tab.sanctions){await loadSanctions(true);return;}if(tab.embeds){await sendEmbed();return;}const values={};'
    new_save = '    async function save(event){event.preventDefault();if(!state.guildId||!state.guildData)return;const tab=tabs[state.tab];if(tab.sanctions){await loadSanctions(true);return;}if(tab.embeds){await sendEmbed();return;}if(tab.gamesSetup){await saveGamesSetup();return;}if(tab.setupTools){return;}const values={};'
    html = _replace_once(html, old_save, new_save, "save")
    old_select = 'state.guildData=await json(`/api/guilds/${value}`);const d=state.guildData;'
    new_select = 'state.guildData=await json(`/api/guilds/${value}`);state.setupTools=null;const d=state.guildData;'
    html = _replace_once(html, old_select, new_select, "guild-change")
    return html


def install(dashboard) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    dashboard.INDEX_HTML = _patch_html(dashboard.INDEX_HTML)
    original_build_app = dashboard.build_app

    def build_app(bot) -> web.Application:
        app = original_build_app(bot)
        app["dashboard_module"] = dashboard
        app.router.add_get("/api/guilds/{guild_id}/setup-tools", handle_setup_data)
        app.router.add_post("/api/guilds/{guild_id}/setup-tools", handle_setup_action)
        app.router.add_put("/api/guilds/{guild_id}/games", handle_save_games)
        return app

    dashboard.build_app = build_app
    logger.info("Centre Setup complet du dashboard chargé.")
