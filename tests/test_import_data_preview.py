"""Import format guards for user-supplied bot exports."""
from __future__ import annotations

import json

import pytest

from cogs.import_data import MAX_UPLOAD_SIZE, parse_export


def test_import_accepts_supported_fields_without_implicit_changes():
    data = {"users": [{"id": "123456789012345678", "xp": 123, "level": 4,
                       "cash": 60, "bank": 30}, {"user_id": 234567890123456789, "xp": 0}]}
    records = parse_export(json.dumps(data).encode())
    assert records == [
        {"id": 123456789012345678, "xp": 123, "level": 4, "cash": 60, "bank": 30},
        {"id": 234567890123456789, "xp": 0},
    ]


@pytest.mark.parametrize("value", [
    {"users": [{"id": "123", "cash": -4}]},
    {"users": [{"id": "123", "xp": 1.5}]},
    {"users": [{"id": "123", "xp": 2}, {"id": "123", "xp": 3}]},
    {"users": [{"id": "123"}]},
    {"users": [{"id": 0, "xp": 2}]},
    {"users": "not a list"},
    {"members": []},
])
def test_import_rejects_invalid_exports(value):
    with pytest.raises(ValueError):
        parse_export(json.dumps(value).encode())


def test_import_rejects_oversized_payload():
    with pytest.raises(ValueError):
        parse_export(b"x" * (MAX_UPLOAD_SIZE + 1))


def test_import_rejects_invalid_encoding():
    with pytest.raises(ValueError):
        parse_export(bytes([0xff, 0xfe]))

def test_setup_import_uses_native_file_upload_modal():
    import discord
    from cogs.import_data import ImportFileModal

    modal = ImportFileModal(object(), 123, 456, english=False)
    assert isinstance(modal.upload, discord.ui.FileUpload)
    assert modal.upload.min_values == 1
    assert modal.upload.max_values == 1
    assert modal.guild_id == 123
    assert modal.author_id == 456


def test_setup_page_has_import_button():
    import inspect
    from cogs.setup_components_v73 import SentriXSetupV73

    code = inspect.getsource(SentriXSetupV73._build_page)
    assert 'if page == "levels":' in code
    assert "ImportFileModal(" in code
    assert "interaction.response.send_modal" in code

def test_import_confirmation_buttons_have_localized_labels():
    import discord
    from cogs.import_data import ImportConfirm

    view = ImportConfirm(object(), 123, 456, [{"id": 12, "xp": 1}], english=False)
    labels = [item.label for item in view.children if isinstance(item, discord.ui.Button)]
    assert labels == ["Ajouter les absents", "Remplacer les champs importés", "Annuler"]

    view_en = ImportConfirm(object(), 123, 456, [{"id": 12, "xp": 1}], english=True)
    labels_en = [item.label for item in view_en.children if isinstance(item, discord.ui.Button)]
    assert labels_en == ["Add missing", "Replace imported fields", "Cancel"]
