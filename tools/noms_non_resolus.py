#!/usr/bin/env python3
"""Detecte les noms globaux utilises mais jamais definis ni importes.

Attrape la classe d'erreur que les tests ne voient pas : un module qui utilise
`stats_service.format_number` sans l'avoir importe ne leve qu'au moment ou la
ligne s'execute — parfois seulement en production, sur un chemin rare.

Trouve reellement lors de la refonte visuelle : cogs/games_economy utilisait
stats_service dans le resultat d'une manche de jeu, sans import. Aucun test ne
parcourait ce chemin.

    python3 tools/noms_non_resolus.py            tout le depot
    python3 tools/noms_non_resolus.py cogs/x.py  un fichier
"""
from __future__ import annotations

import ast
import builtins
import os
import pathlib
import sys

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

CONNUS_BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__"}


def _lies(arbre: ast.AST) -> set[str]:
    """Tous les noms qu'un module lie lui-meme : imports, defs, assignations…"""
    lies: set[str] = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                lies.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            # Une lambda n'a pas de nom mais elle lie bien ses parametres :
            # `key=lambda row: row[0]` ne rend pas `row` non resolu.
            if not isinstance(n, ast.Lambda):
                lies.add(n.name)
            args = getattr(n, "args", None)
            if args is not None:
                for groupe in (args.args, args.posonlyargs, args.kwonlyargs):
                    lies.update(a.arg for a in groupe)
                for special in (args.vararg, args.kwarg):
                    if special is not None:
                        lies.add(special.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            lies.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            lies.add(n.name)
        elif isinstance(n, ast.Global) or isinstance(n, ast.Nonlocal):
            lies.update(n.names)
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and getattr(n, "name", None):
            lies.add(n.name)
    return lies


def _collisions_module(arbre, nom_fichier: str) -> list[str]:
    """Un module importe puis masque par une variable locale du meme nom.

    `panels, files = ...` dans une fonction qui appelle aussi `panels.envoyer`
    rend `panels` LOCAL sur toute la fonction : Python leve UnboundLocalError sur
    les lignes precedentes. Cinq commandes plantaient ainsi apres la migration —
    dont +proof, qui echouait avant meme d'agir.
    """
    # Seuls les imports de NIVEAU MODULE comptent. Un `from . import utility` place
    # dans la fonction, avec un repli `utility = None` dans son except, est un motif
    # correct : le nom est local des le depart, il n'y a rien a masquer.
    modules = set()
    for n in arbre.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                modules.add((alias.asname or alias.name).split(".")[0])
    problemes = []
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        locales = {
            x.id for x in ast.walk(fn)
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)
        }
        heurte = modules & locales
        if not heurte:
            continue
        source = ast.unparse(fn)
        for nom in sorted(heurte):
            if f"{nom}." in source:
                problemes.append(
                    f"{nom_fichier}:{fn.lineno} — `{nom}` est un module ET une variable "
                    f"locale de {fn.name}() : UnboundLocalError garanti"
                )
    return problemes


CONSOMMATEURS = {"sum", "any", "all", "min", "max", "list", "sorted", "len", "tuple", "set"}


def _generateurs_asynchrones(arbre, nom_fichier: str) -> list[str]:
    """Une comprehension contenant `await`, consommee par sum() ou list().

    Dans une fonction async, `sum(await f(x) for x in y)` construit un generateur
    ASYNCHRONE — que sum() ne sait pas parcourir. TypeError a l'execution, sur un
    chemin que la lecture ne signale pas. Trois commandes sentrixpro plantaient
    ainsi. Les crochets suffisent : `sum([... for ...])` evalue avant l'appel.
    """
    problemes = []
    for n in ast.walk(arbre):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in CONSOMMATEURS):
            continue
        for argument in n.args:
            if isinstance(argument, ast.GeneratorExp) and any(
                isinstance(x, ast.Await) for x in ast.walk(argument)
            ):
                problemes.append(
                    f"{nom_fichier}:{n.lineno} — {n.func.id}() consomme une compréhension "
                    f"contenant `await` : générateur asynchrone, TypeError à l'exécution"
                )
    return problemes


def verifier(chemin: pathlib.Path) -> list[str]:
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except SyntaxError as erreur:
        return [f"{chemin.name}: syntaxe invalide ({erreur})"]
    connus = _lies(arbre) | CONNUS_BUILTINS
    manquants: dict[str, int] = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in connus:
            manquants.setdefault(n.id, n.lineno)
    return (
        [f"{chemin.name}:{ligne} — {nom}" for nom, ligne in sorted(manquants.items())]
        + _collisions_module(arbre, chemin.name)
        + _generateurs_asynchrones(arbre, chemin.name)
    )


def main() -> int:
    if len(sys.argv) > 1:
        fichiers = [pathlib.Path(a) for a in sys.argv[1:]]
    else:
        fichiers = sorted(
            [*(RACINE / "cogs").glob("*.py"), *(RACINE / "utils").glob("*.py")]
        )
    problemes = []
    for fichier in fichiers:
        problemes.extend(verifier(fichier))
    if problemes:
        print(f"{len(problemes)} nom(s) global(aux) non résolu(s) :")
        for p in problemes:
            print("   ", p)
        return 1
    print(f"{len(fichiers)} fichiers analysés : aucun nom global non résolu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
