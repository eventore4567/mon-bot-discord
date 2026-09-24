"""Sait si la commande en cours est un mini-jeu.

SentriX affiche une interface volontairement sobre : les pictogrammes décoratifs
sont retirés de tous les panneaux. Les mini-jeux sont la seule exception, et elle
n'est pas cosmétique : leurs pictogrammes SONT le jeu. Retirer les emojis laissait
« 🎰 | | » — une machine à sous aux rouleaux vides — et « SentriX —  Pêche » avec
un trou à la place du poisson.

Une seule fonction, lue par toutes les couches qui nettoient du texte
(utils/embeds.py, utils/command_style_v2.py, cogs/community_v32.py), pour que
l'exception soit décidée à un seul endroit.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.game-context")

# Cogs dont TOUTES les commandes sont des jeux.
COGS_DE_JEU = frozenset({
    "minigames", "gamesrapides", "gamessolo", "gamescommunity", "gamesduels",
    "gamesplayercommands", "gameseconomy", "games", "gamesetup",
})


def _racine_et_cog() -> tuple[str, str]:
    from cogs.final_interaction_policy import _COMMAND_CONTEXT, _COMMAND_ROOT

    ctx = _COMMAND_CONTEXT.get()
    commande = getattr(ctx, "command", None) if ctx is not None else None
    racine = getattr(commande, "root_parent", None) or commande
    nom = str(getattr(racine, "name", "") or _COMMAND_ROOT.get() or "").casefold()
    return nom, str(getattr(commande, "cog_name", "") or "").casefold()


def commande_de_jeu() -> bool:
    """Vrai quand la commande en train de répondre est un mini-jeu."""
    try:
        from cogs.games_catalog import GAME_CATALOG

        nom, cog = _racine_et_cog()
        if nom and nom in GAME_CATALOG:
            return True
        return bool(cog) and cog in COGS_DE_JEU
    except Exception:
        # Hors commande, ou pendant le démarrage : on garde la règle sobre.
        return False


__all__ = ["commande_de_jeu", "COGS_DE_JEU"]
