"""Suppressions de messages regroupées par salon.

Mesuré le 12/10/2026 (tools/spam_burst_e2e.py, 20 spammeurs simultanés) : chaque
message de spam partait dans son propre appel DELETE. Discord limite ces appels
par salon ; la file s'allongeait de plusieurs secondes par spammeur, et le spam
restait visible pendant tout ce temps.

Ici, la première suppression d'un salon part tout de suite. Celles qui arrivent
pendant qu'un appel est en cours s'accumulent et partent ensemble au tour
suivant, en un seul appel de suppression groupée (jusqu'à 100 messages). Aucun
délai n'est ajouté au premier message : on ne regroupe que ce qui attendait de
toute façon.
"""
from __future__ import annotations

import asyncio
import logging

import discord

logger = logging.getLogger("bot.purge_queue")

BULK_LIMIT = 100  # maximum Discord par appel de suppression groupée


class SuppressionsGroupees:
    """File de suppression par salon. ``supprimer`` retourne True si CE message a
    été supprimé par nous (comme ``message.delete()`` qui n'a pas levé)."""

    def __init__(self) -> None:
        self._attente: dict[int, dict[int, tuple[discord.Message, asyncio.Future]]] = {}
        self._vidages: dict[int, asyncio.Task] = {}

    async def supprimer(self, message: discord.Message) -> bool:
        channel_id = message.channel.id
        bucket = self._attente.setdefault(channel_id, {})
        existing = bucket.get(message.id)
        if existing is not None:
            return await asyncio.shield(existing[1])
        future = asyncio.get_running_loop().create_future()
        bucket[message.id] = (message, future)
        task = self._vidages.get(channel_id)
        if task is None or task.done():
            self._vidages[channel_id] = asyncio.create_task(self._vider(channel_id))
        return await asyncio.shield(future)

    async def _vider(self, channel_id: int) -> None:
        try:
            while True:
                bucket = self._attente.pop(channel_id, None)
                if not bucket:
                    return
                items = list(bucket.values())
                for start in range(0, len(items), BULK_LIMIT):
                    await self._envoyer(items[start:start + BULK_LIMIT])
        finally:
            self._vidages.pop(channel_id, None)
            # Arrivé entre le dernier pop et la sortie : relancer plutôt que perdre.
            if self._attente.get(channel_id):
                self._vidages[channel_id] = asyncio.create_task(self._vider(channel_id))

    async def _envoyer(self, items: list[tuple[discord.Message, asyncio.Future]]) -> None:
        messages = [message for message, _future in items]
        if len(messages) > 1:
            try:
                await messages[0].channel.delete_messages(messages)
                self._resoudre(items, True)
                return
            except discord.NotFound:
                # Un message déjà disparu fait échouer tout le lot : un par un.
                pass
            except discord.HTTPException as exc:
                logger.info("Suppression groupée refusée (%s) : repli un par un sur %s messages.",
                            exc.status, len(messages))
            except Exception:
                logger.exception("Suppression groupée impossible : repli un par un.")
        for message, future in items:
            try:
                await message.delete()
                ok = True
            except discord.HTTPException:
                ok = False
            except Exception:
                logger.exception("Suppression impossible message=%s", getattr(message, "id", "?"))
                ok = False
            if not future.done():
                future.set_result(ok)

    @staticmethod
    def _resoudre(items, ok: bool) -> None:
        for _message, future in items:
            if not future.done():
                future.set_result(ok)


__all__ = ["SuppressionsGroupees", "BULK_LIMIT"]
