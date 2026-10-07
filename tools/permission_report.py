#!/usr/bin/env python3
"""Rapport exhaustif : qui peut lancer quoi, sur TOUTE la surface SentriX.

Construit à partir des MESURES, pas de la matrice : chaque ligne vient d'une
invocation réelle sur le bot booté (``tools/permission_audit_sweep.py``), en
préfixe ET en slash, pour cinq personas, module actif puis coupé, et bot privé
de la permission Discord que la commande exige.

Pourquoi pas la matrice : ``permission_audit_sweep`` déduit son attendu de
``access_matrix``, donc il prouve que l'exécution OBÉIT à la matrice, pas que la
matrice est sensée. Ce rapport affiche donc le RÉSULTAT RÉEL, et signale à part
les écarts et les commandes privilégiées atteignables sans rôle.

    python3 tools/permission_report.py --perm reports/perm_audit_20261006.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]

PERSONAS = ("membre", "moderateur", "administrateur", "proprietaire-serveur", "proprietaire-sentrix")
LIBELLE_PERSONA = {
    "membre": "Membre",
    "moderateur": "Modérateur",
    "administrateur": "Administrateur",
    "proprietaire-serveur": "Propriétaire du serveur",
    "proprietaire-sentrix": "Propriétaire SentriX",
}
MARQUE = {"autorise": "✅", "refuse": "⛔", "autorise-ou-module": "➖"}


def charger(chemin: pathlib.Path) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


def construire(data: dict) -> dict:
    """{commande: {tier, module, permission, acces{persona: {transport: reel}}, refus, etats}}"""
    cmds: dict[str, dict] = {}
    for r in data["all"]:
        c = cmds.setdefault(r["root"], {
            "tier": r["tier"], "module": r["module"],
            "permission": r.get("required_permission") or "",
            "acces": defaultdict(dict), "refus": {}, "etats": defaultdict(dict),
            "ecarts": [],
        })
        if r["state"] in ("nominal", "module-on"):
            c["acces"][r["persona"]][r["transport"]] = r["actual"]
            if r["actual"] == "refuse" and r["text"] and r["persona"] == "membre":
                c["refus"].setdefault("membre", (r["text"] or "").strip())
        else:
            c["etats"][r["state"]][r["persona"]] = r["actual"]
        if r["issues"]:
            c["ecarts"].append((r["persona"], r["transport"], r["state"], r["issues"]))
    return cmds


def rendre(cmds: dict, data: dict) -> str:
    out: list[str] = []
    a = out.append
    a("# SentriX — rapport exhaustif des permissions\n")
    a(f"**{len(cmds)} commandes** · **{data['rows']} combinaisons mesurées** · "
      f"anomalies : `{data['issue_counts'] or 'aucune'}`\n")
    a("Chaque case vient d'une invocation réelle sur le bot booté, à travers toute la "
      "chaîne : gardes globaux, matrice d'accès, checks de cog et de commande, cooldowns, "
      "puis le transport. ✅ = la commande s'exécute, ⛔ = elle est refusée.\n")
    a("Les colonnes `+` et `/` sont séparées **exprès** : elles doivent toujours être "
      "identiques, et une divergence serait une faille.\n")

    # --- Vue d'ensemble
    a("\n## Vue d'ensemble\n")
    ouvert_membre = sorted(n for n, c in cmds.items()
                           if "autorise" in c["acces"].get("membre", {}).values())
    a(f"- commandes ouvertes à un **membre sans rôle** : **{len(ouvert_membre)}**")
    for persona in PERSONAS[1:]:
        n = sum(1 for c in cmds.values() if "autorise" in c["acces"].get(persona, {}).values())
        a(f"- atteignables par **{LIBELLE_PERSONA[persona]}** : **{n}**")
    divergents = [n for n, c in cmds.items()
                  for p, t in c["acces"].items() if len(set(t.values())) > 1]
    a(f"\n**Divergences `+` / `/` : {len(set(divergents))}**"
      + ("" if divergents else " — les deux transports décident toujours pareil."))

    # --- Par niveau d'accès
    a("\n## Répartition par niveau requis\n")
    par_tier: dict[str, list[str]] = defaultdict(list)
    for nom, c in sorted(cmds.items()):
        par_tier[c["tier"]].append(nom)
    a("| Niveau requis | Commandes | Détail |")
    a("|---|---:|---|")
    for tier, noms in sorted(par_tier.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        a(f"| `{tier}` | {len(noms)} | {', '.join(f'`{n}`' for n in noms)} |")

    # --- Le tableau complet
    a("\n## Toutes les commandes, persona par persona\n")
    entetes = " | ".join(f"{LIBELLE_PERSONA[p]} +/−" for p in PERSONAS)
    a(f"| Commande | Niveau requis | Permission Discord | Module | {entetes} |")
    a("|---|---|---|---|" + "---|" * len(PERSONAS))
    for nom, c in sorted(cmds.items()):
        cases = []
        for p in PERSONAS:
            t = c["acces"].get(p, {})
            cases.append(
                f"{MARQUE.get(t.get('prefix'), '·')} / {MARQUE.get(t.get('slash'), '·')}"
            )
        a(f"| `{nom}` | `{c['tier']}` | {c['permission'] or '—'} | "
          f"{c['module'] or '—'} | " + " | ".join(cases) + " |")

    # --- Ce qu'un membre voit quand c'est refusé
    a("\n## Le message vu par un membre refusé\n")
    a("Un refus doit nommer la permission manquante, pas se contenter d'un « accès "
      "refusé ». Voici le texte exact rendu à un membre sans rôle.\n")
    a("| Commande | Message rendu |")
    a("|---|---|")
    for nom, c in sorted(cmds.items()):
        texte = c["refus"].get("membre", "")
        if texte:
            a(f"| `{nom}` | {texte[:220].replace('|', '¦')} |")

    # --- Module coupé / bot sans permission
    a("\n## Module désactivé, et bot privé de sa permission\n")
    a("Deux états de dégradation mesurés séparément : couper le module du domaine, "
      "puis retirer au bot la permission Discord que la commande exige.\n")
    a("| Commande | Module coupé → membre | Module coupé → admin | Bot sans permission → admin |")
    a("|---|---|---|---|")
    for nom, c in sorted(cmds.items()):
        off = c["etats"].get("module-off", {})
        sans = {k: v for k, v in c["etats"].items() if k.startswith("bot-sans-")}
        sans_admin = next((v.get("administrateur") for v in sans.values()), None)
        if off or sans:
            a(f"| `{nom}` | {MARQUE.get(off.get('membre'), '·')} | "
              f"{MARQUE.get(off.get('administrateur'), '·')} | "
              f"{MARQUE.get(sans_admin, '·')} |")

    # --- Le détail intégral, combinaison par combinaison
    a("\n## Détail intégral — chaque combinaison mesurée\n")
    a("Une ligne par invocation réelle. C'est la matière brute du rapport : rien ici "
      "n'est déduit, tout a été exécuté.\n")
    par_commande: dict[str, list[dict]] = defaultdict(list)
    for r in data["all"]:
        par_commande[r["command"]].append(r)
    for commande in sorted(par_commande):
        lignes = par_commande[commande]
        reference = lignes[0]
        a(f"\n### `{commande}`\n")
        a(f"- niveau requis : `{reference['tier']}`")
        a(f"- module : {reference['module'] or '—'}")
        a(f"- permission Discord exigée : {reference.get('required_permission') or '—'}")
        invocations = sorted({l["invocation"] for l in lignes if l.get("invocation")})
        if invocations:
            a(f"- invocations testées : " + ", ".join(f"`{i}`" for i in invocations))
        a("")
        a("| Transport | Persona | État du monde | Attendu | Réel | Accord |")
        a("|---|---|---|---|---|---|")
        for l in sorted(lignes, key=lambda x: (x["transport"], x["persona"], x["state"])):
            accord = "✅" if not l["issues"] else "⚠️ " + ", ".join(l["issues"])
            a(f"| {l['transport']} | {LIBELLE_PERSONA.get(l['persona'], l['persona'])} | "
              f"`{l['state']}` | {l['expected']} | **{l['actual']}** | {accord} |")
        textes = sorted({(l["text"] or "").strip() for l in lignes
                         if l["actual"] == "refuse" and (l["text"] or "").strip()})
        for texte in textes[:3]:
            a(f"\n> Refus rendu : {texte[:300]}")

    # --- Écarts
    a("\n## Écarts relevés\n")
    tous = [(n, e) for n, c in sorted(cmds.items()) for e in c["ecarts"]]
    if not tous:
        a("Aucun : sur l'ensemble des combinaisons, le résultat réel correspond partout "
          "à ce que la matrice annonce.\n")
        a("> Cette ligne ne dit PAS que la classification est bonne : l'attendu est "
          "déduit de la matrice elle-même. C'est `tools/escalation_cross_check.py` qui "
          "le vérifie, sans jamais la lire.")
    else:
        a("| Commande | Persona | Transport | État | Anomalie |")
        a("|---|---|---|---|---|")
        for nom, (p, tr, etat, issues) in tous:
            a(f"| `{nom}` | {p} | {tr} | {etat} | {', '.join(issues)} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--perm", default=str(ROOT / "reports" / "perm_audit_20261006.json"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "permissions_sentrix.md"))
    a = ap.parse_args(argv)
    chemin = pathlib.Path(a.perm)
    if not chemin.exists():
        print(f"Rapport de mesure absent : {chemin}\nLancer d'abord tools/permission_audit_sweep.py.")
        return 2
    data = charger(chemin)
    texte = rendre(construire(data), data)
    sortie = pathlib.Path(a.out)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(texte, encoding="utf-8")
    print(f"{len(texte.splitlines())} lignes écrites dans {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
