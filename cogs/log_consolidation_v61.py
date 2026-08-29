"""SentriX V67 — consolidation et anti-doublon exact des journaux serveur.

Cette couche complète V55/V60 sans ajouter de listener Discord :
- un changement de catégorie technique qui suit immédiatement une création/suppression
  de salon est absorbé dans la fiche principale au lieu de produire une seconde carte ;
- les vrais doublons sont bloqués à partir du contenu métier complet de la fiche ;
- deux événements légitimes restent distincts, même s'ils concernent le même salon ;
- les ``view`` (boutons ID) et ``event_key`` du transport officiel sont toujours conservés ;
- l'ancien garde V55 trop grossier est contourné ici afin qu'un deuxième renommage,
  changement vocal ou changement de permissions ne soit jamais masqué par erreur.

Exemples volontairement conservés : deux membres quittant le même vocal, ou deux
renommages successifs du même salon. Seule une répétition réellement identique est
supprimée pendant la courte fenêtre anti-doublon.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import re
import time
from typing import Any

import discord
from discord.ext import commands

from utils import log_service
from . import log_dedupe_guard_v54 as v55
from . import log_identity_context_v60 as v60

logger = logging.getLogger("bot.log-consolidation-v67")

MERGE_WINDOW_SECONDS = 3.0
PRIMARY_HOLD_SECONDS = 0.90
UPDATE_WAIT_SECONDS = 0.55

# Une répétition Gateway/listener apparaît normalement immédiatement. Dix secondes
# couvrent les retries sans risquer de masquer une action réellement répétée plus tard.
EXACT_DEDUPE_TTL = 10.0
EXACT_DEDUPE_MAX = 8192
_EXACT_RECENT: dict[str, float] = {}
_EXACT_INFLIGHT: set[str] = set()

# guild_id -> (expiration, famille, embed source, sujet principal)
_SERVER_BURSTS: dict[int, tuple[float, str, discord.Embed, Any]] = {}


def _prune_bursts() -> None:
    now = time.monotonic()
    for guild_id, data in list(_SERVER_BURSTS.items())[:2000]:
        if data[0] <= now:
            _SERVER_BURSTS.pop(guild_id, None)


def _plain_exact(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _exact_event_key(guild: discord.Guild, log_type: str, embed: discord.Embed) -> str:
    """Empreinte métier complète, volontairement sans footer/timestamp de rendu.

    Les valeurs des champs font partie de la clé. Ainsi deux membres différents ou
    deux modifications différentes du même salon ne peuvent pas être confondus.
    """
    pieces = [
        str(guild.id),
        _plain_exact(log_type),
        _plain_exact(embed.title),
        _plain_exact(embed.description),
    ]
    for field in embed.fields:
        pieces.extend(
            (
                _plain_exact(field.name),
                _plain_exact(field.value),
                "1" if bool(field.inline) else "0",
            )
        )
    digest = hashlib.blake2b("\x1f".join(pieces).encode("utf-8"), digest_size=20).hexdigest()
    return f"v67:{guild.id}:{_plain_exact(log_type)}:{digest}"


def _prune_exact(now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    for key, expires in list(_EXACT_RECENT.items())[:EXACT_DEDUPE_MAX * 2]:
        if expires <= current:
            _EXACT_RECENT.pop(key, None)
    if len(_EXACT_RECENT) > EXACT_DEDUPE_MAX:
        overflow = len(_EXACT_RECENT) - EXACT_DEDUPE_MAX
        for key in list(_EXACT_RECENT)[:overflow]:
            _EXACT_RECENT.pop(key, None)


def _claim_exact(key: str) -> bool:
    now = time.monotonic()
    _prune_exact(now)
    if key in _EXACT_INFLIGHT or _EXACT_RECENT.get(key, 0.0) > now:
        return False
    _EXACT_INFLIGHT.add(key)
    return True


def _release_exact(key: str, sent: bool) -> None:
    _EXACT_INFLIGHT.discard(key)
    if sent:
        _EXACT_RECENT[key] = time.monotonic() + EXACT_DEDUPE_TTL
        _prune_exact()


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

    meaningful = (
        "nom", "name", "sujet modifie", "topic", "permissions modifie",
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
    if getattr(v60._display_channel, "_sentrix_single_channel_v61", False):
        return
    _single_channel_display._sentrix_single_channel_v61 = True
    v60._display_channel = _single_channel_display


def _unwrap_legacy_source_guard(sender):
    """Retire seulement le garde source V55, trop grossier pour certains updates.

    Son verrou de sortie TextChannel reste actif s'il a été installé. Les autres wrappers
    ne sont pas contournés.
    """
    seen: set[int] = set()
    current = sender
    while getattr(current, "_sentrix_source_dedupe_v55", False):
        ident = id(current)
        if ident in seen:
            break
        seen.add(ident)
        original = getattr(current, "_sentrix_original", None)
        if original is None or original is current:
            break
        current = original
    return current


async def _forward_sender(
    sender,
    bot,
    guild: discord.Guild,
    log_type: str,
    embed: discord.Embed,
    *,
    file: discord.File | None,
    view: discord.ui.View | None,
    event_key: str | None,
) -> bool:
    """Préserve le contrat du transport officiel, même avec une ancienne couche intermédiaire."""
    kwargs: dict[str, Any] = {"file": file}
    try:
        signature = inspect.signature(sender)
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if accepts_kwargs or "view" in signature.parameters:
            kwargs["view"] = view
        if accepts_kwargs or "event_key" in signature.parameters:
            kwargs["event_key"] = event_key
    except (TypeError, ValueError):
        # Le transport officiel SentriX accepte ces deux arguments. Ce repli vise les
        # callables dont Python ne peut pas introspecter la signature.
        kwargs["view"] = view
        kwargs["event_key"] = event_key
    return bool(await sender(bot, guild, log_type, embed, **kwargs))


def _install_source_consolidation() -> None:
    current = log_service.send_log
    if getattr(current, "_sentrix_log_consolidation_v67", False):
        return

    base_sender = _unwrap_legacy_source_guard(current)

    async def send_consolidated(
        bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        file: discord.File | None = None,
        *,
        view: discord.ui.View | None = None,
        event_key: str | None = None,
    ) -> bool:
        if not isinstance(embed, discord.Embed):
            return await _forward_sender(
                base_sender,
                bot,
                guild,
                log_type,
                embed,
                file=file,
                view=view,
                event_key=event_key,
            )

        exact_key = _exact_event_key(guild, str(log_type), embed)
        if not _claim_exact(exact_key):
            logger.info(
                "V67: vrai doublon identique supprimé guild=%s type=%s.",
                guild.id,
                log_type,
            )
            return False

        sent = False
        try:
            if str(log_type) == "server":
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
                    await asyncio.sleep(PRIMARY_HOLD_SECONDS)

                elif family == "channel_update" and _category_only_update(embed):
                    if _merge_update_into_primary(guild, embed):
                        logger.info(
                            "V67: update de catégorie absorbée dans la fiche principale guild=%s.",
                            guild.id,
                        )
                        return False
                    await asyncio.sleep(UPDATE_WAIT_SECONDS)
                    if _merge_update_into_primary(guild, embed):
                        logger.info(
                            "V67: update de catégorie anticipée fusionnée après attente guild=%s.",
                            guild.id,
                        )
                        return False

            sent = await _forward_sender(
                base_sender,
                bot,
                guild,
                log_type,
                embed,
                file=file,
                view=view,
                event_key=event_key,
            )
            return bool(sent)
        finally:
            _release_exact(exact_key, bool(sent))

    send_consolidated._sentrix_log_consolidation_v61 = True
    send_consolidated._sentrix_log_consolidation_v67 = True
    send_consolidated._sentrix_original = base_sender
    log_service.send_log = send_consolidated


def install(bot: commands.Bot | None = None, extension_name: str = "") -> None:
    del bot, extension_name
    _install_single_target_renderer()
    _install_source_consolidation()


__all__ = ["install"]
