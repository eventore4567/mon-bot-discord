"""La revue de securite ne doit pas consulter uniquement les attentes de la matrice.

Un regression qui declare 'ban' publique modifie a la fois access_tier et
evaluate. L'audit precedent annoncait donc zero anomalie. Ces tests injectent
volontairement des politiques incorrectes et exigent qu'elles soient detectees.
"""
from __future__ import annotations

from tools import audit_permissions as audit


def test_audit_sensible_politique_normale(capsys):
    noms = ["ban", "kick", "setup", "wipe-server", "sync", "season start"]
    assert audit.auditer(noms) == 0, capsys.readouterr().out


def test_audit_detecte_ban_devenu_public(monkeypatch, capsys):
    monkeypatch.setattr(audit.M, "PUBLIC_COMMANDS", audit.M.PUBLIC_COMMANDS | {"ban"})
    assert audit.auditer(["ban"]) == 1
    assert "NIVEAU SENSIBLE INCORRECT" in capsys.readouterr().out


def test_audit_detecte_wipe_server_reclasse_admin(monkeypatch, capsys):
    monkeypatch.setattr(
        audit.M, "GUILD_OWNER_COMMANDS",
        audit.M.GUILD_OWNER_COMMANDS - {"wipe-server"},
    )
    assert audit.auditer(["wipe-server"]) == 1
    sortie = capsys.readouterr().out
    assert "NIVEAU SENSIBLE INCORRECT" in sortie
    assert "ESCALADE SENSIBLE ADMIN" in sortie


def test_audit_detecte_sous_commande_sensible_devenue_publique(monkeypatch, capsys):
    regles = dict(audit.M.SUBCOMMAND_TIERS)
    regles.pop("season start")
    monkeypatch.setattr(audit.M, "SUBCOMMAND_TIERS", regles)
    assert audit.auditer(["season start"]) == 1
    assert "NIVEAU SENSIBLE INCORRECT" in capsys.readouterr().out
