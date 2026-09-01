"""SentriX V55 — garde anti-doublon source + sortie finale des journaux Discord.

Cette couche est installée APRES tous les renderers.
Elle corrige deux causes différentes de doublons :
1. deux services Railway qui reçoivent le même événement Discord ;
2. un événement journalisé deux fois dans le même process, par exemple /ban qui produit
   une fiche de sanction détaillée puis on_member_ban qui produit un log générique.

Principe :
- un seul service Railway peut publier ;
- log_service.send_log est dédupliqué AVANT le rendu ;
- les événements génériques susceptibles d'avoir une fiche détaillée attendent brièvement ;
  si la fiche détaillée arrive, elle gagne et le log générique est abandonné ;
- TextChannel.send garde un dernier verrou pour les anciens senders directs/transcripts.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import discord
from discord.ext import commands

from utils import log_service
from . import log_output_polish_v53 as v53
from . import log_preferred_style_v30 as v30
from . import log_rectangle_v25 as v25

logger = logging.getLogger("bot.log-dedupe-guard-v55")
_INSTALLED = False

OUTPUT_DEDUPE_TTL = 12.0
SOURCE_DEDUPE_TTL = 12.0
GENERIC_GRACE_SECONDS = 1.35

_OUTPUT_RECENT: dict[str, float] = {}
_OUTPUT_INFLIGHT: set[str] = set()
_SOURCE_RECENT: dict[str, tuple[float, int]] = {}
_SOURCE_INFLIGHT: set[str] = set()

_ID_RE = re.compile(r"(?<!\d)(\d{15,22})(?!\d)")


def _prune_output() -> None:
    now = time.monotonic()
    for key, expires in list(_OUTPUT_RECENT.items())[:6000]:
        if expires <= now:
            _OUTPUT_RECENT.pop(key, None)


def _prune_source() -> None:
    now = time.monotonic()
    for key, data in list(_SOURCE_RECENT.items())[:6000]:
        if data[0] <= now:
            _SOURCE_RECENT.pop(key, None)


def _plain(value: object) -> str:
    return v30._norm(str(value or ""))


def _first_id(value: object) -> int | None:
    match = _ID_RE.search(str(value or ""))
    return int(match.group(1)) if match else None


def _field_value(embed: discord.Embed, *tokens: str) -> str:
    wanted = tuple(_plain(token) for token in tokens)
    for field in embed.fields:
        name = _plain(field.name)
        if any(token == name or token in name for token in wanted):
            return str(field.value or "")
    return ""


def _event_family(log_type: str, embed: discord.Embed) -> str:
    text = _plain(
        " ".join(
            [str(embed.title or ""), str(embed.description or "")]
            + [str(field.name) for field in embed.fields]
        )
    )

    if log_type == "messages":
        if "supprim" in text or "delete" in text:
            return "message_delete"
        if "modifi" in text or "edit" in text:
            return "message_edit"

    if log_type == "moderation":
        # Les formes négatives doivent passer avant les formes positives :
        # "débannissement" contient aussi "bannissement" après normalisation.
        if any(token in text for token in ("debann", "unban")):
            return "unban"
        if any(token in text for token in ("demute", "unmute", "timeout retire", "timeout enleve")):
            return "unmute"
        if any(token in text for token in ("bann", " banni", "tempban")):
            return "ban"
        if any(token in text for token in ("expulsion", "kick")):
            return "kick"
        if any(token in text for token in ("avertissement", "warn")):
            return "warn"
        if any(token in text for token in ("timeout", "mute")):
            return "mute"

    if log_type == "members":
        if any(token in text for token in ("arrive", "join")):
            return "member_join"
        if any(token in text for token in ("parti", "leave", "remove")):
            return "member_leave"
        if any(token in text for token in ("surnom", "nickname", "pseudo")):
            return "member_nick"

    if log_type == "roles":
        if "membre" in text and any(token in text for token in ("ajout", "retir", "attrib", "roles d un membre")):
            return "member_roles"
        if any(token in text for token in ("role cree", "creation de role")):
            return "role_create"
        if any(token in text for token in ("role supprime", "suppression de role")):
            return "role_delete"
        if any(token in text for token in ("role modifie", "modification de role")):
            return "role_update"

    if log_type == "server":
        if any(token in text for token in ("salon cree", "channel create")):
            return "channel_create"
        if any(token in text for token in ("salon supprime", "channel delete")):
            return "channel_delete"
        if any(token in text for token in ("salon modifie", "channel update")):
            return "channel_update"
        if "serveur modifie" in text:
            return "guild_update"

    if log_type == "voice":
        return "voice_update"

    if log_type == "tickets":
        if any(token in text for token in ("ferme", "closed", "closure")):
            return "ticket_close"
        if any(token in text for token in ("reouvert", "reopen")):
            return "ticket_reopen"
        if any(token in text for token in ("ouvert", "open")):
            return "ticket_open"

    if log_type in {"automod", "security", "raid", "spam"}:
        if "raid" in text:
            return "raid"
        if "spam" in text:
            return "spam"
        if "nuke" in text:
            return "nuke"
        return "security"

    title = _plain(embed.title)
    return (title[:70] or log_type or "journal").replace(" ", "_")


def _primary_subject(log_type: str, embed: discord.Embed) -> int | str:
    # Le footer des listeners génériques contient souvent l'ID exact de l'objet.
    footer_id = v25._target_id(embed)

    if log_type == "messages":
        message_id = _first_id(_field_value(embed, "id message", "message id")) or footer_id
        if message_id:
            return message_id

    if log_type == "tickets":
        channel_id = _first_id(_field_value(embed, "salon", "channel", "ticket"))
        if channel_id:
            return channel_id

    if log_type == "voice":
        member_id = _first_id(_field_value(embed, "membre", "utilisateur", "auteur", "cible")) or footer_id
        before_id = _first_id(_field_value(embed, "avant")) or 0
        after_id = _first_id(_field_value(embed, "apres")) or 0
        if member_id:
            return f"{member_id}:{before_id}:{after_id}"

    # Fiches détaillées de modération : l'ID est dans le champ Membre/Utilisateur.
    preferred = _field_value(
        embed,
        "membre", "utilisateur", "cible", "auteur", "role", "rôle", "salon", "channel",
    )
    preferred_id = _first_id(preferred)
    if preferred_id:
        return preferred_id
    if footer_id:
        return footer_id

    # Dernier recours : un ID présent dans la description ou les champs.
    candidate = _first_id(embed.description)
    if candidate:
        return candidate
    for field in embed.fields:
        candidate = _first_id(field.value)
        if candidate:
            return candidate

    # Sans ID, on garde une petite signature stable du texte métier.
    sample = "|".join(
        [_plain(embed.title), _plain(embed.description)]
        + [f"{_plain(field.name)}:{_plain(field.value)[:120]}" for field in embed.fields[:3]]
    )
    return sample[:260]


def _source_key(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    family = _event_family(str(log_type), embed)
    subject = _primary_subject(str(log_type), embed)

    # Pour les changements de rôles d'un membre, inclure les rôles concernés afin que
    # deux changements réellement différents à quelques secondes d'intervalle restent visibles.
    extra = ""
    if str(log_type) == "roles" and family == "member_roles":
        role_ids: list[str] = []
        for field in embed.fields:
            if any(token in _plain(field.name) for token in ("ajout", "retir", "role", "rôle")):
                role_ids.extend(_ID_RE.findall(str(field.value or "")))
        if role_ids:
            extra = ":" + ",".join(sorted(set(role_ids))[:12])

    return f"{guild.id}:{log_type}:{family}:{subject}{extra}"


def _priority(log_type: str, embed: discord.Embed) -> int:
    """Plus la valeur est haute, plus le log est riche et doit être préféré."""
    title = _plain(embed.title)
    names = {_plain(field.name) for field in embed.fields}
    score = min(35, len(embed.fields) * 5)

    if any(token in title for token in ("dossier", "case")):
        score += 80
    for token in ("moderateur", "effectue par", "raison", "historique", "duree", "participants", "transcript"):
        if any(token in name for name in names):
            score += 12

    # Listeners Discord génériques : utiles pour une action externe, mais ils doivent
    # céder la place à la fiche détaillée quand SentriX a lui-même effectué l'action.
    generic_titles = {
        "membre banni", "membre debanni", "timeout modifie",
        "roles d un membre modifies", "role cree", "role supprime", "role modifie",
        "salon cree", "salon supprime", "salon modifie", "serveur modifie",
    }
    if title in generic_titles:
        score = min(score, 10)

    if log_type == "moderation" and any(token in title for token in ("bannissement", "expulsion", "avertissement", "mute", "unmute")):
        if "dossier" in title:
            score = max(score, 100)

    return score


def _needs_grace(log_type: str, embed: discord.Embed, priority: int) -> bool:
    if priority > 15:
        return False
    family = _event_family(log_type, embed)
    return family in {
        "ban", "unban", "mute", "unmute", "kick", "warn",
        "member_roles", "role_create", "role_delete", "role_update",
        "channel_create", "channel_delete", "channel_update", "guild_update",
    }


def _output_semantic_key(
    channel: discord.TextChannel,
    embed: discord.Embed | None,
    view: Any,
) -> str | None:
    if view is not None:
        fingerprint = getattr(view, "_sentrix_log_fingerprint", None)
        if fingerprint:
            return f"{channel.id}:event:{fingerprint}"

    if embed is not None:
        log_type = v53._channel_log_type(channel, embed)
        try:
            return f"{channel.id}:source:{_source_key(channel.guild, log_type, embed)}"
        except Exception:
            try:
                fingerprint = v30._canonical_fingerprint(channel.guild, log_type, embed)
            except Exception:
                fingerprint = v25._fingerprint_embed(channel.guild.id, embed)
            return f"{channel.id}:event:{fingerprint}"
    return None


def _install_source_guard() -> None:
    current = log_service.send_log
    if getattr(current, "_sentrix_source_dedupe_v55", False):
        return

    async def send_source_once(
        bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    
        **identity,
    ) -> bool:
        # Absolument aucun journal n'est émis depuis le service Railway secondaire.
        if not v25._is_primary_process():
            logger.debug("V55 source: service Railway secondaire bloqué guild=%s.", guild.id)
            return False

        if not isinstance(embed, discord.Embed):
            return await current(bot, guild, log_type, embed, file=file, **identity)

        key = _source_key(guild, str(log_type), embed, **identity)
        priority = _priority(str(log_type), embed)

        # Laisse à une fiche détaillée (Dossier, raison, modérateur...) le temps d'arriver
        # avant d'envoyer le listener Discord générique correspondant.
        if _needs_grace(str(log_type), embed, priority):
            await asyncio.sleep(GENERIC_GRACE_SECONDS)

        _prune_source()
        now = time.monotonic()
        recent = _SOURCE_RECENT.get(key)
        if recent and recent[0] > now:
            logger.info("V55 source: doublon supprimé (%s, priorité=%s/%s).", key, priority, recent[1])
            return False
        if key in _SOURCE_INFLIGHT:
            logger.info("V55 source: doublon concurrent supprimé (%s).", key)
            return False

        _SOURCE_INFLIGHT.add(key)
        try:
            sent = await current(bot, guild, log_type, embed, file=file, **identity)
        except Exception:
            _SOURCE_INFLIGHT.discard(key)
            raise
        else:
            _SOURCE_INFLIGHT.discard(key)
            if sent:
                _SOURCE_RECENT[key] = (time.monotonic() + SOURCE_DEDUPE_TTL, priority)
            return bool(sent)

    send_source_once._sentrix_source_dedupe_v55 = True
    send_source_once._sentrix_original = current
    log_service.send_log = send_source_once


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del bot, extension_name
    global _INSTALLED
    if _INSTALLED:
        return

    # 1) Déduplication AVANT rendu : corrige les doubles listeners/actions.
    _install_source_guard()

    # 2) Déduplication au dernier TextChannel.send : corrige les anciens senders directs,
    # les transcripts et constitue un deuxième verrou inter-service.
    previous_send = discord.TextChannel.send
    if getattr(previous_send, "_sentrix_dedupe_guard_v55", False):
        _INSTALLED = True
        return

    async def send_once(self: discord.TextChannel, *args, **kwargs):
        embed = kwargs.get("embed")
        if embed is None:
            for arg in args:
                if isinstance(arg, discord.Embed):
                    embed = arg
                    break
        if not isinstance(embed, discord.Embed):
            embed = None

        view = kwargs.get("view")
        if not v53._looks_like_log(self, embed, view):
            return await previous_send(self, *args, **kwargs)

        if not v25._is_primary_process():
            logger.debug(
                "V55 sortie: log bloqué sur service Railway secondaire guild=%s channel=%s.",
                self.guild.id,
                self.id,
            )
            return None

        key = _output_semantic_key(self, embed, view)
        if key:
            _prune_output()
            now = time.monotonic()
            if key in _OUTPUT_INFLIGHT or _OUTPUT_RECENT.get(key, 0.0) > now:
                logger.info("V55 sortie: doublon supprimé (%s).", key)
                return None
            _OUTPUT_INFLIGHT.add(key)

        try:
            message = await previous_send(self, *args, **kwargs)
        except Exception:
            if key:
                _OUTPUT_INFLIGHT.discard(key)
            raise
        else:
            if key:
                _OUTPUT_INFLIGHT.discard(key)
                if message is not None:
                    _OUTPUT_RECENT[key] = time.monotonic() + OUTPUT_DEDUPE_TTL
            return message

    send_once._sentrix_dedupe_guard_v55 = True
    send_once._sentrix_original = previous_send
    discord.TextChannel.send = send_once
    _INSTALLED = True
    logger.info(
        "V55 anti-doublon actif : source + préférence fiche détaillée + sortie unique Railway."
    )


__all__ = ["install"]
