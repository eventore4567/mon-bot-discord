"""Non-regression checks for the SentriX presentation and name-style payload."""
from __future__ import annotations

from types import SimpleNamespace

from cogs.presentation import _native_presentation, invite_url, presentation_panel
from cogs.sentrix_name_style import style_payload


def test_presentation_is_native_slash_with_channel_option():
    slash = _native_presentation(SimpleNamespace())
    assert slash.name == "presentation"
    assert {p.name for p in slash.parameters} == {"channel"}


def test_invite_uses_the_real_bot_id():
    bot = SimpleNamespace(application_id=123456789012345678, user=None)
    url = invite_url(bot)
    assert url is not None
    assert "client_id=123456789012345678" in url
    assert "applications.commands" in url
    assert "bot" in url


def test_presentation_has_a_button_not_raw_url():
    url = "https://discord.com/oauth2/authorize?client_id=123456789012345678"
    panel = presentation_panel(url, banner=False)
    assert len(panel.boutons_source) == 1
    assert panel.boutons_source[0].libelle == "Ajouter SentriX"
    assert panel.boutons_source[0].url == url
    assert all(url not in (section.texte or "") for section in panel.sections_source)


def test_sentrix_name_style_is_purple_blue_gradient():
    assert style_payload() == {
        "display_name_font_id": 11,
        "display_name_effect_id": 2,
        "display_name_colors": [0x7C3AED, 0x2563EB],
    }
