from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aiohttp import web

from web import brand_avatar_v39


class _Dashboard:
    @staticmethod
    def _public_url(_request):
        return "https://sentrix.example"

    @staticmethod
    def _invite_url(_bot):
        return "https://discord.com/oauth2/authorize?client_id=123&scope=bot"


async def _call(path: str):
    request = SimpleNamespace(
        path=path,
        method="GET",
        app={"dashboard_module": _Dashboard, "bot": object()},
    )
    called = {"handler": False}

    async def handler(_request):
        called["handler"] = True
        return web.Response(text="DASHBOARD", content_type="text/html")

    response = await brand_avatar_v39.public_home_middleware(request, handler)
    return response, called


def test_root_is_intercepted_before_any_dashboard_index_wrapper():
    response, called = asyncio.run(_call("/"))
    assert response.status == 200
    assert called["handler"] is False
    assert "Votre serveur Discord." in response.text
    assert "product-shell" in response.text
    assert response.headers["X-SentriX-Surface"] == "public-home-v3"
    assert "no-store" in response.headers["Cache-Control"]


def test_home_alias_is_intercepted_as_public_landing():
    response, called = asyncio.run(_call("/home"))
    assert response.status == 200
    assert called["handler"] is False
    assert "product-shell" in response.text
    assert response.headers["X-SentriX-Surface"] == "public-home-v3"


def test_app_still_reaches_the_dashboard_handler():
    response, called = asyncio.run(_call("/app"))
    assert called["handler"] is True
    assert response.text == "DASHBOARD"


def test_brand_install_registers_public_middleware_after_meta_middleware():
    import inspect

    source = inspect.getsource(brand_avatar_v39.install)
    meta = source.index("app.middlewares.append(brand_meta_middleware)")
    public = source.index("app.middlewares.append(public_home_middleware)")
    assert meta < public
    assert 'app["dashboard_module"] = dashboard' in source
