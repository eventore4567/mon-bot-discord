"""ProviderManager (utils/music/manager.py) : le pipeline complet requête ->
détection -> métadonnées -> recherche de lecture -> repli automatique, SANS aucun
appel réseau réel (providers factices injectés). Couvre les scénarios demandés
explicitement : titre seul, URL YouTube/YouTube Music, URL Spotify, URL Deezer, URL
SoundCloud, URL invalide, morceau supprimé, provider bloqué, premier provider KO
mais second OK, playlist."""
from __future__ import annotations

import os
import re
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.music.errors import NoPlayableSource, ProviderUnavailable, TrackNotFound
from utils.music.manager import ProviderManager
from utils.music.models import Track
from utils.music.providers.base import MusicProvider


class _FakeProvider(MusicProvider):
    """Provider factice : matches() par regex, résultats/erreurs programmés à
    l'avance — aucun réseau, aucune dépendance à yt-dlp."""

    def __init__(self, name: str, *, url_pattern: str | None = None,
                 can_provide_playback: bool = False, can_search_by_text: bool = False):
        super().__init__()
        self.name = name
        self.can_provide_playback = can_provide_playback
        self.can_search_by_text = can_search_by_text
        self._url_re = re.compile(url_pattern, re.IGNORECASE) if url_pattern else None
        self.metadata_result: list[Track] | Exception | None = None
        self.search_result: list[Track] | Exception | None = None
        self.metadata_calls = 0
        self.search_calls = 0

    def matches(self, query: str) -> bool:
        if self._url_re is None:
            return False
        return bool(self._url_re.match(query.strip()))

    async def resolve_metadata(self, query, *, requested_by=None):
        self.metadata_calls += 1
        if isinstance(self.metadata_result, Exception):
            raise self.metadata_result
        return self.metadata_result or []

    async def search_playable(self, *, title, artist, duration, limit=5):
        self.search_calls += 1
        if isinstance(self.search_result, Exception):
            raise self.search_result
        return self.search_result or []


def _manager_with(*, direct=None, spotify=None, deezer=None, soundcloud=None, youtube=None) -> ProviderManager:
    direct = direct or _FakeProvider("direct", url_pattern=r"^https?://.*\.mp3$")
    spotify = spotify or _FakeProvider("spotify", url_pattern=r"^https?://open\.spotify\.com/")
    deezer = deezer or _FakeProvider("deezer", url_pattern=r"^https?://.*deezer\.com/")
    soundcloud = soundcloud or _FakeProvider(
        "soundcloud", url_pattern=r"^https?://.*soundcloud\.com/", can_provide_playback=True, can_search_by_text=True
    )
    youtube = youtube or _FakeProvider(
        "youtube", url_pattern=r"^https?://.*(youtube\.com|youtu\.be|music\.youtube\.com)/",
        can_provide_playback=True, can_search_by_text=True,
    )
    return ProviderManager(providers=[direct, spotify, deezer, soundcloud, youtube])


def _playable(title="Africa", artist="Toto", duration=295, provider="youtube") -> Track:
    return Track(
        title=f"{artist} - {title} (Official Video)", artist=artist, duration=duration,
        playable_url=f"https://stream.example/{provider}/1", playback_provider=provider, provider=provider,
    )


class ResolveByUrlTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_youtube_est_detectee_et_resolue_directement(self):
        youtube = _FakeProvider("youtube", url_pattern=r"^https?://.*youtube\.com/", can_provide_playback=True)
        youtube.metadata_result = [_playable(provider="youtube")]
        mgr = _manager_with(youtube=youtube)

        result = await mgr.resolve("https://youtube.com/watch?v=abc123", requested_by=1)

        self.assertEqual(youtube.metadata_calls, 1)
        self.assertEqual(len(result.tracks), 1)
        self.assertTrue(result.tracks[0].is_playable)

    async def test_url_youtube_music_est_reconnue_par_le_meme_provider(self):
        youtube = _FakeProvider("youtube", url_pattern=r"^https?://.*(youtube\.com|music\.youtube\.com)/", can_provide_playback=True)
        youtube.metadata_result = [_playable(provider="youtube")]
        mgr = _manager_with(youtube=youtube)

        result = await mgr.resolve("https://music.youtube.com/watch?v=abc123", requested_by=1)

        self.assertEqual(youtube.metadata_calls, 1)
        self.assertEqual(len(result.tracks), 1)

    async def test_url_soundcloud_est_detectee_et_resolue_directement(self):
        soundcloud = _FakeProvider("soundcloud", url_pattern=r"^https?://.*soundcloud\.com/", can_provide_playback=True)
        soundcloud.metadata_result = [_playable(provider="soundcloud")]
        mgr = _manager_with(soundcloud=soundcloud)

        result = await mgr.resolve("https://soundcloud.com/artist/track", requested_by=1)

        self.assertEqual(soundcloud.metadata_calls, 1)
        self.assertEqual(result.tracks[0].playback_provider, "soundcloud")

    async def test_url_spotify_resout_les_metadonnees_puis_cherche_une_lecture(self):
        """C'est exactement le comportement demandé : Spotify donne le titre/
        artiste/durée, PAS un flux — le manager doit chercher ailleurs."""
        spotify = _FakeProvider("spotify", url_pattern=r"^https?://open\.spotify\.com/")
        spotify.metadata_result = [Track(title="Africa", artist="Toto", duration=295, provider="spotify")]
        youtube = _FakeProvider("youtube", can_provide_playback=True, can_search_by_text=True)
        youtube.search_result = [_playable(provider="youtube")]
        mgr = _manager_with(spotify=spotify, youtube=youtube)

        result = await mgr.resolve("https://open.spotify.com/track/xyz", requested_by=1)

        self.assertEqual(spotify.metadata_calls, 1)
        self.assertEqual(youtube.search_calls, 1)
        self.assertEqual(result.tracks[0].provider, "spotify")  # métadonnées d'origine
        self.assertEqual(result.tracks[0].playback_provider, "youtube")  # lecture réelle
        self.assertTrue(result.tracks[0].is_playable)

    async def test_url_deezer_resout_les_metadonnees_puis_cherche_une_lecture(self):
        deezer = _FakeProvider("deezer", url_pattern=r"^https?://.*deezer\.com/")
        deezer.metadata_result = [Track(title="Africa", artist="Toto", duration=295, provider="deezer")]
        youtube = _FakeProvider("youtube", can_provide_playback=True, can_search_by_text=True)
        youtube.search_result = [_playable(provider="youtube")]
        mgr = _manager_with(deezer=deezer, youtube=youtube)

        result = await mgr.resolve("https://www.deezer.com/track/123", requested_by=1)

        self.assertEqual(deezer.metadata_calls, 1)
        self.assertEqual(result.tracks[0].provider, "deezer")
        self.assertEqual(result.tracks[0].playback_provider, "youtube")

    async def test_titre_seul_sans_url_passe_par_la_recherche(self):
        youtube = _FakeProvider("youtube", can_provide_playback=True, can_search_by_text=True)
        youtube.search_result = [_playable(title="Africa", artist="Toto", provider="youtube")]
        mgr = _manager_with(youtube=youtube)

        result = await mgr.resolve("Toto Africa", requested_by=1)

        self.assertEqual(youtube.search_calls, 1)
        self.assertTrue(result.tracks[0].is_playable)

    async def test_url_invalide_ne_plante_pas_et_est_traitee_comme_texte(self):
        """Une URL mal formée ne correspond à aucun provider à URL explicite :
        elle tombe sur SearchProvider (catch-all), pas un crash."""
        youtube = _FakeProvider("youtube", can_provide_playback=True, can_search_by_text=True)
        youtube.search_result = []  # rien ne correspond, c'est un lien cassé
        mgr = _manager_with(youtube=youtube)

        with self.assertRaises(NoPlayableSource):
            await mgr.resolve("https://not-a-real-music-site.example/abc", requested_by=1)


class DeletedTrackTests(unittest.IsolatedAsyncioTestCase):
    async def test_morceau_supprime_leve_track_not_found(self):
        youtube = _FakeProvider("youtube", url_pattern=r"^https?://.*youtube\.com/", can_provide_playback=True)
        youtube.metadata_result = TrackNotFound("youtube", "https://youtube.com/watch?v=deleted")
        mgr = _manager_with(youtube=youtube)

        with self.assertRaises(TrackNotFound):
            await mgr.resolve("https://youtube.com/watch?v=deleted", requested_by=1)


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_bloque_est_marque_indisponible_sans_planter_la_requete(self):
        spotify = _FakeProvider("spotify", url_pattern=r"^https?://open\.spotify\.com/")
        spotify.metadata_result = [Track(title="Africa", artist="Toto", duration=295, provider="spotify")]
        youtube = _FakeProvider("youtube", can_provide_playback=True, can_search_by_text=True)
        youtube.search_result = ProviderUnavailable("youtube", "challenge anti-bot")
        soundcloud = _FakeProvider("soundcloud", can_provide_playback=True, can_search_by_text=True)
        soundcloud.search_result = [_playable(provider="soundcloud")]
        mgr = _manager_with(spotify=spotify, youtube=youtube, soundcloud=soundcloud)

        result = await mgr.resolve("https://open.spotify.com/track/xyz", requested_by=1)

        self.assertTrue(youtube.is_temporarily_unavailable)
        self.assertEqual(result.tracks[0].playback_provider, "soundcloud")

    async def test_premier_provider_ko_mais_second_ok(self):
        """C'est le cas demandé explicitement : YouTube indisponible (Railway
        bloqué), SoundCloud prend le relais automatiquement."""
        youtube = _FakeProvider("youtube", can_provide_playback=True, can_search_by_text=True)
        youtube.search_result = ProviderUnavailable("youtube", "429 too many requests")
        soundcloud = _FakeProvider("soundcloud", can_provide_playback=True, can_search_by_text=True)
        soundcloud.search_result = [_playable(title="Africa", artist="Toto", provider="soundcloud")]
        mgr = _manager_with(youtube=youtube, soundcloud=soundcloud)

        result = await mgr.resolve("Toto Africa", requested_by=1)

        self.assertEqual(result.tracks[0].playback_provider, "soundcloud")
        self.assertTrue(youtube.is_temporarily_unavailable)

    async def test_tous_les_providers_de_lecture_indisponibles_leve_no_playable_source(self):
        youtube = _FakeProvider("youtube", can_provide_playback=True, can_search_by_text=True)
        youtube.search_result = ProviderUnavailable("youtube", "bloqué")
        soundcloud = _FakeProvider("soundcloud", can_provide_playback=True, can_search_by_text=True)
        soundcloud.search_result = ProviderUnavailable("soundcloud", "bloqué")
        mgr = _manager_with(youtube=youtube, soundcloud=soundcloud)

        with self.assertRaises(NoPlayableSource):
            await mgr.resolve("Toto Africa", requested_by=1)


class PlaylistTests(unittest.IsolatedAsyncioTestCase):
    async def test_playlist_youtube_retourne_plusieurs_pistes(self):
        youtube = _FakeProvider("youtube", url_pattern=r"^https?://.*youtube\.com/", can_provide_playback=True)
        youtube.metadata_result = [
            _playable(title="Track 1", provider="youtube"),
            _playable(title="Track 2", provider="youtube"),
            _playable(title="Track 3", provider="youtube"),
        ]
        mgr = _manager_with(youtube=youtube)

        result = await mgr.resolve("https://youtube.com/playlist?list=abc", requested_by=1)

        self.assertTrue(result.is_playlist)
        self.assertEqual(len(result.tracks), 3)

    async def test_playlist_avec_une_piste_non_resolvable_continue_sans_planter(self):
        """Une piste de playlist qui ne trouve aucune lecture ne doit pas faire
        échouer TOUTE la playlist — juste être signalée comme non résolue."""
        spotify = _FakeProvider("spotify", url_pattern=r"^https?://open\.spotify\.com/")
        spotify.metadata_result = [
            Track(title="Findable Song", artist="Real Artist", duration=200, provider="spotify"),
            Track(title="Completely Obscure Unfindable Track", artist="Nobody", duration=200, provider="spotify"),
        ]
        youtube = _FakeProvider("youtube", can_provide_playback=True, can_search_by_text=True)

        async def fake_search(*, title, artist, duration, limit=5):
            if title == "Findable Song":
                return [_playable(title=title, artist=artist, duration=duration, provider="youtube")]
            return []  # rien ne correspond pour l'autre piste

        youtube.search_playable = fake_search
        mgr = _manager_with(spotify=spotify, youtube=youtube)

        result = await mgr.resolve("https://open.spotify.com/playlist/xyz", requested_by=1)

        self.assertEqual(len(result.tracks), 1)
        self.assertEqual(len(result.skipped), 1)


if __name__ == "__main__":
    unittest.main()
