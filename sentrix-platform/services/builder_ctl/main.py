"""Builder controller entrypoint placeholder.

Production wiring is intentionally thin: transport-specific queue/registry
adapters wrap the tested core in :mod:`services.builder_ctl.controller`.
"""

from services.builder_ctl.controller import BuildCache


def create_state() -> BuildCache:
    return BuildCache()
