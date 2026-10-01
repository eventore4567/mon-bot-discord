import asyncio

import pytest

from core.module_kernel import ModuleKernel
from core.module_runtime import ModuleRuntimeController


class FakeBot:
    def __init__(self):
        self.extensions = {"cogs.music": object()}
        self._sentrix_extension_health = None
        self.reload_calls = []
        self.load_calls = []
        self.unload_calls = []

    async def reload_extension(self, name):
        self.reload_calls.append(name)

    async def load_extension(self, name):
        self.load_calls.append(name)
        self.extensions[name] = object()

    async def unload_extension(self, name):
        self.unload_calls.append(name)
        self.extensions.pop(name, None)


@pytest.mark.asyncio
async def test_runtime_controller_reloads_optional_module():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    runtime = ModuleRuntimeController(bot, kernel)

    await runtime.reload("cogs.music")

    assert bot.reload_calls == ["cogs.music"]
    assert runtime.snapshot()["last_operation"]["ok"] is True
    assert kernel.snapshot()["modules"]["cogs.music"]["status"] == "loaded"


@pytest.mark.asyncio
async def test_runtime_controller_refuses_locked_module():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    runtime = ModuleRuntimeController(bot, kernel, locked={"cogs.music"})

    with pytest.raises(RuntimeError):
        await runtime.reload("cogs.music")


@pytest.mark.asyncio
async def test_runtime_controller_stop_marks_unloaded():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    runtime = ModuleRuntimeController(bot, kernel)

    await runtime.stop("cogs.music")

    assert bot.unload_calls == ["cogs.music"]
    assert kernel.snapshot()["modules"]["cogs.music"]["status"] == "unloaded"


@pytest.mark.asyncio
async def test_runtime_controller_opens_maintenance_circuit_during_reload():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    observed = {"open": False}

    async def reload_extension(name):
        observed["open"] = kernel.snapshot()["modules"][name]["circuit_open"]

    bot.reload_extension = reload_extension
    runtime = ModuleRuntimeController(bot, kernel)

    await runtime.reload("cogs.music")

    assert observed["open"] is True
    assert kernel.snapshot()["modules"]["cogs.music"]["circuit_open"] is False


@pytest.mark.asyncio
async def test_failed_reload_with_runtime_rollback_reopens_module():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")

    async def failing_reload(name):
        raise RuntimeError("new version broken")

    bot.reload_extension = failing_reload
    runtime = ModuleRuntimeController(bot, kernel)

    with pytest.raises(RuntimeError):
        await runtime.reload("cogs.music")

    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["status"] == "loaded"
    assert state["circuit_open"] is False
    assert state["last_error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_runtime_controller_waits_for_active_calls_before_reload():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    kernel.enter_runtime("cogs.music")
    observed = {"in_flight_at_reload": None}

    async def reload_extension(name):
        observed["in_flight_at_reload"] = kernel.in_flight(name)

    async def finish_call():
        await asyncio.sleep(0.02)
        kernel.exit_runtime("cogs.music")

    bot.reload_extension = reload_extension
    runtime = ModuleRuntimeController(bot, kernel)
    finisher = asyncio.create_task(finish_call())
    await runtime.reload("cogs.music")
    await finisher

    assert observed["in_flight_at_reload"] == 0


@pytest.mark.asyncio
async def test_failed_recovery_reload_keeps_preexisting_circuit_open():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    kernel.open_circuit("cogs.music", reason="runtime_failure")

    async def failing_reload(name):
        raise RuntimeError("still broken")

    bot.reload_extension = failing_reload
    runtime = ModuleRuntimeController(bot, kernel)

    with pytest.raises(RuntimeError):
        await runtime.reload("cogs.music")

    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["status"] == "loaded"
    assert state["circuit_open"] is True


@pytest.mark.asyncio
async def test_reload_refuses_to_replace_module_when_drain_times_out():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    runtime = ModuleRuntimeController(bot, kernel)

    async def fake_drain(name, timeout=5.0):
        return 1

    runtime._wait_for_drain = fake_drain

    with pytest.raises(RuntimeError):
        await runtime.reload("cogs.music")

    assert bot.reload_calls == []
    assert kernel.snapshot()["modules"]["cogs.music"]["circuit_open"] is False
    assert runtime.snapshot()["last_operation"]["error"] == "ModuleBusy"
