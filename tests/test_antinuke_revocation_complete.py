"""Retirer quelqu'un de la liste blanche anti-nuke le retire VRAIMENT.

**Le défaut.** Deux interfaces écrivent la confiance anti-nuke dans deux
tables différentes :

- ``+antinuke-whitelist-add`` (``cogs/automod``) écrit ``antinuke_whitelist`` ;
- ``+nukewhitelist add`` (``cogs/v17_moderation_security``) écrit
  ``v17_antinuke_whitelist``.

Et ``_antinuke_allowed`` laisse passer si **l'une OU l'autre** correspond.

Le retrait, lui, ne vidait qu'une seule table. Un administrateur lançait donc
``+antinuke-whitelist-remove @X``, lisait « a été retiré de la liste blanche
anti-nuke », et **X restait autorisé** par l'autre table. Une révocation qui
annonce un succès sans révoquer est pire que pas de révocation : on croit la
trappe fermée.

**Le sens de la correction.** Les deux commandes de retrait vident les deux
tables. Retirer est le sens SÛR — ça resserre, jamais ça n'ouvre — donc
nettoyer les deux ne peut créer aucun accès.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import ast
import inspect
import pathlib
import textwrap

RACINE = pathlib.Path(__file__).resolve().parents[1]

#: Les deux tables que la vérification consulte.
TABLES = ("antinuke_whitelist", "v17_antinuke_whitelist")


def _requetes(fonction) -> str:
    """Les requêtes SQL d'une fonction, commentaires exclus.

    Lu sur l'AST : chercher un nom de table dans le source complet
    rougirait sur la prose qui explique le correctif juste au-dessus.
    """
    arbre = ast.parse(textwrap.dedent(inspect.getsource(fonction)))
    return " ".join(
        n.value
        for n in ast.walk(arbre)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )


def test_la_verification_consulte_bien_les_deux_tables():
    """La prémisse du bug. Si elle tombe, le reste de ce fichier n'a plus de
    sens — et il faudra revérifier quelle table fait autorité."""
    from cogs.v17_moderation_security import _antinuke_allowed

    sql = _requetes(_antinuke_allowed)
    for table in TABLES:
        assert table in sql, f"{table} n'est plus consultée par la vérification"


def test_le_retrait_cote_automod_vide_les_deux_tables():
    """``+antinuke-whitelist-remove`` ne vidait que la table historique."""
    from cogs.automod import AutoMod

    sql = _requetes(AutoMod.antinuke_whitelist_remove.callback)
    for table in TABLES:
        assert f"DELETE FROM {table}" in sql, (
            f"le retrait laisse la confiance en place dans {table}"
        )


def test_le_retrait_cote_v17_vide_aussi_la_table_historique():
    """Symétrique : ``+nukewhitelist remove`` ne vidait que la table V17."""
    from cogs.v17_moderation_security import V17ModerationSecurity

    sql = _requetes(V17ModerationSecurity.nukewhitelist_remove.callback)
    for table in TABLES:
        assert f"DELETE FROM {table}" in sql, (
            f"le retrait laisse la confiance en place dans {table}"
        )


def test_le_retrait_v17_partiel_ne_revoque_pas_tout():
    """Une règle limitée à UNE action ne doit pas révoquer une confiance posée
    pour toutes les autres : nettoyer les deux tables est sûr, mais pas au
    point de supprimer plus que ce que l'administrateur a demandé."""
    from cogs.v17_moderation_security import V17ModerationSecurity

    source = textwrap.dedent(
        inspect.getsource(V17ModerationSecurity.nukewhitelist_remove.callback)
    )
    arbre = ast.parse(source)
    gardes = [
        ast.unparse(n.test)
        for n in ast.walk(arbre)
        if isinstance(n, ast.If)
    ]
    assert any("all" in g for g in gardes), (
        "le nettoyage de la table historique n'est pas limité à l'action « all »"
    )
