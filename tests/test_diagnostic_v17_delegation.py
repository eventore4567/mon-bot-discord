"""cogs/final_stability_guard.py::_install_single_v17_diagnostic() décide
réellement quel corps s'exécute pour /diagnostic (et ses alias historiques
/diagnose, /diag) en production : confirmé en traçant __code__.co_filename/
co_firstlineno sur un boot identique à la production (51 extensions) — la
commande garde son cog d'origine (Stats, qui définit son propre /diagnostic
à cogs/stats.py), mais son .callback est remplacé par diagnostic_single, qui
délègue à V17Health.send_report() dès qu'un contexte de guilde et le cog
V17Health sont disponibles, et ne retombe sur le corps d'origine que sinon
(V17Health absent, ou invocation en DM). Aucun test ne verrouillait ce
comportement avant celui-ci : cogs/stats.py::diagnostic et
cogs/final_stability_guard.py::StabilityDiagnostic.diagnostic (un troisième
corps, jamais installé en pratique — voir install()/setup() : il n'est ajouté
que si aucune commande diagnostic/diagnose/diag n'existe déjà) sont tous les
deux du code mort en production tant que V17Health est chargé."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from discord.ext import commands

from cogs import final_stability_guard


class _FakeCtx(commands.Context):
    """Un vrai commands.Context (isinstance compte dans diagnostic_single),
    mais sans passer par le __init__ lourd de discord.py."""

    def __init__(self, *, guild):
        self.guild = guild


class _FakeCommand:
    def __init__(self, callback):
        self.callback = callback


def _make_bot(*, command, health_cog):
    commands_by_name = {"diagnostic": command} if command is not None else {}

    def get_command(name):
        return commands_by_name.get(name)

    def get_cog(name):
        return health_cog if name == "V17Health" else None

    return SimpleNamespace(get_command=get_command, get_cog=get_cog)


class DiagnosticDelegatesToV17HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegue_a_v17_health_en_contexte_de_guilde(self):
        original_calls = []

        async def original_diagnostic(ctx):
            original_calls.append(ctx)
            return "original"

        report_calls = []

        async def send_report(ctx):
            report_calls.append(ctx)
            return "rapport v17"

        command = _FakeCommand(original_diagnostic)
        health = SimpleNamespace(send_report=send_report)
        bot = _make_bot(command=command, health_cog=health)

        installed = final_stability_guard._install_single_v17_diagnostic(bot)
        self.assertTrue(installed)

        ctx = _FakeCtx(guild=SimpleNamespace(id=555))
        result = await command.callback(ctx)

        self.assertEqual(result, "rapport v17")
        self.assertEqual(report_calls, [ctx])
        self.assertEqual(original_calls, [])

    async def test_retombe_sur_le_corps_dorigine_en_dm(self):
        original_calls = []

        async def original_diagnostic(ctx):
            original_calls.append(ctx)
            return "original"

        report_calls = []

        async def send_report(ctx):
            report_calls.append(ctx)
            return "rapport v17"

        command = _FakeCommand(original_diagnostic)
        health = SimpleNamespace(send_report=send_report)
        bot = _make_bot(command=command, health_cog=health)

        final_stability_guard._install_single_v17_diagnostic(bot)

        ctx = _FakeCtx(guild=None)
        result = await command.callback(ctx)

        self.assertEqual(result, "original")
        self.assertEqual(report_calls, [])
        self.assertEqual(original_calls, [ctx])

    async def test_retombe_sur_le_corps_dorigine_si_v17_health_absent(self):
        original_calls = []

        async def original_diagnostic(ctx):
            original_calls.append(ctx)
            return "original"

        command = _FakeCommand(original_diagnostic)
        bot = _make_bot(command=command, health_cog=None)

        installed = final_stability_guard._install_single_v17_diagnostic(bot)
        self.assertFalse(installed)

        ctx = _FakeCtx(guild=SimpleNamespace(id=555))
        result = await command.callback(ctx)

        self.assertEqual(result, "original")
        self.assertEqual(original_calls, [ctx])

    async def test_est_idempotent_sur_reinstallation(self):
        async def original_diagnostic(ctx):
            return "original"

        command = _FakeCommand(original_diagnostic)
        health = SimpleNamespace(send_report=lambda ctx: None)
        bot = _make_bot(command=command, health_cog=health)

        final_stability_guard._install_single_v17_diagnostic(bot)
        installed_callback = command.callback

        again = final_stability_guard._install_single_v17_diagnostic(bot)

        self.assertTrue(again)
        self.assertIs(command.callback, installed_callback)

    async def test_absence_de_commande_diagnostic_ne_leve_rien(self):
        bot = _make_bot(command=None, health_cog=SimpleNamespace(send_report=lambda ctx: None))
        installed = final_stability_guard._install_single_v17_diagnostic(bot)
        self.assertFalse(installed)


if __name__ == "__main__":
    unittest.main()
