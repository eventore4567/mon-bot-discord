"""Discord OAuth web flow for SentriX Cloud.

The OAuth state is stored only in an HttpOnly cookie and the Discord access
 token is never persisted. The signed SentriX session contains only the global
 user id; tenant membership is re-checked on every tenant request.
"""

from __future__ import annotations

import os
import secrets
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from libs.ids import uuid7
from services.api.auth import DiscordOAuth
from services.api.deps import (
    SESSION_COOKIE,
    AppState,
    CurrentUser,
    get_state,
    require_user,
)

router = APIRouter(tags=["auth"])
_OAUTH_STATE_COOKIE = "sentrix_oauth_state"


def personal_org_id(user_id: UUID) -> UUID:
    """Stable personal tenant id without any cross-tenant membership lookup."""
    return uuid5(NAMESPACE_URL, f"https://sentrix.cloud/personal/{user_id}")


def _cookie_secure() -> bool:
    return os.environ.get("CLOUD_COOKIE_SECURE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _cloud_home() -> str:
    return os.environ.get("CLOUD_HOME_URL", "/cloud")


@router.get("/auth/discord")
async def discord_login() -> RedirectResponse:
    state_value = secrets.token_urlsafe(32)
    oauth = DiscordOAuth.from_env()
    response = RedirectResponse(oauth.authorize_url(state_value), status_code=302)
    response.set_cookie(
        _OAUTH_STATE_COOKIE,
        state_value,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


@router.get("/auth/callback")
async def discord_callback(
    state: Annotated[str, Query(min_length=20, max_length=200)],
    code: Annotated[str, Query(min_length=1, max_length=2048)],
    app_state: Annotated[AppState, Depends(get_state)],
    oauth_state: Annotated[str | None, Cookie(alias=_OAUTH_STATE_COOKIE)] = None,
) -> RedirectResponse:
    if oauth_state is None or not secrets.compare_digest(oauth_state, state):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "etat OAuth invalide")

    oauth = DiscordOAuth.from_env()
    try:
        discord_token = await oauth.exchange_code(code)
        profile = await oauth.fetch_user(discord_token)
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Discord OAuth indisponible") from exc

    discord_user_id = str(profile.get("id", "")).strip()
    if not discord_user_id.isdigit():
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "profil Discord invalide")

    username = str(profile.get("username", "")).strip() or f"discord-{discord_user_id}"
    global_name = str(profile.get("global_name") or "").strip()
    display_name = (global_name or username)[:100]
    email_raw = profile.get("email")
    email = str(email_raw)[:320] if email_raw else None

    candidate_user_id = uuid7()
    async with app_state.db.admin_tx() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (id, discord_user_id, email, display_name, last_login_at)
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (discord_user_id) DO UPDATE SET
                email = EXCLUDED.email,
                display_name = EXCLUDED.display_name,
                last_login_at = now()
            RETURNING id
            """,
            candidate_user_id,
            discord_user_id,
            email,
            display_name,
        )
    if row is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "creation de session impossible")

    user_id: UUID = row["id"]
    org_id = personal_org_id(user_id)
    org_slug = f"discord-{discord_user_id}"
    async with app_state.db.tenant_tx(org_id) as conn:
        await conn.execute(
            """
            INSERT INTO organizations (id, name, slug)
            VALUES ($1, $2, $3)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                updated_at = now()
            """,
            org_id,
            f"{display_name} Cloud",
            org_slug,
        )
        await conn.execute(
            """
            INSERT INTO org_members (org_id, user_id, role)
            VALUES ($1, $2, 'owner')
            ON CONFLICT (org_id, user_id) DO NOTHING
            """,
            org_id,
            user_id,
        )

    response = RedirectResponse(_cloud_home(), status_code=302)
    response.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
    response.set_cookie(
        SESSION_COOKIE,
        app_state.sessions.issue(user_id),
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=7 * 24 * 3600,
        path="/",
    )
    return response


@router.post("/auth/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/cloud", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
    return response


@router.get("/v1/me")
async def me(
    user: Annotated[CurrentUser, Depends(require_user)],
    app_state: Annotated[AppState, Depends(get_state)],
) -> dict[str, object]:
    async with app_state.db.admin_tx() as conn:
        user_row = await conn.fetchrow(
            "SELECT id, discord_user_id, display_name, email FROM users WHERE id = $1",
            user.id,
        )
    if user_row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "utilisateur introuvable")

    org_id = personal_org_id(user.id)
    async with app_state.db.tenant_tx(org_id) as conn:
        org_row = await conn.fetchrow(
            "SELECT id, name, slug, plan, status FROM organizations WHERE id = $1",
            org_id,
        )
        member = await conn.fetchrow(
            "SELECT role FROM org_members WHERE user_id = $1",
            user.id,
        )
    if org_row is None or member is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "organisation personnelle incomplete")

    return {
        "user": dict(user_row),
        "organization": dict(org_row),
        "role": member["role"],
    }
