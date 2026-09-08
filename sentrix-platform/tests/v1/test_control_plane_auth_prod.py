from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from libs.status_store import MemoryStatusStore
from services.api.auth import SessionCodec
from services.api.main import create_app


class _UnusedDb:
    """OAuth login/state tests fail before touching PostgreSQL."""


@pytest.fixture
def oauth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_CLIENT_ID", "123456789")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "discord-secret-for-tests")
    monkeypatch.setenv(
        "DISCORD_REDIRECT_URI",
        "https://control.example/v1/auth/discord/callback",
    )
    monkeypatch.setenv("SENTRIX_COOKIE_SECURE", "true")


@pytest.mark.asyncio
async def test_discord_login_sets_secure_httponly_state_cookie(oauth_env: None) -> None:
    app = create_app(
        db=_UnusedDb(),  # type: ignore[arg-type]
        sessions=SessionCodec(b"s" * 48),
        status_store=MemoryStatusStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://control.example",
        follow_redirects=False,
    ) as client:
        response = await client.get("/v1/auth/discord/login")

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://discord.com/oauth2/authorize?")
    query = parse_qs(urlsplit(location).query)
    assert len(query["state"][0]) >= 32
    cookie = response.headers["set-cookie"].lower()
    assert "sentrix_oauth_state=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


@pytest.mark.asyncio
async def test_discord_callback_rejects_state_mismatch_before_network(oauth_env: None) -> None:
    app = create_app(
        db=_UnusedDb(),  # type: ignore[arg-type]
        sessions=SessionCodec(b"s" * 48),
        status_store=MemoryStatusStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://control.example",
        follow_redirects=False,
    ) as client:
        login = await client.get("/v1/auth/discord/login")
        state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
        response = await client.get(
            "/v1/auth/discord/callback",
            params={"code": "unused", "state": state + "x"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "etat OAuth invalide ou expire"


@pytest.mark.asyncio
async def test_logout_expires_session_cookie(oauth_env: None) -> None:
    app = create_app(
        db=_UnusedDb(),  # type: ignore[arg-type]
        sessions=SessionCodec(b"s" * 48),
        status_store=MemoryStatusStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://control.example") as client:
        response = await client.post("/v1/auth/logout")

    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert "sentrix_session=" in cookie
    assert "max-age=0" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
