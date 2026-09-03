"""
Application web SentriX.

Le dashboard tourne dans le même processus aiohttp que le bot. La page publique affiche
l'état de SentriX et son lien d'invitation. La partie administration utilise le flux OAuth2
Discord (identify + guilds), une session opaque côté serveur, un jeton CSRF et une nouvelle
vérification des permissions Discord à chaque lecture ou modification d'un serveur.

Variables Railway nécessaires pour la connexion :
- DISCORD_CLIENT_SECRET : secret OAuth2 de l'application Discord ;
- DASHBOARD_PUBLIC_URL : URL HTTPS publique, sans slash final (recommandé).

Le client ID est lu depuis DISCORD_CLIENT_ID s'il existe, sinon depuis l'identité du bot.
Aucun token utilisateur, token du bot ou secret OAuth n'est envoyé au navigateur.
"""

import logging
import secrets
import time
from urllib.parse import urlencode, urlparse, urlunparse

import discord
from aiohttp import BasicAuth, ClientSession, web

import config
from database.db import now

logger = logging.getLogger("bot.dashboard")

START_TIME = time.time()
DISCORD_API = "https://discord.com/api/v10"
DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
SESSION_COOKIE = "sentrix_session"
OAUTH_STATE_COOKIE = "sentrix_oauth_state"
SESSION_TTL = 12 * 60 * 60
OAUTH_STATE_TTL = 10 * 60
ADMINISTRATOR = 1 << 3

AUTOMOD_FIELDS = {
    "antispam", "antilink", "antiinvite", "antimention", "anticaps",
    "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam",
    "antinuke", "escalation",
}

AI_BOOL_FIELDS = {"enabled", "memory_enabled", "logs_enabled"}
AI_INT_FIELDS = {
    "cooldown_seconds": (0, 3600),
    "per_minute_limit": (1, 100),
    "daily_limit": (1, 10000),
    "max_question_length": (50, 10000),
    "memory_minutes": (1, 1440),
}
AI_CHOICE_FIELDS = {
    "default_model": {"luna", "terra", "sol"},
    "reasoning_effort": {"none", "low", "medium", "high", "xhigh", "max"},
}

TEXT_FIELDS = {
    "prefix": (1, 5),
    "welcome_message": (0, 2000),
    "goodbye_message": (0, 1000),
    "level_message": (0, 1000),
}

URL_FIELDS = {"welcome_image_url"}
SUPPORTED_SOCIAL_DOMAINS = (
    "youtube.com", "youtu.be", "tiktok.com", "twitch.tv", "instagram.com",
    "x.com", "twitter.com", "facebook.com", "fb.watch", "dailymotion.com",
    "dai.ly", "vimeo.com", "kick.com",
)

ROLE_FIELDS = {
    "mod_role", "admin_role", "mute_role", "verification_role", "verify_role",
    "autorole", "warn_role", "member_role", "booster_role",
}

CHANNEL_FIELDS = {
    "log_channel", "welcome_channel", "goodbye_channel", "rules_channel",
    "verification_channel", "ticket_log_channel", "level_channel",
    "suggest_channel", "announce_channel", "giveaway_channel",
    "bot_commands_channel", "report_channel", "partner_channel", "stats_channel",
    "afk_channel", "error_channel", "log_messages", "log_members", "log_voice",
    "log_roles", "log_server", "log_automod", "log_moderation",
}

BOOL_FIELDS = {"ticket_transcript_dm", "ticket_rating_enabled"}
INT_FIELDS = {
    "warn_ban_threshold": (1, 20),
    "ticket_delete_delay": (0, 3600),
}


def _client_id(bot) -> str:
    configured = (config.DISCORD_CLIENT_ID or "").strip()
    if configured:
        return configured
    return str(bot.user.id) if bot.user else ""


def _public_url(request: web.Request) -> str:
    configured = (config.DASHBOARD_PUBLIC_URL or "").strip().rstrip("/")
    if configured:
        return configured
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0]
    host = request.headers.get("X-Forwarded-Host", request.host).split(",")[0]
    return f"{scheme}://{host}"


def _oauth_ready(bot) -> bool:
    return bool(_client_id(bot) and config.DISCORD_CLIENT_SECRET)


def _invite_url(bot, guild_id: int | None = None) -> str | None:
    client_id = _client_id(bot)
    if not client_id:
        return None
    params = {
        "client_id": client_id,
        "permissions": "8",
        "integration_type": "0",
        "scope": "bot applications.commands",
    }
    if guild_id:
        params["guild_id"] = str(guild_id)
        params["disable_guild_select"] = "true"
    return f"{DISCORD_AUTHORIZE}?{urlencode(params)}"


def _avatar_url(user: dict) -> str | None:
    avatar = user.get("avatar")
    if not avatar:
        return None
    extension = "gif" if avatar.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.{extension}?size=128"


def _guild_icon_url(guild: dict) -> str | None:
    icon = guild.get("icon")
    if not icon:
        return None
    return f"https://cdn.discordapp.com/icons/{guild['id']}/{icon}.png?size=128"


def _json_error(message: str, status: int) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


def _session(request: web.Request) -> dict | None:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None
    session = request.app["sessions"].get(session_id)
    if not session:
        return None
    if session["expires_at"] <= time.time():
        request.app["sessions"].pop(session_id, None)
        return None
    return session


def _require_session(request: web.Request) -> tuple[dict | None, web.Response | None]:
    session = _session(request)
    if not session:
        return None, _json_error("Connectez-vous avec Discord pour continuer.", 401)
    return session, None


def _require_csrf(request: web.Request, session: dict) -> web.Response | None:
    if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
        return _json_error("La session de sécurité a expiré. Rechargez la page.", 403)
    return None


async def _administrator_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    """Vérifie les permissions actuelles, sans se fier uniquement à la session OAuth."""
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    return member if member.guild_permissions.administrator else None


async def _manageable_guild(request: web.Request, guild_id: int):
    session, error = _require_session(request)
    if error:
        return None, None, error
    guild = request.app["bot"].get_guild(guild_id)
    if guild is None:
        return session, None, _json_error("Serveur introuvable ou accès refusé.", 404)

    user_id = int(session["user"]["id"])
    if await _administrator_member(guild, user_id) is None:
        return session, None, _json_error("Serveur introuvable ou accès refusé.", 404)
    return session, guild, None


async def _guild_metrics(db, guild_id: int) -> dict:
    queries = {
        "warnings": "SELECT COUNT(*) AS n FROM warnings WHERE guild_id = ?",
        "open_tickets": "SELECT COUNT(*) AS n FROM tickets WHERE guild_id = ? AND status = 'ouvert'",
        "profiles": "SELECT COUNT(*) AS n FROM levels WHERE guild_id = ?",
        "economy_accounts": "SELECT COUNT(*) AS n FROM economy WHERE guild_id = ?",
        "commands_24h": "SELECT COUNT(*) AS n FROM command_logs WHERE guild_id = ? AND timestamp >= ?",
    }
    result = {}
    for key, query in queries.items():
        try:
            params = (guild_id, now() - 86400) if key == "commands_24h" else (guild_id,)
            row = await db.fetchone(query, params)
            result[key] = int(row["n"] if row else 0)
        except Exception:
            result[key] = 0
    return result


async def handle_index(request: web.Request):
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def handle_health(request: web.Request):
    bot = request.app["bot"]
    return web.json_response({
        "ok": True,
        "discord_ready": bot.is_ready(),
        "latency_ms": round(bot.latency * 1000) if bot.is_ready() else None,
    })


async def handle_public(request: web.Request):
    bot = request.app["bot"]
    guilds = bot.guilds
    return web.json_response({
        "bot_name": bot.user.name if bot.user else "SentriX",
        "avatar_url": str(bot.user.display_avatar.url) if bot.user else None,
        "online": bot.is_ready(),
        "guilds": len(guilds),
        "members": sum(g.member_count or 0 for g in guilds),
        "latency_ms": round(bot.latency * 1000) if bot.is_ready() else None,
        "uptime_seconds": int(time.time() - START_TIME),
        "invite_url": _invite_url(bot),
        "oauth_ready": _oauth_ready(bot),
    })


async def handle_login(request: web.Request):
    bot = request.app["bot"]
    if not _oauth_ready(bot):
        raise web.HTTPFound("/?auth=missing")

    state = secrets.token_urlsafe(32)
    request.app["oauth_states"][state] = time.time() + OAUTH_STATE_TTL
    redirect_uri = f"{_public_url(request)}/oauth/callback"
    params = {
        "response_type": "code",
        "client_id": _client_id(bot),
        "scope": "identify guilds",
        "state": state,
        "redirect_uri": redirect_uri,
        "prompt": "consent",
    }
    response = web.HTTPFound(f"{DISCORD_AUTHORIZE}?{urlencode(params)}")
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=OAUTH_STATE_TTL,
        httponly=True,
        secure=_public_url(request).startswith("https://"),
        samesite="Lax",
    )
    raise response


async def handle_callback(request: web.Request):
    state = request.query.get("state", "")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
    expires_at = request.app["oauth_states"].pop(state, 0)
    if not state or not secrets.compare_digest(state, cookie_state) or expires_at <= time.time():
        return web.Response(text=OAUTH_ERROR_HTML, content_type="text/html", status=403)
    if request.query.get("error"):
        raise web.HTTPFound("/?auth=denied")

    code = request.query.get("code")
    if not code:
        return web.Response(text=OAUTH_ERROR_HTML, content_type="text/html", status=400)

    bot = request.app["bot"]
    redirect_uri = f"{_public_url(request)}/oauth/callback"
    try:
        async with ClientSession() as client:
            async with client.post(
                f"{DISCORD_API}/oauth2/token",
                data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
                auth=BasicAuth(_client_id(bot), config.DISCORD_CLIENT_SECRET),
            ) as token_response:
                if token_response.status != 200:
                    logger.warning("Échange OAuth Discord refusé (%s).", token_response.status)
                    raise web.HTTPFound("/?auth=failed")
                token_data = await token_response.json()

            headers = {"Authorization": f"Bearer {token_data['access_token']}"}
            async with client.get(f"{DISCORD_API}/users/@me", headers=headers) as user_response:
                user_response.raise_for_status()
                user = await user_response.json()
            async with client.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as guild_response:
                guild_response.raise_for_status()
                oauth_guilds = await guild_response.json()
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Connexion OAuth Discord impossible.")
        raise web.HTTPFound("/?auth=failed")

    manageable = []
    for guild in oauth_guilds:
        permissions = int(guild.get("permissions", "0"))
        if bool(guild.get("owner")) or permissions & ADMINISTRATOR:
            manageable.append({
                "id": str(guild["id"]),
                "name": guild["name"],
                "icon_url": _guild_icon_url(guild),
                "owner": bool(guild.get("owner")),
            })

    session_id = secrets.token_urlsafe(48)
    request.app["sessions"][session_id] = {
        "user": {
            "id": str(user["id"]),
            "username": user.get("global_name") or user.get("username") or "Utilisateur Discord",
            "avatar_url": _avatar_url(user),
        },
        "guilds": manageable,
        "csrf": secrets.token_urlsafe(32),
        "expires_at": time.time() + SESSION_TTL,
    }
    response = web.HTTPFound("/app")
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=SESSION_TTL,
        httponly=True,
        secure=_public_url(request).startswith("https://"),
        samesite="Lax",
    )
    response.del_cookie(OAUTH_STATE_COOKIE)
    raise response


async def handle_logout(request: web.Request):
    session, error = _require_session(request)
    if error:
        return error
    csrf_error = _require_csrf(request, session)
    if csrf_error:
        return csrf_error
    request.app["sessions"].pop(request.cookies.get(SESSION_COOKIE, ""), None)
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE)
    return response


async def handle_me(request: web.Request):
    session, error = _require_session(request)
    if error:
        return error
    return web.json_response({"user": session["user"], "csrf": session["csrf"]})


async def handle_guilds(request: web.Request):
    session, error = _require_session(request)
    if error:
        return error
    bot = request.app["bot"]
    user_id = int(session["user"]["id"])
    guilds = []
    for item in session["guilds"]:
        guild_id = int(item["id"])
        installed_guild = bot.get_guild(guild_id)
        installed = installed_guild is not None
        if installed and await _administrator_member(installed_guild, user_id) is None:
            continue
        guilds.append({
            **item,
            "installed": installed,
            "invite_url": None if installed else _invite_url(bot, guild_id),
        })
    guilds.sort(key=lambda item: (not item["installed"], item["name"].casefold()))
    return web.json_response({"guilds": guilds})


async def handle_guild(request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return _json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await _manageable_guild(request, guild_id)
    if error:
        return error

    db = request.app["bot"].db
    conf = await db.get_guild_config(guild_id)
    automod = await db.get_automod(guild_id)
    await db.execute(
        "INSERT OR IGNORE INTO ai_settings (guild_id, updated_at) VALUES (?, ?)",
        (guild_id, now()),
    )
    ai_settings = await db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,))
    metrics = await _guild_metrics(db, guild_id)
    social_rows = await db.fetchall(
        """
        SELECT id, source_url, platform, discord_channel_id, role_id,
               custom_text, image_url, enabled, created_at, last_checked_at
        FROM social_notifications
        WHERE guild_id = ?
        ORDER BY id DESC
        """,
        (guild_id,),
    )
    social_notifications = [dict(row) for row in social_rows]
    roles = [
        {"id": str(role.id), "name": role.name, "color": str(role.color)}
        for role in sorted(guild.roles, key=lambda role: role.position, reverse=True)
        if not role.is_default() and not role.managed
    ]
    channels = [
        {"id": str(channel.id), "name": channel.name, "type": str(channel.type)}
        for channel in guild.channels
        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel, discord.CategoryChannel))
    ]
    return web.json_response({
        "guild": {
            "id": str(guild.id),
            "name": guild.name,
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "members": guild.member_count or 0,
            "roles_count": len(guild.roles),
            "channels_count": len(guild.channels),
        },
        "settings": dict(conf) if conf else {},
        "automod": dict(automod) if automod else {},
        "ai": dict(ai_settings) if ai_settings else {},
        "social_notifications": social_notifications,
        "roles": roles,
        "channels": channels,
        "metrics": metrics,
    })


def _normalise_optional_id(value) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    return int(value)


def _valid_https_url(value: str) -> bool:
    try:
        parsed = urlparse(str(value).strip())
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and len(str(value)) <= 2000
    )


def _social_platform(value: str) -> str | None:
    if not _valid_https_url(value):
        return None
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    if not any(host == domain or host.endswith(f".{domain}") for domain in SUPPORTED_SOCIAL_DOMAINS):
        return None
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        return "YouTube"
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "TikTok"
    if host == "twitch.tv" or host.endswith(".twitch.tv"):
        return "Twitch"
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram"
    if host in {"x.com", "twitter.com"} or host.endswith((".x.com", ".twitter.com")):
        return "X"
    if host in {"facebook.com", "fb.watch"} or host.endswith(".facebook.com"):
        return "Facebook"
    if host in {"dailymotion.com", "dai.ly"} or host.endswith(".dailymotion.com"):
        return "Dailymotion"
    if host == "vimeo.com" or host.endswith(".vimeo.com"):
        return "Vimeo"
    if host == "kick.com" or host.endswith(".kick.com"):
        return "Kick"
    return None


def _normalise_social_url(value: str) -> str:
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    if (
        (host == "youtube.com" or host.endswith(".youtube.com"))
        and path
        and not any(part in path for part in ("/watch", "/shorts/", "/live/", "/playlist"))
        and not path.endswith(("/videos", "/shorts", "/streams"))
    ):
        path += "/videos"
    return urlunparse((parsed.scheme, parsed.netloc, path or parsed.path, "", parsed.query, ""))


def _validate_settings(guild: discord.Guild, values: dict) -> tuple[dict, str | None]:
    clean = {}
    for field, value in values.items():
        if field in TEXT_FIELDS:
            minimum, maximum = TEXT_FIELDS[field]
            text = str(value or "").strip()
            if not minimum <= len(text) <= maximum:
                return {}, f"Le champ {field} doit contenir entre {minimum} et {maximum} caractères."
            clean[field] = text or None
        elif field in URL_FIELDS:
            text = str(value or "").strip()
            if text and not _valid_https_url(text):
                return {}, f"Le champ {field} doit être une URL HTTPS valide."
            clean[field] = text or None
        elif field == "security_level":
            if value not in {"faible", "moyen", "eleve"}:
                return {}, "Le niveau de sécurité doit être faible, moyen ou élevé."
            clean[field] = value
        elif field == "xp_multiplier":
            try:
                number = float(value)
            except (TypeError, ValueError):
                return {}, "Le multiplicateur XP doit être un nombre."
            if not 0.1 <= number <= 5:
                return {}, "Le multiplicateur XP doit être compris entre 0,1 et 5."
            clean[field] = round(number, 2)
        elif field in INT_FIELDS:
            try:
                number = int(value)
            except (TypeError, ValueError):
                return {}, f"Le champ {field} doit être un nombre entier."
            minimum, maximum = INT_FIELDS[field]
            if not minimum <= number <= maximum:
                return {}, f"Le champ {field} doit être compris entre {minimum} et {maximum}."
            clean[field] = number
        elif field in BOOL_FIELDS:
            if value not in (True, False, 0, 1):
                return {}, f"Le champ {field} doit être activé ou désactivé."
            clean[field] = int(bool(value))
        elif field in ROLE_FIELDS:
            try:
                role_id = _normalise_optional_id(value)
            except (TypeError, ValueError):
                return {}, f"Le rôle choisi pour {field} est invalide."
            if role_id is not None:
                role = guild.get_role(role_id)
                if role is None or role.is_default() or role.managed:
                    return {}, f"Le rôle choisi pour {field} n'existe plus ou ne peut pas être utilisé."
            clean[field] = role_id
        elif field in CHANNEL_FIELDS or field == "ticket_category":
            try:
                channel_id = _normalise_optional_id(value)
            except (TypeError, ValueError):
                return {}, f"Le salon choisi pour {field} est invalide."
            if channel_id is not None:
                channel = guild.get_channel(channel_id)
                if channel is None:
                    return {}, f"Le salon choisi pour {field} n'existe plus."
                if field == "ticket_category" and not isinstance(channel, discord.CategoryChannel):
                    return {}, "La catégorie des tickets doit être une catégorie Discord."
            clean[field] = channel_id
        else:
            return {}, f"Le réglage {field} n'est pas modifiable depuis le dashboard."
    return clean, None


def _validate_ai(values: dict) -> tuple[dict, str | None]:
    clean = {}
    for field, value in values.items():
        if field in AI_BOOL_FIELDS:
            if value not in (True, False, 0, 1):
                return {}, f"Le réglage IA {field} doit être activé ou désactivé."
            clean[field] = int(bool(value))
        elif field in AI_INT_FIELDS:
            try:
                number = int(value)
            except (TypeError, ValueError):
                return {}, f"Le réglage IA {field} doit être un nombre entier."
            minimum, maximum = AI_INT_FIELDS[field]
            if not minimum <= number <= maximum:
                return {}, f"Le réglage IA {field} doit être compris entre {minimum} et {maximum}."
            clean[field] = number
        elif field in AI_CHOICE_FIELDS:
            if value not in AI_CHOICE_FIELDS[field]:
                return {}, f"La valeur choisie pour {field} n'est pas reconnue."
            clean[field] = value
        else:
            return {}, f"Le réglage IA {field} n'est pas modifiable depuis le dashboard."
    return clean, None


async def handle_create_social_notification(request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return _json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await _manageable_guild(request, guild_id)
    if error:
        return error
    csrf_error = _require_csrf(request, session)
    if csrf_error:
        return csrf_error

    rate_key = (request.cookies.get(SESSION_COOKIE), guild_id, "social-create")
    if time.time() - request.app["write_limits"].get(rate_key, 0) < 1.5:
        return _json_error("Attendez un instant avant d'ajouter une autre notification.", 429)
    try:
        payload = await request.json()
    except Exception:
        return _json_error("Le formulaire envoyé est invalide.", 400)

    source_url = str(payload.get("source_url") or "").strip()
    platform = _social_platform(source_url)
    if platform is None:
        return _json_error(
            "Utilisez un lien HTTPS YouTube, TikTok, Twitch, Instagram, X, Facebook, Dailymotion, Vimeo ou Kick.",
            400,
        )
    source_url = _normalise_social_url(source_url)
    try:
        channel_id = int(payload.get("discord_channel_id"))
        role_id = int(payload.get("role_id"))
    except (TypeError, ValueError):
        return _json_error("Choisissez le salon Discord et le rôle à notifier.", 400)

    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return _json_error("Le salon de destination doit être un salon textuel de ce serveur.", 400)
    role = guild.get_role(role_id)
    if role is None or role.is_default() or role.managed:
        return _json_error("Le rôle choisi n'existe plus ou ne peut pas être utilisé.", 400)

    custom_text = str(payload.get("custom_text") or "").strip()
    if len(custom_text) > 1000:
        return _json_error("Le texte personnalisé ne peut pas dépasser 1 000 caractères.", 400)
    image_url = str(payload.get("image_url") or "").strip()
    if image_url and not _valid_https_url(image_url):
        return _json_error("L'image doit utiliser une URL HTTPS valide.", 400)

    db = request.app["bot"].db
    await db.execute(
        """
        INSERT INTO social_notifications (
            guild_id, source_url, platform, discord_channel_id, role_id,
            custom_text, image_url, enabled, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(guild_id, source_url) DO UPDATE SET
            platform = excluded.platform,
            discord_channel_id = excluded.discord_channel_id,
            role_id = excluded.role_id,
            custom_text = excluded.custom_text,
            image_url = excluded.image_url,
            enabled = 1
        """,
        (
            guild_id, source_url, platform, channel_id, role_id,
            custom_text or None, image_url or None, now(),
        ),
    )
    request.app["write_limits"][rate_key] = time.time()
    logger.info(
        "Dashboard : %s (%s) a configuré une notification %s sur %s (%s).",
        session["user"]["username"], session["user"]["id"], platform, guild.name, guild.id,
    )
    return web.json_response({
        "ok": True,
        "message": "Notification ajoutée. La première vérification sert de point de départ, puis les nouveautés seront publiées automatiquement.",
    })


async def handle_delete_social_notification(request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
        notification_id = int(request.match_info["notification_id"])
    except ValueError:
        return _json_error("Identifiant invalide.", 400)
    session, guild, error = await _manageable_guild(request, guild_id)
    if error:
        return error
    csrf_error = _require_csrf(request, session)
    if csrf_error:
        return csrf_error

    db = request.app["bot"].db
    row = await db.fetchone(
        "SELECT id FROM social_notifications WHERE id = ? AND guild_id = ?",
        (notification_id, guild_id),
    )
    if row is None:
        return _json_error("Cette notification n'existe plus.", 404)
    await db.execute(
        "DELETE FROM social_notifications WHERE id = ? AND guild_id = ?",
        (notification_id, guild_id),
    )
    logger.info(
        "Dashboard : %s (%s) a supprimé la notification %s de %s (%s).",
        session["user"]["username"], session["user"]["id"], notification_id, guild.name, guild.id,
    )
    return web.json_response({"ok": True, "message": "Notification supprimée."})


SANCTION_FILTERS = {
    "all": ("ban", "tempban", "unban", "mute", "unmute", "warn", "clearwarnings"),
    "ban": ("ban", "tempban", "unban"),
    "mute": ("mute", "unmute"),
    "warn": ("warn", "clearwarnings"),
}


def _dashboard_user(bot, guild: discord.Guild, user_id: int) -> dict:
    user = guild.get_member(user_id) or bot.get_user(user_id)
    if user is None:
        return {"id": str(user_id), "name": "Utilisateur inconnu", "avatar_url": None}
    avatar = getattr(user, "display_avatar", None)
    return {
        "id": str(user_id),
        "name": getattr(user, "display_name", None) or getattr(user, "name", str(user_id)),
        "avatar_url": str(avatar.url) if avatar else None,
    }


async def handle_sanctions(request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
        limit = min(max(int(request.query.get("limit", "50")), 10), 100)
        offset = max(int(request.query.get("offset", "0")), 0)
    except ValueError:
        return _json_error("Paramètres de recherche invalides.", 400)
    session, guild, error = await _manageable_guild(request, guild_id)
    if error:
        return error

    sanction_filter = request.query.get("filter", "all").strip().lower()
    actions = SANCTION_FILTERS.get(sanction_filter)
    if actions is None:
        return _json_error("Filtre de sanction invalide.", 400)
    search = request.query.get("user_id", "").strip()
    if search and (not search.isdigit() or len(search) > 24):
        return _json_error("L'identifiant Discord recherché est invalide.", 400)

    placeholders = ",".join("?" for _ in actions)
    where = f"guild_id = ? AND action IN ({placeholders})"
    params: list = [guild_id, *actions]
    if search:
        where += " AND user_id = ?"
        params.append(int(search))

    db = request.app["bot"].db
    total_row = await db.fetchone(f"SELECT COUNT(*) AS n FROM sanctions WHERE {where}", tuple(params))
    total = int(total_row["n"] if total_row else 0)
    rows = await db.fetchall(
        f"""
        SELECT id, case_number, user_id, moderator_id, action, reason,
               duration_seconds, created_at
        FROM sanctions
        WHERE {where}
        ORDER BY case_number DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    )

    user_ids = sorted({int(row["user_id"]) for row in rows})
    latest_bans: dict[int, str] = {}
    latest_mutes: dict[int, dict] = {}
    warn_counts: dict[int, int] = {}
    if user_ids:
        user_placeholders = ",".join("?" for _ in user_ids)
        status_rows = await db.fetchall(
            f"""
            SELECT user_id, action, duration_seconds, created_at
            FROM sanctions
            WHERE guild_id = ? AND user_id IN ({user_placeholders})
              AND action IN ('ban', 'tempban', 'unban', 'mute', 'unmute')
            ORDER BY case_number DESC, id DESC
            """,
            (guild_id, *user_ids),
        )
        for row in status_rows:
            user_id = int(row["user_id"])
            action = row["action"]
            if action in {"ban", "tempban", "unban"} and user_id not in latest_bans:
                latest_bans[user_id] = action
            if action in {"mute", "unmute"} and user_id not in latest_mutes:
                latest_mutes[user_id] = dict(row)
        warning_rows = await db.fetchall(
            f"""
            SELECT user_id, COUNT(*) AS n
            FROM warnings
            WHERE guild_id = ? AND user_id IN ({user_placeholders})
            GROUP BY user_id
            """,
            (guild_id, *user_ids),
        )
        warn_counts = {int(row["user_id"]): int(row["n"]) for row in warning_rows}

    current_time = now()
    bot = request.app["bot"]
    sanctions = []
    for row in rows:
        item = dict(row)
        user_id = int(item["user_id"])
        mute_state = latest_mutes.get(user_id)
        muted = False
        if mute_state and mute_state["action"] == "mute":
            duration = mute_state["duration_seconds"]
            muted = duration is None or int(mute_state["created_at"]) + int(duration) > current_time
        item["user"] = _dashboard_user(bot, guild, user_id)
        moderator_id = int(item["moderator_id"] or 0)
        item["moderator"] = _dashboard_user(bot, guild, moderator_id)
        item["current_banned"] = latest_bans.get(user_id) in {"ban", "tempban"}
        item["current_muted"] = muted
        item["warn_count"] = warn_counts.get(user_id, 0)
        sanctions.append(item)

    next_offset = offset + len(sanctions)
    return web.json_response({
        "ok": True,
        "sanctions": sanctions,
        "total": total,
        "next_offset": next_offset if next_offset < total else None,
        "filter": sanction_filter,
    })


async def handle_sanction_action(request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
        user_id = int(request.match_info["user_id"])
    except ValueError:
        return _json_error("Identifiant Discord invalide.", 400)
    action = request.match_info["action"].strip().lower()
    if action not in {"unban", "unmute", "clear-warnings"}:
        return _json_error("Action de modération invalide.", 400)

    session, guild, error = await _manageable_guild(request, guild_id)
    if error:
        return error
    csrf_error = _require_csrf(request, session)
    if csrf_error:
        return csrf_error

    rate_key = (request.cookies.get(SESSION_COOKIE), guild_id, "sanction-action")
    if time.time() - request.app["write_limits"].get(rate_key, 0) < 1.5:
        return _json_error("Attendez un instant avant d'effectuer une autre action.", 429)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    reason = str(payload.get("reason") or "Action effectuée depuis le dashboard SentriX").strip()
    if not reason or len(reason) > 500:
        return _json_error("La raison doit contenir entre 1 et 500 caractères.", 400)

    bot = request.app["bot"]
    db = bot.db
    moderator_id = int(session["user"]["id"])
    audit_reason = f"{session['user']['username']} ({moderator_id}) via dashboard : {reason}"
    bot_member = guild.me
    try:
        if action == "unban":
            if bot_member is None or not bot_member.guild_permissions.ban_members:
                return _json_error("SentriX n'a pas la permission Bannir des membres sur ce serveur.", 403)
            target = discord.Object(id=user_id)
            await guild.fetch_ban(target)
            await guild.unban(target, reason=audit_reason)
            await db.execute(
                "DELETE FROM tempactions WHERE guild_id = ? AND user_id = ? AND action = 'ban'",
                (guild_id, user_id),
            )
            await db.record_sanction(guild_id, user_id, moderator_id, "unban", reason)
            message = f"L'utilisateur {user_id} a été débanni."
        elif action == "unmute":
            if bot_member is None or not bot_member.guild_permissions.moderate_members:
                return _json_error("SentriX n'a pas la permission Exclure temporairement des membres.", 403)
            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    return _json_error("Ce membre n'est plus présent sur le serveur.", 404)
            timed_out_until = getattr(member, "timed_out_until", None)
            if timed_out_until is None or timed_out_until <= discord.utils.utcnow():
                return _json_error("Ce membre n'est pas actuellement mute.", 409)
            if member == guild.owner or member.top_role >= bot_member.top_role:
                return _json_error("Le rôle de SentriX doit être placé au-dessus de celui du membre.", 403)
            await member.timeout(None, reason=audit_reason)
            await db.record_sanction(guild_id, user_id, moderator_id, "unmute", reason)
            message = f"Le mute de l'utilisateur {user_id} a été retiré."
        else:
            count_row = await db.fetchone(
                "SELECT COUNT(*) AS n FROM warnings WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            count = int(count_row["n"] if count_row else 0)
            if count == 0:
                return _json_error("Cet utilisateur n'a aucun avertissement actif.", 409)
            await db.execute(
                "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            await db.record_sanction(
                guild_id, user_id, moderator_id, "clearwarnings",
                f"{reason} — {count} avertissement(s) retiré(s)",
            )
            message = f"{count} avertissement(s) ont été retirés pour l'utilisateur {user_id}."
    except discord.NotFound:
        return _json_error("Cette sanction n'est plus active ou l'utilisateur est introuvable.", 404)
    except discord.Forbidden:
        return _json_error("Discord a refusé l'action : vérifiez les permissions et la hiérarchie de SentriX.", 403)
    except discord.HTTPException:
        logger.exception("Action de sanction impossible depuis le dashboard.")
        return _json_error("Discord n'a pas pu appliquer cette action. Réessayez dans un instant.", 502)

    request.app["write_limits"][rate_key] = time.time()
    logger.info(
        "Dashboard : %s (%s) a effectué %s sur %s dans %s (%s).",
        session["user"]["username"], moderator_id, action, user_id, guild.name, guild.id,
    )
    return web.json_response({"ok": True, "message": message})


async def handle_update_guild(request: web.Request):
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return _json_error("Identifiant de serveur invalide.", 400)
    session, guild, error = await _manageable_guild(request, guild_id)
    if error:
        return error
    csrf_error = _require_csrf(request, session)
    if csrf_error:
        return csrf_error

    rate_key = (request.cookies.get(SESSION_COOKIE), guild_id)
    last_write = request.app["write_limits"].get(rate_key, 0)
    if time.time() - last_write < 1.5:
        return _json_error("Attendez un instant avant d'enregistrer de nouveau.", 429)

    try:
        payload = await request.json()
    except Exception:
        return _json_error("Le formulaire envoyé est invalide.", 400)
    settings = payload.get("settings", {})
    automod = payload.get("automod", {})
    ai_values = payload.get("ai", {})
    if not isinstance(settings, dict) or not isinstance(automod, dict) or not isinstance(ai_values, dict):
        return _json_error("Le formulaire envoyé est invalide.", 400)
    if len(settings) + len(automod) + len(ai_values) > 40:
        return _json_error("Trop de réglages ont été envoyés en même temps.", 400)

    clean_settings, validation_error = _validate_settings(guild, settings)
    if validation_error:
        return _json_error(validation_error, 400)
    clean_automod = {}
    for field, value in automod.items():
        if field not in AUTOMOD_FIELDS:
            return _json_error(f"Le réglage AutoMod {field} n'est pas autorisé.", 400)
        if value not in (True, False, 0, 1):
            return _json_error(f"Le réglage AutoMod {field} doit être activé ou désactivé.", 400)
        clean_automod[field] = int(bool(value))
    clean_ai, validation_error = _validate_ai(ai_values)
    if validation_error:
        return _json_error(validation_error, 400)

    db = request.app["bot"].db
    for field, value in clean_settings.items():
        await db.set_guild_config(guild_id, field, value)
    for field, value in clean_automod.items():
        await db.set_automod(guild_id, field, value)
    if clean_ai:
        await db.execute(
            "INSERT OR IGNORE INTO ai_settings (guild_id, updated_at) VALUES (?, ?)",
            (guild_id, now()),
        )
        for field, value in clean_ai.items():
            await db.execute(
                f"UPDATE ai_settings SET {field} = ?, updated_at = ? WHERE guild_id = ?",
                (value, now(), guild_id),
            )
    request.app["write_limits"][rate_key] = time.time()
    logger.info(
        "Dashboard : %s (%s) a modifié %s réglage(s) du serveur %s (%s).",
        session["user"]["username"], session["user"]["id"],
        len(clean_settings) + len(clean_automod) + len(clean_ai), guild.name, guild.id,
    )
    return web.json_response({"ok": True, "message": "Configuration enregistrée et appliquée immédiatement."})


@web.middleware
async def security_headers(request: web.Request, handler):
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.path == "/app" or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' https://cdn.discordapp.com data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://discord.com"
    )
    return response


def build_app(bot) -> web.Application:
    app = web.Application(middlewares=[security_headers], client_max_size=64 * 1024)
    app["bot"] = bot
    app["sessions"] = {}
    app["oauth_states"] = {}
    app["write_limits"] = {}
    app.router.add_get("/", handle_index)
    app.router.add_get("/app", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/login", handle_login)
    app.router.add_get("/oauth/callback", handle_callback)
    app.router.add_post("/logout", handle_logout)
    app.router.add_get("/api/public", handle_public)
    app.router.add_get("/api/me", handle_me)
    app.router.add_get("/api/guilds", handle_guilds)
    app.router.add_get("/api/guilds/{guild_id}", handle_guild)
    app.router.add_put("/api/guilds/{guild_id}/settings", handle_update_guild)
    app.router.add_post("/api/guilds/{guild_id}/notifications", handle_create_social_notification)
    app.router.add_delete(
        "/api/guilds/{guild_id}/notifications/{notification_id}",
        handle_delete_social_notification,
    )
    app.router.add_get("/api/guilds/{guild_id}/sanctions", handle_sanctions)
    app.router.add_post(
        "/api/guilds/{guild_id}/sanctions/{user_id}/{action}",
        handle_sanction_action,
    )
    return app


async def start_dashboard(bot):
    """Démarre le dashboard sans empêcher le bot de fonctionner en cas d'erreur web."""
    try:
        app = build_app(bot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", config.DASHBOARD_PORT)
        await site.start()
        logger.info("Application dashboard SentriX démarrée sur le port %s.", config.DASHBOARD_PORT)
        if not _oauth_ready(bot):
            logger.warning(
                "Dashboard en lecture seule : ajoutez DISCORD_CLIENT_SECRET dans Railway pour activer la connexion Discord."
            )
    except Exception:
        logger.exception("Échec du démarrage du dashboard web ; le bot reste en ligne.")


OAUTH_ERROR_HTML = """<!doctype html><html lang="fr"><meta charset="utf-8"><title>SentriX</title>
<style>body{background:#090b12;color:#eef1ff;font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0}
main{max-width:520px;padding:36px;background:#111522;border:1px solid #242b42;border-radius:20px}a{color:#9b8cff}</style>
<main><h1>Connexion impossible</h1><p>La demande de connexion Discord a expiré ou n'est pas valide.</p><a href="/">Revenir au dashboard</a></main></html>"""


INDEX_HTML = r"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="theme-color" content="#090b12">
  <title>SentriX — Dashboard</title>
  <style>
    :root{--bg:#090b12;--panel:#111522;--panel2:#171c2c;--line:#262d43;--text:#f2f4ff;--muted:#949db5;--brand:#7c6cff;--brand2:#a897ff;--ok:#44d39a;--bad:#ff667d;--warn:#f2bd5a;--shadow:0 24px 70px #0007}
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 15% -10%,#33266b55,transparent 35%),var(--bg);color:var(--text);font:15px Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh}button,input,select,textarea{font:inherit}a{color:inherit;text-decoration:none}.hidden{display:none!important}
    .top{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 5vw;border-bottom:1px solid #ffffff0d;background:#090b12cc;backdrop-filter:blur(14px);position:sticky;top:0;z-index:20}.brand{display:flex;align-items:center;gap:12px;font-weight:800;font-size:18px}.brand-logo{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(135deg,var(--brand),#4736b4);box-shadow:0 0 30px #7c6cff55}.brand-logo img{width:100%;height:100%;border-radius:12px}.status{display:flex;align-items:center;gap:9px;color:var(--muted);font-size:13px}.status i{width:9px;height:9px;border-radius:50%;background:var(--ok);box-shadow:0 0 14px var(--ok)}
    .btn{border:1px solid var(--line);border-radius:11px;padding:11px 16px;background:var(--panel2);color:var(--text);cursor:pointer;font-weight:700;display:inline-flex;align-items:center;justify-content:center;gap:8px;transition:.18s}.btn:hover{transform:translateY(-1px);border-color:#4d5778}.btn.primary{background:linear-gradient(135deg,var(--brand),#5e4ee5);border-color:transparent;box-shadow:0 12px 28px #5e4ee533}.btn.ghost{background:transparent}.btn.danger{background:#3a1520;border-color:#713044;color:#ff9aaa}.btn:disabled{opacity:.45;cursor:not-allowed;transform:none}
    .hero{max-width:1180px;margin:0 auto;padding:90px 28px 70px;display:grid;grid-template-columns:1.15fr .85fr;gap:60px;align-items:center}.eyebrow{display:inline-flex;padding:7px 11px;border:1px solid #6e5dff55;background:#6e5dff14;border-radius:999px;color:var(--brand2);font-weight:700;font-size:12px;letter-spacing:.04em;text-transform:uppercase}.hero h1{font-size:clamp(42px,7vw,78px);line-height:.98;letter-spacing:-.055em;margin:20px 0 22px;max-width:800px}.hero h1 span{color:var(--brand2)}.hero p{font-size:18px;line-height:1.7;color:var(--muted);max-width:680px;margin:0}.actions{display:flex;gap:12px;margin-top:32px;flex-wrap:wrap}.preview{background:linear-gradient(160deg,#171c2c,#0e111c);border:1px solid var(--line);border-radius:24px;padding:18px;box-shadow:var(--shadow);transform:rotate(1deg)}.preview-head{display:flex;align-items:center;justify-content:space-between;padding:8px 6px 18px}.preview-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.stat{padding:18px;background:#0d101a;border:1px solid #20263a;border-radius:15px}.stat small{color:var(--muted);display:block;margin-bottom:8px}.stat strong{font-size:26px}.features{max-width:1180px;margin:0 auto;padding:20px 28px 90px;display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.feature{padding:26px;background:#101421;border:1px solid var(--line);border-radius:18px}.feature b{display:block;font-size:17px;margin-bottom:9px}.feature p{color:var(--muted);line-height:1.6;margin:0}
    .shell{min-height:100vh;display:grid;grid-template-columns:270px 1fr}.side{border-right:1px solid var(--line);background:#0c0f18;padding:22px;position:sticky;top:0;height:100vh;overflow:auto}.side .brand{margin-bottom:26px}.user{display:flex;gap:11px;align-items:center;padding:12px;background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:22px}.avatar{width:38px;height:38px;border-radius:12px;background:#272d43;object-fit:cover}.user b,.user span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.user span{font-size:12px;color:var(--muted);margin-top:2px}.nav-label{font-size:11px;color:#6f7891;text-transform:uppercase;letter-spacing:.08em;font-weight:800;margin:20px 8px 8px}.nav button{width:100%;border:0;background:transparent;color:var(--muted);padding:11px 12px;text-align:left;border-radius:10px;cursor:pointer;margin:2px 0;font-weight:650}.nav button:hover,.nav button.active{background:#7c6cff18;color:var(--text)}.side-bottom{margin-top:24px;display:grid;gap:8px}.workspace{padding:34px 4vw 70px;min-width:0}.workspace-head{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:28px}.workspace-head h1{margin:0 0 6px;font-size:30px;letter-spacing:-.03em}.workspace-head p{margin:0;color:var(--muted)}.server-select{min-width:260px}.select,input,textarea{width:100%;background:#0c101a;border:1px solid var(--line);color:var(--text);border-radius:11px;padding:11px 12px;outline:none}.select:focus,input:focus,textarea:focus{border-color:var(--brand)}textarea{resize:vertical;min-height:105px}.overview{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}.metric{background:var(--panel);border:1px solid var(--line);padding:18px;border-radius:15px}.metric small{display:block;color:var(--muted);margin-bottom:8px}.metric strong{font-size:24px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;overflow:hidden}.panel-head{padding:20px 22px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;align-items:center}.panel-head h2{margin:0 0 5px;font-size:18px}.panel-head p{margin:0;color:var(--muted);font-size:13px}.fields{padding:22px;display:grid;grid-template-columns:1fr 1fr;gap:18px}.field label{display:block;font-weight:700;margin-bottom:7px}.field .hint{color:var(--muted);font-size:12px;margin-top:7px;line-height:1.45}.field.full{grid-column:1/-1}.field-group-title{grid-column:1/-1;margin:20px 0 -4px;padding-top:20px;border-top:1px solid var(--line);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}.field-group-title:first-child{margin-top:0;padding-top:0;border-top:0}.switch{display:flex;align-items:center;justify-content:space-between;padding:15px;background:#0d111c;border:1px solid #222940;border-radius:13px}.switch div b{display:block}.switch div span{color:var(--muted);font-size:12px}.switch input{appearance:none;width:42px;height:24px;border:0;border-radius:99px;background:#30374c;padding:0;position:relative;cursor:pointer}.switch input:after{content:"";position:absolute;width:18px;height:18px;left:3px;top:3px;background:white;border-radius:50%;transition:.2s}.switch input:checked{background:var(--brand)}.switch input:checked:after{left:21px}.savebar{display:flex;align-items:center;justify-content:flex-end;gap:14px;padding:16px 22px;border-top:1px solid var(--line);background:#0e121d}.save-status{color:var(--muted);font-size:13px}.empty{padding:50px 25px;text-align:center;color:var(--muted)}.toast{position:fixed;right:25px;bottom:25px;max-width:390px;background:#171d2c;border:1px solid #343d59;padding:14px 17px;border-radius:13px;box-shadow:var(--shadow);z-index:50}.toast.bad{border-color:#78354a}.loading{opacity:.55;pointer-events:none}
    .notification-builder{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:18px}.notification-list{grid-column:1/-1;display:grid;gap:10px;margin-top:4px}.notification-list h3{margin:8px 0 2px}.notification-item{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px;background:#0d111c;border:1px solid #222940;border-radius:13px}.notification-item b,.notification-item span{display:block}.notification-item span{color:var(--muted);font-size:12px;margin-top:4px;overflow-wrap:anywhere}.notification-empty{padding:18px;border:1px dashed #343c58;border-radius:13px;color:var(--muted);text-align:center}
    .sanctions-shell{grid-column:1/-1;display:grid;gap:16px}.sanction-toolbar{display:grid;grid-template-columns:minmax(220px,1fr) 190px auto;gap:10px}.sanction-summary{color:var(--muted);font-size:13px}.sanction-list{display:grid;gap:12px}.sanction-card{padding:17px;background:#0d111c;border:1px solid #222940;border-radius:14px}.sanction-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.sanction-user{display:flex;align-items:center;gap:11px;min-width:0}.sanction-user img,.sanction-avatar{width:42px;height:42px;border-radius:12px;background:#222940;object-fit:cover;display:grid;place-items:center;font-weight:800}.sanction-user b,.sanction-user span{display:block}.sanction-user span{color:var(--muted);font-size:12px;margin-top:3px;overflow-wrap:anywhere}.sanction-badge{padding:6px 9px;border-radius:999px;background:#282f46;color:#c8cee0;font-size:11px;font-weight:800;white-space:nowrap}.sanction-badge.ban{background:#451c28;color:#ff9aaa}.sanction-badge.mute{background:#49391a;color:#ffd98c}.sanction-badge.warn{background:#3d321a;color:#f3c96d}.sanction-badge.positive{background:#153b31;color:#7ce2bd}.sanction-body{display:grid;grid-template-columns:1.2fr .8fr;gap:16px;margin-top:14px}.sanction-body small{display:block;color:var(--muted);margin-bottom:5px}.sanction-body p{margin:0;line-height:1.5;overflow-wrap:anywhere}.sanction-state{margin-top:12px;color:var(--muted);font-size:12px}.sanction-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px;padding-top:13px;border-top:1px solid #222940}.sanction-more{justify-self:center}
    @media(max-width:980px){.hero{grid-template-columns:1fr}.preview{transform:none}.features{grid-template-columns:1fr}.shell{grid-template-columns:1fr}.side{position:relative;height:auto;border-right:0;border-bottom:1px solid var(--line)}.nav{display:flex;overflow:auto}.nav button{min-width:max-content}.side-bottom{display:none}.overview{grid-template-columns:1fr 1fr}.workspace-head{align-items:stretch;flex-direction:column}.server-select{min-width:0}.fields{grid-template-columns:1fr}.field.full{grid-column:auto}}
    @media(max-width:560px){.sanction-toolbar{grid-template-columns:1fr}.sanction-head,.sanction-body{grid-template-columns:1fr;display:grid}.top{padding:0 18px}.hero{padding:60px 20px}.features{padding:10px 20px 60px}.hero h1{font-size:45px}.overview{grid-template-columns:1fr}.preview-grid{grid-template-columns:1fr}.workspace{padding:25px 16px}.fields{padding:16px}.panel-head{padding:17px}.status span{display:none}}
  </style>
  <style id="sentrix-motion">
    /* Animations additives : le dashboard reel (apres connexion) n'avait
       jusqu'ici aucune transition, contrairement a la page d'accueil.
       Purement visuel — aucune classe existante n'est retiree ni renommee,
       aucun script n'est modifie. */
    @media(prefers-reduced-motion:no-preference){
      @keyframes sxAppFade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
      @keyframes sxAppRise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
      .shell:not(.hidden) .side nav button{opacity:0;animation:sxAppFade .4s ease both}
      .shell:not(.hidden) .side nav button:nth-child(1){animation-delay:.03s}
      .shell:not(.hidden) .side nav button:nth-child(2){animation-delay:.06s}
      .shell:not(.hidden) .side nav button:nth-child(3){animation-delay:.09s}
      .shell:not(.hidden) .side nav button:nth-child(4){animation-delay:.12s}
      .shell:not(.hidden) .side nav button:nth-child(5){animation-delay:.15s}
      .shell:not(.hidden) .side nav button:nth-child(6){animation-delay:.18s}
      .shell:not(.hidden) .side nav button:nth-child(7){animation-delay:.21s}
      .shell:not(.hidden) .side nav button:nth-child(8){animation-delay:.24s}
      .shell:not(.hidden) .side nav button:nth-child(9){animation-delay:.27s}
      .shell:not(.hidden) .side nav button:nth-child(10){animation-delay:.3s}
      .metric{animation:sxAppRise .45s cubic-bezier(.2,.8,.2,1) both}
      .metric:nth-child(1){animation-delay:.05s}
      .metric:nth-child(2){animation-delay:.1s}
      .metric:nth-child(3){animation-delay:.15s}
      .metric:nth-child(4){animation-delay:.2s}
      .panel{animation:sxAppFade .35s ease both}
      #toast:not(.hidden){animation:sxAppRise .3s cubic-bezier(.2,.8,.2,1) both}
    }
    .btn{transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease,background .16s ease}
    .btn:hover{transform:translateY(-2px);box-shadow:0 10px 26px #0006}
    .btn:active{transform:translateY(0);box-shadow:none}
    .side nav button{transition:background .16s ease,color .16s ease,padding-left .16s ease}
    .side nav button:hover{padding-left:4px}
    .metric,.panel{transition:box-shadow .2s ease,transform .2s ease}
    .metric:hover{transform:translateY(-3px)}
    /* Ecran de chargement : visible des le premier rendu (CSS pur, aucun JS requis),
       qu'on arrive sur /app directement ou via un lien -- sans lui, /app affichait une
       fraction de seconde la page publique "Se connecter avec Discord" avant que le JS
       ne bascule vers le vrai dashboard une fois la session verifiee. */
    #bootLoader{position:fixed;inset:0;z-index:100;display:grid;place-items:center;background:var(--bg);transition:opacity .35s ease;}
    #bootLoader.hide{opacity:0;pointer-events:none}
    #bootLoader .boot-mark{width:52px;height:52px;border-radius:16px;background:linear-gradient(135deg,var(--brand),#4736b4);box-shadow:0 0 40px #7c6cff55;display:grid;place-items:center;font-weight:800;font-size:20px;animation:sxBootPulse 1.4s ease-in-out infinite}
    @keyframes sxBootPulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(.92);opacity:.75}}
    @media(prefers-reduced-motion:reduce){#bootLoader .boot-mark{animation:none}}
  </style>
</head>
<body>
  <div id="bootLoader"><div class="boot-mark">S</div></div>
  <section id="landing">
    <header class="top">
      <div class="brand"><div class="brand-logo" id="publicLogo">S</div><span>SentriX</span></div>
      <div class="status"><i id="publicDot"></i><span id="publicStatus">Connexion au bot…</span></div>
    </header>
    <main class="hero">
      <div>
        <div class="eyebrow">Dashboard officiel</div>
        <h1>Tout votre serveur, <span>au même endroit.</span></h1>
        <p>Invitez SentriX, choisissez votre serveur puis gérez la sécurité, l'IA rapide, l'accueil, les notifications sociales, les tickets, les rôles et les salons depuis une interface claire.</p>
        <div class="actions">
          <a class="btn primary" id="loginButton" href="/login">Se connecter avec Discord</a>
          <a class="btn" id="inviteButton" href="#" target="_blank" rel="noopener">Ajouter SentriX</a>
        </div>
        <p id="authMessage" style="font-size:13px;margin-top:14px"></p>
      </div>
      <div class="preview">
        <div class="preview-head"><b>SentriX en direct</b><span class="status"><i></i><span>Opérationnel</span></span></div>
        <div class="preview-grid">
          <div class="stat"><small>Serveurs</small><strong id="publicGuilds">—</strong></div>
          <div class="stat"><small>Membres protégés</small><strong id="publicMembers">—</strong></div>
          <div class="stat"><small>Latence</small><strong id="publicLatency">—</strong></div>
          <div class="stat"><small>Disponibilité</small><strong id="publicUptime">—</strong></div>
        </div>
      </div>
    </main>
    <section class="features">
      <article class="feature"><b>Sécurité centralisée</b><p>Activez les protections anti-spam, anti-liens, anti-raid, anti-arnaque et anti-nuke sans chercher une commande.</p></article>
      <article class="feature"><b>Configuration immédiate</b><p>Chaque modification est validée, enregistrée dans la base du serveur et appliquée immédiatement par SentriX.</p></article>
      <article class="feature"><b>Accès protégé</b><p>Seuls les membres avec la permission Administrateur peuvent voir et modifier le serveur concerné. Les autres serveurs restent invisibles.</p></article>
    </section>
  </section>

  <section id="dashboard" class="shell hidden">
    <aside class="side">
      <div class="brand"><div class="brand-logo" id="appLogo">S</div><span>SentriX</span></div>
      <div class="user"><div class="brand-logo avatar" id="userAvatar">U</div><div style="min-width:0"><b id="userName">Utilisateur</b><span>Connecté avec Discord</span></div></div>
      <div class="nav-label">Configuration</div>
      <nav class="nav" id="navigation">
        <button data-tab="general" class="active">Général</button>
        <button data-tab="security">Sécurité</button>
        <button data-tab="sanctions">Sanctions</button>
        <button data-tab="logs">Logs</button>
        <button data-tab="welcome">Accueil</button>
        <button data-tab="levels">Niveaux</button>
        <button data-tab="tickets">Tickets</button>
        <button data-tab="ai">Intelligence artificielle</button>
        <button data-tab="notifications">Notifications</button>
        <button data-tab="roles">Rôles et salons</button>
      </nav>
      <div class="side-bottom">
        <a class="btn primary" id="appInvite" target="_blank" rel="noopener">Ajouter SentriX</a>
        <button class="btn ghost" id="logoutButton">Se déconnecter</button>
      </div>
    </aside>
    <main class="workspace">
      <div class="workspace-head">
        <div><h1 id="pageTitle">Dashboard</h1><p id="pageSubtitle">Choisissez un serveur que vous gérez.</p></div>
        <select id="serverSelect" class="select server-select"><option value="">Chargement des serveurs…</option></select>
      </div>
      <div id="serverContent" class="hidden">
        <div class="overview">
          <div class="metric"><small>Membres</small><strong id="metricMembers">—</strong></div>
          <div class="metric"><small>Commandes sur 24 h</small><strong id="metricCommands">—</strong></div>
          <div class="metric"><small>Tickets ouverts</small><strong id="metricTickets">—</strong></div>
          <div class="metric"><small>Avertissements</small><strong id="metricWarnings">—</strong></div>
        </div>
        <section class="panel">
          <header class="panel-head"><div><h2 id="tabTitle">Configuration générale</h2><p id="tabDescription">Réglages essentiels du serveur.</p></div></header>
          <form id="settingsForm"><div class="fields" id="fields"></div><div class="savebar" id="saveBar"><span class="save-status" id="saveStatus">Aucune modification</span><button class="btn primary" id="saveButton" type="submit">Enregistrer</button></div></form>
        </section>
      </div>
      <div id="emptyState" class="panel empty">Sélectionnez un serveur pour commencer. Les serveurs sans SentriX proposent directement le bouton d'invitation.</div>
    </main>
  </section>

  <div id="toast" class="toast hidden"></div>
  <script>
    const state={publicData:null,user:null,csrf:null,guilds:[],guildData:null,guildId:null,tab:"general",dirty:false,sanctions:[],sanctionNext:null,sanctionLoading:false};
    const tabs={
      general:{title:"Configuration générale",description:"Préfixe, niveau de sécurité et sanctions automatiques.",fields:[
        {key:"prefix",label:"Préfixe des commandes",type:"text",hint:"Entre 1 et 5 caractères. Le préfixe par défaut est +."},
        {key:"security_level",label:"Niveau de sécurité",type:"choice",options:[["faible","Faible"],["moyen","Moyen"],["eleve","Élevé"]]},
        {key:"warn_ban_threshold",label:"Bannissement après avertissements",type:"number",min:1,max:20,hint:"Nombre d'avertissements avant la sanction automatique."}
      ]},
      security:{title:"Sécurité et AutoMod",description:"Filtres appliqués automatiquement aux nouveaux messages et événements.",automod:true,fields:[
        ["antispam","Anti-spam","Limite les messages envoyés trop rapidement.","Messages et contenu"],["antilink","Bloquer les liens","Interdit les liens web non autorisés.","Messages et contenu"],["antiinvite","Bloquer les invitations","Interdit les invitations Discord.","Messages et contenu"],["antimention","Anti-mentions","Bloque les mentions massives.","Messages et contenu"],["anticaps","Anti-majuscules","Limite les messages presque entièrement en majuscules.","Messages et contenu"],["antiemoji","Anti-spam emojis","Limite les messages remplis d'emojis.","Messages et contenu"],
        ["antiraid","Anti-raid","Réagit aux arrivées massives de comptes.","Arrivées et comptes"],["antibot","Anti-bot","Contrôle l'arrivée de nouveaux bots.","Arrivées et comptes"],["antiaccount","Comptes récents","Surveille les comptes trop récents.","Arrivées et comptes"],
        ["antiscam","Anti-arnaque","Détecte les liens et messages suspects.","Protection avancée"],["antinuke","Anti-nuke","Protège les rôles, salons et bannissements massifs.","Protection avancée"],["escalation","Sanctions progressives","Augmente la sanction lors des récidives.","Protection avancée"]
      ].map(x=>({key:x[0],label:x[1],hint:x[2],type:"switch",group:x[3]}))},
      sanctions:{title:"Sanctions",description:"Historique des bannissements, mutes et avertissements appliqués par SentriX sur ce serveur.",sanctions:true,fields:[]},
      logs:{title:"Système de logs",description:"Choisissez un salon différent pour chaque type d'événement.",fields:[
        ["log_messages","Messages","Par catégorie"],["log_members","Membres","Par catégorie"],["log_voice","Salons vocaux","Par catégorie"],["log_roles","Rôles","Par catégorie"],["log_server","Serveur","Par catégorie"],["log_automod","AutoMod","Par catégorie"],["log_moderation","Modération","Par catégorie"],
        ["log_channel","Salon de logs général","Repli"]
      ].map(x=>({key:x[0],label:x[1],type:"channel",group:x[2]}))},
      welcome:{title:"Accueil des membres",description:"Messages d'arrivée, de départ et rôle automatique.",fields:[
        {key:"welcome_channel",label:"Salon de bienvenue",type:"channel",group:"Arrivée"},{key:"welcome_message",label:"Message de bienvenue",type:"textarea",hint:"Variables : {member}, {username}, {server} et {member_count}.",group:"Arrivée"},{key:"welcome_image_url",label:"Image de bienvenue (facultative)",type:"url",hint:"URL HTTPS directe vers une image ou un GIF.",group:"Arrivée"},{key:"autorole",label:"Rôle automatique",type:"role",group:"Arrivée"},
        {key:"goodbye_channel",label:"Salon de départ",type:"channel",group:"Départ"},{key:"goodbye_message",label:"Message de départ",type:"textarea",hint:"Variables disponibles : {member} et {server}.",group:"Départ"}
      ]},
      levels:{title:"Niveaux et expérience",description:"Configurez la progression et les annonces de niveau.",fields:[
        {key:"xp_multiplier",label:"Multiplicateur d'XP",type:"number",min:.1,max:5,step:.1},{key:"level_channel",label:"Salon des niveaux",type:"channel"},{key:"level_message",label:"Message de passage de niveau",type:"textarea",hint:"Le membre est mentionné automatiquement lors du passage de niveau."}
      ]},
      tickets:{title:"Tickets de support",description:"Réglages généraux appliqués aux tickets configurés.",fields:[
        {key:"ticket_category",label:"Catégorie des tickets",type:"category"},{key:"ticket_log_channel",label:"Salon des logs tickets",type:"channel"},{key:"ticket_delete_delay",label:"Délai avant suppression (secondes)",type:"number",min:0,max:3600},{key:"ticket_transcript_dm",label:"Envoyer le transcript en message privé",type:"switch",hint:"Envoie une copie au membre lors de la fermeture."},{key:"ticket_rating_enabled",label:"Activer l'évaluation",type:"switch",hint:"Propose au membre de noter le support."}
      ]},
      ai:{title:"Intelligence artificielle",description:"Modèle, limites, mémoire et journalisation des réponses de SentriX.",ai:true,fields:[
        {key:"enabled",label:"Activer l'IA",type:"switch",hint:"Autorise les membres à utiliser les fonctions IA.",group:"Général"},
        {key:"default_model",label:"Modèle par défaut",type:"choice",hint:"Luna répond presque instantanément aux demandes simples. Terra et Sol sont réservés aux tâches plus complexes.",options:[["luna","Luna — ultra-rapide"],["terra","Terra — rapide et équilibré"],["sol","Sol — raisonnement avancé"]],group:"Général"},
        {key:"reasoning_effort",label:"Niveau de raisonnement",type:"choice",options:[["none","Aucun"],["low","Faible"],["medium","Moyen"],["high","Élevé"],["xhigh","Très élevé"],["max","Maximum"]],group:"Général"},
        {key:"cooldown_seconds",label:"Cooldown par membre (secondes)",type:"number",min:0,max:3600,group:"Limites"},
        {key:"per_minute_limit",label:"Limite par minute",type:"number",min:1,max:100,group:"Limites"},
        {key:"daily_limit",label:"Limite quotidienne par membre",type:"number",min:1,max:10000,group:"Limites"},
        {key:"max_question_length",label:"Longueur maximale d'une question",type:"number",min:50,max:10000,group:"Limites"},
        {key:"memory_enabled",label:"Mémoire de conversation",type:"switch",hint:"Conserve temporairement le contexte séparément pour chaque membre et salon.",group:"Mémoire et journalisation"},
        {key:"memory_minutes",label:"Durée de la mémoire (minutes)",type:"number",min:1,max:1440,group:"Mémoire et journalisation"},
        {key:"logs_enabled",label:"Journaliser l'utilisation",type:"switch",hint:"Enregistre uniquement les compteurs d'utilisation, pas les conversations.",group:"Mémoire et journalisation"}
      ]},
      notifications:{title:"Notifications sociales",description:"Publiez automatiquement les nouveautés de vos créateurs préférés dans Discord.",notifications:true,fields:[]},
      roles:{title:"Rôles et salons",description:"Reliez les fonctions du bot aux éléments déjà présents sur le serveur.",fields:[
        ["mod_role","Rôle modérateur","role","Rôles de modération"],["admin_role","Rôle administrateur","role","Rôles de modération"],["mute_role","Rôle muet","role","Rôles de modération"],["warn_role","Rôle d'avertissement","role","Rôles de modération"],
        ["member_role","Rôle membre","role","Rôles membres"],["booster_role","Rôle booster","role","Rôles membres"],["verification_role","Rôle de vérification","role","Rôles membres"],
        ["rules_channel","Salon du règlement","channel","Salons"],["verification_channel","Salon de vérification","channel","Salons"],["bot_commands_channel","Salon des commandes","channel","Salons"],["suggest_channel","Salon des suggestions","channel","Salons"],["announce_channel","Salon des annonces","channel","Salons"],["giveaway_channel","Salon des giveaways","channel","Salons"],["report_channel","Salon des signalements","channel","Salons"],["error_channel","Salon des erreurs","channel","Salons"]
      ].map(x=>({key:x[0],label:x[1],type:x[2],group:x[3]}))}
    };
    const $=id=>document.getElementById(id); const esc=v=>String(v??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
    const number=v=>Number(v||0).toLocaleString("fr-FR");
    function duration(sec){const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60);return d?`${d} j ${h} h`:h?`${h} h ${m} min`:`${m} min`;}
    function toast(message,bad=false){const el=$("toast");el.textContent=message;el.className=`toast${bad?" bad":""}`;clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.add("hidden"),4200);}
    async function json(url,options={}){const res=await fetch(url,options);let data={};try{data=await res.json()}catch{}if(!res.ok)throw new Error(data.error||"Une erreur est survenue.");return data;}
    async function loadPublic(){state.publicData=await json("/api/public");const d=state.publicData;$("publicGuilds").textContent=number(d.guilds);$("publicMembers").textContent=number(d.members);$("publicLatency").textContent=d.latency_ms===null?"—":`${d.latency_ms} ms`;$("publicUptime").textContent=duration(d.uptime_seconds);$("publicStatus").textContent=d.online?"SentriX est opérationnel":"Connexion Discord en cours";$("publicDot").style.background=d.online?"var(--ok)":"var(--warn)";for(const id of ["inviteButton","appInvite"]){$(id).href=d.invite_url||"#";}if(d.avatar_url){for(const id of ["publicLogo","appLogo"]){$(id).innerHTML=`<img src="${esc(d.avatar_url)}" alt="">`;}}if(!d.oauth_ready){$("loginButton").classList.add("hidden");$("authMessage").textContent="La connexion Discord sera disponible après l'ajout du secret OAuth dans Railway.";}const auth=new URLSearchParams(location.search).get("auth");if(auth)$("authMessage").textContent=auth==="missing"?"La connexion Discord n'est pas encore configurée.":"La connexion Discord a été annulée ou a échoué.";}
    async function loadSession(){try{const me=await json("/api/me");state.user=me.user;state.csrf=me.csrf;$("landing").classList.add("hidden");$("dashboard").classList.remove("hidden");$("userName").textContent=me.user.username;if(me.user.avatar_url)$("userAvatar").innerHTML=`<img class="avatar" src="${esc(me.user.avatar_url)}" alt="">`;await loadGuilds();}catch{if(location.pathname==="/app")history.replaceState({},"","/");}}
    async function loadGuilds(){const data=await json("/api/guilds");state.guilds=data.guilds;const select=$("serverSelect");select.innerHTML='<option value="">Choisissez un serveur</option>'+data.guilds.map(g=>`<option value="${g.installed?esc(g.id):"invite:"+esc(g.id)}">${esc(g.name)}${g.installed?"":" — ajouter SentriX"}</option>`).join("");const first=data.guilds.find(g=>g.installed);if(first){select.value=first.id;await selectGuild(first.id);}}
    async function selectGuild(value){if(!value){state.guildId=null;$("serverContent").classList.add("hidden");$("emptyState").classList.remove("hidden");return;}if(String(value).startsWith("invite:")){const id=String(value).slice(7),g=state.guilds.find(x=>x.id===id);if(g?.invite_url)window.open(g.invite_url,"_blank","noopener");$("serverSelect").value=state.guildId||"";return;}state.guildId=value;$("serverContent").classList.add("loading");try{state.guildData=await json(`/api/guilds/${value}`);const d=state.guildData;$("pageTitle").textContent=d.guild.name;$("pageSubtitle").textContent=`${number(d.guild.members)} membres · ${d.guild.channels_count} salons · ${d.guild.roles_count} rôles`;$("metricMembers").textContent=number(d.guild.members);$("metricCommands").textContent=number(d.metrics.commands_24h);$("metricTickets").textContent=number(d.metrics.open_tickets);$("metricWarnings").textContent=number(d.metrics.warnings);$("emptyState").classList.add("hidden");$("serverContent").classList.remove("hidden");renderTab();}catch(e){toast(e.message,true);}finally{$("serverContent").classList.remove("loading");}}
    function optionList(type,current){const list=type==="role"?state.guildData.roles:state.guildData.channels.filter(c=>type!=="category"||c.type==="category");return '<option value="">Non configuré</option>'+list.map(item=>`<option value="${esc(item.id)}" ${String(current||"")===String(item.id)?"selected":""}>${esc(item.name)}${type!=="role"?` — ${esc(item.type)}`:""}</option>`).join("");}
    function fieldHTML(field){const source=state.tab==="security"?state.guildData.automod:state.tab==="ai"?state.guildData.ai:state.guildData.settings;const value=source[field.key];const hint=field.hint?`<div class="hint">${esc(field.hint)}</div>`:"";if(field.type==="switch")return `<label class="switch full"><div><b>${esc(field.label)}</b><span>${esc(field.hint||"Activation immédiate sur ce serveur.")}</span></div><input data-key="${esc(field.key)}" type="checkbox" ${Number(value)?"checked":""}></label>`;let control="";if(field.type==="choice")control=`<select class="select" data-key="${esc(field.key)}">${field.options.map(o=>`<option value="${esc(o[0])}" ${value===o[0]?"selected":""}>${esc(o[1])}</option>`).join("")}</select>`;else if(["role","channel","category"].includes(field.type))control=`<select class="select" data-key="${esc(field.key)}">${optionList(field.type,value)}</select>`;else if(field.type==="textarea")control=`<textarea data-key="${esc(field.key)}">${esc(value||"")}</textarea>`;else control=`<input data-key="${esc(field.key)}" type="${field.type}" value="${esc(value??"")}" ${field.min!==undefined?`min="${field.min}"`:""} ${field.max!==undefined?`max="${field.max}"`:""} ${field.step!==undefined?`step="${field.step}"`:""}>`;return `<div class="field ${field.type==="textarea"?"full":""}"><label>${esc(field.label)}</label>${control}${hint}</div>`;}
    function sanctionLabel(action){return ({ban:"Bannissement",tempban:"Ban temporaire",unban:"Débannissement",mute:"Mute",unmute:"Retrait du mute",warn:"Avertissement",clearwarnings:"Warns effacés"})[action]||action;}
    function sanctionClass(action){if(["ban","tempban"].includes(action))return"ban";if(action==="mute")return"mute";if(action==="warn")return"warn";if(["unban","unmute","clearwarnings"].includes(action))return"positive";return"";}
    function renderSanctions(){state.sanctions=[];state.sanctionNext=null;$("fields").innerHTML=`<div class="sanctions-shell"><div class="sanction-toolbar"><input id="sanctionSearch" type="text" inputmode="numeric" placeholder="Rechercher avec l'ID Discord"><select class="select" id="sanctionFilter"><option value="all">Toutes les sanctions</option><option value="ban">Bannissements</option><option value="mute">Mutes</option><option value="warn">Avertissements</option></select><button class="btn primary" id="sanctionSearchButton" type="button">Rechercher</button></div><div class="sanction-summary" id="sanctionSummary">Chargement de l'historique…</div><div class="sanction-list" id="sanctionList"><div class="notification-empty">Chargement…</div></div><button class="btn sanction-more hidden" id="sanctionMore" type="button">Afficher la suite</button></div>`;$("sanctionSearchButton").addEventListener("click",()=>loadSanctions(true));$("sanctionFilter").addEventListener("change",()=>loadSanctions(true));$("sanctionMore").addEventListener("click",()=>loadSanctions(false));loadSanctions(true);}
    function sanctionCard(item,showActions){const user=item.user||{id:item.user_id,name:"Utilisateur inconnu"};const moderator=item.moderator||{id:item.moderator_id,name:"Modérateur inconnu"};const avatar=user.avatar_url?`<img src="${esc(user.avatar_url)}" alt="">`:`<div class="sanction-avatar">${esc(String(user.name||"?").slice(0,1).toUpperCase())}</div>`;const date=new Date(Number(item.created_at)*1000).toLocaleString("fr-FR");const details=item.duration_seconds?`${date} · Durée : ${duration(item.duration_seconds)}`:date;const states=[];if(item.current_banned)states.push("BANNI");if(item.current_muted)states.push("MUTE");if(Number(item.warn_count))states.push(`${number(item.warn_count)} WARN(S)`);let buttons="";if(showActions&&item.current_banned)buttons+=`<button class="btn primary" type="button" data-sanction-action="unban" data-user-id="${esc(user.id)}">Débannir</button>`;if(showActions&&item.current_muted)buttons+=`<button class="btn primary" type="button" data-sanction-action="unmute" data-user-id="${esc(user.id)}">Retirer le mute</button>`;if(showActions&&Number(item.warn_count))buttons+=`<button class="btn danger" type="button" data-sanction-action="clear-warnings" data-user-id="${esc(user.id)}">Effacer les warns</button>`;return `<article class="sanction-card"><div class="sanction-head"><div class="sanction-user">${avatar}<div><b>${esc(user.name)}</b><span>ID membre : ${esc(user.id)} · Dossier #${esc(item.case_number)}</span></div></div><span class="sanction-badge ${sanctionClass(item.action)}">${esc(sanctionLabel(item.action))}</span></div><div class="sanction-body"><div><small>Raison</small><p>${esc(item.reason||"Aucune raison fournie")}</p></div><div><small>Modérateur</small><p>${esc(moderator.name)} · ID ${esc(moderator.id)}<br>${esc(details)}</p></div></div><div class="sanction-state">État actuel : ${states.length?esc(states.join(" · ")):"AUCUNE SANCTION ACTIVE"}</div>${buttons?`<div class="sanction-actions">${buttons}</div>`:""}</article>`;}
    function renderSanctionRows(total){const list=$("sanctionList");if(!list)return;if(!state.sanctions.length){list.innerHTML='<div class="notification-empty">Aucune sanction trouvée pour cette recherche.</div>';}else{const actionable=new Set();list.innerHTML=state.sanctions.map(item=>{const id=String(item.user?.id||item.user_id),first=!actionable.has(id);actionable.add(id);return sanctionCard(item,first);}).join("");}const shown=state.sanctions.length;$("sanctionSummary").textContent=`${number(total)} dossier(s) trouvé(s) · ${number(shown)} affiché(s)`;$("sanctionMore").classList.toggle("hidden",state.sanctionNext===null);list.querySelectorAll("[data-sanction-action]").forEach(button=>button.addEventListener("click",()=>sanctionAction(button.dataset.userId,button.dataset.sanctionAction)));}
    async function loadSanctions(reset=true){if(!state.guildId||state.tab!=="sanctions"||state.sanctionLoading)return;const guildId=state.guildId,search=$("sanctionSearch")?.value.trim()||"",filter=$("sanctionFilter")?.value||"all";if(reset){state.sanctions=[];state.sanctionNext=0;$("sanctionList").innerHTML='<div class="notification-empty">Chargement…</div>';}if(state.sanctionNext===null)return;state.sanctionLoading=true;try{const params=new URLSearchParams({limit:"50",offset:String(state.sanctionNext||0),filter});if(search)params.set("user_id",search);const data=await json(`/api/guilds/${guildId}/sanctions?${params}`);if(state.guildId!==guildId||state.tab!=="sanctions")return;state.sanctions=reset?data.sanctions:state.sanctions.concat(data.sanctions);state.sanctionNext=data.next_offset;renderSanctionRows(data.total);}catch(e){toast(e.message,true);if($("sanctionList"))$("sanctionList").innerHTML=`<div class="notification-empty">${esc(e.message)}</div>`;}finally{state.sanctionLoading=false;}}
    async function sanctionAction(userId,action){const labels={unban:"débannir cet utilisateur",unmute:"retirer le mute de ce membre","clear-warnings":"effacer tous les avertissements actifs de ce membre"};if(!confirm(`Confirmer : ${labels[action]||"effectuer cette action"} ?`))return;try{const result=await json(`/api/guilds/${state.guildId}/sanctions/${userId}/${action}`,{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:"{}"});toast(result.message);await loadSanctions(true);}catch(e){toast(e.message,true);}}
    function renderNotifications(){const rows=state.guildData.social_notifications||[];const textChannels=state.guildData.channels.filter(c=>["text","news"].includes(c.type));const channelOptions='<option value="">Choisissez un salon</option>'+textChannels.map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("");const roleOptions='<option value="">Choisissez un rôle</option>'+state.guildData.roles.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("");const list=rows.length?rows.map(n=>`<div class="notification-item"><div><b>${esc(n.platform)} · ${esc(state.guildData.roles.find(r=>String(r.id)===String(n.role_id))?.name||"Rôle supprimé")}</b><span>${esc(n.source_url)} · #${esc(state.guildData.channels.find(c=>String(c.id)===String(n.discord_channel_id))?.name||"salon supprimé")}</span></div><button class="btn danger" type="button" data-delete-notification="${esc(n.id)}">Supprimer</button></div>`).join(""):'<div class="notification-empty">Aucune notification configurée. Ajoutez votre première chaîne ci-dessus.</div>';$("fields").innerHTML=`<div class="notification-builder"><div class="field full"><label>Lien de la chaîne ou du profil</label><input data-key="source_url" type="url" placeholder="https://youtube.com/@votrechaine"><div class="hint">YouTube, TikTok, Twitch, Instagram, X, Facebook, Dailymotion, Vimeo et Kick.</div></div><div class="field"><label>Salon de publication</label><select class="select" data-key="discord_channel_id">${channelOptions}</select></div><div class="field"><label>Rôle à notifier</label><select class="select" data-key="role_id">${roleOptions}</select></div><div class="field full"><label>Texte personnalisé (facultatif)</label><textarea data-key="custom_text" placeholder="Une nouvelle publication vient de sortir !"></textarea></div><div class="field full"><label>Image ou GIF (facultatif)</label><input data-key="image_url" type="url" placeholder="https://exemple.com/image.png"><div class="hint">Utilisez une URL HTTPS directe. Sans image, SentriX utilise la miniature de la publication.</div></div></div><div class="notification-list"><h3>Notifications actives</h3>${list}</div>`;$("fields").querySelectorAll("[data-delete-notification]").forEach(button=>button.addEventListener("click",()=>removeNotification(button.dataset.deleteNotification)));}
    function fieldsHTML(fields){let lastGroup,out="";for(const field of fields){if(field.group&&field.group!==lastGroup){out+=`<h3 class="field-group-title">${esc(field.group)}</h3>`;lastGroup=field.group;}out+=fieldHTML(field);}return out;}
    function renderTab(){if(!state.guildData)return;const tab=tabs[state.tab];$("tabTitle").textContent=tab.title;$("tabDescription").textContent=tab.description;if(tab.sanctions)renderSanctions();else if(tab.notifications)renderNotifications();else $("fields").innerHTML=fieldsHTML(tab.fields);$("saveBar").classList.toggle("hidden",Boolean(tab.sanctions));$("saveButton").textContent=tab.notifications?"Ajouter la notification":"Enregistrer";$("saveStatus").textContent=tab.notifications?"Surveillance toutes les 5 minutes":"Aucune modification";state.dirty=false;$("fields").querySelectorAll("input,select,textarea").forEach(el=>el.addEventListener("input",()=>{if(tab.sanctions)return;state.dirty=true;$("saveStatus").textContent="Modifications non enregistrées";}));}
    async function save(event){event.preventDefault();if(!state.guildId||!state.guildData)return;const tab=tabs[state.tab];if(tab.sanctions){await loadSanctions(true);return;}const values={};$("fields").querySelectorAll("[data-key]").forEach(el=>{let value=el.type==="checkbox"?el.checked:el.value;if(el.type==="number"&&value!=="")value=Number(value);values[el.dataset.key]=value;});const endpoint=tab.notifications?`/api/guilds/${state.guildId}/notifications`:`/api/guilds/${state.guildId}/settings`;const body=tab.notifications?values:tab.automod?{automod:values}:tab.ai?{ai:values}:{settings:values};$("settingsForm").classList.add("loading");try{const result=await json(endpoint,{method:tab.notifications?"POST":"PUT",headers:{"Content-Type":"application/json","X-CSRF-Token":state.csrf},body:JSON.stringify(body)});toast(result.message);state.dirty=false;$("saveStatus").textContent="Configuration enregistrée";await selectGuild(state.guildId);}catch(e){toast(e.message,true);$("saveStatus").textContent="Enregistrement impossible";}finally{$("settingsForm").classList.remove("loading");}}
    async function removeNotification(id){if(!state.guildId||!id)return;if(!confirm("Supprimer cette notification automatique ?"))return;try{const result=await json(`/api/guilds/${state.guildId}/notifications/${id}`,{method:"DELETE",headers:{"X-CSRF-Token":state.csrf}});toast(result.message);await selectGuild(state.guildId);}catch(e){toast(e.message,true);}}
    $("serverSelect").addEventListener("change",e=>selectGuild(e.target.value));$("settingsForm").addEventListener("submit",save);$("navigation").addEventListener("click",e=>{const button=e.target.closest("button[data-tab]");if(!button)return;state.tab=button.dataset.tab;$("navigation").querySelectorAll("button").forEach(x=>x.classList.toggle("active",x===button));renderTab();});$("logoutButton").addEventListener("click",async()=>{try{await json("/logout",{method:"POST",headers:{"X-CSRF-Token":state.csrf}});}finally{location.href="/";}});window.addEventListener("beforeunload",e=>{if(state.dirty){e.preventDefault();e.returnValue="";}});
    (function reportAuthFailure(){
      // handle_login redirige ici avec ?auth=missing quand DISCORD_CLIENT_SECRET
      // n'est pas configure sur Railway : #authMessage existait dans le HTML mais
      // rien ne le remplissait jamais, donc le clic sur "Se connecter avec
      // Discord" ramenait silencieusement a la meme page, sans aucune
      // explication — exactement ce qui ressemblait a "le dashboard ne s'ouvre
      // pas".
      const params=new URLSearchParams(location.search);
      if(params.get("auth")==="missing"){
        const el=$("authMessage");
        if(el)el.textContent="Connexion Discord indisponible pour le moment. Réessayez dans quelques instants ou contactez le support.";
        history.replaceState(null,"",location.pathname);
      }
    })();
    Promise.all([loadPublic(),loadSession()]).catch(e=>toast(e.message,true)).finally(()=>{const loader=document.getElementById("bootLoader");if(loader){loader.classList.add("hide");setTimeout(()=>loader.remove(),400);}});
  </script>
</body>
</html>"""


# Keep the API and the original dashboard logic in this module while the V3
# helper installs the real page router and the dedicated module screens.
from web.dashboard_pages_v3 import apply_dashboard_pages

INDEX_HTML = apply_dashboard_pages(INDEX_HTML)
