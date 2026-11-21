"""Invitations, niveaux et économie : ce que tout le monde peut déjà voir.

21/11/2026. `+invites`, `+level` et `+balance` répondent à tout le monde, donc
ces sources répondent à tout le monde : même donnée, même permission. La règle
du registre vaut dans les deux sens — elle n'ouvre rien que les commandes ne
montrent déjà, et elle ne ferme rien qu'elles laissent ouvert.
"""
from __future__ import annotations

import logging
import re

from utils import connaissance_serveur

logger = logging.getLogger("bot.connaissance-communaute")

_INVITATIONS = re.compile(
    r"\b(?:invitation|invitations|invit|invits|invite[rs]?|parrain\w*|classement\s+invit\w*)\b",
    re.IGNORECASE,
)
_NIVEAU = re.compile(
    r"\b(?:niveau|niveaux|level|xp|exp[eé]rience|classement|leaderboard)\b",
    re.IGNORECASE,
)
_ECONOMIE = re.compile(
    r"\b(?:argent|solde|balance|coins?|pi[eè]ces|[eé]conomie|riche|banque)\b",
    re.IGNORECASE,
)
_MENTION = re.compile(r"<@!?(\d{15,25})>")
_TOP = 5


def concerne_invitations(texte: str) -> bool:
    return bool(_INVITATIONS.search(str(texte or "")))


def concerne_niveau(texte: str) -> bool:
    return bool(_NIVEAU.search(str(texte or "")))


def concerne_economie(texte: str) -> bool:
    return bool(_ECONOMIE.search(str(texte or "")))


def _cible(texte: str, guild, auteur):
    """La personne visée : celle qui est mentionnée, sinon celle qui demande."""
    for brut in _MENTION.findall(str(texte or "")):
        membre = guild.get_member(int(brut))
        if membre is not None:
            return membre
    return auteur


async def lire_invitations(bot, guild, auteur, texte: str) -> str:
    morceaux = []
    try:
        classement = await bot.db.get_invite_leaderboard_credited(guild.id, _TOP)
    except Exception:  # noqa: BLE001
        logger.debug("Classement invitations illisible.", exc_info=True)
        classement = []
    if classement:
        # 21/11/2026 : get_invite_leaderboard_credited renvoie des TUPLES
        # (inviter_id, breakdown), pas des dictionnaires. Appeler .get dessus
        # levait AttributeError, le registre avalait l'erreur, et TOUTE la
        # source invitations disparaissait. Ma fixture de test renvoyait des
        # dictionnaires : j'avais inventé la forme au lieu de la lire.
        lignes = []
        for rang, entree in enumerate(classement[:_TOP], start=1):
            identifiant, detail = entree
            membre = guild.get_member(int(identifiant or 0))
            nom = getattr(membre, "display_name", None) or f"membre {identifiant}"
            credite = detail.get("credited", detail.get("total", 0)) if detail else 0
            lignes.append(f"{rang}. {nom} — {credite} invitation(s)")
        morceaux.append("Classement des invitations (créditées) :\n" + "\n".join(lignes))

    membre = _cible(texte, guild, auteur)
    if membre is not None:
        try:
            stats = await bot.db.get_invite_stats(guild.id, membre.id)
        except Exception:  # noqa: BLE001
            stats = None
        if stats:
            nom = getattr(membre, "display_name", None) or str(membre)
            morceaux.append(
                f"Invitations de {nom} : {stats['total']} au total, "
                f"{stats['active']} encore sur le serveur, {stats['left']} repartis."
            )
    return "\n\n".join(morceaux)


async def lire_niveau(bot, guild, auteur, texte: str) -> str:
    """Le niveau seulement. L'économie a sa propre source, voir plus bas."""
    membre = _cible(texte, guild, auteur)
    if membre is None:
        return ""
    nom = getattr(membre, "display_name", None) or str(membre)
    # Lecture directe : get_level crée la ligne si elle manque, ce qui écrirait
    # en base à chaque question posée.
    niveau = await bot.db.fetchone(
        "SELECT level, xp FROM levels WHERE guild_id = ? AND user_id = ?",
        (guild.id, membre.id),
    )
    if not niveau:
        return f"{nom} n'a encore aucun niveau enregistré."
    return f"{nom} est niveau {niveau['level']} avec {niveau['xp']} XP."


async def lire_economie(bot, guild, auteur, texte: str) -> str:
    """L'économie seulement.

    21/11/2026, revue Codex : lire les deux sous l'autorisation de `level`
    exposait le solde d'un serveur qui a désactivé l'économie, et inversement
    bloquait l'économie d'un serveur sans niveaux. access_matrix range `balance`
    dans le module economy et `level` dans levels : leurs décisions ne sont pas
    interchangeables, donc chaque domaine a sa propre source.
    """
    membre = _cible(texte, guild, auteur)
    if membre is None:
        return ""
    nom = getattr(membre, "display_name", None) or str(membre)
    argent = await bot.db.fetchone(
        "SELECT cash, bank FROM economy WHERE guild_id = ? AND user_id = ?",
        (guild.id, membre.id),
    )
    if not argent:
        return ""
    return f"Économie de {nom} : {argent['cash']} en poche, {argent['bank']} en banque."


def installer() -> None:
    connaissance_serveur.enregistrer(
        connaissance_serveur.Source(
            nom="invitations",
            concerne=concerne_invitations,
            lire=lire_invitations,
            commande_equivalente="invites",   # public, comme +invites
        )
    )
    connaissance_serveur.enregistrer(
        connaissance_serveur.Source(
            nom="niveau",
            concerne=concerne_niveau,
            lire=lire_niveau,
            commande_equivalente="level",     # module levels
        )
    )
    connaissance_serveur.enregistrer(
        connaissance_serveur.Source(
            nom="economie",
            concerne=concerne_economie,
            lire=lire_economie,
            commande_equivalente="balance",   # module economy, décision distincte
        )
    )


__all__ = [
    "concerne_economie", "concerne_invitations", "concerne_niveau", "installer",
    "lire_economie", "lire_invitations", "lire_niveau",
]
