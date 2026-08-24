"""SentriX V54 — garde anti-doublon finale pour les journaux Discord.

Cette couche est installée APRES V53 et constitue le dernier point de sortie :
- un seul service Railway a le droit de publier des logs ;
- la déduplication repose d'abord sur l'empreinte sémantique de l'événement, sans digest
  visuel, afin que deux renderers différents du même événement ne produisent pas 2 logs ;
- les autres messages Discord du bot ne sont pas touchés.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import discord
from discord.ext import commands

from . import log_output_polish_v53 as v53
from . import log_preferred_style_v30 as v30
from . import log_rectangle_v25 as v25

logger = logging.getLogger("bot.log-dedupe-guard-v54")
_INSTALLED = False
DEDUPE_TTL = 8.0
_RECENT: dict[str, float] = {}
_INFLIGHT: set[str] = set()


def _prune() -> None:
    now = time.monotonic()
    for key, expires in list(_RECENT.items())[:6000]:
        if expires <= now:
            _RECENT.pop(key, None)


def _semantic_key(
    channel: discord.TextChannel,
    embed: discord.Embed | None,
    view: Any,
) -> str | None:
    # IMPORTANT : on ignore volontairement le digest visuel V53. Deux layouts différents
    # représentant le même événement doivent partager la même clé et donc être fusionnés.
    if view is not None:
        fingerprint = getattr(view, "_sentrix_log_fingerprint", None)
        if fingerprint:
            return f"{channel.id}:event:{fingerprint}"

    if embed is not None:
        log_type = v53._channel_log_type(channel, embed)
        try:
            fingerprint = v30._canonical_fingerprint(channel.guild, log_type, embed)
        except Exception:
            fingerprint = v25._fingerprint_embed(channel.guild.id, embed)
        return f"{channel.id}:event:{fingerprint}"

    return None


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del bot, extension_name
    global _INSTALLED
    if _INSTALLED:
        return

    previous_send = discord.TextChannel.send
    if getattr(previous_send, "_sentrix_dedupe_guard_v54", False):
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

        # Verrou inter-service : même si une ancienne couche ou un sender direct contourne
        # V25/V53, le second service Railway ne peut plus publier un journal Discord.
        if not v25._is_primary_process():
            logger.debug(
                "V54 : log bloqué sur service Railway secondaire guild=%s channel=%s.",
                self.guild.id,
                self.id,
            )
            return None

        key = _semantic_key(self, embed, view)
        if key:
            _prune()
            now = time.monotonic()
            if key in _INFLIGHT or _RECENT.get(key, 0.0) > now:
                logger.info("V54 : doublon de log supprimé (%s).", key)
                return None
            _INFLIGHT.add(key)

        try:
            message = await previous_send(self, *args, **kwargs)
        except Exception:
            if key:
                _INFLIGHT.discard(key)
            raise
        else:
            if key:
                _INFLIGHT.discard(key)
                if message is not None:
                    _RECENT[key] = time.monotonic() + DEDUPE_TTL
            return message

    send_once._sentrix_dedupe_guard_v54 = True
    send_once._sentrix_original = previous_send
    discord.TextChannel.send = send_once
    _INSTALLED = True
    logger.info(
        "V54 anti-doublon actif : sortie Railway unique + empreinte sémantique finale."
    )


__all__ = ["install"]
