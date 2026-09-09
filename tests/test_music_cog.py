"""Le moteur musique (utils/music/) est déjà testé isolément — voir
test_music_matcher.py / test_music_manager.py / test_music_provider_url_matching.py.
Ce fichier couvre le dernier scénario explicitement demandé et pas encore couvert :
« deux serveurs Discord utilisant la musique simultanément ». La règle explicite
était « une queue par serveur, jamais une queue globale » — ces tests prouvent que
GuildMusicQueue (cogs/music.py) ne fuit jamais d'un serveur à l'autre, y compris
quand deux résolutions tournent concurremment (asyncio.gather).

La connexion vocale réelle et FFmpeg ne peuvent pas être exercés dans cet
environnement (pas de gateway Discord, pas de sortie audio réelle) : `_play_track`
est donc remplacé par un faux qui reproduit son seul contrat observable pour ce test
(marquer `queue.current`, retourner True) sans lancer de sous-processus ffmpeg. Tout
le reste — get_queue(), _ensure_voice(), _resolve_and_queue(), _advance(), les
commandes elles-mêmes — est le vrai code de cogs/music.py, exécuté normalement."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from cogs.music import Music
from utils.music import ResolvedRequest, Track


class _FakeVoiceClient:
    def __init__(self, channel):
        self.channel = channel
        self._connected = True
        self._playing = False
        self._paused = False
        self.source = None

    def is_connected(self):
        return self._connected

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return self._paused

    def play(self, source, *, after=None):
        self._playing = True

    def stop(self):
        self._playing = False

    async def move_to(self, channel):
        self.channel = channel

    async def disconnect(self):
        self._connected = False


class _FakeVoiceChannel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.members = []

    async def connect(self):
        return _FakeVoiceClient(self)


class _FakeBot:
    def __init__(self, db):
        self.db = db

    async def wait_until_ready(self):
        return


class _FakeManager:
    """Remplace ProviderManager : aucun réseau, résout n'importe quelle requête en
    une piste jouable identifiée par la requête elle-même — juste assez pour
    prouver que deux résolutions concurrentes n'écrivent jamais dans la mauvaise
    file de serveur (le vrai moteur multi-provider est déjà testé séparément)."""

    async def resolve(self, query, *, requested_by):
        track = Track(
            title=query, artist="Artiste test", duration=180,
            playable_url=f"https://example.com/{query}.mp3",
            playback_provider="direct", provider="direct",
        )
        return ResolvedRequest(tracks=[track])


def _fake_ctx(guild_id, *, voice_channel, author_id=1):
    author = SimpleNamespace(id=author_id, voice=SimpleNamespace(channel=voice_channel))
    guild = SimpleNamespace(id=guild_id)
    return SimpleNamespace(
        guild=guild, author=author, channel=SimpleNamespace(send=AsyncMock()),
        interaction=None, send=AsyncMock(),
    )


class TwoGuildsSimultaneousMusicTests(unittest.IsolatedAsyncioTestCase):
    """Scénario explicitement demandé : deux serveurs Discord utilisant la
    musique en même temps ne doivent jamais interférer l'un avec l'autre."""

    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self._tmpdir.name, "sentrix-test.db"))
        await self.db.connect()
        self.bot = _FakeBot(self.db)
        self.cog = Music(self.bot)
        self.cog.manager = _FakeManager()

        async def _fake_play_track(queue, track, *, seek_seconds=0.0):
            queue.current = track
            return True

        self.cog._play_track = _fake_play_track

    async def asyncTearDown(self):
        self.cog.cog_unload()
        await self.db._conn.close()
        self._tmpdir.cleanup()

    async def test_deux_serveurs_ont_des_files_independantes(self):
        guild_a, guild_b = 1001, 2002
        ctx_a = _fake_ctx(guild_a, voice_channel=_FakeVoiceChannel(11))
        ctx_b = _fake_ctx(guild_b, voice_channel=_FakeVoiceChannel(22))

        await asyncio.gather(
            self.cog.music_play.callback(self.cog, ctx_a, recherche="chanson pour guilde A"),
            self.cog.music_play.callback(self.cog, ctx_b, recherche="chanson pour guilde B"),
        )

        queue_a = self.cog.get_queue(guild_a)
        queue_b = self.cog.get_queue(guild_b)
        self.assertIsNot(queue_a, queue_b)
        self.assertIsNotNone(queue_a.current)
        self.assertIsNotNone(queue_b.current)
        self.assertEqual(queue_a.current.title, "chanson pour guilde A")
        self.assertEqual(queue_b.current.title, "chanson pour guilde B")

        # Deuxième ajout sur A seulement : B ne doit jamais le voir.
        await self.cog.music_play.callback(self.cog, ctx_a, recherche="deuxieme titre A")
        self.assertEqual(len(queue_a.tracks), 1)
        self.assertEqual(queue_a.tracks[0].title, "deuxieme titre A")
        self.assertEqual(len(queue_b.tracks), 0)
        self.assertEqual(queue_b.current.title, "chanson pour guilde B")

    async def test_volume_et_boucle_ne_fuient_pas_entre_serveurs(self):
        guild_a, guild_b = 3003, 4004
        ctx_a = _fake_ctx(guild_a, voice_channel=_FakeVoiceChannel(33))

        await self.cog.music_volume.callback(self.cog, ctx_a, 20)
        await self.cog.music_loop.callback(self.cog, ctx_a, "queue")

        queue_a = self.cog.get_queue(guild_a)
        queue_b = self.cog.get_queue(guild_b)
        self.assertAlmostEqual(queue_a.volume, 0.20)
        self.assertTrue(queue_a.loop_queue)
        # Guilde B n'a rien configuré : elle garde les valeurs par défaut, jamais
        # celles de A (pas d'état global partagé entre les deux GuildMusicQueue).
        self.assertAlmostEqual(queue_b.volume, 0.5)
        self.assertFalse(queue_b.loop_queue)
        self.assertFalse(queue_b.loop_track)

    async def test_remove_sur_un_serveur_ne_touche_pas_l_autre(self):
        guild_a, guild_b = 5005, 6006
        ctx_a = _fake_ctx(guild_a, voice_channel=_FakeVoiceChannel(55))
        ctx_b = _fake_ctx(guild_b, voice_channel=_FakeVoiceChannel(66))

        await self.cog.music_play.callback(self.cog, ctx_a, recherche="A1")
        await self.cog.music_play.callback(self.cog, ctx_a, recherche="A2")
        await self.cog.music_play.callback(self.cog, ctx_b, recherche="B1")
        await self.cog.music_play.callback(self.cog, ctx_b, recherche="B2")

        queue_a = self.cog.get_queue(guild_a)
        queue_b = self.cog.get_queue(guild_b)
        self.assertEqual(len(queue_a.tracks), 1)  # A1 en cours, A2 en attente
        self.assertEqual(len(queue_b.tracks), 1)  # B1 en cours, B2 en attente

        await self.cog.music_remove.callback(self.cog, ctx_a, 1)
        self.assertEqual(len(queue_a.tracks), 0)
        self.assertEqual(len(queue_b.tracks), 1)  # inchangé côté B
        self.assertEqual(queue_b.tracks[0].title, "B2")


if __name__ == "__main__":
    unittest.main()
