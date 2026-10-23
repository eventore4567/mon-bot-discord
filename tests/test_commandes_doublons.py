"""Pas deux commandes pour exactement le même travail.

Mesuré le 23/10/2026 en comparant l'AST des 673 commandes déclarées dans
``cogs/`` : `+economy` et `+balance` avaient un corps STRICTEMENT identique.
Les journaux d'usage de la production disent que `+economy` n'a jamais servi
depuis le début, alors que `+balance` si.

Elle est devenue un ALIAS plutôt qu'une suppression : sa docstring disait
qu'elle avait été « demandée explicitement », donc elle doit continuer de
répondre — mais sans être une seconde entrée à maintenir.
"""
import ast
import os
import pathlib
import re

os.environ.setdefault("DISCORD_TOKEN", "x")

RACINE = pathlib.Path(__file__).resolve().parent.parent
DECORATEURS = ("command", "hybrid_command", "group", "hybrid_group")


def _nom_declare(deco):
    for kw in getattr(deco, "keywords", []):
        if kw.arg == "name" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    for arg in getattr(deco, "args", []):
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _commandes_par_corps():
    """{corps normalisé: {noms de commande}} sur tout cogs/."""
    par_corps = {}
    for fichier in sorted((RACINE / "cogs").glob("*.py")):
        try:
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in noeud.decorator_list:
                cible = deco.func if isinstance(deco, ast.Call) else deco
                if (getattr(cible, "attr", None) or getattr(cible, "id", None)) not in DECORATEURS:
                    continue
                nom = _nom_declare(deco) or noeud.name.replace("_", "-")
                texte = ast.unparse(ast.Module(body=noeud.body, type_ignores=[]))
                texte = re.sub(r"'''.*?'''|\"\"\".*?\"\"\"", "", texte, flags=re.S)
                texte = re.sub(r"\s+", " ", texte).strip()
                if len(texte) < 40:
                    continue  # un corps trop court n'identifie rien
                par_corps.setdefault(texte, set()).add(nom)
    return par_corps


#: Un groupe et sa sous-commande par défaut partagent légitimement leur corps :
#: le parent ne fait que déléguer. Ce n'est pas un doublon.
DELEGATIONS_ATTENDUES = {
    frozenset({"security", "status"}),
    frozenset({"tickettype", "list"}),
    frozenset({"staff-audit", "staff-diagnostic"}),
}


def test_aucun_nouveau_doublon_de_commande():
    doublons = {
        frozenset(noms)
        for noms in _commandes_par_corps().values()
        if len(noms) > 1
    }
    nouveaux = doublons - DELEGATIONS_ATTENDUES
    assert not nouveaux, (
        "deux commandes font exactement le même travail : "
        + "; ".join(", ".join(sorted(g)) for g in nouveaux)
    )


def test_economy_repond_toujours_mais_comme_alias():
    source = (RACINE / "cogs" / "economy.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    noms_declares, alias = set(), set()
    for noeud in ast.walk(arbre):
        for deco in getattr(noeud, "decorator_list", []):
            cible = deco.func if isinstance(deco, ast.Call) else deco
            if (getattr(cible, "attr", None) or getattr(cible, "id", None)) not in DECORATEURS:
                continue
            nom = _nom_declare(deco)
            if nom:
                noms_declares.add(nom)
            for kw in getattr(deco, "keywords", []):
                if kw.arg == "aliases" and isinstance(kw.value, ast.List):
                    alias.update(
                        e.value for e in kw.value.elts if isinstance(e, ast.Constant)
                    )

    assert "balance" in noms_declares
    assert "economy" not in noms_declares, "+economy ne doit plus être une commande à part"
    assert "economy" in alias, "+economy doit rester utilisable"
