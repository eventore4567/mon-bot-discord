import sys

from core.runtime_attribution import module_from_traceback


def _trace_from_named_module(module_name: str):
    namespace = {"__name__": module_name}
    exec(
        "def boom():\n    raise RuntimeError('boom')",
        namespace,
    )
    try:
        namespace["boom"]()
    except RuntimeError:
        return sys.exc_info()[2]
    raise AssertionError("exception attendue")


def test_traceback_is_attributed_to_known_cog_module():
    tb = _trace_from_named_module("cogs.music")
    assert module_from_traceback(
        tb,
        known=lambda name: name == "cogs.music",
    ) == "cogs.music"


def test_traceback_ignores_unknown_cog_module():
    tb = _trace_from_named_module("cogs.unknown")
    assert module_from_traceback(
        tb,
        known=lambda name: False,
    ) is None
