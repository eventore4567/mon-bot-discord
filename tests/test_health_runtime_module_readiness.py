from core.module_kernel import ModuleKernel
from web.health_runtime_v45 import _extension_state


class FakeBot:
    pass


def test_health_extension_state_respects_kernel_ready_flag():
    bot = FakeBot()
    bot.extensions = {}
    bot.module_kernel = ModuleKernel(["cogs.moderation"], critical={"cogs.moderation"})
    bot.module_kernel.begin("cogs.moderation")
    bot.module_kernel.loaded("cogs.moderation")
    for _ in range(3):
        bot.module_kernel.record_runtime_error("cogs.moderation", RuntimeError("boom"))

    loaded, expected, ok, critical_failed, failed = _extension_state(bot)
    assert loaded == 1
    assert expected == 1
    assert ok is False
    assert critical_failed == []
    assert failed == []
