"""Readiness ne doit pas ignorer un chargement de module partiellement raté."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from web import health_runtime_v45 as health


def fake_bot(*, actual=3, expected=3, ext_errors=None, v17=None):
    names = {str(i): object() for i in range(actual)}
    return SimpleNamespace(
        extensions=names,
        expected_extension_count=expected,
        _sentrix_extension_load_failures=ext_errors or {},
        _sentrix_v17_install_report=v17 or {},
        is_ready=lambda: True,
        latency=0.05,
        guilds=[],
        db=SimpleNamespace(fetchone=AsyncMock(return_value={"ok": 1})),
    )


def test_health_ne_deduit_pas_attendu_depuis_charge():
    bot = fake_bot(actual=2, expected=3)
    assert health._extension_state(bot) == (2, 3, False)


def test_health_detecte_extension_echouee_meme_si_compteur_egal():
    bot = fake_bot(ext_errors={"cogs.example": "ExtensionFailed"})
    assert health._extension_state(bot) == (3, 3, False)


def test_health_detecte_v17_partiellement_echoue():
    bot = fake_bot(v17={
        "tickets": {"status": "ok"},
        "sécurité": {"status": "failed", "error_type": "RuntimeError"},
    })
    assert health._extension_state(bot) == (3, 3, False)
    assert health._installer_failures(bot) == (0, 1)


def test_health_reste_vert_sans_echec_constate():
    bot = fake_bot(v17={"tickets": {"status": "ok"}})
    assert health._extension_state(bot) == (3, 3, True)


@pytest.mark.asyncio
async def test_readiness_signal_degradation_sans_reveler_les_exceptions():
    bot = fake_bot(ext_errors={"cogs.missing": "ValueError"}, v17={
        "modération": {"status": "failed", "error_type": "TypeError"},
    })
    snapshot = await health._snapshot(bot, SimpleNamespace(START_TIME=0))
    assert snapshot["ok"] is False
    assert snapshot["status"] == "extensions_degraded"
    assert snapshot["extensions_expected"] == 3
    assert snapshot["extension_load_failure_count"] == 1
    assert snapshot["v17_install_failure_count"] == 1
    assert "cogs.missing" not in str(snapshot)


@pytest.mark.asyncio
async def test_readiness_success_when_everything_is_ready():
    bot = fake_bot(v17={"modération": {"status": "ok"}})
    snapshot = await health._snapshot(bot, SimpleNamespace(START_TIME=0))
    assert snapshot["ok"] is True
    assert snapshot["status"] == "operational"
