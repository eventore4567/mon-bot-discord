from __future__ import annotations

from pathlib import Path

from cogs.release_ping_policy_v63 import is_major_update


ROOT = Path(__file__).resolve().parents[1]


def test_small_fixes_never_ping_everyone() -> None:
    samples = (
        "fix(logs): corrige les doublons des salons",
        "Hotfix ticket : correction d'un petit bug",
        "Ajustement du texte de la FAQ",
        "Serveurs SentriX V62 — publier uniquement lors d’un ajout",
        "Correction du fallback utilisateur inconnu",
    )
    for message in samples:
        assert is_major_update(message) is False, message


def test_explicit_major_release_pings() -> None:
    assert is_major_update("[MAJOR] Nouvelle génération SentriX") is True
    assert is_major_update("Grosse mise à jour : nouvelle version majeure de SentriX") is True


def test_multi_system_refactor_can_ping() -> None:
    message = "Refonte SentriX : nouveau système tickets, logs et sécurité"
    assert is_major_update(message) is True


def test_no_ping_marker_always_wins() -> None:
    assert is_major_update("[NO-PING] Mise à jour majeure : refonte complète") is False
    assert is_major_update("[MINOR] [MAJOR] test volontaire") is False


def test_policy_is_installed_after_release_announcer() -> None:
    source = (ROOT / "cogs" / "command_no_emoji_runtime.py").read_text(encoding="utf-8")
    base = source.index("install_release_announcer(bot)")
    policy = source.index("install_release_ping_policy_v63(bot)")
    assert base < policy
