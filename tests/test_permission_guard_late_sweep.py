"""Core V2, Phase 3 (docs/core-v2-plan.md) : correction du bug vivant confirmé par
l'audit (docs/core-v2-audit-technical-debt.md, §1) — /sentrixpro security (et 13
sous-commandes sœurs) gardait un @commands.has_guild_permissions(manage_guild=True)
local jamais balayé, parce que cogs.sentrix_ultimate charge via railway_boot.py,
après le SEUL passage du nettoyeur (cogs/permission_guard.py::install(), déclenché
une fois par finalize_runtime()). Conséquence réelle : un rôle explicitement
autorisé via Setup pour une commande "sentrixpro *" restait quand même refusé,
puisque discord.py exige que TOUS les checks passent, pas seulement la décision
d'utils/access_matrix.py.

Deux angles de correction, testés séparément ici :
1. Le cas confirmé lui-même : les 14 décorateurs retirés de sentrix_ultimate.py.
2. La cause structurelle : main.py appelle maintenant _strip_redundant_local_checks
   une seconde fois après le chargement complet des 48 extensions, pour que ce
   bug ne puisse plus se reproduire sur un futur cog chargé tardivement."""
from __future__ import annotations

import ast
import os
import pathlib
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from discord.ext import commands

from cogs import permission_guard
from utils import access_matrix

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _predicate_from(decorator):
    """Même technique que tests/test_action_validation.py::_extract."""

    async def target(ctx):
        return True

    decorator(target)
    return target.__commands_checks__[0]


class _FakeCommand:
    def __init__(self, name, checks):
        self.name = name
        self.checks = checks
        self.root_parent = None
        self.app_command = None


class _FakeBot:
    def __init__(self, commands_list):
        self._commands = commands_list

    def walk_commands(self):
        return iter(self._commands)


class SecondSweepCatchesLateLoadedCommandsTests(unittest.TestCase):
    """Preuve directe du mécanisme : une commande dont la racine est déjà connue
    d'access_matrix, mais qui n'existait pas encore lors du premier balayage
    (exactement le scénario d'une extension ajoutée par railway_boot.py), doit
    être nettoyée par un appel ultérieur — c'est ce que main.py fait maintenant
    une seconde fois, après le chargement complet des 48 extensions."""

    def test_balayage_retire_un_check_has_guild_permissions_brut(self):
        known_root = next(iter(access_matrix.KNOWN_COMMANDS))
        predicate = _predicate_from(commands.has_guild_permissions(manage_guild=True))
        late_command = _FakeCommand(known_root, [predicate])
        bot = _FakeBot([late_command])

        removed = permission_guard._strip_redundant_local_checks(bot)

        self.assertEqual(removed, 1)
        self.assertEqual(late_command.checks, [])

    def test_balayage_retire_un_check_has_permissions_brut(self):
        known_root = next(iter(access_matrix.KNOWN_COMMANDS))
        predicate = _predicate_from(commands.has_permissions(manage_guild=True))
        late_command = _FakeCommand(known_root, [predicate])
        bot = _FakeBot([late_command])

        removed = permission_guard._strip_redundant_local_checks(bot)

        self.assertEqual(removed, 1)

    def test_idempotent_un_second_appel_ne_retire_plus_rien(self):
        """main.py appelle cette fonction une seconde fois inconditionnellement —
        elle ne doit jamais rien casser pour tout ce que le premier passage a
        déjà nettoyé."""
        known_root = next(iter(access_matrix.KNOWN_COMMANDS))
        predicate = _predicate_from(commands.has_guild_permissions(manage_guild=True))
        command = _FakeCommand(known_root, [predicate])
        bot = _FakeBot([command])

        first = permission_guard._strip_redundant_local_checks(bot)
        second = permission_guard._strip_redundant_local_checks(bot)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)

    def test_ne_touche_jamais_une_commande_a_racine_inconnue(self):
        """Fail-safe : une racine absente d'access_matrix.KNOWN_COMMANDS n'est
        jamais balayée, même si son check ressemble à de l'autorisation pure."""
        predicate = _predicate_from(commands.has_guild_permissions(manage_guild=True))
        command = _FakeCommand("__commande_totalement_inconnue__", [predicate])
        bot = _FakeBot([command])

        removed = permission_guard._strip_redundant_local_checks(bot)

        self.assertEqual(removed, 0)
        self.assertEqual(len(command.checks), 1)

    def test_main_py_appelle_bien_le_balayage_apres_la_boucle_extensions(self):
        """Verrou anti-régression : si ce second appel disparaît de main.py, ce
        test doit le voir avant qu'un futur cog tardif ne reproduise le bug."""
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        idx_loop = source.index("for ext in EXTENSIONS")
        idx_sweep = source.index("_strip_redundant_local_checks")
        idx_sync = source.index("await self.tree.sync()")
        self.assertLess(idx_loop, idx_sweep, "le balayage doit venir après la boucle de chargement")
        self.assertLess(idx_sweep, idx_sync, "le balayage doit venir avant tree.sync()")


class SentrixUltimateNoRedundantLocalChecksTests(unittest.TestCase):
    """Verrouille le correctif concret : plus aucune sous-commande de
    /sentrixpro ne porte un décorateur d'autorisation local — la décision
    revient entièrement à utils/access_matrix.py, cohérente pour tout le monde
    y compris un rôle autorisé explicitement via Setup."""

    def test_aucune_fonction_du_fichier_ne_garde_has_guild_permissions(self):
        source = (ROOT / "cogs" / "sentrix_ultimate.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                text = ast.unparse(deco)
                if "has_guild_permissions" in text or "has_permissions" in text:
                    offenders.append(node.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
