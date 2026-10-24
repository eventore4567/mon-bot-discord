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
