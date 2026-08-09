"""SentriX Production Readiness — configuration, rétention et infrastructure.

Cette couche complète les runtimes existants sans ajouter de nouvelle commande racine.
Elle fournit sous +security :
- readiness : audit déterministe 0-100 de la configuration du serveur ;
- infra : état PostgreSQL durable, Redis, sauvegarde externe et canary ;
- retention : politique de conservation et purge périodique des données temporaires ;
- privacy : export ou suppression contrôlée des données personnelles d'un membre.

Elle orchestre aussi les snapshots PostgreSQL de la base principale avec un lease Redis,
et conserve les audits pour suivre la qualité de configuration dans le temps.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from typing import Any

import discord
from discord.ext import commands, tasks

from database.db import now

logger = logging.getLogger("bot.production-readiness")
_COG_NAME = "ProductionReadinessRuntime"

READINESS_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_readiness_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    findings_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guild_readiness_time
ON guild_readiness_audits (guild_id, created_at DESC);

CREATE TABLE IF NOT EXISTS retention_policies (
    guild_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    days INTEGER NOT NULL,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, category)
);

CREATE TABLE IF NOT EXISTS retention_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    deleted_rows INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS privacy_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    target_user_id INTEGER NOT NULL,
    actor_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    affected_rows INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS production_readiness_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at INTEGER NOT NULL
);
"""

RETENTION_DEFAULTS = {
    "transcripts": ("SENTRIX_RETENTION_TRANSCRIPTS_DAYS", 180),
    "evidence": ("SENTRIX_RETENTION_EVIDENCE_DAYS", 365),
    "diagnostics": ("SENTRIX_RETENTION_DIAGNOSTICS_DAYS", 30),
    "analytics": ("SENTRIX_RETENTION_ANALYTICS_DAYS", 180),
    "appeals": ("SENTRIX_RETENTION_APPEALS_DAYS", 365),
}

# Tables temporaires/volumineuses uniquement. Les sanctions et warnings ne sont jamais
# supprimés automatiquement : ce sont des dossiers de modération durables.
RETENTION_TARGETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ticket_transcripts_v2": ("transcripts", ("created_at", "closed_at", "updated_at")),
    "moderation_evidence": ("evidence", ("created_at",)),
    "command_diagnostics": ("diagnostics", ("created_at",)),
    "component_probe_results": ("diagnostics", ("created_at",)),
    "database_health": ("diagnostics", ("created_at",)),
    "runtime_incidents": ("diagnostics", ("created_at", "last_seen")),
    "runtime_health_snapshots": ("diagnostics", ("created_at",)),
    "runtime_metrics_v2": ("analytics", ("created_at",)),
    "message_activity_hourly": ("analytics", ("hour_bucket",)),
    "server_stat_snapshots_v2": ("analytics", ("created_at",)),
    "growth_snapshots": ("analytics", ("timestamp",)),
    "command_logs": ("analytics", ("timestamp",)),
    "ban_appeal_messages": ("appeals", ("created_at",)),
}

EXPORT_TABLES = (
    "warnings", "sanctions", "tempactions", "tickets", "ticket_notes", "economy",
    "inventory", "levels", "profiles", "suggestions", "bug_reports", "reminders",
    "pets", "message_counts", "voice_totals", "member_invites", "invite_bonuses",
    "automod_logs", "moderation_evidence", "adaptive_sanction_advice",
    "game_player_stats", "game_daily_progress", "game_weekly_progress",
    "economy_abuse_state", "economy_transfer_events", "onboarding_state",
    "ban_appeals", "modmail_threads", "modmail_messages",
)

# Données communautaires/personnelles supprimables. Les dossiers de sanctions/warnings,
# preuves et tickets restent traçables ; leur contenu volumineux est géré par la rétention.
PURGE_TABLES = (
    "economy", "inventory", "levels", "profiles", "suggestions", "reminders", "pets",
    "message_counts", "voice_totals", "game_player_stats", "game_daily_progress",
    "game_weekly_progress", "economy_abuse_state", "onboarding_state",
)

_USER_COLUMNS = ("user_id", "member_id", "author_id", "sender_id", "receiver_id", "inviter_id")
_SCHEMA_READY = False
_SUBCOMMANDS_READY = False


def _env_days(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(3650, value))


def _s3_configured() -> bool:
    return bool(
        os.getenv("S3_BUCKET", "").strip()
        and os.getenv("S3_ACCESS_KEY_ID", "").strip()
        and os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
    )


def _finding(severity: str, title: str, detail: str, deduction: int) -> dict[str, Any]:
    return {"severity": severity, "title": title, "detail": detail, "deduction": max(0, int(deduction))}


async def _ensure_schema(bot: commands.Bot) -> bool:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True
    conn = getattr(getattr(bot, "db", None), "_conn", None)
    if conn is None:
        return False
    await conn.executescript(READINESS_SCHEMA)
    await conn.commit()
    _SCHEMA_READY = True
    return True


async def _table_columns(bot: commands.Bot, table: str) -> set[str]:
    try:
        rows = await bot.db.fetchall(f'PRAGMA table_info("{table}")')
        return {str(row["name"]) for row in rows}
    except Exception:
        return set()


async def _table_exists(bot: commands.Bot, table: str) -> bool:
    try:
        row = await bot.db.fetchone(
            "SELECT 1 AS ok FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)
        )
        return bool(row)
    except Exception:
        return False


async def _infra_health(bot: commands.Bot) -> dict[str, Any]:
    infra = getattr(bot, "sentrix_infra", None)
    if infra is not None and hasattr(infra, "health"):
        try:
            state = dict(await infra.health())
        except Exception as exc:
            state = {"postgres_configured": False, "postgres_online": False, "redis_configured": False, "redis_online": False, "error": str(exc)[:300]}
    else:
        state = {
            "postgres_configured": bool(os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")),
            "postgres_online": False,
            "redis_configured": bool(os.getenv("REDIS_URL")),
            "redis_online": False,
        }
    durable = getattr(bot, "sentrix_durable_store", None)
    if durable is not None and hasattr(durable, "health"):
        try:
            state["durable"] = await durable.health()
        except Exception as exc:
            state["durable"] = {"configured": bool(os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")), "postgres_online": False, "error": str(exc)[:300]}
    else:
        state["durable"] = {
            "configured": bool(os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")),
            "postgres_online": False,
            "local_sqlite_ok": True,
        }
    state["s3_configured"] = _s3_configured()
    state["canary_mode"] = os.getenv("SENTRIX_CANARY_MODE", "0").strip().casefold() in {"1", "true", "yes", "on"}
    try:
        state["canary_guild_id"] = int(os.getenv("CANARY_GUILD_ID", "0") or 0)
    except ValueError:
        state["canary_guild_id"] = 0
    state["external_backup_ready"] = bool(state["s3_configured"] or state.get("durable", {}).get("postgres_online"))
    return state


async def audit_guild_configuration(bot: commands.Bot, guild: discord.Guild) -> dict[str, Any]:
    """Audit transparent : chaque retrait de points correspond à un finding visible."""
    findings: list[dict[str, Any]] = []
    config_row = await bot.db.get_guild_config(guild.id)
    conf = dict(config_row) if config_row else {}
    automod_row = await bot.db.get_automod(guild.id)
    automod = dict(automod_row) if automod_row else {}

    me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
    if me is None:
        findings.append(_finding("critical", "Présence du bot", "SentriX ne peut pas résoudre son membre Discord sur ce serveur.", 25))
    else:
        perms = me.guild_permissions
        required = {
            "manage_roles": "Gérer les rôles",
            "manage_channels": "Gérer les salons",
            "manage_messages": "Gérer les messages",
            "ban_members": "Bannir des membres",
            "kick_members": "Expulser des membres",
            "moderate_members": "Modérer les membres",
        }
        missing = [label for key, label in required.items() if not getattr(perms, key, False)]
        if missing:
            findings.append(_finding("critical", "Permissions Discord", "Permissions manquantes : " + ", ".join(missing), min(22, 4 * len(missing))))
        if len(guild.roles) > 1 and me.top_role.position <= 1:
            findings.append(_finding("critical", "Hiérarchie du rôle SentriX", "Le rôle du bot est trop bas pour gérer correctement les rôles du serveur.", 10))

    def channel_ok(key: str) -> bool:
        try:
            value = int(conf.get(key) or 0)
        except (TypeError, ValueError):
            return False
        return bool(value and guild.get_channel(value))

    def role_ok(key: str) -> bool:
        try:
            value = int(conf.get(key) or 0)
        except (TypeError, ValueError):
            return False
        return bool(value and guild.get_role(value))

    if not (channel_ok("log_channel") or channel_ok("log_moderation")):
        findings.append(_finding("warning", "Logs de modération", "Aucun salon de logs de modération valide n'est configuré.", 8))
    if not channel_ok("error_channel"):
        findings.append(_finding("info", "Salon d'erreurs", "Configurez un salon d'erreurs privé pour les alertes techniques.", 3))
    if not (role_ok("mod_role") or role_ok("admin_role")):
        findings.append(_finding("warning", "Rôle staff", "Aucun rôle modérateur/administrateur valide n'est relié à SentriX.", 7))
    if not channel_ok("rules_channel"):
        findings.append(_finding("info", "Règlement", "Le salon du règlement n'est pas configuré.", 3))

    # Vérification : pénalise uniquement une configuration partielle/incohérente.
    verification_parts = [bool(conf.get("verification_channel")), bool(conf.get("verification_role") or conf.get("verify_role"))]
    if any(verification_parts) and not all(verification_parts):
        findings.append(_finding("warning", "Vérification incomplète", "Le salon et le rôle de vérification doivent être configurés ensemble.", 5))

    open_tickets = 0
    try:
        row = await bot.db.fetchone("SELECT COUNT(*) AS n FROM tickets WHERE guild_id=? AND status='ouvert'", (guild.id,))
        open_tickets = int(row["n"] if row else 0)
    except Exception:
        pass
    if open_tickets and not (conf.get("ticket_category") or conf.get("ticket_log_channel")):
        findings.append(_finding("warning", "Tickets", "Des tickets sont utilisés mais leur catégorie/log n'est pas entièrement configuré.", 5))

    for key, label, deduction in (
        ("antinuke", "Anti-nuke", 9),
        ("antiraid", "Anti-raid", 6),
        ("antiscam", "Anti-scam", 4),
        ("escalation", "Escalade AutoMod", 3),
    ):
        if not int(automod.get(key, 0) or 0):
            findings.append(_finding("warning" if key in {"antinuke", "antiraid"} else "info", label, f"{label} est désactivé.", deduction))

    infra = await _infra_health(bot)
    durable = infra.get("durable", {})
    if not durable.get("postgres_online"):
        findings.append(_finding("warning", "Durabilité PostgreSQL", "La réplication durable de la base principale n'est pas active.", 6))
    if not infra.get("redis_online"):
        findings.append(_finding("info", "Redis", "Redis n'est pas actif ; les verrous inter-shards utilisent le fallback local.", 3))
    if not infra.get("external_backup_ready"):
        findings.append(_finding("warning", "Sauvegarde externe", "Ni PostgreSQL durable ni stockage S3 externe n'est actuellement disponible.", 5))
    if not int(infra.get("canary_guild_id") or 0):
        findings.append(_finding("info", "Canary", "Aucun serveur canary n'est configuré pour valider les grosses mises à jour.", 2))
    if not getattr(__import__("config"), "OWNER_IDS", []):
        findings.append(_finding("warning", "Propriétaire du bot", "OWNER_IDS n'est pas configuré.", 4))

    score = max(0, 100 - sum(int(item["deduction"]) for item in findings))
    result = {"guild_id": guild.id, "score": score, "findings": findings, "created_at": now(), "infra": infra}
    if await _ensure_schema(bot):
        await bot.db.execute(
            "INSERT INTO guild_readiness_audits (guild_id,score,findings_json,created_at) VALUES (?,?,?,?)",
            (guild.id, score, json.dumps(findings, ensure_ascii=False), result["created_at"]),
        )
        await bot.db.execute(
            "DELETE FROM guild_readiness_audits WHERE id IN (SELECT id FROM guild_readiness_audits WHERE guild_id=? ORDER BY created_at DESC,id DESC LIMIT -1 OFFSET 30)",
            (guild.id,),
        )
    return result


async def _policies(bot: commands.Bot, guild_id: int) -> dict[str, int]:
    values = {category: _env_days(env_name, default) for category, (env_name, default) in RETENTION_DEFAULTS.items()}
    if not await _ensure_schema(bot):
        return values
    rows = await bot.db.fetchall("SELECT category,days FROM retention_policies WHERE guild_id=?", (guild_id,))
    for row in rows:
        category = str(row["category"])
        if category in values:
            values[category] = max(1, min(3650, int(row["days"])))
    return values


async def run_retention(bot: commands.Bot, guild_id: int | None = None) -> dict[str, Any]:
    policies = await _policies(bot, int(guild_id or 0))
    details: dict[str, int] = {}
    total = 0
    ts = now()
    for table, (category, candidates) in RETENTION_TARGETS.items():
        if not await _table_exists(bot, table):
            continue
        columns = await _table_columns(bot, table)
        time_col = next((name for name in candidates if name in columns), None)
        if not time_col:
            continue
        cutoff = ts - int(policies[category]) * 86400
        params: tuple[Any, ...]
        where = f'"{time_col}" < ?'
        params = (cutoff,)
        if guild_id is not None and "guild_id" in columns:
            where += " AND guild_id = ?"
            params = (cutoff, int(guild_id))
        try:
            cur = await bot.db.execute(f'DELETE FROM "{table}" WHERE {where}', params)
            count = max(0, int(cur.rowcount if cur.rowcount is not None else 0))
        except Exception:
            logger.exception("Rétention impossible pour %s.", table)
            continue
        if count:
            details[table] = count
            total += count
    if await _ensure_schema(bot):
        await bot.db.execute(
            "INSERT INTO retention_runs (guild_id,deleted_rows,details_json,created_at) VALUES (?,?,?,?)",
            (guild_id, total, json.dumps(details, ensure_ascii=False), ts),
        )
    return {"deleted_rows": total, "details": details, "policies": policies, "created_at": ts}


async def _privacy_export(bot: commands.Bot, guild_id: int, user_id: int) -> dict[str, Any]:
    result: dict[str, Any] = {"guild_id": guild_id, "user_id": user_id, "exported_at": now(), "tables": {}}
    for table in EXPORT_TABLES:
        if not await _table_exists(bot, table):
            continue
        columns = await _table_columns(bot, table)
        user_columns = [name for name in _USER_COLUMNS if name in columns]
        if not user_columns:
            continue
        clauses = [f'"{name}"=?' for name in user_columns]
        params: list[Any] = [user_id] * len(user_columns)
        if "guild_id" in columns:
            query = f'SELECT * FROM "{table}" WHERE guild_id=? AND (' + " OR ".join(clauses) + ") LIMIT 500"
            params.insert(0, guild_id)
        else:
            query = f'SELECT * FROM "{table}" WHERE ' + " OR ".join(clauses) + " LIMIT 500"
        try:
            rows = await bot.db.fetchall(query, tuple(params))
        except Exception:
            continue
        clean_rows = []
        for row in rows:
            item = dict(row)
            for secret_key in tuple(item):
                if "token" in secret_key.casefold() or secret_key.casefold() in {"checksum", "password", "secret"}:
                    item.pop(secret_key, None)
                elif isinstance(item.get(secret_key), bytes):
                    item[secret_key] = f"<bytes:{len(item[secret_key])}>"
            clean_rows.append(item)
        if clean_rows:
            result["tables"][table] = clean_rows
    return result


async def _privacy_purge(bot: commands.Bot, guild_id: int, user_id: int) -> int:
    total = 0
    for table in PURGE_TABLES:
        if not await _table_exists(bot, table):
            continue
        columns = await _table_columns(bot, table)
        user_columns = [name for name in _USER_COLUMNS if name in columns]
        if not user_columns:
            continue
        clauses = [f'"{name}"=?' for name in user_columns]
        params: list[Any] = [user_id] * len(user_columns)
        if "guild_id" in columns:
            where = "guild_id=? AND (" + " OR ".join(clauses) + ")"
            params.insert(0, guild_id)
        else:
            where = " OR ".join(clauses)
        try:
            cur = await bot.db.execute(f'DELETE FROM "{table}" WHERE {where}', tuple(params))
            total += max(0, int(cur.rowcount if cur.rowcount is not None else 0))
        except Exception:
            logger.exception("Suppression privacy impossible pour %s.", table)
    # Les preuves de modération gardent l'identifiant/dossier, mais leur contenu sensible
    # peut être supprimé sans casser l'intégrité de l'historique de sanction.
    if await _table_exists(bot, "moderation_evidence"):
        try:
            cur = await bot.db.execute(
                "UPDATE moderation_evidence SET content='[contenu supprimé]',attachments_json='[]' WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            total += max(0, int(cur.rowcount if cur.rowcount is not None else 0))
        except Exception:
            pass
    return total


async def _require_admin(ctx: commands.Context) -> bool:
    if ctx.guild is None or not isinstance(ctx.author, discord.Member):
        await ctx.send("Cette commande est disponible uniquement sur un serveur.")
        return False
    if ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator:
        return True
    await ctx.send("Seul le propriétaire du serveur ou un administrateur peut utiliser cette commande.")
    return False


async def _require_owner(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        await ctx.send("Cette commande est disponible uniquement sur un serveur.")
        return False
    import config
    if ctx.author.id == ctx.guild.owner_id or ctx.author.id in config.OWNER_IDS:
        return True
    await ctx.send("Cette action de confidentialité est réservée au propriétaire du serveur ou du bot.")
    return False


async def _security_readiness(ctx: commands.Context):
    if not await _require_admin(ctx):
        return
    async with ctx.typing():
        result = await audit_guild_configuration(ctx.bot, ctx.guild)
    findings = result["findings"]
    lines = []
    for item in findings[:12]:
        level = {"critical": "Critique", "warning": "À corriger", "info": "Conseil"}.get(item["severity"], "Info")
        lines.append(f"{level} — {item['title']} : {item['detail']} (-{item['deduction']})")
    if not lines:
        lines.append("Aucun problème détecté par l'audit actuel.")
    embed = discord.Embed(
        title=f"Configuration SentriX : {result['score']}/100",
        description="\n".join(lines)[:4000],
        color=0x57F287 if result["score"] >= 85 else (0xFEE75C if result["score"] >= 65 else 0xED4245),
    )
    embed.set_footer(text="Score déterministe : chaque retrait de points est affiché ci-dessus.")
    await ctx.send(embed=embed)


async def _security_infra(ctx: commands.Context):
    if not await _require_admin(ctx):
        return
    state = await _infra_health(ctx.bot)
    durable = state.get("durable", {})
    lines = [
        f"Base locale SQLite : {'OK' if durable.get('local_sqlite_ok') else 'ERREUR'}",
        f"PostgreSQL durable : {'OK' if durable.get('postgres_online') else ('CONFIGURÉ MAIS HORS LIGNE' if durable.get('configured') else 'NON CONFIGURÉ')}",
        f"Redis : {'OK' if state.get('redis_online') else ('CONFIGURÉ MAIS HORS LIGNE' if state.get('redis_configured') else 'NON CONFIGURÉ')}",
        f"Sauvegarde S3 : {'CONFIGURÉE' if state.get('s3_configured') else 'NON CONFIGURÉE'}",
        f"Sauvegarde externe utilisable : {'OUI' if state.get('external_backup_ready') else 'NON'}",
        f"Serveur canary : {state.get('canary_guild_id') or 'NON CONFIGURÉ'}",
    ]
    if durable.get("last_snapshot_at"):
        lines.append(f"Dernier snapshot PostgreSQL : <t:{int(durable['last_snapshot_at'])}:R>")
    await ctx.send(embed=discord.Embed(title="Infrastructure SentriX", description="\n".join(lines), color=0x5865F2))


async def _security_retention(
    ctx: commands.Context,
    action: str = "status",
    category: str | None = None,
    days: int | None = None,
):
    if not await _require_admin(ctx):
        return
    action = str(action or "status").casefold()
    if action in {"status", "show", "voir"}:
        values = await _policies(ctx.bot, ctx.guild.id)
        text = "\n".join(f"{key} : {value} jours" for key, value in values.items())
        return await ctx.send(embed=discord.Embed(title="Conservation des données", description=text, color=0x5865F2))
    if action in {"run", "purge", "nettoyer"}:
        async with ctx.typing():
            result = await run_retention(ctx.bot, ctx.guild.id)
        return await ctx.send(f"Rétention terminée : {result['deleted_rows']} ligne(s) temporaire(s) supprimée(s).")
    if action in {"set", "regler", "régler"}:
        if not category or category not in RETENTION_DEFAULTS or days is None:
            return await ctx.send("Utilisation : +security retention set <transcripts|evidence|diagnostics|analytics|appeals> <jours>.")
        days = max(1, min(3650, int(days)))
        await _ensure_schema(ctx.bot)
        await ctx.bot.db.execute(
            "INSERT INTO retention_policies (guild_id,category,days,updated_by,updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id,category) DO UPDATE SET days=excluded.days,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (ctx.guild.id, category, days, ctx.author.id, now()),
        )
        return await ctx.send(f"Conservation {category} réglée sur {days} jours.")
    await ctx.send("Action inconnue. Utilisez status, set ou run.")


async def _security_privacy(
    ctx: commands.Context,
    action: str | None = None,
    user_id: str | None = None,
    confirmation: str | None = None,
):
    if not await _require_owner(ctx):
        return
    if action not in {"export", "purge"} or not user_id or not str(user_id).isdigit():
        return await ctx.send("Utilisation : +security privacy export <ID> ou +security privacy purge <ID> CONFIRMER.")
    target_id = int(user_id)
    if action == "export":
        async with ctx.typing():
            payload = await _privacy_export(ctx.bot, ctx.guild.id, target_id)
        raw = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        await _ensure_schema(ctx.bot)
        await ctx.bot.db.execute(
            "INSERT INTO privacy_actions (guild_id,target_user_id,actor_id,action,affected_rows,created_at) VALUES (?,?,?,?,?,?)",
            (ctx.guild.id, target_id, ctx.author.id, "export", sum(len(v) for v in payload["tables"].values()), now()),
        )
        return await ctx.send(
            "Export privé généré. Ne partagez ce fichier qu'avec la personne concernée.",
            file=discord.File(io.BytesIO(raw), filename=f"sentrix-data-{ctx.guild.id}-{target_id}.json"),
        )
    if str(confirmation or "").upper() != "CONFIRMER":
        return await ctx.send(f"Suppression non exécutée. Retapez : +security privacy purge {target_id} CONFIRMER")
    async with ctx.typing():
        affected = await _privacy_purge(ctx.bot, ctx.guild.id, target_id)
    await _ensure_schema(ctx.bot)
    await ctx.bot.db.execute(
        "INSERT INTO privacy_actions (guild_id,target_user_id,actor_id,action,affected_rows,created_at) VALUES (?,?,?,?,?,?)",
        (ctx.guild.id, target_id, ctx.author.id, "purge", affected, now()),
    )
    await ctx.send(
        f"Suppression terminée : {affected} ligne(s) de données communautaires/personnelles supprimée(s) ou nettoyée(s). "
        "Les dossiers de sanction restent conservés pour l'intégrité de la modération."
    )


def _install_security_subcommands(bot: commands.Bot) -> None:
    global _SUBCOMMANDS_READY
    root = bot.get_command("security")
    if not isinstance(root, commands.Group):
        return
    specs = (
        ("readiness", _security_readiness, "Auditer toute la configuration SentriX sur 100."),
        ("infra", _security_infra, "Afficher l'état de l'infrastructure de production."),
        ("retention", _security_retention, "Configurer la conservation automatique des données."),
        ("privacy", _security_privacy, "Exporter ou supprimer les données personnelles d'un membre."),
    )
    for name, callback, help_text in specs:
        if root.get_command(name) is None:
            root.add_command(commands.Command(callback, name=name, help=help_text))
    _SUBCOMMANDS_READY = True


class ProductionReadinessRuntime(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_snapshot_attempt = 0
        self._last_retention_day = ""
        self._last_audit_bucket = -1
        self.maintenance.start()

    def cog_unload(self):
        self.maintenance.cancel()

    @tasks.loop(minutes=5)
    async def maintenance(self):
        ts = now()
        durable = getattr(self.bot, "sentrix_durable_store", None)
        infra = getattr(self.bot, "sentrix_infra", None)
        if durable is not None and ts - self._last_snapshot_attempt >= int(getattr(durable, "interval_seconds", 900)):
            self._last_snapshot_attempt = ts
            lease_value = f"{os.getpid()}:{ts}"
            acquired = True
            if infra is not None:
                acquired = await infra.acquire_lease("main-db-snapshot", lease_value, ttl=240)
            if acquired:
                try:
                    await durable.snapshot(reason="periodic")
                finally:
                    if infra is not None:
                        await infra.release_lease("main-db-snapshot", lease_value)

        day = time.strftime("%Y-%m-%d", time.gmtime(ts))
        if day != self._last_retention_day:
            self._last_retention_day = day
            lease_value = f"retention:{os.getpid()}:{ts}"
            acquired = True
            if infra is not None:
                acquired = await infra.acquire_lease("data-retention", lease_value, ttl=900)
            if acquired:
                try:
                    await run_retention(self.bot, None)
                finally:
                    if infra is not None:
                        await infra.release_lease("data-retention", lease_value)

        bucket = ts // (6 * 3600)
        if bucket != self._last_audit_bucket:
            self._last_audit_bucket = bucket
            for guild in list(self.bot.guilds):
                try:
                    await audit_guild_configuration(self.bot, guild)
                except Exception:
                    logger.exception("Audit de configuration impossible pour %s.", guild.id)

    @maintenance.before_loop
    async def before_maintenance(self):
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            raise asyncio.CancelledError
        await asyncio.sleep(30)


async def install(bot: commands.Bot, extension_name: str = "") -> ProductionReadinessRuntime | None:
    await _ensure_schema(bot)
    runtime = bot.get_cog(_COG_NAME)
    if runtime is None:
        runtime = ProductionReadinessRuntime(bot)
        await bot.add_cog(runtime)
        bot.sentrix_production_runtime = runtime
        logger.info("Production Readiness actif : audits, snapshots, rétention et confidentialité.")
    _install_security_subcommands(bot)
    return runtime
