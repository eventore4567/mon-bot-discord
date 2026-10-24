"""« postgres_primary » n'est pas un échec de sauvegarde.

Relevé dans les journaux de production du 23/10 :

    [WARNING] Snapshot ticket non stocké : {'stored': False, 'reason': 'postgres_primary'}

Depuis la bascule PostgreSQL, `durable_database.snapshot()` saute volontairement
l'instantané SQLite : les données vivent dans Postgres, et réécrire le fichier
figé écraserait la vraie dernière sauvegarde SQLite. L'avertissement laissait
donc croire à une perte de réglages de tickets à CHAQUE écriture.

`cogs/member_data_retention_v17` filtrait déjà cette raison ; `runtime_finish_v94`
ne le faisait pas. Un journal qui crie au loup à chaque sauvegarde réussie noie
les vraies pannes — c'est précisément là qu'on cherche les bugs.
"""
import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "x")

RACINE = pathlib.Path(__file__).resolve().parent.parent
RAISON = "postgres_primary"


def _avertit_sans_filtrer(chemin: str) -> bool:
    """Un `if not result.get("stored")` sans garde sur la raison attendue."""
    source = (RACINE / chemin).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.If):
            continue
        test = ast.unparse(noeud.test)
        if '"stored"' not in test and "'stored'" not in test:
            continue
        corps = ast.unparse(noeud.body)
        if "logger.warning" not in corps and "logger.error" not in corps:
            continue
        if RAISON not in test:
            return True
    return False


def test_runtime_finish_ne_crie_plus_au_loup():
    assert not _avertit_sans_filtrer("cogs/runtime_finish_v94.py"), (
        "un snapshot sauté parce que PostgreSQL est la base principale est "
        "normal : l'annoncer en WARNING noie les vraies pannes"
    )


def test_la_retention_filtrait_deja_cette_raison():
    # Le modèle correct existait dans le dépôt ; c'est lui qu'on a repris.
    assert not _avertit_sans_filtrer("cogs/member_data_retention_v17.py")


def test_une_vraie_panne_reste_annoncee():
    # Le filtre ne doit porter QUE sur la raison attendue.
    source = (RACINE / "cogs" / "runtime_finish_v94.py").read_text(encoding="utf-8")
    assert "logger.warning(\"Snapshot ticket non stocké" in source, (
        "les autres raisons (postgres_unavailable, local_invalid…) doivent "
        "toujours remonter"
    )
    assert RAISON in source


def test_la_raison_existe_bien_dans_la_couche_durable():
    # Si durable_database cessait de rendre cette raison, le filtre deviendrait
    # du code mort sans que rien ne le signale.
    source = (RACINE / "utils" / "durable_database.py").read_text(encoding="utf-8")
    assert f'"reason": "{RAISON}"' in source
