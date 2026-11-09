#!/usr/bin/env python3
"""Carte des couches de SentriX : quelles fonctions partagées sont remplacées, par qui.

09/11/2026 — étape 1 de la réorganisation (« rends tout le dépôt plus simple, supprime
les couches »). Ne modifie rien : parcourt cogs/, utils/, web/ et database/, relève
chaque affectation qui remplace une fonction d'un AUTRE module ou d'une classe
partagée (``module.fonction = enveloppe``, ``Classe.méthode = …``,
``objet.méthode = MethodType(…)``), et écrit docs/CARTE_DES_COUCHES.md.

Le câblage d'interface ordinaire (``bouton.callback = …``, ``view.message = …``) n'est
pas une couche et n'est pas compté.

    python3 tools/carte_des_couches.py
"""
from __future__ import annotations

import ast
import collections
import pathlib

RACINE = pathlib.Path(__file__).resolve().parents[1]
DOSSIERS = ("cogs", "utils", "web", "database")
SORTIE = RACINE / "docs" / "CARTE_DES_COUCHES.md"
# Noms locaux qui désignent l'objet lui-même : pas un remplacement d'un autre module.
LOCAUX = {"self", "cls", "this", "_self", "view", "item", "button", "select", "modal", "menu"}
# Attributs d'interface : câblage normal, pas une couche.
INTERFACE = {"callback", "message", "label", "disabled", "style", "emoji", "placeholder",
             "options", "default", "value", "row", "custom_id", "url", "category", "ctx"}


def _est_fonction(valeur: ast.AST) -> bool:
    if isinstance(valeur, ast.Call):
        nom = getattr(valeur.func, "attr", getattr(valeur.func, "id", ""))
        return nom == "MethodType"
    return isinstance(valeur, (ast.Name, ast.Lambda))


def relever() -> dict[str, list[str]]:
    cibles: dict[str, list[str]] = collections.defaultdict(list)
    for dossier in DOSSIERS:
        for fichier in sorted((RACINE / dossier).rglob("*.py")):
            try:
                arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Assign) or not _est_fonction(noeud.value):
                    continue
                for cible in noeud.targets:
                    if not isinstance(cible, ast.Attribute):
                        continue
                    base, chemin = cible.value, []
                    while isinstance(base, ast.Attribute):
                        chemin.insert(0, base.attr)
                        base = base.value
                    if not isinstance(base, ast.Name) or base.id in LOCAUX:
                        continue
                    if cible.attr in INTERFACE or cible.attr.startswith("_sentrix") or cible.attr.startswith("__"):
                        continue
                    if any(part in INTERFACE for part in chemin):
                        continue
                    cibles[cible.attr].append(str(fichier.relative_to(RACINE)))
    return cibles


def ecrire(cibles: dict[str, list[str]]) -> str:
    multiples = sorted(((k, v) for k, v in cibles.items() if len(v) >= 2), key=lambda kv: (-len(kv[1]), kv[0]))
    total = sum(len(v) for v in cibles.values())
    lignes = [
        "# Carte des couches de SentriX",
        "",
        "Généré par `tools/carte_des_couches.py` — ne pas modifier à la main.",
        "",
        "Une « couche », c'est un fichier qui remplace au démarrage une fonction d'un autre",
        "module (souvent en l'enveloppant). Plusieurs couches sur la même fonction : chaque",
        "appel les traverse toutes, et il suffit qu'une seule plante (ou change de signature)",
        "pour que la fonction ne marche plus — c'est l'origine des bugs « l'insulte n'est",
        "pas avertie » et « l'IA ne répond pas à une image » de novembre 2026.",
        "",
        f"**{len(cibles)} fonctions remplacées, {total} remplacements au total.**",
        "",
        "## Fonctions remplacées par au moins deux fichiers",
        "",
        "| Couches | Fonction | Fichiers |",
        "|---:|---|---|",
    ]
    for nom, fichiers in multiples:
        noms = ", ".join(sorted({f.split("/")[-1] for f in fichiers}))
        lignes.append(f"| {len(fichiers)} | `{nom}` | {noms} |")
    lignes += [
        "",
        "## Ordre de la réorganisation",
        "",
        "Chaque fonction de ce tableau devient UNE implémentation, dans le module qui la",
        "possède, et les couches correspondantes sont supprimées. Toujours avec la suite de",
        "tests complète au vert, une PR par fonction (ou par petit groupe).",
        "",
    ]
    return "\n".join(lignes) + "\n"


if __name__ == "__main__":
    texte = ecrire(relever())
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(texte, encoding="utf-8")
    print(f"{SORTIE.relative_to(RACINE)} écrit.")
