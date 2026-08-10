"""Boucle pull/reconcile P1 avec survie a la panne du Control Plane."""

from __future__ import annotations

import asyncio
import logging

from agents.node_agent.cache import DesiredCache
from agents.node_agent.client import ControlPlaneClient
from agents.node_agent.docker_runtime import DockerRuntime
from libs.runtime_models import AgentObservedInstance

log = logging.getLogger("sentrix.node-agent")


class Reconciler:
    def __init__(
        self,
        client: ControlPlaneClient,
        runtime: DockerRuntime,
        cache: DesiredCache,
        *,
        poll_seconds: float = 5.0,
    ) -> None:
        self.client = client
        self.runtime = runtime
        self.cache = cache
        self.poll_seconds = poll_seconds

    async def reconcile_once(self) -> tuple[bool, list[AgentObservedInstance]]:
        fresh = False
        try:
            desired = await self.client.pull()
            self.cache.save(desired)
            fresh = True
        except Exception as exc:  # noqa: BLE001 - panne CP volontairement absorbee
            log.warning("Control Plane indisponible, utilisation du cache local: %s", exc)
            desired = self.cache.load()

        statuses: list[AgentObservedInstance] = []
        desired_ids = {item.instance_id for item in desired}
        for spec in desired:
            try:
                observation = await (
                    self.runtime.start(spec)
                    if spec.desired_state == "running"
                    else self.runtime.stop(spec.instance_id)
                )
                statuses.append(self.runtime.to_report(observation))
            except Exception as exc:  # noqa: BLE001 - une instance ne bloque pas les voisines
                log.exception("echec reconcile instance %s", spec.instance_id)
                statuses.append(
                    AgentObservedInstance(
                        instance_id=spec.instance_id,
                        observed_state="failed",
                        container_id=None,
                        generation=spec.generation,
                        health="unhealthy",
                        detail=str(exc)[:2000],
                    )
                )

        # Ne jamais supprimer des orphelins pendant une panne du CP : le cache
        # peut etre ancien. Le garbage collection n'est autorise qu'apres un pull frais.
        if fresh:
            for instance_id in await self.runtime.list_managed_instance_ids() - desired_ids:
                observation = await self.runtime.stop(instance_id)
                statuses.append(self.runtime.to_report(observation, detail="orphan removed"))

        if fresh:
            try:
                await self.client.report(statuses)
            except Exception as exc:  # noqa: BLE001
                log.warning("rapport de sante impossible: %s", exc)
        return fresh, statuses

    async def run_forever(self) -> None:
        await self.runtime.preflight()
        while True:
            await self.reconcile_once()
            await asyncio.sleep(self.poll_seconds)
