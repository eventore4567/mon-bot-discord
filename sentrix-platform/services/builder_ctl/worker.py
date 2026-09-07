"""Executable managed build worker for SentriX Hosting.

Dependency installation runs inside gVisor. The host-side Docker build uses a
trusted generated Dockerfile, so a tenant Dockerfile is never executed by the
daemon.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, Field

from services.builder_ctl.controller import (
    BuildRejected,
    preflight_source,
    sanitized_build_environment,
)
from services.builder_ctl.models import BuildMount, BuildSandboxSpec
from services.builder_ctl.sandbox import docker_command

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REGISTRY = re.compile(r"^[a-z0-9._:-]+(?:/[a-z0-9._-]+)*$")


class SourceRejectedError(RuntimeError):
    pass


class BuildExecutionError(RuntimeError):
    pass


class RemoteBuildJob(BaseModel):
    build_id: UUID
    org_id: UUID
    environment_id: UUID
    repository: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    library: str
    runtime_mode: str
    lease_attempt: int = Field(ge=1)


@dataclass(frozen=True, slots=True)
class BuildResult:
    image_ref: str
    image_digest: str


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    api_url: str
    worker_id: UUID
    worker_token: str
    registry_prefix: str
    github_token: str | None = None
    build_network: str = "bridge"
    poll_seconds: float = 2.0
    command_timeout: int = 900

    @classmethod
    def from_env(cls) -> WorkerConfig:
        api_url = os.environ["SENTRIX_API_URL"].rstrip("/")
        registry = os.environ["SENTRIX_REGISTRY_PREFIX"].strip("/")
        if not api_url.startswith(("https://", "http://")):
            raise RuntimeError("SENTRIX_API_URL must be http(s)")
        if not _REGISTRY.fullmatch(registry):
            raise RuntimeError("invalid SENTRIX_REGISTRY_PREFIX")
        return cls(
            api_url=api_url,
            worker_id=UUID(os.environ["SENTRIX_CONTROL_WORKER_ID"]),
            worker_token=os.environ["SENTRIX_CONTROL_WORKER_TOKEN"],
            registry_prefix=registry,
            github_token=os.environ.get("SENTRIX_GITHUB_TOKEN") or None,
            build_network=os.environ.get("SENTRIX_BUILD_NETWORK", "bridge"),
            poll_seconds=float(os.environ.get("SENTRIX_BUILD_POLL_SECONDS", "2")),
            command_timeout=int(os.environ.get("SENTRIX_BUILD_TIMEOUT", "900")),
        )


class ControlApi:
    def __init__(self, config: WorkerConfig) -> None:
        self._client = httpx.AsyncClient(
            base_url=config.api_url,
            headers={
                "X-Sentrix-Worker-Id": str(config.worker_id),
                "X-Sentrix-Worker-Token": config.worker_token,
            },
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def claim(self) -> RemoteBuildJob | None:
        response = await self._client.post("/v1/control/builder/claim")
        response.raise_for_status()
        if response.content in (b"", b"null"):
            return None
        return RemoteBuildJob.model_validate(response.json())

    async def renew(self, job: RemoteBuildJob) -> None:
        response = await self._client.post(
            "/v1/control/builder/renew",
            json={"build_id": str(job.build_id), "lease_attempt": job.lease_attempt},
        )
        response.raise_for_status()

    async def report(
        self,
        job: RemoteBuildJob,
        *,
        outcome: str,
        result: BuildResult | None = None,
        error: str | None = None,
    ) -> None:
        response = await self._client.post(
            "/v1/control/builder/report",
            json={
                "build_id": str(job.build_id),
                "lease_attempt": job.lease_attempt,
                "outcome": outcome,
                "image_ref": result.image_ref if result else None,
                "image_digest": result.image_digest if result else None,
                "error": error[:4000] if error else None,
            },
        )
        response.raise_for_status()


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 900,
    check: bool = True,
) -> str:
    if not command:
        raise ValueError("empty command")
    binary = shutil.which(command[0])
    if binary is None:
        raise BuildExecutionError(f"required executable missing: {command[0]}")
    completed = subprocess.run(  # noqa: S603 - argv only; executable is resolved
        [binary, *command[1:]],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )
    output = completed.stdout[-12000:]
    if check and completed.returncode != 0:
        raise BuildExecutionError(
            f"command failed ({command[0]}, exit={completed.returncode}): {output}"
        )
    return output.strip()


def _validate_source_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SourceRejectedError(f"symbolic link rejected: {path.relative_to(root)}")


def _git_environment(home: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _checkout(job: RemoteBuildJob, target: Path, config: WorkerConfig) -> None:
    if not _REPOSITORY.fullmatch(job.repository):
        raise SourceRejectedError("invalid GitHub repository name")
    home = target.parent / "git-home"
    home.mkdir(mode=0o700)
    env = _git_environment(home)
    if config.github_token:
        credential = home / ".git-credentials"
        encoded = quote(config.github_token, safe="")
        credential.write_text(
            f"https://x-access-token:{encoded}@github.com\n",
            encoding="utf-8",
        )
        credential.chmod(0o600)
        _run(["git", "config", "--global", "credential.helper", "store"], env=env)

    target.mkdir()
    _run(["git", "init", "--quiet"], cwd=target, env=env)
    _run(
        ["git", "remote", "add", "origin", f"https://github.com/{job.repository}.git"],
        cwd=target,
        env=env,
    )
    _run(
        ["git", "fetch", "--quiet", "--depth", "1", "origin", job.commit_sha],
        cwd=target,
        env=env,
        timeout=config.command_timeout,
    )
    _run(["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=target, env=env)


def _sandbox_run(name: str, spec: BuildSandboxSpec, config: WorkerConfig) -> None:
    _run(docker_command(name, spec), timeout=config.command_timeout)


def _prepare_python_dependencies(
    source: Path,
    deps: Path,
    job: RemoteBuildJob,
    config: WorkerConfig,
) -> None:
    if not (source / "requirements.txt").exists():
        return
    spec = BuildSandboxSpec(
        image="python:3.12-slim",
        command=(
            "python",
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--disable-pip-version-check",
            "--no-input",
            "--target",
            "/out",
            "-r",
            "/src/requirements.txt",
        ),
        env=sanitized_build_environment(),
        mounts=(
            BuildMount(str(source.resolve()), "/src", read_only=True),
            BuildMount(str(deps.resolve()), "/out", read_only=False),
        ),
        network_name=config.build_network,
        memory_mb=1536,
        cpus=1.5,
        pids=384,
    )
    _sandbox_run(f"sx-build-{job.build_id.hex[:12]}-py", spec, config)


def _prepare_node_dependencies(
    source: Path,
    node_work: Path,
    job: RemoteBuildJob,
    config: WorkerConfig,
) -> None:
    package_json = source / "package.json"
    if not package_json.exists():
        raise SourceRejectedError("discord.js build requires package.json")
    shutil.copy2(package_json, node_work / "package.json")
    package_lock = source / "package-lock.json"
    if package_lock.exists():
        shutil.copy2(package_lock, node_work / "package-lock.json")
        command = ("npm", "ci", "--omit=dev", "--prefix", "/workspace")
    else:
        command = ("npm", "install", "--omit=dev", "--prefix", "/workspace")
    spec = BuildSandboxSpec(
        image="node:22-bookworm-slim",
        command=command,
        env=sanitized_build_environment(
            {"npm_config_audit": "false", "npm_config_fund": "false"}
        ),
        mounts=(BuildMount(str(node_work.resolve()), "/workspace", read_only=False),),
        network_name=config.build_network,
        memory_mb=1536,
        cpus=1.5,
        pids=384,
    )
    _sandbox_run(f"sx-build-{job.build_id.hex[:12]}-js", spec, config)


def _python_entrypoint(source: Path) -> str:
    for candidate in ("main.py", "bot.py", "app.py"):
        if (source / candidate).is_file():
            return candidate
    raise SourceRejectedError("no Python entrypoint found (main.py, bot.py or app.py)")


def _copy_source(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".env",
            ".env.*",
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            "*.pyc",
        ),
    )


def _write_trusted_context(
    source: Path,
    workspace: Path,
    job: RemoteBuildJob,
    deps: Path,
    node_work: Path,
) -> Path:
    context = workspace / "image-context"
    context.mkdir()
    _copy_source(source, context / "src")

    if job.library in {"discordpy", "nextcord", "disnake"}:
        shutil.copytree(deps, context / "deps")
        entrypoint = _python_entrypoint(source)
        dockerfile = (
            "FROM python:3.12-slim\n"
            "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 "
            "PYTHONPATH=/opt/sentrix/deps\n"
            "WORKDIR /app\n"
            "COPY deps /opt/sentrix/deps\n"
            "COPY src /app\n"
            f'CMD ["python", "{entrypoint}"]\n'
        )
    elif job.library == "discordjs":
        modules = node_work / "node_modules"
        if not modules.is_dir():
            raise BuildExecutionError("npm did not produce node_modules")
        shutil.copytree(modules, context / "node_modules", symlinks=True)
        dockerfile = (
            "FROM node:22-bookworm-slim\n"
            "ENV NODE_ENV=production\n"
            "WORKDIR /app\n"
            "COPY src /app\n"
            "COPY node_modules /app/node_modules\n"
            'CMD ["npm", "start", "--silent"]\n'
        )
    else:
        raise SourceRejectedError(f"unsupported Discord library: {job.library}")

    (context / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    return context


def _immutable_ref(tag: str, inspect_output: str) -> BuildResult:
    raw = cast(list[object], json.loads(inspect_output))
    if not isinstance(raw, list):
        raise BuildExecutionError("Docker RepoDigests response is not a list")
    for value in raw:
        if not isinstance(value, str) or "@sha256:" not in value:
            continue
        digest = "sha256:" + value.rsplit("@sha256:", 1)[1]
        if re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            return BuildResult(image_ref=value, image_digest=digest)
    raise BuildExecutionError(f"registry did not return an immutable digest for {tag}")


def execute_build(job: RemoteBuildJob, config: WorkerConfig) -> BuildResult:
    with tempfile.TemporaryDirectory(prefix="sx-build-") as raw:
        workspace = Path(raw)
        source = workspace / "source"
        deps = workspace / "python-deps"
        node_work = workspace / "node-work"
        deps.mkdir()
        node_work.mkdir()

        _checkout(job, source, config)
        _validate_source_tree(source)
        preflight_source(source)

        if job.library in {"discordpy", "nextcord", "disnake"}:
            _prepare_python_dependencies(source, deps, job, config)
        elif job.library == "discordjs":
            _prepare_node_dependencies(source, node_work, job, config)
        else:
            raise SourceRejectedError(f"unsupported Discord library: {job.library}")

        context = _write_trusted_context(source, workspace, job, deps, node_work)
        tag = (
            f"{config.registry_prefix}/sentrix/{job.org_id}/{job.environment_id}:"
            f"{job.commit_sha[:12]}"
        )
        try:
            _run(
                ["docker", "build", "--network=none", "--pull", "-t", tag, "."],
                cwd=context,
                timeout=config.command_timeout,
            )
            _run(["docker", "push", tag], timeout=config.command_timeout)
            inspected = _run(
                ["docker", "inspect", "--format", "{{json .RepoDigests}}", tag]
            )
            return _immutable_ref(tag, inspected)
        finally:
            _run(["docker", "image", "rm", "-f", tag], check=False, timeout=120)


async def _renew_lease(api: ControlApi, job: RemoteBuildJob, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await asyncio.sleep(45)
        if stop.is_set():
            return
        await api.renew(job)


async def process_job(api: ControlApi, job: RemoteBuildJob, config: WorkerConfig) -> None:
    stop = asyncio.Event()
    renewer = asyncio.create_task(_renew_lease(api, job, stop))
    try:
        result = await asyncio.to_thread(execute_build, job, config)
    except (BuildRejected, SourceRejectedError) as exc:
        await api.report(job, outcome="rejected", error=str(exc))
    except (BuildExecutionError, OSError, subprocess.SubprocessError) as exc:
        await api.report(job, outcome="failed", error=str(exc))
    else:
        await api.report(job, outcome="succeeded", result=result)
    finally:
        stop.set()
        renewer.cancel()
        try:
            await renewer
        except asyncio.CancelledError:
            pass


async def run_worker(config: WorkerConfig) -> None:
    api = ControlApi(config)
    try:
        while True:
            job = await api.claim()
            if job is None:
                await asyncio.sleep(config.poll_seconds)
                continue
            await process_job(api, job, config)
    finally:
        await api.close()
