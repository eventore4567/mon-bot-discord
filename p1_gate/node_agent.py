from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import ipaddress
import json
import os
import subprocess
import tempfile


@dataclass(frozen=True)
class Limits:
    cpus: float = 0.5
    memory_mb: int = 256
    pids: int = 128

    def __post_init__(self):
        if not 0.05 <= self.cpus <= 8:
            raise ValueError("bad cpu limit")
        if not 64 <= self.memory_mb <= 32768:
            raise ValueError("bad memory limit")
        if not 16 <= self.pids <= 4096:
            raise ValueError("bad pid limit")


@dataclass(frozen=True)
class Instance:
    id: str
    org_id: str
    env_id: str
    image: str
    desired_state: str = "running"
    command: tuple[str, ...] = ()
    limits: Limits = Limits()
    revision: int = 1

    @property
    def container_name(self):
        return "sx-" + hashlib.sha256(self.id.encode()).hexdigest()[:24]

    @property
    def network_name(self):
        return "sxnet-" + hashlib.sha256(f"{self.org_id}:{self.env_id}".encode()).hexdigest()[:16]

    def to_dict(self):
        return {
            "id": self.id,
            "org_id": self.org_id,
            "env_id": self.env_id,
            "image": self.image,
            "desired_state": self.desired_state,
            "command": list(self.command),
            "revision": self.revision,
            "limits": {"cpus": self.limits.cpus, "memory_mb": self.limits.memory_mb, "pids": self.limits.pids},
        }

    @classmethod
    def from_dict(cls, raw):
        cmd = raw.get("command") or []
        if isinstance(cmd, str):
            raise ValueError("command must be argv, not shell text")
        lim = raw.get("limits") or {}
        return cls(
            id=str(raw["id"]), org_id=str(raw["org_id"]), env_id=str(raw["env_id"]), image=str(raw["image"]),
            desired_state=str(raw.get("desired_state", "running")), command=tuple(str(x) for x in cmd),
            limits=Limits(float(lim.get("cpus", .5)), int(lim.get("memory_mb", 256)), int(lim.get("pids", 128))),
            revision=int(raw.get("revision", 1)),
        )


class Cache:
    def __init__(self, path):
        self.path = Path(path)

    def save(self, instances):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"version": 1, "instances": [x.to_dict() for x in instances]}, f)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path)
            os.chmod(self.path, 0o600)
        finally:
            try: os.unlink(tmp)
            except FileNotFoundError: pass

    def load(self):
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text())
        if raw.get("version") != 1:
            raise ValueError("bad cache version")
        return [Instance.from_dict(x) for x in raw.get("instances", [])]


class DockerRuntime:
    def __init__(self, node_id, policy_script=None, control_plane_cidrs=(), dns_servers=None):
        self.node_id = node_id
        self.policy_script = policy_script
        self.control_plane_cidrs = tuple(control_plane_cidrs)
        if dns_servers is None:
            dns_servers = tuple(x.strip() for x in os.getenv("SENTRIX_DNS_SERVERS", "1.1.1.1,8.8.8.8").split(",") if x.strip())
        self.dns_servers = tuple(str(ipaddress.ip_address(x)) for x in dns_servers)
        if not self.dns_servers:
            raise ValueError("at least one dns server is required")

    def run(self, argv, check=True):
        p = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and p.returncode:
            raise RuntimeError(p.stderr.strip())
        return p.stdout.strip()

    def check(self):
        raw = self.run(["docker", "info", "--format", "{{json .Runtimes}}"])
        if "runsc" not in json.loads(raw):
            raise RuntimeError("runsc missing")

    def exists(self, item):
        return bool(self.run(["docker", "ps", "-a", "--filter", f"name=^{item.container_name}$", "--format", "{{.Names}}"], False))

    def running(self, item):
        return self.exists(item) and self.run(["docker", "inspect", "-f", "{{.State.Running}}", item.container_name], False) == "true"

    def ensure_network(self, item):
        if not self.run(["docker", "network", "ls", "--filter", f"name=^{item.network_name}$", "--format", "{{.Name}}"], False):
            self.run(["docker", "network", "create", "--driver", "bridge", "--label", "sentrix.managed=true", item.network_name])
        if self.policy_script:
            dns_policy_args = [arg for server in self.dns_servers for arg in ("--dns", server)]
            deny_args = [arg for cidr in self.control_plane_cidrs for arg in ("--deny", cidr)]
            self.run([self.policy_script, "apply", item.network_name, *dns_policy_args, *deny_args])

    def ensure_running(self, item):
        if self.running(item):
            return self.run(["docker", "inspect", "-f", "{{.Id}}", item.container_name])
        if self.exists(item):
            self.run(["docker", "rm", "-f", item.container_name], False)
        self.ensure_network(item)
        mem = f"{item.limits.memory_mb}m"
        dns_args = [arg for server in self.dns_servers for arg in ("--dns", server)]
        return self.run([
            "docker", "run", "-d", "--name", item.container_name, "--runtime=runsc", "--network", item.network_name,
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--pids-limit", str(item.limits.pids),
            "--memory", mem, "--memory-swap", mem, "--cpus", str(item.limits.cpus),
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=67108864",
            *dns_args,
            "--label", "sentrix.managed=true", "--label", f"sentrix.node_id={self.node_id}",
            "--label", f"sentrix.instance_id={item.id}", "--label", f"sentrix.org_id={item.org_id}", item.image, *item.command,
        ])

    def ensure_stopped(self, item):
        if self.exists(item):
            self.run(["docker", "rm", "-f", item.container_name], False)


class Agent:
    def __init__(self, client, cache, runtime):
        self.client, self.cache, self.runtime = client, cache, runtime

    def tick(self):
        online = True
        try:
            desired = self.client.desired_state()
            self.cache.save(desired)
        except OSError:
            online = False
            desired = self.cache.load()
        status = []
        for item in desired:
            if item.desired_state == "running":
                cid = self.runtime.ensure_running(item)
                status.append({"instance_id": item.id, "observed_state": "running", "container_id": cid, "revision": item.revision})
            else:
                self.runtime.ensure_stopped(item)
                status.append({"instance_id": item.id, "observed_state": "stopped", "revision": item.revision})
        if online:
            self.client.report_status(status)
        return online
