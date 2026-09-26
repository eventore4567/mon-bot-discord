"""L'autorité du bouton IA doit être chargée par la production.

``cogs/ai_disable_guard`` se décrit comme « l'autorité unique du réglage
ai_settings.enabled », vérifié à deux niveaux : avant la conversation
naturelle, et dans ``utils.ai_service`` « afin qu'aucune ancienne commande,
aucun runtime ou appel direct ne puisse contourner le réglage ».

Mesuré le 2026-09-26 sur la chaîne v8 : le module n'était pas installé, et
``ai_service.generate_image`` n'était enveloppé par personne — alors que trois
appelants directs du service sont vivants en production (cogs.sentrix_ultimate,
utils.ai_actions, utils.proof_service). Même cause que +panic : install() sans
setup(), suspendu à l'enveloppe morte de cogs/__init__.
"""
from __future__ import annotations

import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

RACINE = pathlib.Path(__file__).resolve().parents[1]


def test_le_module_expose_un_setup():
    source = (RACINE / "cogs" / "ai_disable_guard.py").read_text(encoding="utf-8")
    noms = {n.name for n in ast.parse(source).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "setup" in noms


def test_le_module_est_charge_par_la_production():
    import main

    assert "cogs.ai_disable_guard" in main.EXTENSIONS


def test_la_garde_se_charge_apres_le_cog_ai():
    """install() cherche le cog Ai ; sans lui il doit attendre, ce qui coûte
    une tâche de fond inutile au démarrage."""
    import main

    assert main.EXTENSIONS.index("cogs.ai") < main.EXTENSIONS.index("cogs.ai_disable_guard")


def test_la_garde_couvre_les_deux_appels_du_moteur():
    """Un seul des deux gardés laisserait l'autre chemin ouvert."""
    import inspect

    from cogs import ai_disable_guard

    source = inspect.getsource(ai_disable_guard._install_service_guard)
    assert "ai_service.generate =" in source
    assert "ai_service.generate_image =" in source


def test_la_garde_est_idempotente():
    """Elle est appelée depuis plusieurs chemins historiques ; envelopper deux
    fois ajouterait un appel base par requête IA."""
    import inspect

    from cogs import ai_disable_guard

    source = inspect.getsource(ai_disable_guard._install_service_guard)
    assert source.count("_sentrix_ai_enabled_engine_guard") >= 4, (
        "le marqueur d'idempotence doit être testé ET posé sur les deux fonctions")
