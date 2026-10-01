import asyncio

import pytest
from discord.ext import tasks

from core.module_kernel import ModuleKernel
from core.module_supervisor import ModuleSupervisor


class FakeBot:
    def __init__(self, status="failed"):
        self.module_kernel = ModuleKernel(["cogs.music"])
        if status == "failed":
            self.module_kernel.begin("cogs.music")
            self.module_kernel.failed("cogs.music", RuntimeError("boom"))
        else:
            self.module_kernel.begin("cogs.music")
            self.module_kernel.loaded("cogs.music")
        self.calls = 0
        self.closed = False

    def is_closed(self):
        return self.closed

    async def reload_runtime_module(self, name):
        self.calls += 1
        self.module_kernel.begin(name, operation="reload")
        self.module_kernel.loaded(name)


@pytest.mark.asyncio
async def test_supervisor_recovers_failed_optional_module():
    bot = FakeBot()
    supervisor = ModuleSupervisor(["cogs.music"], retry_delays=(1,), scan_interval=5)
    await supervisor._retry_one(bot, "cogs.music")

    assert bot.calls == 1
    assert bot.module_kernel.snapshot()["modules"]["cogs.music"]["status"] == "loaded"
    assert supervisor.snapshot()["recovered"] == 1


@pytest.mark.asyncio
async def test_supervisor_does_not_retry_unloaded_module():
    bot = FakeBot(status="loaded")
    bot.module_kernel.unloaded("cogs.music")
    supervisor = ModuleSupervisor(["cogs.music"], retry_delays=(1,), scan_interval=5)

    snapshot = bot.module_kernel.snapshot()
    assert snapshot["modules"]["cogs.music"]["status"] == "unloaded"
    assert supervisor.snapshot()["pending"] == {}


def test_supervisor_retry_budget_is_bounded():
    supervisor = ModuleSupervisor(["cogs.music"], retry_delays=(1, 2, 3))
    supervisor._schedule_failure("cogs.music")
    supervisor._schedule_failure("cogs.music")
    supervisor._schedule_failure("cogs.music")
    supervisor._schedule_failure("cogs.music")

    assert supervisor.snapshot()["pending"]["cogs.music"]["failures"] == 4
    assert len(supervisor.retry_delays) == 3


@pytest.mark.asyncio
async def test_supervisor_can_restart_module_once_dependency_is_back():
    bot = FakeBot(status="loaded")
    bot.module_kernel = ModuleKernel(
        ["cogs.events", "cogs.giveaway_center"],
        dependencies={"cogs.giveaway_center": ("cogs.events",)},
    )
    bot.module_kernel.begin("cogs.events")
    bot.module_kernel.loaded("cogs.events")
    bot.module_kernel.blocked("cogs.giveaway_center", ())
    supervisor = ModuleSupervisor(["cogs.giveaway_center"], retry_delays=(1,), scan_interval=5)

    await supervisor._retry_one(bot, "cogs.giveaway_center")
    assert bot.module_kernel.snapshot()["modules"]["cogs.giveaway_center"]["status"] == "loaded"


def test_failed_background_loop_degrades_owning_module(monkeypatch):
    class DummyCog:
        __module__ = "cogs.music"

        @tasks.loop(seconds=60)
        async def worker(self):
            pass

    bot = type("Bot", (), {})()
    bot.cogs = {"DummyCog": DummyCog()}
    bot.module_kernel = ModuleKernel(["cogs.music"])
    bot.module_kernel.begin("cogs.music")
    bot.module_kernel.loaded("cogs.music")

    monkeypatch.setattr(tasks.Loop, "failed", lambda self: True)
    supervisor = ModuleSupervisor(["cogs.music"])
    supervisor._scan_failed_loops(bot, bot.module_kernel)

    snapshot = bot.module_kernel.snapshot()
    assert snapshot["runtime_degraded"] == ["cogs.music"]
    assert supervisor.snapshot()["failed_background_loops"]


def test_supervisor_snapshot_exposes_internal_health():
    supervisor = ModuleSupervisor(["cogs.music"])
    snapshot = supervisor.snapshot()
    assert snapshot["internal_errors"] == 0
    assert snapshot["last_internal_error"] is None
    assert snapshot["running"] is False
