"""Un message Components V2 ne peut plus redevenir un embed.

Discord pose le drapeau IS_COMPONENTS_V2 a la CREATION du message. Une edition
qui tente d'y remettre `embed=` est refusee (400), et une vue dont le message
est desormais un panneau mais dont les boutons re-editent en embed est donc
cassee a l'usage — sans qu'aucun test d'import ne le voie.

Cet outil part des vues effectivement envoyees en panneau (via
panels.avec_composants) et verifie que TOUTES leurs editions sont en `view=`.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
EDITIONS = ("edit_message", "edit_original_response", "edit")


def vues_en_panneau(source: str) -> set[str]:
    """Classes de vues passees a avec_composants DANS CE FICHIER.

    On resout par fichier, pas globalement : deux modules peuvent nommer une
    classe SetupView sans que ce soit la meme, et un rapprochement par nom
    seul signalerait des vues qui n'ont jamais ete converties.
    """
    noms: set[str] = set()
    try:
        arbre = ast.parse(source)
    except SyntaxError:
        return noms

    # `avec_composants(..., X(...))` : la classe est ecrite sur place.
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        if not ast.unparse(n.func).endswith("avec_composants") or len(n.args) < 2:
            continue
        arg = n.args[1]
        if isinstance(arg, ast.Call):
            nom = ast.unparse(arg.func).split(".")[-1]
            if nom[:1].isupper():
                noms.add(nom)
        elif isinstance(arg, ast.Name):
            # `avec_composants(p, vue)` : on remonte a l'assignation de `vue`
            # dans la MEME fonction, sinon on ne conclut pas.
            for fn in ast.walk(arbre):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if n not in list(ast.walk(fn)):
                    continue
                for asg in ast.walk(fn):
                    if not isinstance(asg, ast.Assign) or not isinstance(asg.value, ast.Call):
                        continue
                    if not any(getattr(t, "id", None) == arg.id for t in asg.targets):
                        continue
                    nom = ast.unparse(asg.value.func).split(".")[-1]
                    if nom[:1].isupper():
                        noms.add(nom)
    return noms


def main(argv: list[str]) -> int:
    fichiers = [pathlib.Path(a) for a in argv] or sorted(RACINE.glob("cogs/*.py"))
    sources = {}
    for f in fichiers:
        try:
            sources[str(f)] = f.read_text(encoding="utf-8")
        except OSError:
            continue

    problemes: list[str] = []
    toutes: set[str] = set()

    for nom, source in sources.items():
        cibles = vues_en_panneau(source)
        toutes |= cibles
        try:
            arbre = ast.parse(source)
        except SyntaxError:
            continue
        for classe in ast.walk(arbre):
            if not isinstance(classe, ast.ClassDef) or classe.name not in cibles:
                continue
            # Un callback qui a fait `interaction.response.defer(...)` edite
            # ENSUITE un message tout neuf, pas celui de la vue : ce message-la
            # n'est pas Components V2, et un content y est parfaitement valide.
            differes = {
                id(fn)
                for fn in ast.walk(classe)
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                and "interaction.response.defer(" in ast.unparse(fn)
            }
            dans_differe = {
                id(appel)
                for fn in ast.walk(classe)
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(fn) in differes
                for appel in ast.walk(fn)
            }

            for n in ast.walk(classe):
                if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                    continue
                if n.func.attr not in EDITIONS:
                    continue
                if n.func.attr == "edit_original_response" and id(n) in dans_differe:
                    continue
                cles = {k.arg for k in n.keywords if k.arg}
                # `content` est refuse au meme titre qu'un embed : discord.py
                # pose le drapeau components_v2 et l'API renvoie 400.
                fautifs = sorted({"embed", "embeds", "content"} & cles)
                if fautifs:
                    problemes.append(
                        f"{nom}:{n.lineno}  {classe.name}.{n.func.attr}"
                        f"({'=…, '.join(fautifs)}=…) sur un message devenu panneau"
                    )

    # Deuxieme risque, hors des classes de vues : une variable qui recoit le
    # resultat de panels.envoyer() est un message NE en panneau. L'editer avec
    # un embed ou un content est refuse par Discord de la meme facon.
    for nom, source in sources.items():
        try:
            arbre = ast.parse(source)
        except SyntaxError:
            continue
        for fn in ast.walk(arbre):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            nes_panneau: set[str] = set()
            for asg in ast.walk(fn):
                if not isinstance(asg, ast.Assign):
                    continue
                valeur = asg.value
                if isinstance(valeur, ast.Await):
                    valeur = valeur.value
                if not isinstance(valeur, ast.Call):
                    continue
                if not ast.unparse(valeur.func).endswith(("panels.envoyer", "envoyer")):
                    continue
                for cible in asg.targets:
                    if isinstance(cible, ast.Name):
                        nes_panneau.add(cible.id)
            if not nes_panneau:
                continue
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                    continue
                if n.func.attr != "edit":
                    continue
                recepteur = ast.unparse(n.func.value)
                if recepteur not in nes_panneau:
                    continue
                cles = {k.arg for k in n.keywords if k.arg}
                fautifs = sorted({"embed", "embeds", "content"} & cles)
                if fautifs:
                    problemes.append(
                        f"{nom}:{n.lineno}  {fn.name} edite `{recepteur}` "
                        f"({'=…, '.join(fautifs)}=…) alors qu'il est ne en panneau"
                    )

    print(f"vues envoyees en panneau : {len(toutes)}")
    if toutes:
        print("   " + ", ".join(sorted(toutes)))
    print()
    if not problemes:
        print("OK : aucune edition en embed sur un message Components V2.")
        return 0
    print(f"ECHEC : {len(problemes)} edition(s) incompatibles\n")
    for p in problemes:
        print("   " + p)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
