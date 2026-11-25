"""Messages envoyés par SentriX comme RÉPONSE de l'IA (25/11/2026).

Une longue réponse de l'IA s'affiche en carte (bot_experience_v5,
upgraded_send_sentrix_reply). Ai.on_message ne reconnaissait comme « réponse
de l'IA » que les messages texte sans composants : répondre à une carte de
l'IA ne relançait pas la conversation. Ce registre retient les identifiants
des réponses de l'IA, cartes comprises, pour les reconnaître — sans
confondre avec un panneau ou un log, qui n'y figurent jamais.
"""
from __future__ import annotations

from collections import OrderedDict

_MAX = 5000
_IDS: "OrderedDict[int, None]" = OrderedDict()


def noter(message) -> None:
    identifiant = getattr(message, "id", None)
    try:
        identifiant = int(identifiant)
    except (TypeError, ValueError):
        return
    _IDS[identifiant] = None
    _IDS.move_to_end(identifiant)
    while len(_IDS) > _MAX:
        _IDS.popitem(last=False)


def est_reponse_ia(message) -> bool:
    try:
        return int(getattr(message, "id", 0) or 0) in _IDS
    except (TypeError, ValueError):
        return False
