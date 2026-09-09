"""Reconnaissance d'URL des VRAIS providers (pas des factices) — pure logique
regex, aucun réseau. Si un provider ne reconnaît pas son propre format d'URL, le
ProviderManager le fait tomber sur SearchProvider (recherche texte de l'URL brute),
qui échouera silencieusement : c'est le genre de bug qui semble fonctionner en test
manuel rapide et casse sur un lien légèrement différent (playlist, lien court,
paramètres de partage...)."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.music.providers.deezer import DeezerProvider
from utils.music.providers.direct_audio import DirectAudioProvider
from utils.music.providers.soundcloud import SoundCloudProvider
from utils.music.providers.spotify import SpotifyProvider
from utils.music.providers.youtube import YouTubeProvider


class YouTubeMatchTests(unittest.TestCase):
    def setUp(self):
        self.provider = YouTubeProvider()

    def test_reconnait_youtube_watch(self):
        self.assertTrue(self.provider.matches("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_reconnait_youtu_be(self):
        self.assertTrue(self.provider.matches("https://youtu.be/dQw4w9WgXcQ"))

    def test_reconnait_youtube_music(self):
        self.assertTrue(self.provider.matches("https://music.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_reconnait_playlist(self):
        self.assertTrue(self.provider.matches("https://www.youtube.com/playlist?list=PLabc123"))

    def test_rejette_un_titre_simple(self):
        self.assertFalse(self.provider.matches("Toto Africa"))

    def test_rejette_spotify(self):
        self.assertFalse(self.provider.matches("https://open.spotify.com/track/abc"))


class SoundCloudMatchTests(unittest.TestCase):
    def setUp(self):
        self.provider = SoundCloudProvider()

    def test_reconnait_soundcloud(self):
        self.assertTrue(self.provider.matches("https://soundcloud.com/artist/track-name"))

    def test_reconnait_lien_court(self):
        self.assertTrue(self.provider.matches("https://snd.sc/abc123"))

    def test_rejette_youtube(self):
        self.assertFalse(self.provider.matches("https://youtube.com/watch?v=abc"))


class SpotifyMatchTests(unittest.TestCase):
    def setUp(self):
        self.provider = SpotifyProvider()

    def test_reconnait_track(self):
        self.assertTrue(self.provider.matches("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC"))

    def test_reconnait_album(self):
        self.assertTrue(self.provider.matches("https://open.spotify.com/album/abc123"))

    def test_reconnait_playlist(self):
        self.assertTrue(self.provider.matches("https://open.spotify.com/playlist/abc123"))

    def test_reconnait_uri_spotify(self):
        self.assertTrue(self.provider.matches("spotify:track:4uLU6hMCjMI75M1A2tKUQC"))

    def test_reconnait_lien_intl(self):
        self.assertTrue(self.provider.matches("https://open.spotify.com/intl-fr/track/4uLU6hMCjMI75M1A2tKUQC"))

    def test_rejette_deezer(self):
        self.assertFalse(self.provider.matches("https://www.deezer.com/track/123"))


class DeezerMatchTests(unittest.TestCase):
    def setUp(self):
        self.provider = DeezerProvider()

    def test_reconnait_track(self):
        self.assertTrue(self.provider.matches("https://www.deezer.com/fr/track/123456"))

    def test_reconnait_sans_locale(self):
        self.assertTrue(self.provider.matches("https://www.deezer.com/track/123456"))

    def test_reconnait_lien_court(self):
        self.assertTrue(self.provider.matches("https://link.deezer.com/s/abc123"))

    def test_rejette_spotify(self):
        self.assertFalse(self.provider.matches("https://open.spotify.com/track/abc"))


class DirectAudioMatchTests(unittest.TestCase):
    def setUp(self):
        self.provider = DirectAudioProvider()

    def test_reconnait_mp3(self):
        self.assertTrue(self.provider.matches("https://example.com/song.mp3"))

    def test_reconnait_avec_query_string(self):
        self.assertTrue(self.provider.matches("https://cdn.example.com/audio/track.ogg?token=abc"))

    def test_rejette_une_page_web_normale(self):
        self.assertFalse(self.provider.matches("https://example.com/page.html"))

    def test_rejette_youtube(self):
        self.assertFalse(self.provider.matches("https://youtube.com/watch?v=abc"))


if __name__ == "__main__":
    unittest.main()
