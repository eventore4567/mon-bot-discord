"""Annonce automatiquement les nouvelles versions de SentriX dans le serveur d'aide.

Le système est volontairement limité au serveur correspondant à TARGET_INVITE et au
salon TARGET_CHANNEL_NAME. Une version Railway n'est annoncée qu'une seule fois grâce à
un verrou persistant en base de données, même après reconnexion ou redémarrage.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands


logger = logging.getLogger("bot.release-announcer")

TARGET_INVITE = "https://discord.gg/5P5Bqjqu5t"
TARGET_CHANNEL_NAME = "📢・annonces-sentrix"
TARGET_BRANCH = "main"
TARGET_REPOSITORY = "mon-bot-discord"

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sentrix_release_announcements (
    release_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    commit_message TEXT,
    announced_at INTEGER NOT NULL
)
"""

_SETTING_GUILD = "sentrix_release_announce_guild_id"
_SETTING_CHANNEL = "sentrix_release_announce_channel_id"


def _clip(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _normal_channel_name(value: str) -> str:
    text = str(value or "").casefold().strip()
    text = text.replace("・", "-").replace("•", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text)
    return text


def _deployment_info() -> tuple[str, str, str] | None:
    """Retourne (sha, branche, message) uniquement pour un déploiement GitHub principal."""
    sha = str(os.getenv("RAILWAY_GIT_COMMIT_SHA") or "").strip()
    if not sha:
        # Aucun ping lors des tests locaux/CI ou d'un simple import Python.
        return None

    branch = str(os.getenv("RAILWAY_GIT_BRANCH") or TARGET_BRANCH).strip() or TARGET_BRANCH
    if branch != TARGET_BRANCH:
        logger.info("Annonce release ignorée : branche Railway %s (attendu: %s).", branch, TARGET_BRANCH)
        return None

    repo = str(os.getenv("RAILWAY_GIT_REPO_NAME") or TARGET_REPOSITORY).strip()
    if repo and repo != TARGET_REPOSITORY:
        logger.info("Annonce release ignorée : dépôt Railway inattendu %s.", repo)
        return None

    message = str(os.getenv("RAILWAY_GIT_COMMIT_MESSAGE") or "Mise à jour de SentriX").strip()
    return sha, branch, message or "Mise à jour de SentriX"


def _release_title(raw_message: str) -> str:
    """Extrait une ligne humaine d'un message de commit, y compris les merge commits."""
    lines = [line.strip() for line in raw_message.splitlines() if line.strip()]
    useful = [
        line
        for line in lines
        if not line.casefold().startswith("merge pull request")
        and not line.casefold().startswith("merge branch")
    ]
    title = useful[0] if useful else (lines[0] if lines else "Mise à jour de SentriX")
    title = re.sub(r"^(feat|fix|chore|refactor|style|perf|build|ci)(\([^)]*\))?:\s*", "", title, flags=re.I)
    return _clip(title, 240)


def _technical_notes(raw_message: str, title: str) -> str:
    lines = [line.strip(" -*•\t") for line in raw_message.splitlines() if line.strip()]
    notes: list[str] = []
    for line in lines:
        low = line.casefold()
        if low.startswith(("merge pull request", "merge branch")):
            continue
        if line == title or re.sub(
            r"^(feat|fix|chore|refactor|style|perf|build|ci)(\([^)]*\))?:\s*",
            "",
            line,
            flags=re.I,
        ) == title:
            continue
        if line not in notes:
            notes.append(line)
        if len(notes) >= 5:
            break
    if not notes:
        return "• Déploiement de la nouvelle version terminé avec succès."
    return _clip("\n".join(f"• {note}" for note in notes), 1000)


def _impact_notes(raw_message: str) -> str:
    """Transforme les mots du commit en explications compréhensibles pour les membres."""
    low = raw_message.casefold()
    rules: tuple[tuple[tuple[str, ...], str], ...] = (
        (("annonce", "release", "changelog", "mise à jour"),
         "Les nouveautés de SentriX sont mieux communiquées et centralisées dans ce salon."),
        (("style", "design", "interface", "embed", "help", "aide", "ui"),
         "L’interface et les réponses ont été retravaillées pour être plus propres et plus faciles à lire."),
        (("ticket",),
         "Le système de tickets a reçu des améliorations de fonctionnement ou de présentation."),
        (("log", "journal"),
         "Les journaux et informations de suivi ont été améliorés pour être plus clairs et plus fiables."),
        (("security", "sécur", "antinuke", "automod", "anti-"),
         "Les protections et contrôles de sécurité de SentriX ont été renforcés."),
        (("command", "commande", "slash", "prefix", "préfix"),
         "Des commandes ou leur expérience d’utilisation ont été améliorées."),
        (("performance", "perf", "latence", "rapide", "speed"),
         "Des optimisations ont été appliquées pour rendre SentriX plus rapide et plus stable."),
        (("fix", "bug", "corrig", "hotfix", "erreur"),
         "Des bugs ont été corrigés afin d’éviter des erreurs et comportements inattendus."),
        (("database", "base de données", "sqlite", "postgres"),
         "La fiabilité du stockage et des données persistantes a été améliorée."),
    )
    selected: list[str] = []
    for keywords, explanation in rules:
        if any(keyword in low for keyword in keywords) and explanation not in selected:
            selected.append(explanation)
        if len(selected) >= 5:
            break
    if not selected:
        selected.append(
            "Cette version contient des améliorations internes de stabilité et de qualité pour SentriX."
        )
    return "\n".join(f"• {line}" for line in selected)


async def _get_setting(bot: commands.Bot, key: str) -> str | None:
    row = await bot.db.fetchone("SELECT value FROM bot_settings WHERE key = ?", (key,))
    if not row:
        return None
    try:
        return str(row["value"])
    except Exception:
        return str(row[0]) if row else None


async def _save_setting(bot: commands.Bot, key: str, value: int) -> None:
    await bot.db.execute(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
        (key, str(int(value))),
    )


async def _saved_target(bot: commands.Bot) -> tuple[discord.Guild, discord.TextChannel] | None:
    try:
        guild_raw = await _get_setting(bot, _SETTING_GUILD)
        channel_raw = await _get_setting(bot, _SETTING_CHANNEL)
        if not guild_raw or not channel_raw:
            return None
        guild = bot.get_guild(int(guild_raw))
        channel = bot.get_channel(int(channel_raw))
        if guild is None or not isinstance(channel, discord.TextChannel):
            return None
        if channel.guild.id != guild.id:
            return None
        return guild, channel
    except Exception:
        return None


async def _resolve_target(bot: commands.Bot) -> tuple[discord.Guild, discord.TextChannel] | None:
    """Résout une première fois l'invite puis mémorise les IDs exacts du serveur/salon."""
    saved = await _saved_target(bot)
    if saved is not None:
        return saved

    try:
        invite = await bot.fetch_invite(TARGET_INVITE, with_counts=False)
    except Exception:
        logger.exception("Impossible de résoudre le serveur d'aide depuis l'invite configurée.")
        return None

    invite_guild = getattr(invite, "guild", None)
    guild_id = getattr(invite_guild, "id", None)
    if not guild_id:
        logger.error("L'invite du serveur d'aide ne contient aucun identifiant de serveur.")
        return None

    guild = bot.get_guild(int(guild_id))
    if guild is None:
        logger.error("SentriX n'est pas présent dans le serveur d'aide configuré (%s).", guild_id)
        return None

    exact = discord.utils.get(guild.text_channels, name=TARGET_CHANNEL_NAME)
    channel: discord.TextChannel | None = exact
    if channel is None:
        target_normal = _normal_channel_name(TARGET_CHANNEL_NAME)
        candidates = [
            item
            for item in guild.text_channels
            if _normal_channel_name(item.name) == target_normal
            or "annonces-sentrix" in _normal_channel_name(item.name)
        ]
        if len(candidates) == 1:
            channel = candidates[0]

    if channel is None:
        logger.error(
            "Salon d'annonces SentriX introuvable dans %s. Nom attendu: %s",
            guild.name,
            TARGET_CHANNEL_NAME,
        )
        return None

    try:
        await _save_setting(bot, _SETTING_GUILD, guild.id)
        await _save_setting(bot, _SETTING_CHANNEL, channel.id)
    except Exception:
        # La résolution reste utilisable pour ce boot même si la mémorisation échoue.
        logger.exception("Impossible de mémoriser les IDs du salon d'annonces SentriX.")

    logger.info(
        "Salon des mises à jour SentriX verrouillé sur %s (%s) / #%s (%s).",
        guild.name,
        guild.id,
        channel.name,
        channel.id,
    )
    return guild, channel


async def _reserve_release(
    bot: commands.Bot,
    release_id: str,
    guild_id: int,
    channel_id: int,
    commit_message: str,
) -> bool:
    """Réserve atomiquement le SHA afin d'éviter les doubles @everyone."""
    await bot.db.execute(_TABLE_SQL)
    now_ts = int(time.time())
    # Si un conteneur est mort entre la réservation et l'envoi, une réservation vide
    # peut être reprise après 15 minutes au lieu de bloquer la version pour toujours.
    await bot.db.execute(
        "DELETE FROM sentrix_release_announcements "
        "WHERE message_id IS NULL AND announced_at < ?",
        (now_ts - 900,),
    )
    cursor = await bot.db.execute(
        "INSERT OR IGNORE INTO sentrix_release_announcements "
        "(release_id, guild_id, channel_id, message_id, commit_message, announced_at) "
        "VALUES (?, ?, ?, NULL, ?, ?)",
        (release_id, guild_id, channel_id, _clip(commit_message, 1500), now_ts),
    )
    rowcount = getattr(cursor, "rowcount", 0)
    return bool(rowcount and rowcount > 0)


async def _release_reservation_failed(bot: commands.Bot, release_id: str) -> None:
    try:
        await bot.db.execute(
            "DELETE FROM sentrix_release_announcements WHERE release_id = ? AND message_id IS NULL",
            (release_id,),
        )
    except Exception:
        logger.exception("Impossible de libérer la réservation release %s.", release_id[:8])


async def _mark_sent(bot: commands.Bot, release_id: str, message_id: int) -> None:
    await bot.db.execute(
        "UPDATE sentrix_release_announcements SET message_id = ? WHERE release_id = ?",
        (message_id, release_id),
    )


def _build_embed(*, sha: str, branch: str, commit_message: str) -> discord.Embed:
    title = _release_title(commit_message)
    short_sha = sha[:8]
    embed = discord.Embed(
        title="✦ Mise à jour SentriX",
        description=(
            "Une nouvelle version de **SentriX** vient d’être déployée et est déjà active.\n"
            "Voici clairement ce qui change avec cette mise à jour."
        ),
        colour=discord.Colour(0x8B5CF6),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="🚀 Nouveauté principale", value=f"**{_clip(title, 900)}**", inline=False)
    embed.add_field(
        name="✨ Ce que ça change pour vous",
        value=_clip(_impact_notes(commit_message), 1024),
        inline=False,
    )
    technical = _technical_notes(commit_message, title)
    if technical:
        embed.add_field(name="🛠️ Détails de la mise à jour", value=_clip(technical, 1024), inline=False)
    embed.add_field(name="📦 Version", value=f"`{short_sha}`", inline=True)
    embed.add_field(name="🌿 Branche", value=f"`{branch}`", inline=True)
    embed.add_field(name="🟢 Statut", value="Déployée", inline=True)
    embed.add_field(
        name="💡 À savoir",
        value=(
            "Aucune action n’est nécessaire : la nouvelle version est déjà utilisée par SentriX. "
            "Si vous remarquez un problème, vous pouvez le signaler au staff."
        ),
        inline=False,
    )
    embed.set_footer(text="SentriX • Notes de mise à jour automatiques")
    return embed


async def announce_current_release(bot: commands.Bot) -> None:
    info = _deployment_info()
    if info is None:
        return
    sha, branch, commit_message = info

    # Laisser Discord finir le cache READY : l'invite peut être résolue immédiatement,
    # mais guild.me et les permissions de salon sont plus fiables juste après READY.
    await asyncio.sleep(2)

    target = await _resolve_target(bot)
    if target is None:
        return
    guild, channel = target

    me = guild.me
    if me is None:
        logger.error("Impossible de lire le membre SentriX dans le serveur d'aide.")
        return
    permissions = channel.permissions_for(me)
    if not permissions.view_channel or not permissions.send_messages:
        logger.error("SentriX ne peut pas envoyer de message dans #%s.", channel.name)
        return
    if not permissions.embed_links:
        logger.error("SentriX n'a pas la permission Intégrer des liens dans #%s.", channel.name)
        return

    try:
        reserved = await _reserve_release(bot, sha, guild.id, channel.id, commit_message)
    except Exception:
        # Fail-closed : sans anti-doublon persistant, on n'envoie pas de @everyone.
        logger.exception("Anti-doublon release indisponible ; annonce annulée pour éviter le spam.")
        return
    if not reserved:
        logger.info("Release %s déjà annoncée ; aucun nouveau ping.", sha[:8])
        return

    if not permissions.mention_everyone:
        logger.warning(
            "SentriX n'a pas la permission Mentionner @everyone dans #%s ; "
            "le texte @everyone sera visible mais ne notifiera pas tous les membres.",
            channel.name,
        )

    embed = _build_embed(sha=sha, branch=branch, commit_message=commit_message)
    try:
        sent = await channel.send(
            content="@everyone **Nouvelle mise à jour de SentriX disponible !**",
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                everyone=True,
                users=False,
                roles=False,
                replied_user=False,
            ),
        )
    except Exception:
        logger.exception("Échec de l'annonce de la release %s dans #%s.", sha[:8], channel.name)
        await _release_reservation_failed(bot, sha)
        return

    try:
        await _mark_sent(bot, sha, sent.id)
    except Exception:
        # Le message existe déjà : on garde surtout une trace dans les logs pour éviter
        # de masquer un problème de persistance. Le processus-local reste idempotent.
        logger.exception("Annonce envoyée mais impossible d'enregistrer son message_id.")

    logger.info(
        "Mise à jour SentriX %s annoncée dans %s / #%s avec @everyone=%s.",
        sha[:8],
        guild.name,
        channel.name,
        bool(permissions.mention_everyone),
    )


def install(bot: commands.Bot) -> None:
    """Installe une seule écoute READY, même si les finaliseurs SentriX repassent 24 fois."""
    if getattr(bot, "_sentrix_release_announcer_installed", False):
        return

    async def _release_ready_listener() -> None:
        await announce_current_release(bot)

    bot.add_listener(_release_ready_listener, "on_ready")
    bot._sentrix_release_announcer_listener = _release_ready_listener
    bot._sentrix_release_announcer_installed = True
    logger.info("Annonces automatiques des mises à jour SentriX activées pour le serveur d'aide.")
