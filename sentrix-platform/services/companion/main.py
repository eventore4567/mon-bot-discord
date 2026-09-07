"""Application SentriX Companion.

Interface d'exploitation separee du dashboard de configuration Discord. Elle
observe le cluster HA, lance SentriX Doctor et expose la disponibilite Rescue.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from services.companion.doctor import SentrixDoctor
from services.companion.models import DoctorReport

_COOKIE_NAME = "sentrix_companion_session"
_SESSION_MESSAGE = b"sentrix-companion-v1"
_HTML = Path(__file__).with_name("index.html").read_text(encoding="utf-8")


class LoginRequest(BaseModel):
    access_key: str


def _access_key() -> str:
    return os.environ.get("COMPANION_ACCESS_TOKEN", "")


def _session_value(access_key: str) -> str:
    return hmac.new(access_key.encode(), _SESSION_MESSAGE, hashlib.sha256).hexdigest()


def _cookie_secure() -> bool:
    return os.environ.get("COMPANION_COOKIE_SECURE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def _is_authorized(request: Request) -> bool:
    key = _access_key()
    if not key:
        return False

    cookie = request.cookies.get(_COOKIE_NAME, "")
    if cookie and hmac.compare_digest(cookie, _session_value(key)):
        return True

    header = request.headers.get("X-Sentrix-Key", "")
    return bool(header and hmac.compare_digest(header, key))


async def require_access(request: Request) -> None:
    if not _access_key():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SentriX Companion n'est pas encore configure.",
        )
    if not _is_authorized(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise",
        )


def create_app(doctor_factory: Callable[[], SentrixDoctor] = SentrixDoctor) -> FastAPI:
    app = FastAPI(title="SentriX Companion", version="1.0.0")

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        """Healthcheck du Companion lui-meme, sans sonder la production."""
        return {"status": "ok"}

    @app.post("/api/login", tags=["auth"])
    async def login(payload: LoginRequest, response: Response) -> dict[str, bool]:
        key = _access_key()
        if not key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="COMPANION_ACCESS_TOKEN absent",
            )
        if not hmac.compare_digest(payload.access_key, key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Cle invalide",
            )
        response.set_cookie(
            _COOKIE_NAME,
            _session_value(key),
            httponly=True,
            secure=_cookie_secure(),
            samesite="strict",
            max_age=12 * 3600,
            path="/",
        )
        return {"ok": True}

    @app.post("/api/logout", tags=["auth"])
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(_COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/session", tags=["auth"])
    async def session(request: Request) -> dict[str, bool]:
        return {
            "authenticated": _is_authorized(request),
            "configured": bool(_access_key()),
        }

    @app.get("/api/doctor", response_model=DoctorReport, tags=["operations"])
    async def doctor(_: None = Depends(require_access)) -> DoctorReport:
        return await doctor_factory().run()

    @app.get("/api/rescue/readiness", tags=["operations"])
    async def rescue_readiness(_: None = Depends(require_access)) -> dict[str, object]:
        report = await doctor_factory().run()
        return {
            "severity": report.severity,
            "rescue": report.rescue.model_dump(),
            "active_incidents": len(report.incidents),
        }

    @app.get("/api/topology", tags=["operations"])
    async def topology(_: None = Depends(require_access)) -> dict[str, object]:
        report = await doctor_factory().run()
        return {
            "primary": report.primary.model_dump(),
            "standby": report.standby.model_dump(),
            "leader_count": report.rescue.leader_count,
            "automatic_failover": report.rescue.automatic_failover,
        }

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        return _HTML

    return app


app = create_app()
