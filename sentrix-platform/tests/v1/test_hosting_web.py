from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "services" / "api" / "static"
MAIN = ROOT / "services" / "api" / "main.py"
RESOURCES = ROOT / "services" / "api" / "routers" / "resources.py"
AUTH = ROOT / "services" / "api" / "routers" / "auth_routes.py"


def test_hosting_web_assets_are_packaged_with_control_plane() -> None:
    for name in ("index.html", "app.html", "styles.css", "app.js"):
        path = STATIC / name
        assert path.is_file(), name
        assert path.stat().st_size > 500


def test_control_plane_serves_public_site_and_dashboard() -> None:
    text = MAIN.read_text(encoding="utf-8")
    assert 'app.mount("/static"' in text
    assert '@app.get("/", include_in_schema=False)' in text
    assert '@app.get("/app", include_in_schema=False)' in text
    assert 'response.headers["Content-Security-Policy"]' in text


def test_dashboard_is_connected_to_hosting_api_not_mock_data() -> None:
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    required = (
        "/v1/auth/me",
        "/v1/auth/organizations",
        "/hosting/overview",
        "/hosting/builds",
        "/hosting/releases",
        "/hosting/deployments",
        "/hosting/environments/",
        "/hosting/github/refresh",
    )
    for endpoint in required:
        assert endpoint in app
    assert "fetch(path" in app
    assert 'credentials: "same-origin"' in app


def test_dashboard_has_complete_resource_navigation() -> None:
    html = (STATIC / "app.html").read_text(encoding="utf-8")
    for view in (
        "overview",
        "projects",
        "deployments",
        "runtime",
        "observability",
        "secrets",
        "settings",
    ):
        assert f'id="view-{view}"' in html
    assert 'id="project-wizard"' in html
    assert 'id="build-form"' in html


def test_resource_lists_exist_for_dashboard() -> None:
    resources = RESOURCES.read_text(encoding="utf-8")
    assert '@router.get("/bots", response_model=list[BotOut])' in resources
    assert '@router.get("/environments", response_model=list[EnvironmentOut])' in resources


def test_authenticated_organization_list_exists() -> None:
    auth = AUTH.read_text(encoding="utf-8")
    assert '@router.get("/organizations", response_model=list[OrganizationOut])' in auth
    assert "JOIN org_members" in auth
