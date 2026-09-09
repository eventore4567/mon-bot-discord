"""Tampon PCM de lecture anticipée pour la voix Discord.

FFmpeg lit les flux HTTP distants plus vite que le temps réel lorsqu'il le peut.
Ce wrapper conserve quelques secondes de PCM en mémoire afin qu'une courte baisse
de débit du fournisseur (SoundCloud, audio direct, etc.) ne se transforme pas en
silence audible dans Discord.

Le tampon ne contourne aucune protection de plateforme : il ne fait que lisser le
flux déjà autorisé fourni au lecteur FFmpeg.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

import discord

logger = logging.getLogger("bot.music-audio-buffer")

_FRAME_SECONDS = 0.020  # discord.py consomme une trame PCM toutes les 20 ms.
_SENTINEL = object()


class BufferedPCMAudio(discord.AudioSource):
    """AudioSource PCM avec lecture anticipée bornée et diagnostic d'underrun."""

    def __init__(
        self,
        source: discord.AudioSource,
        *,
        prebuffer_seconds: float = 4.0,
        max_buffer_seconds: float = 12.0,
        startup_timeout: float = 5.0,
        label: str = "",
    ) -> None:
        if source.is_opus():
            raise TypeError("BufferedPCMAudio attend une source PCM, pas Opus")
        self.original = source
        self.label = label
        self.prebuffer_frames = max(1, int(prebuffer_seconds / _FRAME_SECONDS))
        max_frames = max(self.prebuffer_frames + 1, int(max_buffer_seconds / _FRAME_SECONDS))
        self._frames: queue.Queue[Any] = queue.Queue(maxsize=max_frames)
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._closed = False
        self._eof = False
        self._started = False
        self._startup_timeout = max(0.1, float(startup_timeout))
        self._underruns = 0
        self._last_underrun_log = 0.0
        self._producer = threading.Thread(
            target=self._produce,
            name=f"sentrix-audio-buffer-{label or 'stream'}",
            daemon=True,
        )
        self._producer.start()

    @property
    def underruns(self) -> int:
        return self._underruns

    @property
    def buffered_seconds(self) -> float:
        return self._frames.qsize() * _FRAME_SECONDS

    def _put(self, item: Any) -> bool:
        while not self._stop.is_set():
            try:
                self._frames.put(item, timeout=0.20)
                return True
            except queue.Full:
                continue
        return False

    def _produce(self) -> None:
        try:
            while not self._stop.is_set():
                data = self.original.read()
                if not data:
                    self._eof = True
                    self._ready.set()
                    self._put(_SENTINEL)
                    return
                if not self._put(data):
                    return
                if self._frames.qsize() >= self.prebuffer_frames:
                    self._ready.set()
        except Exception:
            logger.exception("producteur audio buffer en échec label=%s", self.label)
            self._eof = True
            self._ready.set()
            self._put(_SENTINEL)
        finally:
            self._ready.set()

    def read(self) -> bytes:
        if self._closed:
            return b""

        if not self._started:
            self._started = True
            # On commence dès que le tampon cible est rempli. Si le fournisseur est
            # lent au démarrage, on ne bloque jamais plus longtemps que ce délai.
            self._ready.wait(self._startup_timeout)

        if self._frames.empty() and not self._eof:
            self._underruns += 1
            now = time.monotonic()
            if now - self._last_underrun_log >= 5.0:
                self._last_underrun_log = now
                logger.warning(
                    "audio jitter buffer underrun -> %s count=%s",
                    self.label or "stream",
                    self._underruns,
                )

        try:
            item = self._frames.get(timeout=20.0)
        except queue.Empty:
            logger.warning("audio jitter buffer timeout -> %s", self.label or "stream")
            return b""

        if item is _SENTINEL:
            return b""
        return item

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        try:
            self.original.cleanup()
        finally:
            try:
                self._frames.put_nowait(_SENTINEL)
            except queue.Full:
                pass
            if self._producer.is_alive():
                self._producer.join(timeout=0.5)


__all__ = ["BufferedPCMAudio"]
