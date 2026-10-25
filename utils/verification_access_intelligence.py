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
    portal: list = field(default_factory=list)

    def preview(self) -> str:
        shown = ", ".join(getattr(c, "name", str(c.id)) for c in self.gate[:7]) or "aucun"
        trailing = "…" if len(self.gate) > 7 else ""
        alerts = len(self.sensitive_public)
        return (
            f"**À verrouiller : {len(self.gate)} salon(s) publics**\n"
            f"{shown}{trailing}\n"
            f"**À préserver : {len(self.protected)} salon(s)/catégories privés, staff, logs ou vérification**\n"
            f"**À examiner : {len(self.untouched)} salon(s) ambigus, laissés intacts**\n"
            + (
                f"**Attention : {alerts} salon(s) staff/logs paraissent publics.** "
                "Ils ne seront pas ouverts au rôle Vérifié : vérifiez leur accès staff séparément."
                if alerts else ""
            )
        ).strip()


def plan_access(guild, *, verification_channel_id: int, configured_ids=(), special_ids=()) -> AccessPlan:
    plan = AccessPlan()
    everyone = guild.default_role
    conf_ids = {int(v) for v in configured_ids if v}
    special = {int(v) for v in special_ids if v}
    protected_ids = conf_ids | special | {int(verification_channel_id)}
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
        # Toujours protéger une destination sauvegardée (logs, portails,
        # honeypot), même si elle a été renommée en « général ».
        if channel.id in protected_ids or (parent is not None and parent.id in plan.protected):
            plan.protected[channel.id] = "configuration/portail/catégorie sensible"
            if current_public and (own | parent_words) & SENSITIVE:
                plan.sensitive_public.append(channel)
            continue
        if own & (SENSITIVE | ONBOARDING):
            plan.protected[channel.id] = "staff/logs/accueil"
            if current_public and own & SENSITIVE:
                plan.sensitive_public.append(channel)
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
