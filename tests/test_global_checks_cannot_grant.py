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
    """install() s'enregistre lui-même (bot.add_check()) au lieu de compter sur
    main.py pour ramasser l'attribut d'instance après coup — corrige
    docs/core-v2-audit-technical-debt.md §6 (le garde ne fonctionnait qu'en
    fonction d'un ordre d'exécution accidentel entre permission_guard.install()
    et main.py::setup_hook()). main.py garde un repli conditionnel : il n'ajoute
    sa propre implémentation que si permission_guard n'a jamais chargé, pour
    qu'aucune commande préfixée ne se retrouve jamais sans aucun garde."""
    from cogs import permission_guard

    source = inspect.getsource(permission_guard.install)
    assert "bot.global_permission_check = prefix_permission_guard" in source
    assert "bot.add_check(prefix_permission_guard)" in source
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "self.add_check(self.global_permission_check)" in main_source
    assert '_sentrix_permission_guard", False)' in main_source


def test_installer_le_garde_lenregistre_immediatement_comme_check_reel():
    """Test comportemental (pas seulement textuel) : juste après install(), le
    check doit déjà être dans bot._checks — sans dépendre d'un appel ultérieur
    de main.py::setup_hook(). Aucune boucle asyncio en cours ici (test sync),
    donc install() saute juste sa vérification fail-closed optionnelle
    (protégée par un try/except RuntimeError autour de get_running_loop())."""
    import discord
    from discord.ext import commands

    from cogs import permission_guard

    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())
    permission_guard.install(bot)

    assert any(
        getattr(check, "_sentrix_permission_guard", False) for check in bot._checks
    ), "le garde de permissions doit déjà être un check réel juste après install()"


def test_le_repli_de_main_py_ne_double_enregistre_jamais_le_garde():
    """Reproduit exactement le repli conditionnel de main.py::setup_hook() (voir
    test_le_garde_de_permissions_est_bien_dans_la_chaine pour la vérification que
    ce repli existe bien dans le vrai fichier) : une fois permission_guard.install()
    passé, le garde ne doit jamais être ajouté une seconde fois — sinon chaque
    commande préfixée évaluerait la matrice d'accès deux fois par invocation."""
    import discord
    from discord.ext import commands

    from cogs import permission_guard

    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())
    permission_guard.install(bot)

    if not getattr(bot.global_permission_check, "_sentrix_permission_guard", False):
        bot.add_check(bot.global_permission_check)

    count = sum(1 for check in bot._checks if getattr(check, "_sentrix_permission_guard", False))
    assert count == 1


def test_le_repli_de_main_py_sactive_si_permission_guard_na_jamais_charge():
    """Si l'extension cogs.permission_guard échoue à charger (jamais None,
    jamais installée), le repli de main.py doit tout de même enregistrer UN
    garde — sans lui, aucune commande préfixée n'aurait plus de vérification
    de permission du tout."""
    import discord
    from discord.ext import commands

    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

    async def fallback_check(ctx):
        return True

    bot.global_permission_check = fallback_check  # jamais réaffecté par permission_guard.install()

    if not getattr(bot.global_permission_check, "_sentrix_permission_guard", False):
        bot.add_check(bot.global_permission_check)

    assert fallback_check in bot._checks


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
