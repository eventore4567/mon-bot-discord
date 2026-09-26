"""La reprise des mises de jeu doit être chargée par la production.

``V17Health.on_ready`` appelle ``_recover_startup_tasks``, qui relance les
boucles de fond tombées pendant le chargement ET règle les mises interrompues
par un redémarrage. Sans lui, une manche de ``+bomb``, ``+lava`` ou
``+rocket`` coupée en plein vol laisse l'argent du joueur réservé
indéfiniment.

Le module n'avait qu'``install()``, suspendu à l'enveloppe de chargement de
``cogs/__init__`` — posée sur une classe que la production n'instancie plus.
Vérifié dans les journaux Railway du 2026-09-26 : la ligne « Reprise des
mises de jeu au démarrage », pourtant journalisée même à zéro précisément
pour prouver son passage, n'apparaissait nulle part.
"""
from __future__ import annotations

import ast
import inspect
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

RACINE = pathlib.Path(__file__).resolve().parents[1]


def test_le_module_expose_un_setup():
    source = (RACINE / "cogs" / "v17_health.py").read_text(encoding="utf-8")
    noms = {n.name for n in ast.parse(source).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "setup" in noms


def test_le_module_est_charge_par_la_production():
    import main

    assert "cogs.v17_health" in main.EXTENSIONS


def test_la_reprise_est_declenchee_par_on_ready():
    """C'est le seul moment où bot.is_ready() est vrai ; appelée plus tôt, la
    fonction sort immédiatement et ne règle rien."""
    from cogs.v17_health import V17Health

    source = inspect.getsource(V17Health.on_ready)
    assert "_recover_startup_tasks" in source


def test_la_reprise_sort_tot_si_le_bot_n_est_pas_pret():
    """Relancer des boucles avant READY les ferait retomber aussitôt."""
    from cogs import v17_health

    source = inspect.getsource(v17_health._recover_startup_tasks)
    assert "bot.is_ready()" in source


def test_le_bilan_est_journalise_meme_a_zero():
    """C'est cette ligne qui prouve dans les journaux du déploiement que la
    reprise a tourné. Sans elle, son silence est indiscernable de son absence
    — et c'est exactement ce qui a caché le défaut pendant si longtemps."""
    from cogs import v17_health

    source = inspect.getsource(v17_health._recover_startup_tasks)
    assert "Reprise des mises de jeu au démarrage" in source
    arbre = ast.parse(__import__("textwrap").dedent(source))
    appels_log = [n for n in ast.walk(arbre)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "info"]
    assert appels_log, "le bilan n'est plus journalisé en INFO"


def test_la_reprise_ne_tourne_qu_une_fois():
    """on_ready peut se déclencher à chaque reconnexion gateway. Rembourser
    deux fois la même mise créerait de l'argent."""
    from cogs import v17_health

    source = inspect.getsource(v17_health._recover_startup_tasks)
    assert "_sentrix_mises_reprises" in source
