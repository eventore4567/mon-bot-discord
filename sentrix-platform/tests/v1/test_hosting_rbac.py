from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from libs.ids import uuid7
from services.api.deps import OrgContext, require_org_admin
from services.api.routers import hosting, hosting_github


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_hosting_admin_guard_accepts_privileged_roles(role: str) -> None:
    ctx = OrgContext(org_id=uuid7(), user_id=uuid7(), role=role)
    assert await require_org_admin(ctx) is ctx


@pytest.mark.asyncio
async def test_hosting_admin_guard_rejects_member() -> None:
    ctx = OrgContext(org_id=uuid7(), user_id=uuid7(), role="member")
    with pytest.raises(HTTPException) as exc:
        await require_org_admin(ctx)
    assert exc.value.status_code == 403


def test_all_hosting_mutations_use_admin_dependency() -> None:
    source = inspect.getsource(hosting)
    for function_name in ("queue_build", "queue_deployment", "runtime_action"):
        start = source.index(f"async def {function_name}(")
        section = source[start : start + 700]
        assert "Depends(require_org_admin)" in section, function_name


def test_secret_metadata_and_github_refresh_are_admin_only() -> None:
    hosting_source = inspect.getsource(hosting)
    start = hosting_source.index("async def list_secret_metadata(")
    assert "Depends(require_org_admin)" in hosting_source[start : start + 500]

    github_source = inspect.getsource(hosting_github)
    start = github_source.index("async def refresh_github_targets(")
    assert "Depends(require_org_admin)" in github_source[start : start + 500]
