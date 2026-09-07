"""Discord OAuth entrypoints and first-organization onboarding for Hosting V1."""

from __future__ import annotations

import hmac
import os
import secrets
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from libs import audit
from libs.ids import uuid7
from services.api.auth import DiscordOAuth
from services.api.deps import AppState, CurrentUser, get_state, require_user

router = APIRouter(prefix="/v1/auth", tags=["auth"])

OAUTH_STATE_COOKIE = "sentrix_oauth_state"
SESSION_COOKIE = "sentrix_session"
OAUTH_STATE_TTL = 10 * 60
SESSION_TTL = 7 * 24 * 3600


def _cookie_secure() -> bool:
    return os.environ.get("SENTRIX_COOKIE_SECURE", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _cookie_domain() -> str | None:
    value = os.environ.get("SENTRIX_COOKIE_DOMAIN", "").strip()
    return value or None


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


class AuthMeOut(BaseModel):
    id: UUID
    discord_user_id: str
    email: str | None = None
    display_name: str


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,47}$")


class OrganizationOut(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str


@router.get("/discord/login")
async def discord_login() -> RedirectResponse:
    """Start Discord OAuth with a short-lived, HttpOnly CSRF state cookie."""
    state = secrets.token_urlsafe(32)
    oauth = DiscordOAuth.from_env()
    response = RedirectResponse(oauth.authorize_url(state), status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=OAUTH_STATE_TTL,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        domain=_cookie_domain(),
        path="/v1/auth/discord",
    )
    return response


@router.get("/discord/callback")
async def discord_callback(
    request: Request,
    state_app: Annotated[AppState, Depends(get_state)],
    code: Annotated[str, Query(min_length=1, max_length=4096)],
    state: Annotated[str, Query(min_length=16, max_length=256)],
    state_cookie: Annotated[str | None, Cookie(alias=OAUTH_STATE_COOKIE)] = None,
) -> RedirectResponse:
    """Verify OAuth state, upsert the global user and issue a signed session cookie."""
    if state_cookie is None or not hmac.compare_digest(state_cookie, state):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "etat OAuth invalide ou expire")

    oauth = DiscordOAuth.from_env()
    try:
        access_token = await oauth.exchange_code(code)
        profile = await oauth.fetch_user(access_token)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "connexion Discord impossible") from exc

    discord_id = str(profile.get("id") or "").strip()
    if not discord_id.isdecimal() or len(discord_id) > 32:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "profil Discord invalide")
    email = str(profile.get("email") or "").strip() or None
    display_name = str(
        profile.get("global_name") or profile.get("username") or f"Discord {discord_id}"
    ).strip()[:100]

    user_id = uuid7()
    try:
        async with state_app.db.admin_tx() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (
                    id, discord_user_id, email, display_name, last_login_at
                ) VALUES ($1, $2, $3, $4, now())
                ON CONFLICT (discord_user_id)
                DO UPDATE SET
                    email = EXCLUDED.email,
                    display_name = EXCLUDED.display_name,
                    last_login_at = now()
                RETURNING id
                """,
                user_id,
                discord_id,
                email,
                display_name,
            )
    except asyncpg.PostgresError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "session indisponible") from exc
    assert row is not None
    user_id = UUID(str(row["id"]))

    token = state_app.sessions.issue(user_id, ttl=SESSION_TTL)
    destination = os.environ.get("SENTRIX_APP_URL", "/app").strip() or "/app"
    response = RedirectResponse(destination, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        domain=_cookie_domain(),
        path="/",
    )
    response.delete_cookie(
        OAUTH_STATE_COOKIE,
        domain=_cookie_domain(),
        path="/v1/auth/discord",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/me", response_model=AuthMeOut)
async def auth_me(
    user: Annotated[CurrentUser, Depends(require_user)],
    state_app: Annotated[AppState, Depends(get_state)],
) -> AuthMeOut:
    async with state_app.db.admin_tx() as conn:
        row = await conn.fetchrow(
            "SELECT id, discord_user_id, email, display_name FROM users WHERE id = $1",
            user.id,
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "utilisateur introuvable")
    return AuthMeOut.model_validate(dict(row))


@router.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(
    user: Annotated[CurrentUser, Depends(require_user)],
    state_app: Annotated[AppState, Depends(get_state)],
) -> list[OrganizationOut]:
    """List organizations visible to the signed-in user before an org is selected."""
    async with state_app.db.admin_tx() as conn:
        rows = await conn.fetch(
            "SELECT * FROM public.sentrix_list_user_organizations($1)",
            user.id,
        )
    return [OrganizationOut.model_validate(dict(row)) for row in rows]


@router.post(
    "/organizations",
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_first_organization(
    payload: OrganizationCreate,
    request: Request,
    user: Annotated[CurrentUser, Depends(require_user)],
    state_app: Annotated[AppState, Depends(get_state)],
) -> OrganizationOut:
    """Create an organization and atomically make the authenticated user its owner."""
    org_id = uuid7()
    try:
        async with state_app.db.tenant_tx(org_id) as conn:
            await conn.execute(
                "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3)",
                org_id,
                payload.name.strip(),
                payload.slug,
            )
            await conn.execute(
                "INSERT INTO org_members (org_id, user_id, role) VALUES ($1, $2, 'owner')",
                org_id,
                user.id,
            )
            await audit.record(
                conn,
                org_id=org_id,
                actor_user_id=user.id,
                action="organization.create",
                target_type="organization",
                target_id=org_id,
                metadata={"slug": payload.slug},
                source_ip=_client_ip(request),
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "slug deja utilise") from exc
    except asyncpg.PostgresError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "creation impossible") from exc

    return OrganizationOut(id=org_id, name=payload.name.strip(), slug=payload.slug, role="owner")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        SESSION_COOKIE,
        domain=_cookie_domain(),
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )
    return response
