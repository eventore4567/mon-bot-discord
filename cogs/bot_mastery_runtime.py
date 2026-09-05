"""SentriX Bot Mastery Runtime — amélioration du bot Discord uniquement.

Cette couche complète Excellence sans dépendre du dashboard. Elle ajoute des protections
et des mécanismes de récupération autour des systèmes existants plutôt que de dupliquer
leurs commandes :
- anti-raid à score de risque avec quarantaine temporaire ;
- anti-nuke V3 (rôles, webhooks, serveur, mass-kick) avec rollback ciblé ;
- permissions par commande via +security access ;
- preuves automatiques de modération consultables via +security evidence ;
- conseils de sanction adaptatifs selon l'historique ;
- tickets priorisés et réattribués si un claim devient abandonné ;
- reprise des boucles, panels, musique et états persistants après redémarrage ;
- musique protégée par timeout/retry/circuit breaker et reprise de file ;
- mémoire IA bornée + circuit breaker texte/image ;
- maintenance/quick_check/optimisation SQLite ;
- diagnostics de commandes et erreurs regroupées par empreinte ;
- mode dégradé automatique pour les modules non critiques qui échouent en boucle ;
- détection/réparation des tâches de fond bloquées ;
- sondes de composants persistants ;
- défis hebdomadaires de jeux et anti-farm de récompenses ;
- détection d'abus économique/circular transfers ;
- onboarding privé en deux étapes sans spam ;
- arrêt gracieux avec flush/checkpoint et état clean/dirty.

Les deux seules interfaces ajoutées sont des SOUS-commandes de +security ; aucune nouvelle
racine publique ni commande slash n'est créée.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from types import MethodType
from typing import Any

import discord

from utils import embeds
from utils import sentrix_panels as panels
from discord.ext import commands, tasks

from database.db import now
from utils import helpers

logger = logging.getLogger("bot.mastery-runtime")
_COG_NAME = "BotMasteryRuntime"

JOIN_WINDOW_SECONDS = 20
JOIN_RISK_TIMEOUT_SECONDS = 600
JOIN_RECENT_NAME_SECONDS = 120
NUKE_WINDOW_SECONDS = 30
NUKE_THRESHOLD = 3
MASS_KICK_THRESHOLD = 3
COMMAND_FAILURE_WINDOW = 60
COMMAND_FAILURE_THRESHOLD = 5
DEGRADED_SECONDS = 120
TICKET_REASSIGN_SECONDS = 1800
COMPONENT_PROBE_INTERVAL = 900
DB_MAINTENANCE_INTERVAL = 21600
AI_MEMORY_MAX_MESSAGES = 12
AI_MEMORY_MAX_CHARS = 6000
API_FAILURE_THRESHOLD = 3
API_BREAKER_SECONDS = 90
GAME_WEEKLY_TARGET = 15
GAME_WEEKLY_BONUS = 200
GAME_HOURLY_SOFT_CAP = 12
ECONOMY_ABUSE_BLOCK_SECONDS = 120

CRITICAL_COMMANDS = frozenset({
    "ban", "tempban", "unban", "kick", "mute", "unmute", "warn", "unwarn",
    "clear", "lock", "unlock", "security", "panic", "quarantine", "unquarantine",
    "antinuke", "antiraid", "ticket", "ticket-reopen",
})
MONEY_COMMANDS = frozenset({
    "pay", "rob", "gamble", "daily", "weekly", "work", "sell", "deposit", "withdraw", "banque"
})
MUSIC_COMMANDS = frozenset({
    "join", "leave", "play", "pause", "resume", "skip", "stop", "queue", "nowplaying",
    "volume", "loop", "shuffle", "remove-from-queue", "clear-queue", "playlist-load",
})
URGENT_TICKET_WORDS = (
    "urgent", "urgence", "raid", "nuke", "hack", "pirat", "compte vol", "arnaque",
    "scam", "menace", "dox", "leak", "ban erreur", "banni erreur", "payment", "paiement",
)

RUNTIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS mastery_join_risk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    action TEXT NOT NULL DEFAULT 'none',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mastery_join_risk_time ON mastery_join_risk (guild_id, created_at);

CREATE TABLE IF NOT EXISTS mastery_nuke_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    target_id INTEGER,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    handled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_mastery_nuke_actor ON mastery_nuke_actions (guild_id, actor_id, handled, created_at);

CREATE TABLE IF NOT EXISTS command_access_rules (
    guild_id INTEGER NOT NULL,
    command_name TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    created_by INTEGER,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, command_name, role_id)
);

CREATE TABLE IF NOT EXISTS moderation_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    case_number INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message_id INTEGER,
    channel_id INTEGER,
    content TEXT,
    attachments_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moderation_evidence_case ON moderation_evidence (guild_id, case_number);

CREATE TABLE IF NOT EXISTS adaptive_sanction_advice (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    case_number INTEGER,
    advice TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_mastery_state (
    ticket_id INTEGER PRIMARY KEY,
    priority TEXT NOT NULL DEFAULT 'normale',
    last_claimed_by INTEGER,
    claim_last_seen INTEGER NOT NULL DEFAULT 0,
    reassigned_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS music_recovery_state (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    current_json TEXT,
    queue_json TEXT NOT NULL DEFAULT '[]',
    volume REAL NOT NULL DEFAULT 0.5,
    loop_enabled INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS api_circuit_state (
    service TEXT PRIMARY KEY,
    failures INTEGER NOT NULL DEFAULT 0,
    opened_until INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS database_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    detail TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS command_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    command_name TEXT,
    category TEXT NOT NULL,
    detail TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_command_diagnostics_time ON command_diagnostics (created_at);

CREATE TABLE IF NOT EXISTS runtime_error_groups (
    fingerprint TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    error_type TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    sample TEXT,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_module_state (
    module TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'healthy',
    failures INTEGER NOT NULL DEFAULT 0,
    opened_until INTEGER NOT NULL DEFAULT 0,
    last_seen INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS component_probe_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    component_type TEXT NOT NULL,
    message_id INTEGER,
    status TEXT NOT NULL,
    detail TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS economy_abuse_state (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    blocked_until INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS economy_transfer_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    sender_id INTEGER,
    receiver_id INTEGER,
    amount INTEGER NOT NULL DEFAULT 0,
    direction TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_economy_transfer_recent ON economy_transfer_events (guild_id, sender_id, created_at);

CREATE TABLE IF NOT EXISTS onboarding_state (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS game_weekly_progress (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    week TEXT NOT NULL,
    wins INTEGER NOT NULL DEFAULT 0,
    claimed INTEGER NOT NULL DEFAULT 0,
    claimed_at INTEGER,
    PRIMARY KEY (guild_id, user_id, week)
);

CREATE TABLE IF NOT EXISTS shutdown_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at INTEGER NOT NULL
);
"""



def _reponse(titre: str, description: str = "", *, kind: str = "securite"):
    """Reponse composee : banniere, titre, et le detail en section quand il y en a.

    Une description sur plusieurs lignes devient une SECTION plutot qu'un
    paragraphe : ces reponses enumerent souvent des reglages ou des etats, et une
    enumeration se lit mal d'un bloc.
    """
    # Pas de section ici : une confirmation d'une ligne n'a rien a structurer, et
    # fabriquer une section « Détail » autour d'une phrase ne ferait que deplacer
    # du texte. Ce niveau est l'IDENTITE — banniere, accent, titre. Les ecrans qui
    # ont vraiment de la matiere sont composes a la main, la ou ils sont ecrits.
    resume = " ".join(l.strip() for l in str(description or "").split("\n") if l.strip())
    return panels.Panneau(
        titre=titre if titre.startswith("SentriX") else f"SentriX — {titre}",
        sous_titre=resume,
        kind=kind if kind in panels.INTENTIONS else "securite",
        pied="SentriX",
    )


class MasteryDegradedError(commands.CheckFailure):
    pass


_SCHEMA_READY = False
_MODERATION_PATCHED = False
_MUSIC_PATCHED = False
_AI_PATCHED = False
_GAME_PATCHED = False
_CLOSE_PATCHED = False
_SECURITY_SUBCOMMANDS_PATCHED = False
_ACCESS_CHECK_PATCHED = False


def _session_started(bot: commands.Bot) -> bool:
    return bool(getattr(getattr(bot, "http", None), "token", None))


async def _ensure_schema(bot: commands.Bot) -> bool:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True
    conn = getattr(getattr(bot, "db", None), "_conn", None)
    if conn is None:
        return False
    await conn.executescript(RUNTIME_SCHEMA)
    await conn.commit()
    _SCHEMA_READY = True
    return True


async def _safe_execute(bot: commands.Bot, sql: str, params: tuple = ()) -> None:
    try:
        if await _ensure_schema(bot):
            await bot.db.execute(sql, params)
    except Exception:
        logger.exception("Écriture Mastery impossible.")


async def _group_error(bot: commands.Bot, source: str, error: BaseException) -> None:
    try:
        if not await _ensure_schema(bot):
            return
        error_type = type(error).__name__
        text = re.sub(r"\d{8,}", "<id>", str(error))[:800]
        raw = f"{source}|{error_type}|{text}"
        fingerprint = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]
        ts = now()
        await bot.db.execute(
            "INSERT INTO runtime_error_groups (fingerprint,source,error_type,count,sample,first_seen,last_seen) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(fingerprint) DO UPDATE SET "
            "count = count + 1, sample = excluded.sample, last_seen = excluded.last_seen",
            (fingerprint, source[:120], error_type[:120], 1, text, ts, ts),
        )
    except Exception:
        logger.exception("Regroupement d'erreur Mastery impossible.")


def _role_payload(role: discord.Role) -> dict[str, Any]:
    return {
        "name": role.name,
        "permissions": int(role.permissions.value),
        "colour": int(role.colour.value),
        "hoist": bool(role.hoist),
        "mentionable": bool(role.mentionable),
        "position": int(role.position),
    }


def _member_role_ids(member: discord.Member) -> set[int]:
    return {int(role.id) for role in getattr(member, "roles", [])}


def _week_key(ts: datetime | None = None) -> str:
    dt = ts or datetime.now(timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


async def _api_is_open(bot: commands.Bot, service: str) -> bool:
    try:
        if not await _ensure_schema(bot):
            return False
        row = await bot.db.fetchone("SELECT opened_until FROM api_circuit_state WHERE service = ?", (service,))
        return bool(row and int(row["opened_until"] or 0) > now())
    except Exception:
        return False


async def _api_result(bot: commands.Bot, service: str, ok: bool, error: str | None = None) -> None:
    try:
        if not await _ensure_schema(bot):
            return
        row = await bot.db.fetchone("SELECT failures FROM api_circuit_state WHERE service = ?", (service,))
        failures = int(row["failures"] or 0) if row else 0
        if ok:
            failures = 0
            opened_until = 0
        else:
            failures += 1
            opened_until = now() + API_BREAKER_SECONDS if failures >= API_FAILURE_THRESHOLD else 0
        await bot.db.execute(
            "INSERT INTO api_circuit_state (service,failures,opened_until,last_error,updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(service) DO UPDATE SET failures=excluded.failures, opened_until=excluded.opened_until, "
            "last_error=excluded.last_error, updated_at=excluded.updated_at",
            (service, failures, opened_until, (error or "")[:500], now()),
        )
    except Exception:
        logger.exception("État circuit breaker impossible à enregistrer.")


async def _command_access_check(ctx: commands.Context) -> bool:
    if ctx.guild is None or ctx.command is None or not isinstance(ctx.author, discord.Member):
        return True
    root = ctx.command.root_parent or ctx.command
    name = root.name.casefold()
    try:
        rows = await ctx.bot.db.fetchall(
            "SELECT role_id FROM command_access_rules WHERE guild_id = ? AND command_name = ?",
            (ctx.guild.id, name),
        )
    except Exception:
        return True
    if not rows:
        return True
    if ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator:
        return True
    allowed = {int(row["role_id"]) for row in rows}
    if -1 in allowed:
        raise MasteryDegradedError("Cette commande est réservée aux administrateurs sur ce serveur.")
    if _member_role_ids(ctx.author) & allowed:
        return True
    mentions = [ctx.guild.get_role(rid).mention for rid in allowed if rid > 0 and ctx.guild.get_role(rid)]
    suffix = ", ".join(mentions[:5]) if mentions else "un rôle autorisé"
    raise MasteryDegradedError(f"Cette commande est limitée à {suffix} sur ce serveur.")


async def _security_access(ctx: commands.Context, command_name: str | None = None, *, rule: str | None = None):
    if ctx.guild is None or not isinstance(ctx.author, discord.Member):
        return await panels.envoyer(ctx, _reponse('Accès aux commandes', 'Cette configuration est disponible uniquement sur un serveur.', kind='danger'))
    if not (ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator):
        return await panels.envoyer(ctx, _reponse('Accès aux commandes', 'Seul le propriétaire du serveur ou un administrateur peut modifier cet accès.', kind='danger'))
    if not command_name:
        return await panels.envoyer(ctx, _reponse('Accès aux commandes', 'Utilisation : +security access <commande> <@role|admin|off>. Sans deuxième valeur, SentriX affiche la règle actuelle.', kind='warning'))
    command_name = command_name.casefold().lstrip("+/")
    command = ctx.bot.get_command(command_name)
    if command is None:
        return await panels.envoyer(ctx, _reponse('Accès aux commandes', 'Commande introuvable.', kind='danger'))
    root = command.root_parent or command
    command_name = root.name.casefold()
    if not rule:
        rows = await ctx.bot.db.fetchall(
            "SELECT role_id FROM command_access_rules WHERE guild_id=? AND command_name=?",
            (ctx.guild.id, command_name),
        )
        if not rows:
            return await panels.envoyer(ctx, _reponse('Accès aux commandes', f'Aucune restriction supplémentaire pour +{command_name}.', kind='warning'))
        parts = []
        for row in rows:
            rid = int(row["role_id"])
            if rid == -1:
                parts.append("Administrateurs uniquement")
            else:
                role = ctx.guild.get_role(rid)
                if role:
                    parts.append(role.mention)
        return await panels.envoyer(ctx, _reponse('Accès aux commandes', f'Accès +{command_name} : ' + (', '.join(parts) or 'règle invalide'), kind='brand'))

    value = rule.strip()
    if value.casefold() in {"off", "reset", "remove", "aucun"}:
        await ctx.bot.db.execute(
            "DELETE FROM command_access_rules WHERE guild_id=? AND command_name=?",
            (ctx.guild.id, command_name),
        )
        return await panels.envoyer(ctx, _reponse('Accès aux commandes', f'Restriction supplémentaire retirée pour +{command_name}.', kind='success'))

    if value.casefold() in {"admin", "admins", "administrator", "administrateur"}:
        await ctx.bot.db.execute(
            "DELETE FROM command_access_rules WHERE guild_id=? AND command_name=?",
            (ctx.guild.id, command_name),
        )
        await ctx.bot.db.execute(
            "INSERT INTO command_access_rules (guild_id,command_name,role_id,created_by,created_at) VALUES (?,?,?,?,?)",
            (ctx.guild.id, command_name, -1, ctx.author.id, now()),
        )
        return await panels.envoyer(ctx, _reponse('Accès aux commandes', f'+{command_name} est maintenant réservé aux administrateurs.', kind='success'))

    match = re.search(r"(\d{15,22})", value)
    role = ctx.guild.get_role(int(match.group(1))) if match else None
    if role is None:
        role = discord.utils.find(lambda r: r.name.casefold() == value.casefold(), ctx.guild.roles)
    if role is None or role.is_default():
        return await panels.envoyer(ctx, _reponse('Accès aux commandes', 'Rôle introuvable. Mentionnez le rôle ou donnez son ID.', kind='danger'))
    await ctx.bot.db.execute(
        "DELETE FROM command_access_rules WHERE guild_id=? AND command_name=? AND role_id=-1",
        (ctx.guild.id, command_name),
    )
    await ctx.bot.db.execute(
        "INSERT OR IGNORE INTO command_access_rules (guild_id,command_name,role_id,created_by,created_at) VALUES (?,?,?,?,?)",
        (ctx.guild.id, command_name, role.id, ctx.author.id, now()),
    )
    return await panels.envoyer(ctx, _reponse('Accès aux commandes', f'Le rôle {role.mention} peut utiliser +{command_name}, en plus des administrateurs.', kind='brand'))


async def _security_evidence(ctx: commands.Context, case_number: int | None = None):
    if ctx.guild is None or not isinstance(ctx.author, discord.Member):
        return await panels.envoyer(ctx, _reponse('Preuves de sécurité', 'Cette commande est disponible uniquement sur un serveur.', kind='danger'))
    if not (ctx.author.guild_permissions.moderate_members or ctx.author.guild_permissions.administrator or ctx.author.id == ctx.guild.owner_id):
        return await panels.envoyer(ctx, _reponse('Preuves de sécurité', 'Permission de modération requise.', kind='danger'))
    if case_number is None:
        return await panels.envoyer(ctx, _reponse('Preuves de sécurité', 'Utilisation : +security evidence <numéro de dossier>.', kind='warning'))
    rows = await ctx.bot.db.fetchall(
        "SELECT * FROM moderation_evidence WHERE guild_id=? AND case_number=? ORDER BY id ASC LIMIT 8",
        (ctx.guild.id, int(case_number)),
    )
    if not rows:
        return await panels.envoyer(ctx, _reponse('Preuves de sécurité', 'Aucune preuve automatique enregistrée pour ce dossier.', kind='warning'))
    lines = []
    for row in rows:
        content = (row["content"] or "[message sans texte]").replace("\n", " ")[:240]
        lines.append(f"Salon <#{row['channel_id']}> - message `{row['message_id']}` : {content}")
    text = "\n".join(lines)
    if len(text) > 1800:
        text = text[:1800] + "…"
    await panels.envoyer(ctx, _reponse('Preuves de sécurité', f'Preuves du dossier #{int(case_number)}\n{text}', kind='brand'))


def _install_security_subcommands(bot: commands.Bot) -> None:
    global _SECURITY_SUBCOMMANDS_PATCHED
    if _SECURITY_SUBCOMMANDS_PATCHED:
        return
    root = bot.get_command("security")
    if not isinstance(root, commands.Group):
        return
    if root.get_command("access") is None:
        root.add_command(commands.Command(_security_access, name="access", help="Limiter une commande à un rôle ou aux administrateurs."))
    if root.get_command("evidence") is None:
        root.add_command(commands.Command(_security_evidence, name="evidence", help="Afficher les preuves sauvegardées pour un dossier de modération."))
    _SECURITY_SUBCOMMANDS_PATCHED = True
    logger.info("Security Mastery : sous-commandes access/evidence activées.")


def _install_access_check(bot: commands.Bot) -> None:
    global _ACCESS_CHECK_PATCHED
    if _ACCESS_CHECK_PATCHED:
        return
    bot.add_check(_command_access_check)
    _ACCESS_CHECK_PATCHED = True
    logger.info("Permissions par commande activées comme restriction supplémentaire.")


def _install_moderation_evidence(bot: commands.Bot) -> None:
    global _MODERATION_PATCHED
    if _MODERATION_PATCHED:
        return
    cog = bot.get_cog("Moderation")
    runtime = bot.get_cog(_COG_NAME)
    if cog is None or runtime is None:
        return
    cls = type(cog)
    original = cls.log_sanction
    if getattr(original, "_sentrix_mastery_evidence", False):
        _MODERATION_PATCHED = True
        return

    async def log_sanction_mastery(self, ctx, action, target, reason, duration_seconds=None, extra_fields=None):
        snapshots = list(runtime._recent_messages.get((ctx.guild.id, target.id), ()))
        if getattr(ctx, "message", None) and getattr(ctx.message, "reference", None):
            resolved = getattr(ctx.message.reference, "resolved", None)
            if isinstance(resolved, discord.Message) and resolved.author.id == target.id:
                snapshots.append(runtime._snapshot_message(resolved))
        embed = await original(self, ctx, action, target, reason, duration_seconds, extra_fields)
        try:
            row = await self.bot.db.fetchone(
                "SELECT case_number FROM sanctions WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
                (ctx.guild.id, target.id),
            )
            case_number = int(row["case_number"]) if row and row["case_number"] is not None else None
            if case_number is not None:
                unique: dict[int, dict] = {}
                for snap in snapshots[-8:]:
                    if snap.get("message_id"):
                        unique[int(snap["message_id"])] = snap
                for snap in unique.values():
                    await self.bot.db.execute(
                        "INSERT INTO moderation_evidence (guild_id,case_number,user_id,message_id,channel_id,content,attachments_json,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (
                            ctx.guild.id, case_number, target.id, snap.get("message_id"), snap.get("channel_id"),
                            (snap.get("content") or "")[:1800], json.dumps(snap.get("attachments") or []), now(),
                        ),
                    )
                total = await self.bot.db.get_sanction_count(ctx.guild.id, target.id)
                advice = runtime._sanction_advice(action, total)
                if advice:
                    await self.bot.db.execute(
                        "INSERT INTO adaptive_sanction_advice (guild_id,user_id,case_number,advice,created_at) VALUES (?,?,?,?,?)",
                        (ctx.guild.id, target.id, case_number, advice, now()),
                    )
                    try:
                        embed.add_field(name="Recommandation", value=advice, inline=False)
                    except Exception:
                        pass
                if unique:
                    try:
                        embed.add_field(name="Preuves", value=f"{len(unique)} message(s) récent(s) sauvegardé(s).", inline=False)
                    except Exception:
                        pass
        except Exception as exc:
            await _group_error(self.bot, "moderation_evidence", exc)
        return embed

    log_sanction_mastery._sentrix_mastery_evidence = True
    cls.log_sanction = log_sanction_mastery
    _MODERATION_PATCHED = True
    logger.info("Modération Mastery : preuves et conseils adaptatifs activés.")


def _install_ai_mastery(bot: commands.Bot) -> None:
    global _AI_PATCHED
    if _AI_PATCHED:
        return
    try:
        from utils import ai_service
    except Exception:
        return
    if not hasattr(ai_service, "generate") or not hasattr(ai_service, "generate_image"):
        return

    original_generate = ai_service.generate
    original_image = ai_service.generate_image
    original_history = getattr(ai_service, "get_conversation_history", None)
    if getattr(original_generate, "_sentrix_mastery_circuit", False):
        _AI_PATCHED = True
        return

    async def generate_safe(*args, **kwargs):
        if await _api_is_open(bot, "openai_text"):
            return ai_service.AiResult(error=ai_service.ERROR_CONNECTION, model_key=kwargs.get("model_key"))
        result = await original_generate(*args, **kwargs)
        bad = result.error in {ai_service.ERROR_RATE_LIMIT, ai_service.ERROR_TIMEOUT, ai_service.ERROR_CONNECTION, ai_service.ERROR_GENERIC}
        await _api_result(bot, "openai_text", not bad, result.error if bad else None)
        return result

    async def image_safe(*args, **kwargs):
        if await _api_is_open(bot, "openai_image"):
            return ai_service.ImageResult(error=ai_service.ERROR_CONNECTION)
        result = await original_image(*args, **kwargs)
        bad = result.error in {ai_service.ERROR_RATE_LIMIT, ai_service.ERROR_TIMEOUT, ai_service.ERROR_CONNECTION, ai_service.ERROR_GENERIC}
        await _api_result(bot, "openai_image", not bad, result.error if bad else None)
        return result

    generate_safe._sentrix_mastery_circuit = True
    image_safe._sentrix_mastery_circuit = True
    ai_service.generate = generate_safe
    ai_service.generate_image = image_safe

    if original_history and not getattr(original_history, "_sentrix_mastery_bounded", False):
        async def history_bounded(*args, **kwargs):
            history, response_id = await original_history(*args, **kwargs)
            trimmed = []
            chars = 0
            for item in reversed(history[-AI_MEMORY_MAX_MESSAGES:]):
                content = str(item.get("content") or "")
                if chars + len(content) > AI_MEMORY_MAX_CHARS and trimmed:
                    break
                trimmed.append(item)
                chars += len(content)
            return list(reversed(trimmed)), response_id
        history_bounded._sentrix_mastery_bounded = True
        ai_service.get_conversation_history = history_bounded

    _AI_PATCHED = True
    logger.info("IA Mastery : mémoire bornée et circuit breaker texte/image activés.")


def _install_game_mastery(bot: commands.Bot) -> None:
    global _GAME_PATCHED
    if _GAME_PATCHED:
        return
    try:
        from utils import game_rewards
    except Exception:
        return
    original = game_rewards.reward_game_winner
    if getattr(original, "_sentrix_mastery_weekly", False):
        _GAME_PATCHED = True
        return

    async def reward_mastery(runtime_bot, guild_id, user_id, game_name, base_amount, session_id, result="win", metadata=None):
        adjusted = int(base_amount)
        try:
            if result == "win":
                cutoff = now() - 3600
                row = await runtime_bot.db.fetchone(
                    "SELECT COUNT(*) AS n FROM game_outcomes WHERE guild_id=? AND user_id=? AND result='win' AND created_at>=?",
                    (guild_id, user_id, cutoff),
                )
                wins_hour = int(row["n"] or 0) if row else 0
                if wins_hour >= GAME_HOURLY_SOFT_CAP:
                    factor = max(0.25, 1.0 - ((wins_hour - GAME_HOURLY_SOFT_CAP + 1) * 0.08))
                    adjusted = max(1, int(adjusted * factor))
        except Exception:
            adjusted = int(base_amount)

        reward = await original(
            runtime_bot, guild_id, user_id, game_name, adjusted, session_id,
            result=result, metadata=metadata,
        )
        if result != "win" or not getattr(reward, "success", False):
            return reward
        try:
            week = _week_key()
            await runtime_bot.db.execute(
                "INSERT INTO game_weekly_progress (guild_id,user_id,week,wins,claimed) VALUES (?,?,?,?,0) "
                "ON CONFLICT(guild_id,user_id,week) DO UPDATE SET wins=wins+1",
                (guild_id, user_id, week, 1),
            )
            row = await runtime_bot.db.fetchone(
                "SELECT wins,claimed FROM game_weekly_progress WHERE guild_id=? AND user_id=? AND week=?",
                (guild_id, user_id, week),
            )
            if row and int(row["wins"] or 0) >= GAME_WEEKLY_TARGET and not int(row["claimed"] or 0):
                await runtime_bot.db.add_balance(guild_id, user_id, GAME_WEEKLY_BONUS)
                await runtime_bot.db.execute(
                    "UPDATE game_weekly_progress SET claimed=1, claimed_at=? WHERE guild_id=? AND user_id=? AND week=?",
                    (now(), guild_id, user_id, week),
                )
                try:
                    reward.metadata["weekly_bonus"] = GAME_WEEKLY_BONUS
                    reward.metadata["weekly_target"] = GAME_WEEKLY_TARGET
                except Exception:
                    pass
        except Exception as exc:
            await _group_error(runtime_bot, "game_weekly", exc)
        return reward

    reward_mastery._sentrix_mastery_weekly = True
    game_rewards.reward_game_winner = reward_mastery
    _GAME_PATCHED = True
    logger.info("Jeux Mastery : défi hebdomadaire et anti-farm progressif activés.")


def _install_music_mastery(bot: commands.Bot) -> None:
    global _MUSIC_PATCHED
    if _MUSIC_PATCHED:
        return
    cog = bot.get_cog("Music")
    if cog is None:
        return
    cls = type(cog)
    original_extract = cls.ytdl_extract
    original_next = cls.play_next
    if getattr(original_extract, "_sentrix_mastery_music", False):
        _MUSIC_PATCHED = True
        return

    async def ytdl_safe(self, query: str):
        if await _api_is_open(self.bot, "youtube_audio"):
            raise RuntimeError("Service musique momentanément en récupération")
        last_exc = None
        for attempt in range(2):
            try:
                result = await asyncio.wait_for(original_extract(self, query), timeout=25)
                await _api_result(self.bot, "youtube_audio", True)
                return result
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    await asyncio.sleep(0.8)
        await _api_result(self.bot, "youtube_audio", False, type(last_exc).__name__ if last_exc else "unknown")
        if last_exc:
            raise last_exc
        raise RuntimeError("Extraction audio impossible")

    def play_next_safe(self, guild: discord.Guild):
        state = self.get_state(guild.id)
        before_queue = list(state.queue)
        before_current = state.current
        if state.voice_client is None or not state.voice_client.is_connected():
            return
        try:
            return original_next(self, guild)
        except Exception as exc:
            state.queue = before_queue
            state.current = before_current
            logger.warning("Lecture musique interrompue sur %s : %s", guild.id, type(exc).__name__)
            runtime = self.bot.get_cog(_COG_NAME)
            if runtime:
                asyncio.create_task(runtime._record_runtime_error("music_play_next", exc, guild.id))

    ytdl_safe._sentrix_mastery_music = True
    play_next_safe._sentrix_mastery_music = True
    cls.ytdl_extract = ytdl_safe
    cls.play_next = play_next_safe
    _MUSIC_PATCHED = True
    logger.info("Musique Mastery : retry, timeout, circuit breaker et lecture sûre activés.")


def _install_graceful_close(bot: commands.Bot) -> None:
    global _CLOSE_PATCHED
    if _CLOSE_PATCHED or getattr(bot, "_sentrix_mastery_close", False):
        return
    original_close = bot.close

    async def close_mastery(self):
        runtime = self.get_cog(_COG_NAME)
        if runtime is not None:
            try:
                await asyncio.wait_for(runtime.prepare_shutdown(), timeout=8)
            except Exception as exc:
                await _group_error(self, "graceful_shutdown", exc)
        return await original_close()

    bot.close = MethodType(close_mastery, bot)
    bot._sentrix_mastery_close = True
    _CLOSE_PATCHED = True
    logger.info("Arrêt gracieux Mastery activé.")


def _relancer_boucle(loop_obj: tasks.Loop) -> bool:
    """Remet réellement en marche une boucle morte ou bloquée.

    ``Loop.restart()`` ne relance PAS une boucle morte : discord.py le garde
    derrière ``_can_be_cancelled()``, qui exige une tâche encore vivante
    (``self._task and not self._task.done()``). Or une boucle qui a levé une
    exception a justement une tâche terminée. ``restart()`` y était donc un
    no-op silencieux — exactement dans le seul cas où le watchdog l'appelait.

    En production, ``Moderation.check_tempactions`` est ainsi restée morte
    pendant que le watchdog journalisait « Boucle de fond relancée » toutes les
    60 secondes sans que rien ne redémarre, et plus aucun bannissement
    temporaire n'expirait.

    Sur une tâche terminée, seul ``start()`` recrée la tâche — et il réarme au
    passage le drapeau d'échec que lit ``failed()``.
    """
    try:
        if loop_obj.is_running():
            loop_obj.restart()
        else:
            loop_obj.start()
    except RuntimeError:
        return False
    return loop_obj.is_running()


class BotMasteryRuntime(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._recent_messages: dict[tuple[int, int], deque[dict]] = defaultdict(lambda: deque(maxlen=8))
        self._member_activity: dict[tuple[int, int], float] = {}
        self._join_times: dict[int, deque[tuple[float, int, str]]] = defaultdict(deque)
        self._nuke_times: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._command_failures: dict[str, deque[float]] = defaultdict(deque)
        self._degraded_until: dict[str, float] = {}
        self._ticket_channels: dict[int, dict] = {}
        self._last_ticket_refresh = 0.0
        self._last_component_probe = 0.0
        self._last_db_maintenance = 0.0
        self._recovery_done = False
        self._shutting_down = False
        self.maintenance.start()

    def cog_unload(self):
        self.maintenance.cancel()

    @tasks.loop(seconds=60)
    async def maintenance(self):
        if self._shutting_down:
            return
        try:
            await self._refresh_ticket_cache()
            await self._ticket_reassignment_pass()
            await self._restart_stalled_loops()
            await self._recover_music_disconnects()
            await self._prune_runtime_memory()
            if time.monotonic() - self._last_component_probe >= COMPONENT_PROBE_INTERVAL:
                self._last_component_probe = time.monotonic()
                await self._probe_components()
            if time.monotonic() - self._last_db_maintenance >= DB_MAINTENANCE_INTERVAL:
                self._last_db_maintenance = time.monotonic()
                await self._database_maintenance()
        except Exception as exc:
            await self._record_runtime_error("mastery_maintenance", exc, None)

    @maintenance.before_loop
    async def before_maintenance(self):
        await self.bot.wait_until_ready()

    async def prepare_shutdown(self) -> None:
        self._shutting_down = True
        try:
            await self._persist_all_music()
        except Exception as exc:
            await self._record_runtime_error("shutdown_music", exc, None)
        try:
            conn = getattr(getattr(self.bot, "db", None), "_conn", None)
            if conn is not None:
                await conn.commit()
                try:
                    await conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    await conn.commit()
                except Exception:
                    pass
            await _safe_execute(
                self.bot,
                "INSERT INTO shutdown_state (key,value,updated_at) VALUES ('last_shutdown','clean',?) "
                "ON CONFLICT(key) DO UPDATE SET value='clean', updated_at=excluded.updated_at",
                (now(),),
            )
        finally:
            logger.info("Arrêt gracieux : états critiques et base synchronisés.")

    async def _mark_startup_dirty(self) -> None:
        await _safe_execute(
            self.bot,
            "INSERT INTO shutdown_state (key,value,updated_at) VALUES ('last_shutdown','running',?) "
            "ON CONFLICT(key) DO UPDATE SET value='running', updated_at=excluded.updated_at",
            (now(),),
        )

    def _snapshot_message(self, message: discord.Message) -> dict:
        return {
            "message_id": int(message.id),
            "channel_id": int(message.channel.id),
            "content": (message.content or "")[:1800],
            "attachments": [a.url for a in message.attachments[:8]],
            "created_at": int(message.created_at.timestamp()) if message.created_at else now(),
        }

    def _sanction_advice(self, action: str, total: int) -> str | None:
        if action not in {"warn", "mute"}:
            return None
        if total >= 7:
            return "Historique très élevé : vérifiez le dossier complet avant d'envisager un bannissement."
        if total >= 5:
            return "Récidive importante : une expulsion ou une sanction longue peut être plus adaptée."
        if total >= 3:
            return "Récidive détectée : un mute temporaire peut être plus adapté qu'un nouvel avertissement."
        return None

    async def _record_runtime_error(self, source: str, error: BaseException, guild_id: int | None):
        await _group_error(self.bot, source, error)
        await _safe_execute(
            self.bot,
            "INSERT INTO command_diagnostics (guild_id,user_id,command_name,category,detail,created_at) VALUES (?,?,?,?,?,?)",
            (guild_id, None, source[:120], "runtime", f"{type(error).__name__}: {str(error)[:600]}", now()),
        )

    async def _refresh_ticket_cache(self):
        if time.monotonic() - self._last_ticket_refresh < 45:
            return
        self._last_ticket_refresh = time.monotonic()
        try:
            rows = await self.bot.db.fetchall(
                "SELECT id,guild_id,channel_id,user_id,priority,claimed_by,last_activity_at FROM tickets WHERE status='ouvert'"
            )
            self._ticket_channels = {int(row["channel_id"]): dict(row) for row in rows if row["channel_id"]}
        except Exception as exc:
            await self._record_runtime_error("ticket_cache", exc, None)

    async def _ticket_reassignment_pass(self):
        ts = now()
        for channel_id, ticket in list(self._ticket_channels.items()):
            claimed_by = ticket.get("claimed_by")
            if not claimed_by:
                continue
            guild = self.bot.get_guild(int(ticket["guild_id"]))
            if guild is None:
                continue
            member = guild.get_member(int(claimed_by))
            last_seen = self._member_activity.get((guild.id, int(claimed_by)), 0.0)
            user_activity = int(ticket.get("last_activity_at") or 0)
            abandoned = member is None or (
                user_activity and ts - user_activity >= TICKET_REASSIGN_SECONDS and
                (not last_seen or time.monotonic() - last_seen >= TICKET_REASSIGN_SECONDS)
            )
            if not abandoned:
                continue
            row = await self.bot.db.fetchone("SELECT reassigned_count FROM ticket_mastery_state WHERE ticket_id=?", (ticket["id"],))
            if row and int(row["reassigned_count"] or 0) >= 2:
                continue
            await self.bot.db.execute("UPDATE tickets SET claimed_by=NULL WHERE id=?", (ticket["id"],))
            await self.bot.db.execute(
                "INSERT INTO ticket_mastery_state (ticket_id,priority,last_claimed_by,claim_last_seen,reassigned_count,updated_at) "
                "VALUES (?,?,?,?,1,?) ON CONFLICT(ticket_id) DO UPDATE SET last_claimed_by=excluded.last_claimed_by, "
                "reassigned_count=reassigned_count+1, updated_at=excluded.updated_at",
                (ticket["id"], ticket.get("priority") or "normale", claimed_by, int(last_seen or 0), ts),
            )
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                try:
                    await channel.send("Ce ticket a été remis dans la file staff car sa prise en charge était inactive.")
                except discord.HTTPException:
                    pass
            ticket["claimed_by"] = None

    async def _priority_from_message(self, message: discord.Message, ticket: dict):
        if message.author.bot or message.author.id != int(ticket.get("user_id") or 0):
            return
        content = (message.content or "").casefold()
        priority = "urgente" if any(word in content for word in URGENT_TICKET_WORDS) else (ticket.get("priority") or "normale")
        if priority != ticket.get("priority"):
            await self.bot.db.execute("UPDATE tickets SET priority=? WHERE id=?", (priority, ticket["id"]))
            ticket["priority"] = priority
        await self.bot.db.execute(
            "INSERT INTO ticket_mastery_state (ticket_id,priority,last_claimed_by,claim_last_seen,reassigned_count,updated_at) "
            "VALUES (?,?,?,?,0,?) ON CONFLICT(ticket_id) DO UPDATE SET priority=excluded.priority, updated_at=excluded.updated_at",
            (ticket["id"], priority, ticket.get("claimed_by"), 0, now()),
        )

    async def _restart_stalled_loops(self):
        now_dt = datetime.now(timezone.utc)
        for cog in list(self.bot.cogs.values()):
            for name in dir(cog):
                if not (name.startswith("check_") or any(k in name for k in ("reminder", "cleanup", "snapshot", "notification", "monitor"))):
                    continue
                try:
                    loop_obj = getattr(cog, name)
                except Exception:
                    continue
                if not isinstance(loop_obj, tasks.Loop):
                    continue
                try:
                    if loop_obj.failed() or not loop_obj.is_running():
                        if _relancer_boucle(loop_obj):
                            logger.warning("Boucle de fond relancée : %s.%s", cog.qualified_name, name)
                        else:
                            logger.error(
                                "Boucle de fond morte et impossible à relancer : %s.%s",
                                cog.qualified_name,
                                name,
                            )
                        continue
                    nxt = loop_obj.next_iteration
                    seconds = float(loop_obj.seconds or 0) + float(loop_obj.minutes or 0) * 60 + float(loop_obj.hours or 0) * 3600
                    threshold = max(300.0, seconds * 3 + 60)
                    if nxt and (now_dt - nxt).total_seconds() > threshold:
                        if _relancer_boucle(loop_obj):
                            logger.warning("Boucle silencieusement bloquée relancée : %s.%s", cog.qualified_name, name)
                except Exception:
                    continue

    async def _probe_components(self):
        probes = (
            ("self_role", "SELECT guild_id,channel_id,message_id FROM self_role_panels ORDER BY created_at DESC LIMIT 30"),
            ("shop", "SELECT guild_id,channel_id,message_id FROM shop_panels ORDER BY created_at DESC LIMIT 30"),
            ("reaction_role", "SELECT guild_id,channel_id,message_id FROM reaction_role_panels ORDER BY id DESC LIMIT 30"),
            ("ticket", "SELECT guild_id,channel_id,message_id FROM ticket_panels_v2 ORDER BY id DESC LIMIT 30"),
        )
        for kind, sql in probes:
            try:
                rows = await self.bot.db.fetchall(sql)
            except Exception:
                continue
            for row in rows:
                guild = self.bot.get_guild(int(row["guild_id"]))
                channel = guild.get_channel(int(row["channel_id"])) if guild else None
                status, detail = "ok", "composants présents"
                if not isinstance(channel, discord.abc.Messageable):
                    status, detail = "missing_channel", "salon introuvable"
                else:
                    try:
                        message = await channel.fetch_message(int(row["message_id"]))
                        if not message.components:
                            status, detail = "missing_components", "message sans composant"
                    except discord.NotFound:
                        status, detail = "missing_message", "message supprimé"
                    except discord.HTTPException as exc:
                        status, detail = "http_error", type(exc).__name__
                await _safe_execute(
                    self.bot,
                    "INSERT INTO component_probe_results (guild_id,component_type,message_id,status,detail,created_at) VALUES (?,?,?,?,?,?)",
                    (int(row["guild_id"]), kind, int(row["message_id"]), status, detail, now()),
                )
        try:
            tickets = self.bot.get_cog("Tickets")
            if tickets and hasattr(tickets, "restore_panel_views"):
                await tickets.restore_panel_views()
        except Exception as exc:
            await self._record_runtime_error("component_restore", exc, None)

    async def _database_maintenance(self):
        status, detail = "ok", "quick_check ok"
        try:
            row = await self.bot.db.fetchone("PRAGMA quick_check")
            if row:
                value = list(dict(row).values())[0] if hasattr(row, "keys") else row[0]
                if str(value).casefold() != "ok":
                    status, detail = "warning", str(value)[:500]
            cutoffs = [
                ("runtime_incidents", "created_at", 14 * 86400),
                ("command_diagnostics", "created_at", 14 * 86400),
                ("component_probe_results", "created_at", 14 * 86400),
                ("mastery_join_risk", "created_at", 14 * 86400),
                ("mastery_nuke_actions", "created_at", 7 * 86400),
                ("economy_transfer_events", "created_at", 30 * 86400),
            ]
            for table, column, age in cutoffs:
                await self.bot.db.execute(f"DELETE FROM {table} WHERE {column} < ?", (now() - age,))
            conn = getattr(self.bot.db, "_conn", None)
            if conn is not None:
                await conn.execute("PRAGMA optimize")
                await conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                await conn.commit()
        except Exception as exc:
            status, detail = "error", f"{type(exc).__name__}: {str(exc)[:400]}"
            await _group_error(self.bot, "database_maintenance", exc)
        await _safe_execute(
            self.bot,
            "INSERT INTO database_health (status,detail,created_at) VALUES (?,?,?)",
            (status, detail, now()),
        )

    async def _persist_music(self, guild_id: int):
        music = self.bot.get_cog("Music")
        if music is None:
            return
        state = music.states.get(guild_id)
        if state is None:
            return
        channel_id = None
        if state.voice_client and getattr(state.voice_client, "channel", None):
            channel_id = state.voice_client.channel.id
        elif getattr(state, "_sentrix_last_channel_id", None):
            channel_id = state._sentrix_last_channel_id
        await self.bot.db.execute(
            "INSERT INTO music_recovery_state (guild_id,channel_id,current_json,queue_json,volume,loop_enabled,updated_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, "
            "current_json=excluded.current_json, queue_json=excluded.queue_json, volume=excluded.volume, "
            "loop_enabled=excluded.loop_enabled, updated_at=excluded.updated_at",
            (
                guild_id, channel_id, json.dumps(state.current) if state.current else None,
                json.dumps(state.queue or []), float(state.volume), int(bool(state.loop)), now(),
            ),
        )

    async def _persist_all_music(self):
        music = self.bot.get_cog("Music")
        if music is None:
            return
        for guild_id in list(music.states):
            await self._persist_music(guild_id)

    async def _restore_music(self):
        music = self.bot.get_cog("Music")
        if music is None:
            return
        rows = await self.bot.db.fetchall("SELECT * FROM music_recovery_state WHERE updated_at >= ?", (now() - 3600,))
        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                continue
            state = music.get_state(guild.id)
            try:
                state.current = json.loads(row["current_json"]) if row["current_json"] else None
                state.queue = json.loads(row["queue_json"] or "[]")
            except Exception:
                state.current, state.queue = None, []
            state.volume = float(row["volume"] or 0.5)
            state.loop = bool(row["loop_enabled"])
            state._sentrix_last_channel_id = int(row["channel_id"]) if row["channel_id"] else None
            if not (state.current or state.queue) or not state._sentrix_last_channel_id:
                continue
            channel = guild.get_channel(state._sentrix_last_channel_id)
            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                continue
            perms = channel.permissions_for(guild.me)
            if not perms.connect:
                continue
            try:
                state.voice_client = await channel.connect(reconnect=True, timeout=10)
                if state.current:
                    state.queue.insert(0, state.current)
                    state.current = None
                music.play_next(guild)
            except Exception as exc:
                await self._record_runtime_error("music_restore", exc, guild.id)

    async def _recover_music_disconnects(self):
        music = self.bot.get_cog("Music")
        if music is None:
            return
        for guild_id, state in list(music.states.items()):
            if not (state.current or state.queue):
                continue
            if state.voice_client and state.voice_client.is_connected():
                continue
            channel_id = getattr(state, "_sentrix_last_channel_id", None)
            guild = self.bot.get_guild(guild_id)
            channel = guild.get_channel(channel_id) if guild and channel_id else None
            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                continue
            try:
                state.voice_client = await channel.connect(reconnect=True, timeout=10)
                if state.current:
                    state.queue.insert(0, state.current)
                    state.current = None
                music.play_next(guild)
            except Exception:
                continue

    async def _recover_after_restart(self):
        if self._recovery_done:
            return
        self._recovery_done = True
        try:
            await self._mark_startup_dirty()
            await self._restart_stalled_loops()
            tickets = self.bot.get_cog("Tickets")
            if tickets and hasattr(tickets, "restore_panel_views"):
                await tickets.restore_panel_views()
            await self._restore_music()
            await self._refresh_ticket_cache()
            logger.info("Recovery Mastery terminé : boucles, panels, tickets et musique vérifiés.")
        except Exception as exc:
            await self._record_runtime_error("startup_recovery", exc, None)

    async def _prune_runtime_memory(self):
        cutoff = time.monotonic() - 7200
        for key, value in list(self._member_activity.items()):
            if value < cutoff:
                self._member_activity.pop(key, None)
        for guild_id, dq in list(self._join_times.items()):
            while dq and dq[0][0] < time.monotonic() - JOIN_RECENT_NAME_SECONDS:
                dq.popleft()
            if not dq:
                self._join_times.pop(guild_id, None)
        for name, dq in list(self._command_failures.items()):
            while dq and dq[0] < time.monotonic() - COMMAND_FAILURE_WINDOW:
                dq.popleft()
            if not dq:
                self._command_failures.pop(name, None)

    async def _actor_for(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int | None):
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return None, None
        try:
            conf = await automod.get_automod_cached(guild.id)
            if not conf or not conf.get("antinuke"):
                return automod, None
            actor = await automod.get_audit_actor(guild, action, target_id)
            if actor is None:
                return automod, None
            if await automod.is_antinuke_exempt(guild, actor):
                return automod, None
            return automod, actor
        except Exception:
            return automod, None

    async def _record_nuke(self, guild: discord.Guild, actor_id: int, action_type: str, target_id: int | None, payload: dict):
        ts = now()
        await self.bot.db.execute(
            "INSERT INTO mastery_nuke_actions (guild_id,actor_id,action_type,target_id,payload_json,created_at,handled) VALUES (?,?,?,?,?,?,0)",
            (guild.id, actor_id, action_type, target_id, json.dumps(payload, ensure_ascii=False), ts),
        )
        key = (guild.id, actor_id)
        dq = self._nuke_times[key]
        mono = time.monotonic()
        dq.append(mono)
        while dq and dq[0] < mono - NUKE_WINDOW_SECONDS:
            dq.popleft()
        return len(dq) >= NUKE_THRESHOLD

    async def _rollback_nuke_v3(self, guild: discord.Guild, actor_id: int):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM mastery_nuke_actions WHERE guild_id=? AND actor_id=? AND handled=0 AND created_at>=? ORDER BY id DESC LIMIT 50",
            (guild.id, actor_id, now() - NUKE_WINDOW_SECONDS - 10),
        )
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
                action = row["action_type"]
                target_id = int(row["target_id"]) if row["target_id"] else None
                if action == "role_create" and target_id:
                    role = guild.get_role(target_id)
                    if role and role < guild.me.top_role:
                        await role.delete(reason="Rollback anti-nuke SentriX V3")
                elif action == "role_delete":
                    role = await guild.create_role(
                        name=payload.get("name", "restored-role")[:100],
                        permissions=discord.Permissions(int(payload.get("permissions", 0))),
                        colour=discord.Colour(int(payload.get("colour", 0))),
                        hoist=bool(payload.get("hoist")), mentionable=bool(payload.get("mentionable")),
                        reason="Rollback anti-nuke SentriX V3",
                    )
                    try:
                        await guild.edit_role_positions(positions={role: int(payload.get("position", 1))})
                    except Exception:
                        pass
                elif action == "role_update" and target_id:
                    role = guild.get_role(target_id)
                    if role and role < guild.me.top_role:
                        await role.edit(
                            name=payload.get("name", role.name),
                            permissions=discord.Permissions(int(payload.get("permissions", role.permissions.value))),
                            colour=discord.Colour(int(payload.get("colour", role.colour.value))),
                            hoist=bool(payload.get("hoist", role.hoist)),
                            mentionable=bool(payload.get("mentionable", role.mentionable)),
                            reason="Rollback anti-nuke SentriX V3",
                        )
                elif action == "guild_update":
                    kwargs = {}
                    if payload.get("name"):
                        kwargs["name"] = payload["name"]
                    verification = payload.get("verification_level")
                    if verification is not None:
                        try:
                            kwargs["verification_level"] = discord.VerificationLevel(int(verification))
                        except Exception:
                            pass
                    if kwargs:
                        await guild.edit(reason="Rollback anti-nuke SentriX V3", **kwargs)
                elif action == "webhook_create" and target_id:
                    for channel in guild.text_channels[:100]:
                        try:
                            hooks = await channel.webhooks()
                        except discord.HTTPException:
                            continue
                        hook = discord.utils.get(hooks, id=target_id)
                        if hook:
                            await hook.delete(reason="Rollback anti-nuke SentriX V3")
                            break
            except Exception as exc:
                await self._record_runtime_error("antinuke_v3_rollback", exc, guild.id)
            finally:
                await self.bot.db.execute("UPDATE mastery_nuke_actions SET handled=1 WHERE id=?", (row["id"],))

    async def _trigger_nuke(self, automod, guild: discord.Guild, actor_id: int, reason: str):
        await self._rollback_nuke_v3(guild, actor_id)
        try:
            await automod.punish_nuker(guild, actor_id, reason)
        except Exception as exc:
            await self._record_runtime_error("antinuke_v3_punish", exc, guild.id)

    async def _economy_abuse_check(self, guild_id: int, user_id: int):
        cutoff = now() - 600
        rows = await self.bot.db.fetchall(
            "SELECT sender_id,receiver_id,amount,created_at FROM economy_transactions "
            "WHERE guild_id=? AND created_at>=? AND (sender_id=? OR receiver_id=?) ORDER BY created_at DESC LIMIT 40",
            (guild_id, cutoff, user_id, user_id),
        )
        outgoing = [r for r in rows if r["sender_id"] == user_id and r["receiver_id"]]
        score = 0
        if len(outgoing) >= 8:
            score += 3
        pairs = defaultdict(int)
        for row in rows:
            s, r = row["sender_id"], row["receiver_id"]
            if s and r:
                pairs[(int(s), int(r))] += 1
        for (a, b), count in pairs.items():
            if a == user_id and count >= 2 and pairs.get((b, a), 0) >= 2:
                score += 3
                break
        if outgoing and sum(abs(int(r["amount"] or 0)) for r in outgoing) >= 1_000_000:
            score += 2
        blocked_until = now() + ECONOMY_ABUSE_BLOCK_SECONDS if score >= 5 else 0
        await self.bot.db.execute(
            "INSERT INTO economy_abuse_state (guild_id,user_id,score,blocked_until,updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET score=excluded.score, blocked_until=excluded.blocked_until, updated_at=excluded.updated_at",
            (guild_id, user_id, score, blocked_until, now()),
        )

    async def _degraded_check(self, ctx: commands.Context) -> bool:
        if ctx.command is None:
            return True
        root = ctx.command.root_parent or ctx.command
        name = root.name.casefold()
        if name in CRITICAL_COMMANDS:
            return True
        until = self._degraded_until.get(name, 0.0)
        if until > time.monotonic():
            raise MasteryDegradedError("Cette fonction se remet automatiquement d'une série d'erreurs. Réessayez dans quelques instants.")
        if ctx.guild and name in {"pay", "rob", "gamble"}:
            row = await self.bot.db.fetchone(
                "SELECT blocked_until FROM economy_abuse_state WHERE guild_id=? AND user_id=?",
                (ctx.guild.id, ctx.author.id),
            )
            if row and int(row["blocked_until"] or 0) > now():
                raise MasteryDegradedError("Les actions économiques sensibles sont temporairement limitées après une activité inhabituelle.")
        return True

    @commands.Cog.listener()
    async def on_ready(self):
        await self._recover_after_restart()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        self._member_activity[(message.guild.id, message.author.id)] = time.monotonic()
        self._recent_messages[(message.guild.id, message.author.id)].append(self._snapshot_message(message))
        ticket = self._ticket_channels.get(message.channel.id)
        if ticket:
            try:
                await self._priority_from_message(message, ticket)
            except Exception as exc:
                await self._record_runtime_error("ticket_priority", exc, message.guild.id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot and member.guild.me and member.id == member.guild.me.id:
            return
        guild = member.guild
        automod = self.bot.get_cog("Automod")
        conf = None
        if automod:
            try:
                conf = await automod.get_automod_cached(guild.id)
            except Exception:
                conf = None
        score = 0
        reasons = []
        if conf and conf.get("antiraid"):
            age = datetime.now(timezone.utc) - member.created_at
            if age < timedelta(hours=2):
                score += 3; reasons.append("compte de moins de 2 heures")
            elif age < timedelta(days=1):
                score += 2; reasons.append("compte de moins de 24 heures")
            elif age < timedelta(days=7):
                score += 1; reasons.append("compte récent")
            if member.bot:
                score += 3; reasons.append("bot pendant une vague")
            dq = self._join_times[guild.id]
            mono = time.monotonic()
            name_key = re.sub(r"[^a-z0-9]", "", member.display_name.casefold())[:24]
            dq.append((mono, member.id, name_key))
            while dq and dq[0][0] < mono - JOIN_RECENT_NAME_SECONDS:
                dq.popleft()
            burst = sum(1 for t, _, _ in dq if t >= mono - JOIN_WINDOW_SECONDS)
            if burst >= 10:
                score += 5; reasons.append(f"vague de {burst} arrivées")
            elif burst >= 6:
                score += 3; reasons.append(f"afflux de {burst} arrivées")
            similar = sum(1 for _, uid, key in dq if uid != member.id and key and key == name_key)
            if similar >= 2:
                score += 2; reasons.append("noms très similaires dans la vague")
            action = "none"
            if score >= 7 and guild.me.guild_permissions.moderate_members and member < guild.me.top_role:
                try:
                    await member.timeout(timedelta(seconds=JOIN_RISK_TIMEOUT_SECONDS), reason="Anti-raid SentriX : quarantaine de vérification")
                    action = "timeout_quarantine"
                    try:
                        await helpers.send_log(
                            self.bot, guild, "automod",
                            discord.Embed(
                                title="Anti-raid : quarantaine préventive",
                                description=f"{member.mention} a été isolé 10 minutes. Score {score}/10.\n" + ", ".join(reasons),
                                color=discord.Color.orange(),
                            ),
                        )
                    except Exception:
                        pass
                except discord.HTTPException:
                    action = "quarantine_failed"
            await self.bot.db.execute(
                "INSERT INTO mastery_join_risk (guild_id,user_id,score,reasons_json,action,created_at) VALUES (?,?,?,?,?,?)",
                (guild.id, member.id, score, json.dumps(reasons, ensure_ascii=False), action, now()),
            )
        await self._send_onboarding(member)

    async def _send_onboarding(self, member: discord.Member):
        try:
            conf = await self.bot.db.get_guild_config(member.guild.id)
            if not conf:
                return
            rules_id = conf["rules_channel"] if "rules_channel" in conf.keys() else None
            verify_id = conf["verification_channel"] if "verification_channel" in conf.keys() else None
            if not rules_id and not verify_id:
                return
            links = []
            if rules_id:
                links.append(f"Règlement : https://discord.com/channels/{member.guild.id}/{int(rules_id)}")
            if verify_id:
                links.append(f"Vérification : https://discord.com/channels/{member.guild.id}/{int(verify_id)}")
            text = (
                f"Bienvenue sur {member.guild.name}.\n" + "\n".join(links) +
                "\n\nCommence par le règlement puis la vérification. Une fois vérifié, SentriX t'indiquera la suite dans un seul message."
            )
            await member.send(text[:1900], allowed_mentions=discord.AllowedMentions.none())
            await self.bot.db.execute(
                "INSERT INTO onboarding_state (guild_id,user_id,stage,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET stage=excluded.stage,updated_at=excluded.updated_at",
                (member.guild.id, member.id, "welcome_sent", now()),
            )
        except discord.HTTPException:
            return
        except Exception as exc:
            await self._record_runtime_error("onboarding_join", exc, member.guild.id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.roles == after.roles:
            return
        try:
            conf = await self.bot.db.get_guild_config(after.guild.id)
            if not conf:
                return
            verify_role = None
            for key in ("verify_role", "verification_role"):
                try:
                    if conf[key]:
                        verify_role = int(conf[key]); break
                except Exception:
                    pass
            if not verify_role or verify_role in _member_role_ids(before) or verify_role not in _member_role_ids(after):
                return
            state = await self.bot.db.fetchone(
                "SELECT stage FROM onboarding_state WHERE guild_id=? AND user_id=?",
                (after.guild.id, after.id),
            )
            if state and state["stage"] == "verified_sent":
                return
            row = await self.bot.db.fetchone(
                "SELECT channel_id FROM self_role_panels WHERE guild_id=? ORDER BY created_at DESC LIMIT 1",
                (after.guild.id,),
            )
            extra = ""
            if row and row["channel_id"]:
                extra = f"\nChoix de rôles : https://discord.com/channels/{after.guild.id}/{int(row['channel_id'])}"
            await after.send(
                f'Votre vérification sur {after.guild.name} est terminée.{extra}\nPour découvrir les commandes utiles, utilise +help.',
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.bot.db.execute(
                "INSERT INTO onboarding_state (guild_id,user_id,stage,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET stage=excluded.stage,updated_at=excluded.updated_at",
                (after.guild.id, after.id, "verified_sent", now()),
            )
        except discord.HTTPException:
            pass
        except Exception as exc:
            await self._record_runtime_error("onboarding_verified", exc, after.guild.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        automod, actor = await self._actor_for(role.guild, discord.AuditLogAction.role_delete, role.id)
        if actor is None:
            return
        if await self._record_nuke(role.guild, actor.id, "role_delete", role.id, _role_payload(role)):
            await self._trigger_nuke(automod, role.guild, actor.id, "Suppression massive de rôles")

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        automod, actor = await self._actor_for(role.guild, discord.AuditLogAction.role_create, role.id)
        if actor is None:
            return
        if await self._record_nuke(role.guild, actor.id, "role_create", role.id, _role_payload(role)):
            await self._trigger_nuke(automod, role.guild, actor.id, "Création massive de rôles")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        if before.permissions == after.permissions and before.name == after.name and before.colour == after.colour and before.hoist == after.hoist:
            return
        automod, actor = await self._actor_for(after.guild, discord.AuditLogAction.role_update, after.id)
        if actor is None:
            return
        if await self._record_nuke(after.guild, actor.id, "role_update", after.id, _role_payload(before)):
            await self._trigger_nuke(automod, after.guild, actor.id, "Modification massive de rôles ou permissions")

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        changed = before.name != after.name or before.verification_level != after.verification_level
        if not changed:
            return
        automod, actor = await self._actor_for(after, discord.AuditLogAction.guild_update, after.id)
        if actor is None:
            return
        payload = {"name": before.name, "verification_level": int(before.verification_level.value)}
        if await self._record_nuke(after, actor.id, "guild_update", after.id, payload):
            await self._trigger_nuke(automod, after, actor.id, "Modification massive des paramètres du serveur")

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return
        try:
            conf = await automod.get_automod_cached(guild.id)
            if not conf or not conf.get("antinuke"):
                return
            for action in (discord.AuditLogAction.webhook_create, discord.AuditLogAction.webhook_update, discord.AuditLogAction.webhook_delete):
                entry = None
                async for candidate in guild.audit_logs(limit=2, action=action):
                    if (datetime.now(timezone.utc) - candidate.created_at).total_seconds() <= 8:
                        entry = candidate; break
                if not entry or not entry.user:
                    continue
                actor = guild.get_member(entry.user.id) or entry.user
                if await automod.is_antinuke_exempt(guild, actor):
                    continue
                target_id = getattr(entry.target, "id", None)
                kind = "webhook_create" if action == discord.AuditLogAction.webhook_create else "webhook_change"
                if await self._record_nuke(guild, actor.id, kind, target_id, {"channel_id": channel.id}):
                    await self._trigger_nuke(automod, guild, actor.id, "Modification massive de webhooks")
                return
        except (discord.Forbidden, discord.HTTPException):
            return
        except Exception as exc:
            await self._record_runtime_error("webhook_antinuke", exc, guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        guild = member.guild
        automod = self.bot.get_cog("Automod")
        if automod is None:
            return
        try:
            conf = await automod.get_automod_cached(guild.id)
            if not conf or not conf.get("antinuke"):
                return
            entry = None
            async for candidate in guild.audit_logs(limit=3, action=discord.AuditLogAction.kick):
                if getattr(candidate.target, "id", None) == member.id and (datetime.now(timezone.utc) - candidate.created_at).total_seconds() <= 8:
                    entry = candidate; break
            if not entry or not entry.user:
                return
            actor = guild.get_member(entry.user.id) or entry.user
            if await automod.is_antinuke_exempt(guild, actor):
                return
            if await self._record_nuke(guild, actor.id, "kick", member.id, {"user_id": member.id}):
                await self._trigger_nuke(automod, guild, actor.id, "Expulsions massives de membres")
        except (discord.Forbidden, discord.HTTPException):
            return

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not self.bot.user or member.id != self.bot.user.id:
            return
        music = self.bot.get_cog("Music")
        if music is None:
            return
        state = music.states.get(member.guild.id)
        if state is None:
            return
        if after.channel:
            state._sentrix_last_channel_id = after.channel.id
            await self._persist_music(member.guild.id)
        elif before.channel and (state.current or state.queue):
            state._sentrix_last_channel_id = before.channel.id
            asyncio.create_task(self._delayed_music_reconnect(member.guild.id))

    async def _delayed_music_reconnect(self, guild_id: int):
        await asyncio.sleep(3)
        await self._recover_music_disconnects()

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        if ctx.guild is None or ctx.command is None:
            return
        root = ctx.command.root_parent or ctx.command
        name = root.name.casefold()
        self._member_activity[(ctx.guild.id, ctx.author.id)] = time.monotonic()
        if name in MUSIC_COMMANDS:
            try:
                music = self.bot.get_cog("Music")
                if music:
                    state = music.states.get(ctx.guild.id)
                    if state and isinstance(ctx.author, discord.Member) and ctx.author.voice and ctx.author.voice.channel:
                        state._sentrix_last_channel_id = ctx.author.voice.channel.id
                await self._persist_music(ctx.guild.id)
            except Exception as exc:
                await self._record_runtime_error("music_persist", exc, ctx.guild.id)
        if name in MONEY_COMMANDS:
            try:
                await self._economy_abuse_check(ctx.guild.id, ctx.author.id)
            except Exception as exc:
                await self._record_runtime_error("economy_abuse", exc, ctx.guild.id)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        root = ctx.command.root_parent if ctx.command and ctx.command.root_parent else ctx.command
        name = root.name.casefold() if root else "unknown"
        original = getattr(error, "original", error)
        if isinstance(error, commands.CommandOnCooldown):
            category = "cooldown"
        elif isinstance(error, commands.MissingPermissions):
            category = "user_permission"
        elif isinstance(error, commands.BotMissingPermissions):
            category = "bot_permission"
        elif isinstance(original, discord.Forbidden):
            category = "discord_permission_or_hierarchy"
        elif isinstance(original, discord.HTTPException):
            category = "discord_api"
        elif isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            category = "usage"
        elif isinstance(error, MasteryDegradedError):
            category = "degraded"
        else:
            category = "unexpected"
        await _safe_execute(
            self.bot,
            "INSERT INTO command_diagnostics (guild_id,user_id,command_name,category,detail,created_at) VALUES (?,?,?,?,?,?)",
            (
                ctx.guild.id if ctx.guild else None, ctx.author.id if ctx.author else None,
                name, category, f"{type(original).__name__}: {str(original)[:600]}", now(),
            ),
        )
        if category == "unexpected":
            await _group_error(self.bot, f"command:{name}", original)
            if name not in CRITICAL_COMMANDS:
                dq = self._command_failures[name]
                mono = time.monotonic()
                dq.append(mono)
                while dq and dq[0] < mono - COMMAND_FAILURE_WINDOW:
                    dq.popleft()
                if len(dq) >= COMMAND_FAILURE_THRESHOLD:
                    until = mono + DEGRADED_SECONDS
                    self._degraded_until[name] = until
                    await _safe_execute(
                        self.bot,
                        "INSERT INTO runtime_module_state (module,state,failures,opened_until,last_seen) VALUES (?,?,?,?,?) "
                        "ON CONFLICT(module) DO UPDATE SET state=excluded.state,failures=excluded.failures,opened_until=excluded.opened_until,last_seen=excluded.last_seen",
                        (name, "degraded", len(dq), now() + DEGRADED_SECONDS, now()),
                    )


async def install(bot: commands.Bot, extension_name: str = "") -> None:
    """Installation idempotente appelée après chaque extension par stability_runtime."""
    await _ensure_schema(bot)
    runtime = bot.get_cog(_COG_NAME)
    if runtime is None:
        runtime = BotMasteryRuntime(bot)
        await bot.add_cog(runtime)
        bot.add_check(runtime._degraded_check)
        logger.info("Bot Mastery Runtime chargé sans nouvelle racine de commande.")
    _install_access_check(bot)
    _install_security_subcommands(bot)
    _install_moderation_evidence(bot)
    _install_ai_mastery(bot)
    _install_game_mastery(bot)
    _install_music_mastery(bot)
    _install_graceful_close(bot)
