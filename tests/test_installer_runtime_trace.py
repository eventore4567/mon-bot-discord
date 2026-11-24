"""Le traceur comptabilise les installateurs réellement exécutés, pas importés."""
import sys

from tools import installer_runtime_trace as trace


def test_trace_sees_real_installer_calls_in_cogs():
    observed = set()
    code = compile(
        "def install(bot):\n"
        "    return None\n"
        "install(None)\n",
        str(trace.COGS / "synthetic_installer.py"),
        "exec",
    )
    previous = sys.getprofile()
    sys.setprofile(trace.make_profiler(observed))
    try:
        exec(code, {})
    finally:
        sys.setprofile(previous)
    assert "cogs.synthetic_installer" in observed


def test_trace_ignores_non_executed_installer():
    observed = set()
    code = compile(
        "def install(bot):\n"
        "    return None\n",
        str(trace.COGS / "not_executed.py"),
        "exec",
    )
    previous = sys.getprofile()
    sys.setprofile(trace.make_profiler(observed))
    try:
        exec(code, {})
    finally:
        sys.setprofile(previous)
    assert "cogs.not_executed" not in observed


import pytest
from unittest.mock import AsyncMock


@pytest.mark.parametrize(
    "v17_failures, load_failures, loaded, expected, exit_code",
    [
        (0, 0, 12, 12, 0),
        (1, 0, 12, 12, 1),
        (0, 1, 12, 12, 1),
        (0, 0, 11, 12, 1),
        (0, 0, 12, None, 1),
    ],
)
def test_runtime_trace_exits_nonzero_on_incomplete_boot(
    monkeypatch, capsys, v17_failures, load_failures, loaded, expected, exit_code
):
    payload = {
        "v17_failure_count": v17_failures,
        "extension_load_failure_count": load_failures,
        "extensions_loaded": loaded,
        "extensions_expected": expected,
    }
    monkeypatch.setattr(trace, "trace", AsyncMock(return_value=payload))
    assert trace.main() == exit_code
    assert "Attention" in capsys.readouterr().out
