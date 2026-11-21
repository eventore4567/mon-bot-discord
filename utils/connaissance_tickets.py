"""Ce que SentriX sait des tickets — et uniquement pour le staff (21/11/2026).

« fait que seules les personnes avec la perm puissent demander les tickets,
les trucs staff quoi. » C'est la règle, et elle est appliquée par le registre
lui-même : cette source déclare `sentrixpro ticket-summary` comme commande
équivalente, donc access_matrix lui applique la catégorie « tickets », soit
administrateur ou rôle autorisé dans Setup.

Un membre ordinaire qui demande « combien de tickets ouverts ? » n'obtient
rien du tout : la source n'est même pas lue, aucune requête n'est faite.
"""
from __future__ import annotations

import logging
import re
import time

from utils import connaissance_serveur

logger = logging.getLogger("bot.connaissance-tickets")

_MOTS = re.compile(
    r"\b(?:ticket|tickets|réclamation|reclamation|support|demandes?\s+d['’ ]aide)\b",
    re.IGNORECASE,
)
_MAX_LIGNES = 8


def concerne(texte: str) -> bool:
    return bool(_MOTS.search(str(texte or "")))


def _age(depuis: int | None) -> str:
    if not depuis:
        return "ouverture inconnue"
    heures = max(0, int(time.time()) - int(depuis)) // 3600
    if heures < 1:
        return "ouvert il y a moins d'une heure"
    if heures < 48:
        return f"ouvert depuis {heures} h"
    return f"ouvert depuis {heures // 24} j"


async def lire(bot, guild, auteur, texte: str) -> str:
    lignes = await bot.db.fetchall(
        "SELECT channel_id, user_id, status, category, priority, claimed_by, created_at "
        # 21/11/2026, revue : « status != 'ferme' » incluait les tickets
        # SUPPRIMÉS, que cogs/tickets.py conserve avec status='supprime'. Un
        # serveur n'ayant qu'un ticket supprimé s'entendait dire qu'il avait un
        # ticket ouvert, et ces lignes mortes chassaient de vrais tickets de la
        # liste des huit. On nomme donc le seul statut qui compte.
        "FROM tickets WHERE guild_id = ? AND status = 'ouvert' "
        "ORDER BY created_at ASC LIMIT ?",
        (guild.id, _MAX_LIGNES + 1),
    )
    lignes = list(lignes or ())
    total = await bot.db.fetchone(
        "SELECT COUNT(*) AS c FROM tickets WHERE guild_id = ? AND status = 'ouvert'",
        (guild.id,),
    )
    ouverts = int(total["c"]) if total else len(lignes)

    if not ouverts:
        return "Tickets : aucun ticket ouvert en ce moment sur ce serveur."

    detail = []
    for ligne in lignes[:_MAX_LIGNES]:
        auteur_ticket = guild.get_member(int(ligne["user_id"] or 0))
        nom = getattr(auteur_ticket, "display_name", None) or f"membre {ligne['user_id']}"
        pris = guild.get_member(int(ligne["claimed_by"] or 0)) if ligne["claimed_by"] else None
        prise_en_charge = (
            f"pris par {pris.display_name}" if pris is not None
            else ("pris en charge" if ligne["claimed_by"] else "NON pris en charge")
        )
        detail.append(
            f"- #{ligne['channel_id']} · {nom} · {ligne['category'] or 'general'} · "
            f"priorité {ligne['priority'] or 'normale'} · {prise_en_charge} · {_age(ligne['created_at'])}"
        )

    entete = f"Tickets ouverts sur ce serveur : {ouverts}"
    if ouverts > _MAX_LIGNES:
        entete += f" (les {_MAX_LIGNES} plus anciens sont listés, il y en a d'autres)"
    return entete + " :\n" + "\n".join(detail)


def installer() -> None:
    connaissance_serveur.enregistrer(
        connaissance_serveur.Source(
            nom="tickets",
            concerne=concerne,
            lire=lire,
            # Même porte que la vue staff des tickets : catégorie « tickets ».
            commande_equivalente="sentrixpro ticket-summary",
        )
    )


__all__ = ["concerne", "installer", "lire"]
