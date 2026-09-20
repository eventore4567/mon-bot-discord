"""cogs/command_health.py : alerte privée dès la première erreur technique d'une
commande, dédoublonnée, sans contenu de message ; compteur exposé pour /health."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest import mock

import pytest

from cogs import command_health
from core.errors import pipeline


@pytest.fixture(autouse=True)
def _reset():
    pipeline.reset_for_tests()
    yield
    pipeline.reset_for_tests()


class _Target:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text, **_kw):
        self.sent.append(text)


def _bot():
    return SimpleNamespace(_sentrix_observability_v26={"release": "abc1234"})


def test_pipeline_notifies_subscribers_and_survives_failures():
    seen = []
    pipeline.subscribe(seen.append)

    def boom(_entry):
        raise RuntimeError("abonné cassé")

    pipeline.subscribe(boom)
    entry = pipeline.report(ValueError("x"), command="clear", transport="prefix")
    assert seen == [entry]
    pipeline.unsubscribe(seen.append)
    pipeline.report(ValueError("y"), command="clear", transport="prefix")
    assert len(seen) == 1


def test_first_error_sends_one_private_alert_and_dedupes():
    bot = _bot()
    target = _Target()

    async def scenario():
        command_health.install(bot)
        with mock.patch("cogs.production_ops._resolve_alert_target", new=mock.AsyncMock(return_value=target)), \
             mock.patch.dict(os.environ, {"RAILWAY_SERVICE_NAME": ""}):
            pipeline.report(Exception("Can only bulk delete messages up to 100 messages"), command="clear", transport="prefix")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            pipeline.report(Exception("again"), command="clear", transport="prefix")
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    asyncio.run(scenario())
    assert len(target.sent) == 1
    text = target.sent[0]
    assert "`+clear`" in text and "SXR-CMD-0001" in text and "Exception" in text
    assert "bulk delete" not in text  # jamais le message d'exception brut
    snap = command_health.snapshot(bot)
    assert snap["total_errors"] == 2 and snap["broken_commands"] == 1
    assert snap["top"][0]["command"] == "clear" and snap["top"][0]["errors"] == 2
    assert snap["alerts_sent"] == 1


def test_user_errors_are_counted_but_never_alerted():
    bot = _bot()
    target = _Target()

    async def scenario():
        command_health.install(bot)
        with mock.patch("cogs.production_ops._resolve_alert_target", new=mock.AsyncMock(return_value=target)):
            from discord.ext import commands
            pipeline.report(commands.MissingRequiredArgument(SimpleNamespace(name="x", displayed_name="x")), command="ban", transport="prefix")
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    asyncio.run(scenario())
    assert target.sent == []
    assert command_health.snapshot(bot)["total_errors"] == 1


def test_secondary_service_stays_silent():
    bot = _bot()
    target = _Target()

    async def scenario():
        command_health.install(bot)
        with mock.patch("cogs.production_ops._resolve_alert_target", new=mock.AsyncMock(return_value=target)), \
             mock.patch.dict(os.environ, {"RAILWAY_SERVICE_NAME": "sentrix-standby"}):
            pipeline.report(RuntimeError("x"), command="kick", transport="slash")
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    asyncio.run(scenario())
    assert target.sent == []


def test_health_payload_exposes_command_health():
    from web import health_runtime_v45

    bot = _bot()
    bot._sentrix_command_health = {"commands": {"clear": {"errors": 3, "last_exc": "ClientException"},
                                                "ban": {"errors": 1, "last_exc": "TypeError"}}}
    payload = health_runtime_v45._command_health_state(bot)
    assert payload["broken_commands"] == 2 and payload["total_errors"] == 4
    assert payload["top"][0] == {"command": "clear", "errors": 3, "last_exc": "ClientException"}
