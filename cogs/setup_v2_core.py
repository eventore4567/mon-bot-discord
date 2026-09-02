"""Runtime V2 SentriX: permissions +/slash, modules, whitelist, logs et économie."""
from __future__ import annotations

import asyncio
import functools
import io
import logging
import re
import time
from types import MethodType
from typing import Any

import discord
from discord.ext import commands

from utils import checks, embeds, log_service
from utils import sentrix_panels as panels
from . import permission_guard

logger = logging.getLogger("bot.setup-v2-core")

MODULES = (
    "moderation", "security", "logs", "tickets", "welcome", "roles",
    "levels", "economy", "notifications", "ai",
)

MODERATION_COMMANDS = frozenset({
    "ban", "tempban", "unban", "kick", "mute", "unmute", "warn", "unwarn",
    "warnings", "clearwarnings", "case", "modhistory", "quarantine", "unquarantine",
    "clear", "slowmode", "lock", "unlock", "hide", "show", "nickname", "nick",
    "resetnick", "move", "disconnect", "say",
})
ECONOMY_COMMANDS = frozenset({
    "balance", "economy", "daily", "weekly", "work", "rob", "pay",
    "economyleaderboard", "leaderboard-money", "shop", "buy", "buyrole", "inventory",
    "sell", "gamble", "deposit", "withdraw", "banque", "slots", "blackjack",
    "coinflip", "dice", "luckyroll", "highlow",
})
LEVEL_COMMANDS = frozenset({"level", "rank", "leaderboard-levels", "voice-time", "stats", "me"})
AI_COMMANDS = frozenset({
    "sentrix", "ask", "chat", "chat-reset", "summarize", "image-prompt", "image",
    "explain", "rewrite", "fact-check", "ai", "improve", "correct", "ai-translate", "code",
})
TICKET_OPERATION_COMMANDS = frozenset({"ticket", "ticket-reopen", "tickettranscript"})
SECURITY_OPERATION_COMMANDS = frozenset({"panic", "lockdown-server", "unlock-server"})
NOTIFICATION_COMMANDS = frozenset({"notifs-ping", "notifs-list", "notifs-remove"})
CURRENCY_DISPLAY_COMMANDS = ECONOMY_COMMANDS | frozenset({"stats", "profile", "level", "rank"})
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_CACHED_IMAGE_BYTES = 8_000_000
MAX_CACHED_IMAGES_PER_MESSAGE = 4


async def ensure_schema(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_v2_schema_ready", False):
        return
    lock = getattr(bot, "_sentrix_v2_schema_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        bot._sentrix_v2_schema_lock = lock
    async with lock:
        if getattr(bot, "_sentrix_v2_schema_ready", False):
            return
        statements = (
            """
            CREATE TABLE IF NOT EXISTS module_settings (
                guild_id INTEGER NOT NULL,
                module TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_by INTEGER,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, module)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS command_role_permissions (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                command_name TEXT NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('allow','deny')),
                updated_by INTEGER,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, role_id, command_name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS trusted_members (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                added_by INTEGER,
                added_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS economy_settings_v2 (
                guild_id INTEGER PRIMARY KEY,
                currency_singular TEXT NOT NULL DEFAULT 'Pièce',
                currency_plural TEXT NOT NULL DEFAULT 'Pièces',
                currency_symbol TEXT NOT NULL DEFAULT '🪙',
                updated_by INTEGER,
                updated_at INTEGER NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS message_attachment_cache_v2 (
                message_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT,
                data BLOB NOT NULL,
                stored_at INTEGER NOT NULL,
                PRIMARY KEY (message_id, position)
            )
            """,
        )
        for statement in statements:
            await bot.db.execute(statement)
        await bot.db.execute(
            "INSERT OR IGNORE INTO trusted_members (guild_id, user_id, added_by, added_at) "
            "SELECT guild_id, user_id, NULL, strftime('%s','now') FROM antinuke_whitelist"
        )
        bot._sentrix_v2_schema_ready = True
        logger.info("SentriX V2: schéma prêt.")


# --------------------------------------------------------------------------
# Cache des interrupteurs de modules
#
# Mesure : un message ordinaire declenchait TROIS fois la meme requete
# "SELECT enabled FROM module_settings WHERE guild_id=? AND module=?", depuis trois
# modules differents. C'est le poste le plus lourd du chemin chaud.
#
# Un interrupteur de module est de la CONFIGURATION : une valeur perimee laisserait
# tourner un module qu'un administrateur vient de couper. L'invalidation est donc
# explicite a chaque ecriture, et un TTL court sert uniquement de filet si une
# nouvelle ecriture apparaissait un jour sans invalidation.
#
# Les DEUX seuls ecrivains de module_settings sont :
#   - set_module_enabled (ci-dessous)
#   - setup_v2_completion, qui supprime la ligne lors d'une reinitialisation
# Tous deux appellent invalidate_module_cache.
_MODULE_ROW_CACHE: dict[tuple[int, str], tuple[float, int | None]] = {}
_MODULE_CACHE_TTL = 60.0


def invalidate_module_cache(guild_id: int | None = None, module: str | None = None) -> None:
    """Purge le cache. Sans argument : tout. Avec : la seule entree concernee."""
    if guild_id is None:
        _MODULE_ROW_CACHE.clear()
        return
    if module is None:
        for key in [k for k in _MODULE_ROW_CACHE if k[0] == int(guild_id)]:
            _MODULE_ROW_CACHE.pop(key, None)
        return
    _MODULE_ROW_CACHE.pop((int(guild_id), str(module)), None)


async def module_row_value(bot: commands.Bot, guild_id: int, module: str) -> int | None:
    """Valeur brute de module_settings.enabled, ou None si aucune ligne.

    Point de lecture unique et mis en cache. Les appelants appliquent ensuite LEUR
    propre semantique : c'est volontaire, module_enabled et access_matrix n'ont pas
    exactement les memes regles de repli et il ne faut pas les confondre.
    """
    key = (int(guild_id), str(module))
    cached = _MODULE_ROW_CACHE.get(key)
    if cached is not None and (time.monotonic() - cached[0]) < _MODULE_CACHE_TTL:
        return cached[1]
    row = await bot.db.fetchone(
        "SELECT enabled FROM module_settings WHERE guild_id=? AND module=?",
        (int(guild_id), str(module)),
    )
    value = None if row is None else int(row["enabled"])
    if len(_MODULE_ROW_CACHE) > 5000:
        _MODULE_ROW_CACHE.clear()
    _MODULE_ROW_CACHE[key] = (time.monotonic(), value)
    return value


async def module_enabled(bot: commands.Bot, guild_id: int, module: str) -> bool:
    if module not in MODULES:
        return True
    await ensure_schema(bot)
    value = await module_row_value(bot, guild_id, module)
    row = None if value is None else {"enabled": value}
    if row is None:
        if module == "ai":
            ai = await bot.db.fetchone("SELECT enabled FROM ai_settings WHERE guild_id=?", (int(guild_id),))
            if ai is not None:
                return bool(ai["enabled"])
        return True
    return bool(row["enabled"])


async def set_module_enabled(
    bot: commands.Bot,
    guild_id: int,
    module: str,
    enabled: bool,
    *,
    actor_id: int | None = None,
) -> None:
    if module not in MODULES:
        raise ValueError(f"module inconnu: {module}")
    await ensure_schema(bot)
    now_ts = int(time.time())
    await bot.db.execute(
        "INSERT INTO module_settings (guild_id,module,enabled,updated_by,updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(guild_id,module) DO UPDATE SET enabled=excluded.enabled, "
        "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (int(guild_id), module, 1 if enabled else 0, actor_id, now_ts),
    )
    # Invalidation immediate : couper un module doit prendre effet au message suivant,
    # pas au bout du TTL.
    invalidate_module_cache(guild_id, module)
    if module == "ai":
        await bot.db.execute(
            "INSERT INTO ai_settings (guild_id,enabled,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,updated_at=excluded.updated_at",
            (int(guild_id), 1 if enabled else 0, now_ts),
        )


async def economy_settings(bot: commands.Bot, guild_id: int) -> dict[str, Any]:
    await ensure_schema(bot)
    row = await bot.db.fetchone("SELECT * FROM economy_settings_v2 WHERE guild_id=?", (int(guild_id),))
    if row is None:
        return {"currency_singular": "Pièce", "currency_plural": "Pièces", "currency_symbol": "🪙"}
    return {
        "currency_singular": str(row["currency_singular"] or "Pièce"),
        "currency_plural": str(row["currency_plural"] or "Pièces"),
        "currency_symbol": str(row["currency_symbol"] or "🪙"),
    }


async def set_currency(
    bot: commands.Bot,
    guild_id: int,
    singular: str,
    plural: str,
    symbol: str,
    *,
    actor_id: int | None = None,
) -> None:
    await ensure_schema(bot)
    singular = str(singular or "Pièce").strip()[:32] or "Pièce"
    plural = str(plural or singular).strip()[:32] or singular
    symbol = str(symbol or "🪙").strip()[:16] or "🪙"
    await bot.db.execute(
        "INSERT INTO economy_settings_v2 "
        "(guild_id,currency_singular,currency_plural,currency_symbol,updated_by,updated_at) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET "
        "currency_singular=excluded.currency_singular,currency_plural=excluded.currency_plural,"
        "currency_symbol=excluded.currency_symbol,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (int(guild_id), singular, plural, symbol, actor_id, int(time.time())),
    )


async def get_role_command_decision(
    bot: commands.Bot,
    guild: discord.Guild | None,
    author: Any,
    command_name: str,
) -> str | None:
    if guild is None or not isinstance(author, discord.Member):
        return None
    await ensure_schema(bot)
    role_ids = [int(role.id) for role in author.roles]
    if not role_ids:
        return None
    placeholders = ",".join("?" for _ in role_ids)
    rows = await bot.db.fetchall(
        f"SELECT decision FROM command_role_permissions WHERE guild_id=? AND command_name=? "
        f"AND role_id IN ({placeholders})",
        (guild.id, command_name.casefold(), *role_ids),
    )
    decisions = {str(row["decision"]).casefold() for row in rows}
    if "deny" in decisions:
        return "deny"
    if "allow" in decisions:
        return "allow"
    return None


async def set_role_command_decision(
    bot: commands.Bot,
    guild_id: int,
    role_id: int,
    command_name: str,
    decision: str | None,
    *,
    actor_id: int | None = None,
) -> None:
    await ensure_schema(bot)
    command_name = str(command_name or "").casefold().strip()
    if not command_name:
        raise ValueError("command_name vide")
    if decision is None or decision == "default":
        await bot.db.execute(
            "DELETE FROM command_role_permissions WHERE guild_id=? AND role_id=? AND command_name=?",
            (int(guild_id), int(role_id), command_name),
        )
        return
    decision = decision.casefold()
    if decision not in {"allow", "deny"}:
        raise ValueError("decision invalide")
    await bot.db.execute(
        "INSERT INTO command_role_permissions "
        "(guild_id,role_id,command_name,decision,updated_by,updated_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(guild_id,role_id,command_name) DO UPDATE SET decision=excluded.decision,"
        "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (int(guild_id), int(role_id), command_name, decision, actor_id, int(time.time())),
    )


async def is_trusted(bot: commands.Bot, guild_id: int, user_id: int) -> bool:
    await ensure_schema(bot)
    row = await bot.db.fetchone(
        "SELECT 1 FROM trusted_members WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )
    if row is not None:
        return True
    legacy = await bot.db.fetchone(
        "SELECT 1 FROM antinuke_whitelist WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )
    return legacy is not None


async def add_trusted(bot: commands.Bot, guild_id: int, user_id: int, actor_id: int | None) -> None:
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT OR REPLACE INTO trusted_members (guild_id,user_id,added_by,added_at) VALUES (?,?,?,?)",
        (int(guild_id), int(user_id), actor_id, int(time.time())),
    )
    await bot.db.execute(
        "INSERT OR IGNORE INTO antinuke_whitelist (guild_id,user_id) VALUES (?,?)",
        (int(guild_id), int(user_id)),
    )


async def remove_trusted(bot: commands.Bot, guild_id: int, user_id: int) -> None:
    await ensure_schema(bot)
    await bot.db.execute("DELETE FROM trusted_members WHERE guild_id=? AND user_id=?", (int(guild_id), int(user_id)))
    await bot.db.execute("DELETE FROM antinuke_whitelist WHERE guild_id=? AND user_id=?", (int(guild_id), int(user_id)))


def _operation_module(command_name: str) -> str | None:
    name = str(command_name or "").casefold()
    if name in MODERATION_COMMANDS:
        return "moderation"
    if name in ECONOMY_COMMANDS:
        return "economy"
    if name in LEVEL_COMMANDS:
        return "levels"
    if name in AI_COMMANDS:
        return "ai"
    if name in TICKET_OPERATION_COMMANDS:
        return "tickets"
    if name in SECURITY_OPERATION_COMMANDS:
        return "security"
    return None


def _patch_permission_guard(bot: commands.Bot) -> None:
    """Neutralisé : la décision d'accès vit dans utils/access_matrix.py.

    Ce wrapper enveloppait evaluate_command_access et pouvait contredire la
    matrice (module coupé pour l'owner global, None == None ouvrant l'accès).
    Les modules et les règles de rôle sont désormais lus par la matrice.
    """
    return


def _patch_local_checks(bot: commands.Bot) -> None:
    for command in bot.walk_commands():
        checks_list = getattr(command, "checks", None)
        if not isinstance(checks_list, list):
            continue
        for index, predicate in enumerate(list(checks_list)):
            label = getattr(predicate, "_sentrix_permission_label", None)
            if not label or getattr(predicate, "_sentrix_setup_v2", False):
                continue
            if "Propriétaire global SentriX" in str(label):
                continue

            @functools.wraps(predicate)
            async def aligned(ctx, _original=predicate):
                try:
                    result = _original(ctx)
                    if hasattr(result, "__await__"):
                        result = await result
                    if result:
                        return True
                except checks.BotPermissionError:
                    pass
                command_obj = getattr(ctx, "command", None)
                root = getattr(command_obj, "root_parent", None) or command_obj
                decision = await permission_guard.evaluate_command_access(
                    ctx.bot,
                    command_name=getattr(root, "name", ""),
                    author=ctx.author,
                    guild=ctx.guild,
                )
                if decision.allowed:
                    return True
                raise checks.BotPermissionError(decision.reason or "Permission insuffisante.")

            aligned._sentrix_permission_label = label
            aligned._sentrix_setup_v2 = True
            checks_list[index] = aligned


def _patch_security(bot: commands.Bot) -> None:
    automod = bot.get_cog("Automod")
    if automod is None or getattr(automod, "_sentrix_setup_v2_security", False):
        return

    original_exempt = automod.is_automod_exempt

    async def automod_exempt_v2(_self, member):
        if isinstance(member, discord.Member) and await is_trusted(bot, member.guild.id, member.id):
            return True
        return await original_exempt(member)

    automod.is_automod_exempt = MethodType(automod_exempt_v2, automod)

    original_nuke_exempt = automod.is_antinuke_exempt

    async def nuke_exempt_v2(_self, guild, actor):
        if actor is not None and await is_trusted(bot, guild.id, actor.id):
            return True
        return await original_nuke_exempt(guild, actor)

    automod.is_antinuke_exempt = MethodType(nuke_exempt_v2, automod)

    original_cached = automod.get_automod_cached

    async def automod_cached_v2(_self, guild_id):
        conf = await original_cached(guild_id)
        if await module_enabled(bot, guild_id, "security"):
            return conf
        muted = dict(conf or {})
        for key in (
            "antispam", "antilink", "antiinvite", "antimention", "anticaps", "antiemoji",
            "antiraid", "antibot", "antiaccount", "antiscam", "antinuke", "escalation",
        ):
            muted[key] = 0
        return muted

    automod.get_automod_cached = MethodType(automod_cached_v2, automod)
    automod._sentrix_setup_v2_security = True


async def _cache_message_images(bot: commands.Bot, message: discord.Message) -> None:
    if message.guild is None or message.author.bot or not message.attachments:
        return
    await ensure_schema(bot)
    saved = 0
    for attachment in message.attachments:
        if saved >= MAX_CACHED_IMAGES_PER_MESSAGE:
            break
        filename = str(attachment.filename or "image").lower()
        content_type = str(attachment.content_type or "").lower()
        if not (content_type.startswith("image/") or filename.endswith(IMAGE_EXTENSIONS)):
            continue
        if int(getattr(attachment, "size", 0) or 0) > MAX_CACHED_IMAGE_BYTES:
            continue
        try:
            data = await attachment.read()
        except (discord.HTTPException, OSError):
            continue
        if not data or len(data) > MAX_CACHED_IMAGE_BYTES:
            continue
        await bot.db.execute(
            "INSERT OR REPLACE INTO message_attachment_cache_v2 "
            "(message_id,position,guild_id,filename,content_type,data,stored_at) VALUES (?,?,?,?,?,?,?)",
            (
                message.id,
                saved,
                message.guild.id,
                attachment.filename,
                attachment.content_type,
                data,
                int(time.time()),
            ),
        )
        saved += 1


async def _first_cached_image(bot: commands.Bot, guild_id: int, message_id: int):
    await ensure_schema(bot)
    return await bot.db.fetchone(
        "SELECT * FROM message_attachment_cache_v2 WHERE guild_id=? AND message_id=? ORDER BY position LIMIT 1",
        (int(guild_id), int(message_id)),
    )


def _message_id_from_event_key(event_key: str | None) -> int | None:
    if not event_key:
        return None
    parts = str(event_key).split(":")
    if len(parts) < 6:
        return None
    try:
        value = int(parts[5])
    except (TypeError, ValueError):
        return None
    return value or None


def _patch_logs(bot: commands.Bot) -> None:
    log_service.LOG_TYPES.setdefault(
        "resources",
        {
            "label": "Ressources serveur (emojis, invitations, stickers, webhooks)",
            "category": "Ressources serveur",
            "legacy_column": None,
            "emits": True,
        },
    )
    if "Ressources serveur" not in log_service.CATEGORY_ORDER:
        try:
            insert_at = log_service.CATEGORY_ORDER.index("Vocal")
        except ValueError:
            insert_at = len(log_service.CATEGORY_ORDER)
        log_service.CATEGORY_ORDER.insert(insert_at, "Ressources serveur")

    current_send_log = log_service.send_log
    if not getattr(current_send_log, "_sentrix_setup_v2", False):

        async def send_log_v2(target_bot, guild, log_type, embed, file=None, *, view=None, event_key=None, **identity):
            if not await module_enabled(target_bot, guild.id, "logs"):
                return False
            return await current_send_log(
                target_bot,
                guild,
                log_type,
                embed,
                file,
                view=view,
                event_key=event_key,
            **identity)

        send_log_v2._sentrix_setup_v2 = True
        send_log_v2._sentrix_previous = current_send_log
        log_service.send_log = send_log_v2

    logs_cog = bot.get_cog("Logs")
    if logs_cog is None or getattr(logs_cog, "_sentrix_setup_v2", False):
        return

    original_send = logs_cog._send

    async def logs_send_v2(_self, guild, config_key, embed, *, view=None, event_key=None):
        title = str(getattr(embed, "title", "") or "")
        if config_key == "log_roles" and title in {"Rôle ajouté", "Rôle retiré"}:
            config_key = "log_members"
        if config_key == "log_server" and title.startswith("Rôle "):
            config_key = "log_roles"
        if config_key == "log_messages" and title == "Message supprimé":
            message_id = _message_id_from_event_key(event_key)
            if message_id:
                cached = await _first_cached_image(bot, guild.id, message_id)
                if cached is not None:
                    filename = str(cached["filename"] or "image.png")
                    data = bytes(cached["data"])
                    file = discord.File(io.BytesIO(data), filename=filename)
                    embed.set_image(url=f"attachment://{filename}")
                    return await log_service.send_log(
                        bot,
                        guild,
                        "messages",
                        embed,
                        file,
                        view=view,
                        event_key=event_key,
                    )
        return await original_send(guild, config_key, embed, view=view, event_key=event_key)

    logs_cog._send = MethodType(logs_send_v2, logs_cog)

    original_cache = logs_cog._cache_message

    async def cache_v2(_self, message):
        await original_cache(message)
        await _cache_message_images(bot, message)

    logs_cog._cache_message = MethodType(cache_v2, logs_cog)

    original_forget = logs_cog._forget_cached_message

    async def forget_v2(_self, message_id):
        await original_forget(message_id)
        try:
            await bot.db.execute(
                "DELETE FROM message_attachment_cache_v2 WHERE message_id=?",
                (int(message_id),),
            )
        except Exception:
            pass

    logs_cog._forget_cached_message = MethodType(forget_v2, logs_cog)
    logs_cog._sentrix_setup_v2 = True


def _patch_feature_runtimes(bot: commands.Bot) -> None:
    levels = bot.get_cog("Levels")
    if levels is not None and not getattr(levels, "_sentrix_setup_v2", False):
        original_process = levels._process_xp

        async def process_xp_v2(_self, message, settings, conf):
            if not await module_enabled(bot, message.guild.id, "levels"):
                return None
            return await original_process(message, settings, conf)

        levels._process_xp = MethodType(process_xp_v2, levels)
        levels._sentrix_setup_v2 = True

    tickets = bot.get_cog("Tickets")
    if tickets is not None and not getattr(tickets, "_sentrix_setup_v2", False):
        original_create = tickets.create_ticket

        async def create_ticket_v2(_self, interaction, ticket_type, answers):
            if not await module_enabled(bot, interaction.guild.id, "tickets"):
                return await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error('Le module **Tickets** est désactivé sur ce serveur.')), ephemere=True)
            return await original_create(interaction, ticket_type, answers)

        tickets.create_ticket = MethodType(create_ticket_v2, tickets)
        tickets._sentrix_setup_v2 = True

    notifications = bot.get_cog("Notifications")
    if notifications is not None and not getattr(notifications, "_sentrix_setup_v2", False):
        original_check = notifications._check_subscription

        async def check_subscription_v2(_self, row):
            if not await module_enabled(bot, int(row["guild_id"]), "notifications"):
                return None
            return await original_check(row)

        notifications._check_subscription = MethodType(check_subscription_v2, notifications)
        notifications._sentrix_setup_v2 = True


def _replace_currency_text(text: str | None, settings: dict[str, Any]) -> str | None:
    if text is None:
        return None
    value = str(text).replace("🪙", settings["currency_symbol"])
    value = re.sub(r"\bPièces\b", settings["currency_plural"], value)
    value = re.sub(r"\bpièces\b", settings["currency_plural"].lower(), value)
    value = re.sub(r"\bPièce\b", settings["currency_singular"], value)
    value = re.sub(r"\bpièce\b", settings["currency_singular"].lower(), value)
    return value


def _embed_mentions_currency(embed: discord.Embed | None) -> bool:
    if embed is None:
        return False
    blob = " ".join(
        [str(embed.title or ""), str(embed.description or "")]
        + [f"{field.name} {field.value}" for field in embed.fields]
    )
    return (
        "🪙" in blob
        or "Portefeuille" in blob
        or "Boutique" in blob
        or "Classement économique" in blob
    )


def _apply_currency_to_embed(embed: discord.Embed, settings: dict[str, Any]) -> None:
    if embed.title:
        embed.title = _replace_currency_text(embed.title, settings)
    if embed.description:
        embed.description = _replace_currency_text(embed.description, settings)
    for index, field in enumerate(list(embed.fields)):
        embed.set_field_at(
            index,
            name=_replace_currency_text(field.name, settings) or field.name,
            value=_replace_currency_text(field.value, settings) or field.value,
            inline=field.inline,
        )
    if embed.footer and embed.footer.text:
        embed.set_footer(
            text=_replace_currency_text(embed.footer.text, settings),
            icon_url=embed.footer.icon_url,
        )


def _root_name(command: Any) -> str:
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _patch_currency_transport(bot: commands.Bot) -> None:
    current_ctx_send = commands.Context.send
    if not getattr(current_ctx_send, "_sentrix_currency_v2", False):

        async def ctx_send_v2(self, *args, **kwargs):
            guild = getattr(self, "guild", None)
            root = _root_name(getattr(self, "command", None))
            candidate = kwargs.get("embed")
            if guild is not None and (
                root in CURRENCY_DISPLAY_COMMANDS or _embed_mentions_currency(candidate)
            ):
                settings = await economy_settings(self.bot, guild.id)
                if isinstance(candidate, discord.Embed):
                    _apply_currency_to_embed(candidate, settings)
                for item in kwargs.get("embeds") or ():
                    if isinstance(item, discord.Embed) and _embed_mentions_currency(item):
                        _apply_currency_to_embed(item, settings)
            return await current_ctx_send(self, *args, **kwargs)

        ctx_send_v2._sentrix_currency_v2 = True
        ctx_send_v2._sentrix_previous = current_ctx_send
        commands.Context.send = ctx_send_v2

    current_response = discord.InteractionResponse.send_message
    if not getattr(current_response, "_sentrix_currency_v2", False):

        async def response_v2(self, *args, **kwargs):
            interaction = getattr(self, "_parent", None)
            guild = getattr(interaction, "guild", None)
            candidate = kwargs.get("embed")
            if guild is not None and isinstance(candidate, discord.Embed) and _embed_mentions_currency(candidate):
                client = getattr(interaction, "client", bot)
                settings = await economy_settings(client, guild.id)
                _apply_currency_to_embed(candidate, settings)
            return await current_response(self, *args, **kwargs)

        response_v2._sentrix_currency_v2 = True
        response_v2._sentrix_previous = current_response
        discord.InteractionResponse.send_message = response_v2


def _install_welcome_listeners(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_welcome_v2", False):
        return

    async def on_member_join_v2(member: discord.Member):
        guild = member.guild
        conf = await bot.db.get_guild_config(guild.id)

        if await module_enabled(bot, guild.id, "roles"):
            try:
                role_id = conf["autorole"] if conf else None
            except (KeyError, IndexError, TypeError):
                role_id = None
            role = guild.get_role(int(role_id)) if role_id else None
            if role and guild.me and guild.me.guild_permissions.manage_roles and role < guild.me.top_role:
                try:
                    await member.add_roles(role, reason="Autorole SentriX")
                except discord.HTTPException:
                    pass

        if not await module_enabled(bot, guild.id, "welcome"):
            return

        def cv(key, default=None):
            try:
                value = conf[key] if conf else None
            except (KeyError, IndexError, TypeError):
                value = None
            return default if value is None else value

        channel_id = cv("welcome_channel")
        channel = guild.get_channel(int(channel_id)) if channel_id else guild.system_channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        me = guild.me
        if me is None:
            return
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            return
        template = cv(
            "welcome_message",
            "Bienvenue {member} ! Content de t’accueillir sur **{server}**.",
        )
        text = str(template).replace("{member}", member.mention).replace("{username}", member.display_name)
        text = text.replace("{server}", guild.name).replace("{member_count}", str(guild.member_count or 0))
        panel = embeds.brand(f"Bienvenue {member.display_name}", text)
        panel.set_thumbnail(url=member.display_avatar.url)
        image_url = cv("welcome_image_url")
        if image_url and str(image_url).startswith(("https://", "http://")):
            panel.set_image(url=str(image_url))
        try:
            await channel.send(
                content=member.mention,
                embed=panel,
                allowed_mentions=discord.AllowedMentions(
                    users=[member],
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.HTTPException:
            pass

    async def on_member_remove_v2(member: discord.Member):
        guild = member.guild
        if not await module_enabled(bot, guild.id, "welcome"):
            return
        conf = await bot.db.get_guild_config(guild.id)

        def cv(key, default=None):
            try:
                value = conf[key] if conf else None
            except (KeyError, IndexError, TypeError):
                value = None
            return default if value is None else value

        channel_id = cv("goodbye_channel")
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        template = cv("goodbye_message", "**{username}** a quitté **{server}**.")
        text = str(template).replace("{member}", member.mention).replace("{username}", member.display_name)
        text = text.replace("{server}", guild.name).replace("{member_count}", str(guild.member_count or 0))
        panel = embeds.neutral("Départ d’un membre", text)
        panel.set_thumbnail(url=member.display_avatar.url)
        try:
            await panels.envoyer(channel, panels.depuis_embed(panel), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    bot.add_listener(on_member_join_v2, "on_member_join")
    bot.add_listener(on_member_remove_v2, "on_member_remove")
    bot._sentrix_welcome_v2 = True


def _install_whitelist_commands(bot: commands.Bot) -> None:
    if bot.get_command("whitelist") is None:

        async def whitelist_callback(
            ctx: commands.Context,
            membre: discord.Member | None = None,
            action: str = "add",
        ):
            if ctx.guild is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée dans un serveur.')))
            await ensure_schema(bot)
            if membre is None:
                rows = await bot.db.fetchall(
                    "SELECT user_id,added_by,added_at FROM trusted_members WHERE guild_id=? ORDER BY added_at",
                    (ctx.guild.id,),
                )
                if not rows:
                    return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Aucun membre ou bot n’est dans la whitelist globale SentriX.')))
                lines = []
                for row in rows[:40]:
                    actor = f"<@{row['added_by']}>" if row["added_by"] else "migration anti-nuke"
                    lines.append(f"<@{row['user_id']}> — ajouté par {actor}")
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('\n'.join(lines), title='Whitelist globale SentriX')))
            normalized = str(action or "add").casefold()
            if normalized in {"remove", "delete", "retirer", "supprimer", "off"}:
                await remove_trusted(bot, ctx.guild.id, membre.id)
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} a été retiré de la whitelist globale SentriX.')))
            await add_trusted(bot, ctx.guild.id, membre.id, ctx.author.id)
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} est maintenant whitelisté pour les protections automatiques SentriX.')))

        whitelist_callback = checks.is_owner_or_admin_for("securite")(whitelist_callback)
        whitelist_command = commands.hybrid_command(
            name="whitelist",
            description="Ajouter, retirer ou afficher la whitelist globale SentriX.",
        )(whitelist_callback)
        bot.add_command(whitelist_command)

    if bot.get_command("unwhitelist") is None:

        async def unwhitelist_callback(ctx: commands.Context, membre: discord.Member):
            if ctx.guild is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée dans un serveur.')))
            await remove_trusted(bot, ctx.guild.id, membre.id)
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} a été retiré de la whitelist globale SentriX.')))

        unwhitelist_callback = checks.is_owner_or_admin_for("securite")(unwhitelist_callback)
        unwhitelist_command = commands.hybrid_command(
            name="unwhitelist",
            description="Retirer un membre ou bot de la whitelist globale SentriX.",
        )(unwhitelist_callback)
        bot.add_command(unwhitelist_command)


def permission_scope_for_command(bot: commands.Bot, command_name: str) -> str:
    name = str(command_name or "").casefold()
    if name in MODERATION_COMMANDS:
        return "moderation"
    if name in ECONOMY_COMMANDS:
        return "economy"
    if name in LEVEL_COMMANDS:
        return "levels"
    if name in AI_COMMANDS:
        return "ai"
    if name.startswith("ticket") or name == "ticket":
        return "tickets"
    if name.startswith("notif"):
        return "notifications"
    policy_module = __import__(bot.__class__.__module__, fromlist=["CATEGORY_COMMANDS"])
    categories = getattr(policy_module, "CATEGORY_COMMANDS", {})
    for category, names in categories.items():
        if name in names:
            return str(category)
    public = set(getattr(policy_module, "PUBLIC_COMMANDS", ()))
    if name in public:
        return "public"
    return "other"


def commands_for_scope(bot: commands.Bot, scope: str) -> list[str]:
    names: set[str] = set()
    for command in bot.walk_commands():
        root = getattr(command, "root_parent", None) or command
        name = str(getattr(root, "name", "") or "").casefold()
        if name and permission_scope_for_command(bot, name) == scope:
            names.add(name)
    return sorted(names)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_v2_core", False):
        return
    _patch_permission_guard(bot)
    _install_whitelist_commands(bot)
    _patch_local_checks(bot)
    _patch_security(bot)
    _patch_logs(bot)
    _patch_feature_runtimes(bot)
    _install_welcome_listeners(bot)
    _patch_currency_transport(bot)
    bot._sentrix_setup_v2_core = True
    logger.info("SentriX V2 core installé.")


__all__ = [
    "MODULES", "MODERATION_COMMANDS", "ECONOMY_COMMANDS", "LEVEL_COMMANDS",
    "AI_COMMANDS", "ensure_schema", "module_enabled", "set_module_enabled",
    "economy_settings", "set_currency", "get_role_command_decision",
    "set_role_command_decision", "is_trusted", "add_trusted", "remove_trusted",
    "permission_scope_for_command", "commands_for_scope", "install",
]
