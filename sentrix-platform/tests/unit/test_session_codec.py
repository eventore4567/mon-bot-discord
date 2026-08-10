from __future__ import annotations

from uuid import uuid4

import pytest

from services.api.auth import SessionCodec, SessionError


def test_session_round_trip() -> None:
    codec = SessionCodec(b"a" * 48)
    user_id = uuid4()

    payload = codec.verify(codec.issue(user_id))

    assert payload.user_id == user_id
    assert payload.expires_at > 0


def test_session_tampering_is_rejected() -> None:
    codec = SessionCodec(b"a" * 48)
    token = codec.issue(uuid4())
    body, signature = token.split(".", 1)
    replacement = "A" if signature[0] != "A" else "B"
    forged = f"{body}.{replacement}{signature[1:]}"

    with pytest.raises(SessionError, match="signature invalide"):
        codec.verify(forged)


def test_session_signed_by_other_key_is_rejected() -> None:
    issuer = SessionCodec(b"a" * 48)
    verifier = SessionCodec(b"b" * 48)

    with pytest.raises(SessionError, match="signature invalide"):
        verifier.verify(issuer.issue(uuid4()))


def test_expired_session_is_rejected() -> None:
    codec = SessionCodec(b"a" * 48)

    with pytest.raises(SessionError, match="session expiree"):
        codec.verify(codec.issue(uuid4(), ttl=-1))


def test_malformed_session_is_rejected() -> None:
    codec = SessionCodec(b"a" * 48)

    with pytest.raises(SessionError, match="jeton malforme"):
        codec.verify("pas-de-separateur")
