"""Commandes masquées de /help et du menu « / » faute d'usage — une seule liste.

Décision de Jayden du 16/10/2026, sur l'usage réel de production (rapport
``cogs/command_usage_report``, journal ``command_logs``) : du 05/08 au 16/10/2026,
1 855 exécutions sur 44 serveurs ; 164 commandes utilisées sur 440, 273 jamais.

Masquer n'est PAS supprimer : chaque commande d'ici reste utilisable en préfixe
(``+nom``), avec exactement les mêmes contrôles d'accès, et ``+help nom`` affiche
toujours sa fiche. Elle disparaît seulement des pages de l'aide et du menu « / ».
Pour en remettre une : la retirer de ``MASQUEES``.

La sélection actuelle contient exactement 132 routes du catalogue slash, dont 26 routes de jeux ; 40 routes de jeux restent visibles. Une source
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

RELEVE = "2026-10-20"
PERIODE = ("2026-08-05", "2026-10-16")

MASQUEES: frozenset[str] = frozenset({
    # Masquées du menu slash, jamais supprimées de leurs commandes préfixées +.
    "achievements-v21",
    "add-xp",
    "addbonusinvites",
    "adventure",
    "ai memory",
    "ai model",
    "announce",
    "archery",
    "bot-leave",
    "bot-servers",
    "bot-status",
    "buy",
    "challenges",
    "changelog",
    "channelinfo",
    "choose",
    "code",
    "collec",
    "colorquiz",
    "command-stats",
    "config-history",
    "correct",
    "crown",
    "detective",
    "economy",
    "economyleaderboard",
    "embed duplicate",
    "embed export",
    "embed import",
    "embed message",
    "embed rename",
    "embedconfig addrole",
    "embedconfig list",
    "embedconfig removerole",
    "emoji-list",
    "emojiquiz",
    "event-leave",
    "event-list",
    "explain",
    "explore",
    "fact-check",
    "footer",
    "gamble",
    "gamehistory",
    "gamestats",
    "ghost",
    "give-money",
    "giveaway blacklist",
    "giveaway list",
    "giveaway unblacklist",
    "highlow",
    "hunt",
    "ice",
    "image-prompt",
    "improve",
    "infinit resume",
    "infinit status",
    "invite-codes",
    "invite-history",
    "invite-info",
    "invite-label",
    "invite-leaderboard",
    "invite-rank",
    "invite-retention",
    "invite-search",
    "invite-sources",
    "invite-stats",
    "invite-unlabel",
    "invitebonushistory",
    "lava",
    "logevent",
    "logevent off",
    "logevent on",
    "market",
    "market-buy",
    "market-cancel",
    "market-find",
    "market-history",
    "market-my",
    "market-sell",
    "memory",
    "minesweeper",
    "mining",
    "notifs-list",
    "notifs-status",
    "pay",
    "permissions liste",
    "potion",
    "profilecard",
    "reactionrole-list",
    "reminder-cancel",
    "reminder-list",
    "remove-level-role",
    "removebonusinvites",
    "rephistory",
    "repleaderboard",
    "reset-economy",
    "reset-invites",
    "reset-levels",
    "rob",
    "rolepanel-refresh",
    "roll",
    "safe",
    "say",
    "schedule-list",
    "scramble",
    "sell",
    "sentrixpro badges",
    "sentrixpro goal",
    "sentrixpro live",
    "sentrixpro season",
    "server-audit",
    "server-growth",
    "server-health",
    "server-managed",
    "set-bio",
    "set-bot",
    "set-level-role",
    "set-xp",
    "setstatus",
    "shoprole add",
    "shoprole list",
    "shoprole price",
    "shoprole remove",
    "starboard-off",
    "status-rotate",
    "sticky-every",
    "suggestion-status",
    "summarize",
    "sync-invites",
    "syncbl",
    "systemstatus",
    "theme",
    "tournament-join",
    "tournament-list",
    "treasure",
    "voice-limit",
    "voice-name",
    "voice-time",
    "voice-transfer",
    "weekly",
    "wordgame",
    "zombie",
})


def masquee(nom: str) -> bool:
    return str(nom or "").strip().casefold() in MASQUEES


__all__ = ["MASQUEES", "masquee", "RELEVE", "PERIODE"]
