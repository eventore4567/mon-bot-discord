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


def test_dependency_failure_blocks_dependent_without_marking_technical_failure():
    kernel = ModuleKernel(
        ["cogs.automod", "cogs.security_runtime_hardening"],
        critical={"cogs.automod", "cogs.security_runtime_hardening"},
        dependencies={"cogs.security_runtime_hardening": ("cogs.automod",)},
    )
    kernel.begin("cogs.automod")
    kernel.failed("cogs.automod", RuntimeError("boom"))
    blockers = kernel.blockers("cogs.security_runtime_hardening")
    kernel.blocked("cogs.security_runtime_hardening", blockers)

    snapshot = kernel.snapshot()
    dependent = snapshot["modules"]["cogs.security_runtime_hardening"]
    assert dependent["status"] == "blocked"
    assert dependent["blocked_by"] == ["cogs.automod"]
    assert "cogs.security_runtime_hardening" in snapshot["critical_failed"]
    assert all(
        item["name"] != "cogs.security_runtime_hardening"
        for item in snapshot["failed"]
    )


def test_dependency_unblocks_after_dependency_recovers():
    kernel = ModuleKernel(
        ["cogs.events", "cogs.giveaway_center"],
        dependencies={"cogs.giveaway_center": ("cogs.events",)},
    )
    kernel.begin("cogs.events")
    kernel.failed("cogs.events", RuntimeError("boom"))
    kernel.blocked("cogs.giveaway_center", kernel.blockers("cogs.giveaway_center"))
    assert kernel.blockers("cogs.giveaway_center") == ("cogs.events",)

    kernel.begin("cogs.events", operation="reload")
    kernel.loaded("cogs.events")
    assert kernel.blockers("cogs.giveaway_center") == ()


def test_reconcile_detects_missing_runtime_module():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")

    changed = kernel.reconcile([])
    state = kernel.snapshot()["modules"]["cogs.music"]
    assert changed == ["cogs.music"]
    assert state["status"] == "failed"
    assert state["error"] == "RuntimeMissing"


def test_reconcile_recovers_stale_failed_state_when_runtime_has_module():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.failed("cogs.music", RuntimeError("boom"))

    changed = kernel.reconcile(["cogs.music"])
    state = kernel.snapshot()["modules"]["cogs.music"]
    assert changed == ["cogs.music"]
    assert state["status"] == "loaded"
    assert state["error"] is None


def test_runtime_errors_degrade_module_after_threshold_and_success_recovers():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")

    kernel.record_runtime_error("cogs.music", RuntimeError("one"))
    kernel.record_runtime_error("cogs.music", RuntimeError("two"))
    assert kernel.snapshot()["runtime_degraded"] == []

    kernel.record_runtime_error("cogs.music", RuntimeError("three"))
    snapshot = kernel.snapshot()
    state = snapshot["modules"]["cogs.music"]
    assert snapshot["runtime_degraded"] == ["cogs.music"]
    assert state["runtime_errors"] == 3
    assert state["consecutive_runtime_errors"] == 3
    assert state["runtime_degraded"] is True

    kernel.record_runtime_success("cogs.music")
    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["runtime_degraded"] is False
    assert state["consecutive_runtime_errors"] == 0
    assert state["runtime_errors"] == 3
