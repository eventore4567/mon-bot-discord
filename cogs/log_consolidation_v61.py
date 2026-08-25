"""SentriX V61 — consolidation des journaux serveur.

Cette couche complète V55/V60 sans ajouter de listener Discord :
- un changement de catégorie technique qui suit immédiatement une création/suppression
  de salon est absorbé dans la fiche principale au lieu de produire une seconde carte ;
- la fiche principale conserve l'information utile du changement absorbé ;
- les cibles de salon utilisent une seule représentation visuelle (mention OU nom), puis
  l'ID, afin d'éviter ``#general · #general · ID``.

Les modifications réellement indépendantes (nom, sujet, permissions, etc.) restent des
journaux séparés. Le but est de supprimer le bruit, pas de masquer les actions utiles.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord
from discord.ext import commands

from utils import log_service
from . import log_dedupe_guard_v54 as v55
from . import log_identity_context_v60 as v60

logger = logging.getLogger("bot.log-consolidation-v61")

MERGE_WINDOW_SECONDS = 3.0
PRIMARY_HOLD_SECONDS = 0.90
UPDATE_WAIT_SECONDS = 0.55

# guild_id -> (expiration, famille, embed source, sujet principal)
_SERVER_BURSTS: dict[int, tuple[float, str, discord.Embed, Any]] = {}


def _prune_bursts() -> None:
    now = time.monotonic()
    for guild_id, data in list(_SERVER_BURSTS.items())[:2000]:
        if data[0] <= now:
            _SERVER_BURSTS.pop(guild_id, None)


def _all_text(embed: discord.Embed) -> str:
    values = [str(embed.title or ""), str(embed.description or "")]
    for field in embed.fields:
        values.extend((str(field.name or ""), str(field.value or "")))
    return v55._plain(" ".join(values))


def _category_only_update(embed: discord.Embed) -> bool:
    """Vrai uniquement pour le bruit « catégorie modifiée » sans autre changement utile."""
    text = _all_text(embed)
    if "categorie modifiee" not in text and "category changed" not in text:
        return False

    # Ces marqueurs correspondent à une vraie modification que l'on doit conserver.
    meaningful = (
        "nom :", "name :", "sujet modifie", "topic", "permissions modifie",
        "slowmode", "mode lent", "nsfw", "bitrate", "debit", "limite utilisateurs",
        "user limit", "type modifie",
    )
    return not any(token in text for token in meaningful)


def _channel_label(guild: discord.Guild, embed: discord.Embed) -> str:
    subject = v55._primary_subject("server", embed)
    channel_id: int | None = subject if isinstance(subject, int) else None
    if channel_id is None:
        channel_id = v55._first_id(v55._field_value(embed, "salon", "channel"))
    if channel_id is None:
        channel_id = v55._first_id(getattr(getattr(embed, "footer", None), "text", ""))

    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if channel is not None:
            return f"{channel.mention} · `{channel.id}`"

    raw = v55._field_value(embed, "salon", "channel") or str(embed.description or "")
    saved = v60._safe_name(raw)
    if saved and channel_id:
        return f"**#{saved}** · `{channel_id}`"
    if saved:
        return f"**#{saved}**"
    if channel_id:
        return f"**Salon** · `{channel_id}`"
    return "**Salon lié**"


def _merge_update_into_primary(guild: discord.Guild, update_embed: discord.Embed) -> bool:
    _prune_bursts()
    pending = _SERVER_BURSTS.get(guild.id)
    if pending is None or pending[0] <= time.monotonic():
        return False

    _expires, family, primary, primary_subject = pending
    if family not in {"channel_create", "channel_delete"}:
        return False

    update_subject = v55._primary_subject("server", update_embed)
    # Si Discord rapporte une update sur exactement le même objet que la fiche principale,
    # V55 devrait déjà la dédupliquer. Ici on vise surtout le salon voisin réorganisé.
    label = _channel_label(guild, update_embed)
    note = f"Catégorie réorganisée automatiquement pour {label}."

    for index, field in enumerate(list(primary.fields)):
        if v55._plain(field.name) not in {"changement lie", "reorganisation liee"}:
            continue
        current = str(field.value or "")
        if note not in current:
            merged = (current.rstrip() + "\n" + note).strip()[:1024]
            primary.set_field_at(
                index,
                name="Réorganisation liée",
                value=merged,
                inline=False,
            )
        return True

    # Éviter de produire une information inutile si le second event désigne exactement
    # le même salon et n'apporte rien de plus.
    if update_subject == primary_subject:
        return True

    primary.add_field(name="Réorganisation liée", value=note[:1024], inline=False)
    return True


def _single_channel_display(guild: discord.Guild, raw: object, target_id: int | None = None) -> str:
    """Une seule représentation de salon : mention cliquable + ID, jamais le nom en double."""
    raw_text = str(raw or "")
    channel_id = v60._first_id(raw_text) or target_id
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if channel is not None:
            return f"{channel.mention} · `{channel.id}`"

    saved = v60._safe_name(raw_text)
    if saved and channel_id:
        return f"**#{saved}** · `{channel_id}`"
    if saved:
        return f"**#{saved}**"
    if channel_id:
        return f"**Salon supprimé** · `{channel_id}`"
    return "**Salon** · identité non fournie par Discord"


def _install_single_target_renderer() -> None:
    # _context_block de V60 résout _display_channel depuis son module au moment de l'appel,
    # donc remplacer cette fonction suffit sans empiler un nouveau renderer complet.
    if getattr(v60._display_channel, "_sentrix_single_channel_v61", False):
        return
    _single_channel_display._sentrix_single_channel_v61 = True
    v60._display_channel = _single_channel_display


def _install_source_consolidation() -> None:
    current = log_service.send_log
    if getattr(current, "_sentrix_log_consolidation_v61", False):
        return

    async def send_consolidated(
        bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
    ) -> bool:
        if not isinstance(embed, discord.Embed) or str(log_type) != "server":
            return await current(bot, guild, log_type, embed, file=file)

        family = v55._event_family("server", embed)
        _prune_bursts()

        if family in {"channel_create", "channel_delete"}:
            subject = v55._primary_subject("server", embed)
            _SERVER_BURSTS[guild.id] = (
                time.monotonic() + MERGE_WINDOW_SECONDS,
                family,
                embed,
                subject,
            )
            # Petite attente : laisse les événements secondaires Gateway arriver avant
            # que les renderers transforment l'embed principal.
            await asyncio.sleep(PRIMARY_HOLD_SECONDS)
            return await current(bot, guild, log_type, embed, file=file)

        if family == "channel_update" and _category_only_update(embed):
            if _merge_update_into_primary(guild, embed):
                logger.info(
                    "V61: update de catégorie absorbée dans la fiche principale guild=%s.",
                    guild.id,
                )
                return False
            # L'update peut arriver quelques centaines de ms avant le create/delete.
            await asyncio.sleep(UPDATE_WAIT_SECONDS)
            if _merge_update_into_primary(guild, embed):
                logger.info(
                    "V61: update de catégorie anticipée fusionnée après attente guild=%s.",
                    guild.id,
                )
                return False

        return await current(bot, guild, log_type, embed, file=file)

    send_consolidated._sentrix_log_consolidation_v61 = True
    send_consolidated._sentrix_original = current
    log_service.send_log = send_consolidated


def install(bot: commands.Bot | None = None, extension_name: str = "") -> None:
    del bot, extension_name
    _install_single_target_renderer()
    _install_source_consolidation()


__all__ = ["install"]
