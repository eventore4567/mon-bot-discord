"""Bulletin de sécurité : ce qui expose RÉELLEMENT le serveur.

`+security scan` ne regardait que les permissions de SentriX et le nombre de
filtres actifs. Ça dit si le bot peut travailler, pas si le serveur est exposé.
Un serveur peut afficher 100/100 avec quatorze membres administrateurs et six
webhooks ouverts.

Ce module répond à l'autre question : **qui peut faire quoi, et par où un
attaquant passerait**. Chaque constat porte un chiffre mesuré sur le serveur,
jamais une estimation. Aucune note globale inventée : un score moyen masque
justement le seul rôle qui pose problème.

Tout est pur — aucune E/S, aucun appel Discord — pour que ce soit testable et
que l'appelant décide quand mesurer. Les webhooks sont le seul élément qui
demande un appel réseau : il est passé en argument.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable, Sequence

from utils.access_matrix import permission_label

#: Les permissions qui donnent la main sur le serveur. L'ordre compte : il
#: classe les constats du plus grave au moins grave.
PERMISSIONS_CRITIQUES = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_webhooks",
    "manage_channels",
    "ban_members",
    "kick_members",
    "mention_everyone",
    "moderate_members",
    "manage_messages",
)

#: Ce qu'un rôle par défaut ne devrait jamais porter. `mention_everyone` y est :
#: c'est le vecteur de spam le plus utilisé, et il ne se voit pas dans les logs
#: tant que personne ne s'en sert.
PERMISSIONS_INTERDITES_A_EVERYONE = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "ban_members",
    "kick_members",
    "moderate_members",
    "manage_messages",
    "mention_everyone",
)

CRITIQUE, ELEVE, MOYEN, INFO = "critique", "eleve", "moyen", "info"
_RANG = {CRITIQUE: 0, ELEVE: 1, MOYEN: 2, INFO: 3}

MARQUEURS = {
    CRITIQUE: "🟥",
    ELEVE: "🟧",
    MOYEN: "🟨",
    INFO: "🟦",
}

LIBELLES_GRAVITE = {
    CRITIQUE: "Critique",
    ELEVE: "Élevé",
    MOYEN: "Moyen",
    INFO: "Information",
}


@dataclasses.dataclass(frozen=True)
class Constat:
    """Un point d'exposition, avec de quoi agir.

    `mesure` porte le chiffre brut : c'est lui qui rend le constat vérifiable,
    et c'est aussi lui qui change quand la situation évolue.
    """

    code: str
    gravite: str
    titre: str
    constat: str
    consequence: str
    correction: str
    mesure: int = 0

    @property
    def marqueur(self) -> str:
        return MARQUEURS.get(self.gravite, MARQUEURS[INFO])


def _est_role_de_bot(role) -> bool:
    """Un rôle géré par une intégration : le retirer casse le bot concerné."""
    return bool(getattr(role, "managed", False))


def _permissions_actives(role, parmi: Sequence[str]) -> list[str]:
    permissions = getattr(role, "permissions", None)
    if permissions is None:
        return []
    return [nom for nom in parmi if getattr(permissions, nom, False)]


def _humains(role) -> list:
    """Les membres humains du rôle. Les bots sont comptés séparément."""
    return [m for m in getattr(role, "members", []) or [] if not getattr(m, "bot", False)]


def _lister(noms: Iterable[str], limite: int = 4) -> str:
    noms = list(noms)
    visibles = noms[:limite]
    reste = len(noms) - len(visibles)
    texte = ", ".join(visibles)
    return texte + (f" et {reste} autre(s)" if reste else "")


# --------------------------------------------------------------- les contrôles

def _controle_administrateurs(guild) -> list[Constat]:
    """Administrator contourne TOUTES les dérogations de salon.

    C'est la permission qui rend tout le reste décoratif : un membre
    administrateur voit chaque salon privé, quelles que soient les permissions
    posées dessus.
    """
    proprietaire = getattr(guild, "owner_id", None)
    porteurs, roles_concernes = set(), []
    for role in getattr(guild, "roles", []) or []:
        if _est_role_de_bot(role) or not getattr(role.permissions, "administrator", False):
            continue
        humains = [m for m in _humains(role) if m.id != proprietaire]
        if humains:
            roles_concernes.append(role.name)
            porteurs.update(m.id for m in humains)
    if not porteurs:
        return []
    return [
        Constat(
            code="administrateurs",
            gravite=CRITIQUE if len(porteurs) > 3 else ELEVE,
            titre="Membres administrateurs",
            constat=(
                f"{len(porteurs)} membre(s) hors propriétaire portent Administrateur, "
                f"via {_lister(roles_concernes)}."
            ),
            consequence=(
                "Administrateur ignore toutes les dérogations de salon : ces membres "
                "voient chaque salon privé et peuvent tout supprimer. SentriX ne peut "
                "pas les en empêcher."
            ),
            correction=(
                "Retirer Administrateur et ne donner que les permissions réellement "
                "nécessaires au rôle."
            ),
            mesure=len(porteurs),
        )
    ]


def _controle_everyone(guild) -> list[Constat]:
    role = getattr(guild, "default_role", None)
    if role is None:
        return []
    dangereuses = _permissions_actives(role, PERMISSIONS_INTERDITES_A_EVERYONE)
    if not dangereuses:
        return []
    critique = any(p in dangereuses for p in ("administrator", "manage_guild", "manage_roles"))
    return [
        Constat(
            code="everyone",
            gravite=CRITIQUE if critique else ELEVE,
            titre="Permissions ouvertes à tout le serveur",
            constat=(
                "Le rôle par défaut porte : "
                + ", ".join(permission_label(p) for p in dangereuses)
                + "."
            ),
            consequence=(
                "Chaque membre, y compris un compte qui vient d'arriver, dispose de "
                "ces droits sur tout le serveur."
            ),
            correction=(
                "Retirer ces permissions du rôle par défaut et les redonner à un rôle "
                "de confiance."
            ),
            mesure=len(dangereuses),
        )
    ]


def _controle_hierarchie(guild) -> list[Constat]:
    """Un membre au-dessus du bot échappe à timeout, kick et ban.

    Discord refuse ces actions sur un membre dont le rôle le plus haut dépasse
    celui du bot. SentriX peut encore lui retirer un rôle, mais plus le
    sanctionner.
    """
    moi = getattr(guild, "me", None)
    mon_rang = getattr(getattr(moi, "top_role", None), "position", None)
    if mon_rang is None:
        return []
    proprietaire = getattr(guild, "owner_id", None)
    au_dessus = set()
    for role in getattr(guild, "roles", []) or []:
        if getattr(role, "position", 0) <= mon_rang or _est_role_de_bot(role):
            continue
        if not _permissions_actives(role, PERMISSIONS_CRITIQUES):
            continue
        au_dessus.update(m.id for m in _humains(role) if m.id != proprietaire)
    if not au_dessus:
        return []
    return [
        Constat(
            code="hierarchie",
            gravite=ELEVE,
            titre="Staff hors de portée de SentriX",
            constat=(
                f"{len(au_dessus)} membre(s) avec des permissions sensibles sont "
                "placés au-dessus du rôle de SentriX."
            ),
            consequence=(
                "Discord refuse exclusion, bannissement et exclusion temporaire sur "
                "eux. En cas d'abus, SentriX ne peut que retirer leurs rôles "
                "accessibles et alerter le propriétaire."
            ),
            correction="Remonter le rôle de SentriX au-dessus des rôles de staff.",
            mesure=len(au_dessus),
        )
    ]


def _controle_bots(guild) -> list[Constat]:
    """Un bot administrateur est une clé du serveur confiée à un tiers.

    SentriX s'exclut lui-même : se signaler reviendrait à conseiller de le
    désarmer, et ses propres manques sont déjà couverts par `permissions_bot`.
    """
    moi_id = getattr(getattr(guild, "me", None), "id", None)
    bots = []
    for membre in getattr(guild, "members", []) or []:
        if not getattr(membre, "bot", False) or membre.id == moi_id:
            continue
        permissions = getattr(membre, "guild_permissions", None)
        if permissions is not None and getattr(permissions, "administrator", False):
            bots.append(getattr(membre, "display_name", "?"))
    if not bots:
        return []
    return [
        Constat(
            code="bots_admin",
            gravite=ELEVE,
            titre="Bots administrateurs",
            constat=f"{len(bots)} bot(s) portent Administrateur : {_lister(bots)}.",
            consequence=(
                "Si l'un d'eux est compromis, l'attaquant obtient le serveur entier. "
                "Un bot compromis est le vecteur de nuke le plus courant."
            ),
            correction=(
                "Ne garder Administrateur que sur les bots qui en ont réellement "
                "besoin, et leur donner sinon la liste exacte de leurs permissions."
            ),
            mesure=len(bots),
        )
    ]


def _controle_webhooks(nombre_de_webhooks: int | None) -> list[Constat]:
    """Un webhook est une URL qui publie sans authentification ni rôle.

    Elle survit au départ de celui qui l'a créée et n'apparaît dans aucune
    liste de membres.
    """
    if not nombre_de_webhooks:
        return []
    return [
        Constat(
            code="webhooks",
            gravite=MOYEN if nombre_de_webhooks < 10 else ELEVE,
            titre="Webhooks actifs",
            constat=f"{nombre_de_webhooks} webhook(s) sont enregistrés sur le serveur.",
            consequence=(
                "Chaque webhook est une adresse qui publie dans un salon sans compte "
                "ni rôle. Une adresse qui fuite reste utilisable tant qu'elle n'est "
                "pas supprimée, même si son auteur a quitté le serveur."
            ),
            correction=(
                "Supprimer les webhooks dont personne ne se sert et restreindre "
                "« Gérer les webhooks » au staff."
            ),
            mesure=nombre_de_webhooks,
        )
    ]


def _controle_reglages_discord(guild) -> list[Constat]:
    constats: list[Constat] = []
    verification = getattr(getattr(guild, "verification_level", None), "name", None)
    if verification in {"none", "low"}:
        constats.append(
            Constat(
                code="verification",
                gravite=MOYEN,
                titre="Niveau de vérification faible",
                constat=f"Le niveau de vérification du serveur est « {verification} ».",
                consequence=(
                    "Un compte créé dans la minute peut écrire immédiatement : c'est "
                    "ce qui rend les vagues de comptes jetables rentables."
                ),
                correction="Passer la vérification à « Moyen » au minimum.",
            )
        )
    mfa = getattr(getattr(guild, "mfa_level", None), "name", None)
    if mfa == "disabled":
        constats.append(
            Constat(
                code="mfa",
                gravite=ELEVE,
                titre="Double authentification non exigée",
                constat="Le serveur n'exige pas la 2FA pour les actions de modération.",
                consequence=(
                    "Le mot de passe d'un seul modérateur suffit alors à prendre la "
                    "main sur la modération du serveur."
                ),
                correction=(
                    "Paramètres du serveur → Modération → exiger la 2FA. Seul le "
                    "propriétaire peut l'activer."
                ),
            )
        )
    filtre = getattr(getattr(guild, "explicit_content_filter", None), "name", None)
    if filtre == "disabled":
        constats.append(
            Constat(
                code="filtre_medias",
                gravite=INFO,
                titre="Filtre de médias Discord désactivé",
                constat="Discord n'analyse aucun média envoyé sur le serveur.",
                consequence="Les images explicites ne sont filtrées par personne en amont.",
                correction="Activer le filtre natif pour tous les membres.",
            )
        )
    return constats


def _controle_permissions_du_bot(guild, manquantes: Sequence[str]) -> list[Constat]:
    if not manquantes:
        return []
    return [
        Constat(
            code="permissions_bot",
            gravite=ELEVE,
            titre="Permissions manquantes pour SentriX",
            constat="SentriX n'a pas : " + ", ".join(permission_label(p) for p in manquantes) + ".",
            consequence=(
                "Les protections concernées se déclenchent mais ne peuvent pas agir : "
                "l'incident est enregistré, la sanction échoue."
            ),
            correction="Rendre ces permissions au rôle de SentriX.",
            mesure=len(manquantes),
        )
    ]


PERMISSIONS_ATTENDUES = (
    "manage_messages",
    "view_audit_log",
    "kick_members",
    "ban_members",
    "moderate_members",
    "manage_roles",
    "manage_channels",
)


def permissions_manquantes(guild) -> list[str]:
    moi = getattr(guild, "me", None)
    permissions = getattr(moi, "guild_permissions", None)
    if permissions is None:
        return []
    return [p for p in PERMISSIONS_ATTENDUES if not getattr(permissions, p, False)]


def analyser(guild, *, nombre_de_webhooks: int | None = None) -> list[Constat]:
    """Tous les constats, du plus grave au moins grave.

    Une liste vide est un vrai résultat : elle veut dire qu'aucun des contrôles
    n'a trouvé d'exposition, pas que l'analyse a échoué.
    """
    constats: list[Constat] = []
    constats += _controle_administrateurs(guild)
    constats += _controle_everyone(guild)
    constats += _controle_hierarchie(guild)
    constats += _controle_bots(guild)
    constats += _controle_webhooks(nombre_de_webhooks)
    constats += _controle_permissions_du_bot(guild, permissions_manquantes(guild))
    constats += _controle_reglages_discord(guild)
    constats.sort(key=lambda c: (_RANG.get(c.gravite, 9), c.titre))
    return constats


def empreinte(constats: Sequence[Constat]) -> str:
    """Ce qui identifie une situation.

    Sert à ne pas republier le même bulletin à chaque redémarrage : tant que le
    code, la gravité et la mesure sont identiques, rien n'a bougé.
    """
    return "|".join(f"{c.code}:{c.gravite}:{c.mesure}" for c in constats) or "sain"


def gravite_dominante(constats: Sequence[Constat]) -> str:
    """La pire gravité présente — jamais une moyenne.

    Une moyenne diluerait l'unique constat critique dans six constats mineurs,
    ce qui est exactement l'information à ne pas perdre.
    """
    if not constats:
        return INFO
    return min((c.gravite for c in constats), key=lambda g: _RANG.get(g, 9))


def resume(constats: Sequence[Constat]) -> str:
    """Une ligne de comptage par gravité, sans note globale inventée."""
    if not constats:
        return "Aucune exposition détectée par les contrôles SentriX."
    comptes = []
    for gravite in (CRITIQUE, ELEVE, MOYEN, INFO):
        n = sum(1 for c in constats if c.gravite == gravite)
        if n:
            libelle = LIBELLES_GRAVITE[gravite].lower() + ("s" if n > 1 else "")
            comptes.append(f"{MARQUEURS[gravite]} {n} {libelle}")
    return " · ".join(comptes)


#: Discord refuse un embed dont le TOTAL dépasse 6000 caractères, même si
#: chaque champ tient dans ses 1024. Six constats verbeux suffisaient à faire
#: refuser la carte entière. La marge couvre titre, résumé, pied et boutons.
BUDGET_TOTAL = 4500


def champs(
    constats: Sequence[Constat], *, limite: int = 6, budget: int = BUDGET_TOTAL
) -> list[tuple[str, str, bool]]:
    """Les constats sous forme de champs d'embed, tronqués en le disant.

    Deux plafonds, et les deux comptent : le nombre de constats détaillés, et
    le total de caractères. Ce qui ne rentre pas est annoncé, jamais perdu en
    silence — les constats arrivent triés, donc c'est toujours le moins grave
    qui saute.
    """
    champs_rendus: list[tuple[str, str, bool]] = []
    for constat in constats[:limite]:
        # La gravité va dans la VALEUR, pas dans le titre du champ : la couche
        # de texte sobre retire l'émoji en tête d'un nom de champ (mesuré), et
        # le marqueur de gravité disparaissait silencieusement du bulletin
        # publié dans les journaux.
        valeur = (
            f"{constat.marqueur} **{LIBELLES_GRAVITE[constat.gravite]}** · {constat.constat}\n"
            f"**Conséquence :** {constat.consequence}\n"
            f"**À faire :** {constat.correction}"
        )[:1024]
        nom = constat.titre
        if champs_rendus and len(nom) + len(valeur) > budget:
            break
        budget -= len(nom) + len(valeur)
        champs_rendus.append((nom, valeur, False))
    reste = len(constats) - len(champs_rendus)
    if reste > 0:
        champs_rendus.append(
            ("Et ensuite", f"{reste} autre(s) point(s) de moindre gravité.", False)
        )
    return champs_rendus


async def analyser_complet(guild) -> list[Constat]:
    """Analyse d'un serveur, webhooks compris quand Discord nous les donne.

    Compter les webhooks demande « Gérer les webhooks ». Sans cette permission
    on passe None : le contrôle disparaît du bulletin, au lieu d'annoncer zéro
    webhook — un chiffre faux présenté comme rassurant.

    C'est la seule fonction de ce module qui fait une E/S. Tout le reste est
    pur, pour rester testable sans serveur Discord.
    """
    import discord

    nombre_de_webhooks = None
    try:
        nombre_de_webhooks = len(await guild.webhooks())
    except (discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    return analyser(guild, nombre_de_webhooks=nombre_de_webhooks)


__all__ = [
    "CRITIQUE",
    "ELEVE",
    "MOYEN",
    "INFO",
    "Constat",
    "analyser",
    "analyser_complet",
    "champs",
    "empreinte",
    "gravite_dominante",
    "permissions_manquantes",
    "resume",
]
