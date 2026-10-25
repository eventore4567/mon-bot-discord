"""Plan prudent de visibilité Discord pour le règlement SentriX.

Ni IA probabiliste ni écriture Discord : les indices déterministes sont
noms/catégories, permissions actuelles et identifiants persistés. Une erreur
de classification ne peut jamais rendre un salon privé accessible au rôle
« Vérifié » : les salons inconnus sont conservés sans modification.
"""
from __future__ import annotations

import json
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
# Priorité au portail Discord dans une catégorie sécurité : le CAPTCHA,
# le règlement et stay-muted ne doivent jamais disparaître pour les arrivants.
PORTALS = frozenset({"verification", "verify", "verif", "captcha", "reglement", "rules", "rule", "stay", "muted"})

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
    # Catégories membres 100 % synchronisées et sans aucun salon sensible :
    # appliquer à la catégorie au lieu de rompre chaque synchronisation.
    category_gates: list = field(default_factory=list)
    protected: dict[int, str] = field(default_factory=dict)
    untouched: dict[int, str] = field(default_factory=dict)
    sensitive_public: list = field(default_factory=list)
    # Diagnostic uniquement : NE JAMAIS appliquer ces corrections dans le
    # parcours qui verrouille les salons membres.
    secure_sensitive: list = field(default_factory=list)
    log_destinations: list = field(default_factory=list)
    suspected_logs: list = field(default_factory=list)
    staff_channels: list = field(default_factory=list)
    portal: list = field(default_factory=list)

    def preview(self) -> str:
        """Résumé compréhensible sans exposer l'audit technique ni l'IA."""
        nb = len(self.gate)
        categories = len(self.category_gates)
        labels = ", ".join(
            "#" + str(getattr(channel, "name", getattr(channel, "id", "?")))
            for channel in self.gate[:4]
        )
        if nb > 4:
            labels += "…"
        protected_count = len(self.protected) + len(self.untouched)
        sensitive = len(self.secure_sensitive)
        lines = [
            f"**Salons membres : {nb}**" + (f" ({labels})" if labels else ""),
        ]
        if categories:
            lines.append(f"**Catégories membres : {categories}**")
        lines.append(f"**Salons protégés ou inchangés : {protected_count}**")
        if sensitive:
            lines.append(f"**À vérifier séparément : {sensitive} salon(s) sensibles**")
        lines.append("Les salons staff, logs et vérification restent protégés.")
        return "\n".join(lines)


def _safe_ai_label(value: object) -> str:
    """Données non fiables, limitées en taille, sans mention Discord ni URL."""
    value = str(value or "")
    value = re.sub(r"<(?:@!?|@&|#)\d+>", "[mention]", value)
    value = re.sub(r"@(?:everyone|here)", "[mention]", value, flags=re.I)
    value = re.sub(r"https?://\S+", "[url]", value, flags=re.I)
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return value[:60]


def ai_access_review_context(plan: AccessPlan) -> str:
    """Synthèse minimale à envoyer à l'IA sur clic explicite de l'admin.

    Jamais de contenu de messages, identifiant Discord, propriétaire,
    liste de membres ni overwrite brut. Les noms fournis sont des DONNÉES,
    jamais des instructions ni une preuve que des permissions sont sûres.
    """
    def sample(channels):
        return [
            {
                "salon": _safe_ai_label(getattr(c, "name", "")),
                "categorie": _safe_ai_label(getattr(getattr(c, "category", None), "name", "")),
            }
            for c in channels[:12]
        ]

    return json.dumps({
        "salons_publics_membres": sample(plan.gate),
        "salons_staff_ou_logs": sample(plan.staff_channels),
        "destinations_logs_enregistrees": sample(plan.log_destinations),
        "salons_logs_suspectes_par_nom": sample(plan.suspected_logs),
        "salons_sensibles_a_verifier_manuellement": sample(plan.secure_sensitive),
        "comptes": {
            "verrouillage_membres": len(plan.gate),
            "sensibles_a_examiner": len(plan.secure_sensitive),
            "proteges": len(plan.protected),
            "ambigus_laisses_intacts": len(plan.untouched),
        },
    }, ensure_ascii=False)


STAFF_ROLE_WORDS = frozenset({
    "staff", "admin", "administrateur", "administrateurs", "moderation",
    "moderateur", "moderateurs", "modo", "modos", "fondateur", "fondateurs",
    "direction", "responsable", "responsables", "manager", "managers",
})


def has_explicit_staff_access(channel, everyone) -> bool:
    """Preuve : une permission staff explicite sur le salon OU sa catégorie synchronisée.

    Une catégorie non synchronisée n'est pas une preuve d'accès au salon.
    On n'invente jamais un rôle staff et on n'ouvre jamais un salon privé.
    """
    sources = [getattr(channel, "overwrites", {}) or {}]
    category = getattr(channel, "category", None)
    if category is not None and bool(getattr(channel, "permissions_synced", False)):
        sources.append(getattr(category, "overwrites", {}) or {})
    for overwrites in sources:
        for role, overwrite in overwrites.items():
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


def plan_access(
    guild, *, verification_channel_id: int, configured_ids=(), special_ids=(),
    log_ids=(), verified_role=None,
) -> AccessPlan:
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
        if (
            own & ONBOARDING
            and not own & SENSITIVE
            and channel.id not in log_destinations
            and (not parent_words & SENSITIVE or own & PORTALS)
        ):
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
            elif own & {"logs", "log", "audit", "audits", "transcript", "transcripts", "dossiers"}:
                # Nom suggestif, mais pas une destination officielle log_config.
                plan.suspected_logs.append(channel)
            else:
                plan.staff_channels.append(channel)
            # Un ancien overwrite peut laisser le rôle Vérifié lire des logs
            # pourtant invisibles à @everyone. Ne pas prendre "déjà privé"
            # pour une garantie de confidentialité du rôle final.
            verified_overwrite = (
                channel.overwrites_for(verified_role)
                if verified_role is not None else None
            )
            explicit_verified_allow = (
                verified_overwrite is not None
                and verified_overwrite.view_channel is True
            )
            category = getattr(channel, "category", None)
            if (
                not explicit_verified_allow
                and verified_role is not None
                and category is not None
                and bool(getattr(channel, "permissions_synced", False))
            ):
                inherited = category.overwrites_for(verified_role)
                explicit_verified_allow = inherited.view_channel is True

            if current_public:
                plan.sensitive_public.append(channel)
                if has_explicit_staff_access(channel, everyone):
                    plan.secure_sensitive.append(channel)
            elif explicit_verified_allow:
                # Révoquer seulement cet accès inadéquat ; les autres rôles
                # (modération, propriétaires, administrateurs) sont intacts.
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

    # Les permissions de catégorie se propagent aux salons synchronisés.
    # Écrire un overwrite directement sur chaque salon casserait cet héritage.
    # Autoriser la modification de la catégorie SEULEMENT si l'ensemble de
    # ses enfants sont publics, membres, et toujours synchronisés. Une seule
    # exception (staff, logs, portail, privé, inconnu) annule l'opération de
    # catégorie pour éviter d'affecter accidentellement cette exception.
    gate_ids = {channel.id for channel in plan.gate}
    for category in categories:
        children = [
            ch for ch in guild.channels
            if ch not in categories and getattr(ch, "category", None) == category
        ]
        synced_gates = [
            ch for ch in children
            if ch.id in gate_ids and bool(getattr(ch, "permissions_synced", False))
        ]
        if not synced_gates:
            continue
        safe_whole_category = (
            bool(children)
            and category.id not in plan.protected
            and all(ch.id in gate_ids for ch in children)
            and all(bool(getattr(ch, "permissions_synced", False)) for ch in children)
            and bool(category.permissions_for(everyone).view_channel)
        )
        if safe_whole_category:
            plan.category_gates.append(category)
            continue
        # Une catégorie mixte nécessite un choix explicite de l'admin.
        # Ne jamais casser sa synchro silencieusement pour modifier un seul
        # des salons membres.
        synced_ids = {ch.id for ch in synced_gates}
        plan.gate = [ch for ch in plan.gate if ch.id not in synced_ids]
        gate_ids.difference_update(synced_ids)
        for ch in synced_gates:
            plan.untouched[ch.id] = "catégorie synchronisée mixte : revue manuelle"
    return plan
