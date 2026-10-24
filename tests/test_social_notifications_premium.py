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
    # L'envoi vit dans _send_social_event, appelé par _check_subscription.
    assert "_send_social_event(" in inspect.getsource(notifications.Notifications._check_subscription)
    source = inspect.getsource(notifications.Notifications._send_social_event)
    assert "embed=notification" not in source
    assert "SocialNotificationPanel(" in source
    assert "delete_after=5" in source
    assert "await channel.send(view=notification)" in source
    # L'ordre compte : la carte d'abord. Si Discord la refuse, aucun ping
    # parasite n'est parti et le passage suivant retentera la publication.
    assert source.index("await channel.send(view=notification)") < source.index("delete_after=5")


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
    # L'enrichissement vit dans _item_event, appelé avant l'envoi.
    check = inspect.getsource(notifications.Notifications._check_subscription)
    assert check.index("_item_event(") < check.index("_send_social_event(")
    source = inspect.getsource(notifications.Notifications._item_event)
    assert "_extract_details(link)" in source
    assert "_best_thumbnail(" in source and 'row["image_url"]' in source
