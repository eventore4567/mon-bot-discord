"""Entrypoint `python -m agents.node_agent.main`."""

from __future__ import annotations

import asyncio
import logging

from agents.node_agent.cache import DesiredCache
from agents.node_agent.client import ControlPlaneClient
from agents.node_agent.config import AgentConfig
from agents.node_agent.docker_runtime import DockerRuntime
from agents.node_agent.reconciler import Reconciler


async def _run() -> None:
    config = AgentConfig.from_env()
    client = ControlPlaneClient(config.control_plane_url, config.node_id, config.node_token)
    runtime = DockerRuntime(
        config.docker_bin,
        config.runtime,
        config.egress_script,
        config.control_plane_cidrs,
    )
    reconciler = Reconciler(
        client,
        runtime,
        DesiredCache(config.cache_path),
        poll_seconds=config.poll_seconds,
    )
    try:
        await reconciler.run_forever()
    finally:
        await client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
