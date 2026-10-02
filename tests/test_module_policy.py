from core.module_policy import (
    CRITICAL_EXTENSIONS,
    MODULE_DEPENDENCIES,
    RUNTIME_LOCKED_EXTENSIONS,
    validate_policy,
)


def test_module_policy_is_internally_consistent_for_known_modules():
    extensions = set(CRITICAL_EXTENSIONS) | set(RUNTIME_LOCKED_EXTENSIONS)
    extensions.update(MODULE_DEPENDENCIES)
    for dependencies in MODULE_DEPENDENCIES.values():
        extensions.update(dependencies)

    assert validate_policy(extensions) == []


def test_module_policy_reports_missing_dependency():
    problems = validate_policy(["cogs.ticket_claim_security"])
    assert any("cogs.tickets" in problem for problem in problems)
