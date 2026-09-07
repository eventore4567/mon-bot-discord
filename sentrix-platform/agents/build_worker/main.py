"""Production build worker for SentriX Cloud V1.

The trusted worker coordinates Git/Docker, but tenant dependencies are installed
inside a disposable gVisor sandbox. User Dockerfiles are never evaluated.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from agents.node_agent.docker_runtime import CommandRunner, RuntimeErrorP1
from services.builder_ctl.controller import BuildRejected, preflight_source

log = logging.getLogger("sentrix.build-worker")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_SOURCE_FILES = 10_000
_TRUSTED_DOCKERFILE = """FROM python:3.12-slim
WORKDIR /app
COPY source/ /app/
COPY deps/ /opt/sentrix/deps/
ENV PYTHONPATH=/opt/sentrix/deps
"""


@dataclass(frozen=True, slots=True)
class BuildWorkerConfig:
    control_plane_url: str
    token: str
    worker_id: str
    docker_bin: str
    runtime: str
    egress_script: Path
    control_plane_cidrs: str
    poll_seconds: float

    @classmethod
    def from_env(cls) -> "BuildWorkerConfig":
        token = os.environ["SENTRIX_BUILDER_TOKEN"]
        if len(token) < 32:
            raise ValueError("SENTRIX_BUILDER_TOKEN trop court")
        return cls(
            control_plane_url=os.environ["SENTRIX_CONTROL_PLANE_URL"].rstrip("/"),
            token=token,
            worker_id=os.environ.get("SENTRIX_BUILDER_ID", "builder-1"),
            docker_bin=os.environ.get("SENTRIX_DOCKER_BIN", "docker"),
            runtime=os.environ.get("SENTRIX_GVISOR_RUNTIME", "runsc"),
            egress_script=Path(
                os.environ.get(
                    "SENTRIX_EGRESS_SCRIPT",
                    "ops/execution/apply-egress-policy.sh",
                )
            ),
            control_plane_cidrs=os.environ.get("SENTRIX_CONTROL_PLANE_CIDRS", ""),
            poll_seconds=float(os.environ.get("SENTRIX_BUILD_POLL_SECONDS", "2")),
        )


class BuildWorker:
    def __init__(self, config: BuildWorkerConfig) -> None:
        self.config = config
        self.runner = CommandRunner()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0))
        self.headers = {"X-Sentrix-Builder-Token": config.token}

    async def close(self) -> None:
        await self.client.aclose()

    async def preflight(self) -> None:
        await self.runner.run(self.config.docker_bin, "info")
        runtimes_raw = await self.runner.run(
            self.config.docker_bin,
            "info",
            "--format",
            "{{json .Runtimes}}",
        )
        if self.config.runtime not in runtimes_raw:
            raise RuntimeErrorP1(f"runtime gVisor {self.config.runtime!r} absent")
        if not self.config.egress_script.exists():
            raise RuntimeErrorP1("script egress absent")
        await self.runner.run(self.config.docker_bin, "pull", "python:3.12-slim")

    async def _claim(self) -> dict[str, object] | None:
        response = await self.client.get(
            f"{self.config.control_plane_url}/v1/internal/builder/claim",
            params={"worker_id": self.config.worker_id},
            headers=self.headers,
        )
        response.raise_for_status()
        payload = response.json()
        job = payload.get("job")
        return payload if isinstance(job, dict) else None

    async def _complete(self, claim: dict[str, object], digest: str) -> None:
        job = claim["job"]
        assert isinstance(job, dict)
        response = await self.client.post(
            f"{self.config.control_plane_url}/v1/internal/builder/complete",
            headers=self.headers,
            json={
                "message_id": claim["message_id"],
                "build_id": job["build_id"],
                "org_id": job["org_id"],
                "environment_id": job["environment_id"],
                "image_digest": digest,
            },
        )
        response.raise_for_status()

    async def _failed(self, claim: dict[str, object], error: str) -> None:
        job = claim["job"]
        assert isinstance(job, dict)
        response = await self.client.post(
            f"{self.config.control_plane_url}/v1/internal/builder/failed",
            headers=self.headers,
            json={
                "message_id": claim["message_id"],
                "build_id": job["build_id"],
                "org_id": job["org_id"],
                "environment_id": job["environment_id"],
                "error": error[:2000],
            },
        )
        response.raise_for_status()

    @staticmethod
    def _validate_job(job: dict[str, object]) -> tuple[str, str]:
        repository = str(job.get("repository", ""))
        commit = str(job.get("commit_sha", ""))
        if not _REPOSITORY.fullmatch(repository) or not _COMMIT.fullmatch(commit):
            raise ValueError("coordonnees GitHub invalides")
        return repository, commit

    async def _checkout(self, repository: str, commit: str, target: Path) -> None:
        await self.runner.run("git", "init", str(target))
        await self.runner.run(
            "git",
            "-C",
            str(target),
            "remote",
            "add",
            "origin",
            f"https://github.com/{repository}.git",
        )
        await self.runner.run(
            "git",
            "-C",
            str(target),
            "-c",
            "protocol.file.allow=never",
            "fetch",
            "--depth=1",
            "origin",
            commit,
        )
        await self.runner.run("git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD")
        await self.runner.run("git", "-C", str(target), "clean", "-ffdqx")
        shutil.rmtree(target / ".git", ignore_errors=True)

    @staticmethod
    def _enforce_source_limits(root: Path) -> None:
        files = 0
        total = 0
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            files += 1
            total += path.stat().st_size
            if files > _MAX_SOURCE_FILES or total > _MAX_SOURCE_BYTES:
                raise ValueError("depot trop volumineux pour SentriX Cloud V1")

    async def _network(self, name: str) -> None:
        await self.runner.run(
            self.config.docker_bin,
            "network",
            "create",
            "--driver",
            "bridge",
            "--opt",
            "com.docker.network.bridge.enable_icc=false",
            "--label",
            "sentrix.managed=true",
            name,
        )
        await self.runner.run(
            str(self.config.egress_script),
            self.config.docker_bin,
            self.config.control_plane_cidrs,
        )

    async def _dependencies(self, root: Path, work: Path, build_name: str) -> None:
        deps = work / "deps"
        deps.mkdir()
        requirements = root / "requirements.txt"
        if not requirements.exists():
            return
        network = f"sx-build-net-{build_name}"
        container = f"sx-build-{build_name}"
        await self._network(network)
        try:
            await self.runner.run(
                self.config.docker_bin,
                "run",
                "-d",
                "--name",
                container,
                "--runtime",
                self.config.runtime,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                "256",
                "--cpus",
                "1.0",
                "--memory",
                "1024m",
                "--memory-swap",
                "1024m",
                "--network",
                network,
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=256m",
                "--tmpfs",
                "/work:rw,nosuid,nodev,size=768m",
                "python:3.12-slim",
                "/bin/sh",
                "-c",
                "sleep 900",
            )
            await self.runner.run(
                self.config.docker_bin,
                "cp",
                str(requirements),
                f"{container}:/work/requirements.txt",
            )
            await self.runner.run(
                self.config.docker_bin,
                "exec",
                container,
                "python",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--only-binary=:all:",
                "--requirement",
                "/work/requirements.txt",
                "--target",
                "/work/deps",
            )
            await self.runner.run(
                self.config.docker_bin,
                "cp",
                f"{container}:/work/deps/.",
                str(deps),
            )
        finally:
            await self.runner.run(self.config.docker_bin, "rm", "-f", container, check=False)
            await self.runner.run(self.config.docker_bin, "network", "rm", network, check=False)
            await self.runner.run(
                str(self.config.egress_script),
                self.config.docker_bin,
                self.config.control_plane_cidrs,
                check=False,
            )

    async def _assemble(self, source: Path, work: Path, build_name: str) -> str:
        context = work / "image"
        context.mkdir()
        shutil.copytree(source, context / "source", symlinks=True)
        shutil.copytree(work / "deps", context / "deps", symlinks=True)
        (context / "Dockerfile.sentrix").write_text(_TRUSTED_DOCKERFILE, encoding="utf-8")
        tag = f"sentrix-runtime:{build_name}"
        await self.runner.run(
            self.config.docker_bin,
            "build",
            "--network=none",
            "--file",
            str(context / "Dockerfile.sentrix"),
            "--tag",
            tag,
            str(context),
        )
        digest = await self.runner.run(
            self.config.docker_bin,
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            tag,
        )
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise RuntimeErrorP1("digest runtime invalide")
        return digest

    async def build(self, claim: dict[str, object]) -> str:
        job = claim["job"]
        assert isinstance(job, dict)
        repository, commit = self._validate_job(job)
        build_name = uuid4().hex[:16]
        with tempfile.TemporaryDirectory(prefix="sentrix-build-") as temp:
            work = Path(temp)
            source = work / "source"
            source.mkdir()
            await self._checkout(repository, commit, source)
            self._enforce_source_limits(source)
            preflight_source(source)
            await self._dependencies(source, work, build_name)
            return await self._assemble(source, work, build_name)

    async def run_once(self) -> bool:
        claim = await self._claim()
        if claim is None:
            return False
        try:
            digest = await self.build(claim)
            await self._complete(claim, digest)
        except BuildRejected as exc:
            await self._failed(claim, f"secret scan rejected source ({len(exc.findings)} findings)")
        except Exception as exc:  # noqa: BLE001 - job failure is reported, worker stays alive.
            log.exception("build echoue")
            await self._failed(claim, f"{type(exc).__name__}: {exc}")
        return True

    async def run_forever(self) -> None:
        await self.preflight()
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(self.config.poll_seconds)


async def _run() -> None:
    worker = BuildWorker(BuildWorkerConfig.from_env())
    try:
        await worker.run_forever()
    finally:
        await worker.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
