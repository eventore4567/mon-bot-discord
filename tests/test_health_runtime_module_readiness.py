from core.module_health import extension_state_from_runtime, supervisor_ready


def test_health_extension_state_respects_kernel_ready_flag():
    runtime = {
        "loaded": 1,
        "expected": 1,
        "ready": False,
        "critical_failed": [],
        "failed": [],
    }

    loaded, expected, ok, critical_failed, failed = extension_state_from_runtime(
        runtime,
        fallback_loaded=0,
        fallback_expected=0,
    )
    assert loaded == 1
    assert expected == 1
    assert ok is False
    assert critical_failed == []
    assert failed == []


def test_health_extension_state_falls_back_without_runtime_snapshot():
    loaded, expected, ok, critical_failed, failed = extension_state_from_runtime(
        None,
        fallback_loaded=3,
        fallback_expected=4,
    )
    assert loaded == 3
    assert expected == 4
    assert ok is False
    assert critical_failed == []
    assert failed == []


def test_supervisor_readiness_requires_running_clean_supervisor():
    assert supervisor_ready({"running": True, "last_internal_error": None}) is True
    assert supervisor_ready({"running": False, "last_internal_error": None}) is False
    assert supervisor_ready({"running": True, "last_internal_error": "RuntimeError"}) is False
    assert supervisor_ready(None) is False
