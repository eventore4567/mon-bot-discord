"""SentriX V64 — annonces de mises à jour uniquement sur demande explicite.

Aucune petite correction, hotfix, refactor, polish ou mise à jour normale n'est publiée
dans #annonces-sentrix. Une release n'est annoncée que si son message de commit contient
explicitement le marqueur [MAJOR] (ou [PING]). Dans ce cas, l'annonce est considérée comme
importante et peut notifier @everyone.

Cette politique est volontairement manuelle : pas de détection automatique de « grosse »
mise à jour. Cela évite tout spam du serveur officiel lors des nombreux correctifs internes.
"""
from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from . import release_announcer as releases

logger = logging.getLogger("bot.release-ping-policy-v64")
_INSTALLED = False


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def is_major_update(raw_message: str) -> bool:
    """Vrai uniquement lorsqu'une annonce importante a été demandée explicitement."""
    low = _norm(raw_message)
    return bool(re.search(r"\[(?:major|ping)\]", low))


async def announce_current_release_v64(bot: commands.Bot) -> None:
    info = releases._deployment_info()
    if info is None:
        return
    sha, branch, commit_message = info

    # Politique principale : aucune annonce automatique pour une release ordinaire.
    if not is_major_update(commit_message):
        logger.info(
            "V64: release %s non marquée [MAJOR] ; aucune annonce envoyée dans le serveur officiel.",
            sha[:8],
        )
        return

    import asyncio
    await asyncio.sleep(2)

    target = await releases._resolve_target(bot)
    if target is None:
        return
    guild, channel = target

    me = guild.me
    if me is None:
        logger.error("V64: membre SentriX introuvable dans le serveur d'aide.")
        return
    permissions = channel.permissions_for(me)
    if not permissions.view_channel or not permissions.send_messages:
        logger.error("V64: SentriX ne peut pas écrire dans #%s.", channel.name)
        return
    if not permissions.embed_links:
        logger.error("V64: permission Intégrer des liens absente dans #%s.", channel.name)
        return

    try:
        reserved = await releases._reserve_release(bot, sha, guild.id, channel.id, commit_message)
    except Exception:
        logger.exception("V64: anti-doublon release indisponible ; annonce annulée.")
        return
    if not reserved:
        logger.info("V64: release majeure %s déjà annoncée.", sha[:8])
        return

    if not permissions.mention_everyone:
        logger.warning(
            "V64: release [MAJOR] détectée mais permission @everyone absente dans #%s.",
            channel.name,
        )

    embed = releases._build_embed(sha=sha, branch=branch, commit_message=commit_message)
    content = "@everyone **Grosse mise à jour de SentriX disponible !**"
    mentions = discord.AllowedMentions(
        everyone=True,
        users=False,
        roles=False,
        replied_user=False,
    )

    try:
        sent = await channel.send(content=content, embed=embed, allowed_mentions=mentions)
    except Exception:
        logger.exception("V64: échec annonce release %s dans #%s.", sha[:8], channel.name)
        await releases._release_reservation_failed(bot, sha)
        return

    try:
        await releases._mark_sent(bot, sha, sent.id)
    except Exception:
        logger.exception("V64: annonce envoyée mais message_id non persisté.")

    logger.info(
        "V64: release [MAJOR] %s annoncée dans %s / #%s ; ping_effectif=%s.",
        sha[:8],
        guild.name,
        channel.name,
        bool(permissions.mention_everyone),
    )


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return
    # Le listener historique appelle ce nom global à chaque READY : on remplace uniquement
    # la politique, sans ajouter de listener supplémentaire ni créer de doublon.
    releases.announce_current_release = announce_current_release_v64
    _INSTALLED = True
    logger.info("V64: annonces automatiques désactivées ; seules les releases [MAJOR] sont publiées.")


__all__ = ["install", "is_major_update"]
