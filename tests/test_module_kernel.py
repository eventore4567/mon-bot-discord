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


def test_optional_module_opens_circuit_after_five_consecutive_errors():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")

    for _ in range(5):
        kernel.record_runtime_error("cogs.music", RuntimeError("boom"))

    snapshot = kernel.snapshot()
    state = snapshot["modules"]["cogs.music"]
    assert state["circuit_open"] is True
    assert snapshot["open_circuits"] == ["cogs.music"]


def test_critical_module_never_auto_opens_circuit():
    kernel = ModuleKernel(["cogs.moderation"], critical={"cogs.moderation"})
    kernel.begin("cogs.moderation")
    kernel.loaded("cogs.moderation")

    for _ in range(10):
        kernel.record_runtime_error("cogs.moderation", RuntimeError("boom"))

    state = kernel.snapshot()["modules"]["cogs.moderation"]
    assert state["runtime_degraded"] is True
    assert state["circuit_open"] is False


def test_success_closes_open_circuit():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    for _ in range(5):
        kernel.record_runtime_error("cogs.music", RuntimeError("boom"))

    kernel.record_runtime_success("cogs.music")
    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["circuit_open"] is False
    assert state["runtime_degraded"] is False


def test_old_runtime_errors_do_not_accumulate_into_new_circuit(monkeypatch):
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")

    times = iter([1000, 1001, 1002, 1400])
    monkeypatch.setattr("core.module_kernel.time.time", lambda: next(times))

    kernel.record_runtime_error("cogs.music", RuntimeError("one"))
    kernel.record_runtime_error("cogs.music", RuntimeError("two"))
    kernel.record_runtime_error("cogs.music", RuntimeError("three"))
    assert kernel.snapshot()["modules"]["cogs.music"]["runtime_degraded"] is True

    # 398 secondes plus tard : la série précédente ne doit plus compter.
    kernel.record_runtime_error("cogs.music", RuntimeError("later"))
    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["consecutive_runtime_errors"] == 1
    assert state["runtime_degraded"] is False
    assert state["circuit_open"] is False


def test_kernel_keeps_bounded_lifecycle_journal():
    kernel = ModuleKernel(["cogs.music"])
    for _ in range(150):
        kernel.begin("cogs.music", operation="reload")
        kernel.loaded("cogs.music")

    events = kernel.snapshot()["recent_events"]
    assert len(events) <= 20
    assert events[-1]["module"] == "cogs.music"
    assert events[-1]["event"] == "loaded"


def test_circuit_transitions_are_recorded_in_journal():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    for _ in range(5):
        kernel.record_runtime_error("cogs.music", RuntimeError("boom"))
    kernel.close_circuit("cogs.music")

    event_names = [event["event"] for event in kernel.snapshot()["recent_events"]]
    assert "circuit_open" in event_names
    assert "circuit_closed" in event_names


def test_in_flight_counter_never_goes_negative():
    kernel = ModuleKernel(["cogs.music"])
    kernel.enter_runtime("cogs.music")
    kernel.enter_runtime("cogs.music")
    assert kernel.in_flight("cogs.music") == 2

    kernel.exit_runtime("cogs.music")
    kernel.exit_runtime("cogs.music")
    kernel.exit_runtime("cogs.music")
    assert kernel.in_flight("cogs.music") == 0


def test_degraded_critical_module_fails_kernel_readiness_without_opening_circuit():
    kernel = ModuleKernel(["cogs.moderation"], critical={"cogs.moderation"})
    kernel.begin("cogs.moderation")
    kernel.loaded("cogs.moderation")
    for _ in range(3):
        kernel.record_runtime_error("cogs.moderation", RuntimeError("boom"))

    snapshot = kernel.snapshot()
    assert snapshot["ready"] is False
    assert snapshot["critical_runtime_degraded"] == ["cogs.moderation"]
    assert snapshot["open_circuits"] == []


def test_runtime_success_does_not_close_maintenance_circuit():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    kernel.open_circuit("cogs.music", reason="maintenance")

    kernel.record_runtime_success("cogs.music")
    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["circuit_open"] is True
    assert state["circuit_reason"] == "maintenance"


def test_runtime_error_circuit_has_reason_and_success_can_close_it():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    for _ in range(5):
        kernel.record_runtime_error("cogs.music", RuntimeError("boom"))

    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["circuit_reason"] == "runtime_errors"

    kernel.record_runtime_success("cogs.music")
    state = kernel.snapshot()["modules"]["cogs.music"]
    assert state["circuit_open"] is False
    assert state["circuit_reason"] is None


def test_kernel_exposes_reverse_dependencies():
    kernel = ModuleKernel(
        ["cogs.ai", "cogs.ai_disable_guard", "cogs.other"],
        dependencies={"cogs.ai_disable_guard": ("cogs.ai",)},
    )

    assert kernel.dependents("cogs.ai") == ("cogs.ai_disable_guard",)
    assert kernel.dependents("cogs.other") == ()


def test_dependency_with_open_circuit_blocks_dependent():
    kernel = ModuleKernel(
        ["cogs.events", "cogs.giveaway_center"],
        dependencies={"cogs.giveaway_center": ("cogs.events",)},
    )
    for name in ("cogs.events", "cogs.giveaway_center"):
        kernel.begin(name)
        kernel.loaded(name)

    assert kernel.blockers("cogs.giveaway_center") == ()
    kernel.open_circuit("cogs.events", reason="runtime_failure")
    assert kernel.blockers("cogs.giveaway_center") == ("cogs.events",)


def test_kernel_invariants_are_clean_for_normal_loaded_module():
    kernel = ModuleKernel(["cogs.music"])
    kernel.begin("cogs.music")
    kernel.loaded("cogs.music")
    assert kernel.validate_invariants() == []
    assert kernel.snapshot()["ready"] is True


def test_kernel_invariant_error_fails_readiness():
    kernel = ModuleKernel(["cogs.moderation"], critical={"cogs.moderation"})
    kernel.begin("cogs.moderation")
    kernel.loaded("cogs.moderation")

    # Simule une corruption interne impossible via l'API normale.
    kernel._states["cogs.moderation"].circuit_open = True
    kernel._states["cogs.moderation"].circuit_reason = "corrupt"

    snapshot = kernel.snapshot()
    assert snapshot["ready"] is False
    assert any("circuit ouvert" in problem for problem in snapshot["invariant_errors"])
