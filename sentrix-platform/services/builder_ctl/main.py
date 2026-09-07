"""Entrypoint for the dedicated SentriX build worker."""

from __future__ import annotations

import asyncio

from services.builder_ctl.controller import BuildCache
from services.builder_ctl.network import prepare_from_env
from services.builder_ctl.worker import WorkerConfig, run_worker


def create_state() -> BuildCache:
    """Compatibility helper retained for deterministic controller tests."""
    return BuildCache()


def main() -> None:
    # Fail closed before the worker can claim any untrusted build.  This creates
    # or verifies the dedicated managed bridge and applies the host egress rules.
    prepare_from_env()
    asyncio.run(run_worker(WorkerConfig.from_env()))


if __name__ == "__main__":
    main()
