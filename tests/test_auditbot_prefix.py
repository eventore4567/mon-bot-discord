"""+auditbot : un seul diagnostic non destructif en préfixe après retrait de '+'."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import prefix_deprecation as retired
from cogs.auditbot import AuditReport, _check_registered_commands, _user_can_audit
from utils import access_matrix, slash_catalog


def test_prefix_only_auditbot_allowed_not_rest():
    ctx = SimpleNamespace(
        interaction=None,
        command=SimpleNamespace(qualified_name="auditbot"),
    )
    assert not retired.prefixe_actif()
    assert retired._auditbot_allowed(ctx)
    for name in ("ban", "clear", "dm", "setup", "health"):
        assert not retired._auditbot_allowed(
            SimpleNamespace(interaction=None, command=SimpleNamespace(qualified_name=name))
        )
    assert not retired._auditbot_allowed(
        SimpleNamespace(interaction=object(), command=ctx.command)
    )


def test_audit_is_admin_only_and_not_a_slash_command():
    assert access_matrix.access_tier("auditbot") == "discord:administrator"
    assert not any(entry.source == "auditbot" for entry in slash_catalog.CATALOG)


def test_owner_or_admin_authorization_is_scoped():
    guild = SimpleNamespace(owner_id=42)
    def ctx(identifier, administrator=False):
        return SimpleNamespace(
            guild=guild, author=SimpleNamespace(
                id=identifier,
                guild_permissions=SimpleNamespace(administrator=administrator),
            ),
        )
    assert _user_can_audit(ctx(42))
    assert _user_can_audit(ctx(50, True))
    assert not _user_can_audit(ctx(50, False))


def test_report_prioritizes_critical_issues_and_has_remediation():
    report = AuditReport(123)
    report.count("Commandes inspectées", 400)
    report.add("AVERTISSEMENT", "Salon", "Bienvenue", "Non configuré.", "Configurer /setup.")
    report.add("CRITIQUE", "Base", "Connexion", "Lecture indisponible.", "Vérifier Railway.")
    data = report.markdown()
    assert data.index("[CRITIQUE]") < data.index("[AVERTISSEMENT]")
    assert "Aucune commande de modération" in data or "aucune commande" in data.lower()
    assert "À faire : Vérifier Railway." in data
    assert "Commandes inspectées: 400" in data
    assert "1 critique" in report.summary()


def test_command_inspection_never_invokes_the_callback():
    called = []
    def dangerous(*args):
        called.append("executed")
    cmd = SimpleNamespace(qualified_name="ban", callback=dangerous)
    class Tree:
        def walk_commands(self):
            return []
    bot = SimpleNamespace(
        walk_commands=lambda: [cmd],
        tree=Tree(), extensions={},
        module_supervisor=None,
        get_cog=lambda *_: None,
    )
    report = AuditReport(123)
    _check_registered_commands(bot, report)
    assert not called
    assert report.counts["Commandes préfixées inspectées"] == 1


def test_report_does_not_include_secrets_or_message_history():
    report = AuditReport(123)
    assert "token" in report.markdown().lower()  # explanation, not token values
    assert "messages" in report.markdown().lower()
    assert "bot.get_channel" not in report.markdown()
