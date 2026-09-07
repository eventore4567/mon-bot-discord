"""Point d'entree du service API (Control Plane)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from libs.db import Database
from libs.status_store import MemoryStatusStore, RedisStatusStore, StatusStore
from services.api.auth import SessionCodec
from services.api.deps import AppState
from services.api.routers import (
    agents,
    auth_routes,
    control,
    hosting,
    hosting_github,
    infra_status,
    instances,
    resources,
    webhooks,
)

__all__ = ["create_app"]

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _render_static_html(name: str, scripts: tuple[str, ...]) -> HTMLResponse:
    html = (_STATIC_DIR / name).read_text(encoding="utf-8")
    html = html.replace(
        "</head>",
        '  <link rel="stylesheet" href="/static/enhancements.css">\n</head>',
        1,
    )
    script_tags = "\n".join(f'  <script src="{src}" defer></script>' for src in scripts)
    html = html.replace("</body>", f"{script_tags}\n</body>", 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def create_app(
    db: Database | None = None,
    sessions: SessionCodec | None = None,
    status_store: StatusStore | None = None,
) -> FastAPI:
    """Fabrique l'application. Les dependances sont injectables pour les tests."""
    injected = db is not None and sessions is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if injected:
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
        title="SentriX Hosting Control Plane",
        description="Provider-neutral application hosting control plane.",
        version="0.5.0",
        lifespan=lifespan,
    )
    if injected:
        assert db is not None and sessions is not None
        app.state.app_state = AppState(
            db=db,
            sessions=sessions,
            status_store=status_store or MemoryStatusStore(),
        )

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # FastAPI's Swagger/ReDoc pages load their official static bundles from
        # jsDelivr. The previous global 'self'-only CSP blocked those scripts,
        # producing the completely blank /docs page seen in production.
        if request.url.path in {"/docs", "/redoc"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
                "script-src 'self' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
                "form-action 'self'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        return response

    # Authentication is intentionally omitted from the public OpenAPI schema.
    # In production SentriX uses its provider-neutral local session endpoint;
    # legacy OAuth compatibility routes stay disabled and invisible.
    app.include_router(auth_routes.router, include_in_schema=False)
    app.include_router(resources.router)
    app.include_router(instances.router)
    app.include_router(agents.router)
    app.include_router(hosting.router)
    app.include_router(hosting_github.router)
    app.include_router(infra_status.router)
    app.include_router(control.router)
    app.include_router(webhooks.router)

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def landing_page() -> HTMLResponse:
        return _render_static_html(
            "index.html",
            ("/static/landing-enhancements.js",),
        )

    @app.get("/app", include_in_schema=False)
    async def dashboard_page() -> HTMLResponse:
        return _render_static_html(
            "app.html",
            (
                "/static/dashboard-enhancements.js",
                "/static/generic-hosting.js",
            ),
        )

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
