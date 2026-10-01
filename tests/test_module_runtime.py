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
