"""SentriX V63 — politique intelligente de ping des mises à jour.

Toutes les releases restent annoncées dans #annonces-sentrix, mais @everyone n'est utilisé
que pour une vraie mise à jour majeure. Les petits fixes, hotfixes, ajustements, doublons,
polish et corrections de texte sont annoncés silencieusement.

Forçages disponibles dans le message de commit :
- [MAJOR] / [PING] : force le ping
- [NO-PING] / [MINOR] : interdit le ping
"""
from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from . import release_announcer as releases

logger = logging.getLogger("bot.release-ping-policy-v63")
_INSTALLED = False


def _norm(value: str) -> str:
    text = str(value or "").casefold()
    for old, new in (
        ("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
        ("à", "a"), ("â", "a"), ("ä", "a"),
        ("ù", "u"), ("û", "u"), ("ü", "u"),
        ("ô", "o"), ("ö", "o"), ("î", "i"), ("ï", "i"), ("ç", "c"),
    ):
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def is_major_update(raw_message: str) -> bool:
    """Détermine si une release mérite réellement de notifier @everyone."""
    raw = str(raw_message or "")
    low = _norm(raw)

    # Forçages explicites : utiles quand l'automatique ne peut pas comprendre le contexte.
    if re.search(r"\[(?:no[-_ ]?ping|minor)\]", low):
        return False
    if re.search(r"\[(?:major|ping)\]", low):
        return True

    # Une vraie annonce majeure doit pouvoir être reconnue sans ambiguïté.
    strong_phrases = (
        "mise a jour majeure",
        "grosse mise a jour",
        "major update",
        "refonte complete",
        "refonte majeure",
        "nouvelle version majeure",
        "nouveau systeme complet",
        "nouvelle fonctionnalite majeure",
        "breaking change",
        "breaking changes",
        "lancement officiel",
        "nouvelle generation",
    )
    if any(phrase in low for phrase in strong_phrases):
        return True

    # Un commit explicitement de correction reste silencieux, même s'il touche un domaine
    # important comme les logs ou la sécurité. Cela évite de ping pour chaque petit patch.
    minor_markers = (
        "fix", "bug", "hotfix", "corrig", "correction", "patch", "typo",
        "doublon", "duplicate", "ajustement", "cleanup", "nettoyage", "polish",
        "wording", "texte", "fallback", "compatibilite", "regression",
    )
    if any(marker in low for marker in minor_markers):
        return False

    # Une grosse release multi-systèmes peut mériter le ping même si le titre ne contient
    # pas littéralement « majeure ». Il faut au moins 3 domaines significatifs ET un
    # marqueur de nouveauté/refonte pour rester volontairement conservateur.
    domains = (
        ("tickets", ("ticket",)),
        ("logs", ("log", "journal")),
        ("security", ("security", "secur", "antinuke", "automod", "anti-raid")),
        ("moderation", ("moderation", "ban", "mute", "warn")),
        ("ai", (" ia ", "intelligence artificielle", "image generation", "generation d image")),
        ("dashboard", ("dashboard", "setup", "configuration")),
        ("commands", ("100 commandes", "commandes", "slash", "prefix")),
        ("economy", ("economie", "economy", "money", "shop")),
        ("community", ("giveaway", "level", "profile", "communaute")),
        ("server", ("create-server", "serveur complet", "server builder")),
    )
    changed_domains = {
        name for name, keywords in domains if any(keyword in f" {low} " for keyword in keywords)
    }
    novelty = any(token in low for token in (
        "nouveau systeme", "nouvelle fonctionnalite", "nouvelles fonctionnalites",
        "ajoute", "ajout de", "refonte", "nouvelle interface", "nouveau dashboard",
    ))
    return novelty and len(changed_domains) >= 3


async def announce_current_release_v63(bot: commands.Bot) -> None:
    info = releases._deployment_info()
    if info is None:
        return
    sha, branch, commit_message = info

    # Même délai que le moteur historique pour laisser le cache Discord se stabiliser.
    import asyncio
    await asyncio.sleep(2)

    target = await releases._resolve_target(bot)
    if target is None:
        return
    guild, channel = target

    me = guild.me
    if me is None:
        logger.error("V63: membre SentriX introuvable dans le serveur d'aide.")
        return
    permissions = channel.permissions_for(me)
    if not permissions.view_channel or not permissions.send_messages:
        logger.error("V63: SentriX ne peut pas écrire dans #%s.", channel.name)
        return
    if not permissions.embed_links:
        logger.error("V63: permission Intégrer des liens absente dans #%s.", channel.name)
        return

    try:
        reserved = await releases._reserve_release(bot, sha, guild.id, channel.id, commit_message)
    except Exception:
        logger.exception("V63: anti-doublon release indisponible ; annonce annulée.")
        return
    if not reserved:
        logger.info("V63: release %s déjà annoncée.", sha[:8])
        return

    major = is_major_update(commit_message)
    if major and not permissions.mention_everyone:
        logger.warning("V63: release majeure détectée mais permission @everyone absente dans #%s.", channel.name)

    embed = releases._build_embed(sha=sha, branch=branch, commit_message=commit_message)
    if major:
        content = "@everyone **Grosse mise à jour de SentriX disponible !**"
        mentions = discord.AllowedMentions(everyone=True, users=False, roles=False, replied_user=False)
    else:
        content = "**Mise à jour de SentriX disponible.**"
        mentions = discord.AllowedMentions.none()

    try:
        sent = await channel.send(content=content, embed=embed, allowed_mentions=mentions)
    except Exception:
        logger.exception("V63: échec annonce release %s dans #%s.", sha[:8], channel.name)
        await releases._release_reservation_failed(bot, sha)
        return

    try:
        await releases._mark_sent(bot, sha, sent.id)
    except Exception:
        logger.exception("V63: annonce envoyée mais message_id non persisté.")

    logger.info(
        "V63: release %s annoncée dans %s / #%s ; majeure=%s ; ping_effectif=%s.",
        sha[:8], guild.name, channel.name, major, bool(major and permissions.mention_everyone),
    )


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return
    # Le listener créé par release_announcer résout ce nom global lors de chaque READY.
    # Remplacer la fonction suffit donc sans ajouter un deuxième listener ni un doublon.
    releases.announce_current_release = announce_current_release_v63
    _INSTALLED = True
    logger.info("V63: @everyone réservé aux mises à jour majeures.")


__all__ = ["install", "is_major_update"]
