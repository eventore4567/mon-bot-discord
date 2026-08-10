"""UUIDv7 : conformite RFC 9562."""

from __future__ import annotations

import time

import pytest

from libs.ids import uuid7, uuid7_at


def test_version_and_variant_bits() -> None:
    for _ in range(200):
        value = uuid7()
        assert value.version == 7
        # Variant RFC 4122 : les 2 bits hauts de l'octet 8 valent 0b10.
        assert (value.bytes[8] & 0xC0) == 0x80


def test_timestamp_is_encoded_in_first_48_bits() -> None:
    ts_ms = 1_700_000_000_123
    value = uuid7_at(ts_ms)
    assert int.from_bytes(value.bytes[0:6], "big") == ts_ms


def test_monotonic_ordering_across_milliseconds() -> None:
    earlier = uuid7_at(1_700_000_000_000)
    later = uuid7_at(1_700_000_001_000)
    assert str(earlier) < str(later)


def test_uniqueness() -> None:
    values = {uuid7() for _ in range(10_000)}
    assert len(values) == 10_000


def test_reflects_current_time() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000
    encoded = int.from_bytes(value.bytes[0:6], "big")
    assert before <= encoded <= after


def test_rejects_out_of_range_timestamp() -> None:
    with pytest.raises(ValueError):
        uuid7_at(-1)
    with pytest.raises(ValueError):
        uuid7_at(1 << 48)
