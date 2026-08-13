"""Production V9: recommandations de modération basées sur des signaux vérifiables."""

import json

import discord
from discord.ext import commands

from database.db import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS moderation_risk_snapshots_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL,
    confidence REAL NOT NULL,
    recommendation TEXT NOT NULL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moderation_risk_snapshots_v2
ON moderation_risk_snapshots_v2 (guild_id, user_id, created_at);
"""
_INSTALLED = False


async def _count_automod(bot, guild_id: int, user_id: int) -> int:
    try:
        row = await bot.db.fetchone(
            "SELECT COUNT(*) c FROM automod_logs WHERE guild_id=? AND user_id=? AND timestamp>=?",
            (guild_id, user_id, now() - 86400),
        )
        return int(row["c"] or 0) if row else 0
    except Exception:
        return 0


async def calculate_risk(bot, guild_id: int, user_id: int) -> dict:
    sanctions = await bot.db.fetchone(
        "SELECT COUNT(*) c FROM sanctions WHERE guild_id=? AND user_id=? AND created_at>=?",
        (guild_id, user_id, now() - 30 * 86400),
    )
    joins = None
    try:
        joins = await bot.db.fetchone(
            "SELECT score FROM mastery_join_risk WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
            (guild_id, user_id),
        )
    except Exception:
        pass

    sanction_count = int(sanctions["c"] or 0) if sanctions else 0
    automod_count = await _count_automod(bot, guild_id, user_id)
    join_score = int(joins["score"] or 0) if joins else 0

    score = min(100, sanction_count * 14 + min(automod_count, 10) * 5 + min(join_score, 40))
    evidence_count = sanction_count + automod_count + (1 if joins else 0)
    confidence = min(0.95, 0.35 + evidence_count * 0.07)

    reasons = []
    if sanction_count:
        reasons.append(f"{sanction_count} sanction(s) enregistrée(s) sur 30 jours")
    if automod_count:
        reasons.append(f"{automod_count} déclenchement(s) AutoMod sur 24 h")
    if join_score:
        reasons.append(f"score de risque à l'arrivée: {join_score}/100")

    if score < 25:
        recommendation = "Aucune escalade recommandée. Surveillez seulement si nécessaire."
    elif score < 50:
        recommendation = "Vérification humaine recommandée; avertissement uniquement si le contexte le justifie."
    elif score < 75:
        recommendation = "Examinez les preuves et l'historique avant d'envisager une mesure proportionnée."
    else:
        recommendation = "Revue staff prioritaire recommandée. Vérifiez les preuves avant toute décision."

    await bot.db.execute(
        "INSERT INTO moderation_risk_snapshots_v2 "
        "(guild_id,user_id,score,confidence,recommendation,reasons_json,created_at) VALUES (?,?,?,?,?,?,?)",
        (guild_id, user_id, score, confidence, recommendation, json.dumps(reasons, ensure_ascii=False), now()),
    )
    return {
        "score": score,
        "confidence": confidence,
        "recommendation": recommendation,
        "reasons": reasons,
    }


async def security_risk(ctx: commands.Context, member: discord.Member = None):
    if not ctx.guild:
        return await ctx.send("Cette analyse doit être utilisée sur un serveur.")
    if member is None:
        return await ctx.send("Utilisation : `+security risk @membre`.")
    result = await calculate_risk(ctx.bot, ctx.guild.id, member.id)
    reasons = "\n".join(f"- {reason}" for reason in result["reasons"]) or "- Aucun signal récent significatif."
    embed = discord.Embed(
        title=f"Analyse de risque — {member}",
        description=(
            f"Score: **{result['score']}/100**\n"
            f"Confiance des données: **{round(result['confidence'] * 100)}%**\n\n"
            f"Signaux:\n{reasons}\n\n"
            f"Recommandation: {result['recommendation']}"
        ),
        colour=discord.Colour.orange() if result["score"] >= 50 else discord.Colour.blurple(),
    )
    embed.set_footer(text="Aucune sanction automatique — décision humaine obligatoire")
    await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


def install(bot):
    global _INSTALLED
    if _INSTALLED:
        return
    root = bot.get_command("security")
    if not isinstance(root, commands.Group):
        return
    if root.get_command("risk") is None:
        root.add_command(
            commands.Command(
                security_risk,
                name="risk",
                help="Évaluer les signaux récents d'un membre sans sanction automatique.",
            )
        )
    _INSTALLED = True


async def setup(bot):
    conn = getattr(bot.db, "_conn", None)
    if conn is not None:
        await conn.executescript(SCHEMA)
        await conn.commit()
    install(bot)
