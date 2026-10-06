#!/usr/bin/env python3
"""Une commande privilégiée est-elle atteignable par un simple membre ?

``tools/permission_audit_sweep.py`` répond « zéro anomalie » même quand une
commande dangereuse est déclarée publique. Ce n'est pas un bug : il déduit
l'attendu de ``access_matrix`` (ligne 359) — la matrice même qu'il contrôle. Il
prouve donc que l'exécution OBÉIT à la matrice, pas que la matrice est sensée.
Mesuré : en déclarant ``ban`` public, on obtient
``attendu=autorise réel=autorise anomalies=[]`` et un membre bannit en + et en /.

Ce croisement comble exactement ce trou, sans jamais lire la matrice. Il confronte
deux MESURES indépendantes :

- qui franchit la commande    (permission_audit_sweep : persona « membre » autorisée) ;
- ce que la commande FAIT     (log_trace_sweep : les routes réellement appelées).

Une commande qui frappe une route privilégiée — bannir, expulser, éditer un
membre, changer des rôles ou des permissions de salon — et qu'un membre sans rôle
franchit, est une escalade, quoi que dise la classification.

    python3 tools/escalation_cross_check.py
    python3 tools/escalation_cross_check.py --strict        # porte CI
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Routes dont l'appel suppose un pouvoir sur le serveur ou sur autrui. Décrites
#: par la route Discord, donc indépendantes de toute configuration SentriX.
ROUTES_PRIVILEGIEES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(PUT|DELETE) /guilds/\d+/bans/"), "bannir / débannir"),
    (re.compile(r"^DELETE /guilds/\d+/members/\d+$"), "expulser"),
    (re.compile(r"^PATCH /guilds/\d+/members/\d+$"), "éditer un membre (pseudo, timeout, rôles)"),
    (re.compile(r"^(PUT|DELETE) /guilds/\d+/members/\d+/roles/"), "donner / retirer un rôle"),
    (re.compile(r"^(PUT|DELETE) /channels/\d+/permissions/"), "changer les permissions d'un salon"),
    (re.compile(r"^(PATCH|DELETE) /channels/\d+$"), "modifier / supprimer un salon"),
    (re.compile(r"^POST /guilds/\d+/channels"), "créer un salon"),
    (re.compile(r"^(POST|PATCH|DELETE) /guilds/\d+/roles"), "créer / modifier / supprimer un rôle"),
    (re.compile(r"^PATCH /guilds/\d+$"), "modifier le serveur"),
    (re.compile(r"^POST /channels/\d+/messages/bulk-delete"), "purger des messages"),
    # Pas de DELETE d'un message seul : la route ne dit pas QUI l'a écrit, et le cas
    # courant est un jeu qui efface sa propre question. Mesuré : colorquiz, hangman et
    # image ressortaient en « escalade » pour avoir nettoyé leur propre message.
    # La purge en masse reste privilégiée, elle : elle ne vise jamais ses propres envois.
    (re.compile(r"^(POST|PATCH|DELETE) /guilds/\d+/auto-moderation"), "changer l'AutoMod"),
    (re.compile(r"^(PUT|POST|DELETE) /guilds/\d+/integrations"), "changer une intégration"),
    (re.compile(r"^(POST|DELETE) /channels/\d+/webhooks"), "créer / supprimer un webhook"),
)


def _pouvoir(route: str) -> str:
    for motif, libelle in ROUTES_PRIVILEGIEES:
        if motif.search(route):
            return libelle
    return ""


def _membres_autorises(chemin: pathlib.Path) -> dict[str, set[str]]:
    """{commande racine: transports} réellement franchis par un membre sans rôle."""
    data = json.loads(chemin.read_text(encoding="utf-8"))
    ouvert: dict[str, set[str]] = {}
    for ligne in data["all"]:
        if ligne["persona"] != "membre" or ligne["actual"] != "autorise":
            continue
        if ligne["state"] not in ("nominal", "module-on"):
            continue
        ouvert.setdefault(ligne["root"], set()).add(ligne["transport"])
    return ouvert


def _pouvoirs_mesures(chemin: pathlib.Path) -> dict[str, dict[str, set[str]]]:
    """{commande: {pouvoir: routes}} d'après les appels réellement émis."""
    data = json.loads(chemin.read_text(encoding="utf-8"))
    pouvoirs: dict[str, dict[str, set[str]]] = {}
    for ligne in data["results"]:
        for route in ligne.get("mutations", ()):
            libelle = _pouvoir(route)
            if libelle:
                racine = ligne["command"].split()[0]
                entree = pouvoirs.setdefault(racine, {})
                entree.setdefault(libelle, set()).add(route)
                if " " in ligne["command"]:
                    entree["_multi"] = True
    return pouvoirs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--perm", default=str(ROOT / "reports" / "perm_audit_20261006.json"),
                   help="rapport de tools/permission_audit_sweep.py")
    p.add_argument("--trace", default=str(ROOT / "reports" / "log_trace_audit.json"),
                   help="rapport de tools/log_trace_sweep.py")
    p.add_argument("--strict", action="store_true")
    a = p.parse_args(argv)

    manquants = [c for c in (a.perm, a.trace) if not pathlib.Path(c).exists()]
    if manquants:
        print("Rapport(s) absent(s) : " + ", ".join(manquants))
        print("Lancer d'abord tools/permission_audit_sweep.py puis tools/log_trace_sweep.py.")
        return 2

    ouvert = _membres_autorises(pathlib.Path(a.perm))
    pouvoirs = _pouvoirs_mesures(pathlib.Path(a.trace))

    # Une sous-commande ne peut PAS être jugée par ce croisement : le rapport de
    # permissions ne connaît que les racines. « sentrixpro » est atteignable par
    # « sentrixpro profile » (public) alors que ses routes privilégiées viennent de
    # « sentrixpro quarantine-setup », qu'un membre ne franchit pas. Confondre les deux
    # annonçait une escalade inexistante ; on les sort donc, et on le dit.
    escalades, non_jugeables = [], []
    for commande, transports in sorted(ouvert.items()):
        if commande not in pouvoirs:
            continue
        if any(" " in route_cmd for route_cmd in pouvoirs[commande].get("_sous", ())):
            pass
        cible = (commande, sorted(transports), pouvoirs[commande])
        (non_jugeables if pouvoirs[commande].get("_multi") else escalades).append(cible)

    print(f"commandes franchies par un membre sans rôle : {len(ouvert)}")
    print(f"commandes mesurées comme privilégiées        : {len(pouvoirs)}")
    print(f"ESCALADES (les deux à la fois)               : {len(escalades)}\n")
    for commande, transports, detail in escalades:
        print(f"  {commande}  [{', '.join(transports)}]")
        for libelle, routes in sorted(detail.items()):
            if libelle.startswith("_"):
                continue
            print(f"      {libelle} — {sorted(routes)[0]}")
    if not escalades:
        print("  aucune : aucun pouvoir privilégié n'est atteignable sans rôle.")
    if non_jugeables:
        print(f"\nNON JUGEABLES par ce croisement : {len(non_jugeables)} racine(s) dont le")
        print("pouvoir vient d'une sous-commande que le rapport de permissions ne couvre pas :")
        for commande, _t, detail in non_jugeables:
            quoi = ", ".join(k for k in sorted(detail) if not k.startswith("_"))
            print(f"  {commande} — {quoi}")
    return 1 if (a.strict and escalades) else 0


if __name__ == "__main__":
    sys.exit(main())
