"""Production V9: saisons et missions pour les mini-jeux existants."""

from datetime import datetime, timezone

import discord
from discord.ext import commands

from database.db import now

WIN_POINTS = 10
DRAW_POINTS = 3
PLAY_POINTS = 1
MISSION_BONUS = 15
SCHEMA = """
CREATE TABLE IF NOT EXISTS game_season_scores_v2 (
    season_key TEXT NOT NULL,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    plays INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    rewards INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (season_key, guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_game_season_rank_v2
ON game_season_scores_v2 (season_key, guild_id, score DESC, wins DESC);
CREATE TABLE IF NOT EXISTS game_mission_progress_v2 (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    day_key TEXT NOT NULL,
    mission_key TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    target INTEGER NOT NULL,
    bonus_awarded INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, day_key, mission_key)
);
"""
_PATCHED = False


def _season_key():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _day_key():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _multiplier():
    return 2 if datetime.now(timezone.utc).weekday() >= 5 else 1


async def _mission(bot, guild_id, user_id, key, increment, target):
    ts = now()
    day = _day_key()
    await bot.db.execute(
        "INSERT INTO game_mission_progress_v2 (guild_id,user_id,day_key,mission_key,progress,target,bonus_awarded,updated_at) "
        "VALUES (?,?,?,?,?,?,0,?) ON CONFLICT(guild_id,user_id,day_key,mission_key) DO UPDATE SET "
        "progress=MIN(target,progress+excluded.progress),updated_at=excluded.updated_at",
        (guild_id, user_id, day, key, increment, target, ts),
    )
    row = await bot.db.fetchone(
        "SELECT progress,target,bonus_awarded FROM game_mission_progress_v2 "
        "WHERE guild_id=? AND user_id=? AND day_key=? AND mission_key=?",
        (guild_id, user_id, day, key),
    )
    if row and int(row["progress"]) >= int(row["target"]) and not int(row["bonus_awarded"]):
        cur = await bot.db.execute(
            "UPDATE game_mission_progress_v2 SET bonus_awarded=1,updated_at=? "
            "WHERE guild_id=? AND user_id=? AND day_key=? AND mission_key=? AND bonus_awarded=0",
            (ts, guild_id, user_id, day, key),
        )
        if int(getattr(cur, "rowcount", 0) or 0) > 0:
            await bot.db.execute(
                "UPDATE game_season_scores_v2 SET score=score+?,updated_at=? "
                "WHERE season_key=? AND guild_id=? AND user_id=?",
                (MISSION_BONUS, ts, _season_key(), guild_id, user_id),
            )


def _install_reward_hook(bot):
    global _PATCHED
    if _PATCHED:
        return
    from utils import game_rewards
    current = game_rewards.reward_game_winner
    if getattr(current, "_sentrix_game_seasons_v9", False):
        _PATCHED = True
        return

    async def reward_with_season(*args, **kwargs):
        reward = await current(*args, **kwargs)
        if not getattr(reward, "success", False):
            return reward
        result = str(reward.result or "").casefold()
        base = WIN_POINTS if result == "win" else (DRAW_POINTS if result == "draw" else PLAY_POINTS)
        ts = now()
        await bot.db.execute(
            "INSERT INTO game_season_scores_v2 (season_key,guild_id,user_id,score,plays,wins,draws,rewards,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(season_key,guild_id,user_id) DO UPDATE SET "
            "score=score+excluded.score,plays=plays+1,wins=wins+excluded.wins,draws=draws+excluded.draws,"
            "rewards=rewards+excluded.rewards,updated_at=excluded.updated_at",
            (_season_key(), reward.guild_id, reward.user_id, base * _multiplier(), 1,
             1 if result == "win" else 0, 1 if result == "draw" else 0,
             max(0, int(reward.amount or 0)), ts),
        )
        await _mission(bot, reward.guild_id, reward.user_id, "play_5", 1, 5)
        if result == "win":
            await _mission(bot, reward.guild_id, reward.user_id, "win_2", 1, 2)
        return reward

    reward_with_season._sentrix_game_seasons_v9 = True
    game_rewards.reward_game_winner = reward_with_season
    _PATCHED = True


class GameSeasonsV9(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="season", aliases=["saison"])
    async def season(self, ctx):
        if not ctx.guild:
            return await ctx.send("Cette commande doit être utilisée sur un serveur.")
        season = _season_key()
        rows = await self.bot.db.fetchall(
            "SELECT user_id,score,wins FROM game_season_scores_v2 WHERE season_key=? AND guild_id=? "
            "ORDER BY score DESC,wins DESC LIMIT 10",
            (season, ctx.guild.id),
        )
        own = await self.bot.db.fetchone(
            "SELECT score,wins,plays FROM game_season_scores_v2 WHERE season_key=? AND guild_id=? AND user_id=?",
            (season, ctx.guild.id, ctx.author.id),
        )
        missions = await self.bot.db.fetchall(
            "SELECT mission_key,progress,target FROM game_mission_progress_v2 WHERE guild_id=? AND user_id=? AND day_key=?",
            (ctx.guild.id, ctx.author.id, _day_key()),
        )
        ranking = []
        for index, row in enumerate(rows, 1):
            member = ctx.guild.get_member(int(row["user_id"]))
            name = member.display_name if member else f"Utilisateur {row['user_id']}"
            ranking.append(f"`#{index}` **{name}** — {row['score']} pts • {row['wins']} victoire(s)")
        progress = {row["mission_key"]: int(row["progress"]) for row in missions}
        embed = discord.Embed(
            title=f"Saison jeux {season}",
            description="\n".join(ranking) if ranking else "Aucun score pour le moment.",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="Votre saison",
            value=f"{int(own['score']) if own else 0} pts • {int(own['wins']) if own else 0} victoire(s) • {int(own['plays']) if own else 0} partie(s)",
            inline=False,
        )
        embed.add_field(
            name="Missions du jour",
            value=f"Jouer 5 parties: **{progress.get('play_5', 0)}/5**\nGagner 2 parties: **{progress.get('win_2', 0)}/2**\nBonus: **+{MISSION_BONUS} pts** par mission",
            inline=False,
        )
        if _multiplier() == 2:
            embed.add_field(name="Événement actif", value="Week-end: **x2 points de saison**.", inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    conn = getattr(bot.db, "_conn", None)
    if conn is not None:
        await conn.executescript(SCHEMA)
        await conn.commit()
    import main
    main.PUBLIC_COMMANDS = main.PUBLIC_COMMANDS | frozenset({"season"})
    main.KNOWN_PERMISSION_COMMANDS = main.KNOWN_PERMISSION_COMMANDS | frozenset({"season"})
    _install_reward_hook(bot)
    await bot.add_cog(GameSeasonsV9(bot))
