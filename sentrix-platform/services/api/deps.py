"""Dependances FastAPI : etat applicatif, session, resolution de l'org courante."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from libs.db import Database
from libs.status_store import StatusStore
from services.api.auth import SessionCodec, SessionError

__all__ = ["AppState", "CurrentUser", "get_state", "require_org", "require_user"]

SESSION_COOKIE = "sentrix_session"


@dataclass
class AppState:
    db: Database
    sessions: SessionCodec
    status_store: StatusStore


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.app_state
    return state


@dataclass(frozen=True)
class CurrentUser:
    id: UUID


async def require_user(
    state: Annotated[AppState, Depends(get_state)],
    sentrix_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Resout l'utilisateur depuis le cookie de session ou l'en-tete Bearer."""
    token = sentrix_session
    if token is None and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")

    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session absente")

    try:
        payload = state.sessions.verify(token)
    except SessionError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    return CurrentUser(id=payload.user_id)


@dataclass(frozen=True)
class OrgContext:
    org_id: UUID
    user_id: UUID
    role: str


async def require_org(
    org_id: UUID,
    state: Annotated[AppState, Depends(get_state)],
    user: Annotated[CurrentUser, Depends(require_user)],
) -> OrgContext:
    """Verifie que l'utilisateur appartient a l'org demandee.

    C'est ce controle qui fait echouer l'attaque n.11 : un jeton valide pour A,
    rejoue sur une ressource de B, ne trouve aucune ligne org_members et repond
    404 - jamais 403, pour ne pas reveler l'existence de l'org.

    La lecture se fait en tenant_tx(org_id), PAS en admin_tx : org_members est
    sous RLS, donc sans contexte tenant la requete leverait 42704 (defaillance
    fermee) au lieu de repondre. Poser le contexte sur l'org demandee est sans
    risque ici : RLS borne la visibilite aux membres de CETTE org, la requete
    est limitee a l'utilisateur courant, et l'absence de ligne interrompt la
    requete avant tout acces aux ressources.
    """
    async with state.db.tenant_tx(org_id) as conn:
        row = await conn.fetchrow(
            "SELECT role FROM org_members WHERE user_id = $1",
            user.id,
        )

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ressource introuvable")

    return OrgContext(org_id=org_id, user_id=user.id, role=row["role"])


def map_pg_error(exc: asyncpg.PostgresError) -> HTTPException:
    """Traduit une erreur PostgreSQL en reponse HTTP sans fuite d'information."""
    code = getattr(exc, "sqlstate", None)
    if code == "23503":  # foreign_key_violation -> parent invisible/inexistant
        return HTTPException(status.HTTP_404_NOT_FOUND, "ressource parente introuvable")
    if code == "23505":  # unique_violation
        return HTTPException(status.HTTP_409_CONFLICT, "ressource deja existante")
    if code == "42501":  # insufficient_privilege (RLS WITH CHECK, GRANT)
        return HTTPException(status.HTTP_403_FORBIDDEN, "operation refusee")
    return HTTPException(status.HTTP_400_BAD_REQUEST, "requete invalide")
