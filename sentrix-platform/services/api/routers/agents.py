"""API P1 privee des node-agents.

Aucune donnee tenant n'est lue directement sans preuve d'affectation. Les
fonctions PostgreSQL SECURITY DEFINER verifient le token du noeud puis exposent
seulement les instances assignees a ce noeud.
"""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from libs.runtime_models import AgentDesiredInstance, AgentReport, AgentRuntimeSecret
from services.api.deps import AppState, get_state
from services.secrets.crypto import SecretEnvelope
from services.secrets.runtime import KmsConfigurationError, cipher_from_env

router = APIRouter(prefix="/v1/agent/nodes/{node_id}", tags=["node-agent"])


def _token_digest(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _auth_error(exc: asyncpg.PostgresError) -> HTTPException:
    if getattr(exc, "sqlstate", None) == "42501":
        return HTTPException(status.HTTP_401_UNAUTHORIZED, "node non autorise")
    return HTTPException(status.HTTP_400_BAD_REQUEST, "rapport agent invalide")


@router.get("/desired", response_model=list[AgentDesiredInstance])
async def desired_state(
    node_id: UUID,
    state: Annotated[AppState, Depends(get_state)],
    node_token: Annotated[str, Header(alias="X-Sentrix-Node-Token", min_length=16, max_length=512)],
) -> list[AgentDesiredInstance]:
    try:
        async with state.db.admin_tx() as conn:
            rows = await conn.fetch(
                "SELECT * FROM public.sentrix_agent_pull($1, $2)",
                node_id,
                _token_digest(node_token),
            )
    except asyncpg.PostgresError as exc:
        raise _auth_error(exc) from exc
    return [AgentDesiredInstance.model_validate(dict(row)) for row in rows]


@router.get(
    "/instances/{instance_id}/secrets",
    response_model=list[AgentRuntimeSecret],
)
async def runtime_secrets(
    node_id: UUID,
    instance_id: UUID,
    response: Response,
    state: Annotated[AppState, Depends(get_state)],
    node_token: Annotated[str, Header(alias="X-Sentrix-Node-Token", min_length=16, max_length=512)],
) -> list[AgentRuntimeSecret]:
    """Materialise les derniers secrets uniquement pour le node assigne.

    La preuve d'affectation pose le contexte RLS local a la transaction. Les
    valeurs en clair ne sont jamais persistees, journalisees ou cachees ici.
    """
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    try:
        cipher = cipher_from_env()
    except KmsConfigurationError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    try:
        async with state.db.admin_tx() as conn:
            environment_id = await conn.fetchval(
                "SELECT public.sentrix_agent_authorize_instance($1, $2, $3)",
                node_id,
                _token_digest(node_token),
                instance_id,
            )
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (name)
                       name, provider, version, ciphertext, wrapped_dek
                  FROM environment_secrets
                 WHERE environment_id = $1
                 ORDER BY name, version DESC
                """,
                environment_id,
            )
    except asyncpg.PostgresError as exc:
        raise _auth_error(exc) from exc

    result: list[AgentRuntimeSecret] = []
    for row in rows:
        envelope = SecretEnvelope(
            ciphertext=bytes(row["ciphertext"]),
            wrapped_dek=bytes(row["wrapped_dek"]),
            version=row["version"],
        )
        plaintext = cipher.decrypt(envelope, environment_id=str(environment_id))
        result.append(
            AgentRuntimeSecret(
                name=row["name"],
                provider=row["provider"],
                version=row["version"],
                value=plaintext.decode("utf-8"),
            )
        )
    return result


@router.post("/report", status_code=status.HTTP_204_NO_CONTENT)
async def report_state(
    node_id: UUID,
    payload: AgentReport,
    state: Annotated[AppState, Depends(get_state)],
    node_token: Annotated[str, Header(alias="X-Sentrix-Node-Token", min_length=16, max_length=512)],
) -> None:
    digest = _token_digest(node_token)
    try:
        async with state.db.admin_tx() as conn:
            for item in payload.statuses:
                await conn.fetchval(
                    """
                    SELECT public.sentrix_agent_report_instance(
                        $1,$2,$3,$4,$5,$6,$7,$8,$9
                    )
                    """,
                    node_id,
                    digest,
                    item.instance_id,
                    item.observed_state,
                    item.container_id,
                    item.generation,
                    item.exit_code,
                    item.health,
                    item.detail,
                )
        await state.status_store.heartbeat(
            node_id,
            {"status": "online", "instances": len(payload.statuses)},
            ttl=30,
        )
    except asyncpg.PostgresError as exc:
        raise _auth_error(exc) from exc
