from __future__ import annotations

import base64
import os
from pathlib import Path
import tempfile
from urllib.parse import quote

import pytest

from services.alerting.discord import Alert
from services.log_ingest.pipeline import LogPipeline, MemoryLogSink
from services.log_ingest.quota import OrgLogQuota
from services.log_ingest.redaction import SecretRedactor
from services.metering.models import UsageSample
from services.secrets.crypto import EnvelopeCipher, LocalAesKms
from services.secrets.service import SecretService, TmpfsSecretSpec, provider_exposure, write_tmpfs_secret


def service() -> SecretService:
    return SecretService(EnvelopeCipher(LocalAesKms(b"k" * 32)))


def test_secret_is_envelope_encrypted_write_only_and_audited() -> None:
    secrets = service()
    plaintext = b"super-sensitive-discord-token"
    stored = secrets.put("env1", "DISCORD_TOKEN", plaintext, provider="tmpfs_file")
    assert plaintext not in stored.envelope.ciphertext
    assert plaintext not in stored.envelope.wrapped_dek
    public = stored.public_view()
    assert public["value"] is None
    assert "ciphertext" not in public and "wrapped_dek" not in public
    assert secrets.materialize("env1", "DISCORD_TOKEN", actor="node-agent") == plaintext
    assert [x["action"] for x in secrets.audit] == ["secret.put", "secret.access"]


def test_rotation_increments_version_without_reexposing_value() -> None:
    secrets = service()
    one = secrets.put("env1", "DISCORD_TOKEN", b"token-one-secret", provider="env")
    two = secrets.put("env1", "DISCORD_TOKEN", b"token-two-secret", provider="tmpfs_file")
    assert (one.envelope.version, two.envelope.version) == (1, 2)
    assert two.public_view()["value"] is None
    assert secrets.materialize("env1", "DISCORD_TOKEN", actor="node") == b"token-two-secret"


def test_tmpfs_file_has_owner_only_permissions_and_no_env_contract() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        path = write_tmpfs_secret(root, TmpfsSecretSpec("/run/secrets/discord_token"), b"abc123-secret")
        assert path.read_bytes() == b"abc123-secret"
        assert os.stat(path).st_mode & 0o777 == 0o400
    assert provider_exposure("tmpfs_file").startswith("low:")
    assert provider_exposure("env").startswith("high:")


def test_log_pipeline_redacts_raw_base64_and_urlencoded_secret() -> None:
    secret = b"Abc+/very-secret-token"
    redactor = SecretRedactor([secret])
    sink = MemoryLogSink()
    pipe = LogPipeline(OrgLogQuota(bytes_per_window=10000), sink)
    lines = [
        b"raw=" + secret,
        b"b64=" + base64.b64encode(secret),
        b"url=" + quote(secret.decode(), safe="").encode(),
    ]
    for i, line in enumerate(lines):
        assert pipe.ingest("org", line, now=float(i), redactor=redactor)
    stored = b"\n".join(line for _org, line in sink.rows)
    assert secret not in stored
    assert base64.b64encode(secret) not in stored
    assert quote(secret.decode(), safe="").encode() not in stored
    assert stored.count(b"[REDACTED]") == 3


def test_log_flood_is_tenant_scoped_and_does_not_drop_neighbor() -> None:
    quota = OrgLogQuota(bytes_per_window=10, window_seconds=60)
    sink = MemoryLogSink()
    pipe = LogPipeline(quota, sink)
    redactor = SecretRedactor([])
    assert pipe.ingest("A", b"1234567890", now=0, redactor=redactor)
    assert not pipe.ingest("A", b"X", now=1, redactor=redactor)
    assert pipe.ingest("B", b"neighbor", now=1, redactor=redactor)
    assert pipe.dropped_bytes["A"] == 1
    assert "B" not in pipe.dropped_bytes


def test_usage_samples_and_discord_alerts_are_safe() -> None:
    sample = UsageSample("o", "e", 1, 2, 3, 4, 5)
    sample.validate()
    with pytest.raises(ValueError):
        UsageSample("o", "e", 1, -1, 0, 0, 0).validate()
    payload = Alert("identify_budget_low", "Budget bas", "reste 7", "env").payload()
    assert payload["allowed_mentions"] == {"parse": []}
