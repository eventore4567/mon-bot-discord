"""Crash-test de sécurité (10/11/2026).

« Fais des trucs révolutionnaires. » Aucun bot ne dit à un propriétaire ce qui se
passerait VRAIMENT si son serveur était attaqué maintenant. Le crash-test joue neuf
attaques en simulation contre la configuration réelle du serveur :

- les messages d'attaque passent dans les VRAIS détecteurs de SentriX (arnaque, pub,
  insultes) : si un détecteur rate son échantillon, le test le dit ;
- les réglages réellement enregistrés (protections actives, seuils de spam, seuil de
  raid selon la taille du serveur) ;
- les permissions réelles du rôle SentriX et sa place dans la hiérarchie des rôles.

Rien n'est envoyé, personne n'est sanctionné : c'est une lecture.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

BLOQUE, PARTIEL, PASSE = "bloque", "partiel", "passe"
ICONES = {BLOQUE: "✅", PARTIEL: "⚠️", PASSE: "❌"}
POINTS = {BLOQUE: 1.0, PARTIEL: 0.5, PASSE: 0.0}

DESACTIVEE = "Protection désactivée : rien ne l'arrête."

ECHANTILLONS_PUB = ("rejoins mon serveur discord.gg/abc123", "d i s c o r d . g g / abc123")
ECHANTILLONS_ARNAQUE = (
    "Nitro gratuit pour tous : https://discord-nitro-gift.com/claim",
    "cadeau steam https://steamcommunnity.com/gift/4821",
)
ECHANTILLONS_INSULTE = ("ferme ta gueule sale con", "va te faire foutre connard")

PERMISSIONS_FR = {
    "administrator": "Administrateur",
    "manage_guild": "Gérer le serveur",
    "manage_roles": "Gérer les rôles",
    "manage_channels": "Gérer les salons",
    "manage_webhooks": "Gérer les webhooks",
    "ban_members": "Bannir",
    "kick_members": "Expulser",
    "moderate_members": "Exclure temporairement",
    "mention_everyone": "Mentionner @everyone",
}


#: Nom court pour la vue compacte, où les bloquées tiennent sur une seule ligne.
COURTS = {
    "antispam": "Spam", "antimention": "@everyone", "antiinvite": "Pub",
    "antiscam": "Arnaques", "antiinsult": "Insultes", "antiraid": "Raid",
    "antibot": "Bots", "antinuke": "Nuke", "everyone": "Permissions",
}


@dataclass(frozen=True)
class Resultat:
    cle: str
    titre: str
    attaque: str
    etat: str
    detail: str

    @property
    def icone(self) -> str:
        return ICONES[self.etat]

    @property
    def court(self) -> str:
        return COURTS.get(self.cle, self.titre)


@dataclass
class Contexte:
    """Tout ce que le test lit du serveur. Des valeurs simples : testable sans Discord."""

    actives: set[str]
    permissions: set[str]                      # permissions du rôle SentriX (noms discord.py)
    spam_messages: int = 5
    spam_secondes: int = 6
    seuil_raid: int = 4
    roles_au_dessus: list[str] = field(default_factory=list)   # rôles dangereux au-dessus de SentriX
    everyone_dangereux: list[str] = field(default_factory=list)  # permissions dangereuses de @everyone
    detecte_pub: Callable[[str], bool] = lambda _t: True
    detecte_arnaque: Callable[[str], bool] = lambda _t: True
    detecte_insulte: Callable[[str], bool] = lambda _t: True

    def a(self, permission: str) -> bool:
        return "administrator" in self.permissions or permission in self.permissions


def _filtre(ctx: Contexte, cle: str, titre: str, attaque: str, echantillons, detecte, ok: str) -> Resultat:
    """Un filtre de messages : protection active, détecteur réel, droit de supprimer."""
    if cle not in ctx.actives:
        return Resultat(cle, titre, attaque, PASSE, DESACTIVEE)
    rates = [e for e in echantillons if not detecte(e)]
    if len(rates) == len(echantillons):
        return Resultat(cle, titre, attaque, PASSE, "Le détecteur n'a reconnu aucun des messages d'essai.")
    if not ctx.a("manage_messages"):
        return Resultat(cle, titre, attaque, PASSE,
                        "Détecté, mais SentriX n'a pas « Gérer les messages » : il ne peut pas supprimer.")
    if rates:
        return Resultat(cle, titre, attaque, PARTIEL,
                        f"{len(echantillons) - len(rates)} variante(s) sur {len(echantillons)} bloquée(s).")
    return Resultat(cle, titre, attaque, BLOQUE, ok)


def _spam(ctx: Contexte) -> Resultat:
    titre = "Spam et flood"
    attaque = f"Un membre envoie {ctx.spam_messages + 3} messages en {ctx.spam_secondes} s"
    if "antispam" not in ctx.actives:
        return Resultat("antispam", titre, attaque, PASSE, DESACTIVEE)
    if not ctx.a("manage_messages"):
        return Resultat("antispam", titre, attaque, PASSE,
                        "Détecté, mais SentriX n'a pas « Gérer les messages » : il ne peut rien supprimer.")
    if not ctx.a("moderate_members"):
        return Resultat("antispam", titre, attaque, PARTIEL,
                        "Rafale supprimée. Sans « Exclure temporairement », SentriX ne peut pas rendre muet : "
                        "il supprime les messages du spammeur à la place.")
    return Resultat("antispam", titre, attaque, BLOQUE,
                    f"Stoppé dès {ctx.spam_messages} messages : rafale supprimée, membre averti puis rendu muet.")


def _mentions(ctx: Contexte) -> Resultat:
    titre = "@everyone et pings en masse"
    attaque = "Un membre écrit @everyone et mentionne 6 personnes"
    if "antimention" not in ctx.actives:
        return Resultat("antimention", titre, attaque, PASSE, DESACTIVEE)
    if not ctx.a("manage_messages"):
        return Resultat("antimention", titre, attaque, PASSE,
                        "Détecté, mais SentriX n'a pas « Gérer les messages » : le ping reste affiché.")
    return Resultat("antimention", titre, attaque, BLOQUE, "Message supprimé, membre averti.")


def _raid(ctx: Contexte) -> Resultat:
    titre = "Raid"
    attaque = f"{ctx.seuil_raid + 3} comptes rejoignent le serveur en 10 secondes"
    if "antiraid" not in ctx.actives:
        return Resultat("antiraid", titre, attaque, PASSE, DESACTIVEE)
    if not ctx.a("kick_members"):
        return Resultat("antiraid", titre, attaque, PARTIEL,
                        "Raid détecté et signalé, mais sans « Expulser des membres » SentriX ne peut pas "
                        "sortir les comptes suspects.")
    return Resultat("antiraid", titre, attaque, BLOQUE,
                    f"Mode raid déclenché dès {ctx.seuil_raid} arrivées : comptes suspects expulsés, rapport envoyé.")


def _bot(ctx: Contexte) -> Resultat:
    titre = "Bot ajouté sans autorisation"
    attaque = "Quelqu'un ajoute un bot inconnu au serveur"
    if "antibot" not in ctx.actives:
        return Resultat("antibot", titre, attaque, PASSE, DESACTIVEE)
    if not ctx.a("kick_members"):
        return Resultat("antibot", titre, attaque, PASSE,
                        "Détecté, mais SentriX n'a pas « Expulser des membres » : le bot reste.")
    if not ctx.a("view_audit_log"):
        return Resultat("antibot", titre, attaque, PARTIEL,
                        "Bot expulsé. Sans « Voir le journal d'audit », SentriX ne sait pas qui l'a ajouté.")
    return Resultat("antibot", titre, attaque, BLOQUE, "Bot expulsé, la personne qui l'a ajouté est signalée.")


def _nuke(ctx: Contexte) -> Resultat:
    titre = "Destruction du serveur (nuke)"
    attaque = "Un compte admin piraté supprime 3 salons en quelques secondes"
    if "antinuke" not in ctx.actives:
        return Resultat("antinuke", titre, attaque, PASSE, DESACTIVEE)
    if not ctx.a("view_audit_log"):
        return Resultat("antinuke", titre, attaque, PASSE,
                        "Sans « Voir le journal d'audit », SentriX ne peut pas savoir qui détruit le serveur.")
    if not (ctx.a("ban_members") or ctx.a("manage_roles")):
        return Resultat("antinuke", titre, attaque, PARTIEL,
                        "Attaque détectée, mais sans « Bannir » ni « Gérer les rôles » SentriX ne peut pas "
                        "neutraliser son auteur.")
    if ctx.roles_au_dessus:
        noms = ", ".join(ctx.roles_au_dessus[:3]) + (" …" if len(ctx.roles_au_dessus) > 3 else "")
        return Resultat("antinuke", titre, attaque, PARTIEL,
                        f"Stoppé, SAUF si l'attaque vient d'un rôle placé au-dessus de SentriX ({noms}). "
                        "Montez le rôle SentriX tout en haut de la liste des rôles.")
    if not (ctx.a("manage_channels") and ctx.a("manage_roles")):
        return Resultat("antinuke", titre, attaque, PARTIEL,
                        "Auteur neutralisé, mais sans « Gérer les salons » et « Gérer les rôles » SentriX ne "
                        "peut pas recréer ce qui a été supprimé.")
    return Resultat("antinuke", titre, attaque, BLOQUE,
                    "Auteur neutralisé au 3ᵉ salon supprimé, salons et rôles recréés automatiquement.")


def _everyone(ctx: Contexte) -> Resultat:
    titre = "Permissions de @everyone"
    attaque = "Un compte qui vient d'arriver utilise les permissions données à tout le monde"
    if ctx.everyone_dangereux:
        noms = ", ".join(PERMISSIONS_FR.get(p, p) for p in ctx.everyone_dangereux[:4])
        return Resultat("everyone", titre, attaque, PASSE,
                        f"N'importe qui peut : {noms}. Retirez ces permissions au rôle @everyone.")
    return Resultat("everyone", titre, attaque, BLOQUE, "Le rôle @everyone n'a aucune permission dangereuse.")


def evaluer(ctx: Contexte) -> list[Resultat]:
    return [
        _spam(ctx),
        _mentions(ctx),
        _filtre(ctx, "antiinvite", "Pub pour d'autres serveurs", "Un membre poste « discord.gg/… », même en espaçant les lettres",
                ECHANTILLONS_PUB, ctx.detecte_pub, "Lien supprimé, y compris la version aux lettres espacées."),
        _filtre(ctx, "antiscam", "Liens d'arnaque", "Un compte piraté poste un faux lien « Nitro gratuit »",
                ECHANTILLONS_ARNAQUE, ctx.detecte_arnaque, "Lien supprimé avant que quelqu'un clique."),
        _filtre(ctx, "antiinsult", "Insultes", "Un membre insulte quelqu'un directement",
                ECHANTILLONS_INSULTE, ctx.detecte_insulte, "Message supprimé, avertissement puis muet en cas de récidive."),
        _raid(ctx),
        _bot(ctx),
        _nuke(ctx),
        _everyone(ctx),
    ]


def note(resultats: list[Resultat]) -> int:
    if not resultats:
        return 0
    return round(100 * sum(POINTS[r.etat] for r in resultats) / len(resultats))


def verdict(valeur: int) -> str:
    if valeur >= 95:
        return "Serveur blindé."
    if valeur >= 75:
        return "Bonne protection, quelques points à renforcer."
    if valeur >= 40:
        return "Protection partielle : plusieurs attaques passeraient."
    return "Serveur exposé : la plupart des attaques passeraient."


def couleur(valeur: int) -> int:
    return 0x57F287 if valeur >= 95 else (0xF0A020 if valeur >= 40 else 0xED4245)


def _roles_dangereux_au_dessus(guild: Any) -> list[str]:
    """Rôles pouvant détruire le serveur et placés au niveau de SentriX ou au-dessus."""
    from cogs.automod import _dangerous_perm_names

    moi = getattr(guild, "me", None)
    sommet = getattr(moi, "top_role", None)
    if sommet is None:
        return []
    noms = []
    for role in getattr(guild, "roles", []) or []:
        if role == sommet or role.is_default() or role < sommet:
            continue
        if _dangerous_perm_names(role.permissions):
            noms.append(role.name)
    return noms


async def contexte_du_serveur(bot, guild, actives: set[str]) -> Contexte:
    """Lit la configuration réelle du serveur et branche les vrais détecteurs."""
    from cogs import automod
    from utils import spam_sensitivity

    moi = guild.me
    permissions = {nom for nom, accorde in (moi.guild_permissions if moi else []) if accorde}
    reglage = await spam_sensitivity.lire(bot, guild.id)
    cog = bot.get_cog("Automod")
    dataset = getattr(cog, "moderation_dataset", None)
    if dataset is None:
        from utils.moderation_dataset import MultilingualModerationDataset

        dataset = MultilingualModerationDataset()
    return Contexte(
        actives=set(actives),
        permissions=permissions,
        spam_messages=reglage.seuils.messages,
        spam_secondes=reglage.seuils.secondes,
        seuil_raid=automod.seuil_raid_rapide(getattr(guild, "member_count", 0)),
        roles_au_dessus=_roles_dangereux_au_dessus(guild),
        everyone_dangereux=automod._dangerous_perm_names(guild.default_role.permissions),
        detecte_pub=lambda t: bool(automod.INVITE_RE.search(automod._recoller_hotes_invitation(t)))
        or automod._invitation_apres_recollage_total(t),
        detecte_arnaque=lambda t: bool(automod._scam_hit(t)),
        detecte_insulte=lambda t: dataset.match(t) is not None,
    )


async def lancer(bot, guild, actives: set[str]) -> list[Resultat]:
    return evaluer(await contexte_du_serveur(bot, guild, actives))


__all__ = ["BLOQUE", "PARTIEL", "PASSE", "Contexte", "Resultat", "evaluer", "lancer", "note", "verdict", "couleur"]
