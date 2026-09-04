"""Recovery V54 doit utiliser le build_app courant au moment du démarrage.

Sur Railway, web/__init__.py installe Recovery V54 avant que sitecustomize ajoute le
proxy HA. Si Recovery capture une ancienne référence de build_app, /login est servi par
le PRIMARY passif au lieu d'être proxyfié vers le leader Discord.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from web import dashboard_recovery_v54 as recovery


class _Router:
    def __init__(self):
        self._paths = set()

    def routes(self):
        return []

    def add_get(self, path, _handler):
        self._paths.add(path)


class _App(dict):
    def __init__(self):
        super().__init__()
        self.router = _Router()


class _Runner:
    def __init__(self, app):
        self.app = app

    async def setup(self):
        return None

    async def cleanup(self):
        return None


class _Site:
    def __init__(self, _runner, _host, _port):
        pass

    async def start(self):
        return None


def test_recovery_uses_build_app_installed_after_recovery(monkeypatch):
    calls = []

    async def original_start(_bot):
        return None

    dashboard = SimpleNamespace(
        build_app=lambda _bot: (_ for _ in ()).throw(AssertionError("ancien build_app utilisé")),
        start_dashboard=original_start,
        _oauth_ready=lambda _bot: True,
    )

    recovery.install(dashboard)

    def late_ha_build(_bot):
        calls.append("late-wrapper")
        return _App()

    # Simule exactement sitecustomize : le proxy HA remplace build_app APRES Recovery V54.
    dashboard.build_app = late_ha_build

    monkeypatch.setattr(recovery.web, "AppRunner", _Runner)
    monkeypatch.setattr(recovery.web, "TCPSite", _Site)

    bot = SimpleNamespace(_sentrix_dashboard_runner_v54=None)
    asyncio.run(dashboard.start_dashboard(bot))

    assert calls == ["late-wrapper"]
    assert bot._sentrix_dashboard_mode_v54 == "complet"
