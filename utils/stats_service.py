"""Service centralisé pour les statistiques membres de SentriX.

V2.2 réduit fortement les allers-retours SQLite du profil : les niveaux, messages, vocal,
économie et réputation sont maintenant lus par une seule requête de snapshot. Les lectures
n'insèrent plus de lignes vides juste pour afficher un profil. Le classement garde son cache
court et les rôles de niveau sont récupérés en une seule requête.
"""

import time
import discord


def xp_required_for_level(level: int) -> int:
    """XP nécessaire pour passer du niveau ``level`` au niveau suivant."""
    level = max(0, int(level))
    return 5 * (level ** 2) + 50 * level + 100


def calculate_level_from_total_xp(total_xp: int) -> tuple[int, int, int]:
    remaining = max(0, int(total_xp))
    level = 0
    needed = xp_required_for_level(level)
    while remaining >= needed:
        remaining -= needed
        level += 1
        needed = xp_required_for_level(level)
    return level, remaining, needed


def total_xp_for(level: int, current_xp: int) -> int:
    level = max(0, int(level))
    total = sum(xp_required_for_level(l) for l in range(level))
    return total + max(0, int(current_xp))


def progress_percent(current: int, needed: int) -> int:
    if needed <= 0:
        return 100
    return max(0, min(100, round((current / needed) * 100)))


def progress_bar(current: int, needed: int, length: int = 10, emoji_filled: str = "🟩", emoji_empty: str = "⬜") -> tuple[str, int]:
    pct = progress_percent(current, needed)
    filled = max(0, min(length, round(length * pct / 100)))
    return emoji_filled * filled + emoji_empty * (length - filled), pct


def format_number(number) -> str:
    try:
        number = int(round(number))
    except (TypeError, ValueError):
        return str(number)
    return f"{number:,}".replace(",", " ")


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3600:
        return f"{seconds // 60} min"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days > 0:
        return f"{days}j {hours}h {minutes}min"
    return f"{hours}h {minutes}min"


RANK_CACHE_TTL = 20


async def get_rank(bot, guild_id: int, user_id: int, level: int, xp: int) -> int:
    cache = getattr(bot, "_rank_cache", None)
    if cache is None:
        cache = bot._rank_cache = {}
    key = (guild_id, user_id)
    cached = cache.get(key)
    now_ts = time.time()
    if cached and now_ts - cached[0] < RANK_CACHE_TTL:
        return cached[1]
    row = await bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM levels WHERE guild_id = ? AND (level > ? OR (level = ? AND xp > ?))",
        (guild_id, level, level, xp),
    )
    rank = int(row["n"] if row else 0) + 1
    cache[key] = (now_ts, rank)
    return rank


def invalidate_rank_cache(bot, guild_id: int, user_id: int | None = None):
    cache = getattr(bot, "_rank_cache", None)
    if not cache:
        return
    if user_id is not None:
        cache.pop((guild_id, user_id), None)
        return
    for key in [key for key in cache if key[0] == guild_id]:
        cache.pop(key, None)


async def _profile_snapshot(db, guild_id: int, user_id: int):
    """Une seule lecture pour les données de profil fréquemment affichées.

    Les sous-requêtes retournent zéro lorsqu'une ligne n'existe pas encore. Une commande de
    consultation ne provoque donc plus plusieurs INSERT OR IGNORE + COMMIT inutiles.
    """
    return await db.fetchone(
        """
        SELECT
          COALESCE((SELECT level FROM levels WHERE guild_id=? AND user_id=?), 0) AS level,
          COALESCE((SELECT xp FROM levels WHERE guild_id=? AND user_id=?), 0) AS xp,
          COALESCE((SELECT count FROM message_counts WHERE guild_id=? AND user_id=?), 0) AS message_count,
          COALESCE((SELECT seconds FROM voice_totals WHERE guild_id=? AND user_id=?), 0) AS voice_seconds,
          (SELECT joined_at FROM voice_sessions WHERE guild_id=? AND user_id=?) AS voice_joined_at,
          COALESCE((SELECT cash FROM economy WHERE guild_id=? AND user_id=?), 0) AS cash,
          COALESCE((SELECT bank FROM economy WHERE guild_id=? AND user_id=?), 0) AS bank,
          COALESCE((SELECT reputation FROM profiles WHERE guild_id=? AND user_id=?), 0) AS reputation
        """,
        (
            guild_id, user_id,
            guild_id, user_id,
            guild_id, user_id,
            guild_id, user_id,
            guild_id, user_id,
            guild_id, user_id,
            guild_id, user_id,
            guild_id, user_id,
        ),
    )


async def get_member_statistics(bot, guild: discord.Guild, member: discord.Member) -> dict:
    """Source unique pour +stats, +level, +profile, +balance et les hubs V2.

    V2.2 : 1 snapshot SQL + 1 requête rôles de niveau + éventuellement 1 requête de rang,
    au lieu d'une succession d'ensure/get qui écrivait et relisait plusieurs tables.
    """
    db = bot.db
    snapshot = await _profile_snapshot(db, guild.id, member.id)
    current_level = int(snapshot["level"] if snapshot else 0)
    current_level_xp = int(snapshot["xp"] if snapshot else 0)
    message_count = int(snapshot["message_count"] if snapshot else 0)
    voice_time = int(snapshot["voice_seconds"] if snapshot else 0)
    voice_joined_at = snapshot["voice_joined_at"] if snapshot else None
    wallet = int(snapshot["cash"] if snapshot else 0)
    bank = int(snapshot["bank"] if snapshot else 0)
    reputation = int(snapshot["reputation"] if snapshot else 0)

    if voice_joined_at:
        from database.db import now as _now
        voice_time += max(0, _now() - int(voice_joined_at))

    required_xp = xp_required_for_level(current_level)
    has_activity = not (current_level == 0 and current_level_xp == 0 and message_count == 0)
    rank = await get_rank(bot, guild.id, member.id, current_level, current_level_xp) if has_activity else None

    role_rows = await db.fetchall(
        "SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC",
        (guild.id,),
    )
    has_any_configured = bool(role_rows)
    role_row = next((row for row in role_rows if int(row["level"]) > current_level), None)
    next_level_role = guild.get_role(int(role_row["role_id"])) if role_row else None
    next_level_requirement = int(role_row["level"]) if role_row else None
    remaining_levels = (
        max(0, next_level_requirement - current_level)
        if next_level_requirement is not None else None
    )
    all_roles_obtained = has_any_configured and role_row is None

    pct = progress_percent(current_level_xp, required_xp)
    total_xp = total_xp_for(current_level, current_level_xp)

    return {
        "wallet": wallet,
        "bank": bank,
        "total_money": wallet + bank,
        "reputation": reputation,
        "current_level": current_level,
        "total_xp": total_xp,
        "current_level_xp": current_level_xp,
        "required_xp": required_xp,
        "next_level_role": next_level_role,
        "next_level_requirement": next_level_requirement,
        "remaining_levels": remaining_levels,
        "all_roles_obtained": all_roles_obtained,
        "has_any_level_role_configured": has_any_configured,
        "rank": rank,
        "message_count": message_count,
        "voice_time": voice_time,
        "is_ranked": has_activity,
        "progress_pct": pct,
        "joined_at": member.joined_at,
        "level": current_level,
        "xp_current": current_level_xp,
        "xp_needed": required_xp,
        "voice_seconds": voice_time,
        "next_role": next_level_role,
        "next_role_level": next_level_requirement,
    }


async def get_category_ranks(bot, guild_id: int, stats: dict) -> dict:
    db = bot.db
    # Un seul aller-retour au lieu de quatre COUNT(*) successifs.
    row = await db.fetchone(
        """
        SELECT
          (SELECT COUNT(*) FROM message_counts WHERE guild_id=? AND count>?) AS message_rank_before,
          (SELECT COUNT(*) FROM voice_totals WHERE guild_id=? AND seconds>?) AS voice_rank_before,
          (SELECT COUNT(*) FROM economy WHERE guild_id=? AND (cash+bank)>?) AS economy_rank_before,
          (SELECT COUNT(*) FROM profiles WHERE guild_id=? AND reputation>?) AS reputation_rank_before
        """,
        (
            guild_id, int(stats.get("message_count", 0)),
            guild_id, int(stats.get("voice_time", 0)),
            guild_id, int(stats.get("total_money", 0)),
            guild_id, int(stats.get("reputation", 0)),
        ),
    )
    return {
        "xp_rank": stats.get("rank"),
        "message_rank": int(row["message_rank_before"] if row else 0) + 1,
        "voice_rank": int(row["voice_rank_before"] if row else 0) + 1,
        "economy_rank": int(row["economy_rank_before"] if row else 0) + 1,
        "reputation_rank": int(row["reputation_rank_before"] if row else 0) + 1,
    }
