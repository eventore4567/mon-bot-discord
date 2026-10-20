"""Commandes masquées de /help et du menu « / » faute d'usage — une seule liste.

Décision de Jayden du 16/10/2026, sur l'usage réel de production (rapport
``cogs/command_usage_report``, journal ``command_logs``) : du 05/08 au 16/10/2026,
1 855 exécutions sur 44 serveurs ; 164 commandes utilisées sur 440, 273 jamais.

Masquer n'est PAS supprimer : chaque commande d'ici reste utilisable en préfixe
(``+nom``), avec exactement les mêmes contrôles d'accès, et ``+help nom`` affiche
toujours sa fiche. Elle disparaît seulement des pages de l'aide et du menu « / ».
Pour en remettre une : la retirer de ``MASQUEES``.

La sélection finale contient exactement 100 routes du catalogue slash. Une source
qui n'avait déjà aucune route dans le catalogue ne compte pas dans ce total : en
particulier, un paramètre comme ``nombre=100`` de ``/clear`` n'est évidemment pas
une commande. Les commandes essentielles de modération, sécurité, journaux,
tickets, musique et les jeux représentatifs restent dans le menu slash.

Parmi les commandes jamais utilisées, n'ont PAS été masquées :
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

    # Sous-jeux très proches les uns des autres : les moteurs restent accessibles
    # en préfixe, et le menu slash conserve un choix représentatif de jeux solo,
    # rapides, duels, courses et statistiques.
    'archery', 'bomb', 'collec', 'crown', 'detective', 'ghost', 'ice', 'lava',
    'minesweeper', 'potion', 'rocket', 'safe', 'zombie',
    'adventure', 'explore', 'hunt', 'mining', 'treasure',
    'blackjack', 'coinflip', 'highlow', 'slots', 'choose', 'roll',
    'gamehistory', 'gamestats',

    # Raccourcis IA spécialisés qui exécutent la même famille de traitement que
    # /ai ask. Les fonctions ne disparaissent pas : leurs commandes + restent là.
    'code', 'explain', 'correct', 'improve', 'summarize', 'fact-check', 'image-prompt',

    # Micro-vues d'invitations : /user invites et /server invites restent les deux
    # entrées slash principales ; les outils détaillés restent en préfixe.
    'invite-codes', 'invite-stats', 'invite-rank', 'invite-history',
    'invite-info', 'invite-sources', 'invite-retention', 'invite-search',
    'invite-label', 'invite-unlabel', 'sync-invites', 'reset-invites',
    'addbonusinvites', 'removebonusinvites', 'invitebonushistory',

    # Variantes de profil secondaires ; /profile view, progress et trust restent.
    'profilecard', 'set-bio', 'voice-time', 'sentrixpro badges', 'sentrixpro season',

    # Historique de versions secondaire ; /bot info et /bot status restent visibles.
    'changelog',
})


def masquee(nom: str) -> bool:
    return str(nom or "").strip().casefold() in MASQUEES


__all__ = ["MASQUEES", "masquee", "RELEVE", "PERIODE"]
