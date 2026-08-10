"""Envelope encryption primitives for P5.

Production uses a cloud/HSM-backed KMS adapter. ``LocalAesKms`` exists only for
local development and tests; it still uses authenticated AES-256-GCM and never
stores a plaintext DEK inside a SecretEnvelope.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Kms(Protocol):
    def wrap_key(self, plaintext_key: bytes, *, aad: bytes) -> bytes: ...
    def unwrap_key(self, wrapped_key: bytes, *, aad: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SecretEnvelope:
    ciphertext: bytes
    wrapped_dek: bytes
    version: int


class LocalAesKms:
    """Development-only KEK adapter."""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != 32:
            raise ValueError("LocalAesKms requires a 32-byte key")
        self._aead = AESGCM(master_key)

    def wrap_key(self, plaintext_key: bytes, *, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, plaintext_key, aad)

    def unwrap_key(self, wrapped_key: bytes, *, aad: bytes) -> bytes:
        if len(wrapped_key) < 13:
            raise ValueError("invalid wrapped key")
        return self._aead.decrypt(wrapped_key[:12], wrapped_key[12:], aad)


class EnvelopeCipher:
    def __init__(self, kms: Kms) -> None:
        self._kms = kms

    def encrypt(self, plaintext: bytes, *, environment_id: str, version: int) -> SecretEnvelope:
        if version < 1:
            raise ValueError("secret version starts at 1")
        aad = f"sentrix:{environment_id}:v{version}".encode()
        dek = os.urandom(32)
        data_aead = AESGCM(dek)
        nonce = os.urandom(12)
        ciphertext = nonce + data_aead.encrypt(nonce, plaintext, aad)
        wrapped = self._kms.wrap_key(dek, aad=aad)
        return SecretEnvelope(ciphertext, wrapped, version)

    def decrypt(self, envelope: SecretEnvelope, *, environment_id: str) -> bytes:
        aad = f"sentrix:{environment_id}:v{envelope.version}".encode()
        dek = self._kms.unwrap_key(envelope.wrapped_dek, aad=aad)
        if len(envelope.ciphertext) < 13:
            raise ValueError("invalid ciphertext")
        return AESGCM(dek).decrypt(envelope.ciphertext[:12], envelope.ciphertext[12:], aad)
