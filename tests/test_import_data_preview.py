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
