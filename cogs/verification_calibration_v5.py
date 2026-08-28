"""Calibration réelle du moteur de vérification adaptative SentriX V5.

Objectif : mesurer V5 sur 1 000 vraies évaluations Discord, sans créer de faux comptes
et sans modifier les sanctions. Chaque paire serveur/membre occupe au maximum une place ;
les réévaluations mettent à jour le même échantillon.

La précision n'est calculée que sur les échantillons auxquels un membre du staff a donné
une vérité terrain (`legit` ou `suspect`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import discord
from discord.ext import commands

from . import automatic_verification_v5 as v5

logger = logging.getLogger("bot.security.verification-calibration-v5")

CALIBRATION_TARGET = 1000
_CALIBRATION_COG = "VerificationCalibrationV5"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS automatic_verification_calibration_v5 (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    predicted_status TEXT NOT NULL,
    score REAL NOT NULL,
    threshold INTEGER NOT NULL,
    factors_json TEXT NOT NULL,
    staff_label TEXT,
    staff_label_by INTEGER,
    staff_label_at INTEGER,
    PRIMARY KEY (guild_id, user_id)
)
"""


def _get(row: Any, key: str, index: int = 0, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        pass
    try:
        return row[index]
    except (TypeError, IndexError):
        return default


def _prediction(status: str) -> str | None:
    if status == "verified":
        return "legit"
    if status == "review":
        return "suspect"
    return None


def _factors_payload(factors: list[v5.Signal]) -> str:
    return json.dumps(
        {
            "engine": "v5-40-signals",
            "signal_count": v5.SIGNAL_COUNT,
            "groups": v5.score_breakdown(factors),
            "signals": [
                {
                    "key": signal.key,
                    "passed": signal.passed,
                    "available": signal.available,
                    "group": signal.group,
                    "weight": signal.weight,
                    "critical": signal.critical,
                }
                for signal in factors
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


class VerificationCalibrationV5(commands.Cog, name=_CALIBRATION_COG):
    """Collecte et revue des 1 000 vraies évaluations V5."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()

    async def record(
        self,
        member: discord.Member,
        score: float,
        threshold: int,
        status: str,
        factors: list[v5.Signal],
    ) -> None:
        if member.bot or bool(getattr(member, "system", False)):
            return

        now = int(time.time())
        payload = _factors_payload(factors)
        async with self._lock:
            existing = await self.bot.db.fetchone(
                "SELECT 1 FROM automatic_verification_calibration_v5 "
                "WHERE guild_id=? AND user_id=?",
                (member.guild.id, member.id),
            )

            if existing is None:
                count_row = await self.bot.db.fetchone(
                    "SELECT COUNT(*) AS c FROM automatic_verification_calibration_v5"
                )
                enrolled = int(_get(count_row, "c", 0, 0) or 0)
                if enrolled >= CALIBRATION_TARGET:
                    return
                await self.bot.db.execute(
                    "INSERT INTO automatic_verification_calibration_v5 "
                    "(guild_id,user_id,first_seen_at,last_seen_at,predicted_status,score,threshold,factors_json) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        member.guild.id,
                        member.id,
                        now,
                        now,
                        status,
                        float(score),
                        int(threshold),
                        payload,
                    ),
                )
                enrolled += 1
                if enrolled == 1 or enrolled % 25 == 0 or enrolled == CALIBRATION_TARGET:
                    logger.info(
                        "Calibration V5 réelle : %s/%s échantillons collectés.",
                        enrolled,
                        CALIBRATION_TARGET,
                    )
            else:
                # Le second contrôle adaptatif remplace le verdict provisoire du même
                # membre ; il ne consomme jamais une deuxième place dans les 1 000.
                await self.bot.db.execute(
                    "UPDATE automatic_verification_calibration_v5 SET "
                    "last_seen_at=?,predicted_status=?,score=?,threshold=?,factors_json=? "
                    "WHERE guild_id=? AND user_id=?",
                    (
                        now,
                        status,
                        float(score),
                        int(threshold),
                        payload,
                        member.guild.id,
                        member.id,
                    ),
                )

    async def stats(self) -> dict[str, Any]:
        rows = await self.bot.db.fetchall(
            "SELECT predicted_status,staff_label FROM automatic_verification_calibration_v5"
        )
        enrolled = len(rows)
        finalized = 0
        reviewed = 0
        correct = 0
        false_accept = 0
        false_reject = 0
        suspect_caught = 0
        legit_accepted = 0

        for row in rows:
            status = str(_get(row, "predicted_status", 0, "") or "")
            truth = _get(row, "staff_label", 1)
            predicted = _prediction(status)
            if predicted is not None:
                finalized += 1
            if truth not in {"legit", "suspect"} or predicted is None:
                continue
            reviewed += 1
            if predicted == truth:
                correct += 1
            if truth == "legit" and predicted == "legit":
                legit_accepted += 1
            elif truth == "legit" and predicted == "suspect":
                false_reject += 1
            elif truth == "suspect" and predicted == "suspect":
                suspect_caught += 1
            elif truth == "suspect" and predicted == "legit":
                false_accept += 1

        return {
            "target": CALIBRATION_TARGET,
            "enrolled": enrolled,
            "finalized": finalized,
            "reviewed": reviewed,
            "correct": correct,
            "accuracy": (correct / reviewed * 100.0) if reviewed else None,
            "legit_accepted": legit_accepted,
            "suspect_caught": suspect_caught,
            "false_accept": false_accept,
            "false_reject": false_reject,
        }

    async def _staff_allowed(self, ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return False
        if ctx.author.id == ctx.guild.owner_id:
            return True
        perms = ctx.author.guild_permissions
        if perms.administrator or perms.manage_guild:
            return True
        try:
            return await self.bot.is_owner(ctx.author)
        except Exception:
            return False

    @commands.command(name="verification-calibration", aliases=["verif-calibration"])
    @commands.guild_only()
    async def verification_calibration(self, ctx: commands.Context) -> None:
        """Affiche l'avancement et la précision réellement mesurée de V5."""
        if not await self._staff_allowed(ctx):
            return await ctx.send("Tu n'as pas la permission de consulter la calibration.")
        data = await self.stats()
        accuracy = (
            f"{data['accuracy']:.2f} %"
            if data["accuracy"] is not None
            else "Pas encore mesurable"
        )
        embed = discord.Embed(
            title="SentriX • Calibration vérification V5",
            description=(
                "Mesure sur de **vraies arrivées Discord**. La précision n'utilise que "
                "les échantillons revus par le staff."
            ),
            colour=discord.Color.blurple(),
        )
        embed.add_field(
            name="Collecte",
            value=f"**{data['enrolled']}/{data['target']}** membres uniques\nFinalisés : **{data['finalized']}**",
            inline=True,
        )
        embed.add_field(
            name="Vérité terrain",
            value=f"Revus par le staff : **{data['reviewed']}**\nPrécision mesurée : **{accuracy}**",
            inline=True,
        )
        embed.add_field(
            name="Erreurs mesurées",
            value=(
                f"Legit refusés : **{data['false_reject']}**\n"
                f"Suspects acceptés : **{data['false_accept']}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Bonnes décisions",
            value=(
                f"Legit acceptés : **{data['legit_accepted']}**\n"
                f"Suspects détectés : **{data['suspect_caught']}**"
            ),
            inline=True,
        )
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="verification-review", aliases=["verif-review"])
    @commands.guild_only()
    async def verification_review(
        self,
        ctx: commands.Context,
        member: discord.Member,
        verdict: str,
    ) -> None:
        """Ajoute la vérité terrain staff : legit ou suspect."""
        if not await self._staff_allowed(ctx):
            return await ctx.send("Tu n'as pas la permission de valider un échantillon.")

        normalized = verdict.casefold().strip()
        aliases = {
            "legit": "legit",
            "legitime": "legit",
            "légitime": "legit",
            "ok": "legit",
            "suspect": "suspect",
            "malveillant": "suspect",
            "bot": "suspect",
            "raid": "suspect",
        }
        label = aliases.get(normalized)
        if label is None:
            return await ctx.send("Verdict invalide : utilise `legit` ou `suspect`.")

        row = await self.bot.db.fetchone(
            "SELECT predicted_status,score FROM automatic_verification_calibration_v5 "
            "WHERE guild_id=? AND user_id=?",
            (ctx.guild.id, member.id),
        )
        if row is None:
            return await ctx.send(
                "Ce membre ne fait pas partie des 1 000 échantillons collectés sur ce serveur."
            )

        await self.bot.db.execute(
            "UPDATE automatic_verification_calibration_v5 SET "
            "staff_label=?,staff_label_by=?,staff_label_at=? "
            "WHERE guild_id=? AND user_id=?",
            (label, ctx.author.id, int(time.time()), ctx.guild.id, member.id),
        )
        status = str(_get(row, "predicted_status", 0, "") or "")
        predicted = _prediction(status) or "en attente du second contrôle"
        await ctx.send(
            f"Échantillon validé : {member.mention} = **{label}**. "
            f"Verdict SentriX : **{predicted}**.",
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def install(bot: commands.Bot) -> None:
    """Installe la collecte après V5 et la rend idempotente."""
    await bot.db.execute(_SCHEMA)

    cog = bot.get_cog(_CALIBRATION_COG)
    if cog is None:
        cog = VerificationCalibrationV5(bot)
        await bot.add_cog(cog)

    current_save = v5.AutomaticVerificationV5._save_result
    if not getattr(current_save, "_sentrix_calibration_1000", False):
        async def save_result(self, member, score, threshold, status, factors):
            await current_save(self, member, score, threshold, status, factors)
            calibration = self.bot.get_cog(_CALIBRATION_COG)
            if calibration is None:
                return
            try:
                await calibration.record(member, score, threshold, status, factors)
            except Exception:
                # Une panne de métrique ne doit jamais bloquer la vérification d'un membre.
                logger.exception("Impossible d'enregistrer l'échantillon de calibration V5")

        save_result._sentrix_calibration_1000 = True
        save_result._sentrix_original = current_save
        v5.AutomaticVerificationV5._save_result = save_result

    bot._sentrix_verification_calibration_target = CALIBRATION_TARGET
    bot._sentrix_verification_calibration_v5 = True
    logger.info("Calibration V5 active : cible=%s vraies évaluations.", CALIBRATION_TARGET)


__all__ = ["CALIBRATION_TARGET", "VerificationCalibrationV5", "install"]
