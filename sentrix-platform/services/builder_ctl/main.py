"""Entrypoint for the dedicated SentriX build worker."""

from __future__ import annotations

import asyncio

from services.builder_ctl.controller import BuildCache
from services.builder_ctl.worker import WorkerConfig, run_worker


def create_state() -> BuildCache:
    """Compatibility helper retained for deterministic controller tests."""
    return BuildCache()


def main() -> None:
    asyncio.run(run_worker(WorkerConfig.from_env()))


if __name__ == "__main__":
    main()
