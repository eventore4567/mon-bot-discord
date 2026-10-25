"""Plan prudent de visibilité Discord pour le règlement SentriX.

Ni IA probabiliste ni écriture Discord : les indices déterministes sont
noms/catégories, permissions actuelles et identifiants persistés. Une erreur
de classification ne peut jamais rendre un salon privé accessible au rôle
« Vérifié » : les salons inconnus sont conservés sans modification.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def tokens(text: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKD", str(text or "").casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return frozenset(re.findall(r"[a-z0-9]+", normalized))


# Les termes ont des frontières : « staff » oui, « staffing-public » est
# examiné selon sa catégorie, et « verification-auto » reste un portail.
SENSITIVE = frozenset({
    "staff", "admin", "administration", "moderation", "moderateurs", "moderateur",
    "modo", "modos", "logs", "log", "audit", "audits", "sanctions",
    "modmail", "direction", "fondateur", "fondateurs", "private", "prive",
    "securite", "security", "transcript", "transcripts", "dossiers",
    "candidatures", "enquetes", "reports",
})
# Portails que les nouveaux membres doivent conserver AVANT la vérification.
ONBOARDING = frozenset({
    "verification", "verify", "verif", "captcha", "reglement", "rules",
    "rule", "bienvenue", "welcome", "arrivee", "depart", "start",
    "commencer", "onboarding", "informations", "information", "info",
    "aide", "help", "support", "ticket", "tickets", "stay", "muted",
})
# Gater seulement des salons manifestement destinés aux membres ; les salons
# sans catégorie claire restent intactes jusqu'à décision d'un administrateur.
MEMBER = frozenset({
    "general", "chat", "discussion", "discussions", "blabla", "parler",
    "communaute", "community", "membres", "membre", "public",
    "media", "medias", "images", "photos", "video", "videos",
    "clips", "memes", "jeux", "game", "games", "gaming", "musique",
    "music", "vocal", "vocaux", "voice", "offtopic", "partage",
    "partages", "commandes", "bot", "bots", "forum", "salon", "salons",
})


@dataclass
class AccessPlan:
    gate: list = field(default_factory=list)
    protected: dict[int, str] = field(default_factory=dict)
    untouched: dict[int, str] = field(default_factory=dict)
    sensitive_public: list = field(default_factory=list)
    secure_sensitive: list = field(default_factory=list)
    log_destinations: list = field(default_factory=list)
    staff_channels: list = field(default_factory=list)
    portal: list = field(default_factory=list)

    def preview(self) -> str:
        names = ", ".join(getattr(c, "name", str(c.id)) for c in self.gate[:7]) or "aucun"
        if len(self.gate) > 7:
            names += "…"
        pending = len(self.sensitive_public) - len(self.secure_sensitive)
        lines = [
            f"**Salons membres à verrouiller : {len(self.gate)}**",
            names,
            f"**Staff/logs publics sécurisables : {len(self.secure_sensitive)}**",
            (
                "**Destinations logs enregistrées : **"
                + (", ".join("#" + str(getattr(c, "name", c.id)) for c in self.log_destinations[:5]) or "aucune")
                + ("…" if len(self.log_destinations) > 5 else "")
            ),
            (
                "**Salons staff repérés : **"
                + (", ".join("#" + str(getattr(c, "name", c.id)) for c in self.staff_channels[:5]) or "aucun")
                + ("…" if len(self.staff_channels) > 5 else "")
            ),
            f"**Salons/catégories protégés : {len(self.protected)}**",
            f"**Salons ambigus, laissés inchangés : {len(self.untouched)}**",
        ]
        if pending:
            lines.append(
                f"**Attention : {pending} salon(s) staff/logs semblent publics "
                "mais n'ont pas de rôle staff explicitement autorisé.** "
                "Vérifiez-les manuellement."
            )
        lines.append(
            "Aucun accès privé ne sera donné au rôle Vérifié. "
            "Les salons inconnus et les espaces de vérification restent inchangés."
        )
        return "\n".join(lines)


STAFF_ROLE_WORDS = frozenset({
    "staff", "admin", "administrateur", "administrateurs", "moderation",
    "moderateur", "moderateurs", "modo", "modos", "fondateur", "fondateurs",
    "direction", "responsable", "responsables", "manager", "managers",
})


def has_explicit_staff_access(channel, everyone) -> bool:
    """Preuve locale : un rôle staff existant bénéficie déjà de l'accès.

    On ne déduit JAMAIS un rôle staff via IA pour lui ouvrir un salon privé.
    """
    for role, overwrite in getattr(channel, "overwrites", {}).items():
        if role == everyone or getattr(overwrite, "view_channel", None) is not True:
            continue
        role_name = tokens(getattr(role, "name", ""))
        permissions = getattr(role, "permissions", None)
        privileged = bool(permissions and any(
            getattr(permissions, attr, False) for attr in (
                "administrator", "manage_guild", "manage_channels",
                "ban_members", "kick_members",
            )
        ))
        if privileged or (role_name & STAFF_ROLE_WORDS):
            return True
    return False


def plan_access(guild, *, verification_channel_id: int, configured_ids=(), special_ids=(), log_ids=()) -> AccessPlan:
    plan = AccessPlan()
    everyone = guild.default_role
    conf_ids = {int(v) for v in configured_ids if v}
    special = {int(v) for v in special_ids if v}
    log_destinations = {int(v) for v in log_ids if v}
    protected_ids = conf_ids | special | log_destinations | {int(verification_channel_id)}
    categories = list(getattr(guild, "categories", ()))
    for category in categories:
        category_tokens = tokens(getattr(category, "name", ""))
        if category.id in protected_ids or category_tokens & (SENSITIVE | ONBOARDING):
            plan.protected[category.id] = "catégorie protégée"

    for channel in list(guild.channels):
        if channel in categories:
            continue
        parent = getattr(channel, "category", None)
        own = tokens(getattr(channel, "name", ""))
        parent_words = tokens(getattr(parent, "name", "")) if parent else frozenset()
        current_public = bool(channel.permissions_for(everyone).view_channel)
        # Un portail de vérification doit RESTER visible. Les logs persistés
        # et les catégories staff gardent leur classification après renommage.
        if channel.id == verification_channel_id or channel.id in special or (
            channel.id in conf_ids and channel.id not in log_destinations
        ):
            plan.protected[channel.id] = "portail/configuration enregistrée"
            continue
        # Exemple réel : #verification et #stay-muted dans la catégorie
        # « Sécurité SentriX ». Ce sont des portails, PAS des salons staff
        # à cacher ; leur fonction passe avant le nom de leur catégorie.
        if own & ONBOARDING and not own & SENSITIVE and channel.id not in log_destinations:
            plan.protected[channel.id] = "portail d'accueil/vérification"
            continue
        sensitive = bool(
            channel.id in log_destinations
            or (own | parent_words) & SENSITIVE
            or (parent is not None and parent.id in plan.protected and not parent_words & ONBOARDING)
        )
        if sensitive:
            plan.protected[channel.id] = "staff/logs/sécurité"
            if channel.id in log_destinations:
                plan.log_destinations.append(channel)
            else:
                plan.staff_channels.append(channel)
            if current_public:
                plan.sensitive_public.append(channel)
                if has_explicit_staff_access(channel, everyone):
                    plan.secure_sensitive.append(channel)
            continue
        if own & ONBOARDING or parent_words & ONBOARDING:
            plan.protected[channel.id] = "accueil/vérification"
            continue
        if not current_public:
            plan.protected[channel.id] = "déjà privé"
            continue
        # Les catégories de membres peuvent compléter l'indice d'un nom
        # générique, sans annuler une exclusion explicite.
        if own & MEMBER or parent_words & MEMBER:
            plan.gate.append(channel)
        else:
            plan.untouched[channel.id] = "fonction inconnue"
    return plan
