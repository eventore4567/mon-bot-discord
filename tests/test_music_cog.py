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
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
        self.move_calls = 0
        self.last_after = None

    def is_connected(self):
        return self._connected

    def is_playing(self):
        return self._playing

    def is_paused(self):
        return self._paused

    def play(self, source, *, after=None):
        self._playing = True
        self._paused = False
        self.source = source
        self.last_after = after

    def pause(self):
        if self._playing:
            self._playing = False
            self._paused = True

    def resume(self):
        if self._paused:
            self._paused = False
            self._playing = True

    def stop(self):
        self._playing = False
        self._paused = False

    async def move_to(self, channel):
        self.move_calls += 1
        self.channel = channel

    async def disconnect(self):
        self._connected = False
        self._playing = False
        self._paused = False


class _FakeVoiceChannel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.members = []
        self.connect_calls = 0

    async def connect(self):
        self.connect_calls += 1
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


    async def test_unconfigured_player_reuses_voice_when_already_in_correct_channel(self):
        channel = _FakeVoiceChannel(70)
        ctx = _fake_ctx(7070, voice_channel=channel)
        queue = self.cog.get_queue(7070)
        voice = _FakeVoiceClient(channel)
        queue.voice_client = voice

        resolved = await self.cog._ensure_voice(ctx)

        self.assertIs(resolved, queue)
        self.assertIs(queue.voice_client, voice)
        self.assertEqual(channel.connect_calls, 0)
        self.assertEqual(voice.move_calls, 0)

    async def test_unconfigured_player_moves_existing_voice_instead_of_reconnecting(self):
        old_channel = _FakeVoiceChannel(71)
        target_channel = _FakeVoiceChannel(72)
        ctx = _fake_ctx(7171, voice_channel=target_channel)
        queue = self.cog.get_queue(7171)
        voice = _FakeVoiceClient(old_channel)
        queue.voice_client = voice

        resolved = await self.cog._ensure_voice(ctx)

        self.assertIs(resolved, queue)
        self.assertIs(queue.voice_client, voice)
        self.assertIs(voice.channel, target_channel)
        self.assertEqual(voice.move_calls, 1)
        self.assertEqual(target_channel.connect_calls, 0)

    async def test_skip_advances_once_and_stop_clears_player_state(self):
        queue = self.cog.get_queue(7272)
        voice = _FakeVoiceClient(_FakeVoiceChannel(73))
        voice._playing = True
        queue.voice_client = voice
        first = Track(title="premier", artist="A", duration=180)
        second = Track(title="second", artist="B", duration=180)
        queue.current = first
        queue.tracks = [second]
        before_generation = queue.playback_generation

        skipped = await self.cog._skip_queue(queue)

        self.assertTrue(skipped)
        self.assertIs(queue.current, second)
        self.assertIn(first, queue.history)
        self.assertGreater(queue.playback_generation, before_generation)

        queue.tracks = [Track(title="reste", artist="C")]
        voice._playing = True
        had_activity = await self.cog._stop_queue(queue)

        self.assertTrue(had_activity)
        self.assertIsNone(queue.current)
        self.assertEqual(queue.tracks, [])
        self.assertFalse(queue.loop_track)
        self.assertFalse(queue.loop_queue)
        self.assertFalse(queue.autoplay)
        self.assertEqual(queue.position_seconds(), 0.0)

    async def test_play_track_refreshes_expired_source_before_every_start(self):
        queue = self.cog.get_queue(7373)
        voice = _FakeVoiceClient(_FakeVoiceChannel(74))
        queue.voice_client = voice
        track = Track(
            title="URL temporaire",
            artist="A",
            duration=180,
            playable_url="https://expired.example/audio",
            playback_provider="direct",
            provider="direct",
        )
        manager = SimpleNamespace(
            refresh_playable_url=AsyncMock(return_value="https://fresh.example/audio")
        )
        self.cog.manager = manager

        ffmpeg = SimpleNamespace(cleanup=lambda: None)
        buffered = SimpleNamespace(underruns=0, cleanup=lambda: None)
        source = SimpleNamespace(volume=queue.volume, cleanup=lambda: None)

        with (
            patch("cogs.music.discord.FFmpegPCMAudio", return_value=ffmpeg) as ffmpeg_cls,
            patch("cogs.music.BufferedPCMAudio", return_value=buffered),
            patch("cogs.music.discord.PCMVolumeTransformer", return_value=source),
        ):
            started = await Music._play_track(self.cog, queue, track)

        self.assertTrue(started)
        manager.refresh_playable_url.assert_awaited_once_with(track)
        ffmpeg_cls.assert_called_once()
        self.assertEqual(ffmpeg_cls.call_args.args[0], "https://fresh.example/audio")
        self.assertIs(queue.current, track)
        self.assertIs(voice.source, source)

    async def test_sentrix_music_card_is_compact_and_has_five_useful_actions(self):
        queue = self.cog.get_queue(7474)
        queue.current = Track(
            title="Faded",
            artist="Alan Walker",
            album="Different World",
            duration=212,
            thumbnail="https://example.test/cover.jpg",
            provider="spotify",
            playback_provider="youtube",
        )
        queue.elapsed_offset = 64.0
        queue.started_at = 0.0
        queue.volume = 0.7
        queue.tracks = [Track(title="Next")]

        panel = self.cog._music_player_panel(queue)
        text = panel.titre + "\n" + panel.sous_titre + "\n" + "\n".join(
            section.rendu(index)
            for index, section in enumerate(panel.sections_source, start=1)
        )

        self.assertEqual(panel.kind, "musique")
        self.assertIn("Lecture en cours", text)
        self.assertNotIn("SentriX Music", text)
        self.assertIn("Faded", text)
        self.assertIn("Alan Walker", text)
        self.assertIn("Progression", text)
        self.assertIn("Spotify → YouTube", text)
        self.assertIn("70 %", text)
        self.assertEqual(
            [button.libelle for button in panel.boutons_source],
            ["Pause / Reprendre", "Suivant", "Stop", "File", "Playlists"],
        )
        self.assertTrue(all(callable(button.callback) for button in panel.boutons_source))
    async def test_pause_resume_freeze_position_clock(self):
        queue = self.cog.get_queue(7007)
        voice = _FakeVoiceClient(_FakeVoiceChannel(77))
        voice._playing = True
        queue.voice_client = voice
        queue.elapsed_offset = 5.0
        queue.started_at = time.monotonic() - 10.0

        self.assertTrue(self.cog._pause_queue(queue))
        paused_position = queue.position_seconds()
        self.assertEqual(queue.started_at, 0.0)
        await asyncio.sleep(0.02)
        self.assertAlmostEqual(queue.position_seconds(), paused_position, delta=0.01)

        self.assertTrue(self.cog._resume_queue(queue))
        self.assertGreater(queue.started_at, 0.0)
        self.assertFalse(queue.paused_by_user)

    async def test_stale_audio_callback_cannot_advance_queue_twice(self):
        queue = self.cog.get_queue(8008)
        queue.voice_client = _FakeVoiceClient(_FakeVoiceChannel(88))
        current = Track(title="courant", artist="A", duration=180)
        following = Track(title="suivant", artist="B", duration=180)
        queue.current = current
        queue.tracks = [following]
        queue.playback_generation = 10

        await self.cog._on_track_finished(
            queue,
            generation=9,
            finished_track=current,
        )

        self.assertIs(queue.current, current)
        self.assertEqual(queue.tracks, [following])

    async def test_long_queue_auto_skips_broken_tracks_once_then_continues(self):
        queue = self.cog.get_queue(9009)
        queue.voice_client = _FakeVoiceClient(_FakeVoiceChannel(99))
        queue.text_channel = SimpleNamespace(send=AsyncMock())
        broken = [
            Track(title=f"cassé-{index}", artist="X", duration=180)
            for index in range(25)
        ]
        good = Track(title="jouable", artist="Y", duration=180)
        queue.tracks = [*broken, good]

        async def selective_play(q, track, *, seek_seconds=0.0, recovery=False):
            if track.title.startswith("cassé-"):
                return False
            q.current = track
            q.playback_generation += 1
            return True

        self.cog._play_track = selective_play
        await self.cog._advance(queue)

        self.assertIs(queue.current, good)
        self.assertEqual(queue.tracks, [])
        self.assertEqual(queue.text_channel.send.await_count, 1)
        notice = queue.text_channel.send.await_args.args[0]
        self.assertIn("25 titre(s) indisponible(s)", notice)
        self.assertIn("jouable", notice)

    async def test_runtime_audio_error_restarts_same_track_once(self):
        queue = self.cog.get_queue(10010)
        queue.voice_client = _FakeVoiceClient(_FakeVoiceChannel(101))
        queue.text_channel = SimpleNamespace(send=AsyncMock())
        track = Track(title="fragile", artist="A", duration=180)
        following = Track(title="après", artist="B", duration=180)
        queue.current = track
        queue.tracks = [following]
        queue.elapsed_offset = 42.0
        queue.started_at = 0.0
        queue.playback_generation = 3
        calls = []

        async def restart(q, candidate, *, seek_seconds=0.0, recovery=False):
            calls.append((candidate, seek_seconds, recovery))
            q.current = candidate
            q.playback_generation += 1
            return True

        self.cog._play_track = restart
        await self.cog._on_track_finished(
            queue,
            error=RuntimeError("ffmpeg stream ended"),
            generation=3,
            finished_track=track,
        )

        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], track)
        self.assertAlmostEqual(calls[0][1], 42.0, delta=0.1)
        self.assertTrue(calls[0][2])
        self.assertEqual(queue.tracks, [following])
        self.assertEqual(queue.recovery_attempts, 1)

    async def test_voice_outage_preserves_current_track_and_pending_queue(self):
        queue = self.cog.get_queue(11011)
        voice = _FakeVoiceClient(_FakeVoiceChannel(111))
        voice._connected = False
        queue.voice_client = voice
        queue.text_channel = SimpleNamespace(send=AsyncMock())
        track = Track(title="à reprendre", artist="A", duration=180)
        following = Track(title="ensuite", artist="B", duration=180)
        queue.current = track
        queue.tracks = [following]
        queue.elapsed_offset = 30.0
        queue.playback_generation = 4

        await self.cog._on_track_finished(
            queue,
            error=RuntimeError("voice websocket closed"),
            generation=4,
            finished_track=track,
        )

        self.assertIs(queue.current, track)
        self.assertEqual(queue.tracks, [following])
        notice = queue.text_channel.send.await_args.args[0]
        self.assertIn("file sont conservées", notice)

    async def test_wrong_voice_cannot_control_active_player(self):
        queue = self.cog.get_queue(12012)
        bot_channel = _FakeVoiceChannel(121)
        bot_channel.name = "Musique"
        queue.voice_client = _FakeVoiceClient(bot_channel)
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=12012, voice_client=queue.voice_client),
            author=SimpleNamespace(voice=SimpleNamespace(channel=_FakeVoiceChannel(122))),
            interaction=None,
        )

        short = AsyncMock()
        with patch("cogs.music.panels.texte_court", new=short):
            voice = await self.cog._require_control_voice(ctx, queue)

        self.assertIsNone(voice)
        self.assertEqual(short.await_count, 1)
        self.assertIn("Rejoins", short.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
