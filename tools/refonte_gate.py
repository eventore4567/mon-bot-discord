#!/usr/bin/env python3
"""Quelles interfaces ont été REELLEMENT recomposées, et lesquelles pas encore.

Le critère n'est plus « la commande utilise-t-elle le design system » — une
couleur, un pied de page et une barre ne changent pas la composition. Le critère
est : la réponse est-elle un panneau Components V2 avec bannière en tête et
sections séparées, plutôt qu'un embed à champs ?

Trois verdicts :

  recomposé   la réponse passe par un panneau composé (sentrix_panels.Panneau,
              VueAide, PremiumEmbedView). Bannière en tête, sections, filets.
  embed       la réponse reste un embed classique. Conforme au design system,
              mais visuellement inchangé.
  autre       texte, rendu spécialisé, ou chemin non résolu.

Usage :
    python3 tools/refonte_gate.py            résumé
    python3 tools/refonte_gate.py --liste    détail par commande
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import json
import logging
import os
import pathlib
import re
import sys
import tempfile

os.environ.setdefault("DISCORD_TOKEN", "x")
RACINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "tools"))
logging.disable(logging.CRITICAL)

from ui_coverage_gate import suivre_delegation  # noqa: E402

# Marqueurs d'une composition reelle. `_panneau(` a ete ECARTE : ce nom designe un
# helper qui renvoie un Embed dans security_command_center et un Panneau dans le
# module d'erreur. Le retenir gonflait le compte de 60 commandes qui n'ont pas
# change de composition. Un marqueur ambigu vaut moins qu'un chiffre juste.
RECOMPOSE = (
    "panels.Panneau", "sx_panels.Panneau", "panels.envoyer", "sx_panels.envoyer",
    "VueAide(", "PremiumEmbedView(", "_status_panneau", "build_level_panneau",
    "_prefix_error_panel", "_component_error_panel", "_slash_error_panel",
)
EMBED = ("embeds.", "design_system.", "discord.Embed(", "create_embed", "_embed(")


def classer(source: str) -> str:
    if any(m in source for m in RECOMPOSE):
        return "recomposé"
    if any(m in source for m in EMBED):
        return "embed"
    return "autre"


PROFONDEUR = 6


def sources_atteintes(depart: str, fns: dict, globales: dict, profondeur: int = PROFONDEUR) -> str:
    """Source de toutes les fonctions REELLEMENT appelees depuis `depart`.

    Une premiere version concatenait la source de toute fonction globale dont le
    NOM apparaissait comme sous-chaine du corps analyse. Des noms courts comme
    `_t` ou `_conf` matchaient partout : la porte annoncait 32 commandes
    recomposees dans un module qui n'en comptait que deux. On suit donc les
    appels, comme la porte de couverture UI.
    """
    morceaux: list[str] = []
    vus: set[str] = set()
    file = [(depart, profondeur)]
    while file:
        nom, reste = file.pop()
        if nom in vus or reste <= 0:
            continue
        source = ast.unparse(fns[nom]) if nom in fns else globales.get(nom)
        if source is None:
            continue
        vus.add(nom)
        morceaux.append(source)
        try:
            arbre = ast.parse(source)
        except SyntaxError:
            continue
        for n in ast.walk(arbre):
            if isinstance(n, ast.Call):
                appele = ast.unparse(n.func).split(".")[-1]
                if appele not in vus:
                    file.append((appele, reste - 1))
    return "\n".join(morceaux)


async def analyser() -> list[dict]:
    import config
    from database.db import Database

    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "refonte.db")
    import main as bot_main

    bot = bot_main.BotAllInOne()
    bot.db = Database(config.DATABASE_PATH)
    await bot.db.connect()
    extensions = list(bot_main.EXTENSIONS)
    boot = (RACINE / "railway_boot.py").read_text(encoding="utf-8")
    for module in re.findall(r'bot_main\.EXTENSIONS\.append\("(cogs\.[a-z0-9_]+)"\)', boot):
        if module not in extensions:
            extensions.append(module)
    for extension in extensions:
        try:
            await asyncio.wait_for(bot.load_extension(extension), timeout=25)
        except Exception:
            pass

    arbres: dict[str, dict] = {}

    def fonctions(module: str) -> dict:
        if module not in arbres:
            chemin = RACINE / "cogs" / f"{module}.py"
            if not chemin.exists():
                chemin = RACINE / "utils" / f"{module}.py"
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8"))
                arbres[module] = {
                    n.name: n for n in ast.walk(arbre)
                    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                }
            except Exception:
                arbres[module] = {}
        return arbres[module]

    compte: dict[str, int] = {}
    sources: dict[str, str] = {}
    for dossier in ("cogs", "utils"):
        for fichier in sorted((RACINE / dossier).glob("*.py")):
            try:
                arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            except Exception:
                continue
            for n in ast.walk(arbre):
                if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    compte[n.name] = compte.get(n.name, 0) + 1
                    sources[n.name] = ast.unparse(n)
    globales = {n: s for n, s in sources.items() if compte[n] == 1}

    resultats = []
    for commande in bot.walk_commands():
        rappel = getattr(commande, "callback", None)
        if rappel is None:
            continue
        module = rappel.__module__.split(".")[-1]
        fns = fonctions(module)
        depart = rappel.__name__
        if depart not in fns:
            qualname = getattr(rappel, "__qualname__", "")
            if "<locals>" in qualname:
                englobante = qualname.split(".<locals>.")[0].split(".")[-1]
                if englobante in fns:
                    depart = englobante
        if depart not in fns:
            resultats.append({"nom": commande.qualified_name, "module": module, "verdict": "autre"})
            continue

        resultats.append({
            "nom": commande.qualified_name,
            "module": module,
            "verdict": classer(sources_atteintes(depart, fns, globales)),
        })

    await bot.db.close()
    return resultats


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--liste", action="store_true")
    parseur.add_argument("--json", action="store_true")
    args = parseur.parse_args()

    resultats = asyncio.run(analyser())
    if args.json:
        print(json.dumps(resultats, ensure_ascii=False, indent=1))
        return 0

    par_verdict: dict[str, list[dict]] = {}
    for r in resultats:
        par_verdict.setdefault(r["verdict"], []).append(r)

    total = len(resultats)
    recomposees = par_verdict.get("recomposé", [])
    print(f"commandes analysées : {total}")
    for verdict in ("recomposé", "embed", "autre"):
        lot = par_verdict.get(verdict, [])
        print(f"  {verdict:12} {len(lot):>4}  ({len(lot) * 100 // max(total, 1)} %)")

    print(f"\n{len(recomposees)} commandes servies par une interface recomposée :")
    par_module: dict[str, list[str]] = {}
    for r in recomposees:
        par_module.setdefault(r["module"], []).append(r["nom"])
    for module, noms in sorted(par_module.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(noms):>3}  {module}: {', '.join(sorted(noms)[:8])}"
              + (" …" if len(noms) > 8 else ""))

    if args.liste:
        print("\nreste en embed classique, par module :")
        restants: dict[str, int] = {}
        for r in par_verdict.get("embed", []):
            restants[r["module"]] = restants.get(r["module"], 0) + 1
        for module, n in sorted(restants.items(), key=lambda kv: -kv[1])[:25]:
            print(f"  {n:>3}  {module}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
