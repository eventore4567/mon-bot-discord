from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENHANCEMENTS = ROOT / "services" / "api" / "static" / "dashboard-enhancements.js"
GENERIC = ROOT / "services" / "api" / "static" / "generic-hosting.js"


def test_project_modal_has_explicit_close_fix() -> None:
    text = ENHANCEMENTS.read_text(encoding="utf-8")
    assert 'button.closest("dialog")?.close()' in text
    assert "event.preventDefault()" in text


def test_project_creation_is_reduced_to_one_simple_screen() -> None:
    text = ENHANCEMENTS.read_text(encoding="utf-8")
    assert 'stepper.style.display = "none"' in text
    assert 'serviceStep.style.display = "none"' in text
    assert 'envStep.style.display = "none"' in text
    assert 'createButton.textContent = "Créer le service"' in text


def test_simple_mode_keeps_secure_generic_defaults() -> None:
    text = ENHANCEMENTS.read_text(encoding="utf-8")
    assert 'kind.value = "prod"' in text
    assert 'runtime.value = "generic"' in text
    assert 'provider.value = "tmpfs_file"' in text
    assert '<option value="python">Python</option>' in text
    assert '<option value="node">Node.js</option>' in text
    assert '<option value="docker">Dockerfile</option>' in text


def test_dashboard_uses_local_login_instead_of_discord() -> None:
    text = GENERIC.read_text(encoding="utf-8")
    assert 'fetch("/v1/auth/login"' in text
    assert "Aucun compte Discord ni OAuth requis" in text
