"""Persistance des connexions vocales de SentriX.

Une connexion créée par ``/music join`` ou ``/music play`` reste épinglée jusqu'à
``/music leave``. Une file vide, l'absence de membres humains ou la fin d'un titre
ne provoquent jamais de départ automatique. Si l'instance Discord redémarre, perd
sa connexion vocale ou qu'un failover HA a lieu, le salon mémorisé est rejoint de
nouveau dès que l'instance active est prête.

La volonté de rester dans le salon est persistée en SQLite et, lorsqu'il est
configuré, immédiatement checkpointée vers le stockage durable PostgreSQL. Aucun
état de lecture audio n'est inventé : seule la présence dans le salon vocal est
restaurée.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time
import types
from typing import Any

from discord.ext import commands

logger = logging.getLogger("bot.music-persistence")

_RETRY_SECONDS = 30
_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS music_voice_sessions (
    guild_id INTEGER PRIMARY KEY,
    voice_channel_id INTEGER NOT NULL,
    text_channel_id INTEGER,
    updated_at INTEGER NOT NULL
)
"""


class PersistentVoiceState:
    def __init__(self, bot: commands.Bot, cog: Any):
        self.bot = bot
        self.cog = cog
        self._schema_ready = False
        self._restore_lock = asyncio.Lock()
        self._closed = False
        self._watchdog_task: asyncio.Task | None = None

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        await self.bot.db.execute(_TABLE_SQL)
        self._schema_ready = True

    async def _durable_checkpoint(self, reason: str) -> None:
        durable = getattr(self.bot, "sentrix_durable_store", None)
        if durable is None or not getattr(durable, "configured", False):
            return
        try:
            await asyncio.wait_for(
                durable.snapshot(reason=reason, clean_shutdown=False),
                timeout=15,
            )
        except Exception as exc:
            # La connexion vocale reste valide même si le miroir durable est
            # momentanément indisponible ; le prochain snapshot normal la reprendra.
            logger.warning("checkpoint vocal durable impossible: %s", exc)

    async def remember(
        self,
        guild_id: int,
        voice_channel_id: int,
        text_channel_id: int | None = None,
    ) -> None:
        await self.ensure_schema()
        previous = await self.bot.db.fetchone(
            "SELECT voice_channel_id, text_channel_id FROM music_voice_sessions WHERE guild_id = ?",
            (guild_id,),
        )
        changed = (
            previous is None
            or int(previous["voice_channel_id"]) != int(voice_channel_id)
            or (previous["text_channel_id"] if previous["text_channel_id"] is not None else None)
            != (int(text_channel_id) if text_channel_id is not None else None)
        )
        await self.bot.db.execute(
            "INSERT INTO music_voice_sessions "
            "(guild_id, voice_channel_id, text_channel_id, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "voice_channel_id=excluded.voice_channel_id, "
            "text_channel_id=excluded.text_channel_id, updated_at=excluded.updated_at",
            (guild_id, voice_channel_id, text_channel_id, int(time.time())),
        )
        if changed:
            logger.info(
                "salon vocal épinglé -> guild=%s voice=%s text=%s",
                guild_id,
                voice_channel_id,
                text_channel_id,
            )
            await self._durable_checkpoint("music_voice_pin")

    async def remember_queue(self, queue: Any) -> None:
        vc = getattr(queue, "voice_client", None)
        if vc is None:
            return
        try:
            connected = bool(vc.is_connected())
        except Exception:
            connected = False
        channel = getattr(vc, "channel", None)
        if not connected or channel is None:
            return
        text_channel = getattr(queue, "text_channel", None)
        await self.remember(
            int(queue.guild_id),
            int(channel.id),
            int(text_channel.id) if getattr(text_channel, "id", None) is not None else None,
        )

    async def forget(self, guild_id: int) -> None:
        await self.ensure_schema()
        existing = await self.bot.db.fetchone(
            "SELECT 1 FROM music_voice_sessions WHERE guild_id = ?",
            (guild_id,),
        )
        await self.bot.db.execute(
            "DELETE FROM music_voice_sessions WHERE guild_id = ?",
            (guild_id,),
        )
        if existing is not None:
            logger.info("salon vocal désépinglé explicitement -> guild=%s", guild_id)
            await self._durable_checkpoint("music_voice_unpin")

    async def is_pinned(self, guild_id: int) -> bool:
        await self.ensure_schema()
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM music_voice_sessions WHERE guild_id = ?",
            (guild_id,),
        )
        return row is not None

    async def restore_all(self) -> None:
        if self._closed or not self.bot.is_ready() or self.bot.is_closed():
            return
        async with self._restore_lock:
            await self.ensure_schema()
            rows = await self.bot.db.fetchall(
                "SELECT guild_id, voice_channel_id, text_channel_id "
                "FROM music_voice_sessions ORDER BY guild_id"
            )
            for row in rows:
                guild_id = int(row["guild_id"])
                guild = self.bot.get_guild(guild_id)
                if guild is None:
                    # Le bot n'est plus dans ce serveur : la cible ne peut plus être
                    # rejointe et l'enregistrement serait définitivement orphelin.
                    await self.forget(guild_id)
                    continue

                voice_channel = guild.get_channel(int(row["voice_channel_id"]))
                if voice_channel is None or not hasattr(voice_channel, "connect"):
                    logger.warning(
                        "salon vocal épinglé introuvable, épingle supprimée -> guild=%s channel=%s",
                        guild_id,
                        row["voice_channel_id"],
                    )
                    await self.forget(guild_id)
                    continue

                queue = self.cog.get_queue(guild_id)
                text_id = row["text_channel_id"]
                if text_id is not None:
                    text_channel = guild.get_channel(int(text_id))
                    if text_channel is not None and hasattr(text_channel, "send"):
                        queue.text_channel = text_channel

                vc = getattr(guild, "voice_client", None) or getattr(queue, "voice_client", None)
                if vc is not None:
                    try:
                        if vc.is_connected():
                            queue.voice_client = vc
                            # Si Discord ou un administrateur a déplacé SentriX, la
                            # destination réelle devient la nouvelle cible persistante.
                            current_channel = getattr(vc, "channel", None)
                            if current_channel is not None and int(current_channel.id) != int(voice_channel.id):
                                await self.remember(
                                    guild_id,
                                    int(current_channel.id),
                                    int(queue.text_channel.id) if getattr(queue.text_channel, "id", None) is not None else None,
                                )
                            continue
                        # Un VoiceClient peut être en plein handshake/reconnect. On ne
                        # crée pas une seconde connexion concurrente ; le watchdog réessaie.
                        continue
                    except Exception:
                        continue

                try:
                    queue.voice_client = await voice_channel.connect(timeout=30, reconnect=True)
                    logger.warning(
                        "connexion vocale persistante restaurée -> guild=%s channel=%s",
                        guild_id,
                        voice_channel.id,
                    )
                except Exception as exc:
                    # Permissions, réseau ou Discord indisponible : on conserve l'épingle
                    # et on réessaie indéfiniment tant que /music leave n'est pas appelé.
                    logger.warning(
                        "reconnexion vocale différée -> guild=%s channel=%s error=%s",
                        guild_id,
                        voice_channel.id,
                        str(exc)[:180],
                    )

    async def on_ready(self) -> None:
        await self.restore_all()

    async def on_voice_state_update(self, member: Any, before: Any, after: Any) -> None:
        user = getattr(self.bot, "user", None)
        if user is None or getattr(member, "id", None) != getattr(user, "id", None):
            return
        guild = getattr(member, "guild", None)
        if guild is None:
            return

        # Une arrivée ou un déplacement du bot devient la nouvelle cible persistante.
        # Un départ externe, crash ou failover ne supprime JAMAIS l'épingle : le
        # watchdog rétablira la connexion. Seul /music leave appelle forget().
        channel = getattr(after, "channel", None)
        if channel is not None:
            queue = self.cog.get_queue(guild.id)
            queue.voice_client = getattr(guild, "voice_client", None) or queue.voice_client
            text_channel = getattr(queue, "text_channel", None)
            await self.remember(
                int(guild.id),
                int(channel.id),
                int(text_channel.id) if getattr(text_channel, "id", None) is not None else None,
            )

    async def watchdog(self) -> None:
        try:
            await self.bot.wait_until_ready()
            while not self._closed and not self.bot.is_closed():
                try:
                    await self.restore_all()
                except Exception:
                    logger.exception("watchdog de reconnexion vocale en échec")
                await asyncio.sleep(_RETRY_SECONDS)
        except asyncio.CancelledError:
            return

    def start(self) -> None:
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(
                self.watchdog(),
                name="sentrix-music-persistent-voice",
            )

    def close(self) -> None:
        self._closed = True
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()


def _find_context(args: tuple[Any, ...], kwargs: dict[str, Any]) -> commands.Context | None:
    ctx = kwargs.get("ctx")
    if isinstance(ctx, commands.Context):
        return ctx
    for value in args:
        if isinstance(value, commands.Context):
            return value
    return None


def install_on_cog(bot: commands.Bot, cog: Any) -> PersistentVoiceState:
    """Branche la persistance sur le Cog Music déjà enregistré."""
    existing = getattr(cog, "_sentrix_persistent_voice", None)
    if isinstance(existing, PersistentVoiceState):
        return existing

    state = PersistentVoiceState(bot, cog)
    cog._sentrix_persistent_voice = state

    # 1) Toute connexion/migration réussie via /music join ou /music play est épinglée.
    original_ensure_voice = cog._ensure_voice

    async def _ensure_voice_persistent(self, ctx):
        queue = await original_ensure_voice(ctx)
        if queue is not None:
            await state.remember_queue(queue)
        return queue

    cog._ensure_voice = types.MethodType(_ensure_voice_persistent, cog)

    # 2) Fin de file, salon vide ou /music stop ne doivent plus déclencher de départ.
    def _never_disconnect_for_inactivity(self, queue):
        cancel = getattr(self, "_cancel_disconnect", None)
        if callable(cancel):
            cancel(queue)
        logger.debug("départ automatique ignoré : salon vocal épinglé guild=%s", queue.guild_id)

    cog._schedule_disconnect = types.MethodType(_never_disconnect_for_inactivity, cog)

    # 3) /music leave est l'UNIQUE action qui retire l'épingle. Le wrapper conserve
    # la signature de la commande pour ne pas polluer les audits +/slash.
    leave_command = bot.get_command("music leave")
    if leave_command is not None and not getattr(leave_command, "_sentrix_persistent_leave", False):
        original_callback = leave_command.callback

        @functools.wraps(original_callback)
        async def _leave_with_unpin(*args, **kwargs):
            ctx = _find_context(args, kwargs)
            if ctx is not None and ctx.guild is not None:
                await state.forget(int(ctx.guild.id))
            return await original_callback(*args, **kwargs)

        try:
            _leave_with_unpin.__signature__ = inspect.signature(original_callback)
        except (TypeError, ValueError):
            pass
        leave_command.callback = _leave_with_unpin
        leave_command._sentrix_persistent_leave = True

    # 4) Restaurer immédiatement après READY, puis toutes les 30 s si Discord/Railway
    # a coupé la connexion. Une déconnexion externe ne vaut jamais "leave".
    bot.add_listener(state.on_ready, "on_ready")
    bot.add_listener(state.on_voice_state_update, "on_voice_state_update")

    original_unload = getattr(cog, "cog_unload", None)

    def _cog_unload_persistent():
        state.close()
        try:
            bot.remove_listener(state.on_ready, "on_ready")
            bot.remove_listener(state.on_voice_state_update, "on_voice_state_update")
        except Exception:
            pass
        if callable(original_unload):
            return original_unload()
        return None

    cog.cog_unload = _cog_unload_persistent
    state.start()
    logger.warning(
        "Musique V104 voix persistante active : aucun départ automatique ; "
        "reconnexion après restart/failover jusqu'à /music leave."
    )
    return state


__all__ = ["PersistentVoiceState", "install_on_cog"]
