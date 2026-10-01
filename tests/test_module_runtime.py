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


@pytest.mark.asyncio
async def test_parent_reload_also_reloads_loaded_dependents():
    bot = FakeBot()
    bot.extensions = {
        "cogs.ai": object(),
        "cogs.ai_disable_guard": object(),
    }
    kernel = ModuleKernel(
        ["cogs.ai", "cogs.ai_disable_guard"],
        dependencies={"cogs.ai_disable_guard": ("cogs.ai",)},
    )
    for name in ("cogs.ai", "cogs.ai_disable_guard"):
        kernel.begin(name)
        kernel.loaded(name)

    runtime = ModuleRuntimeController(bot, kernel)
    await runtime.reload("cogs.ai")

    assert bot.reload_calls == ["cogs.ai", "cogs.ai_disable_guard"]
    state = runtime.snapshot()["last_operation"]
    assert state["dependents"] == ["cogs.ai_disable_guard"]
    assert state["dependent_failures"] == []
    snapshot = kernel.snapshot()["modules"]
    assert snapshot["cogs.ai"]["circuit_open"] is False
    assert snapshot["cogs.ai_disable_guard"]["circuit_open"] is False


@pytest.mark.asyncio
async def test_dependent_reload_failure_is_isolated_without_reloading_parent_again():
    bot = FakeBot()
    bot.extensions = {
        "cogs.events": object(),
        "cogs.giveaway_center": object(),
    }
    kernel = ModuleKernel(
        ["cogs.events", "cogs.giveaway_center"],
        dependencies={"cogs.giveaway_center": ("cogs.events",)},
    )
    for name in ("cogs.events", "cogs.giveaway_center"):
        kernel.begin(name)
        kernel.loaded(name)

    async def reload_extension(name):
        bot.reload_calls.append(name)
        if name == "cogs.giveaway_center":
            raise RuntimeError("dependent broken")

    bot.reload_extension = reload_extension
    runtime = ModuleRuntimeController(bot, kernel)

    await runtime.reload("cogs.events")

    assert bot.reload_calls == ["cogs.events", "cogs.giveaway_center"]
    operation = runtime.snapshot()["last_operation"]
    assert operation["ok"] is True
    assert operation["dependent_failures"] == [
        {"module": "cogs.giveaway_center", "error": "RuntimeError"}
    ]

    snapshot = kernel.snapshot()["modules"]
    assert snapshot["cogs.events"]["status"] == "loaded"
    assert snapshot["cogs.events"]["circuit_open"] is False
    assert snapshot["cogs.giveaway_center"]["status"] == "loaded"
    assert snapshot["cogs.giveaway_center"]["runtime_degraded"] is True
    assert snapshot["cogs.giveaway_center"]["circuit_open"] is True
    assert snapshot["cogs.giveaway_center"]["circuit_reason"] == "dependency_reload_failed"


@pytest.mark.asyncio
async def test_stop_refuses_parent_with_active_dependents():
    bot = FakeBot()
    bot.extensions = {
        "cogs.events": object(),
        "cogs.giveaway_center": object(),
    }
    kernel = ModuleKernel(
        ["cogs.events", "cogs.giveaway_center"],
        dependencies={"cogs.giveaway_center": ("cogs.events",)},
    )
    for name in ("cogs.events", "cogs.giveaway_center"):
        kernel.begin(name)
        kernel.loaded(name)

    runtime = ModuleRuntimeController(bot, kernel)

    with pytest.raises(RuntimeError):
        await runtime.stop("cogs.events")

    assert bot.unload_calls == []
    operation = runtime.snapshot()["last_operation"]
    assert operation["error"] == "ActiveDependents"
    assert operation["dependents"] == ["cogs.giveaway_center"]


@pytest.mark.asyncio
async def test_runtime_reload_times_out_instead_of_hanging_forever():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")

    async def hanging_reload(name):
        await asyncio.sleep(1)

    bot.reload_extension = hanging_reload
    runtime = ModuleRuntimeController(
        bot,
        kernel,
        operation_timeout_seconds=0.01,
    )

    with pytest.raises(asyncio.TimeoutError):
        await runtime.reload("cogs.music")

    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["status"] == "loaded"
    assert state["last_error"] == "TimeoutError"


@pytest.mark.asyncio
async def test_runtime_unload_times_out_without_marking_module_unloaded():
    bot = FakeBot()
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")

    async def hanging_unload(name):
        await asyncio.sleep(1)

    bot.unload_extension = hanging_unload
    runtime = ModuleRuntimeController(
        bot,
        kernel,
        operation_timeout_seconds=0.01,
    )

    with pytest.raises(asyncio.TimeoutError):
        await runtime.stop("cogs.music")

    assert kernel.snapshot()["modules"]["cogs.music"]["status"] == "loaded"


@pytest.mark.asyncio
async def test_recover_missing_can_load_absent_critical_module_without_reload():
    bot = FakeBot()
    bot.extensions = {}
    kernel = ModuleKernel(["cogs.moderation"], critical={"cogs.moderation"})
    kernel.begin("cogs.moderation")
    kernel.failed("cogs.moderation", RuntimeError("boot failed"))

    runtime = ModuleRuntimeController(bot, kernel)
    await runtime.recover_missing("cogs.moderation")

    assert bot.load_calls == ["cogs.moderation"]
    assert bot.reload_calls == []
    assert kernel.snapshot()["modules"]["cogs.moderation"]["status"] == "loaded"


@pytest.mark.asyncio
async def test_recover_missing_never_reloads_already_active_critical_module():
    bot = FakeBot()
    bot.extensions = {"cogs.moderation": object()}
    kernel = ModuleKernel(["cogs.moderation"], critical={"cogs.moderation"})
    kernel.begin("cogs.moderation")
    kernel.loaded("cogs.moderation")

    runtime = ModuleRuntimeController(bot, kernel)
    await runtime.recover_missing("cogs.moderation")

    assert bot.load_calls == []
    assert bot.reload_calls == []
    assert kernel.snapshot()["modules"]["cogs.moderation"]["status"] == "loaded"
