from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLOUD_INIT = ROOT / "ops" / "worker" / "cloud-init.yaml"
PREFLIGHT = ROOT / "ops" / "worker" / "preflight.sh"
SYSTEMD = ROOT / "ops" / "worker" / "sentrix-node-agent.service"
BUILDER_SYSTEMD = ROOT / "ops" / "worker" / "sentrix-builder.service"
BUILDER_MAIN = ROOT / "services" / "builder_ctl" / "main.py"


def test_cloud_init_keeps_credentials_as_placeholders() -> None:
    text = CLOUD_INIT.read_text(encoding="utf-8")
    for placeholder in (
        "__SENTRIX_CONTROL_PLANE_URL__",
        "__SENTRIX_NODE_ID__",
        "__SENTRIX_NODE_TOKEN__",
        "__SENTRIX_REPO_URL__",
        "__SENTRIX_REPO_REF__",
    ):
        assert placeholder in text
    assert "curl | sh" not in text
    assert 'permissions: "0600"' in text


def test_cloud_init_installs_and_smoke_tests_gvisor() -> None:
    text = CLOUD_INIT.read_text(encoding="utf-8")
    assert "https://gvisor.dev/archive.key" in text
    assert "apt-get install -y --no-install-recommends" in text
    assert "runsc install" in text
    assert "docker run --rm --runtime=runsc hello-world" in text
    assert "systemctl enable --now sentrix-node-agent.service" in text


def test_preflight_fails_closed_without_egress_enforcement() -> None:
    text = PREFLIGHT.read_text(encoding="utf-8")
    assert "iptables -S DOCKER-USER" in text
    assert "Docker runtime 'runsc' is not registered" in text
    assert "SENTRIX_EGRESS_SCRIPT" in text


def test_preflight_distinguishes_builder_from_runtime_node() -> None:
    text = PREFLIGHT.read_text(encoding="utf-8")
    assert "SENTRIX_CONTROL_WORKER_ID" in text
    assert "SENTRIX_CONTROL_WORKER_TOKEN" in text
    assert "SENTRIX_API_URL is missing" in text
    assert "SENTRIX_REGISTRY_PREFIX is missing" in text
    assert "SENTRIX_NODE_TOKEN must be at least 16 chars" in text
    assert "sentrix-build-" in text


def test_systemd_runs_preflight_before_agent() -> None:
    text = SYSTEMD.read_text(encoding="utf-8")
    assert "ExecStartPre=/opt/sentrix-platform/ops/worker/preflight.sh" in text
    assert "ExecStart=/opt/sentrix-platform/.venv/bin/python -m agents.node_agent.main" in text
    assert "NoNewPrivileges=true" in text
    assert "ProtectKernelModules=true" in text


def test_builder_service_and_entrypoint_prepare_managed_network() -> None:
    service = BUILDER_SYSTEMD.read_text(encoding="utf-8")
    main = BUILDER_MAIN.read_text(encoding="utf-8")
    assert "Environment=SENTRIX_BUILD_NETWORK=sentrix-build-egress" in service
    assert "Environment=SENTRIX_EGRESS_SCRIPT=" in service
    assert "ExecStartPre=/opt/sentrix-platform/ops/worker/preflight.sh" in service
    assert "prepare_from_env()" in main
    assert "WorkerConfig.from_env()" in main
    assert main.index("prepare_from_env()") < main.index("WorkerConfig.from_env()")
