"""SentriX V4 — vérification automatique 20 facteurs + honeypot.

Le membre n'a aucun captcha, calcul ou séquence à résoudre. SentriX évalue exactement
20 signaux techniques/comportementaux disponibles côté Discord et valide automatiquement
à partir du seuil configuré (16/20 minimum).

Un score insuffisant ne bannit jamais le membre : il reste Non vérifié pour revue staff.
Le honeypot reste une protection séparée et peut, lui, appliquer l'action configurée.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import discord
from discord.ext import commands

from utils import helpers
from . import setup_v2_core

logger = logging.getLogger("bot.security.auto-verification-v4")
_COG_NAME = "HoneypotVerification"  # compatibilité avec Control Center V3
FACTOR_COUNT = 20
MIN_THRESHOLD = 16
DEFAULT_THRESHOLD = 16
MAX_THRESHOLD = 20
DEFAULT_MIN_ACCOUNT_AGE_MINUTES = 60
AUTO_EVALUATION_DELAY_SECONDS = 4
RAID_WINDOW_SECONDS = 20
RAID_JOIN_LIMIT = 8

SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS automatic_verification_v4 (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    threshold INTEGER NOT NULL DEFAULT 16,
    min_account_age_minutes INTEGER NOT NULL DEFAULT 60,
    log_channel_id INTEGER,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL DEFAULT 0
)
"""

RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS automatic_verification_results_v4 (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    threshold INTEGER NOT NULL,
    status TEXT NOT NULL,
    factors_json TEXT NOT NULL,
    evaluated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
)
"""

EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS automatic_verification_events_v4 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    created_at INTEGER NOT NULL
)
"""


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    passed: bool
    detail: str = ""


def clamp_threshold(value: int | str | None) -> int:
    try:
        parsed = int(value if value is not None else DEFAULT_THRESHOLD)
    except (TypeError, ValueError):
        parsed = DEFAULT_THRESHOLD
    return max(MIN_THRESHOLD, min(MAX_THRESHOLD, parsed))


def score_factors(factors: list[Factor], threshold: int = DEFAULT_THRESHOLD) -> tuple[int, bool]:
    """Contrat pur testé : exactement 20 facteurs ; 16 passe, 15 échoue par défaut."""
    if len(factors) != FACTOR_COUNT:
        raise ValueError(f"SentriX exige exactement {FACTOR_COUNT} facteurs, reçu {len(factors)}")
    threshold = clamp_threshold(threshold)
    score = sum(1 for factor in factors if bool(factor.passed))
    return score, score >= threshold


class AutomaticVerification(commands.Cog, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._trap_locks: set[tuple[int, int]] = set()

    async def ensure_schema(self) -> None:
        await self.bot.db.execute(SETTINGS_SCHEMA)
        await self.bot.db.execute(RESULTS_SCHEMA)
        await self.bot.db.execute(EVENTS_SCHEMA)
        # Réutilise les tables du moteur V3/V50 pour rester compatible avec les données déjà créées.
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS honeypot_verification (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                category_id INTEGER,
                trap_channel_id INTEGER,
                verify_channel_id INTEGER,
                unverified_role_id INTEGER,
                verified_role_id INTEGER,
                sanction TEXT NOT NULL DEFAULT 'softban',
                created_at INTEGER NOT NULL
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS honeypot_pending_members (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS honeypot_verified_members (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                verified_at INTEGER NOT NULL,
                method TEXT NOT NULL,
                account_age_seconds INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

    async def config(self, guild_id: int, *, enabled_only: bool = True):
        await self.ensure_schema()
        query = "SELECT * FROM honeypot_verification WHERE guild_id=?"
        if enabled_only:
            query += " AND enabled=1"
        return await self.bot.db.fetchone(query, (int(guild_id),))

    async def settings(self, guild_id: int) -> dict[str, Any]:
        await self.ensure_schema()
        row = await self.bot.db.fetchone(
            "SELECT * FROM automatic_verification_v4 WHERE guild_id=?", (int(guild_id),)
        )
        if row is None:
            return {
                "enabled": 1,
                "threshold": DEFAULT_THRESHOLD,
                "min_account_age_minutes": DEFAULT_MIN_ACCOUNT_AGE_MINUTES,
                "log_channel_id": None,
            }
        return {
            "enabled": int(row["enabled"]),
            "threshold": clamp_threshold(row["threshold"]),
            "min_account_age_minutes": max(0, int(row["min_account_age_minutes"] or 0)),
            "log_channel_id": row["log_channel_id"],
        }

    async def update_settings(
        self,
        guild_id: int,
        *,
        threshold: int | None = None,
        min_account_age_minutes: int | None = None,
        log_channel_id: int | None = None,
        actor_id: int | None = None,
    ) -> None:
        current = await self.settings(guild_id)
        threshold = clamp_threshold(threshold if threshold is not None else current["threshold"])
        age = current["min_account_age_minutes"] if min_account_age_minutes is None else max(0, min(525600, int(min_account_age_minutes)))
        logs = current["log_channel_id"] if log_channel_id is None else log_channel_id
        await self.bot.db.execute(
            "INSERT INTO automatic_verification_v4(guild_id,enabled,threshold,min_account_age_minutes,log_channel_id,updated_by,updated_at) "
            "VALUES(?,1,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET enabled=1,threshold=excluded.threshold,"
            "min_account_age_minutes=excluded.min_account_age_minutes,log_channel_id=excluded.log_channel_id,"
            "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (int(guild_id), threshold, age, logs, actor_id, int(time.time())),
        )

    async def _event(self, guild_id: int, user_id: int, kind: str) -> None:
        await self.bot.db.execute(
            "INSERT INTO automatic_verification_events_v4(guild_id,user_id,kind,created_at) VALUES(?,?,?,?)",
            (int(guild_id), int(user_id), str(kind)[:64], int(time.time())),
        )

    async def _event_count(self, guild_id: int, *, user_id: int | None = None, kind: str | None = None, since: int = 0) -> int:
        sql = "SELECT COUNT(*) c FROM automatic_verification_events_v4 WHERE guild_id=? AND created_at>=?"
        params: list[Any] = [int(guild_id), int(since)]
        if user_id is not None:
            sql += " AND user_id=?"
            params.append(int(user_id))
        if kind is not None:
            sql += " AND kind=?"
            params.append(kind)
        row = await self.bot.db.fetchone(sql, tuple(params))
        return int(row["c"] if row else 0)

    async def _pending_joined_at(self, guild_id: int, user_id: int) -> int:
        row = await self.bot.db.fetchone(
            "SELECT joined_at FROM honeypot_pending_members WHERE guild_id=? AND user_id=?",
            (int(guild_id), int(user_id)),
        )
        return int(row["joined_at"] if row else time.time())

    async def _mark_pending(self, member: discord.Member) -> None:
        joined = int(member.joined_at.timestamp()) if member.joined_at else int(time.time())
        await self.bot.db.execute(
            "INSERT INTO honeypot_pending_members(guild_id,user_id,joined_at) VALUES(?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET joined_at=excluded.joined_at",
            (member.guild.id, member.id, joined),
        )

    async def _clear_pending(self, guild_id: int, user_id: int) -> None:
        await self.bot.db.execute(
            "DELETE FROM honeypot_pending_members WHERE guild_id=? AND user_id=?",
            (int(guild_id), int(user_id)),
        )

    async def _find_or_create_role(self, guild: discord.Guild, name: str) -> discord.Role:
        role = discord.utils.get(guild.roles, name=name)
        if role is not None and not role.managed:
            return role
        return await guild.create_role(name=name, permissions=discord.Permissions.none(), reason="SentriX : vérification automatique")

    @staticmethod
    def _blocked_overwrite() -> discord.PermissionOverwrite:
        return discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            add_reactions=False,
            create_public_threads=False,
            create_private_threads=False,
            connect=False,
            speak=False,
        )

    async def _lock_channels(self, guild: discord.Guild, role: discord.Role, excluded: set[int]) -> None:
        for channel in list(guild.channels):
            if channel.id in excluded:
                continue
            try:
                await channel.set_permissions(role, overwrite=self._blocked_overwrite(), reason="SentriX : accès après vérification automatique")
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Impossible de verrouiller le salon %s", channel.id)
            await asyncio.sleep(0.02)

    async def create_or_refresh_system(self, guild: discord.Guild, *, sanction: str = "softban"):
        """API compatible V3, mais le salon verification est purement informatif : aucun captcha."""
        await self.ensure_schema()
        if sanction not in {"softban", "kick"}:
            sanction = "softban"
        me = guild.me
        if me is None:
            return None, "SentriX est introuvable sur ce serveur."
        required = {
            "Gérer les rôles": me.guild_permissions.manage_roles,
            "Gérer les salons": me.guild_permissions.manage_channels,
            "Gérer les messages": me.guild_permissions.manage_messages,
        }
        if sanction == "softban":
            required["Bannir des membres"] = me.guild_permissions.ban_members
        elif sanction == "kick":
            required["Expulser des membres"] = me.guild_permissions.kick_members
        missing = [label for label, ok in required.items() if not ok]
        if missing:
            return None, "Permissions manquantes : " + ", ".join(missing)

        old = await self.config(guild.id, enabled_only=False)
        unverified = guild.get_role(old["unverified_role_id"]) if old and old["unverified_role_id"] else None
        verified = guild.get_role(old["verified_role_id"]) if old and old["verified_role_id"] else None
        unverified = unverified or await self._find_or_create_role(guild, "Non vérifié")
        verified = verified or await self._find_or_create_role(guild, "Vérifié")
        if unverified >= me.top_role or verified >= me.top_role:
            return None, "Place les rôles `Non vérifié` et `Vérifié` sous le rôle SentriX puis réessaie."

        category = guild.get_channel(old["category_id"]) if old and old["category_id"] else None
        if not isinstance(category, discord.CategoryChannel):
            category = await guild.create_category("SentriX • Vérification", reason="SentriX : vérification automatique")

        verify = guild.get_channel(old["verify_channel_id"]) if old and old["verify_channel_id"] else None
        if not isinstance(verify, discord.TextChannel):
            verify = await guild.create_text_channel("verification-auto", category=category, reason="SentriX : vérification automatique")
        trap = guild.get_channel(old["trap_channel_id"]) if old and old["trap_channel_id"] else None
        if not isinstance(trap, discord.TextChannel):
            trap = await guild.create_text_channel("stay-muted", category=category, reason="SentriX : honeypot")

        # Visibilité : les nouveaux voient uniquement l'information et le honeypot jusqu'au verdict.
        try:
            await verify.set_permissions(guild.default_role, view_channel=False)
            await verify.set_permissions(unverified, view_channel=True, send_messages=False, read_message_history=True)
            await trap.set_permissions(guild.default_role, view_channel=False)
            await trap.set_permissions(unverified, view_channel=True, send_messages=True, read_message_history=True)
            await verify.set_permissions(verified, view_channel=False)
            await trap.set_permissions(verified, view_channel=False)
        except (discord.Forbidden, discord.HTTPException):
            pass
        await self._lock_channels(guild, unverified, {category.id, verify.id, trap.id})

        settings = await self.settings(guild.id)
        try:
            await verify.purge(limit=20, check=lambda m: self.bot.user is not None and m.author.id == self.bot.user.id)
        except (discord.Forbidden, discord.HTTPException):
            pass
        info = discord.Embed(
            title="SentriX • Vérification automatique",
            description=(
                "Tu n'as **rien à faire**. SentriX vérifie automatiquement ton compte avec **20 facteurs** "
                f"techniques et comportementaux. Il faut au minimum **{settings['threshold']}/20** pour être validé.\n\n"
                "Si les règles Discord du serveur doivent être acceptées, fais-le normalement : SentriX relancera "
                "le contrôle tout seul juste après. Un score insuffisant ne provoque aucun bannissement automatique."
            ),
            colour=discord.Color.blurple(),
        )
        info.set_footer(text="SentriX • Aucun captcha, aucun calcul, aucun code")
        try:
            await verify.send(embed=info)
        except discord.HTTPException:
            pass

        try:
            await trap.purge(limit=20, check=lambda m: self.bot.user is not None and m.author.id == self.bot.user.id)
        except (discord.Forbidden, discord.HTTPException):
            pass
        trap_embed = discord.Embed(
            title="NE PAS ENVOYER DE MESSAGE DANS CE SALON",
            description=(
                "Ce salon est un **honeypot anti-bot**. Il n'est pas nécessaire pour la vérification. "
                "Un compte non vérifié qui écrit ici déclenche la protection configurée."
            ),
            colour=discord.Color.red(),
        )
        try:
            await trap.send(embed=trap_embed)
        except discord.HTTPException:
            pass

        await self.bot.db.execute(
            "INSERT INTO honeypot_verification(guild_id,enabled,category_id,trap_channel_id,verify_channel_id,unverified_role_id,verified_role_id,sanction,created_at) "
            "VALUES(?,1,?,?,?,?,?,?,?) ON CONFLICT(guild_id) DO UPDATE SET enabled=1,category_id=excluded.category_id,"
            "trap_channel_id=excluded.trap_channel_id,verify_channel_id=excluded.verify_channel_id,unverified_role_id=excluded.unverified_role_id,"
            "verified_role_id=excluded.verified_role_id,sanction=excluded.sanction",
            (guild.id, category.id, trap.id, verify.id, unverified.id, verified.id, sanction, int(time.time())),
        )
        await self.update_settings(guild.id)
        return {"category": category, "verify": verify, "trap": trap, "unverified": unverified, "verified": verified, "sanction": sanction}, None

    async def disable_system(self, guild: discord.Guild) -> tuple[bool, str]:
        conf = await self.config(guild.id, enabled_only=False)
        if conf is None:
            return True, "La vérification était déjà désactivée."
        await self.bot.db.execute("UPDATE honeypot_verification SET enabled=0 WHERE guild_id=?", (guild.id,))
        await self.bot.db.execute("UPDATE automatic_verification_v4 SET enabled=0 WHERE guild_id=?", (guild.id,))
        await self.bot.db.execute("DELETE FROM honeypot_pending_members WHERE guild_id=?", (guild.id,))
        role = guild.get_role(conf["unverified_role_id"]) if conf["unverified_role_id"] else None
        if role:
            for channel in list(guild.channels):
                try:
                    overwrite = channel.overwrites_for(role)
                    if not overwrite.is_empty():
                        await channel.set_permissions(role, overwrite=None, reason="SentriX : vérification automatique désactivée")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        return True, "Vérification automatique désactivée. Les salons et rôles sont conservés."

    async def _trusted(self, member: discord.Member) -> bool:
        if member.id == member.guild.owner_id:
            return True
        try:
            return await setup_v2_core.is_trusted(self.bot, member.guild.id, member.id)
        except Exception:
            return False

    async def collect_factors(self, member: discord.Member) -> list[Factor]:
        """Retourne TOUJOURS exactement 20 facteurs explicables."""
        now_dt = discord.utils.utcnow()
        now_ts = int(time.time())
        settings = await self.settings(member.guild.id)
        created = member.created_at
        age_seconds = max(0, int((now_dt - created).total_seconds()))
        joined_at = member.joined_at
        joined_age = max(0, int((now_dt - joined_at).total_seconds())) if joined_at else 0
        trusted = await self._trusted(member)
        timeout_until = getattr(member, "timed_out_until", None)
        timed_out = bool(timeout_until and timeout_until > now_dt)
        pending = bool(getattr(member, "pending", False))
        has_avatar = getattr(member, "avatar", None) is not None

        try:
            snowflake_created = discord.utils.snowflake_time(member.id)
            snowflake_ok = abs((snowflake_created - created).total_seconds()) <= 300
        except Exception:
            snowflake_ok = False

        honeypot_session = await self._event_count(
            member.guild.id, user_id=member.id, kind="honeypot", since=int(joined_at.timestamp()) if joined_at else now_ts - 3600
        )
        honeypot_30d = await self._event_count(member.guild.id, user_id=member.id, kind="honeypot", since=now_ts - 30 * 86400)
        rejoins_1h = await self._event_count(member.guild.id, user_id=member.id, kind="join", since=now_ts - 3600)
        guild_joins_burst = await self._event_count(member.guild.id, kind="join", since=now_ts - RAID_WINDOW_SECONDS)
        low_scores = await self._event_count(member.guild.id, user_id=member.id, kind="low_score", since=now_ts - 30 * 86400)
        security_events = await self._event_count(member.guild.id, user_id=member.id, kind="security_negative", since=now_ts - 30 * 86400)
        prior = await self.bot.db.fetchone(
            "SELECT 1 FROM honeypot_verified_members WHERE guild_id=? AND user_id=?",
            (member.guild.id, member.id),
        )

        min_age = max(0, int(settings["min_account_age_minutes"]) * 60)
        elevated = any(getattr(role.permissions, "administrator", False) for role in getattr(member, "roles", []) if role != member.guild.default_role)
        factors = [
            Factor("human", "Compte humain", not member.bot, "Le compte n'est pas déclaré bot par Discord."),
            Factor("not_system", "Compte non système", not bool(getattr(member, "system", False)), "Le compte n'est pas un compte système Discord."),
            Factor("screening", "Règles Discord validées", not pending, "Membership Screening terminé si activé."),
            Factor("age_minimum", "Âge minimum configuré", age_seconds >= min_age, f"Compte âgé de {age_seconds // 60} min ; minimum {min_age // 60} min."),
            Factor("age_1_day", "Compte âgé d'au moins 1 jour", age_seconds >= 86400),
            Factor("age_7_days", "Compte âgé d'au moins 7 jours", age_seconds >= 7 * 86400),
            Factor("age_30_days", "Compte âgé d'au moins 30 jours", age_seconds >= 30 * 86400),
            Factor("snowflake", "Identité Discord cohérente", snowflake_ok, "Timestamp du snowflake cohérent avec created_at."),
            Factor("joined_at", "Entrée serveur cohérente", joined_at is not None and joined_at >= created),
            Factor("profile", "Profil initialisé", has_avatar, "Avatar personnalisé présent."),
            Factor("timeout", "Aucun timeout actif", not timed_out),
            Factor("honeypot_session", "Aucun honeypot sur cette entrée", honeypot_session == 0),
            Factor("honeypot_history", "Aucun honeypot récent", honeypot_30d == 0),
            Factor("rejoin", "Pas de boucle de réentrée", rejoins_1h <= 2, f"{rejoins_1h} entrée(s) sur 1h."),
            Factor("low_score_history", "Pas d'échecs répétés", low_scores < 3, f"{low_scores} score(s) faible(s) récent(s)."),
            Factor("raid_burst", "Entrée hors rafale de raid", guild_joins_burst < RAID_JOIN_LIMIT, f"{guild_joins_burst} arrivée(s) sur {RAID_WINDOW_SECONDS}s."),
            Factor("join_stability", "Présence stable après arrivée", joined_age >= 3, f"Présent depuis {joined_age}s."),
            Factor("security_history", "Historique sécurité propre", trusted or security_events == 0),
            Factor("prior_trust", "Historique de vérification sain", bool(prior) or (honeypot_30d == 0 and low_scores < 2)),
            Factor("role_state", "État des rôles cohérent", trusted or not elevated, "Pas de privilège administrateur inattendu à l'arrivée."),
        ]
        if len(factors) != FACTOR_COUNT:
            raise RuntimeError("Contrat 20 facteurs cassé")
        return factors

    async def _save_result(self, member: discord.Member, score: int, threshold: int, status: str, factors: list[Factor]) -> None:
        payload = json.dumps(
            [{"key": f.key, "label": f.label, "passed": f.passed, "detail": f.detail} for f in factors],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await self.bot.db.execute(
            "INSERT INTO automatic_verification_results_v4(guild_id,user_id,score,threshold,status,factors_json,evaluated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET score=excluded.score,threshold=excluded.threshold,"
            "status=excluded.status,factors_json=excluded.factors_json,evaluated_at=excluded.evaluated_at",
            (member.guild.id, member.id, score, threshold, status, payload, int(time.time())),
        )

    async def _log_result(self, member: discord.Member, score: int, threshold: int, status: str, factors: list[Factor]) -> None:
        failed = [f.label for f in factors if not f.passed]
        colour = discord.Color.green() if status == "verified" else discord.Color.orange()
        embed = discord.Embed(
            title="SentriX • Vérification automatique",
            description=f"{member.mention} (`{member.id}`) — **{score}/{FACTOR_COUNT}** • seuil **{threshold}/{FACTOR_COUNT}**",
            colour=colour,
        )
        embed.add_field(name="Décision", value="Vérifié automatiquement" if status == "verified" else "Reste Non vérifié — revue staff possible", inline=False)
        embed.add_field(name="Facteurs non validés", value="\n".join(f"• {x}" for x in failed)[:1024] or "Aucun", inline=False)
        settings = await self.settings(member.guild.id)
        channel = member.guild.get_channel(settings.get("log_channel_id") or 0)
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                return
            except discord.HTTPException:
                pass
        try:
            await helpers.send_log(self.bot, member.guild, "automod", embed)
        except Exception:
            logger.exception("Impossible d'envoyer le log de vérification")

    async def evaluate_member(self, member: discord.Member, *, reason: str = "auto") -> tuple[int, bool] | None:
        conf = await self.config(member.guild.id)
        if conf is None or member.bot:
            return None
        if bool(getattr(member, "pending", False)):
            # Ce n'est pas un échec : on attend que Discord confirme l'acceptation des règles.
            return None
        factors = await self.collect_factors(member)
        settings = await self.settings(member.guild.id)
        threshold = clamp_threshold(settings["threshold"])
        score, passed = score_factors(factors, threshold)
        status = "verified" if passed else "review"
        await self._save_result(member, score, threshold, status, factors)
        if not passed:
            await self._event(member.guild.id, member.id, "low_score")
            await self._log_result(member, score, threshold, status, factors)
            return score, False

        unverified = member.guild.get_role(conf["unverified_role_id"]) if conf["unverified_role_id"] else None
        verified = member.guild.get_role(conf["verified_role_id"]) if conf["verified_role_id"] else None
        if verified is None:
            return score, False
        try:
            if verified not in member.roles:
                await member.add_roles(verified, reason=f"SentriX : vérification automatique {score}/{FACTOR_COUNT}")
            if unverified and unverified in member.roles:
                await member.remove_roles(unverified, reason="SentriX : vérification automatique réussie")
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible d'appliquer les rôles de vérification à %s", member.id)
            return score, False
        await self._clear_pending(member.guild.id, member.id)
        account_age = max(0, int((discord.utils.utcnow() - member.created_at).total_seconds()))
        await self.bot.db.execute(
            "INSERT INTO honeypot_verified_members(guild_id,user_id,verified_at,method,account_age_seconds) VALUES(?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET verified_at=excluded.verified_at,method=excluded.method,account_age_seconds=excluded.account_age_seconds",
            (member.guild.id, member.id, int(time.time()), f"automatic-{score}-of-20", account_age),
        )
        try:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO verified_users(guild_id,user_id,verified_at) VALUES(?,?,strftime('%s','now'))",
                (member.guild.id, member.id),
            )
        except Exception:
            pass
        await self._event(member.guild.id, member.id, "verified")
        await self._log_result(member, score, threshold, status, factors)
        return score, True

    def schedule_evaluation(self, member: discord.Member, *, reason: str = "auto") -> None:
        key = (member.guild.id, member.id)
        old = self._tasks.pop(key, None)
        if old and not old.done():
            old.cancel()

        async def runner():
            try:
                await asyncio.sleep(AUTO_EVALUATION_DELAY_SECONDS)
                fresh = member.guild.get_member(member.id)
                if fresh is not None:
                    await self.evaluate_member(fresh, reason=reason)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Échec évaluation automatique de %s", member.id)
            finally:
                self._tasks.pop(key, None)

        self._tasks[key] = asyncio.create_task(runner())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        conf = await self.config(member.guild.id)
        if conf is None:
            return
        await self._event(member.guild.id, member.id, "join")
        await self._mark_pending(member)
        role = member.guild.get_role(conf["unverified_role_id"]) if conf["unverified_role_id"] else None
        if role:
            try:
                await member.add_roles(role, reason="SentriX : vérification automatique en cours")
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Impossible d'ajouter Non vérifié à %s", member.id)
        self.schedule_evaluation(member, reason="join")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return
        # Membership Screening vient d'être accepté : recontrôle automatique, sans bouton.
        if bool(getattr(before, "pending", False)) and not bool(getattr(after, "pending", False)):
            pending = await self.bot.db.fetchone(
                "SELECT 1 FROM honeypot_pending_members WHERE guild_id=? AND user_id=?",
                (after.guild.id, after.id),
            )
            if pending:
                self.schedule_evaluation(after, reason="screening-complete")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        key = (member.guild.id, member.id)
        task = self._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
        try:
            await self._clear_pending(member.guild.id, member.id)
            await self._event(member.guild.id, member.id, "leave")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        conf = await self.config(channel.guild.id)
        if conf is None:
            return
        excluded = {int(conf["category_id"] or 0), int(conf["verify_channel_id"] or 0), int(conf["trap_channel_id"] or 0)}
        if channel.id in excluded:
            return
        role = channel.guild.get_role(conf["unverified_role_id"]) if conf["unverified_role_id"] else None
        if role:
            try:
                await channel.set_permissions(role, overwrite=self._blocked_overwrite(), reason="SentriX : salon protégé avant vérification")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or not isinstance(message.author, discord.Member):
            return
        conf = await self.config(message.guild.id)
        if conf is None or message.channel.id != int(conf["trap_channel_id"] or 0):
            return
        member = message.author
        if member.id == message.guild.owner_id or member.guild_permissions.administrator or await self._trusted(member):
            return
        role = message.guild.get_role(conf["unverified_role_id"]) if conf["unverified_role_id"] else None
        if role is None or role not in member.roles:
            return
        key = (message.guild.id, member.id)
        if key in self._trap_locks:
            return
        self._trap_locks.add(key)
        try:
            await self._event(message.guild.id, member.id, "honeypot")
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass
            sanction = str(conf["sanction"] or "softban")
            if sanction == "kick":
                try:
                    await member.kick(reason="SentriX Honeypot anti-bot")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            else:
                try:
                    await message.guild.ban(member, reason="SentriX Honeypot anti-bot", delete_message_seconds=0)
                    await message.guild.unban(member, reason="SentriX Honeypot : softban terminé")
                except (discord.Forbidden, discord.HTTPException):
                    pass
        finally:
            self._trap_locks.discard(key)


async def install(bot: commands.Bot) -> AutomaticVerification:
    """Remplace proprement l'ancien cog challenge par l'autorité V4 compatible."""
    existing = bot.get_cog(_COG_NAME)
    if isinstance(existing, AutomaticVerification):
        await existing.ensure_schema()
        return existing
    if existing is not None:
        await bot.remove_cog(_COG_NAME)
    cog = AutomaticVerification(bot)
    await bot.add_cog(cog)
    await cog.ensure_schema()
    bot._sentrix_automatic_verification_v4 = True
    logger.info("Vérification automatique V4 chargée : 20 facteurs, seuil minimum 16/20.")
    return cog


__all__ = [
    "AutomaticVerification",
    "Factor",
    "FACTOR_COUNT",
    "MIN_THRESHOLD",
    "DEFAULT_THRESHOLD",
    "score_factors",
    "clamp_threshold",
    "install",
]
