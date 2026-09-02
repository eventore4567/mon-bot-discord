"""Ou reste-t-il des embeds, toutes surfaces confondues ?

La mesure d'execution ne regarde que la reponse d'une commande. Un bouton, un
modal, un followup ou un evenement (arrivee d'un membre, journal) envoient
pourtant des messages que l'utilisateur voit exactement de la meme facon.
Cet inventaire les compte separement pour qu'aucune surface ne reste dans un
angle mort.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys
from collections import Counter, defaultdict

RACINE = pathlib.Path(__file__).resolve().parent.parent

# Une surface = comment le message atteint l'utilisateur.
SURFACES = {
    "interaction": re.compile(r"^interaction\b|^inter\b|^i\b"),
    "followup": re.compile(r"followup$"),
    "reponse": re.compile(r"response$"),
    "message": re.compile(r"^(message|msg|sent_message|panneau_message)\b"),
    "salon": re.compile(r"(channel|salon|chan)$"),
    "membre": re.compile(r"^(member|membre|user|utilisateur|author|auteur|owner)\b"),
    "contexte": re.compile(r"^ctx\b"),
}

# Ce qui est legitimement hors du systeme de panneaux.
TOLERE = {
    "embed_builder.py",   # affiche un apercu REEL de l'embed en construction
}


def surface_de(cible: str) -> str:
    tete = cible.split(".")[0]
    for nom, motif in SURFACES.items():
        if motif.search(cible) or motif.search(tete):
            return nom
    return "autre"


def analyser(chemin: pathlib.Path):
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    trouves = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        if n.func.attr not in ("send", "reply", "send_message", "edit_message",
                               "edit_original_response", "edit", "respond"):
            continue
        cles = {k.arg for k in n.keywords if k.arg}
        if not ({"embed", "embeds"} & cles):
            continue
        cible = ast.unparse(n.func.value)
        trouves.append((n.lineno, surface_de(cible), f"{cible}.{n.func.attr}"))
    return trouves


def main(argv: list[str]) -> int:
    fichiers = [pathlib.Path(a) for a in argv] or sorted(RACINE.glob("cogs/*.py"))
    par_surface: Counter = Counter()
    par_fichier: dict[str, list] = defaultdict(list)
    total = 0
    for chemin in fichiers:
        if chemin.name in TOLERE:
            continue
        for ligne, surface, appel in analyser(chemin):
            par_surface[surface] += 1
            par_fichier[str(chemin)].append((ligne, surface, appel))
            total += 1

    print(f"{total} envoi(s) d'embed restants, sur {len(par_fichier)} fichier(s)\n")
    for surface, n in par_surface.most_common():
        print(f"  {surface:12} {n:>5}")
    print()
    pires = sorted(par_fichier.items(), key=lambda kv: -len(kv[1]))[:20]
    for nom, lignes in pires:
        print(f"  {len(lignes):>4}  {nom}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
