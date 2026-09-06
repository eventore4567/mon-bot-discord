"""cogs/embed_builder.py et sentrix_broadcast_dmall_visual.py ont échoué au
chargement en production (2026-09-06) avec :

    discord.app_commands.errors.CommandLimitReached: maximum number of slash
    commands exceeded 100 globally

slash_command_budget.py existe justement pour empêcher ça : il recompte les
racines slash à chaque ajout et écarte silencieusement celles qui
dépasseraient la limite de 100. Mais son appel final vers le vrai
tree.add_command() de discord.py n'était protégé par aucun try/except — si le
comptage local (_global_roots) diverge ne serait-ce que d'une commande du
compte réel que discord.py utilise en interne (ce qui arrive en production :
railway_boot.py ajoute une vingtaine d'extensions supplémentaires après
main.EXTENSIONS, dans un ordre et avec un état — variables d'environnement,
fonctionnalités activées — qu'un simple bot.load_extension() local ne
reproduit pas), CommandLimitReached remontait telle quelle et faisait échouer
TOUTE l'extension (ExtensionFailed) — donc TOUTES ses commandes, y compris
+embed en préfixe, pas seulement la racine slash en trop.

Ce test simule exactement ce scénario : le comptage local du budget croit
qu'il reste de la place, mais le vrai tree.add_command() de discord.py refuse
quand même. Le budget doit absorber ce refus au lieu de le laisser remonter.
"""
from __future__ import annotations

import os
from unittest.mock import Mock

os.environ.setdefault("DISCORD_TOKEN", "x")

from discord import app_commands  # noqa: E402

from cogs import slash_command_budget  # noqa: E402


def _fake_command(name: str) -> Mock:
    command = Mock(spec=app_commands.Command)
    command.name = name
    return command


def _fake_bot(add_command_side_effect):
    tree = Mock()
    tree.get_commands = Mock(return_value=[])
    tree.remove_command = Mock()
    tree.add_command = Mock(side_effect=add_command_side_effect)
    bot = Mock()
    bot.tree = tree
    bot._sentrix_slash_budget_installed = False
    return bot


def test_une_racine_refusee_par_discord_py_est_absorbee_pas_propagee():
    """Le comptage local dit qu'il y a de la place (get_commands renvoie []),
    mais le vrai add_command refuse quand même — exactement ce qui s'est
    produit en production pour embed_builder."""

    def refuse_toujours(command, **kwargs):
        raise app_commands.CommandLimitReached(None, 100)

    bot = _fake_bot(refuse_toujours)
    slash_command_budget.install(bot)

    # Ne doit RIEN lever : c'est exactement ce qui a fait planter l'extension
    # entière en production.
    result = bot.tree.add_command(_fake_command("embed"))
    assert result is None
    assert "embed" in bot._sentrix_skipped_global_slash


def test_les_ajouts_normaux_continuent_de_fonctionner():
    """Le filet de sécurité ne doit pas empêcher les ajouts qui réussissent
    normalement."""
    added = []

    def accepte(command, **kwargs):
        added.append(command)
        return command

    bot = _fake_bot(accepte)
    slash_command_budget.install(bot)

    result = bot.tree.add_command(_fake_command("ping"))
    assert result is not None
    assert len(added) == 1
    assert bot._sentrix_skipped_global_slash == []


if __name__ == "__main__":
    import unittest

    unittest.main()
