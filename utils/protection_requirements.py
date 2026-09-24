"""Ce dont chaque protection a besoin pour fonctionner VRAIMENT.

Le panneau Sécurité affichait une protection « active » dès qu'elle était
cochée, et listait à part, dans un fourre-tout, les permissions manquantes du
rôle SentriX. Rien ne reliait les deux. Un propriétaire pouvait donc lire
« Anti-nuke ● ACTIF » et « il manque : Voir le journal d'audit » sans jamais
faire le lien — alors que sans ce journal, l'anti-nuke ne détecte rien du tout :
`get_audit_actor` ne peut pas nommer l'auteur, et l'anti-nuke refuse par
construction de sanctionner quelqu'un au hasard.

Une protection cochée mais incapable d'agir est pire qu'une protection
désactivée : elle donne un sentiment de sécurité qui n'existe pas. Ce module
sert à le dire.

Deux degrés, et la différence n'est pas cosmétique :

- ``INERTE``   : sans cette permission, la protection ne se déclenche jamais.
- ``DEGRADEE`` : elle détecte et journalise, mais ne peut pas sanctionner.

Les exigences sont relevées dans cogs/automod.py, pas devinées : anti-nuke lit
l'audit (get_audit_actor) puis bannit avec repli sur l'expulsion ; anti-raid
relève le niveau de vérification (guild.edit) ; les filtres de messages
suppriment (message.delete) ; anti-bot et anti-compte-récent expulsent.
"""
from __future__ import annotations

INERTE = "inerte"
DEGRADEE = "degradee"
OPERATIONNELLE = "operationnelle"

# protection -> ((permission Discord, libellé, degré si absente), ...)
EXIGENCES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "antispam": (("manage_messages", "Gérer les messages", INERTE),),
    "antilink": (("manage_messages", "Gérer les messages", INERTE),),
    "antiinvite": (("manage_messages", "Gérer les messages", INERTE),),
    "antiscam": (("manage_messages", "Gérer les messages", INERTE),),
    "antiinsult": (("manage_messages", "Gérer les messages", INERTE),),
    "antimention": (("manage_messages", "Gérer les messages", INERTE),),
    "anticaps": (("manage_messages", "Gérer les messages", INERTE),),
    "antiemoji": (("manage_messages", "Gérer les messages", INERTE),),
    # L'anti-raid alerte toujours ; c'est la riposte — relever le niveau de
    # vérification du serveur — qui demande Gérer le serveur.
    "antiraid": (("manage_guild", "Gérer le serveur", DEGRADEE),),
    # Sans le journal d'audit, l'anti-nuke ne sait pas QUI a supprimé le salon,
    # et il ne sanctionne jamais quelqu'un au hasard : il ne fait donc rien.
    "antinuke": (
        ("view_audit_log", "Voir le journal d'audit", INERTE),
        ("ban_members", "Bannir des membres", DEGRADEE),
    ),
    "antibot": (("kick_members", "Expulser des membres", INERTE),),
    "antiaccount": (("kick_members", "Expulser des membres", INERTE),),
}


def etat_protection(permissions, protection: str) -> tuple[str, list[str]]:
    """(état, permissions manquantes) pour une protection donnée.

    ``permissions`` est un ``discord.Permissions`` — celui du rôle SentriX.
    """
    manquantes_inertes: list[str] = []
    manquantes_degradees: list[str] = []
    for attribut, libelle, degre in EXIGENCES.get(protection, ()):
        if getattr(permissions, attribut, False):
            continue
        (manquantes_inertes if degre == INERTE else manquantes_degradees).append(libelle)
    if manquantes_inertes:
        return INERTE, manquantes_inertes
    if manquantes_degradees:
        return DEGRADEE, manquantes_degradees
    return OPERATIONNELLE, []


def diagnostic(permissions, protections_actives) -> tuple[list[tuple[str, list[str]]], list[tuple[str, list[str]]]]:
    """(inertes, dégradées) parmi les protections que le serveur a activées.

    Seules les protections ACTIVÉES sont remontées : signaler qu'une protection
    décochée manque d'une permission n'apprend rien à personne.
    """
    inertes: list[tuple[str, list[str]]] = []
    degradees: list[tuple[str, list[str]]] = []
    for protection in protections_actives:
        etat, manquantes = etat_protection(permissions, protection)
        if etat == INERTE:
            inertes.append((protection, manquantes))
        elif etat == DEGRADEE:
            degradees.append((protection, manquantes))
    return inertes, degradees


__all__ = ["EXIGENCES", "INERTE", "DEGRADEE", "OPERATIONNELLE", "etat_protection", "diagnostic"]
