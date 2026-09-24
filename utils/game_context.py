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


def jeu_en_cours() -> str:
    """Le nom du mini-jeu en train de répondre, ou une chaîne vide."""
    try:
        from cogs.games_catalog import GAME_CATALOG

        nom, _cog = _racine_et_cog()
        return nom if nom in GAME_CATALOG else ""
    except Exception:
        return ""


def pictogramme_du_jeu(nom: str) -> str:
    """Le pictogramme que le catalogue donne à ce jeu.

    Le catalogue préfixe chaque libellé de son emoji (« 🎲 Pari sur un dé ») :
    c'est donc lui l'autorité, et non une liste de mots-clés qui laissait
    retomber la moitié des jeux sur un « 🎮 » générique.
    """
    try:
        from cogs.games_catalog import GAME_CATALOG

        libelle = (GAME_CATALOG.get(nom) or ("", ""))[0]
    except Exception:
        return ""
    tete = libelle.split(" ", 1)[0].strip()
    # Un libellé commence par son emoji ; s'il commence par une lettre, il n'y en a pas.
    return tete if tete and not tete[0].isalnum() else ""


# Secours pour les écrans de jeu rattachés à aucun jeu précis (classements,
# réglages, récapitulatifs) : le catalogue ne peut rien en dire, le titre si.
_MOTS_CLES = (
    (("réaction", "reaction", "clic"), "⚡"),
    (("vitesse", "retape", "fast"), "⌨️"),
    (("mémoire", "memory"), "🧠"),
    (("mine", "minage", "démineur"), "⛏️"),
    (("chasse", "hunt"), "🏹"),
    (("pêche", "peche", "fishing"), "🎣"),
    (("donjon", "dungeon"), "🗝️"),
    (("trésor", "tresor", "treasure"), "💎"),
    (("aventure", "quête", "quete"), "🗺️"),
    (("plus haut", "plus bas"), "🃏"),
    (("quiz", "trivia"), "❓"),
    (("course", "race"), "🏁"),
    (("duel",), "⚔️"),
    (("collection", "butin", "prise"), "🎒"),
    (("classement",), "🏆"),
)


def pictogramme_de_titre(titre: str) -> str:
    """Le pictogramme à poser devant le titre d'un écran de jeu.

    Une seule règle pour tout le bot : le catalogue d'abord — il sait que
    `dice` est un dé et `slots` une machine à sous —, les mots-clés ensuite,
    et « 🎮 » seulement quand rien d'autre ne dit mieux.
    """
    depuis_catalogue = pictogramme_du_jeu(jeu_en_cours())
    if depuis_catalogue:
        return depuis_catalogue
    valeur = str(titre or "").casefold()
    for mots, icone in _MOTS_CLES:
        if any(mot in valeur for mot in mots):
            return icone
    return "🎮"


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


__all__ = ["commande_de_jeu", "jeu_en_cours", "pictogramme_du_jeu", "pictogramme_de_titre", "COGS_DE_JEU"]
