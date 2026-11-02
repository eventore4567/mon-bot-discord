"""UnbelievaBoat economic import: exact values and explicit overflow conversion."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import import_data


def export(rows):
    return json.dumps({"users": rows}).encode("utf-8")


def test_import_accepts_64_unbelievaboat_members_above_old_trillion_limit():
    users = [
        {"id": str(1524528157158539505 + i), "cash": 2_500_000_000_000 + i, "bank": i}
        for i in range(64)
    ]
    rows = import_data.parse_export(export(users))
    assert len(rows) == 64
    assert rows[0]["cash"] == 2_500_000_000_000
    assert rows[-1]["bank"] == 63


def test_import_keeps_full_signed_64_bit_economy_capacity_safe_for_sum():
    value = import_data.MAX_CURRENCY_VALUE
    rows = import_data.parse_export(
        export([{"id": "1524528157158539505", "cash": value, "bank": value}])
    )
    assert rows[0]["cash"] == value
    assert rows[0]["cash"] + rows[0]["bank"] < 2**63


def test_overflow_never_silently_clamps_or_changes_money():
    maximum = import_data.MAX_CURRENCY_VALUE + 12
    data = export([
        {"id": "1524528157158539505", "cash": maximum, "bank": 1000},
        {"id": "1524528157158539506", "cash": 300, "bank": 3000},
    ])
    with pytest.raises(import_data.BalanceOverflowError) as caught:
        import_data.parse_export(data)
    assert caught.value.maximum == maximum
    assert caught.value.divisor == 10
    adapted = import_data.parse_export(data, scale_currency=True)
    assert adapted[0]["cash"] == maximum // 10
    assert adapted[0]["bank"] == 100
    assert adapted[1]["cash"] == 30
    assert adapted[1]["bank"] == 300


def test_negative_unbelievaboat_debt_is_preserved():
    data = export([
        {"id": "1524528157158539505", "cash": -153_000_000_000, "bank": 500},
        {"id": "1524528157158539506", "cash": -1, "bank": -42},
    ])
    rows = import_data.parse_export(data)
    assert rows[0]["cash"] == -153_000_000_000
    assert rows[1]["cash"] == -1
    assert rows[1]["bank"] == -42


def test_negative_overflow_requires_opt_in_and_divides_toward_zero():
    big = -(import_data.MAX_CURRENCY_VALUE + 1)
    data = export([{"id": "1524528157158539505", "cash": big, "bank": -9}])
    with pytest.raises(import_data.BalanceOverflowError):
        import_data.parse_export(data)
    converted = import_data.parse_export(data, scale_currency=True)
    assert converted[0]["cash"] == -(abs(big) // 10)
    assert converted[0]["bank"] == 0


def test_import_accepts_more_than_previous_5000_member_limit():
    raw = export([
        {"id": str(1524528157158539505 + n), "cash": n}
        for n in range(5001)
    ])
    assert len(import_data.parse_export(raw)) == 5001


def test_import_rejects_invalid_numbers_before_writes():
    for bad in [True, "200"]:
        with pytest.raises(ValueError):
            import_data.parse_export(export([{"id": "1524528157158539505", "cash": bad}]))
    with pytest.raises(ValueError):
        import_data.parse_export(export([
            {"id": "1524528157158539505", "cash": 5},
            {"id": "1524528157158539505", "cash": 9},
        ]))


@pytest.mark.asyncio
async def test_oversized_balance_requires_extra_consent(monkeypatch):
    raw = export([
        {"id": "1524528157158539505", "cash": import_data.MAX_CURRENCY_VALUE + 1}
    ])
    attachment = SimpleNamespace(filename="sentrix_import.json", size=len(raw), read=AsyncMock(return_value=raw))
    monkeypatch.setattr(import_data.language_runtime, "get_language", AsyncMock(return_value="fr"))
    embed, view = await import_data.preview_attachment(object(), 123, 456, attachment)
    assert isinstance(view, import_data.BalanceScaleConsent)
    assert "Conversion facultative" in embed.title
    assert "tous" in embed.description.lower()
    assert "arrondi" in embed.description.lower()
    assert any(getattr(child, "label", "").startswith("Adapter") for child in view.children)
    assert all(not hasattr(child, "records") for child in view.children)
