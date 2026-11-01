"""Regression checks for sticky modes, private setup acknowledgement and UI banners."""
from cogs.sentrix_plus import SentriXPlus
from cogs.embed_builder import EmbedBuilderView, EmbedDraft
from cogs import setup_invitations
from cogs.role_mass_target import MassRoleView
import discord
import inspect


def test_sticky_modes_preserve_existing_messages():
    assert SentriXPlus._sticky_decode("hello") == ("text", "hello")
    for mode in ("text", "embed", "banner"):
        payload = SentriXPlus._sticky_encode("Bonjour !", mode)
        assert SentriXPlus._sticky_decode(payload) == (mode, "Bonjour !")


def test_sticky_supports_multiple_channels_and_revisions():
    from cogs.sticky_setup_ui import StickySetupView, StickyTextModal
    source = inspect.getsource(StickySetupView)
    assert "max_values=5" in source
    assert "_sticky_store" in source
    assert "send_modal(StickyTextModal(self))" in source
    assert hasattr(SentriXPlus, "sticky_edit")
    assert hasattr(SentriXPlus, "sticky_list")
    assert hasattr(SentriXPlus, "sticky_remove")


def test_slash_sticky_has_native_fields_and_prefix_opens_minisetup():
    from cogs.sticky_setup_ui import open_sticky_setup
    assert "open_sticky_setup(ctx, self)" in inspect.getsource(SentriXPlus.sticky.callback)
    params = inspect.signature(SentriXPlus.sticky_add.callback).parameters
    assert {"channel", "format", "message", "channel_2"} <= set(params)
    assert "Literal" in str(params["format"].annotation)
    assert "StickySetupView" in inspect.getsource(open_sticky_setup)


def test_embed_editor_banner_is_first_not_last():
    view = EmbedBuilderView(object(), EmbedDraft(), 1234)
    items = view.build_panel_embeds()
    assert len(items) >= 2
    assert items[0].image.url.startswith("attachment://")
    assert items[1].title == "Créateur d'embed SentriX"
    view.banner_enabled = False
    other = view.build_panel_embeds()
    assert other[0].title == "Créateur d'embed SentriX"


def test_setup_public_ack_is_deleted_after_defer():
    source = inspect.getsource(setup_invitations._prepare_private_setup_interaction)
    assert "delete_original_response()" in source
    assert source.index("edit_original_response") < source.index("delete_original_response()")


def test_mass_role_uses_thin_components_panel():
    source = inspect.getsource(MassRoleView)
    assert "_sentrix_panel_view" in source
    assert "interaction.followup.send" in source
