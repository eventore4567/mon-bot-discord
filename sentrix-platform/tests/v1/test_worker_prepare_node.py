from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
PREPARE_NODE = ROOT / "ops" / "worker" / "prepare_node.py"
CLOUD_INIT = ROOT / "ops" / "worker" / "cloud-init.yaml"
PLACEHOLDERS = (
    "__SENTRIX_CONTROL_PLANE_URL__",
    "__SENTRIX_CONTROL_PLANE_CIDRS__",
    "__SENTRIX_NODE_ID__",
    "__SENTRIX_NODE_TOKEN__",
    "__SENTRIX_REPO_URL__",
    "__SENTRIX_REPO_REF__",
)


def _renderer() -> Callable[..., str]:
    namespace = runpy.run_path(str(PREPARE_NODE))
    return cast(Callable[..., str], namespace["render_cloud_init"])


def test_render_cloud_init_shell_quotes_operator_values() -> None:
    render = _renderer()
    rendered = render(
        CLOUD_INIT.read_text(encoding="utf-8"),
        control_plane_url="https://control.example.invalid/",
        control_plane_cidrs="203.0.113.10/32,198.51.100.0/24",
        node_id=UUID("01920000-0000-7000-8000-000000000123"),
        node_token="node-token-with-safe-generated-characters",
        repo_url="https://example.invalid/repo.git?x=1&echo injected",
        repo_ref="feature/test ref",
    )

    assert all(placeholder not in rendered for placeholder in PLACEHOLDERS)
    assert "SENTRIX_CONTROL_PLANE_URL=https://control.example.invalid" in rendered
    assert "SENTRIX_REPO_URL='https://example.invalid/repo.git?x=1&echo injected'" in rendered
    assert "SENTRIX_REPO_REF='feature/test ref'" in rendered
    assert "SENTRIX_NODE_TOKEN=node-token-with-safe-generated-characters" in rendered


def test_render_cloud_init_quotes_empty_cidr_list() -> None:
    render = _renderer()
    rendered = render(
        CLOUD_INIT.read_text(encoding="utf-8"),
        control_plane_url="https://control.example.invalid",
        control_plane_cidrs="",
        node_id=UUID("01920000-0000-7000-8000-000000000124"),
        node_token="another-generated-node-token-value",
        repo_url="https://example.invalid/repo.git",
        repo_ref="main",
    )
    assert "SENTRIX_CONTROL_PLANE_CIDRS=''" in rendered
