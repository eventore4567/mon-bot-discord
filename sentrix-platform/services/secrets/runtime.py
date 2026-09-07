"""Production wiring for envelope-encrypted SentriX secrets.

The V1 self-hosted deployment uses a 256-bit software KEK supplied only through
``SENTRIX_KMS_MASTER_KEY``. The key itself is never stored in PostgreSQL. A
future cloud KMS adapter can replace this without changing secret envelopes.
"""

from __future__ import annotations

import base64
import os

from services.secrets.crypto import EnvelopeCipher, LocalAesKms


class KmsConfigurationError(RuntimeError):
    """The control plane does not have a usable key-encryption key."""


def _decode_key(raw: str) -> bytes:
    raw = raw.strip()
    try:
        if len(raw) == 64:
            value = bytes.fromhex(raw)
        else:
            value = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, TypeError) as exc:
        raise KmsConfigurationError("SENTRIX_KMS_MASTER_KEY invalide") from exc
    if len(value) != 32:
        raise KmsConfigurationError("SENTRIX_KMS_MASTER_KEY doit contenir 32 octets")
    return value


def cipher_from_env() -> EnvelopeCipher:
    raw = os.environ.get("SENTRIX_KMS_MASTER_KEY", "")
    if not raw:
        raise KmsConfigurationError("SENTRIX_KMS_MASTER_KEY absente")
    return EnvelopeCipher(LocalAesKms(_decode_key(raw)))
