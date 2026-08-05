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
# Progression (texte uniquement — plus de barre en blocs/emojis dans aucune commande,
# demande explicite de Jayden). progress_bar() reste disponible pour compatibilité (au
# cas où du code l'appellerait encore ailleurs) mais n'est plus utilisée par /stats ni
# /level : voir progress_percent() ci-dessous, utilisée à la place.
# ---------------------------------------------------------------------------

def progress_percent(current: int, needed: int) -> int:
    """Pourcentage de progression (0-100), sans construire de barre visuelle."""
    if needed <= 0:
        return 100
    return max(0, min(100, round((current / needed) * 100)))


def progress_bar(current: int, needed: int, length: int = 10, emoji_filled: str = "🟩", emoji_empty: str = "⬜") -> tuple[str, int]:
    """Retourne (barre, pourcentage). Le pourcentage reste toujours entre 0 et 100 ;
    si `current` dépasse `needed` (ne devrait pas arriver, le niveau doit avoir déjà été
    recalculé avant l'affichage), on plafonne à 100 plutôt que d'afficher un nombre absurde.
    Conservée pour compatibilité mais plus utilisée pour l'affichage — voir progress_percent()."""
    pct = progress_percent(current, needed)
    filled = max(0, min(length, round(length * pct / 100)))
    bar = emoji_filled * filled + emoji_empty * (length - filled)
    return bar, pct


# ---------------------------------------------------------------------------
# Nombres — séparateur de milliers (espace), utilisé PARTOUT où un montant ou un total
# est affiché (économie, XP, classements...). Ne jamais formater un nombre à la main.
# ---------------------------------------------------------------------------

def format_number(number) -> str:
    try:
        number = int(round(number))
    except (TypeError, ValueError):
        return str(number)
    return f"{number:,}".replace(",", " ")


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
    """Récupère TOUT ce qu'il faut pour afficher /stats, /level, /profile, /balance ou
    une entrée de /leaderboard pour ce membre — une seule fonction, une seule vérité.

    Clés retournées : wallet, bank, total_money, reputation, current_level, total_xp,
    current_level_xp, required_xp, next_level_role, next_level_requirement,
    remaining_levels, all_roles_obtained, rank, is_ranked, message_count, voice_time,
    progress_pct, progress_bar, joined_at.
    (D'anciens alias — level, xp_current, xp_needed, voice_seconds, next_role,
    next_role_level — restent aussi présents pour compatibilité.)
    """
    db = bot.db
    await db.ensure_level(guild.id, member.id)
    level_row = await db.get_level(guild.id, member.id)
    current_level = level_row["level"]
    current_level_xp = level_row["xp"]
    required_xp = xp_required_for_level(current_level)

    msg_row = await db.fetchone(
        "SELECT count FROM message_counts WHERE guild_id = ? AND user_id = ?", (guild.id, member.id)
    )
    message_count = msg_row["count"] if msg_row else 0

    # Une donnée est considérée "vide" (membre jamais actif) si niveau 0, XP 0 ET aucun
    # message envoyé : dans ce cas précis on affiche "non classé" plutôt qu'un classement
    # qui n'aurait pas vraiment de sens (voir demande explicite de Jayden).
    has_activity = not (current_level == 0 and current_level_xp == 0 and message_count == 0)
    rank = await get_rank(bot, guild.id, member.id, current_level, current_level_xp) if has_activity else None

    voice_row = await db.fetchone(
        "SELECT seconds FROM voice_totals WHERE guild_id = ? AND user_id = ?", (guild.id, member.id)
    )
    voice_time = voice_row["seconds"] if voice_row else 0
    # Si le membre est actuellement en vocal, on ajoute le temps de la session en cours
    # (pas encore "flush" dans voice_totals) pour un affichage en temps réel exact.
    session_row = await db.fetchone(
        "SELECT joined_at FROM voice_sessions WHERE guild_id = ? AND user_id = ?", (guild.id, member.id)
    )
    if session_row:
        from database.db import now as _now
        voice_time += max(0, _now() - session_row["joined_at"])

    await db.ensure_economy(guild.id, member.id)
    bal = await db.get_balance(guild.id, member.id)
    reputation = await db.get_reputation(guild.id, member.id)
    wallet = bal["cash"] if bal else 0
    bank = bal["bank"] if bal else 0

    # Premier palier configuré dont le niveau requis dépasse le niveau actuel du membre.
    role_row = await db.fetchone(
        "SELECT * FROM level_roles WHERE guild_id = ? AND level > ? ORDER BY level ASC LIMIT 1",
        (guild.id, current_level),
    )
    # Existe-t-il AU MOINS un palier configuré sur ce serveur ? (distingue "aucun palier
    # configuré du tout" de "tous les paliers ont déjà été atteints").
    any_role_row = await db.fetchone("SELECT COUNT(*) AS n FROM level_roles WHERE guild_id = ?", (guild.id,))
    has_any_configured = bool(any_role_row and any_role_row["n"])

    next_level_role = None
    next_level_requirement = None
    remaining_levels = None
    if role_row:
        next_level_role = guild.get_role(role_row["role_id"])
        next_level_requirement = role_row["level"]
        remaining_levels = max(0, next_level_requirement - current_level)
    all_roles_obtained = has_any_configured and role_row is None

    pct = progress_percent(current_level_xp, required_xp)
    total_xp = total_xp_for(current_level, current_level_xp)

    return {
        # Noms demandés par Jayden
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
        # Champs additionnels utiles à l'affichage
        "is_ranked": has_activity,
        "progress_pct": pct,
        "joined_at": member.joined_at,
        # Alias conservés pour compatibilité avec du code déjà écrit
        "level": current_level,
        "xp_current": current_level_xp,
        "xp_needed": required_xp,
        "voice_seconds": voice_time,
        "next_role": next_level_role,
        "next_role_level": next_level_requirement,
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
        (guild_id, stats["voice_time"]),
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
