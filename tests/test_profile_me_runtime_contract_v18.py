from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_profile_uses_canonical_total_xp_key():
    profile = (ROOT / "cogs" / "profile_oxyde_runtime.py").read_text(encoding="utf-8")
    stats_service = (ROOT / "utils" / "stats_service.py").read_text(encoding="utf-8")
    assert '"total_xp": total_xp' in stats_service
    assert "stats.get('total_xp')" in profile
    assert "stats.get('xp')" not in profile
