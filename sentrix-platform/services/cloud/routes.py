"""Routes web statiques de SentriX Cloud."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["cloud-ui"])
_HTML = Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@router.get("/cloud", response_class=HTMLResponse, include_in_schema=False)
async def cloud() -> str:
    return _HTML


@router.get("/cloud/", include_in_schema=False)
async def cloud_slash() -> RedirectResponse:
    return RedirectResponse("/cloud", status_code=308)
