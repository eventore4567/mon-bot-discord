from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENHANCEMENTS = ROOT / "services" / "api" / "static" / "dashboard-enhancements.js"


def test_project_modal_has_explicit_close_fix() -> None:
    text = ENHANCEMENTS.read_text(encoding="utf-8")
    assert 'button.closest("dialog")?.close()' in text
    assert "event.preventDefault()" in text


def test_project_creation_is_reduced_to_one_simple_screen() -> None:
    text = ENHANCEMENTS.read_text(encoding="utf-8")
    assert 'stepper.style.display = "none"' in text
    assert 'botStep.style.display = "none"' in text
    assert 'envStep.style.display = "none"' in text
    assert 'createButton.textContent = "Créer mon bot"' in text


def test_simple_mode_keeps_secure_production_defaults() -> None:
    text = ENHANCEMENTS.read_text(encoding="utf-8")
    assert 'kind.value = "prod"' in text
    assert 'runtime.value = "managed"' in text
    assert 'provider.value = "tmpfs_file"' in text
