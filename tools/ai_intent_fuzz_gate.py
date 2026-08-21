#!/usr/bin/env python3
"""Fuzz gate pur pour le routeur naturel SentriX.

Une phrase de discussion ne doit jamais devenir une sanction/paiement/vol. À l'inverse,
les formulations d'action explicites doivent continuer à produire un plan sensible qui
sera ensuite confirmé côté Discord.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.intelligent_ux import parse_natural_action

SAFE_PHRASES = (
    "c'est quoi un ban ?",
    "explique moi un ban discord",
    "pourquoi les modos ban des gens",
    "comment marche le mute",
    "est ce que mute 10m est beaucoup",
    "quelle est la différence entre kick et ban",
    "comment éviter de se faire voler",
    "je me suis fait voler 500 pièces",
    "un membre veut me voler",
    "comment envoyer de l'argent",
    "peut on payer un membre avec des crédits",
    "combien coûte un paiement de 5k",
    "donne moi 5 idées de jeux",
    "donne moi une explication du système économique",
    "je veux comprendre le système de warn",
    "un warn ça dure combien de temps",
    "le mot ban est affiché dans mon message",
    "est ce que le bot peut bannir quelqu'un",
    "peux tu expliquer comment bannir un spammeur",
    "tu peux m'expliquer comment mute fonctionne",
    "pourquoi mon ami a été kick",
    "j'ai reçu un timeout hier",
    "mon paiement de 5k n'est pas passé",
    "le transfert vers mon ami a échoué",
    "je veux savoir si rob est autorisé",
    "comment fonctionne la commande rob",
    "est-ce dangereux de bannir temporairement",
    "c'est quoi tempban",
    "aide moi à comprendre les sanctions",
    "quelle sanction pour du spam",
    "quelle est la commande pour payer",
    "explique la commande ban",
    "explique la commande mute",
    "explique la commande warn",
    "explique la commande kick",
    "comment faire un ticket de ban injuste",
    "mon ticket parle d'un ban",
    "le staff m'a mute sans raison",
    "est ce que je peux récupérer 5k après un bug",
    "j'ai perdu 5k en gamble",
)

ACTION_CASES = (
    ("ban <@123456789> raid", "ban"),
    ("stp ban <@123456789> raid", "ban"),
    ("tu peux ban <@123456789> spam", "ban"),
    ("mute <@123456789> 30m spam", "mute"),
    ("peux tu mute <@123456789> 10m insultes", "mute"),
    ("kick <@123456789> pub", "kick"),
    ("warn <@123456789> insultes", "warn"),
    ("unmute <@123456789>", "unmute"),
    ("tempban <@123456789> 2h raid", "tempban"),
    ("ban temporaire <@123456789> 1j scam", "tempban"),
    ("envoie 5k à <@123456789>", "pay"),
    ("tu peux envoyer 1500 à <@123456789>", "pay"),
    ("paye 200 pour <@123456789>", "pay"),
    ("vole <@123456789>", "rob"),
    ("stp rob <@123456789>", "rob"),
)


def main() -> int:
    errors: list[str] = []

    for phrase in SAFE_PHRASES:
        plan = parse_natural_action(phrase)
        if plan is not None:
            errors.append(f"faux positif: {phrase!r} -> {plan.command}")

    for phrase, expected in ACTION_CASES:
        plan = parse_natural_action(phrase)
        if plan is None:
            errors.append(f"action explicite non reconnue: {phrase!r}")
            continue
        if plan.command != expected:
            errors.append(f"mauvaise action: {phrase!r} -> {plan.command}, attendu {expected}")
        if expected in {"ban", "mute", "kick", "warn", "unmute", "tempban", "pay", "rob"} and not plan.sensitive:
            errors.append(f"action sensible non marquée sensible: {phrase!r}")

    if parse_natural_action("ban temporaire <@123456789>") is not None:
        errors.append("tempban sans durée ne doit jamais produire de plan")

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC INTENT FUZZ: {len(errors)} régression(s)")
        return 1
    print(f"OK INTENT FUZZ: {len(SAFE_PHRASES)} phrases sûres + {len(ACTION_CASES)} actions explicites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
