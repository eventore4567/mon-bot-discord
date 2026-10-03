from __future__ import annotations

import hashlib
import hmac
import inspect
import json

from cogs import notifications
from services import social_providers


def test_youtube_channel_monitors_videos_shorts_and_streams_even_from_old_videos_url():
    surfaces = social_providers.source_surfaces(
        "https://www.youtube.com/@vortexV1/videos",
        "YouTube",
    )
    assert surfaces == [
        ("videos", "https://www.youtube.com/@vortexV1/videos", "video"),
        ("shorts", "https://www.youtube.com/@vortexV1/shorts", "short"),
        ("streams", "https://www.youtube.com/@vortexV1/streams", "live"),
    ]


def test_tiktok_and_twitch_keep_single_provider_surface():
    assert social_providers.source_surfaces(
        "https://www.tiktok.com/@creator", "TikTok"
    ) == [("default", "https://www.tiktok.com/@creator", "post")]
    assert social_providers.source_surfaces(
        "https://www.twitch.tv/creator", "Twitch"
    ) == [("default", "https://www.twitch.tv/creator", "live")]


def test_phyllo_signature_uses_hmac_sha256_raw_body():
    body = b'{"event":"CONTENTS.UPDATED"}'
    secret = "test-webhook-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert social_providers.verify_phyllo_signature(body, signature, secret)
    assert social_providers.verify_phyllo_signature(
        body, f"sha256={signature}", secret
    )
    assert not social_providers.verify_phyllo_signature(
        body, "deadbeef", secret
    )


def test_phyllo_content_payload_is_normalized_without_platform_specific_code():
    payload = {
        "event": "CONTENTS.ADDED",
        "data": {
            "content": {
                "id": "short-123",
                "platform": "youtube",
                "url": "https://www.youtube.com/shorts/abc123",
                "title": "Nouveau short",
                "creator_name": "vortexV1",
                "profile_url": "https://www.youtube.com/@vortexV1",
                "thumbnail_url": "https://img.example/abc.jpg",
                "published_at": "2026-10-03T09:55:00Z",
                "content_type": "short",
            }
        },
    }
    events = social_providers.parse_phyllo_webhook(payload)

    assert len(events) == 1
    event = events[0]
    assert event.provider == "phyllo"
    assert event.platform == "YouTube"
    assert event.kind == "short"
    assert event.item_id == "short-123"
    assert event.creator == "vortexV1"
    assert event.creator_url == "https://www.youtube.com/@vortexV1"


def test_notification_panel_uses_common_premium_copy_for_every_provider():
    source = inspect.getsource(notifications.SocialNotificationPanel)
    assert "nouveau Short" in source
    assert "est en LIVE" in source
    assert "nouveau TikTok" in source
    assert "nouvelle vidéo" in source
    assert 'label=f"Voir sur {platform}"' in source
    assert "MediaGallery" in source
    assert "discord.Embed" not in source


def test_monitor_no_longer_swallows_gather_exceptions():
    source = inspect.getsource(notifications.Notifications.social_monitor.coro)
    assert "return_exceptions=True" in source
    assert "isinstance(result, BaseException)" in source
    assert "Échec non géré du moniteur social" in source


def test_webhook_event_key_is_deterministic_without_explicit_id():
    payload = {"event": "CONTENTS.ADDED", "data": {"x": 1}}
    body = json.dumps(payload, separators=(",", ":")).encode()
    first = social_providers.webhook_event_key(payload, body)
    second = social_providers.webhook_event_key(payload, body)
    assert first == second
    assert first.startswith("phyllo:")
