import unittest
from unittest.mock import AsyncMock

from utils.music.manager import ProviderManager
from utils.music.models import Track
from utils.music.providers.youtube import YouTubeProvider


class YouTubePlaylistRailwayFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_playlist_uses_flat_metadata_without_audio_extraction(self):
        provider = YouTubeProvider()
        seen = {}

        async def fake_extract(query, *, opts_override=None):
            seen["query"] = query
            seen["opts"] = dict(opts_override or {})
            return {
                "entries": [
                    {
                        "id": "abc123xyz00",
                        "title": "Faded",
                        "channel": "Alan Walker",
                        "url": "abc123xyz00",
                    },
                    {
                        "id": "def123xyz00",
                        "title": "Alone",
                        "channel": "Alan Walker",
                        "url": "def123xyz00",
                    },
                ]
            }

        provider._extract = fake_extract
        tracks = await provider.resolve_metadata(
            "https://music.youtube.com/playlist?list=PL_TEST",
            requested_by=42,
        )

        self.assertEqual(len(tracks), 2)
        self.assertEqual(seen["opts"]["extract_flat"], "in_playlist")
        self.assertFalse(seen["opts"]["noplaylist"])
        self.assertTrue(seen["opts"]["skip_download"])
        self.assertIsNone(tracks[0].playable_url)
        self.assertIsNone(tracks[0].playback_provider)
        self.assertEqual(
            tracks[0].original_url,
            "https://www.youtube.com/watch?v=abc123xyz00",
        )

    async def test_manager_does_not_resolve_every_playlist_audio_during_import(self):
        manager = ProviderManager()

        class FakePlaylistProvider:
            name = "youtube"
            can_provide_playback = True

            async def resolve_metadata(self, query, *, requested_by=None):
                return [
                    Track(title="One", artist="Artist", provider="youtube", requested_by=requested_by),
                    Track(title="Two", artist="Artist", provider="youtube", requested_by=requested_by),
                ]

            def mark_available(self):
                raise AssertionError("metadata-only playlist must not be marked as playable")

        fake = FakePlaylistProvider()
        manager._detect_provider = lambda query: fake

        result = await manager.resolve("https://youtube.com/playlist?list=x", requested_by=7)

        self.assertTrue(result.is_playlist)
        self.assertEqual([track.title for track in result.tracks], ["One", "Two"])
        self.assertTrue(all(not track.is_playable for track in result.tracks))

    async def test_refresh_lazily_resolves_metadata_only_playlist_track(self):
        manager = ProviderManager()
        track = Track(title="Faded", artist="Alan Walker", provider="youtube", requested_by=7)

        async def make_playable(current):
            current.playable_url = "https://cdn.example.test/audio"
            current.playback_provider = None
            return current

        manager.ensure_playable = AsyncMock(side_effect=make_playable)
        url = await manager.refresh_playable_url(track)

        manager.ensure_playable.assert_awaited_once_with(track)
        self.assertEqual(url, "https://cdn.example.test/audio")


if __name__ == "__main__":
    unittest.main()
