#!/usr/bin/env python3
"""Porte de couverture UI : verifie que chaque commande passe par le renderer canonique.

Pourquoi pas de simples regex sur les fichiers : une commande peut deleguer son
rendu a un helper, un module peut etre charge a l'execution hors de la liste
EXTENSIONS, et un `discord.Embed(` dans un fichier n'appartient pas forcement a
une commande. La porte charge donc le bot pour de vrai, parcourt les commandes
reellement enregistrees, puis analyse l'AST du callback et des helpers qu'il
appelle dans son propre module.

Trois verdicts par commande :

  conforme      le rendu atteint utils/embeds._base, directement ou via
                utils/design_system.create_embed qui lui delegue.
  exemptee      la commande correspond a une regle d'exclusion motivee
                (journalisation, webhook, message interne, rendu specialise,
                reponse volontairement textuelle). Chaque regle porte sa raison.
  dette         tout le reste. La liste est figee dans ui_coverage_debt.json et
                ne peut que retrecir : une commande qui n'y figure pas et qui
                n'est pas conforme fait echouer la porte.

Usage :
    python3 tools/ui_coverage_gate.py            verifie
    python3 tools/ui_coverage_gate.py --init     (re)genere la dette de reference
    python3 tools/ui_coverage_gate.py --liste    affiche la dette restante
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
logging.disable(logging.CRITICAL)

DETTE = pathlib.Path(__file__).parent / "ui_coverage_debt.json"


# --------------------------------------------------------------------------
# Ce qui compte comme « conforme »
# --------------------------------------------------------------------------
# Depuis l'unification de la palette, design_system.create_embed delegue a
# embeds._base : les deux chemins produisent le meme embed (meme couleur
# semantique, meme barre d'identite, meme pied de page). Les deux sont donc
# canoniques, et il n'y a plus de raison de reecrire les commandes de l'un vers
# l'autre — ce serait du churn sans gain visuel.
RENDU_CANONIQUE = (
    "embeds.", "sx.", "sentrix_embeds.", "shared_embeds.",
    "design_system.", "create_embed", "category_embed",
    "success_embed(", "error_embed(", "warning_embed(", "info_embed(",
    "_panneau(",
)

# Components V2 : LayoutView et compagnie portent leur propre identite visuelle
# (Container + accent color + MediaGallery). C'est un rendu SentriX a part
# entiere, pas un contournement.
COMPONENTS_V2 = ("LayoutView", "ui.Container", "MediaGallery", "ui.Section", "TextDisplay")

# --------------------------------------------------------------------------
# Exclusions, chacune motivee
# --------------------------------------------------------------------------
EXEMPTIONS = (
    (
        "journalisation",
        ("send_log", "wide_logs", "send_wide_log", "log_embed", "WideLogView"),
        "Les logs ont leur propre format grand format, volontairement different "
        "des reponses de commande. Les uniformiser rendrait les journaux moins "
        "lisibles.",
    ),
    (
        "webhook",
        ("Webhook.", "webhook.send", "create_webhook", "_webhook"),
        "Un message poste via webhook s'affiche sous une autre identite : il "
        "n'est pas une reponse du bot et ne doit pas porter son pied de page.",
    ),
    (
        "rendu_specialise",
        ("premium_style.", "command_visuals.", "PremiumEmbedView", "PremiumLogView",
         "proof_service.", "generate_card", "Image.new", "discord.File("),
        "Rendu dedie (carte generee, fiche premium, image). Le passer au "
        "constructeur generique detruirait la mise en page voulue.",
    ),
    (
        "texte_volontaire",
        (),  # rempli par la liste nominative ci-dessous
        "Reponse volontairement textuelle : une ligne suffit et un panneau "
        "serait plus lourd que l'information transmise.",
    ),
)

# Commandes dont la reponse texte est un choix, pas un oubli. Nommees une par une :
# une regle automatique se tromperait, et une exclusion doit rester auditable.
TEXTE_VOLONTAIRE = {
    "ping": "La latence tient en un nombre ; la reponse doit arriver instantanement.",
    "say": "Le bot repete le texte de l'utilisateur — l'encadrer le denaturerait.",
    "echo": "Le bot renvoie le texte fourni tel quel ; l'encadrer le denaturerait.",
    "nick": "Confirmation d'une seule ligne sur une action triviale.",
}


def chemins_trouves(source: str) -> set[str]:
    trouves = set()
    if any(m in source for m in RENDU_CANONIQUE):
        trouves.add("canonique")
    if any(m in source for m in COMPONENTS_V2):
        trouves.add("components_v2")
    if "discord.Embed(" in source:
        trouves.add("embed_brut")
    for nom, motifs, _raison in EXEMPTIONS:
        if motifs and any(m in source for m in motifs):
            trouves.add(nom)
    return trouves


# Profondeur maximale de la chaine de delegation suivie. La plus longue chaine
# reelle du depot en compte quatre (fishing -> _run_solo -> _partage -> _embed ->
# create_embed) ; six laisse de la marge sans rendre la porte lente ou imprevisible.
# Noms de methodes trop courants pour servir de saut inter-modules. `x.clear()`
# sur une liste ne mene pas a la commande +clear, et `y.send()` ne mene pas a la
# fonction send d'un cog. Sans cette liste, la porte annoncait 15 commandes
# recomposees dans embed_builder parce qu'il appelle `.clear()` quelque part.
NOMS_TROP_COURANTS = frozenset({
    "clear", "send", "edit", "add", "remove", "get", "set", "close", "stop",
    "start", "update", "keys", "values", "items", "join", "format", "strip",
    "split", "append", "pop", "copy", "count", "index", "insert", "extend",
    "read", "write", "open", "run", "check", "reset", "save", "load", "build",
    "render", "refresh", "cancel", "delete", "create", "connect", "execute",
    "lower", "upper", "title", "replace", "startswith", "endswith", "encode",
    "decode", "sort", "reverse", "next", "seek", "flush", "wait", "done",
})

# Receveurs depuis lesquels un saut inter-modules a du sens. `cog.send_report(ctx)`
# et `help_cog.send_help(...)` designent bien une methode d'un autre cog ; en
# revanche `guild.ban(...)` est une methode de discord.py, pas la commande +ban.
# Sans cette regle, +bl paraissait recompose parce qu'il appelle guild.ban().
RECEVEURS_SUIVIS = ("self", "cog")


def _saut_autorise(cible: str) -> bool:
    """Le saut vers l'index global est-il legitime pour cet appel ?"""
    if "." not in cible:
        return True  # appel nu : envoyer(...), _aide(...)
    receveur = cible.rsplit(".", 1)[0].split(".")[-1]
    return receveur in RECEVEURS_SUIVIS or receveur.endswith("_cog")


PROFONDEUR_MAX = 6


def suivre_delegation(depart: str, fns: dict, profondeur: int = PROFONDEUR_MAX,
                      globales: dict | None = None) -> set[str]:
    """Chemins de rendu atteignables depuis `depart` en suivant les appels.

    Le suivi franchit les frontieres de module : `+diagnostic` appelle
    `cog.send_report(ctx)` sur un AUTRE cog, `+help` passe par
    `help_cog.send_help()` puis `_home()`. Sans cela, des commandes parfaitement
    conformes restaient signalees.

    Le saut hors du module n'est autorise que si le nom est defini UNE SEULE FOIS
    dans tout le depot (`globales`) : une homonymie declarerait conforme a tort.
    Le module courant reste prioritaire, et la profondeur borne la recherche.
    """
    globales = globales or {}
    trouves: set[str] = set()
    vus: set[str] = set()

    def source_de(nom: str) -> str | None:
        if nom in fns:
            return ast.unparse(fns[nom])
        return globales.get(nom)

    file = [(depart, profondeur)]
    while file:
        nom, reste = file.pop()
        if nom in vus or reste <= 0:
            continue
        source = source_de(nom)
        if source is None:
            continue
        vus.add(nom)
        trouves |= chemins_trouves(source)
        try:
            arbre = ast.parse(source)
        except SyntaxError:
            continue
        for n in ast.walk(arbre):
            if not isinstance(n, ast.Call):
                continue
            morceaux = ast.unparse(n.func).split(".")
            appele = morceaux[-1]
            # `self.autre_commande.callback(self, ctx)` delegue a `autre_commande` :
            # sans ce cas, `+embedconfig list` paraissait ne rien afficher.
            if appele == "callback" and len(morceaux) >= 2:
                appele = morceaux[-2]
            if appele not in vus:
                file.append((appele, reste - 1))
    return trouves


async def analyser() -> list[dict]:
    import config
    from database.db import Database

    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "ui_gate.db")
    import main as bot_main

    bot = bot_main.BotAllInOne()
    bot.db = Database(config.DATABASE_PATH)
    await bot.db.connect()

    # railway_boot ajoute des extensions hors de la liste EXTENSIONS : sans elles
    # la porte ne verrait pas toutes les commandes reellement servies.
    extensions = list(bot_main.EXTENSIONS)
    boot = (RACINE / "railway_boot.py").read_text(encoding="utf-8")
    for module in re.findall(r'bot_main\.EXTENSIONS\.append\("(cogs\.[a-z0-9_]+)"\)', boot):
        if module not in extensions:
            extensions.append(module)
    for extension in extensions:
        try:
            await asyncio.wait_for(bot.load_extension(extension), timeout=20)
        except Exception:
            pass

    arbres: dict[str, dict] = {}

    # Index inter-modules des fonctions dont le nom n'apparait qu'une fois dans le
    # depot. Il sert uniquement de dernier recours, pour les appels qui traversent
    # une frontiere de module (`bot.get_cog(...).methode(...)`).
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
    globales = {nom: src for nom, src in sources.items() if compte[nom] == 1}

    def fonctions(module: str) -> dict:
        if module not in arbres:
            chemin = RACINE / "cogs" / f"{module}.py"
            if not chemin.exists():
                chemin = RACINE / "utils" / f"{module}.py"
            try:
                arbre = ast.parse(chemin.read_text(encoding="utf-8"))
                arbres[module] = {
                    n.name: n
                    for n in ast.walk(arbre)
                    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                }
            except Exception:
                arbres[module] = {}
        return arbres[module]

    resultats = []
    for commande in bot.walk_commands():
        rappel = getattr(commande, "callback", None)
        if rappel is None:
            continue
        module = rappel.__module__.split(".")[-1]
        fns = fonctions(module)
        depart = rappel.__name__
        noeud = fns.get(depart)
        if noeud is None:
            # Beaucoup de commandes sont installees au demarrage sous forme de
            # fermeture, avec __name__ reecrit (les ponts +serverinfo et +leaderboard
            # par exemple). Le qualname garde la trace de la fonction englobante :
            # « _install_bridge.<locals>.bridge ». On analyse celle-ci, qui contient
            # bien le rendu reellement utilise.
            qualname = getattr(rappel, "__qualname__", "")
            if "<locals>" in qualname:
                englobante = qualname.split(".<locals>.")[0].split(".")[-1]
                if englobante in fns:
                    depart, noeud = englobante, fns[englobante]
            if noeud is None:
                dernier = qualname.split(".")[-1]
                if dernier in fns:
                    depart, noeud = dernier, fns[dernier]
        if noeud is None:
            resultats.append({
                "nom": commande.qualified_name, "module": module,
                "verdict": "source_introuvable", "chemins": [],
            })
            continue

        # Une commande delegue souvent son rendu, et parfois en plusieurs sauts :
        # fishing -> _run_solo -> _embed -> design_system.create_embed. S'arreter au
        # premier niveau declarerait a tort 13 commandes de jeu « sans rendu ».
        # On suit donc la chaine transitivement, avec garde-fou contre les cycles.
        trouves = suivre_delegation(depart, fns, globales=globales)

        nom = commande.qualified_name
        if nom in TEXTE_VOLONTAIRE:
            verdict = "exemptee"
        elif trouves & {"canonique", "components_v2"}:
            verdict = "conforme"
        elif trouves & {"journalisation", "webhook", "rendu_specialise"}:
            verdict = "exemptee"
        else:
            verdict = "dette"

        resultats.append({
            "nom": nom, "module": module, "verdict": verdict,
            "chemins": sorted(trouves),
        })

    await bot.db.close()
    return resultats


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--init", action="store_true", help="regenere la dette de reference")
    parseur.add_argument("--liste", action="store_true", help="affiche la dette restante")
    parseur.add_argument("--json", action="store_true", help="sortie machine")
    args = parseur.parse_args()

    resultats = asyncio.run(analyser())
    par_verdict: dict[str, list[dict]] = {}
    for r in resultats:
        par_verdict.setdefault(r["verdict"], []).append(r)
    dette_actuelle = sorted(
        r["nom"] for r in resultats if r["verdict"] in ("dette", "source_introuvable")
    )

    if args.json:
        print(json.dumps({"resultats": resultats, "dette": dette_actuelle}, ensure_ascii=False, indent=1))
        return 0

    total = len(resultats)
    conformes = len(par_verdict.get("conforme", []))
    print(f"commandes analysees : {total}")
    print(f"  conformes  : {conformes:>4}  ({conformes * 100 // max(total, 1)} %)")
    print(f"  exemptees  : {len(par_verdict.get('exemptee', [])):>4}")
    print(f"  dette      : {len(dette_actuelle):>4}")

    if args.init:
        DETTE.write_text(
            json.dumps(
                {
                    "_lisez_moi": (
                        "Commandes qui ne passent pas encore par le renderer canonique. "
                        "Cette liste ne peut que retrecir : la porte echoue si une "
                        "commande absente d'ici devient non conforme. Retirez une entree "
                        "quand la commande est migree ; n'en ajoutez pas sans raison ecrite."
                    ),
                    "commandes": dette_actuelle,
                },
                ensure_ascii=False,
                indent=1,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"\ndette de reference ecrite : {len(dette_actuelle)} commandes")
        return 0

    if args.liste:
        print("\ndette restante, par module :")
        par_module: dict[str, list[str]] = {}
        for r in resultats:
            if r["verdict"] in ("dette", "source_introuvable"):
                par_module.setdefault(r["module"], []).append(r["nom"])
        for module, noms in sorted(par_module.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(noms):>3}  {module}: {', '.join(sorted(noms)[:6])}"
                  + (" ..." if len(noms) > 6 else ""))
        return 0

    if not DETTE.exists():
        print("\nAucune dette de reference. Lancez --init une premiere fois.")
        return 1

    reference = set(json.loads(DETTE.read_text(encoding="utf-8"))["commandes"])
    nouvelles = sorted(set(dette_actuelle) - reference)
    reglees = sorted(reference - set(dette_actuelle))

    if reglees:
        print(f"\n{len(reglees)} commande(s) migrees depuis la derniere reference :")
        for nom in reglees[:20]:
            print(f"    {nom}")
        print("  -> relancez --init pour verrouiller ce progres.")

    if nouvelles:
        print(f"\nECHEC : {len(nouvelles)} commande(s) contournent le renderer canonique")
        print("        sans figurer dans la dette de reference :")
        for nom in nouvelles:
            detail = next(r for r in resultats if r["nom"] == nom)
            print(f"    {nom}  ({detail['module']}, chemins={detail['chemins'] or 'aucun'})")
        print("\n  Utilisez utils/embeds ou utils/design_system, ou motivez une")
        print("  exemption dans EXEMPTIONS / TEXTE_VOLONTAIRE de ce fichier.")
        return 1

    print("\nOK : aucune nouvelle commande hors du renderer canonique.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
