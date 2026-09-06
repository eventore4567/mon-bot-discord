from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from aiohttp import web


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "web" / "dashboard_frontend_freeze_v55.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("dashboard_frontend_freeze_v55_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _stable_html(label: str = "stable") -> str:
    return f'''<!doctype html><html><body data-version="{label}"><script>
async function loadSession(){{return fetch("/api/me");}}
async function loadGuilds(){{return fetch("/api/guilds");}}
async function selectGuild(value){{return fetch(`/api/guilds/${{value}}`);}}
</script></body></html>'''


class _Request:
    def __init__(self, path: str):
        self.path = path


def test_freeze_serves_the_prestart_snapshot_even_after_late_mutation():
    freeze = _load_module()

    async def original(_request):
        return web.Response(text="landing", content_type="text/html")

    dashboard = types.SimpleNamespace(INDEX_HTML=_stable_html("before-cogs"), handle_index=original)
    assert freeze.install(dashboard) is True
    frozen_sha = dashboard._sentrix_frontend_snapshot_sha_v55

    # Simule exactement les finaliseurs tardifs observés en production : ils peuvent encore
    # réécrire la variable globale, mais la route /app ne doit plus relire cette valeur.
    dashboard.INDEX_HTML = "<html><body>BROKEN AFTER COGS</body></html>"

    import asyncio

    response = asyncio.run(dashboard.handle_index(_Request("/app")))
    assert 'data-version="before-cogs"' in response.text
    assert "BROKEN AFTER COGS" not in response.text
    assert response.headers["Cache-Control"].startswith("no-store")
    assert response.headers["X-SentriX-Dashboard"] == "v55-frozen"
    assert response.headers["X-SentriX-Frontend-SHA"] == frozen_sha


def test_freeze_does_not_replace_the_public_landing_page():
    freeze = _load_module()

    async def original(_request):
        return web.Response(text="public landing", content_type="text/html")

    dashboard = types.SimpleNamespace(INDEX_HTML=_stable_html(), handle_index=original)
    assert freeze.install(dashboard) is True

    import asyncio

    response = asyncio.run(dashboard.handle_index(_Request("/")))
    assert response.text == "public landing"


def test_freeze_refuses_a_snapshot_without_the_session_boot_chain():
    freeze = _load_module()

    async def original(_request):
        return web.Response(text="old")

    dashboard = types.SimpleNamespace(INDEX_HTML="<html>incomplete</html>", handle_index=original)
    assert freeze.install(dashboard) is False
    assert dashboard.handle_index is original


def test_product_prestart_hook_freezes_immediately_after_no_store(monkeypatch):
    freeze = _load_module()

    calls = []

    def original_no_store(dashboard):
        calls.append("no-store")
        # Le vrai sentrix_product_update remplace ici le handler avant le bind aiohttp.
        current = dashboard.handle_index

        async def dynamic_handler(request):
            if request.path == "/app":
                return web.Response(text=dashboard.INDEX_HTML, content_type="text/html")
            return await current(request)

        dashboard.handle_index = dynamic_handler

    fake_product = types.SimpleNamespace(_install_no_store_index=original_no_store)
    monkeypatch.setitem(sys.modules, "sentrix_product_update", fake_product)

    assert freeze.install_product_prestart_hook() is True
    assert getattr(fake_product._install_no_store_index, "_sentrix_frontend_freeze_hook_v55", False)

    async def original(_request):
        return web.Response(text="landing")

    dashboard = types.SimpleNamespace(INDEX_HTML=_stable_html("prestart"), handle_index=original)
    fake_product._install_no_store_index(dashboard)
    assert calls == ["no-store"]
    assert getattr(dashboard.handle_index, "_sentrix_frontend_freeze_v55", False)

    dashboard.INDEX_HTML = "<html>late rewrite</html>"

    import asyncio

    response = asyncio.run(dashboard.handle_index(_Request("/app")))
    assert 'data-version="prestart"' in response.text
    assert "late rewrite" not in response.text
