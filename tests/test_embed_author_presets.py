"""Éditeur d'embed : nom et avatar configurables sans simuler un badge APP."""
from types import SimpleNamespace

from cogs.embed_builder import EmbedDraft, EmbedAppearanceView, apply_author_preset


def _asset(url):
    return SimpleNamespace(url=url)


def test_server_author_uses_current_guild_name_and_icon():
    draft = EmbedDraft()
    guild = SimpleNamespace(name="Selimor x Tomioka", icon=_asset("https://cdn.discordapp.com/icons/1/icon.png"))
    assert apply_author_preset(draft, "guild", guild=guild)
    assert draft.author_name == "Selimor x Tomioka"
    assert draft.author_icon_url.endswith("icon.png")
    assert draft.dirty


def test_bot_author_uses_real_application_profile():
    draft = EmbedDraft()
    bot = SimpleNamespace(name="SentriX", display_name="SentriX", display_avatar=_asset("https://cdn.discordapp.com/avatars/1/s.png"))
    assert apply_author_preset(draft, "bot", bot_user=bot)
    assert draft.author_name == "SentriX"
    assert draft.author_icon_url.endswith("s.png")


def test_absent_icon_and_clear_presets():
    draft = EmbedDraft()
    assert apply_author_preset(draft, "guild", guild=SimpleNamespace(name="Test", icon=None))
    assert draft.author_icon_url is None
    assert apply_author_preset(draft, "none")
    assert draft.author_name is None
    assert draft.author_icon_url is None


def test_unknown_presets_fail_without_mutating_existing_author():
    draft = EmbedDraft()
    draft.author_name = "Preserve"
    assert not apply_author_preset(draft, "unknown")
    assert draft.author_name == "Preserve"


def test_embed_author_is_in_payload_and_can_be_saved():
    draft = EmbedDraft()
    assert apply_author_preset(draft, "guild", guild=SimpleNamespace(name="Selimor x Tomioka", icon=None))
    draft.description = "Le règlement du serveur"
    embed = draft.to_embed()
    assert embed.author.name == "Selimor x Tomioka"
    assert draft.to_dict()["author_name"] == "Selimor x Tomioka"


def test_appearance_contains_identity_choices():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "cogs/embed_builder.py").read_text()
    for option in ("bot", "guild", "custom", "none"):
        assert f'value="{option}"' in source
    assert "EmbedIdentityModal(self)" in source
