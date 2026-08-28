"""SentriX V5 — vérification adaptative à 40 signaux.

Le score reste sur 20 points pour préserver le contrat du Setup (16..20), mais il est
calculé à partir de 40 signaux regroupés en familles plafonnées. Les signaux corrélés
(par exemple plusieurs seuils d'ancienneté) ne peuvent donc plus dominer le résultat.

Principes de sûreté :
- un signal indisponible est neutre, jamais traité comme un échec ;
- les comptes limites sont réévalués après une courte observation ;
- un score faible ne bannit/expulse jamais : il laisse le membre Non vérifié ;
- le honeypot reste la seule protection capable d'appliquer la sanction configurée.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

import discord
from discord.ext import commands

from utils import helpers
from . import automatic_verification_v4 as v4
from . import setup_control_center as setup_ui

logger = logging.getLogger("bot.security.auto-verification-v5")

_COG_NAME = v4._COG_NAME
FACTOR_COUNT = 20  # échelle de score compatible avec le Setup
SIGNAL_COUNT = 40
MIN_THRESHOLD = v4.MIN_THRESHOLD
DEFAULT_THRESHOLD = v4.DEFAULT_THRESHOLD
MAX_THRESHOLD = v4.MAX_THRESHOLD
INITIAL_EVALUATION_DELAY_SECONDS = 7
FOLLOWUP_EVALUATION_DELAY_SECONDS = 28
BORDERLINE_MARGIN = 2.0
UNKNOWN_VALUE = 0.5

GROUP_BUDGETS: dict[str, float] = {
    "identity": 3.0,
    "maturity": 2.0,
    "session": 2.5,
    "roles": 2.5,
    "history": 3.0,
    "raid": 2.0,
    "behavior": 2.5,
    "trust": 2.5,
}

_INVITE_RE = re.compile(r"(?:discord\.gg/|discord(?:app)?\.com/invite/)", re.IGNORECASE)
_LINK_RE = re.compile(r"https?://", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")

_BADGE_FLAGS = (
    "staff",
    "partner",
    "bug_hunter",
    "bug_hunter_level_2",
    "hypesquad",
    "hypesquad_bravery",
    "hypesquad_brilliance",
    "hypesquad_balance",
    "early_supporter",
    "verified_bot_developer",
    "active_developer",
)


@dataclass(frozen=True)
class Signal:
    key: str
    label: str
    passed: bool | None
    group: str
    weight: float = 1.0
    detail: str = ""
    available: bool = True
    critical: bool = False


def clamp_threshold(value: int | str | None) -> int:
    return v4.clamp_threshold(value)


def _signal_value(signal: Signal) -> float:
    if not signal.available or signal.passed is None:
        return UNKNOWN_VALUE
    return 1.0 if signal.passed else 0.0


def score_breakdown(signals: list[Signal]) -> dict[str, float]:
    if len(signals) != SIGNAL_COUNT:
        raise ValueError(f"SentriX V5 exige exactement {SIGNAL_COUNT} signaux, reçu {len(signals)}")

    by_group: dict[str, list[Signal]] = {group: [] for group in GROUP_BUDGETS}
    for signal in signals:
        if signal.group not in GROUP_BUDGETS:
            raise ValueError(f"Groupe inconnu pour {signal.key}: {signal.group}")
        by_group[signal.group].append(signal)

    breakdown: dict[str, float] = {}
    for group, budget in GROUP_BUDGETS.items():
        items = by_group[group]
        if not items:
            raise ValueError(f"Aucun signal dans le groupe {group}")
        total_weight = sum(max(0.01, float(item.weight)) for item in items)
        earned = sum(
            max(0.01, float(item.weight)) * _signal_value(item)
            for item in items
        )
        breakdown[group] = round(budget * (earned / total_weight), 3)
    return breakdown


def score_signals(
    signals: list[Signal],
    threshold: int = DEFAULT_THRESHOLD,
) -> tuple[float, bool]:
    threshold = clamp_threshold(threshold)
    breakdown = score_breakdown(signals)
    score = round(sum(breakdown.values()), 2)
    blocker = any(
        signal.critical
        and signal.available
        and signal.passed is False
        for signal in signals
    )
    return score, bool(score >= threshold and not blocker)


# Alias explicite pour les futurs tests/outils qui cherchent encore score_factors.
score_factors = score_signals


class AutomaticVerificationV5(v4.AutomaticVerification, name=_COG_NAME):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self._followup_tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._behavior: dict[tuple[int, int], dict[str, Any]] = {}

    def _behavior_state(self, member: discord.Member) -> dict[str, Any]:
        key = (member.guild.id, member.id)
        state = self._behavior.get(key)
        if state is None:
            state = {
                "messages": deque(maxlen=30),
                "fingerprints": deque(maxlen=30),
                "mass_mentions": False,
                "invite_early": False,
                "external_link_early": False,
                "duplicate_burst": False,
                "message_burst": False,
            }
            self._behavior[key] = state
        return state

    @staticmethod
    def _adaptive_join_limits(guild: discord.Guild) -> tuple[int, int, int]:
        members = max(1, int(guild.member_count or 1))
        five = min(20, max(4, (members + 4999) // 5000))
        twenty = min(40, max(8, (members + 2499) // 2500))
        sixty = min(80, max(15, (members + 999) // 1000))
        return five, twenty, sixty

    async def collect_factors(self, member: discord.Member) -> list[Signal]:
        now = discord.utils.utcnow()
        now_ts = int(time.time())
        settings = await self.settings(member.guild.id)
        conf = await self.config(member.guild.id, enabled_only=False)

        created = member.created_at
        joined_at = member.joined_at
        age_seconds = max(0, int((now - created).total_seconds()))
        joined_age = max(0, int((now - joined_at).total_seconds())) if joined_at else 0
        min_age = max(0, int(settings["min_account_age_minutes"]) * 60)
        trusted = await self._trusted(member)
        pending = bool(getattr(member, "pending", False))
        timeout_until = getattr(member, "timed_out_until", None)
        timed_out = bool(timeout_until and timeout_until > now)

        try:
            snowflake_created = discord.utils.snowflake_time(member.id)
            snowflake_ok = abs((snowflake_created - created).total_seconds()) <= 300
        except Exception:
            snowflake_ok = False

        public_flags = getattr(member, "public_flags", None)
        badge_present = bool(
            public_flags
            and any(bool(getattr(public_flags, flag, False)) for flag in _BADGE_FLAGS)
        )

        since_join = int(joined_at.timestamp()) if joined_at else now_ts - 3600
        joins_10m = await self._event_count(
            member.guild.id, user_id=member.id, kind="join", since=now_ts - 600
        )
        joins_1h = await self._event_count(
            member.guild.id, user_id=member.id, kind="join", since=now_ts - 3600
        )
        honeypot_session = await self._event_count(
            member.guild.id, user_id=member.id, kind="honeypot", since=since_join
        )
        honeypot_30d = await self._event_count(
            member.guild.id, user_id=member.id, kind="honeypot", since=now_ts - 30 * 86400
        )
        low_24h = await self._event_count(
            member.guild.id, user_id=member.id, kind="low_score", since=now_ts - 86400
        )
        low_30d = await self._event_count(
            member.guild.id, user_id=member.id, kind="low_score", since=now_ts - 30 * 86400
        )
        security_24h = await self._event_count(
            member.guild.id, user_id=member.id, kind="security_negative", since=now_ts - 86400
        )
        security_30d = await self._event_count(
            member.guild.id, user_id=member.id, kind="security_negative", since=now_ts - 30 * 86400
        )

        prior = await self.bot.db.fetchone(
            "SELECT 1 FROM honeypot_verified_members WHERE guild_id=? AND user_id=?",
            (member.guild.id, member.id),
        )
        prior_verified = bool(prior)

        guild_join_5s = await self._event_count(member.guild.id, kind="join", since=now_ts - 5)
        guild_join_20s = await self._event_count(member.guild.id, kind="join", since=now_ts - 20)
        guild_join_60s = await self._event_count(member.guild.id, kind="join", since=now_ts - 60)
        guild_honeypot_60s = await self._event_count(
            member.guild.id, kind="honeypot", since=now_ts - 60
        )
        guild_low_60s = await self._event_count(
            member.guild.id, kind="low_score", since=now_ts - 60
        )
        limit_5, limit_20, limit_60 = self._adaptive_join_limits(member.guild)

        roles = [
            role
            for role in getattr(member, "roles", [])
            if role != member.guild.default_role
        ]
        has_admin = any(role.permissions.administrator for role in roles)
        has_manage_guild = any(role.permissions.manage_guild for role in roles)
        has_role_or_channel_admin = any(
            role.permissions.manage_roles or role.permissions.manage_channels
            for role in roles
        )

        verified_role = None
        unverified_role = None
        if conf:
            if conf["verified_role_id"]:
                verified_role = member.guild.get_role(int(conf["verified_role_id"]))
            if conf["unverified_role_id"]:
                unverified_role = member.guild.get_role(int(conf["unverified_role_id"]))
        verified_preassigned = bool(verified_role and verified_role in roles)
        unverified_expected = bool(unverified_role)
        unverified_present = bool(unverified_role and unverified_role in roles)
        role_state_ok = trusted or prior_verified or not verified_preassigned
        unverified_state_ok = (not unverified_expected) or unverified_present or prior_verified or trusted

        behavior = self._behavior.get((member.guild.id, member.id), {})
        messages = list(behavior.get("messages", ()))
        observed_behavior = bool(messages) or joined_age >= 20

        signals = [
            # Identité — 6
            Signal("human", "Compte humain", not member.bot, "identity", 2.0, critical=True),
            Signal("not_system", "Compte non système", not bool(getattr(member, "system", False)), "identity", 1.5, critical=True),
            Signal("snowflake", "Timestamp Discord cohérent", snowflake_ok, "identity", 1.5),
            Signal("join_after_creation", "Arrivée postérieure à la création", bool(joined_at and joined_at >= created), "identity", 1.25, available=joined_at is not None),
            Signal("avatar", "Profil avec avatar", getattr(member, "avatar", None) is not None, "identity", 0.4),
            Signal("badge", "Badge Discord établi", True if badge_present else None, "identity", 0.35, available=badge_present),

            # Ancienneté — 6 ; budget total plafonné à 2 points
            Signal("age_configured", "Ancienneté minimale configurée", age_seconds >= min_age, "maturity", 1.75, f"{age_seconds // 60} min / {min_age // 60} min"),
            Signal("age_1h", "Compte âgé d'au moins 1 heure", age_seconds >= 3600, "maturity", 0.5),
            Signal("age_1d", "Compte âgé d'au moins 1 jour", age_seconds >= 86400, "maturity", 0.75),
            Signal("age_7d", "Compte âgé d'au moins 7 jours", age_seconds >= 7 * 86400, "maturity", 1.0),
            Signal("age_30d", "Compte âgé d'au moins 30 jours", age_seconds >= 30 * 86400, "maturity", 1.0),
            Signal("age_90d", "Compte âgé d'au moins 90 jours", age_seconds >= 90 * 86400, "maturity", 0.75),

            # Session / onboarding — 5
            Signal("screening", "Règles Discord validées", not pending, "session", 2.0, critical=False),
            Signal("joined_at", "Date d'arrivée disponible", joined_at is not None, "session", 0.75),
            Signal("stability", "Session stable après arrivée", joined_age >= 3, "session", 1.0, f"{joined_age}s", available=joined_at is not None),
            Signal("not_timed_out", "Aucun timeout actif", not timed_out, "session", 1.5, critical=timed_out),
            Signal("honeypot_session", "Aucun honeypot sur cette session", honeypot_session == 0, "session", 2.25, critical=honeypot_session > 0),

            # Rôles / privilèges — 4
            Signal("no_admin", "Aucun rôle administrateur inattendu", trusted or not has_admin, "roles", 2.5, critical=has_admin and not trusted),
            Signal("no_manage_guild", "Aucun privilège Gérer le serveur inattendu", trusted or not has_manage_guild, "roles", 1.5),
            Signal("no_role_channel_admin", "Aucun privilège rôles/salons inattendu", trusted or not has_role_or_channel_admin, "roles", 1.5),
            Signal("verification_roles", "État des rôles de vérification cohérent", role_state_ok and unverified_state_ok, "roles", 1.5),

            # Historique — 7
            Signal("no_honeypot_30d", "Aucun honeypot récent", honeypot_30d == 0, "history", 2.0),
            Signal("no_low_24h", "Aucun score faible sur 24 h", low_24h == 0, "history", 1.0),
            Signal("low_30d", "Pas d'échecs répétés sur 30 j", low_30d < 3, "history", 1.0, f"{low_30d} échec(s)"),
            Signal("security_24h", "Aucun incident sécurité sur 24 h", trusted or security_24h == 0, "history", 1.25),
            Signal("security_30d", "Historique sécurité récent propre", trusted or security_30d < 2, "history", 1.0),
            Signal("rejoin_10m", "Pas de boucle de réentrée sur 10 min", joins_10m <= 1, "history", 1.25, f"{joins_10m} entrée(s)"),
            Signal("rejoin_1h", "Pas de boucle de réentrée sur 1 h", joins_1h <= 2, "history", 1.0, f"{joins_1h} entrée(s)"),

            # Contexte de raid — 5 ; seuils adaptés à la taille du serveur
            Signal("raid_5s", "Rafale 5 s normale", guild_join_5s < limit_5, "raid", 1.0, f"{guild_join_5s}/{limit_5}"),
            Signal("raid_20s", "Rafale 20 s normale", guild_join_20s < limit_20, "raid", 1.5, f"{guild_join_20s}/{limit_20}"),
            Signal("raid_60s", "Rafale 60 s normale", guild_join_60s < limit_60, "raid", 1.0, f"{guild_join_60s}/{limit_60}"),
            Signal("raid_honeypot", "Pas de vague honeypot serveur", guild_honeypot_60s < 3, "raid", 1.5, f"{guild_honeypot_60s}/min"),
            Signal("raid_low_scores", "Pas de vague de scores faibles", guild_low_60s < 5, "raid", 1.0, f"{guild_low_60s}/min"),

            # Comportement précoce — 5 ; neutre tant qu'il n'y a pas assez d'observation
            Signal("message_burst", "Pas de rafale de messages", not bool(behavior.get("message_burst")), "behavior", 1.5, available=observed_behavior),
            Signal("mass_mentions", "Pas de mentions massives", not bool(behavior.get("mass_mentions")), "behavior", 2.0, available=observed_behavior),
            Signal("invite_early", "Pas d'invitation Discord immédiate", not bool(behavior.get("invite_early")), "behavior", 1.5, available=observed_behavior),
            Signal("external_link", "Pas de lien externe immédiat", not bool(behavior.get("external_link_early")), "behavior", 0.75, available=observed_behavior),
            Signal("duplicate_burst", "Pas de messages dupliqués en rafale", not bool(behavior.get("duplicate_burst")), "behavior", 2.0, available=observed_behavior),

            # Confiance positive — 2 ; absence = neutre, jamais négative
            Signal("prior_verified", "Déjà vérifié sainement sur ce serveur", True if prior_verified else None, "trust", 2.0, available=prior_verified),
            Signal("trusted", "Membre explicitement de confiance", True if trusted else None, "trust", 2.0, available=trusted),
        ]

        if len(signals) != SIGNAL_COUNT:
            raise RuntimeError(f"Contrat {SIGNAL_COUNT} signaux cassé: {len(signals)}")
        return signals

    async def _save_result(
        self,
        member: discord.Member,
        score: float,
        threshold: int,
        status: str,
        factors: list[Signal],
    ) -> None:
        breakdown = score_breakdown(factors)
        payload = json.dumps(
            {
                "engine": "v5-40-signals",
                "score_scale": FACTOR_COUNT,
                "signal_count": SIGNAL_COUNT,
                "groups": breakdown,
                "signals": [
                    {
                        "key": signal.key,
                        "label": signal.label,
                        "passed": signal.passed,
                        "available": signal.available,
                        "group": signal.group,
                        "weight": signal.weight,
                        "critical": signal.critical,
                        "detail": signal.detail,
                    }
                    for signal in factors
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await self.bot.db.execute(
            "INSERT INTO automatic_verification_results_v4(guild_id,user_id,score,threshold,status,factors_json,evaluated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
            "score=excluded.score,threshold=excluded.threshold,status=excluded.status,"
            "factors_json=excluded.factors_json,evaluated_at=excluded.evaluated_at",
            (
                member.guild.id,
                member.id,
                float(score),
                int(threshold),
                status,
                payload,
                int(time.time()),
            ),
        )

    async def _log_result(
        self,
        member: discord.Member,
        score: float,
        threshold: int,
        status: str,
        factors: list[Signal],
    ) -> None:
        failed = [
            signal.label
            for signal in factors
            if signal.available and signal.passed is False
        ]
        unknown = sum(1 for signal in factors if not signal.available or signal.passed is None)
        blockers = [
            signal.label
            for signal in factors
            if signal.critical and signal.available and signal.passed is False
        ]
        colour = discord.Color.green() if status == "verified" else discord.Color.orange()
        embed = discord.Embed(
            title="SentriX • Vérification adaptative",
            description=(
                f"{member.mention} (`{member.id}`) — **{score:.2f}/20** "
                f"• seuil **{threshold}/20** • **{SIGNAL_COUNT} signaux**"
            ),
            colour=colour,
        )
        decision = (
            "Vérifié automatiquement"
            if status == "verified"
            else "Reste Non vérifié — revue staff possible"
        )
        embed.add_field(name="Décision", value=decision, inline=False)
        if blockers:
            embed.add_field(
                name="Blocage fort",
                value="\n".join(f"• {item}" for item in blockers)[:1024],
                inline=False,
            )
        embed.add_field(
            name="Signaux non validés",
            value="\n".join(f"• {item}" for item in failed)[:1024] or "Aucun",
            inline=False,
        )
        embed.add_field(
            name="Signaux neutres / non disponibles",
            value=str(unknown),
            inline=True,
        )
        embed.add_field(
            name="Moteur",
            value="8 familles pondérées • score normalisé sur 20",
            inline=True,
        )
        settings = await self.settings(member.guild.id)
        channel = member.guild.get_channel(settings.get("log_channel_id") or 0)
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            except discord.HTTPException:
                pass
        try:
            await helpers.send_log(self.bot, member.guild, "automod", embed)
        except Exception:
            logger.exception("Impossible d'envoyer le log de vérification V5")

    def _schedule_followup(self, member: discord.Member) -> None:
        key = (member.guild.id, member.id)
        old = self._followup_tasks.pop(key, None)
        if old and not old.done():
            old.cancel()

        async def runner() -> None:
            try:
                await asyncio.sleep(FOLLOWUP_EVALUATION_DELAY_SECONDS)
                fresh = member.guild.get_member(member.id)
                if fresh is not None:
                    await self.evaluate_member(fresh, reason="adaptive-followup")
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Échec du second contrôle V5 pour %s", member.id)
            finally:
                self._followup_tasks.pop(key, None)

        self._followup_tasks[key] = asyncio.create_task(runner())

    async def evaluate_member(
        self,
        member: discord.Member,
        *,
        reason: str = "auto",
    ) -> tuple[float, bool] | None:
        conf = await self.config(member.guild.id)
        if conf is None or member.bot:
            return None
        if bool(getattr(member, "pending", False)):
            return None

        factors = await self.collect_factors(member)
        settings = await self.settings(member.guild.id)
        threshold = clamp_threshold(settings["threshold"])
        score, passed = score_signals(factors, threshold)

        if not passed:
            if reason != "adaptive-followup" and score >= threshold - BORDERLINE_MARGIN:
                await self._save_result(
                    member, score, threshold, "pending_recheck", factors
                )
                self._schedule_followup(member)
                return score, False

            await self._save_result(member, score, threshold, "review", factors)
            await self._event(member.guild.id, member.id, "low_score")
            await self._log_result(member, score, threshold, "review", factors)
            return score, False

        unverified = (
            member.guild.get_role(conf["unverified_role_id"])
            if conf["unverified_role_id"]
            else None
        )
        verified = (
            member.guild.get_role(conf["verified_role_id"])
            if conf["verified_role_id"]
            else None
        )
        if verified is None:
            await self._save_result(member, score, threshold, "review", factors)
            return score, False

        try:
            if verified not in member.roles:
                await member.add_roles(
                    verified,
                    reason=f"SentriX V5 : vérification adaptative {score:.2f}/20",
                )
            if unverified and unverified in member.roles:
                await member.remove_roles(
                    unverified,
                    reason="SentriX V5 : vérification adaptative réussie",
                )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Impossible d'appliquer les rôles de vérification à %s", member.id)
            await self._save_result(member, score, threshold, "review", factors)
            return score, False

        await self._clear_pending(member.guild.id, member.id)
        account_age = max(
            0, int((discord.utils.utcnow() - member.created_at).total_seconds())
        )
        await self.bot.db.execute(
            "INSERT INTO honeypot_verified_members(guild_id,user_id,verified_at,method,account_age_seconds) "
            "VALUES(?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
            "verified_at=excluded.verified_at,method=excluded.method,"
            "account_age_seconds=excluded.account_age_seconds",
            (
                member.guild.id,
                member.id,
                int(time.time()),
                f"adaptive-v5-{score:.2f}-of-20",
                account_age,
            ),
        )
        try:
            await self.bot.db.execute(
                "INSERT OR IGNORE INTO verified_users(guild_id,user_id,verified_at) "
                "VALUES(?,?,strftime('%s','now'))",
                (member.guild.id, member.id),
            )
        except Exception:
            pass

        await self._save_result(member, score, threshold, "verified", factors)
        await self._event(member.guild.id, member.id, "verified")
        await self._log_result(member, score, threshold, "verified", factors)
        self._behavior.pop((member.guild.id, member.id), None)
        return score, True

    def schedule_evaluation(
        self,
        member: discord.Member,
        *,
        reason: str = "auto",
    ) -> None:
        key = (member.guild.id, member.id)
        old = self._tasks.pop(key, None)
        if old and not old.done():
            old.cancel()

        async def runner() -> None:
            try:
                await asyncio.sleep(INITIAL_EVALUATION_DELAY_SECONDS)
                fresh = member.guild.get_member(member.id)
                if fresh is not None:
                    await self.evaluate_member(fresh, reason=reason)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Échec évaluation adaptative de %s", member.id)
            finally:
                self._tasks.pop(key, None)

        self._tasks[key] = asyncio.create_task(runner())

    async def create_or_refresh_system(
        self,
        guild: discord.Guild,
        *,
        sanction: str = "softban",
    ):
        result, error = await super().create_or_refresh_system(guild, sanction=sanction)
        if error or result is None:
            return result, error

        settings = await self.settings(guild.id)
        verify = result["verify"]
        try:
            await verify.purge(
                limit=20,
                check=lambda message: (
                    self.bot.user is not None
                    and message.author.id == self.bot.user.id
                ),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        info = discord.Embed(
            title="SentriX • Vérification adaptative",
            description=(
                "Tu n'as **rien à faire**. SentriX analyse **40 signaux** répartis "
                "dans **8 familles pondérées** et produit un score normalisé sur **20**.\n\n"
                f"Seuil actuel : **{settings['threshold']}/20**. Les signaux indisponibles "
                "sont neutres et les comptes limites sont réévalués automatiquement. "
                "Un score insuffisant ne bannit jamais le membre."
            ),
            colour=discord.Color.blurple(),
        )
        info.add_field(
            name="Familles analysées",
            value=(
                "Identité • ancienneté • onboarding • rôles/permissions • historique "
                "• contexte de raid • comportement précoce • confiance"
            ),
            inline=False,
        )
        info.set_footer(
            text="SentriX • 40 signaux • aucun captcha • score faible = revue, jamais ban"
        )
        try:
            await verify.send(embed=info)
        except discord.HTTPException:
            pass
        return result, None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await super().on_member_join(member)

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ):
        await super().on_member_update(before, after)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        key = (member.guild.id, member.id)
        task = self._followup_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()
        self._behavior.pop(key, None)
        await super().on_member_remove(member)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await super().on_guild_channel_create(channel)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # L'ancien moteur conserve l'autorité du honeypot.
        await super().on_message(message)

        if (
            message.guild is None
            or message.author.bot
            or not isinstance(message.author, discord.Member)
        ):
            return

        member = message.author
        conf = await self.config(message.guild.id)
        if conf is None:
            return
        if message.channel.id == int(conf["trap_channel_id"] or 0):
            return

        joined_at = member.joined_at
        if joined_at is None:
            return
        joined_age = max(
            0,
            int((discord.utils.utcnow() - joined_at).total_seconds()),
        )
        if joined_age > 300:
            return

        unverified = (
            message.guild.get_role(conf["unverified_role_id"])
            if conf["unverified_role_id"]
            else None
        )
        if unverified is not None and unverified not in member.roles:
            return

        state = self._behavior_state(member)
        now = time.monotonic()
        state["messages"].append(now)

        recent_5s = [stamp for stamp in state["messages"] if now - stamp <= 5]
        if len(recent_5s) >= 5:
            state["message_burst"] = True

        mentions = (
            len(getattr(message, "mentions", ()))
            + len(getattr(message, "role_mentions", ()))
        )
        if getattr(message, "mention_everyone", False) or mentions >= 5:
            state["mass_mentions"] = True

        content = str(getattr(message, "content", "") or "")
        if content and joined_age <= 60:
            if _INVITE_RE.search(content):
                state["invite_early"] = True
            if _LINK_RE.search(content):
                state["external_link_early"] = True

            normalized = _SPACE_RE.sub(" ", content.casefold()).strip()
            if normalized:
                fingerprint = hashlib.blake2s(
                    normalized.encode("utf-8"),
                    digest_size=8,
                ).hexdigest()
                state["fingerprints"].append((now, fingerprint))
                recent = [
                    fp
                    for stamp, fp in state["fingerprints"]
                    if now - stamp <= 20
                ]
                counts = Counter(recent)
                if counts and max(counts.values()) >= 3:
                    state["duplicate_burst"] = True


def _patch_setup_display(bot: commands.Bot) -> None:
    view_cls = setup_ui.SetupView
    current = view_cls.build_embed
    if getattr(current, "_sentrix_auto_verification_v5_display", False):
        return

    async def build_embed(self):
        embed = await current(self)
        if (
            getattr(self, "category", None) == "security"
            and getattr(self, "_v4_subpage", None) == "auto_verification"
        ):
            embed.description = (
                "Aucun captcha ni calcul : SentriX combine **40 signaux** en "
                "**8 familles pondérées**, puis produit un score sur **20**."
            )
            for index in reversed(range(len(embed.fields))):
                name = str(embed.fields[index].name or "").casefold()
                if "20 facteurs" in name or "40 signaux" in name:
                    embed.remove_field(index)
            embed.add_field(
                name="40 signaux intelligents",
                value=(
                    "**Identité (6)** • **Ancienneté (6)** • **Session (5)** • "
                    "**Rôles/permissions (4)** • **Historique (7)** • **Raid (5)** • "
                    "**Comportement (5)** • **Confiance (2)**\n"
                    "Chaque famille est plafonnée : plusieurs signaux similaires ne "
                    "peuvent plus dominer artificiellement le score."
                ),
                inline=False,
            )
            embed.add_field(
                name="Décision adaptative",
                value=(
                    "Signal indisponible = **neutre** • compte limite = **second contrôle** "
                    "• score insuffisant = **Non vérifié / revue staff**, jamais ban automatique."
                ),
                inline=False,
            )
        return embed

    build_embed._sentrix_auto_verification_v5_display = True
    build_embed._sentrix_original = current
    view_cls.build_embed = build_embed
    bot._sentrix_auto_verification_v5_display = True


async def install(bot: commands.Bot) -> AutomaticVerificationV5:
    existing = bot.get_cog(_COG_NAME)
    if isinstance(existing, AutomaticVerificationV5):
        await existing.ensure_schema()
        _patch_setup_display(bot)
        return existing

    if existing is not None:
        await bot.remove_cog(_COG_NAME)

    cog = AutomaticVerificationV5(bot)
    await bot.add_cog(cog)
    await cog.ensure_schema()
    _patch_setup_display(bot)
    bot._sentrix_automatic_verification_v5 = True
    logger.info(
        "Vérification adaptative V5 chargée : 40 signaux, 8 familles, score sur 20."
    )
    return cog


__all__ = [
    "AutomaticVerificationV5",
    "Signal",
    "SIGNAL_COUNT",
    "FACTOR_COUNT",
    "GROUP_BUDGETS",
    "score_signals",
    "score_factors",
    "score_breakdown",
    "clamp_threshold",
    "install",
]
