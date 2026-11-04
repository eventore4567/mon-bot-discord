"""Disponibilité et page de récupération du dashboard HA SentriX."""
from __future__ import annotations

import os
import re
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from web import dashboard_ha_proxy_v1 as proxy


def test_navigation_ha_unavailable_is_html_branded_no_cache():
    req = make_mocked_request("GET", "/app", headers={"Accept": "text/html"})
    response = proxy._dashboard_unavailable(req, "ha_leader_unreachable")
    assert response.status == 503
    assert response.content_type == "text/html"
    assert response.headers["Cache-Control"].startswith("no-store")
    assert response.headers["Retry-After"] == "5"
    body = response.text
    assert "Le dashboard se reconnecte" in body
    assert "SentriX" in body
    assert "Réessayer maintenant" in body
    assert "Accès direct de secours" in body
    assert "mon-bot-discord-production-8944.up.railway.app/app" in body
    assert "ha_leader_unreachable" not in body


def test_api_and_auth_fail_closed_with_json_only():
    for method, path in (
        ("GET", "/api/guilds"),
        ("POST", "/api/guilds/123/settings"),
        ("GET", "/oauth/callback"),
        ("GET", "/login"),
        ("GET", "/health"),
    ):
        req = make_mocked_request(method, path, headers={"Accept": "text/html"})
        response = proxy._dashboard_unavailable(req, "ha_peer_unknown")
        assert response.status == 503
        assert response.content_type == "application/json"
        assert "dashboard_temporary_unavailable" in response.text
        assert "ha_peer_unknown" not in response.text


def test_non_html_clients_keep_machine_readable_error():
    req = make_mocked_request("GET", "/app", headers={"Accept": "application/json"})
    assert proxy._dashboard_unavailable(req, "leader_unavailable").content_type == "application/json"


def test_dockerfile_uses_static_ffmpeg_without_apt_disk_exhaustion():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text("utf-8")
    assert "mwader/static-ffmpeg:8.1.2" in dockerfile
    assert "COPY --from=ffmpeg_static /ffmpeg /usr/local/bin/ffmpeg" in dockerfile
    assert "COPY --from=ffmpeg_static /ffprobe /usr/local/bin/ffprobe" in dockerfile
    # ffmpeg ne repasse jamais par apt (>200 paquets, disque Railway saturé). Seule
    # exception, depuis le 04/11/2026 : libopus0, un seul petit paquet sans
    # recommandations, indispensable à la voix (discord.opus.OpusNotLoaded sans lui).
    instructions = "\n".join(l for l in dockerfile.splitlines() if not l.lstrip().startswith("#"))
    installs = re.findall(r"apt-get install[^\n]*", instructions)
    assert installs == ["apt-get install -y --no-install-recommends libopus0 \\"], installs
    assert "ffmpeg" not in " ".join(installs)
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile
