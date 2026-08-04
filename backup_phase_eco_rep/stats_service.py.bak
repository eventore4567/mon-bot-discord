"""
Service centralisé pour tout ce qui touche aux statistiques d'un membre : niveau, XP,
classement, messages, temps vocal, économie, réputation.

But de ce fichier : que +stats, +level, +rank, +profile et +leaderboard n'aient plus
JAMAIS à recalculer chacun leur propre version des mêmes chiffres. Toutes les commandes
doivent passer par get_member_statistics() (ou par les fonctions ci-dessous prises
séparément) pour être certaines d'afficher exactement la même chose.

Modèle de stockage choisi : l'XP en base (table `levels`) reste RELATIF au niveau actuel
(comme avant — elle repasse à 0 à chaque niveau gagné), ce qui n'a pas changé pour éviter
une migration de données risquée sur un serveur de 200 000 membres. Le "XP total" demandé
dans le nouveau design est calculé à la volée par total_xp_for() à partir de ce même
stockage : aucune donnée existante n'est perdue ni réinterprétée.
"""

import time
import discord


# ---------------------------------------------------------------------------
# Formules XP — SOURCE UNIQUE. Ne jamais dupliquer ce calcul ailleurs dans le bot.
# ---------------------------------------------------------------------------

def xp_required_for_level(level: int) -> int:
    """XP nécessaire pour passer du niveau `level` au niveau `level + 1`."""
    level = max(0, int(level))
    return 5 * (level ** 2) + 50 * level + 100


def calculate_level_from_total_xp(total_xp: int) -> tuple[int, int, int]:
    """Convertit un total d'XP cumulé en (niveau, xp_actuel_dans_le_niveau, xp_requis_pour_le_prochain).
    Utilisée pour retomber juste après un ajustement manuel d'XP total, ou pour toute
    future fonctionnalité qui raisonnerait en XP cumulé plutôt qu'en XP par palier."""
    remaining = max(0, int(total_xp))
    level = 0
    needed = xp_required_for_level(level)
    while remaining >= needed:
        remaining -= needed
        level += 1
        needed = xp_required_for_level(level)
    return level, remaining, needed


def total_xp_for(level: int, current_xp: int) -> int:
    """XP cumulée totale représentée par (niveau, xp dans ce niveau) — l'inverse de
    calculate_level_from_total_xp(). C'est ce qui alimente le champ "XP total" du profil."""
    level = max(0, int(level))
    total = sum(xp_required_for_level(l) for l in range(level))
    return total + max(0, int(current_xp))


# ---------------------------------------------------------------------------
# Barre de progression
# ---------------------------------------------------------------------------

def progress_bar(current: int, needed: int, length: int = 10, emoji_filled: str = "🟩", emoji_empty: str = "⬜") -> tuple[str, int]:
    """Retourne (barre, pourcentage). Le pourcentage reste toujours entre 0 et 100 ;
    si `current` dépasse `needed` (ne devrait pas arriver, le niveau doit avoir déjà été
    recalculé avant l'affichage), on plafonne à 100 plutôt que d'afficher un nombre absurde."""
    if needed <= 0:
        pct = 100
    else:
        pct = max(0, min(100, round((current / needed) * 100)))
    filled = max(0, min(length, round(length * pct / 100)))
    bar = emoji_filled * filled + emoji_empty * (length - filled)
    return bar, pct


# ---------------------------------------------------------------------------
# Temps vocal — mise en forme
# ---------------------------------------------------------------------------

def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} min"
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days > 0:
        return f"{days}j {hours}h {minutes}min"
    return f"{hours}h {minutes}min"


# ---------------------------------------------------------------------------
# Classement — cache court, invalidé quand l'XP d'un membre change
# ---------------------------------------------------------------------------

RANK_CACHE_TTL = 20  # secondes — court exprès : évite les COUNT(*) répétés lors d'un
                      # enchaînement rapide de commandes, sans jamais afficher un chiffre
                      # vieux de plusieurs minutes.


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
    rank = (row["n"] if row else 0) + 1
    cache[key] = (now_ts, rank)
    return rank


def invalidate_rank_cache(bot, guild_id: int, user_id: int | None = None):
    """À appeler après TOUTE écriture d'XP (message, /add-xp, /set-xp, /reset-levels...).
    Si `user_id` est None, invalide tout le classement du serveur (ex: reset complet)."""
    cache = getattr(bot, "_rank_cache", None)
    if not cache:
        return
    if user_id is not None:
        cache.pop((guild_id, user_id), None)
    else:
        for k in [k for k in cache if k[0] == guild_id]:
            cache.pop(k, None)


# ---------------------------------------------------------------------------
# Service central
# ---------------------------------------------------------------------------

async def get_member_statistics(bot, guild: discord.Guild, member: discord.Member) -> dict:
    """Récupère TOUT ce qu'il faut pour afficher /stats, /level, /profile ou une entrée
    de /leaderboard pour ce membre — une seule fonction, une seule vérité.

    Retourne un dict avec les clés :
    level, xp_current, xp_needed, xp_total, progress_pct, progress_bar_str, rank,
    is_ranked, message_count, voice_seconds, wallet, bank, total_money, reputation,
    joined_at, next_role, next_role_level.
    """
    db = bot.db
    await db.ensure_level(guild.id, member.id)
    level_row = await db.get_level(guild.id, member.id)
    level = level_row["level"]
    xp_current = level_row["xp"]
    needed = xp_required_for_level(level)

    msg_row = await db.fetchone(
        "SELECT count FROM message_counts WHERE guild_id = ? AND user_id = ?", (guild.id, member.id)
    )
    message_count = msg_row["count"] if msg_row else 0

    # Une donnée est considérée "vide" (membre jamais actif) si niveau 0, XP 0 ET aucun
    # message envoyé : dans ce cas précis on affiche "non classé" plutôt qu'un classement
    # qui n'aurait pas vraiment de sens (voir demande explicite de Jayden).
    has_activity = not (level == 0 and xp_current == 0 and message_count == 0)
    rank = await get_rank(bot, guild.id, member.id, level, xp_current) if has_activity else None

    voice_row = await db.fetchone(
        "SELECT seconds FROM voice_totals WHERE guild_id = ? AND user_id = ?", (guild.id, member.id)
    )
    voice_seconds = voice_row["seconds"] if voice_row else 0
    # Si le membre est actuellement en vocal, on ajoute le temps de la session en cours
    # (pas encore "flush" dans voice_totals) pour un affichage en temps réel exact.
    session_row = await db.fetchone(
        "SELECT joined_at FROM voice_sessions WHERE guild_id = ? AND user_id = ?", (guild.id, member.id)
    )
    if session_row:
        from database.db import now as _now
        voice_seconds += max(0, _now() - session_row["joined_at"])

    await db.ensure_economy(guild.id, member.id)
    bal = await db.get_balance(guild.id, member.id)
    reputation = await db.get_reputation(guild.id, member.id)

    role_row = await db.fetchone(
        "SELECT * FROM level_roles WHERE guild_id = ? AND level > ? ORDER BY level ASC LIMIT 1",
        (guild.id, level),
    )
    next_role = None
    next_role_level = None
    if role_row:
        next_role = guild.get_role(role_row["role_id"])
        next_role_level = role_row["level"]

    bar_str, pct = progress_bar(xp_current, needed)

    return {
        "level": level,
        "xp_current": xp_current,
        "xp_needed": needed,
        "xp_total": total_xp_for(level, xp_current),
        "progress_pct": pct,
        "progress_bar": bar_str,
        "rank": rank,
        "is_ranked": has_activity,
        "message_count": message_count,
        "voice_seconds": voice_seconds,
        "wallet": bal["cash"] if bal else 0,
        "bank": bal["bank"] if bal else 0,
        "total_money": (bal["cash"] + bal["bank"]) if bal else 0,
        "reputation": reputation,
        "joined_at": member.joined_at,
        "next_role": next_role,
        "next_role_level": next_role_level,
    }


async def get_category_ranks(bot, guild_id: int, stats: dict) -> dict:
    """Classement du membre dans chaque catégorie (page "🏆 Classement" des boutons de
    /stats). Réutilise les chiffres déjà calculés par get_member_statistics() plutôt que
    de tout recalculer."""
    db = bot.db
    msg_row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM message_counts WHERE guild_id = ? AND count > ?",
        (guild_id, stats["message_count"]),
    )
    voice_row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM voice_totals WHERE guild_id = ? AND seconds > ?",
        (guild_id, stats["voice_seconds"]),
    )
    eco_row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM economy WHERE guild_id = ? AND (cash + bank) > ?",
        (guild_id, stats["total_money"]),
    )
    rep_row = await db.fetchone(
        "SELECT COUNT(*) AS n FROM profiles WHERE guild_id = ? AND reputation > ?",
        (guild_id, stats["reputation"]),
    )
    return {
        "xp_rank": stats["rank"],
        "message_rank": (msg_row["n"] if msg_row else 0) + 1,
        "voice_rank": (voice_row["n"] if voice_row else 0) + 1,
        "economy_rank": (eco_row["n"] if eco_row else 0) + 1,
        "reputation_rank": (rep_row["n"] if rep_row else 0) + 1,
    }
