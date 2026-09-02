"""SentriX V3 — expérience membre visible.

Cette couche ajoute des fonctionnalités de produit (pas seulement du hardening) sans
multiplier les commandes :
- saison mensuelle et XP de saison ;
- missions quotidiennes automatiques ;
- streak quotidien avec bonus économique ;
- profil communautaire enrichi et achievements ;
- tickets résumés/classés automatiquement à l'ouverture ;
- IA consciente du contexte public du serveur ;
- onboarding automatique lorsqu'un serveur ajoute SentriX ;
- métriques V3 visibles dans le dashboard.

Les tables V3 sont créées de façon idempotente au runtime afin de rester compatibles avec
les installations existantes. Aucune donnée sensible n'est ajoutée au contexte IA.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import hashlib
import json
import logging
import re
import time
import types
from collections import defaultdict
from datetime import datetime, timezone

import discord
from discord.ext import commands

import config
from utils import design_system, embeds, stats_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.community-v3")

_SCHEMA_READY = False
_SCHEMA_LOCK = asyncio.Lock()
_PROGRESS_LOCKS: defaultdict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
_PENDING_MESSAGES: defaultdict[tuple[int, int], int] = defaultdict(int)
_FLUSH_TASK: asyncio.Task | None = None
_AI_GUILD_CONTEXT: contextvars.ContextVar[int | None] = contextvars.ContextVar("sentrix_v3_ai_guild", default=None)
_AI_CHANNEL_CONTEXT: contextvars.ContextVar[int | None] = contextvars.ContextVar("sentrix_v3_ai_channel", default=None)

MISSION_POOL = (
    ("messages", "💬 Envoyer 10 messages", 10, 70),
    ("commands", "⚡ Utiliser 5 commandes", 5, 55),
    ("games", "🎮 Jouer à 2 mini-jeux", 2, 85),
    ("economy", "💰 Faire 3 actions économie", 3, 65),
    ("ai", "🤖 Utiliser SentriX AI", 1, 45),
    ("tickets", "🎫 Ouvrir un ticket si nécessaire", 1, 40),
)

GAME_COMMANDS = {
    "rps", "guess-number", "trivia", "tictactoe", "hangman", "math-quiz",
    "blackjack", "slots", "coinflip", "dice", "luckyroll", "highlow", "memory",
    "reaction", "scramble", "wordgame", "emojiquiz", "colorquiz", "fasttype", "duel",
    "connect4", "numberduel", "reactionduel", "quizduel", "triviastart", "wordrace",
    "reactionevent", "guessrace", "mathrace", "lastmessage", "emoji-race", "adventure",
    "dungeon", "mining", "fishing", "treasure", "hunt", "explore",
}
ECONOMY_COMMANDS = {
    "daily", "weekly", "work", "rob", "pay", "shop", "buy", "sell", "gamble",
    "deposit", "withdraw", "banque", "balance", "economy",
}
AI_COMMANDS = {
    "sentrix", "ai", "chat", "ask", "summarize", "explain", "rewrite", "fact-check",
    "improve", "correct", "ai-translate", "code", "image", "image-prompt",
}

URGENT_PATTERNS = re.compile(
    r"\b(urgent|urgence|hack|hacker|pirat|scam|arnaqu|menace|harcel|dox|raid|vol[eé]?|"
    r"paiement|payement|rembourse|ban injust|danger|compte compromis|token)\b",
    re.IGNORECASE,
)


async def _ensure_schema(bot: commands.Bot) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        statements = (
            """
            CREATE TABLE IF NOT EXISTS member_engagement (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                season_id TEXT NOT NULL,
                season_xp INTEGER NOT NULL DEFAULT 0,
                daily_streak INTEGER NOT NULL DEFAULT 0,
                longest_streak INTEGER NOT NULL DEFAULT 0,
                last_daily_claim INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS member_daily_progress (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                messages INTEGER NOT NULL DEFAULT 0,
                commands INTEGER NOT NULL DEFAULT 0,
                games INTEGER NOT NULL DEFAULT 0,
                economy INTEGER NOT NULL DEFAULT 0,
                ai INTEGER NOT NULL DEFAULT 0,
                tickets INTEGER NOT NULL DEFAULT 0,
                rewarded_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (guild_id, user_id, day)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_member_engagement_season ON member_engagement (guild_id, season_id, season_xp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_member_daily_progress_day ON member_daily_progress (guild_id, day)",
        )
        for statement in statements:
            await bot.db.execute(statement)
        _SCHEMA_READY = True
        logger.info("SentriX V3 : tables saison/missions prêtes.")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def current_day() -> str:
    return _utc_now().strftime("%Y-%m-%d")


def current_season() -> str:
    return _utc_now().strftime("%Y-%m")


def season_label(season_id: str | None = None) -> str:
    raw = season_id or current_season()
    try:
        year, month = raw.split("-", 1)
        names = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
        return f"{names[int(month) - 1].capitalize()} {year}"
    except Exception:
        return raw


def mission_selection(guild_id: int, user_id: int, day: str | None = None):
    """Retourne 3 missions stables et toujours distinctes pour toute la journée UTC."""
    day = day or current_day()
    seed = f"{day}:{int(guild_id)}:{int(user_id)}"
    ranked = sorted(
        MISSION_POOL,
        key=lambda mission: hashlib.sha256(f"{seed}:{mission[0]}".encode()).digest(),
    )
    return tuple(ranked[:3])


def _season_tier(xp: int) -> str:
    if xp >= 5000:
        return "👑 Master"
    if xp >= 3000:
        return "💎 Diamant"
    if xp >= 1500:
        return "🥇 Or"
    if xp >= 600:
        return "🥈 Argent"
    return "🥉 Bronze"


def _progress_bar(current: int, target: int, blocks: int = 10) -> str:
    if target <= 0:
        return "█" * blocks
    ratio = max(0.0, min(1.0, current / target))
    filled = round(ratio * blocks)
    return "█" * filled + "░" * (blocks - filled)


async def _engagement_row(bot: commands.Bot, guild_id: int, user_id: int):
    await _ensure_schema(bot)
    season = current_season()
    row = await bot.db.fetchone(
        "SELECT * FROM member_engagement WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    )
    if row is None:
        await bot.db.execute(
            "INSERT INTO member_engagement (guild_id,user_id,season_id) VALUES (?,?,?)",
            (guild_id, user_id, season),
        )
    elif row["season_id"] != season:
        await bot.db.execute(
            "UPDATE member_engagement SET season_id=?, season_xp=0 WHERE guild_id=? AND user_id=?",
            (season, guild_id, user_id),
        )
    return await bot.db.fetchone(
        "SELECT * FROM member_engagement WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    )


async def _daily_row(bot: commands.Bot, guild_id: int, user_id: int):
    await _ensure_schema(bot)
    day = current_day()
    await bot.db.execute(
        "INSERT OR IGNORE INTO member_daily_progress (guild_id,user_id,day) VALUES (?,?,?)",
        (guild_id, user_id, day),
    )
    return await bot.db.fetchone(
        "SELECT * FROM member_daily_progress WHERE guild_id=? AND user_id=? AND day=?",
        (guild_id, user_id, day),
    )


async def _add_season_xp(bot: commands.Bot, guild_id: int, user_id: int, amount: int) -> int:
    if amount <= 0:
        row = await _engagement_row(bot, guild_id, user_id)
        return int(row["season_xp"] or 0)
    await _engagement_row(bot, guild_id, user_id)
    await bot.db.execute(
        "UPDATE member_engagement SET season_xp=season_xp+? WHERE guild_id=? AND user_id=?",
        (int(amount), guild_id, user_id),
    )
    row = await bot.db.fetchone(
        "SELECT season_xp FROM member_engagement WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    )
    return int(row["season_xp"] or 0)


async def record_action(bot: commands.Bot, guild_id: int, user_id: int, action: str, amount: int = 1) -> list[tuple[str, int]]:
    """Incrémente une progression et auto-récompense les missions terminées."""
    if action not in {"messages", "commands", "games", "economy", "ai", "tickets"}:
        return []
    amount = max(1, min(int(amount), 100))
    key = (int(guild_id), int(user_id))
    async with _PROGRESS_LOCKS[key]:
        await _daily_row(bot, guild_id, user_id)
        await bot.db.execute(
            f"UPDATE member_daily_progress SET {action}=MIN({action}+?, 100000) WHERE guild_id=? AND user_id=? AND day=?",
            (amount, guild_id, user_id, current_day()),
        )
        row = await _daily_row(bot, guild_id, user_id)
        try:
            rewarded = set(json.loads(row["rewarded_json"] or "[]"))
        except (TypeError, ValueError):
            rewarded = set()
        rewards: list[tuple[str, int]] = []
        for mission_key, label, target, xp in mission_selection(guild_id, user_id, row["day"]):
            if mission_key in rewarded:
                continue
            if int(row[mission_key] or 0) >= target:
                rewarded.add(mission_key)
                rewards.append((label, xp))
        if rewards:
            await bot.db.execute(
                "UPDATE member_daily_progress SET rewarded_json=? WHERE guild_id=? AND user_id=? AND day=?",
                (json.dumps(sorted(rewarded)), guild_id, user_id, row["day"]),
            )
            await _add_season_xp(bot, guild_id, user_id, sum(xp for _, xp in rewards))
        return rewards


async def register_daily_claim(bot: commands.Bot, guild_id: int, user_id: int, *, claimed_at: int | None = None) -> dict:
    """Met à jour le streak uniquement après une vraie réussite de +daily."""
    await _ensure_schema(bot)
    claimed_at = int(claimed_at or time.time())
    key = (int(guild_id), int(user_id))
    async with _PROGRESS_LOCKS[key]:
        row = await _engagement_row(bot, guild_id, user_id)
        previous = int(row["last_daily_claim"] or 0)
        if previous and claimed_at - previous < 60:
            return {"new": False, "streak": int(row["daily_streak"] or 0), "bonus": 0}
        gap = claimed_at - previous if previous else 0
        if previous and gap <= 48 * 3600:
            streak = int(row["daily_streak"] or 0) + 1
        else:
            streak = 1
        longest = max(int(row["longest_streak"] or 0), streak)
        await bot.db.execute(
            "UPDATE member_engagement SET daily_streak=?, longest_streak=?, last_daily_claim=? WHERE guild_id=? AND user_id=?",
            (streak, longest, claimed_at, guild_id, user_id),
        )
        bonus = min(streak, 7) * 25
        await bot.db.add_balance(guild_id, user_id, bonus)
        await bot.db.log_transaction(guild_id, None, user_id, "daily_streak_bonus", bonus, f"Bonus streak quotidien x{streak}")
        await _add_season_xp(bot, guild_id, user_id, 20 + min(streak, 10) * 3)
        return {"new": True, "streak": streak, "bonus": bonus, "longest": longest}


async def get_progression(bot: commands.Bot, guild_id: int, user_id: int) -> dict:
    engagement = await _engagement_row(bot, guild_id, user_id)
    daily = await _daily_row(bot, guild_id, user_id)
    missions = []
    try:
        rewarded = set(json.loads(daily["rewarded_json"] or "[]"))
    except (TypeError, ValueError):
        rewarded = set()
    for key, label, target, xp in mission_selection(guild_id, user_id, daily["day"]):
        current = min(target, int(daily[key] or 0))
        missions.append({
            "key": key,
            "label": label,
            "target": target,
            "current": current,
            "xp": xp,
            "done": key in rewarded or current >= target,
        })
    season_xp = int(engagement["season_xp"] or 0)
    season_level = season_xp // 250 + 1
    level_current = season_xp % 250
    return {
        "season_id": engagement["season_id"],
        "season_xp": season_xp,
        "season_level": season_level,
        "season_level_xp": level_current,
        "season_level_target": 250,
        "tier": _season_tier(season_xp),
        "daily_streak": int(engagement["daily_streak"] or 0),
        "longest_streak": int(engagement["longest_streak"] or 0),
        "missions": missions,
    }


def achievement_names(stats: dict, progression: dict) -> list[str]:
    result = []
    if int(stats.get("current_level", 0)) >= 5:
        result.append("📈 En progression")
    if int(stats.get("message_count", 0)) >= 1000:
        result.append("💬 Pilier du serveur")
    if int(stats.get("voice_time", 0)) >= 10 * 3600:
        result.append("🎙️ Habitué du vocal")
    if int(stats.get("total_money", 0)) >= 10_000:
        result.append("💰 Entrepreneur")
    if int(stats.get("reputation", 0)) >= 10:
        result.append("⭐ Apprécié")
    if int(progression.get("longest_streak", 0)) >= 7:
        result.append("🔥 Semaine parfaite")
    if int(progression.get("season_xp", 0)) >= 1500:
        result.append("🏆 Compétiteur de saison")
    return result or ["🌱 Nouveau départ"]


def ticket_summary(ticket_type_name: str, answers: list) -> tuple[str, str]:
    """Résumé local rapide : aucun appel IA ni contenu envoyé hors du serveur."""
    cleaned = []
    raw_parts = []
    for label, value in answers:
        value = str(value or "").strip()
        if not value:
            continue
        raw_parts.append(value)
        short = re.sub(r"\s+", " ", value)
        if len(short) > 150:
            short = short[:147] + "…"
        cleaned.append(f"{label}: {short}")
    body = " | ".join(cleaned[:3]) if cleaned else "Aucun détail supplémentaire fourni."
    summary = f"{ticket_type_name} — {body}"
    if len(summary) > 750:
        summary = summary[:747] + "…"
    priority = "haute" if URGENT_PATTERNS.search(" ".join(raw_parts)) else "normale"
    return summary, priority


async def _flush_pending_messages(bot: commands.Bot) -> None:
    if not _PENDING_MESSAGES:
        return
    snapshot = dict(_PENDING_MESSAGES)
    _PENDING_MESSAGES.clear()
    for (guild_id, user_id), count in snapshot.items():
        try:
            await record_action(bot, guild_id, user_id, "messages", min(count, 30))
        except Exception:
            logger.exception("V3 : impossible d'enregistrer la mission messages (guild=%s user=%s).", guild_id, user_id)


async def _flush_loop(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
        while not bot.is_closed():
            await asyncio.sleep(45)
            await _flush_pending_messages(bot)
    except asyncio.CancelledError:
        raise
    except RuntimeError as exc:
        logger.debug("V3 : boucle différée jusqu'au vrai démarrage Discord: %s", exc)
    except Exception:
        logger.exception("V3 : boucle de progression interrompue.")


def _replace_command_callback(command: commands.Command | None, callback, marker: str) -> bool:
    if command is None or getattr(command, marker, False):
        return False
    params = command.params.copy()
    callback = functools.wraps(command.callback)(callback)
    command.callback = callback
    command.params = params
    setattr(command, marker, True)
    return True


def _install_rich_profile(bot: commands.Bot) -> None:
    command = bot.get_command("profile")
    if command is None:
        return

    async def rich_profile(cog, ctx: commands.Context, membre: discord.Member = None):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande fonctionne uniquement sur un serveur.')))
        if ctx.interaction:
            await ctx.defer()
        member = membre or ctx.author
        settings = await bot.db.get_stats_settings(ctx.guild.id)
        design = await bot.db.get_design_settings(ctx.guild.id)
        stats = await stats_service.get_member_statistics(bot, ctx.guild, member)
        progression = await get_progression(bot, ctx.guild.id, member.id)
        bio_row = await bot.db.fetchone(
            "SELECT bio FROM profiles WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, member.id),
        )
        achievements = achievement_names(stats, progression)
        eco_emoji = settings.get("economy_emoji", "🪙")
        style = design_system.CATEGORY_STYLES["levels"]
        progress = _progress_bar(progression["season_level_xp"], progression["season_level_target"])
        embed = design_system.create_embed(
            title=f"🪪 {member.display_name} — Profil SentriX",
            description=(
                f"{member.mention} • Niveau **{stats['current_level']}**"
                + (f" • Rang **#{stats['rank']}**" if stats["is_ranked"] else " • Non classé")
                + f"\n{progression['tier']} • Saison **{season_label(progression['season_id'])}**"
            ),
            colour=design.get("primary_color", style["colour"]),
            user=member if design.get("show_avatars", True) else None,
            thumbnail=member.display_avatar.url if design.get("show_avatars", True) else None,
            footer=design.get("footer") or "SentriX • Profil communautaire",
        )
        embed.add_field(name="📈 Niveau", value=f"**{stats['current_level']}**", inline=True)
        embed.add_field(name="💬 Messages", value=stats_service.format_number(stats["message_count"]), inline=True)
        embed.add_field(name="🔊 Vocal", value=stats_service.format_duration(stats["voice_time"]), inline=True)
        if settings.get("show_economy", True):
            embed.add_field(
                name="💰 Économie",
                value=(
                    f"{stats_service.format_number(stats['wallet'])} {eco_emoji} portefeuille\n"
                    f"{stats_service.format_number(stats['bank'])} 🏦 banque\n"
                    f"**{stats_service.format_number(stats['total_money'])}** total"
                ),
                inline=True,
            )
        if settings.get("show_reputation", True):
            embed.add_field(name="⭐ Réputation", value=f"**{stats_service.format_number(stats['reputation'])}** point(s)", inline=True)
        embed.add_field(
            name="🔥 Série quotidienne",
            value=f"**{progression['daily_streak']} jour(s)**\nRecord : {progression['longest_streak']} jour(s)",
            inline=True,
        )
        embed.add_field(
            name=f"🏆 Saison • Niveau {progression['season_level']}",
            value=(
                f"`{progress}` **{progression['season_level_xp']}/250 XP**\n"
                f"XP saison : **{stats_service.format_number(progression['season_xp'])}**"
            ),
            inline=False,
        )
        if member.id == ctx.author.id:
            mission_lines = []
            for mission in progression["missions"]:
                icon = "✅" if mission["done"] else "▫️"
                mission_lines.append(
                    f"{icon} {mission['label']} — **{mission['current']}/{mission['target']}** · +{mission['xp']} XP"
                )
            embed.add_field(name="🎯 Missions du jour", value="\n".join(mission_lines), inline=False)
        embed.add_field(name="🏅 Succès", value=" • ".join(achievements[:5]), inline=False)
        embed.add_field(
            name="📝 Bio",
            value=(bio_row["bio"] if bio_row and bio_row["bio"] else "Aucune bio définie — utilise `+set-bio` pour en ajouter une."),
            inline=False,
        )
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    _replace_command_callback(command, rich_profile, "_sentrix_v3_rich_profile")


def _install_ticket_intelligence(bot: commands.Bot) -> None:
    tickets = bot.get_cog("Tickets")
    if tickets is None or getattr(tickets, "_sentrix_v3_ticket_intelligence", False):
        return
    original = tickets.create_ticket

    async def smart_create(this, interaction: discord.Interaction, ticket_type, answers: list):
        summary, priority = ticket_summary(str(ticket_type["name"]), list(answers or []))
        enriched = list(answers or [])
        enriched.append(("🧠 Résumé automatique", summary))
        enriched.append(("⚡ Priorité détectée", "Haute — à regarder rapidement" if priority == "haute" else "Normale"))
        result = await original(interaction, ticket_type, enriched)
        if interaction.guild and interaction.user:
            try:
                row = await bot.db.fetchone(
                    "SELECT id FROM tickets WHERE guild_id=? AND user_id=? AND type_id=? AND status='ouvert' ORDER BY id DESC LIMIT 1",
                    (interaction.guild.id, interaction.user.id, ticket_type["id"]),
                )
                if row:
                    await bot.db.execute("UPDATE tickets SET priority=? WHERE id=?", (priority, row["id"]))
                await record_action(bot, interaction.guild.id, interaction.user.id, "tickets")
            except Exception:
                logger.exception("V3 : post-traitement ticket impossible.")
        return result

    smart_create._sentrix_v3_ticket_intelligence = True
    tickets.create_ticket = types.MethodType(smart_create, tickets)
    tickets._sentrix_v3_ticket_intelligence = True


async def _server_context(bot: commands.Bot, guild_id: int | None, channel_id: int | None) -> str:
    if not guild_id:
        return ""
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return ""
    prefix = getattr(bot, "prefix_cache", {}).get(guild.id, config.DEFAULT_PREFIX)
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    lines = [
        "\n\nCONTEXTE PUBLIC DU SERVEUR DISCORD (utilise-le seulement si pertinent) :",
        f"- Serveur : {guild.name}",
        f"- Membres : {guild.member_count or 0}",
        f"- Préfixe SentriX : {prefix}",
        f"- Salon actuel : #{getattr(channel, 'name', 'inconnu')}",
    ]
    try:
        conf = await bot.db.get_guild_config(guild.id)
        if conf:
            rules = guild.get_channel(conf["rules_channel"]) if conf["rules_channel"] else None
            commands_channel = guild.get_channel(conf["bot_commands_channel"]) if conf["bot_commands_channel"] else None
            if rules:
                lines.append(f"- Salon du règlement : #{rules.name}")
            if commands_channel:
                lines.append(f"- Salon conseillé pour les commandes : #{commands_channel.name}")
    except Exception:
        pass
    lines.append(
        "Quand la personne demande comment utiliser SentriX ou le serveur, donne une réponse concrète avec le préfixe réel. "
        "N'invente jamais un rôle, une règle, un salon ou une action non présent dans ce contexte."
    )
    return "\n".join(lines)


def _install_ai_context(bot: commands.Bot) -> None:
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None or getattr(ai_cog, "_sentrix_v3_context", False):
        return

    original_build = ai_cog._build_system_instructions
    original_ask = ai_cog.ask_ai
    original_prepare = ai_cog._prepare_and_generate

    async def build_with_server_context(this, user_id: int | None, author_name: str | None = None):
        text = await original_build(user_id, author_name)
        text += (
            "\n\nStyle SentriX V3 : sois naturel, direct et utile dans un contexte Discord. "
            "Évite les longs pavés quand quelques lignes suffisent. Si une commande existante répond mieux, indique-la clairement."
        )
        text += await _server_context(bot, _AI_GUILD_CONTEXT.get(), _AI_CHANNEL_CONTEXT.get())
        return text

    async def ask_with_context(this, prompt, history: list = None, author_name: str = None, **kwargs):
        token_g = _AI_GUILD_CONTEXT.set(kwargs.get("guild_id"))
        token_c = _AI_CHANNEL_CONTEXT.set(kwargs.get("channel_id"))
        try:
            return await original_ask(prompt, history, author_name, **kwargs)
        finally:
            _AI_GUILD_CONTEXT.reset(token_g)
            _AI_CHANNEL_CONTEXT.reset(token_c)

    async def prepare_with_context(this, **kwargs):
        token_g = _AI_GUILD_CONTEXT.set(kwargs.get("guild_id"))
        token_c = _AI_CHANNEL_CONTEXT.set(kwargs.get("channel_id"))
        try:
            return await original_prepare(**kwargs)
        finally:
            _AI_GUILD_CONTEXT.reset(token_g)
            _AI_CHANNEL_CONTEXT.reset(token_c)

    ai_cog._build_system_instructions = types.MethodType(build_with_server_context, ai_cog)
    ai_cog.ask_ai = types.MethodType(ask_with_context, ai_cog)
    ai_cog._prepare_and_generate = types.MethodType(prepare_with_context, ai_cog)
    ai_cog._sentrix_v3_context = True


def _install_dashboard_v3(bot: commands.Bot) -> None:
    try:
        from web import dashboard
    except Exception:
        logger.exception("V3 : dashboard import impossible.")
        return
    if getattr(dashboard, "_sentrix_v3_metrics", False):
        return

    original_metrics = dashboard._guild_metrics

    async def metrics_v3(db, guild_id: int) -> dict:
        data = await original_metrics(db, guild_id)
        await _ensure_schema(bot)
        today = current_day()
        season = current_season()
        queries = {
            "season_players": ("SELECT COUNT(*) AS n FROM member_engagement WHERE guild_id=? AND season_id=? AND season_xp>0", (guild_id, season)),
            "missions_today": ("SELECT COUNT(*) AS n FROM member_daily_progress WHERE guild_id=? AND day=?", (guild_id, today)),
            "priority_tickets": ("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND status='ouvert' AND priority='haute'", (guild_id,)),
            "ai_requests_today": ("SELECT COALESCE(SUM(requests),0) AS n FROM ai_usage WHERE guild_id=? AND day=?", (guild_id, today)),
        }
        for key, (query, params) in queries.items():
            try:
                row = await db.fetchone(query, params)
                data[key] = int(row["n"] if row else 0)
            except Exception:
                data[key] = 0
        return data

    dashboard._guild_metrics = metrics_v3
    html = dashboard.INDEX_HTML
    old_cards = '''<div class="overview">
          <div class="metric"><small>Membres</small><strong id="metricMembers">—</strong></div>
          <div class="metric"><small>Commandes sur 24 h</small><strong id="metricCommands">—</strong></div>
          <div class="metric"><small>Tickets ouverts</small><strong id="metricTickets">—</strong></div>
          <div class="metric"><small>Avertissements</small><strong id="metricWarnings">—</strong></div>
        </div>'''
    new_cards = '''<div class="overview">
          <div class="metric"><small>Membres</small><strong id="metricMembers">—</strong></div>
          <div class="metric"><small>Commandes sur 24 h</small><strong id="metricCommands">—</strong></div>
          <div class="metric"><small>Tickets ouverts</small><strong id="metricTickets">—</strong></div>
          <div class="metric"><small>Tickets prioritaires</small><strong id="metricPriorityTickets">—</strong></div>
          <div class="metric"><small>Joueurs de la saison</small><strong id="metricSeasonPlayers">—</strong></div>
          <div class="metric"><small>Missions actives aujourd'hui</small><strong id="metricMissions">—</strong></div>
          <div class="metric"><small>Requêtes IA aujourd'hui</small><strong id="metricAI">—</strong></div>
          <div class="metric"><small>Avertissements</small><strong id="metricWarnings">—</strong></div>
        </div>'''
    if old_cards in html:
        html = html.replace(old_cards, new_cards, 1)
    old_js = '$("metricTickets").textContent=number(d.metrics.open_tickets);$("metricWarnings").textContent=number(d.metrics.warnings);'
    new_js = '$("metricTickets").textContent=number(d.metrics.open_tickets);$("metricPriorityTickets").textContent=number(d.metrics.priority_tickets);$("metricSeasonPlayers").textContent=number(d.metrics.season_players);$("metricMissions").textContent=number(d.metrics.missions_today);$("metricAI").textContent=number(d.metrics.ai_requests_today);$("metricWarnings").textContent=number(d.metrics.warnings);'
    if old_js in html:
        html = html.replace(old_js, new_js, 1)
    dashboard.INDEX_HTML = html
    dashboard._sentrix_v3_metrics = True


async def _notify_mission_rewards(ctx: commands.Context, rewards: list[tuple[str, int]]) -> None:
    if not rewards:
        return
    total = sum(xp for _, xp in rewards)
    names = "\n".join(f"✅ {label} — **+{xp} XP saison**" for label, xp in rewards)
    try:
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'🎯 Mission terminée !\n{names}\n\nTotal gagné : **+{total} XP saison**')))
    except discord.HTTPException:
        pass


def _root_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


async def _on_message(bot: commands.Bot, message: discord.Message) -> None:
    if message.author.bot or message.guild is None:
        return
    key = (message.guild.id, message.author.id)
    _PENDING_MESSAGES[key] = min(30, _PENDING_MESSAGES[key] + 1)


async def _on_command_completion(bot: commands.Bot, ctx: commands.Context) -> None:
    if ctx.guild is None or getattr(ctx.author, "bot", False):
        return
    root = _root_name(ctx)
    rewards = await record_action(bot, ctx.guild.id, ctx.author.id, "commands")
    if root in GAME_COMMANDS:
        rewards += await record_action(bot, ctx.guild.id, ctx.author.id, "games")
    if root in ECONOMY_COMMANDS:
        rewards += await record_action(bot, ctx.guild.id, ctx.author.id, "economy")
    if root in AI_COMMANDS:
        rewards += await record_action(bot, ctx.guild.id, ctx.author.id, "ai")

    if root == "daily":
        try:
            balance = await bot.db.get_balance(ctx.guild.id, ctx.author.id)
            last_daily = int(balance["last_daily"] or 0) if balance else 0
            if last_daily and abs(int(time.time()) - last_daily) <= 30:
                streak = await register_daily_claim(bot, ctx.guild.id, ctx.author.id, claimed_at=last_daily)
                if streak.get("new"):
                    await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"🔥 **Streak quotidien : {streak['streak']} jour(s)**\nBonus de série : **+{stats_service.format_number(streak['bonus'])} 🪙**\nRecord : **{streak['longest']} jour(s)**")))
        except Exception:
            logger.exception("V3 : impossible de mettre à jour le streak daily.")
    await _notify_mission_rewards(ctx, rewards)


async def _on_guild_join(bot: commands.Bot, guild: discord.Guild) -> None:
    bot_member = guild.me
    if bot_member is None:
        return
    channel = guild.system_channel
    if channel is None or not channel.permissions_for(bot_member).send_messages:
        channel = next(
            (c for c in guild.text_channels if c.permissions_for(bot_member).send_messages),
            None,
        )
    if channel is None:
        return
    embed = embeds.brand(
        "🚀 Bienvenue sur SentriX V3",
        (
            "SentriX est prêt. Pour éviter une configuration compliquée, commence par **`+setup`** : l'assistant vous guide pour les rôles, salons, tickets, sécurité, niveaux et logs.\n\n**Pour les membres :** `+profile` affiche maintenant la saison, le streak, les missions et les succès.\n**IA :** écris simplement `SentriX ...` ou utilisez `+ai`.\n**Besoin d'aide :** `+help`."
        ),
    )
    if config.DASHBOARD_PUBLIC_URL:
        embed.add_field(name="🌐 Dashboard", value=config.DASHBOARD_PUBLIC_URL, inline=False)
    try:
        await panels.envoyer(channel, panels.depuis_embed(embed))
    except discord.HTTPException:
        pass


def install(bot: commands.Bot) -> None:
    """Installe V3 une seule fois après les cogs historiques."""
    global _FLUSH_TASK
    if getattr(bot, "_sentrix_community_v3_installed", False):
        return

    _install_rich_profile(bot)
    _install_ticket_intelligence(bot)
    _install_ai_context(bot)
    _install_dashboard_v3(bot)

    async def message_listener(message: discord.Message):
        await _on_message(bot, message)

    async def command_listener(ctx: commands.Context):
        await _on_command_completion(bot, ctx)

    async def guild_join_listener(guild: discord.Guild):
        await _on_guild_join(bot, guild)

    async def ready_listener():
        await _ensure_schema(bot)
        _install_rich_profile(bot)
        _install_ticket_intelligence(bot)
        _install_ai_context(bot)
        _install_dashboard_v3(bot)

    bot.add_listener(message_listener, "on_message")
    bot.add_listener(command_listener, "on_command_completion")
    bot.add_listener(guild_join_listener, "on_guild_join")
    bot.add_listener(ready_listener, "on_ready")

    try:
        _FLUSH_TASK = asyncio.create_task(_flush_loop(bot), name="sentrix-v3-mission-flush")
    except RuntimeError:
        _FLUSH_TASK = None

    bot._sentrix_community_v3_installed = True
    bot._sentrix_community_v3_state = {
        "ready": True,
        "season": current_season(),
        "missions": 3,
        "features": (
            "season", "daily_missions", "daily_streak", "achievements",
            "smart_tickets", "server_aware_ai", "guild_onboarding", "dashboard_metrics",
        ),
    }
    logger.info("SentriX V3 expérience membre installée : saisons, missions, streak, profil, tickets, IA et dashboard.")
