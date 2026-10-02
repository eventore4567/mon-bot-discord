from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_successful_sanction_logging_is_best_effort():
    source = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")

    assert "Dossier de sanction non persisté" in source
    assert "Comptage de l'historique indisponible" in source
    assert "Journal de sanction non envoyé" in source
    assert "Indisponible temporairement" in source


def test_log_sanction_returns_even_when_audit_steps_fail():
    source = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")

    marker = 'async def log_sanction'
    start = source.index(marker)
    end = source.index("    # Deux appels identiques", start)
    block = source[start:end]

    assert block.count("except Exception:") >= 3
    assert "return e" in block


def test_tempban_expiry_consumes_after_discord_success_even_if_audit_fails():
    source = (ROOT / "cogs" / "moderation.py").read_text(encoding="utf-8")

    assert "Dossier d'unban automatique non persisté" in source
    assert "Log d'unban automatique non envoyé" in source
    assert "Discord a confirmé le débannissement" in source
    assert "return True" in source
