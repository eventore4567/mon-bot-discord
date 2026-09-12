"""cogs/setup_diagnostics.py — /setupdiag (Milestone 2, Configuration Platform).

Enveloppe fine autour de core/modules/registry.py, avec exactement le même
garde de permission que /setup (cogs.setup_control_center._can_setup,
importé verbatim, jamais réimplémenté). Ces tests vérifient le CÂBLAGE : le
garde est bien appliqué, le panneau reflète fidèlement le registre — la
logique de statut par module est déjà testée séparément dans
tests/test_module_registry.py.

Vérifié par boot réel (voir commit) : classer "setupdiag" dans utils/
access_matrix.py::CATEGORY_COMMANDS["configuration"] (à côté de "setup" —
requis de toute façon par les portes de cohérence des permissions,
tests/test_permission_audit_gates.py notamment, qui refusent une commande
sans classification explicite) lui donne AUTOMATIQUEMENT le même
comportement que /setup pour le portail global (allowed=True, policy=
"discord:manage_guild" pour un membre "Gérer le serveur" sans être
Administrateur) — le portail traite la catégorie, pas le nom littéral
"setup". Aucune modification de la chaîne à 3 niveaux qui décide déjà de
/setup n'a donc été nécessaire. Ces tests couvrent le CÂBLAGE local
(_can_setup, le rendu du panneau) — le portail global lui-même est déjà
testé ailleurs (tests/test_access_tiers_5.py, tests/test_global_checks_
cannot_grant.py, tests/test_permission_audit_gates.py).
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.setup_diagnostics import SetupDiagnostics, _module_line
from core.modules.registry import ModuleDefinition, ModuleStatus
from utils import sentrix_panels as panels


def _fake_ctx(author, guild):
    return SimpleNamespace(guild=guild, author=author, interaction=None, send=AsyncMock())


def test_setupdiag_is_classified_next_to_setup_in_access_matrix():
    """Garde-fou textuel, rapide : si quelqu'un retire un jour "setupdiag" de
    cette liste, les tests réels (tests/test_permission_audit_gates.py, qui
    bootent le vrai bot) le détecteraient de toute façon — celui-ci donne juste
    un signal immédiat sans avoir à booter les 51 extensions."""
    from utils.access_matrix import CATEGORY_COMMANDS

    configuration = CATEGORY_COMMANDS["configuration"]
    assert "setupdiag" in configuration
    assert "setup" in configuration


def test_module_line_shows_green_when_fully_configured():
    ligne = _module_line(ModuleStatus(enabled=True, configured=True, summary="prêt"), "Tickets")
    assert ligne.label.startswith("🟢")
    assert ligne.indice is None


def test_module_line_shows_yellow_with_issue_count_when_enabled_but_not_configured():
    status = ModuleStatus(enabled=True, configured=False, summary="incomplet", issues=("a", "b"))
    ligne = _module_line(status, "Vérification")
    assert ligne.label.startswith("🟡")
    assert ligne.indice == "2 point(s) à corriger"


def test_module_line_shows_grey_when_disabled():
    ligne = _module_line(ModuleStatus(enabled=False, configured=False, summary="inactif"), "AutoMod")
    assert ligne.label.startswith("⚪")


def test_command_denies_and_sends_permission_error_when_can_setup_is_false():
    async def run():
        bot = SimpleNamespace()
        cog = SetupDiagnostics(bot)
        ctx = _fake_ctx(SimpleNamespace(id=1), SimpleNamespace(id=555))

        with patch("cogs.setup_diagnostics._can_setup", new=AsyncMock(return_value=False)), \
             patch("cogs.setup_diagnostics._permission_error", new=AsyncMock()) as perm_error:
            await SetupDiagnostics.setupdiag.callback(cog, ctx)

        perm_error.assert_awaited_once_with(ctx)
        ctx.send.assert_not_called()

    asyncio.run(run())


def test_command_renders_registry_statuses_when_allowed():
    async def run():
        bot = SimpleNamespace()
        cog = SetupDiagnostics(bot)
        ctx = _fake_ctx(SimpleNamespace(id=1), SimpleNamespace(id=555))

        fake_statuses = {
            "tickets": ModuleStatus(enabled=True, configured=True, summary="2 types configurés"),
            "automod": ModuleStatus(enabled=False, configured=False, summary="aucun filtre actif"),
        }
        fake_definitions = (
            ModuleDefinition(key="tickets", label="Tickets", describe=AsyncMock()),
            ModuleDefinition(key="automod", label="AutoMod", describe=AsyncMock()),
        )

        sent = {}

        async def fake_envoyer(target, panneau, **kwargs):
            sent["panneau"] = panneau

        with patch("cogs.setup_diagnostics._can_setup", new=AsyncMock(return_value=True)), \
             patch("cogs.setup_diagnostics.registry.all_statuses", new=AsyncMock(return_value=fake_statuses)), \
             patch("cogs.setup_diagnostics.registry.all_modules", return_value=fake_definitions), \
             patch("cogs.setup_diagnostics.panels.envoyer", new=fake_envoyer):
            await SetupDiagnostics.setupdiag.callback(cog, ctx)

        texte = panels.texte_complet(sent["panneau"])
        assert "Tickets" in texte
        assert "AutoMod" in texte
        assert "2 types configurés" in texte

    asyncio.run(run())


def test_command_reports_zero_issues_when_every_module_is_clean():
    async def run():
        bot = SimpleNamespace()
        cog = SetupDiagnostics(bot)
        ctx = _fake_ctx(SimpleNamespace(id=1), SimpleNamespace(id=555))

        fake_statuses = {"tickets": ModuleStatus(enabled=True, configured=True, summary="prêt")}
        sent = {}

        async def fake_envoyer(target, panneau, **kwargs):
            sent["panneau"] = panneau

        with patch("cogs.setup_diagnostics._can_setup", new=AsyncMock(return_value=True)), \
             patch("cogs.setup_diagnostics.registry.all_statuses", new=AsyncMock(return_value=fake_statuses)), \
             patch("cogs.setup_diagnostics.registry.all_modules", return_value=(
                 ModuleDefinition(key="tickets", label="Tickets", describe=AsyncMock()),
             )), \
             patch("cogs.setup_diagnostics.panels.envoyer", new=fake_envoyer):
            await SetupDiagnostics.setupdiag.callback(cog, ctx)

        assert sent["panneau"].kind == "success"
        assert "1/1" in panels.texte_complet(sent["panneau"])

    asyncio.run(run())
