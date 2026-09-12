"""Milestone 1 (SentriX Core Reliability), priorité P0 #2 : tests pour
tools/deployment_status.py — distinguer CODE CORRIGÉ / DÉPLOYÉ / BOOT OK sans
jamais supposer qu'un commit poussé sur GitHub est réellement en production.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import deployment_status as ds  # noqa: E402


def test_health_url_normalizes_base_url_from_argv():
    assert ds._health_url(["https://example.com"]) == "https://example.com/health"
    assert ds._health_url(["https://example.com/health"]) == "https://example.com/health"
    assert ds._health_url(["https://example.com/"]) == "https://example.com/health"


def test_health_url_falls_back_to_env_var(monkeypatch):
    monkeypatch.setenv("SENTRIX_HEALTH_URL", "https://staging.example.com")
    assert ds._health_url([]) == "https://staging.example.com/health"


def test_health_url_returns_none_without_any_source(monkeypatch):
    monkeypatch.delenv("SENTRIX_HEALTH_URL", raising=False)
    assert ds._health_url([]) is None


def test_main_reports_match_when_deployed_equals_local_head(monkeypatch):
    monkeypatch.setattr(ds, "_local_head", lambda: "abc123def456789")
    monkeypatch.setattr(
        ds, "_fetch_health", lambda url: {"release": "abc123def456", "status": "ok"}
    )
    with patch.object(sys, "argv", ["deployment_status.py", "https://example.com"]):
        exit_code = ds.main()
    assert exit_code == 0


def test_main_reports_mismatch_when_deployed_differs_from_local_head(monkeypatch, capsys):
    monkeypatch.setattr(ds, "_local_head", lambda: "aaaaaaaaaaaa000000")
    monkeypatch.setattr(
        ds, "_fetch_health", lambda url: {"release": "bbbbbbbbbbbb", "status": "ok"}
    )
    with patch.object(sys, "argv", ["deployment_status.py", "https://example.com"]):
        exit_code = ds.main()
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "NON" in out
    assert "ATTENTION" in out


def test_main_fails_closed_when_health_endpoint_unreachable(monkeypatch):
    monkeypatch.setattr(ds, "_local_head", lambda: "abc123def456")
    monkeypatch.setattr(ds, "_fetch_health", lambda url: None)
    with patch.object(sys, "argv", ["deployment_status.py", "https://example.com"]):
        exit_code = ds.main()
    assert exit_code == 1


def test_main_fails_closed_when_release_not_exposed(monkeypatch):
    monkeypatch.setattr(ds, "_local_head", lambda: "abc123def456")
    monkeypatch.setattr(ds, "_fetch_health", lambda url: {"status": "ok"})
    with patch.object(sys, "argv", ["deployment_status.py", "https://example.com"]):
        exit_code = ds.main()
    assert exit_code == 1


def test_main_requires_a_url(monkeypatch):
    monkeypatch.delenv("SENTRIX_HEALTH_URL", raising=False)
    with patch.object(sys, "argv", ["deployment_status.py"]):
        exit_code = ds.main()
    assert exit_code == 1
