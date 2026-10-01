import pytest

from types import SimpleNamespace

import pytest
from discord import app_commands

from core.module_gate import (
    AppModuleTemporarilyUnavailable,
    ModuleTemporarilyUnavailable,
    circuit_open,
    install_app_gates,
    prefix_gate,
)
from core.module_kernel import ModuleKernel


class FakeKernel:
    def __init__(self, open_value):
        self.open_value = open_value

    def snapshot(self):
        return {
            "modules": {
                "cogs.music": {
                    "circuit_open": self.open_value,
                }
            }
        }


class FakeBot:
    def __init__(self, open_value):
        self.module_kernel = FakeKernel(open_value)


def test_module_gate_reads_circuit_state():
    assert circuit_open(FakeBot(True), "cogs.music") is True
    assert circuit_open(FakeBot(False), "cogs.music") is False
    assert circuit_open(FakeBot(True), None) is False


def test_module_unavailable_exceptions_are_dedicated_check_failures():
    prefix = ModuleTemporarilyUnavailable("cogs.music")
    slash = AppModuleTemporarilyUnavailable("cogs.music")

    assert prefix.module == "cogs.music"
    assert slash.module == "cogs.music"


@pytest.mark.asyncio
async def test_prefix_gate_counts_only_allowed_module_call():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")

    async def callback():
        pass

    callback.__module__ = "cogs.music"
    ctx = SimpleNamespace(
        bot=SimpleNamespace(module_kernel=kernel),
        command=SimpleNamespace(cog=None, callback=callback),
    )

    assert await prefix_gate(ctx) is True
    assert kernel.in_flight("cogs.music") == 1


@pytest.mark.asyncio
async def test_prefix_gate_does_not_count_blocked_circuit_call():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    kernel.open_circuit("cogs.music", reason="test")

    async def callback():
        pass

    callback.__module__ = "cogs.music"
    ctx = SimpleNamespace(
        bot=SimpleNamespace(module_kernel=kernel),
        command=SimpleNamespace(cog=None, callback=callback),
    )

    with pytest.raises(ModuleTemporarilyUnavailable):
        await prefix_gate(ctx)
    assert kernel.in_flight("cogs.music") == 0


def test_slash_gate_installation_is_idempotent():
    async def callback(interaction):
        return None

    callback.__module__ = "cogs.music"
    command = app_commands.Command(
        name="musictest",
        description="test",
        callback=callback,
    )

    class Tree:
        def get_commands(self):
            return [command]

    bot = SimpleNamespace(tree=Tree())
    first = install_app_gates(bot)
    second = install_app_gates(bot)

    assert first == 1
    assert second == 0
