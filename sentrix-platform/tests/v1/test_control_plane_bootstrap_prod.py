from __future__ import annotations

from pathlib import Path

import pytest

from ops.bootstrap.production_control_plane import BootstrapError, database_dsn, role_dsn

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "ops" / "bootstrap" / "production_control_plane.py"
DOCKERFILE = ROOT / "Dockerfile"


def test_database_dsn_preserves_superuser_credentials_verbatim() -> None:
    source = "postgresql://postgres:p%40ss@postgres.internal:5432/railway?sslmode=require"
    assert database_dsn(source, database="sentrix_platform") == (
        "postgresql://postgres:p%40ss@postgres.internal:5432/sentrix_platform?sslmode=require"
    )


def test_role_dsn_encodes_generated_credentials_and_switches_database() -> None:
    source = "postgresql://postgres:root@postgres.internal:5432/railway?sslmode=require"
    rendered = role_dsn(
        source,
        username="sentrix_app",
        password="a/b:c@d?e#f" + "x" * 32,
        database="sentrix_platform",
    )
    assert rendered.startswith("postgresql://sentrix_app:")
    assert "a%2Fb%3Ac%40d%3Fe%23f" in rendered
    assert "@postgres.internal:5432/sentrix_platform?sslmode=require" in rendered


@pytest.mark.parametrize("source", ["", "https://db.example/x", "postgresql:///missing-host"])
def test_bootstrap_dsn_helpers_fail_closed_on_invalid_source(source: str) -> None:
    with pytest.raises(BootstrapError):
        database_dsn(source, database="sentrix_platform")


def test_bootstrap_contains_no_development_database_passwords() -> None:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    assert "migrator_dev_only" not in text
    assert "app_dev_only" not in text
    assert "admin_dev_only" not in text
    assert "NOBYPASSRLS NOSUPERUSER" in text
    assert "os.environ.pop(name, None)" in text
    assert 'os.environ["DATABASE_URL"] = app_dsn' in text


def test_control_plane_image_contains_migrations_and_uses_secure_bootstrap() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY migrations ./migrations" in text
    assert "COPY ops ./ops" in text
    assert 'CMD ["python", "ops/bootstrap/production_control_plane.py"]' in text
