from core.module_kernel import ModuleKernel


def test_optional_module_failure_is_isolated():
    kernel = ModuleKernel(
        ["cogs.moderation", "cogs.music"],
        critical={"cogs.moderation"},
    )
    kernel.begin("cogs.moderation")
    kernel.loaded("cogs.moderation")
    kernel.begin("cogs.music")
    kernel.failed("cogs.music", RuntimeError("boom"))

    snapshot = kernel.snapshot()
    assert snapshot["ready"] is True
    assert snapshot["critical_failed"] == []
    assert snapshot["loaded"] == 1
    assert snapshot["modules"]["cogs.music"]["status"] == "failed"
    assert snapshot["modules"]["cogs.music"]["error"] == "RuntimeError"


def test_critical_module_failure_blocks_readiness():
    kernel = ModuleKernel(
        ["cogs.moderation", "cogs.music"],
        critical={"cogs.moderation"},
    )
    kernel.begin("cogs.moderation")
    kernel.failed("cogs.moderation", ValueError("broken"))

    snapshot = kernel.snapshot()
    assert snapshot["ready"] is False
    assert snapshot["critical_failed"] == ["cogs.moderation"]


def test_kernel_tracks_loading_attempts_and_duration():
    kernel = ModuleKernel(["cogs.utility"])
    kernel.begin("cogs.utility")
    kernel.loaded("cogs.utility")

    state = kernel.snapshot()["modules"]["cogs.utility"]
    assert state["attempts"] == 1
    assert state["status"] == "loaded"
    assert state["load_ms"] is not None
    assert state["load_ms"] >= 0


def test_kernel_tracks_unload_and_reload_metadata():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    kernel.begin("cogs.music", operation="reload")
    kernel.loaded("cogs.music")
    kernel.unloaded("cogs.music")

    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["status"] == "unloaded"
    assert state["reloads"] == 1
    assert state["last_operation"] == "unload"


def test_recovered_reload_keeps_module_available_and_records_error():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    kernel.begin("cogs.music", operation="reload")
    kernel.recovered("cogs.music", RuntimeError("new version failed"))

    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["status"] == "loaded"
    assert state["error"] is None
    assert state["last_error"] == "RuntimeError"
    assert kernel.snapshot()["ready"] is True
