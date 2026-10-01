import pytest

from core.module_gate import (
    AppModuleTemporarilyUnavailable,
    ModuleTemporarilyUnavailable,
    circuit_open,
)


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
