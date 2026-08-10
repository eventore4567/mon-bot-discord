from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import tempfile

import pytest

from libs.release_identity import ReleaseIdentity, hash_config
from services.builder_ctl.controller import BuildRejected, BuildCache, cache_lookup, preflight_source, sanitized_build_environment
from services.builder_ctl.models import BuildRequest, BuildSandboxSpec
from services.builder_ctl.sandbox import docker_command
from services.webhook_gw.security import MemoryDeliveryDeduper, WebhookAuthError
from services.webhook_gw.service import accept_push


@pytest.mark.asyncio
async def test_webhook_hmac_and_delivery_dedup() -> None:
    secret = b"webhook-secret"
    body = json.dumps({
        "repository": {"full_name": "owner/repo"},
        "after": "a" * 40,
        "ref": "refs/heads/main",
    }).encode()
    sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    deduper = MemoryDeliveryDeduper()
    first = await accept_push(body=body, signature=sig, delivery_id="d-1", webhook_secret=secret, deduper=deduper)
    assert first is not None and first.commit_sha == "a" * 40
    assert await accept_push(body=body, signature=sig, delivery_id="d-1", webhook_secret=secret, deduper=deduper) is None
    assert await accept_push(body=body, signature=sig, delivery_id="d-1", webhook_secret=secret, deduper=deduper) is None
    with pytest.raises(WebhookAuthError):
        await accept_push(body=body, signature="sha256=00", delivery_id="d-2", webhook_secret=secret, deduper=deduper)


def test_source_scanner_rejects_hardcoded_discord_token_before_build() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "bot.py").write_text('DISCORD_TOKEN="M' + 'A' * 23 + '.AAAAAA.' + 'B' * 30 + '"')
        with pytest.raises(BuildRejected):
            preflight_source(root)


def test_build_environment_is_allowlisted_not_inherited() -> None:
    env = sanitized_build_environment({"PIP_INDEX_URL": "https://pypi.org/simple"})
    assert "DISCORD_TOKEN" not in env
    assert "DATABASE_URL" not in env
    with pytest.raises(ValueError):
        sanitized_build_environment({"DISCORD_TOKEN": "secret"})


def test_build_sandbox_is_disposable_gvisor_and_secret_free() -> None:
    spec = BuildSandboxSpec(
        image="python:3.12-alpine",
        command=("python", "-c", "print('ok')"),
        env=sanitized_build_environment(),
        network_name="none",
    )
    cmd = docker_command("sx-build-abc", spec)
    joined = " ".join(cmd)
    for required in ("--rm", "--runtime=runsc", "--read-only", "--cap-drop=ALL", "--network none"):
        assert required in joined
    for forbidden in ("DISCORD_TOKEN", "DATABASE_URL", "/var/run/docker.sock", "--privileged"):
        assert forbidden not in joined


def test_release_identity_and_cache_are_content_addressed() -> None:
    digest = "sha256:" + "1" * 64
    config = b'{"runtime":"managed"}'
    rid = ReleaseIdentity(digest, hash_config(config), 7)
    assert len(rid.stable_key) == 64
    request = BuildRequest("o", "owner/repo", "a" * 40, "builder:v1")
    cache = BuildCache()
    assert cache_lookup(cache, request) is None
    cache.put(request.cache_key, digest)
    assert cache_lookup(cache, request) == digest
