"""Identifiants Discord des commandes / : de quoi écrire une mention cliquable.

``</logs search:123>`` s'affiche comme un lien ; un clic place la commande dans
la barre de message. Rempli au démarrage par la vérification en direct
(cogs/live_command_gate_v19, qui lit déjà ``tree.fetch_commands()``). Tant que
l'identifiant est inconnu, la commande reste écrite ``/logs search``.
"""
from __future__ import annotations

IDS: dict[str, int] = {}


def retenir(commandes) -> None:
    for commande in commandes or ():
        nom, ident = getattr(commande, "name", None), getattr(commande, "id", None)
        if nom and ident:
            IDS[str(nom).casefold()] = int(ident)


def mention(chemin: str) -> str:
    """``/chemin`` cliquable si l'identifiant de sa racine est connu."""
    chemin = str(chemin or "").strip().lstrip("/")
    ident = IDS.get(chemin.split(" ")[0].casefold()) if chemin else None
    return f"</{chemin}:{ident}>" if ident else f"/{chemin}"
