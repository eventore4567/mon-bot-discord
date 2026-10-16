"""Commandes masquées de /help et du menu « / » faute d'usage — une seule liste.

Décision de Jayden du 16/10/2026, sur l'usage réel de production (rapport
``cogs/command_usage_report``, journal ``command_logs``) : du 05/08 au 16/10/2026,
1 855 exécutions sur 44 serveurs ; 164 commandes utilisées sur 440, 273 jamais.

Masquer n'est PAS supprimer : chaque commande d'ici reste utilisable en préfixe
(``+nom``), avec exactement les mêmes contrôles d'accès, et ``+help nom`` affiche
toujours sa fiche. Elle disparaît seulement des pages de l'aide et du menu « / ».
Pour en remettre une : la retirer de ``MASQUEES``.

Parmi les 273 jamais utilisées, n'ont PAS été masquées (216) :
* modération, sécurité et urgence (53) — ne pas servir en temps calme ne les
  rend pas inutiles pendant un raid (panic, quarantine, tempban, antinuke…) ;
  plus ``note`` et ``watch`` (outils staff) et ``feedback`` (le retour des membres) ;
* commandes de moins d'un mois (46) : pas encore eu le temps de servir ;
* compléments d'une fonction utilisée (76) : ``play`` sert, donc ``music skip``
  reste ; ``giveaway create`` sert, donc ``giveaway end`` reste, etc. ;
* découvertes depuis moins d'un mois (18) : events et tournois rendus visibles le
  26/09 (852aae7d), sticky, schedule et starboard publiés le 08/10 (7a36366d).
  « Jamais utilisée » ne vaut rien pour une commande que personne ne voyait.
  Celles rendues visibles le 09/09 (8dd4b484 : buy, sell, pay…) ont eu 37 jours.
"""
from __future__ import annotations

RELEVE = "2026-10-16"
PERIODE = ("2026-08-05", "2026-10-16")

MASQUEES: frozenset[str] = frozenset({
    'achievements-v21', 'announce', 'bot-leave', 'bot-servers', 'buy', 'challenges',
    'colorquiz', 'command-stats', 'connect4', 'dailygames', 'dice', 'dragon', 'dungeon',
    'economy', 'emojiquiz', 'fishing', 'footer', 'give-money', 'guessrace', 'lastmessage',
    'logevent', 'logevent off', 'logevent on', 'luckyroll', 'market', 'market-buy',
    'market-cancel', 'market-find', 'market-history', 'market-my', 'market-sell',
    'mathrace', 'memory', 'numberduel', 'pay', 'quizduel', 'reaction', 'reactionduel',
    'remove-level-role', 'reset-economy', 'reset-levels', 'scramble', 'sell', 'sequence',
    'server-managed', 'set-bot', 'set-level-role', 'setstatus', 'status-rotate', 'syncbl',
    'systemstatus', 'target', 'theme', 'tictactoe', 'triviastart', 'weekly', 'wordgame',
})


def masquee(nom: str) -> bool:
    return str(nom or "").strip().casefold() in MASQUEES


__all__ = ["MASQUEES", "masquee", "RELEVE", "PERIODE"]
