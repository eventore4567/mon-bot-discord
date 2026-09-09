"""Régressions production du 2026-09-09 :

- YouTube peut bloquer les IP Railway avec un challenge anti-bot. On doit alors
  conserver les métadonnées publiques sans contourner le challenge et chercher une
  autre source autorisée.
- Un seul résultat SoundCloud DRM ne doit pas tuer toute la recherche SoundCloud.
- Quand le playback bascule vers un autre provider, le refresh FFmpeg doit réutiliser
  l'URL de CE provider, pas l'URL de métadonnées d'origine.

Aucun test ici ne touche au réseau réel.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from utils.music.errors import ProviderUnavailable
from utils.music.manager import ProviderManager
from utils.music.models import Track
from utils.music.providers.base import MusicProvider
from utils.music.providers.soundcloud import SoundCloudProvider
from utils.music.providers.youtube import YouTubeProvider


class YouTubeMetadataFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_antibot_uses_metadata_only_and_marks_playback_unavailable(self):
        provider = YouTubeProvider()
        provider._extract = AsyncMock(
            side_effect=ProviderUnavailable("youtube", "Sign in to confirm you're not a bot")
        )
        provider._oembed_metadata = AsyncMock(
            return_value=Track(
                title="Faded",
                artist="Alan Walker",
                original_url="https://www.youtube.com/watch?v=pIWaVJPl0-c",
                provider="youtube",
            )
        )

        tracks = await provider.resolve_metadata(
            "https://www.youtube.com/watch?v=pIWaVJPl0-c", requested_by=42
        )

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Faded")
        self.assertFalse(tracks[0].is_playable)
        self.assertTrue(provider.is_temporarily_unavailable)
        provider._oembed_metadata.assert_awaited_once()


class _FakeProvider(MusicProvider):
    def __init__(
        self,
        name: str,
        *,
        matches_youtube: bool = False,
        can_play: bool = False,
        metadata: list[Track] | None = None,
        search: list[Track] | None = None,
        mark_blocked_on_metadata: bool = False,
    ):
        super().__init__()
        self.name = name
        self.can_provide_playback = can_play
        self.can_search_by_text = can_play
        self.matches_youtube = matches_youtube
        self.metadata = metadata or []
        self.search = search or []
        self.mark_blocked_on_metadata = mark_blocked_on_metadata
        self.search_calls = 0

    def matches(self, query: str) -> bool:
        return self.matches_youtube and "youtube.com/" in query

    async def resolve_metadata(self, query: str, *, requested_by: int | None = None) -> list[Track]:
        if self.mark_blocked_on_metadata:
            self.mark_unavailable("anti-bot")
        return self.metadata

    async def search_playable(self, *, title: str, artist: str | None, duration: int | None, limit: int = 5) -> list[Track]:
        self.search_calls += 1
        return self.search


class ManagerCooldownPreservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_fallback_does_not_immediately_retry_blocked_youtube(self):
        direct = _FakeProvider("direct")
        spotify = _FakeProvider("spotify")
        deezer = _FakeProvider("deezer")
        soundcloud = _FakeProvider(
            "soundcloud",
            can_play=True,
            search=[
                Track(
                    title="Alan Walker - Faded",
                    artist="Alan Walker",
                    original_url="https://soundcloud.com/example/faded",
                    provider="soundcloud",
                    playable_url="https://stream.example/faded",
                    playback_provider="soundcloud",
                )
            ],
        )
        youtube = _FakeProvider(
            "youtube",
            matches_youtube=True,
            can_play=True,
            metadata=[
                Track(
                    title="Faded",
                    artist="Alan Walker",
                    original_url="https://www.youtube.com/watch?v=pIWaVJPl0-c",
                    provider="youtube",
                )
            ],
            mark_blocked_on_metadata=True,
        )
        manager = ProviderManager(providers=[direct, spotify, deezer, soundcloud, youtube])

        result = await manager.resolve(
            "https://www.youtube.com/watch?v=pIWaVJPl0-c", requested_by=42
        )

        self.assertEqual(result.tracks[0].playback_provider, "soundcloud")
        self.assertEqual(
            result.tracks[0].original_url,
            "https://soundcloud.com/example/faded",
        )
        self.assertEqual(youtube.search_calls, 0)
        self.assertEqual(soundcloud.search_calls, 1)
        self.assertTrue(youtube.is_temporarily_unavailable)


class SoundCloudDrmFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_drm_candidate_is_skipped_and_next_candidate_is_used(self):
        provider = SoundCloudProvider()
        provider._extract = AsyncMock(
            side_effect=[
                {
                    "entries": [
                        {"webpage_url": "https://soundcloud.com/example/drm"},
                        {"webpage_url": "https://soundcloud.com/example/ok"},
                    ]
                },
                ProviderUnavailable("soundcloud", "This video is DRM protected"),
                {
                    "title": "Faded",
                    "uploader": "Alan Walker",
                    "duration": 212,
                    "webpage_url": "https://soundcloud.com/example/ok",
                    "url": "https://stream.example/soundcloud/faded",
                },
            ]
        )

        results = await provider.search_playable(
            title="Faded", artist="Alan Walker", duration=212, limit=5
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].playback_provider, "soundcloud")
        self.assertEqual(results[0].original_url, "https://soundcloud.com/example/ok")
        self.assertFalse(provider.is_temporarily_unavailable)

    async def test_all_drm_candidates_return_empty_without_provider_cooldown(self):
        provider = SoundCloudProvider()
        provider._extract = AsyncMock(
            side_effect=[
                {
                    "entries": [
                        {"webpage_url": "https://soundcloud.com/example/drm1"},
                        {"webpage_url": "https://soundcloud.com/example/drm2"},
                    ]
                },
                ProviderUnavailable("soundcloud", "This video is DRM protected"),
                ProviderUnavailable("soundcloud", "This video is DRM protected"),
            ]
        )

        results = await provider.search_playable(
            title="Faded", artist="Alan Walker", duration=212, limit=5
        )

        self.assertEqual(results, [])
        self.assertFalse(provider.is_temporarily_unavailable)


if __name__ == "__main__":
    unittest.main()
