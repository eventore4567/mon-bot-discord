from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "services" / "api" / "main.py"
AUTH = ROOT / "services" / "api" / "routers" / "auth_routes.py"
LANDING = ROOT / "services" / "api" / "static" / "index.html"
GENERIC = ROOT / "services" / "api" / "static" / "generic-hosting.js"
MIGRATION = ROOT / "migrations" / "0024_generic_hosting.sql"


def test_docs_csp_allows_fastapi_swagger_assets() -> None:
    text = MAIN.read_text(encoding="utf-8")
    assert 'request.url.path in {"/docs", "/redoc"}' in text
    assert "https://cdn.jsdelivr.net" in text


def test_production_can_authenticate_without_discord() -> None:
    text = AUTH.read_text(encoding="utf-8")
    assert 'SENTRIX_AUTH_MODE' in text
    assert '@router.post("/login"' in text
    assert 'SENTRIX_ADMIN_PASSWORD' in text
    assert 'auth_subject = f"local:{expected_user}"' in text


def test_public_experience_is_provider_neutral() -> None:
    landing = LANDING.read_text(encoding="utf-8")
    generic = GENERIC.read_text(encoding="utf-8")
    assert "Aucun compte Discord n'est nécessaire" in landing
    assert 'href="/app">Dashboard</a>' in landing
    assert '/v1/auth/discord/login' not in landing
    assert 'fetch("/v1/auth/login"' in generic


def test_generic_runtimes_are_enabled_in_schema_migration() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    assert "'python'" in text
    assert "'node'" in text
    assert "'docker'" in text
    assert "auth_subject" in text
