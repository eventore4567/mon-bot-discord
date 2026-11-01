"""Regressions for active Setup V116 and visual/role workflows."""

import inspect

from cogs.import_data import ImportSetupView
from cogs.presentation import _publish
from sentrix_setup_v116 import MODULE_BY_KEY


def test_import_is_in_active_v116_levels_and_economy():
    for module in ("levels", "economy"):
        entries = MODULE_BY_KEY[module].sections
        assert any(section.key == "import" and section.action == "import-data"
                   for section in entries)


def test_import_minisetup_has_upload_and_example():
    view = ImportSetupView(object(), 123, 456)
    labels = {getattr(item, "label", "") for item in view.children}
    assert {"Choisir le fichier JSON", "Format du fichier", "Fermer"} <= labels
    assert view.guild_id == 123
    assert view.author_id == 456


def test_presentation_banner_default_can_be_disabled():
    assert inspect.signature(_publish).parameters["banniere"].default is True
    source = inspect.getsource(_publish)
    assert "banner=banniere" in source
    assert "attachments=panel.fichiers()" in source


def test_mass_role_exposes_target_and_acks_slash():
    from cogs.role_mass_target import MassRole
    source = inspect.getsource(MassRole.mass.callback)
    assert "cible: str" in source
    assert "ctx.defer(ephemeral=True)" in source
    assert "view.target = cible" in source


def test_embed_builder_has_thin_banner_toggle():
    from cogs.embed_builder import EmbedBuilderView
    source = inspect.getsource(EmbedBuilderView)
    assert "toggle_banner" in source
    assert "attachment://" in source
    assert "banner_enabled" in source
