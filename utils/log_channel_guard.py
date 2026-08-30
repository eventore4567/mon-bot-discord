"""Filet de compatibilité pour les anciens envois directs dans les salons de logs.

Le pipeline officiel passe par ``utils.log_service`` -> ``utils.wide_logs``. Cette garde
intercepte uniquement les vieux ``TextChannel.send(embed=...)`` qui auraient échappé à ce
pipeline dans un salon de logs SentriX et leur applique le même rendu avec bannière.

Elle ne touche jamais un message déjà rendu avec ``LayoutView`` et conserve la valeur de
retour native de ``TextChannel.send`` (un ``discord.Message``), afin de ne pas casser les
appelants historiques.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import discord

from utils.log_banners import banner_kind, get_banner

logger = logging.getLogger("bot.log-guard")

_INSTALLED = False
_ORIGINAL_SEND = None


def _is_log_channel(channel: discord.TextChannel) -> bool:
    """Reconnaît les salons dédiés aux journaux sans toucher aux salons ordinaires."""
    name = str(getattr(channel, "name", "") or "").casefold()
    category = str(getattr(getattr(channel, "category", None), "name", "") or "").casefold()

    if name.startswith("logs-") or name.startswith("log-"):
        return True
    if name in {"logs", "log", "journal", "journaux"}:
        return True
    return "sentrix" in category and ("log" in category or "journal" in category)


def _infer_log_type(channel: discord.TextChannel, embed: discord.Embed) -> str:
    sample = " ".join(
        (
            str(getattr(channel, "name", "") or ""),
            str(embed.title or ""),
            str(embed.description or ""),
        )
    ).casefold()

    rules = (
        ("messages", ("message",)),
        ("members", ("membre", "member", "arriv", "départ", "depart")),
        ("voice", ("vocal", "voice")),
        ("roles", ("rôle", "role")),
        ("tickets", ("ticket",)),
        ("automod", ("sécurité", "securite", "automod", "anti-")),
        ("moderation", ("modération", "moderation", "ban", "kick", "mute", "warn", "sanction")),
        ("server", ("serveur", "salon", "channel", "catégorie", "categorie")),
    )
    for log_type, words in rules:
        if any(word in sample for word in words):
            return log_type
    return "system"


def _rewind(file: discord.File) -> None:
    try:
        file.fp.seek(0)
    except Exception:
        pass


async def _guarded_send(self: discord.TextChannel, *args: Any, **kwargs: Any):
    """Convertit un ancien embed de log en panneau V2 avec bannière, au dernier moment."""
    assert _ORIGINAL_SEND is not None

    # Le renderer officiel est déjà passé : surtout ne pas l'intercepter une seconde fois.
    view = kwargs.get("view")
    if isinstance(view, discord.ui.LayoutView):
        return await _ORIGINAL_SEND(self, *args, **kwargs)

    embed = kwargs.get("embed")
    if not isinstance(embed, discord.Embed) or not _is_log_channel(self):
        return await _ORIGINAL_SEND(self, *args, **kwargs)

    try:
        # Import tardif : évite tout cycle au démarrage du package utils.
        from utils.wide_logs import NO_PINGS, WideLogView

        log_type = _infer_log_type(self, embed)
        kind = banner_kind(log_type, embed.title or "", embed.description or "")
        banner_path: Path = get_banner(log_type, embed.title or "", embed.description or "")
        banner_filename = f"sentrix_log_{kind}.png"
        banner_file = discord.File(str(banner_path), filename=banner_filename)

        incoming_files: list[discord.File] = []
        single_file = kwargs.pop("file", None)
        if isinstance(single_file, discord.File):
            incoming_files.append(single_file)
        multiple_files = kwargs.pop("files", None)
        if multiple_files:
            incoming_files.extend(file for file in multiple_files if isinstance(file, discord.File))

        for file in incoming_files:
            _rewind(file)

        accent = embed.colour.value if embed.colour else None
        guarded_view = WideLogView(embed, banner_filename, view, accent)

        kwargs.pop("embed", None)
        kwargs.pop("embeds", None)
        kwargs["view"] = guarded_view
        kwargs["files"] = [banner_file, *incoming_files]
        kwargs["allowed_mentions"] = discord.AllowedMentions(
            everyone=False,
            users=False,
            roles=False,
            replied_user=False,
        )

        logger.warning(
            "Ancien envoi direct rattrapé et converti en log V2 avec bannière channel=%s title=%r",
            self.id,
            embed.title,
        )
        return await _ORIGINAL_SEND(self, *args, **kwargs)

    except Exception:
        # Dernier filet : même si Components V2 est refusé, la bannière reste visible dans
        # l'embed classique. On ne revient jamais silencieusement à un log sans bannière.
        logger.exception("Conversion V2 d'un ancien log impossible ; tentative embed avec bannière.")
        try:
            log_type = _infer_log_type(self, embed)
            kind = banner_kind(log_type, embed.title or "", embed.description or "")
            banner_path = get_banner(log_type, embed.title or "", embed.description or "")
            banner_filename = f"sentrix_log_{kind}.png"
            fallback_banner = discord.File(str(banner_path), filename=banner_filename)
            fallback_embed = embed.copy()
            fallback_embed.set_image(url=f"attachment://{banner_filename}")

            fallback_kwargs = dict(kwargs)
            fallback_kwargs["embed"] = fallback_embed
            fallback_kwargs.pop("embeds", None)
            fallback_kwargs.pop("file", None)
            previous_files = fallback_kwargs.pop("files", None) or []
            usable_files = [file for file in previous_files if isinstance(file, discord.File)]
            for file in usable_files:
                _rewind(file)
            fallback_kwargs["files"] = [fallback_banner, *usable_files]
            fallback_kwargs["allowed_mentions"] = discord.AllowedMentions(
                everyone=False,
                users=False,
                roles=False,
                replied_user=False,
            )
            return await _ORIGINAL_SEND(self, *args, **fallback_kwargs)
        except Exception:
            logger.exception("Même le fallback avec bannière a échoué ; envoi legacy conservé.")
            return await _ORIGINAL_SEND(self, *args, **kwargs)


def install() -> None:
    """Installe la garde une seule fois pour tout le processus SentriX."""
    global _INSTALLED, _ORIGINAL_SEND
    if _INSTALLED:
        return
    _ORIGINAL_SEND = discord.TextChannel.send
    discord.TextChannel.send = _guarded_send
    _INSTALLED = True
    logger.info("Garde globale des salons de logs SentriX installée.")


__all__ = ["install"]
