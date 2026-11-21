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
_PROGRESSION = re.compile(
    r"\b(?:niveau|niveaux|level|xp|exp[eé]rience|classement|leaderboard|"
    r"argent|solde|balance|coins?|pi[eè]ces|[eé]conomie|riche)\b",
    re.IGNORECASE,
)
_MENTION = re.compile(r"<@!?(\d{15,25})>")
_TOP = 5


def concerne_invitations(texte: str) -> bool:
    return bool(_INVITATIONS.search(str(texte or "")))


def concerne_progression(texte: str) -> bool:
    return bool(_PROGRESSION.search(str(texte or "")))


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
        lignes = []
        for rang, entree in enumerate(classement[:_TOP], start=1):
            identifiant = int(entree.get("user_id") or entree.get("inviter_id") or 0)
            membre = guild.get_member(identifiant)
            nom = getattr(membre, "display_name", None) or f"membre {identifiant}"
            lignes.append(f"{rang}. {nom} — {entree.get('credited', entree.get('total', 0))} invitation(s)")
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


async def lire_progression(bot, guild, auteur, texte: str) -> str:
    membre = _cible(texte, guild, auteur)
    if membre is None:
        return ""
    nom = getattr(membre, "display_name", None) or str(membre)
    morceaux = []

    # Lecture directe : get_level et get_balance créent la ligne si elle manque,
    # ce qui écrirait en base à chaque question posée.
    niveau = await bot.db.fetchone(
        "SELECT level, xp FROM levels WHERE guild_id = ? AND user_id = ?",
        (guild.id, membre.id),
    )
    if niveau:
        morceaux.append(f"{nom} est niveau {niveau['level']} avec {niveau['xp']} XP.")
    else:
        morceaux.append(f"{nom} n'a encore aucun niveau enregistré.")

    argent = await bot.db.fetchone(
        "SELECT cash, bank FROM economy WHERE guild_id = ? AND user_id = ?",
        (guild.id, membre.id),
    )
    if argent:
        morceaux.append(
            f"Économie de {nom} : {argent['cash']} en poche, {argent['bank']} en banque."
        )
    return "\n".join(morceaux)


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
            nom="progression",
            concerne=concerne_progression,
            lire=lire_progression,
            commande_equivalente="level",     # public, comme +level
        )
    )


__all__ = [
    "concerne_invitations", "concerne_progression", "installer",
    "lire_invitations", "lire_progression",
]
