"""Le endpoint /health de production ne doit pas annoncer sain un boot incomplet."""
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from web import production_health as production


def make_bot(*, expected=3, loaded=3, failure=False):
    bot = SimpleNamespace(
        db=SimpleNamespace(_conn=object(), fetchone=AsyncMock(return_value={"ok": 1})),
        is_ready=lambda: True,
        extensions={str(i): object() for i in range(loaded)},
        expected_extension_count=expected,
        _sentrix_extension_load_failures={"cogs.bad": "RuntimeError"} if failure else {},
        _sentrix_v17_install_report={"modération": {"status": "ok"}},
        latency=0.03,
        shard_count=1,
    )
    return bot


@pytest.mark.asyncio
async def test_production_health_signale_module_echoue(monkeypatch):
    monkeypatch.setattr(production, "_INSTALLED", False)
    monkeypatch.setattr(production, "build_runtime_snapshot", AsyncMock(return_value={"available": False}))
    dashboard = SimpleNamespace(handle_health=None, START_TIME=time.time() - 120)
    production.install(dashboard)
    response = await dashboard.handle_health(SimpleNamespace(app={"bot": make_bot(failure=True)}))
    payload = json.loads(response.text)
    assert response.status == 503
    assert payload["ok"] is False
    assert payload["health_level"] == "degraded"
    assert payload["extensions_ok"] is False
    assert payload["extension_load_failure_count"] == 1
    assert "cogs.bad" not in response.text


@pytest.mark.asyncio
async def test_production_health_ok_when_all_extensions_loaded(monkeypatch):
    monkeypatch.setattr(production, "_INSTALLED", False)
    monkeypatch.setattr(production, "build_runtime_snapshot", AsyncMock(return_value={"available": False}))
    dashboard = SimpleNamespace(handle_health=None, START_TIME=time.time() - 120)
    production.install(dashboard)
    response = await dashboard.handle_health(SimpleNamespace(app={"bot": make_bot()}))
    payload = json.loads(response.text)
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["health_level"] == "healthy"
    assert payload["extensions_loaded"] == 3
    assert payload["extensions_expected"] == 3
