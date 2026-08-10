"""Authentification OAuth2 Discord + session signee.

La session est un jeton signe HMAC-SHA256 (stdlib uniquement, pas de dependance
supplementaire). Format : <payload_b64>.<signature_b64> ou payload contient
user_id et expiration.

Note P0 : le jeton porte l'identite de l'UTILISATEUR, jamais l'org. L'org
courante est resolue a chaque requete depuis org_members, et son appartenance
est verifiee cote serveur - c'est ce qui fait echouer l'attaque n.11 (rejeu du
jeton de A sur une ressource de B).
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

import httpx

__all__ = ["DiscordOAuth", "SessionCodec", "SessionError", "SessionPayload"]

DISCORD_API = "https://discord.com/api/v10"
SESSION_TTL_SECONDS = 7 * 24 * 3600


class SessionError(Exception):
    """Jeton de session absent, malforme, expire ou signature invalide."""


@dataclass(frozen=True)
class SessionPayload:
    user_id: UUID
    expires_at: int


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


class SessionCodec:
    """Encodage/decodage des jetons de session."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("le secret de session doit faire au moins 32 octets")
        self._secret = secret

    def issue(self, user_id: UUID, *, ttl: int = SESSION_TTL_SECONDS) -> str:
        payload = {"uid": str(user_id), "exp": int(time.time()) + ttl}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        body = _b64e(raw)
        sig = hmac.new(self._secret, body.encode("ascii"), sha256).digest()
        return f"{body}.{_b64e(sig)}"

    def verify(self, token: str) -> SessionPayload:
        try:
            body, sig = token.split(".", 1)
        except ValueError as exc:
            raise SessionError("jeton malforme") from exc

        expected = hmac.new(self._secret, body.encode("ascii"), sha256).digest()
        try:
            provided = _b64d(sig)
        except (ValueError, TypeError) as exc:
            raise SessionError("signature illisible") from exc

        # Comparaison a temps constant.
        if not hmac.compare_digest(expected, provided):
            raise SessionError("signature invalide")

        try:
            payload = json.loads(_b64d(body))
            user_id = UUID(payload["uid"])
            expires_at = int(payload["exp"])
        except (ValueError, TypeError, KeyError) as exc:
            raise SessionError("charge utile invalide") from exc

        if expires_at < int(time.time()):
            raise SessionError("session expiree")

        return SessionPayload(user_id=user_id, expires_at=expires_at)

    @classmethod
    def from_env(cls, var: str = "SESSION_SECRET") -> SessionCodec:
        secret = os.environ.get(var)
        if not secret:
            raise RuntimeError(f"variable d'environnement {var} absente")
        return cls(secret.encode("utf-8"))


class DiscordOAuth:
    """Echange de code OAuth2 et lecture du profil."""

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def authorize_url(self, state: str) -> str:
        from urllib.parse import urlencode

        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": "identify email",
            "state": state,
        }
        return f"https://discord.com/oauth2/authorize?{urlencode(params)}"

    async def exchange_code(self, code: str) -> str:
        """Retourne l'access_token Discord."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{DISCORD_API}/oauth2/token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            token: str = response.json()["access_token"]
            return token

    async def fetch_user(self, access_token: str) -> dict[str, str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{DISCORD_API}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            data: dict[str, str] = response.json()
            return data

    @classmethod
    def from_env(cls) -> DiscordOAuth:
        client_id = os.environ.get("DISCORD_CLIENT_ID", "")
        client_secret = os.environ.get("DISCORD_CLIENT_SECRET", "")
        redirect_uri = os.environ.get("DISCORD_REDIRECT_URI", "")
        if not (client_id and client_secret and redirect_uri):
            raise RuntimeError("configuration OAuth Discord incomplete")
        return cls(client_id, client_secret, redirect_uri)
