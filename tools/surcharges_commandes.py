"""Quelles commandes sont remplacees a l'execution, et par quoi ?

Une commande peut etre redefinie apres coup : `cmd = bot.get_command("ping")`
puis `cmd.callback = ...`. C'est ainsi que +ping et +clear rendaient encore
l'ancien embed alors que leur cog etait migre depuis longtemps — et que
+reinitialiser-logs-all executait une autre implementation que +reset-logs-all.

Cet inventaire les liste toutes pour qu'aucune ne reste invisible.
"""
from __future__ import annotations

import ast
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent


def analyser(chemin: pathlib.Path):
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    trouves = []
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            continue
        # variable -> nom de commande recuperee par get_command("…")
        commandes: dict[str, str] = {}
        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign) or len(n.targets) != 1:
                continue
            v = n.value.value if isinstance(n.value, ast.Await) else n.value
            if not isinstance(v, ast.Call) or not isinstance(v.func, ast.Attribute):
                continue
            if v.func.attr != "get_command" or not v.args:
                continue
            if not isinstance(v.args[0], ast.Constant):
                continue
            cible = n.targets[0]
            if isinstance(cible, ast.Name):
                commandes[cible.id] = str(v.args[0].value)

        for n in ast.walk(fn):
            if not isinstance(n, ast.Assign) or len(n.targets) != 1:
                continue
            cible = n.targets[0]
            if not isinstance(cible, ast.Attribute) or cible.attr != "callback":
                continue
            recepteur = ast.unparse(cible.value)
            nom = commandes.get(recepteur)
            if nom is None:
                continue
            trouves.append((n.lineno, nom, recepteur))
    return trouves


def main(argv: list[str]) -> int:
    fichiers = [pathlib.Path(a) for a in argv] or sorted(RACINE.glob("cogs/*.py"))
    par_commande: dict[str, list[str]] = {}
    for chemin in fichiers:
        for ligne, nom, _ in analyser(chemin):
            site = f"{chemin}:{ligne}"
            sites = par_commande.setdefault(nom, [])
            # Le parcours visite les portees imbriquees : un meme site peut
            # remonter deux fois.
            if site not in sites:
                sites.append(site)

    total = sum(len(v) for v in par_commande.values())
    print(f"{total} surcharge(s) de callback sur {len(par_commande)} commande(s)\n")
    for nom in sorted(par_commande, key=lambda n: (-len(par_commande[n]), n)):
        sites = par_commande[nom]
        marque = "  ⚠ plusieurs couches" if len(sites) > 1 else ""
        print(f"  {nom:22} {len(sites)}{marque}")
        for s in sites:
            print(f"       {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
