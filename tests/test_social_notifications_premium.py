from __future__ import annotations

import inspect

from cogs import notifications


def test_social_notification_uses_components_v2_without_embed_or_accent_bar():
    source = inspect.getsource(notifications.SocialNotificationPanel)
    assert "discord.ui.Container()" in source
    assert "accent_color" not in source
    assert "accent_colour" not in source
    assert "discord.Embed" not in source
    assert "MediaGallery" in source
    assert "Voir sur {platform}" in source


def test_social_monitor_does_not_send_the_old_embed_card():
    source = inspect.getsource(notifications.Notifications._check_subscription)
    assert "embed=notification" not in source
    assert "SocialNotificationPanel(" in source
    assert "delete_after=3" in source
    assert "await channel.send(view=notification)" in source


def test_thumbnail_prefers_configured_media_but_falls_back_to_real_item_thumbnail():
    item = {
        "thumbnail": "https://cdn.example.test/fresh.webp",
        "thumbnails": [{"url": "https://cdn.example.test/fallback.webp"}],
    }
    assert notifications._best_thumbnail(
        item, "https://cdn.example.test/custom.gif"
    ) == "https://cdn.example.test/custom.gif"
    assert notifications._best_thumbnail(item, None) == "https://cdn.example.test/fresh.webp"


def test_new_social_item_is_enriched_before_rendering():
    source = inspect.getsource(notifications.Notifications._check_subscription)
    assert "_extract_details(link)" in source
    assert "_best_thumbnail(item, row[\"image_url\"])" in source
