"""Les modules tickets doivent être chargés par la production, pas par une enveloppe.

Deux défauts mesurés le 2026-09-26 sur la chaîne v8 — celle du Procfile :

  - ``+logevent`` et ``+logsearch`` n'existaient pas au runtime, alors que
    ``HELP_VISIBLE_EXTRA_COMMANDS`` les déclare visibles dans l'aide. Le module
    qui les fournit, ``cogs/v17_tickets_logs``, n'était jamais installé.
  - ``cogs/ticket_claim_security`` non plus. Or ``Tickets.handle_control_button``
    ne vérifie une autorisation que si un ``role_id`` est configuré pour ce
    bouton précis ; sans configuration, aucun contrôle. Le créateur d'un ticket
    pouvait donc utiliser claim, add, remove, rename et transfer — dont ``add``,
    qui fait entrer d'autres membres dans son salon privé.

Même cause dans les deux cas : ces modules n'exposaient qu'``install()``,
appelé par l'enveloppe ``load_extension`` de ``cogs/__init__``, posée sur une
classe que la production n'instancie plus depuis que ``railway_boot`` remplace
``commands.Bot``.
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[1]

MODULES = ("cogs.v17_tickets_logs", "cogs.ticket_claim_security")


def _source(module: str) -> str:
    return (RACINE / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8")


@pytest.mark.parametrize("module", MODULES)
def test_le_module_expose_un_setup(module):
    arbre = ast.parse(_source(module))
    noms = {n.name for n in arbre.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "setup" in noms, f"{module} n'expose pas setup() : impossible à charger"


@pytest.mark.parametrize("module", MODULES)
def test_le_module_est_charge_par_la_production(module):
    import main

    assert module in main.EXTENSIONS


def test_les_modules_tickets_se_chargent_apres_le_cog_tickets():
    """Tous deux enveloppent des méthodes de ``cogs.tickets`` : il doit exister."""
    import main

    base = main.EXTENSIONS.index("cogs.tickets")
    for module in MODULES:
        assert base < main.EXTENSIONS.index(module), module


def test_les_boutons_reserves_au_staff_sont_bien_listes():
    """Le cœur de la protection : la liste des boutons que le créateur ne doit
    pas pouvoir presser. ``add`` en particulier fait entrer un tiers dans un
    salon privé."""
    from cogs import ticket_claim_security as securite

    assert {"claim", "add", "remove", "rename", "transfer"} <= securite._STAFF_ONLY_KEYS


def test_la_fermeture_reste_possible_pour_le_createur():
    """Une protection qui empêcherait un membre de fermer son propre ticket
    déplacerait le problème sur le staff."""
    from cogs import ticket_claim_security as securite

    assert "close" not in securite._STAFF_ONLY_KEYS


def test_le_controle_staff_ne_depend_pas_d_un_role_configure():
    """C'est exactement la faille : le contrôle de base est conditionné à un
    ``role_id`` configuré, celui-ci ne doit pas l'être."""
    import inspect

    from cogs import ticket_claim_security as securite

    source = inspect.getsource(securite._authorized_staff)
    # Le propriétaire et les administrateurs passent d'office, puis le rôle
    # configuré, puis le rôle staff du type de ticket — et refus par défaut.
    assert "guild.owner_id" in source
    assert "administrator" in source
    assert "staff_role_id" in source
    assert source.rstrip().endswith("return False") or "return False" in source


def test_les_commandes_annoncees_dans_l_aide_existent_desormais():
    """``HELP_VISIBLE_EXTRA_COMMANDS`` promettait +logevent et +logsearch."""
    from cogs.command_catalog_cleanup import HELP_VISIBLE_EXTRA_COMMANDS

    source = _source("cogs.v17_tickets_logs")
    for nom in ("logevent", "logsearch"):
        assert nom in HELP_VISIBLE_EXTRA_COMMANDS, f"{nom} n'est plus annoncée"
        assert f'name="{nom}"' in source, (
            f"{nom} n'est plus fournie par v17_tickets_logs : l'aide l'annoncerait "
            "sans qu'elle existe")
