"""Logs vocaux lisibles et orientés événement pour SentriX.

Remplace uniquement le listener vocal du cog Logs :
- connexion -> membre + salon ;
- déconnexion -> membre + salon quitté + durée connue ;
- déplacement -> membre + avant/après ;
- les changements micro/casque/caméra sans changement de salon ne polluent plus log_voice.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

import discord
from discord.ext import commands

from utils import log_service

logger = logging.getLogger("bot.voice-logs-v2")


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


def _seed_existing_sessions(bot: commands.Bot, sessions: dict[tuple[int, int], datetime | None]) -> None:
    """Marque les connexions déjà présentes sans inventer leur heure de début."""
    for guild in bot.guilds:
        for member_id, voice_state in guild.voice_states.items():
            if voice_state.channel is not None:
                sessions.setdefault((guild.id, int(member_id)), None)


def _remove_official_listener(bot: commands.Bot, logs_cog) -> int:
    listener = getattr(logs_cog, "on_voice_state_update", None)
    if listener is None:
        return 0
    removed = 0
    registered = bot.extra_events.get("on_voice_state_update", [])
    while listener in registered:
        bot.remove_listener(listener, "on_voice_state_update")
        removed += 1
        registered = bot.extra_events.get("on_voice_state_update", [])
    return removed


def install(bot: commands.Bot) -> bool:
    if getattr(bot, "_sentrix_voice_logs_v2", False):
        return True

    logs_cog = bot.get_cog("Logs")
    if logs_cog is None:
        logger.warning("Logs vocaux V2 non installés : cog Logs absent.")
        return False

    sessions: dict[tuple[int, int], datetime | None] = {}
    _seed_existing_sessions(bot, sessions)
    removed = _remove_official_listener(bot, logs_cog)

    async def on_ready() -> None:
        # Un reconnect Discord ne doit pas écraser le vrai début d'une session déjà suivie.
        _seed_existing_sessions(bot, sessions)

    async def on_voice_state_update(
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        # Mute/deaf/stream/caméra ne sont pas des déplacements vocaux.
        if before.channel == after.channel:
            return

        key_id = (member.guild.id, member.id)
        before_channel = before.channel
        after_channel = after.channel
        now = discord.utils.utcnow()

        if before_channel is None and after_channel is not None:
            sessions[key_id] = now
            title = "Activité vocale — Connexion"
            fields = (
                ("Membre", member.mention, False),
                ("Salon", after_channel.mention, False),
            )
            event_type = "voice_join"

        elif before_channel is not None and after_channel is None:
            started_at = sessions.pop(key_id, None)
            fields_list: list[tuple[str, str, bool]] = [
                ("Membre", member.mention, False),
                ("Salon quitté", before_channel.mention, False),
            ]
            if started_at is not None:
                fields_list.append(
                    ("Durée", _format_duration((now - started_at).total_seconds()), False)
                )
            title = "Activité vocale — Déconnexion"
            fields = tuple(fields_list)
            event_type = "voice_leave"

        elif before_channel is not None and after_channel is not None:
            # Si SentriX a démarré pendant la session, garde l'état "durée inconnue".
            sessions.setdefault(key_id, None)
            title = "Activité vocale — Déplacement"
            fields = (
                ("Membre", member.mention, False),
                ("Avant", before_channel.mention, False),
                ("Après", after_channel.mention, False),
            )
            event_type = "voice_move"
        else:
            return

        panel = logs_cog._embed(title, fields=fields)
        event_key = log_service.make_event_key(
            member.guild.id,
            event_type,
            target_id=member.id,
            discriminator=(
                f"{before_channel.id if before_channel else 0}:"
                f"{after_channel.id if after_channel else 0}:"
                f"{int(time.time() // 2)}"
            ),
        )
        await logs_cog._send(
            member.guild,
            # event_type (voice_join/leave/move), pas "log_voice" : ce dernier
            # est un alias de CATEGORIE qui court-circuite canonical_event_type
            # avant qu'il ne puisse reconnaitre l'evenement precis via le titre —
            # narrative_body() tombait donc dans le fallback generique, qui
            # filtre les mentions courtes (Membre, Salon, Duree).
            event_type,
            panel,
            event_key=event_key,
        )

    bot.add_listener(on_ready, "on_ready")
    bot.add_listener(on_voice_state_update, "on_voice_state_update")
    bot._sentrix_voice_sessions_v2 = sessions
    bot._sentrix_voice_logs_v2_ready_listener = on_ready
    bot._sentrix_voice_logs_v2_listener = on_voice_state_update
    bot._sentrix_voice_logs_v2 = True
    logger.info(
        "Logs vocaux V2 actifs : listener legacy retiré=%s, connexion/déconnexion/déplacement séparés.",
        removed,
    )
    return True


__all__ = ["install"]
