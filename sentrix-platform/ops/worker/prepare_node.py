#!/usr/bin/env python3
"""Register a SentriX Hosting worker and render its private cloud-init.

This is an operator tool, not a tenant API. It requires a privileged PostgreSQL
DSN able to insert into the global ``nodes`` table. The plaintext node token is
written only inside the requested 0600 cloud-init file; PostgreSQL stores its
SHA-256 digest.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
import shlex
from pathlib import Path
from uuid import UUID

import asyncpg

from libs.ids import uuid7

DEFAULT_CELL_ID = UUID("01920000-0000-7000-8000-000000000001")
TEMPLATE = Path(__file__).with_name("cloud-init.yaml")


def render_cloud_init(
    template: str,
    *,
    control_plane_url: str,
    control_plane_cidrs: str,
    node_id: UUID,
    node_token: str,
    repo_url: str,
    repo_ref: str,
) -> str:
    """Render only shell-quoted values into EnvironmentFile-style assignments."""
    replacements = {
        "__SENTRIX_CONTROL_PLANE_URL__": shlex.quote(control_plane_url.rstrip("/")),
        "__SENTRIX_CONTROL_PLANE_CIDRS__": shlex.quote(control_plane_cidrs),
        "__SENTRIX_NODE_ID__": shlex.quote(str(node_id)),
        "__SENTRIX_NODE_TOKEN__": shlex.quote(node_token),
        "__SENTRIX_REPO_URL__": shlex.quote(repo_url),
        "__SENTRIX_REPO_REF__": shlex.quote(repo_ref),
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    unresolved = [placeholder for placeholder in replacements if placeholder in rendered]
    if unresolved:
        raise RuntimeError("cloud-init template still contains unresolved placeholders")
    return rendered


def _render_worker_file(
    args: argparse.Namespace,
    node_id: UUID,
    node_token: str,
) -> tuple[Path, str]:
    """Perform local path/template work outside the async database loop."""
    template = TEMPLATE.read_text(encoding="utf-8")
    rendered = render_cloud_init(
        template,
        control_plane_url=args.control_plane_url,
        control_plane_cidrs=args.control_plane_cidrs,
        node_id=node_id,
        node_token=node_token,
        repo_url=args.repo_url,
        repo_ref=args.repo_ref,
    )
    output = Path(args.output).expanduser().resolve()
    return output, rendered


def _write_private_output(output: Path, rendered: str) -> None:
    """Create the credential file atomically and never overwrite an old token."""
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd: int | None = None
    created = False
    try:
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            handle.write(rendered)
    except FileExistsError as exc:
        raise RuntimeError(
            "--output already exists; refusing to overwrite a node credential"
        ) from exc
    except Exception:
        if fd is not None:
            os.close(fd)
        if created:
            output.unlink(missing_ok=True)
        raise


async def prepare(args: argparse.Namespace) -> tuple[UUID, Path]:
    if not args.control_plane_url.startswith("https://"):
        raise RuntimeError("--control-plane-url must use HTTPS")
    if not args.repo_url:
        raise RuntimeError("--repo-url is required")
    if not args.repo_ref:
        raise RuntimeError("--repo-ref is required")

    node_id = uuid7()
    node_token = secrets.token_urlsafe(48)
    token_digest = hashlib.sha256(node_token.encode()).digest()
    output, rendered = await asyncio.to_thread(
        _render_worker_file,
        args,
        node_id,
        node_token,
    )

    conn = await asyncpg.connect(args.database_url)
    inserted = False
    try:
        cell = await conn.fetchval(
            "SELECT id FROM cells WHERE id = $1 AND status = 'active'",
            args.cell_id,
        )
        if cell is None:
            raise RuntimeError(f"active cell not found: {args.cell_id}")

        await conn.execute(
            """
            INSERT INTO nodes (id, cell_id, name, agent_token_sha256, status)
            VALUES ($1, $2, $3, $4, 'active')
            """,
            node_id,
            args.cell_id,
            args.name,
            token_digest,
        )
        inserted = True

        try:
            await asyncio.to_thread(_write_private_output, output, rendered)
        except Exception:
            await conn.execute("DELETE FROM nodes WHERE id = $1", node_id)
            inserted = False
            raise
    finally:
        await conn.close()

    if not inserted:
        raise RuntimeError("node registration did not complete")
    return node_id, output


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Prepare a SentriX Hosting worker")
    result.add_argument("--database-url", default=os.environ.get("SENTRIX_ADMIN_DATABASE_URL"))
    result.add_argument("--name", required=True, help="Unique worker name, e.g. worker-eu-01")
    result.add_argument("--cell-id", type=UUID, default=DEFAULT_CELL_ID)
    result.add_argument("--control-plane-url", required=True)
    result.add_argument("--control-plane-cidrs", default="")
    result.add_argument("--repo-url", required=True)
    result.add_argument("--repo-ref", required=True)
    result.add_argument("--output", required=True, help="Private rendered cloud-init path")
    return result


def main() -> None:
    args = parser().parse_args()
    if not args.database_url:
        raise SystemExit("SENTRIX_ADMIN_DATABASE_URL or --database-url is required")
    try:
        node_id, output = asyncio.run(prepare(args))
    except (asyncpg.PostgresError, OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"worker preparation failed: {type(exc).__name__}") from exc

    print(f"node_id={node_id}")
    print(f"cloud_init={output}")
    print("The node token exists only in that 0600 cloud-init file; keep it private.")


if __name__ == "__main__":
    main()
