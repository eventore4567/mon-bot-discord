"""Le renforcement sécurité doit être chargé par la production, pas par une enveloppe.

Le défaut mesuré le 2026-09-26 sur la chaîne v8 — celle du Procfile — est de
ceux qu'aucun test de source ne pouvait voir : ``+panic``, le verrouillage
d'urgence du serveur, n'existait pas au runtime. La commande était écrite,
``NORMAL_DIRECT_COMMANDS`` l'annonçait, et ``tools/security_runtime_audit.py``
la validait — mais cet audit boote autrement que la production.

La chaîne de causes :

  1. ``cogs/security_runtime_hardening`` n'exposait qu'``install()``, sans
     ``setup()`` : impossible à charger comme extension.
  2. ``install()`` était appelé par l'enveloppe ``load_extension`` posée par
     ``cogs/__init__`` sur ``commands.Bot``.
  3. ``railway_boot`` remplace ``commands.Bot`` par sa classe AutoSharded, et
     ``main.BotAllInOne`` hérite de CELLE-LÀ. L'enveloppe restait donc sur une
     classe que la production n'instancie plus.

Ces tests gardent la sortie de cette dépendance. Ils ne vérifient pas que
l'enveloppe fonctionne : ils vérifient qu'on n'en a plus besoin.
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[1]

#: Modules dont la perte est silencieuse et dont l'effet est une protection.
CRITIQUES = (
    "cogs.security_runtime_hardening",
    "cogs.smart_creation_guard_v47",
    "cogs.owner_sanction_immunity",
)


def _source(module: str) -> str:
    return (RACINE / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8")


@pytest.mark.parametrize("module", CRITIQUES)
def test_le_module_expose_un_setup(module):
    """Sans ``setup()``, discord.py ne peut pas le charger comme extension."""
    arbre = ast.parse(_source(module))
    setups = [n for n in arbre.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "setup"]
    assert setups, f"{module} n'expose pas setup() au niveau du module"


@pytest.mark.parametrize("module", CRITIQUES)
def test_le_module_est_dans_la_liste_des_extensions(module):
    """C'est la seule liste que la chaîne de production lise réellement."""
    import main

    assert module in main.EXTENSIONS, (
        f"{module} n'est pas chargé par la production ; il dépendrait alors de "
        "l'enveloppe load_extension de cogs/__init__, posée sur une classe que "
        "railway_boot a remplacée")


def test_le_renforcement_est_charge_apres_automod():
    """``install()`` rend la main si le cog Automod n'est pas encore là."""
    import main

    assert main.EXTENSIONS.index("cogs.automod") < main.EXTENSIONS.index(
        "cogs.security_runtime_hardening")


def test_panic_reste_reserve_au_proprietaire():
    """Un verrouillage d'urgence ouvert à tous serait une arme, pas une protection."""
    source = _source("cogs.security_runtime_hardening")
    arbre = ast.parse(source)
    trouve = False
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if noeud.name not in ("panic", "panic_off", "panic_status"):
            continue
        trouve = True
        decorateurs = {
            d.func.id if isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
            else d.id if isinstance(d, ast.Name) else ""
            for d in noeud.decorator_list
        }
        assert "critical_security_owner_only" in decorateurs, noeud.name
    assert trouve, "les fonctions panic ont été renommées : test à mettre à jour"


def test_le_module_ne_depend_plus_de_l_enveloppe_pour_exister():
    """``setup()`` doit appeler ``install()``, pas redéfinir sa propre logique.

    Deux chemins d'installation divergeraient : l'un recevrait un correctif que
    l'autre n'aurait pas, et seul l'un des deux protégerait le serveur.
    """
    for module in CRITIQUES:
        arbre = ast.parse(_source(module))
        setup = next(n for n in arbre.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == "setup")
        appels = {n.func.id for n in ast.walk(setup)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "install" in appels, f"{module}.setup() n'appelle pas install()"
