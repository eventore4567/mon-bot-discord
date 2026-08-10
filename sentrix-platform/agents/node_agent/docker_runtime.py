"""Runtime Docker/gVisor P1.

Le node-agent est un composant de confiance du noeud et pilote Docker. Les
sandboxes, elles, ne recoivent aucun socket Docker, aucune capability Linux et
aucun bind mount hote.
"""

from __future__ import annotations

import asyncio
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from libs.runtime_models import AgentDesiredInstance, AgentObservedInstance


class RuntimeErrorP1(RuntimeError):
    pass


@dataclass(frozen=True)
class ContainerObservation:
    instance_id: UUID
    container_id: str | None
    state: str
    generation: int
    exit_code: int | None


class CommandRunner:
    async def run(self, *args: str, check: bool = True) -> str:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        stdout = out.decode("utf-8", "replace").strip()
        stderr = err.decode("utf-8", "replace").strip()
        if check and proc.returncode != 0:
            raise RuntimeErrorP1(f"commande {args[0]!r} echouee ({proc.returncode}): {stderr}")
        return stdout


class DockerRuntime:
    def __init__(
        self,
        docker_bin: str,
        runtime: str,
        egress_script: Path,
        control_plane_cidrs: tuple[str, ...],
        *,
        runner: CommandRunner | None = None,
    ) -> None:
        self.docker = docker_bin
        self.runtime = runtime
        self.egress_script = egress_script
        self.control_plane_cidrs = control_plane_cidrs
        self.runner = runner or CommandRunner()

    @staticmethod
    def container_name(instance_id: UUID) -> str:
        return f"sentrix-{instance_id}"

    @staticmethod
    def network_name(instance_id: UUID) -> str:
        return f"sentrix-net-{instance_id}"

    async def preflight(self) -> None:
        if platform.system() != "Linux":
            raise RuntimeErrorP1("Execution Plane P1 exige un hote Linux")
        if not Path("/sys/fs/cgroup/cgroup.controllers").exists():
            raise RuntimeErrorP1("cgroups v2 requis")
        runtimes_raw = await self.runner.run(self.docker, "info", "--format", "{{json .Runtimes}}")
        runtimes = json.loads(runtimes_raw or "{}")
        if self.runtime not in runtimes:
            raise RuntimeErrorP1(f"runtime gVisor {self.runtime!r} absent de Docker")
        if not self.egress_script.exists():
            raise RuntimeErrorP1(f"script egress absent: {self.egress_script}")

    async def _container_id(self, instance_id: UUID) -> str | None:
        name = self.container_name(instance_id)
        value = await self.runner.run(
            self.docker,
            "ps",
            "-aq",
            "--filter",
            f"name=^{name}$",
            check=False,
        )
        return value.splitlines()[0] if value else None

    async def _inspect(self, container_id: str) -> dict[str, object]:
        raw = await self.runner.run(self.docker, "inspect", container_id)
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or not parsed:
            raise RuntimeErrorP1("docker inspect invalide")
        item = parsed[0]
        if not isinstance(item, dict):
            raise RuntimeErrorP1("docker inspect invalide")
        return item

    async def ensure_network(self, instance_id: UUID) -> None:
        name = self.network_name(instance_id)
        exists = await self.runner.run(
            self.docker,
            "network",
            "ls",
            "-q",
            "--filter",
            f"name=^{name}$",
            check=False,
        )
        if not exists:
            await self.runner.run(
                self.docker,
                "network",
                "create",
                "--driver",
                "bridge",
                "--opt",
                "com.docker.network.bridge.enable_icc=false",
                "--label",
                "sentrix.managed=true",
                "--label",
                f"sentrix.instance_id={instance_id}",
                name,
            )
        await self.apply_egress_policy()

    async def apply_egress_policy(self) -> None:
        await self.runner.run(
            str(self.egress_script),
            self.docker,
            ",".join(self.control_plane_cidrs),
        )

    async def observe(self, instance_id: UUID) -> ContainerObservation:
        cid = await self._container_id(instance_id)
        if cid is None:
            return ContainerObservation(instance_id, None, "stopped", 0, None)
        info = await self._inspect(cid)
        state = info.get("State", {})
        config = info.get("Config", {})
        labels = config.get("Labels", {}) if isinstance(config, dict) else {}
        running = bool(state.get("Running")) if isinstance(state, dict) else False
        exit_code = state.get("ExitCode") if isinstance(state, dict) else None
        generation_raw = labels.get("sentrix.generation", "0") if isinstance(labels, dict) else "0"
        try:
            generation = int(generation_raw)
        except (TypeError, ValueError):
            generation = 0
        return ContainerObservation(
            instance_id=instance_id,
            container_id=cid,
            state="running" if running else "stopped",
            generation=generation,
            exit_code=int(exit_code) if isinstance(exit_code, int) else None,
        )

    async def start(self, spec: AgentDesiredInstance) -> ContainerObservation:
        current = await self.observe(spec.instance_id)
        if (
            current.container_id
            and current.state == "running"
            and current.generation == spec.generation
        ):
            return current
        if current.container_id:
            await self.runner.run(self.docker, "rm", "-f", current.container_id, check=False)

        await self.ensure_network(spec.instance_id)
        memory = f"{spec.memory_mb}m"
        cpus = f"{spec.cpu_millis / 1000:.3f}"
        args = [
            self.docker,
            "run",
            "-d",
            "--name",
            self.container_name(spec.instance_id),
            "--runtime",
            self.runtime,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(spec.pids_limit),
            "--cpus",
            cpus,
            "--memory",
            memory,
            "--memory-swap",
            memory,
            "--network",
            self.network_name(spec.instance_id),
            "--label",
            "sentrix.managed=true",
            "--label",
            f"sentrix.instance_id={spec.instance_id}",
            "--label",
            f"sentrix.generation={spec.generation}",
            spec.image_ref,
            *spec.command,
        ]
        await self.runner.run(*args)
        return await self.observe(spec.instance_id)

    async def stop(self, instance_id: UUID) -> ContainerObservation:
        cid = await self._container_id(instance_id)
        if cid:
            await self.runner.run(self.docker, "rm", "-f", cid, check=False)
        network = self.network_name(instance_id)
        await self.runner.run(self.docker, "network", "rm", network, check=False)
        await self.apply_egress_policy()
        return ContainerObservation(instance_id, None, "stopped", 0, 0)

    async def list_managed_instance_ids(self) -> set[UUID]:
        raw = await self.runner.run(
            self.docker,
            "ps",
            "-aq",
            "--filter",
            "label=sentrix.managed=true",
            check=False,
        )
        result: set[UUID] = set()
        for cid in raw.splitlines():
            if not cid:
                continue
            info = await self._inspect(cid)
            config = info.get("Config", {})
            labels = config.get("Labels", {}) if isinstance(config, dict) else {}
            value = labels.get("sentrix.instance_id") if isinstance(labels, dict) else None
            if isinstance(value, str):
                try:
                    result.add(UUID(value))
                except ValueError:
                    continue
        return result

    @staticmethod
    def to_report(
        observation: ContainerObservation, *, detail: str | None = None
    ) -> AgentObservedInstance:
        running = observation.state == "running"
        return AgentObservedInstance(
            instance_id=observation.instance_id,
            observed_state="running" if running else "stopped",
            container_id=observation.container_id,
            generation=observation.generation,
            exit_code=observation.exit_code,
            health="healthy" if running else "unknown",
            detail=detail,
        )
