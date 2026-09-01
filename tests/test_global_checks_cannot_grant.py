"""Les checks globaux ne peuvent que RESTREINDRE, jamais accorder.

discord.py combine tous les checks globaux en ET : chacun doit renvoyer True pour que
la commande s'execute. Un check ne peut donc pas ouvrir un acces que la matrice refuse.
C'est la garantie qui rend les couches historiques inoffensives pour la securite.

Cartographie des 7 checks globaux presents au demarrage :

  _resource_guard        (bot_excellence_runtime)  limitation de debit
  economy_check          (v17_ai_economy_games)    anti-farm economie
  module_permission_check(operations_center)       ACL par role, par module
  _degraded_check        (bot_mastery_runtime)     coupe-circuit apres erreurs
  _command_access_check  (bot_mastery_runtime)     ACL par role, par commande
  bot_check              (feature_systems)         interrupteurs de systemes
  prefix_guard           (command_hardening_v41)   anti double invocation

Trois sources de regles par role coexistent, chacune ecrite par des commandes
differentes et donc reellement utilisee :
  command_role_permissions  <- Setup (matrice canonique)
  module_role_permissions   <- operations_center
  command_access_rules      <- bot_mastery_runtime
Aucune n'est supprimee : elles ne peuvent que refuser, et en retirer une effacerait
des regles configurees par un administrateur.
"""
import ast
import inspect
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

CHECKS_GLOBAUX = [
    ("cogs/bot_excellence_runtime.py", "_resource_guard", "debit"),
    ("cogs/v17_ai_economy_games.py", "economy_check", "debit"),
    ("cogs/operations_center.py", "module_permission_check", "acl"),
    ("cogs/bot_mastery_runtime.py", "_degraded_check", "disponibilite"),
    ("cogs/bot_mastery_runtime.py", "_command_access_check", "acl"),
    ("cogs/feature_systems.py", "bot_check", "interrupteur"),
    ("cogs/command_hardening_v41.py", "prefix_guard", "anti-doublon"),
]


def _function(path: str, name: str):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} introuvable dans {path}")


@pytest.mark.parametrize("path,name,nature", CHECKS_GLOBAUX)
def test_le_check_existe_toujours(path, name, nature):
    assert _function(path, name) is not None


@pytest.mark.parametrize("path,name,nature", CHECKS_GLOBAUX)
def test_aucun_check_global_ne_contourne_la_matrice(path, name, nature):
    """Aucun ne doit appeler evaluate pour ACCORDER un acces en dehors de la matrice."""
    source = ast.unparse(_function(path, name))
    # Un check global n'a pas a decider d'un acces canonique : c'est le role du garde.
    assert "access_matrix.evaluate" not in source, f"{name} redecide l'acces canonique"
    assert "evaluate_command_access" not in source, f"{name} redecide l'acces canonique"


@pytest.mark.parametrize("path,name,nature", CHECKS_GLOBAUX)
def test_un_check_ne_peut_que_refuser(path, name, nature):
    """Un check global renvoie True (laisse passer) ou refuse. Il n'accorde jamais.

    Concretement : renvoyer True ne suffit pas a executer la commande, puisque le garde
    de permissions est lui aussi dans la chaine ET.
    """
    node = _function(path, name)
    source = ast.unparse(node)
    # Il ne doit exister aucun raccourci du style « je renvoie True donc c'est autorise »
    # qui retirerait le garde de la chaine.
    assert "remove_check" not in source, f"{name} retire un check global"
    assert "_checks.clear" not in source
    assert "bot._checks" not in source


def test_le_garde_de_permissions_est_bien_dans_la_chaine():
    from cogs import permission_guard

    source = inspect.getsource(permission_guard.install)
    assert "bot.global_permission_check = prefix_permission_guard" in source
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "self.add_check(self.global_permission_check)" in main_source
    # L'ajout doit avoir lieu APRES le chargement des extensions, sinon l'attribut
    # capture serait l'ancienne implementation et le garde serait inerte.
    assert main_source.index("for ext in EXTENSIONS") < main_source.index(
        "self.add_check(self.global_permission_check)"
    )


def test_les_trois_sources_de_regles_par_role_sont_toutes_ecrites():
    """Aucune n'est morte : en retirer une effacerait des regles d'admin."""
    tables = {
        "command_role_permissions": 0,
        "module_role_permissions": 0,
        "command_access_rules": 0,
    }
    for path in list((ROOT / "cogs").glob("*.py")) + list((ROOT / "web").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for table in tables:
            if f"INSERT INTO {table}" in text or f"INSERT OR REPLACE INTO {table}" in text \
               or f"INSERT OR IGNORE INTO {table}" in text:
                tables[table] += 1
    for table, writers in tables.items():
        assert writers > 0, f"{table} n'a plus aucun ecrivain : regle morte"
