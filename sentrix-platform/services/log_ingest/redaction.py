"""Secret redaction before durable log storage."""

from __future__ import annotations

import base64
from urllib.parse import quote


class SecretRedactor:
    def __init__(self, secrets: list[bytes]) -> None:
        variants: set[bytes] = set()
        for secret in secrets:
            if len(secret) < 6:
                continue
            variants.add(secret)
            variants.add(base64.b64encode(secret))
            variants.add(quote(secret.decode(errors="ignore"), safe="").encode())
        self._variants = sorted(variants, key=len, reverse=True)

    def redact(self, line: bytes) -> bytes:
        out = line
        for value in self._variants:
            if value:
                out = out.replace(value, b"[REDACTED]")
        return out
