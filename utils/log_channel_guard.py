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


async def _ensure_banner_permissions(channel: discord.TextChannel) -> bool:
    """Garantit les permissions nécessaires aux bannières quand SentriX peut réparer le salon.

    Les anciennes catégories de logs ont souvent été créées avant que les bannières ne
    deviennent obligatoires et leur overwrite ne contenait donc pas ``attach_files``.
    Dans ce cas Discord accepte encore l'embed classique mais refuse silencieusement notre
    rendu avec fichier. Si le bot possède ``manage_channels``, on répare son overwrite une
    seule fois directement sur le salon.
    """
    guild = channel.guild
    me = guild.me
    if me is None:
        return False

    perms = channel.permissions_for(me)
    if (
        perms.view_channel
        and perms.send_messages
        and perms.embed_links
        and perms.attach_files
    ):
        return True

    if not perms.manage_channels:
        logger.warning(
            "Permissions V2 manquantes et impossibles à réparer channel=%s "
            "view=%s send=%s embeds=%s files=%s manage_channels=%s",
            channel.id,
            perms.view_channel,
            perms.send_messages,
            perms.embed_links,
            perms.attach_files,
            perms.manage_channels,
        )
        return False

    try:
        await channel.set_permissions(
            me,
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            reason="SentriX : réparation automatique des permissions des logs V2",
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.exception("Impossible de réparer les permissions V2 du salon %s.", channel.id)
        return False

    repaired = channel.permissions_for(me)
    ok = bool(
        repaired.view_channel
        and repaired.send_messages
        and repaired.embed_links
        and repaired.attach_files
    )
    if ok:
        logger.warning("Permissions du salon de logs %s réparées pour les bannières V2.", channel.id)
    return ok


async def _guarded_send(self: discord.TextChannel, *args: Any, **kwargs: Any):
    """Convertit un ancien embed de log en panneau V2 avec bannière, au dernier moment."""
    assert _ORIGINAL_SEND is not None

    # Conserver une copie AVANT toute mutation : si Discord refuse V2 puis la bannière,
    # le dernier fallback doit pouvoir renvoyer exactement l'ancien embed et ses boutons.
    original_kwargs = dict(kwargs)

    # Le renderer officiel est déjà passé : surtout ne pas l'intercepter une seconde fois.
    view = kwargs.get("view")
    if isinstance(view, discord.ui.LayoutView):
        return await _ORIGINAL_SEND(self, *args, **kwargs)

    embed = kwargs.get("embed")
    if not isinstance(embed, discord.Embed) or not _is_log_channel(self):
        return await _ORIGINAL_SEND(self, *args, **kwargs)

    try:
        # Les bannières sont des pièces jointes. Répare les anciens salons dont l'overwrite
        # du bot autorisait les embeds mais pas "Joindre des fichiers".
        await _ensure_banner_permissions(self)

        # Import tardif : évite tout cycle au démarrage du package utils.
        from utils.wide_logs import WideLogView

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
        # l'embed classique. On repart de la copie ORIGINALE, pas des kwargs V2 mutés.
        logger.exception("Conversion V2 d'un ancien log impossible ; tentative embed avec bannière.")
        try:
            await _ensure_banner_permissions(self)
            log_type = _infer_log_type(self, embed)
            kind = banner_kind(log_type, embed.title or "", embed.description or "")
            banner_path = get_banner(log_type, embed.title or "", embed.description or "")
            banner_filename = f"sentrix_log_{kind}.png"
            fallback_banner = discord.File(str(banner_path), filename=banner_filename)
            fallback_embed = embed.copy()
            fallback_embed.set_image(url=f"attachment://{banner_filename}")

            fallback_kwargs = dict(original_kwargs)
            fallback_kwargs["embed"] = fallback_embed
            fallback_kwargs.pop("embeds", None)

            usable_files: list[discord.File] = []
            original_file = fallback_kwargs.pop("file", None)
            if isinstance(original_file, discord.File):
                usable_files.append(original_file)
            original_files = fallback_kwargs.pop("files", None) or []
            usable_files.extend(file for file in original_files if isinstance(file, discord.File))
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
            return await _ORIGINAL_SEND(self, *args, **original_kwargs)


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
