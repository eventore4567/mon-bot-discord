"""Point d'entree du service API (Control Plane)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from libs.db import Database
from libs.status_store import MemoryStatusStore, RedisStatusStore, StatusStore
from services.api.auth import SessionCodec
from services.api.deps import AppState
from services.api.routers import agents, instances, resources

__all__ = ["create_app"]


def create_app(
    db: Database | None = None,
    sessions: SessionCodec | None = None,
    status_store: StatusStore | None = None,
) -> FastAPI:
    """Fabrique l'application. Les dependances sont injectables pour les tests.

    IMPORTANT : quand db et sessions sont fournis, l'etat est pose IMMEDIATEMENT,
    sans attendre le lifespan. httpx.ASGITransport n'execute pas les evenements
    de lifespan : si l'etat n'etait construit que la, chaque test echouerait sur
    un AttributeError a la premiere requete.
    """
    injected = db is not None and sessions is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if injected:
            # Dependances deja posees ci-dessous : leur cycle de vie appartient
            # a l'appelant (la fixture de test), pas a l'application.
            yield
            return

        database = db or Database(os.environ["DATABASE_URL"])
        codec = sessions or SessionCodec.from_env()
        await database.connect()
        store = status_store or RedisStatusStore(os.environ["REDIS_URL"])
        app.state.app_state = AppState(db=database, sessions=codec, status_store=store)
        try:
            yield
        finally:
            if db is None:
                await database.close()
            if status_store is None:
                await store.close()

    app = FastAPI(
        title="SentriX Platform - Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )
    if injected:
        assert db is not None and sessions is not None
        app.state.app_state = AppState(
            db=db, sessions=sessions, status_store=status_store or MemoryStatusStore()
        )

    app.include_router(resources.router)
    app.include_router(instances.router)
    app.include_router(agents.router)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
