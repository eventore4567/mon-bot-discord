from core.module_health import is_technical_failure


def test_user_and_permission_errors_do_not_degrade_module_health():
    for name in (
        "BadArgument",
        "CheckFailure",
        "CommandOnCooldown",
        "MissingPermissions",
        "Forbidden",
        "ModuleTemporarilyUnavailable",
    ):
        assert is_technical_failure(name) is False


def test_unexpected_runtime_error_counts_as_technical_failure():
    assert is_technical_failure(RuntimeError("boom")) is True
    assert is_technical_failure("RuntimeError") is True
