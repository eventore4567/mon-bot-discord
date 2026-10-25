"""La politique sensible ne doit pas être auditée contre elle-même.

Tests de mutations volontaires : les attentes viennent d'un contrat distinct
de utils.access_matrix, même si un bug modifie à la fois access_tier/evaluate.
"""
from tools import audit_permissions as audit


def test_sensitive_policy_is_valid_for_existing_commands(capsys):
    names = [
        "setup", "ban", "kick", "clear", "wipe-server",
        "server-restore", "config-reset", "reset-economy",
        "bl", "sync", "season start", "season end",
    ]
    assert audit.auditer(names) == 0, capsys.readouterr().out


def test_ban_accidentally_public_fails_independent_audit(monkeypatch, capsys):
    monkeypatch.setattr(
        audit.M, "PUBLIC_COMMANDS", audit.M.PUBLIC_COMMANDS | {"ban"},
    )
    assert audit.auditer(["ban"]) == 1
    assert "NIVEAU SENSIBLE INCORRECT" in capsys.readouterr().out


def test_wipe_server_not_owner_only_fails_independent_audit(monkeypatch, capsys):
    monkeypatch.setattr(
        audit.M, "GUILD_OWNER_COMMANDS",
        audit.M.GUILD_OWNER_COMMANDS - {"wipe-server"},
    )
    assert audit.auditer(["wipe-server"]) == 1
    output = capsys.readouterr().out
    assert "NIVEAU SENSIBLE INCORRECT" in output
    assert "ESCALADE SENSIBLE ADMIN" in output


def test_sensitive_subcommand_cannot_silently_inherit_public_root(monkeypatch, capsys):
    rules = dict(audit.M.SUBCOMMAND_TIERS)
    rules.pop("season start")
    monkeypatch.setattr(audit.M, "SUBCOMMAND_TIERS", rules)
    assert audit.auditer(["season start"]) == 1
    assert "NIVEAU SENSIBLE INCORRECT" in capsys.readouterr().out


def test_global_owner_command_exposure_is_detected(monkeypatch, capsys):
    monkeypatch.setattr(audit.M, "OWNER_ONLY_COMMANDS", audit.M.OWNER_ONLY_COMMANDS - {"sync"})
    monkeypatch.setattr(audit.M, "PUBLIC_COMMANDS", audit.M.PUBLIC_COMMANDS | {"sync"})
    assert audit.auditer(["sync"]) == 1
    output = capsys.readouterr().out
    assert "NIVEAU SENSIBLE INCORRECT" in output
