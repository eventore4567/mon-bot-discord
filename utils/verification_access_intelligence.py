"""Plan prudent de visibilité Discord pour le règlement SentriX.

Ni IA probabiliste ni écriture Discord : la visibilité réelle de @everyone
sert de critère d'appartenance aux espaces membres. Les exceptions sensibles,
les salons privés et les accès d'accueil/vérification restent intacts.
Un salon privé ne doit jamais être ouvert au rôle « Vérifié ».
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field


def is_voice_channel(channel) -> bool:
    """Voice and stage voice only; category permissions are handled separately."""
    return str(getattr(channel, "type", "")) in {"voice", "stage_voice"}


def _bits(value) -> int:
    return int(getattr(value, "value", 0) or 0)


def newcomer_access(channel, everyone, entry_roles=()) -> tuple[bool, bool]:
    """(voir, se connecter) pour un membre qui vient d'arriver, non vérifié.

    Un nouvel arrivant ne porte pas que @everyone : rôle automatique, rôle
    « non vérifié », rôle d'arrivée d'un autre bot… Un salon ouvert par l'un
    d'eux lui est accessible même si @everyone est masqué. Sans rôle d'arrivée,
    on garde exactement l'ancien calcul (permissions de @everyone).

    L'ordre est celui de Discord : permissions de serveur cumulées, dérogation
    @everyone, puis dérogations de rôles (les autorisations l'emportent sur les
    refus). Sans « Voir le salon », aucune autre permission ne compte.
    """
    roles = [role for role in entry_roles if role is not None and role != everyone]
    if not roles:
        perms = channel.permissions_for(everyone)
        view = bool(getattr(perms, "view_channel", False))
        return view, view and bool(getattr(perms, "connect", view))
    import discord

    value = _bits(getattr(everyone, "permissions", None))
    for role in roles:
        value |= _bits(getattr(role, "permissions", None))
    if discord.Permissions(value).administrator:
        return True, True
    allow, deny = channel.overwrites_for(everyone).pair()
    value = (value & ~deny.value) | allow.value
    role_allow = role_deny = 0
    for role in roles:
        allow, deny = channel.overwrites_for(role).pair()
        role_allow |= allow.value
        role_deny |= deny.value
    perms = discord.Permissions((value & ~role_deny) | role_allow)
    return perms.view_channel, perms.view_channel and perms.connect


def opening_roles(channel, everyone, entry_roles=()) -> list:
    """Rôles d'arrivée dont la dérogation ouvre explicitement ce salon."""
    return [
        role for role in entry_roles
        if role is not None and role != everyone
        and channel.overwrites_for(role).view_channel is True
    ]


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
# Uniquement les portails indispensables avant la validation. Les salons
# d'annonces, d'informations, de giveaways, d'aide ou de discussion sont
# verrouillables s'ils sont PUBLICS, sauf s'ils sont référencés explicitement
# dans la configuration (Onboarding Discord, règlement, bienvenue, etc.).
ONBOARDING = frozenset({
    "verification", "verify", "verif", "captcha", "reglement", "rules",
    "rule", "bienvenue", "welcome", "arrivee", "start", "commencer",
    "onboarding", "stay", "muted",
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
    voice_already_locked: list = field(default_factory=list)
    # En catégorie mixte, seules les surfaces membres seront écrites : cela
    # désynchronise ces salons, après confirmation explicite de l'aperçu.
    mixed_synced: list = field(default_factory=list)
    # Visibles des nouveaux membres mais classés par leur NOM seulement
    # (portail présumé, catégorie de vérification) : jamais verrouillés
    # d'office, proposés à l'administrateur dans la sélection manuelle.
    review: list = field(default_factory=list)
    # Rôles reçus à l'arrivée pris en compte, et pour chaque salon à
    # verrouiller, les rôles d'arrivée qui l'ouvrent (en plus de @everyone).
    entry_roles: list = field(default_factory=list)
    opened_by: dict[int, list] = field(default_factory=dict)
    # Salons ouverts seulement par un rôle FACULTATIF : y ajouter « Vérifié »
    # les ouvrirait à tous les vérifiés. Ils restent tels quels.
    role_restricted: list = field(default_factory=list)
    verified_only: list = field(default_factory=list)
    # Salons par défaut de l'Onboarding Discord visibles des arrivants :
    # Discord refuse de les masquer (erreur 350003) tant qu'ils y figurent.
    onboarding: list = field(default_factory=list)
    manual_excluded: list = field(default_factory=list)
    manual_included: list = field(default_factory=list)
    # Choix manuels refusés, avec la raison, pour l'expliquer à l'admin.
    refused: dict[int, str] = field(default_factory=dict)

    def preview(self) -> str:
        """Résumé compact : quoi verrouiller, quoi confirmer, quoi reste intact.

        Jamais de liste interminable : au plus quelques noms par groupe, le
        reste en « +N ». Les noms des salons staff/logs ne sont pas affichés.
        """
        def names(channels, limit=6, hash_=True) -> str:
            shown = [
                ("#" if hash_ else "") + str(getattr(c, "name", getattr(c, "id", "?")))
                for c in channels[:limit]
            ]
            extra = len(channels) - limit
            return ", ".join(shown) + (f" +{extra}" if extra > 0 else "")

        text_channels = [ch for ch in self.gate if not is_voice_channel(ch)]
        voice_channels = [ch for ch in self.gate if is_voice_channel(ch)]
        lines = ["**🔒 À verrouiller**"]
        line = f"Salons textuels à verrouiller : {len(text_channels)}"
        lines.append(line + (f" — {names(text_channels)}" if text_channels else ""))
        line = f"Vocaux à verrouiller : {len(voice_channels)}"
        lines.append(line + (f" — {names(voice_channels, hash_=False)}" if voice_channels else ""))
        if self.category_gates:
            lines.append(f"Catégories membres synchronisées conservées : {len(self.category_gates)}")
        if self.mixed_synced:
            lines.append(
                f"Catégories mixtes : {len(self.mixed_synced)} salon(s) membre(s) "
                "seront désynchronisés de leur catégorie."
            )
        opening = {
            str(getattr(role, "name", "?"))
            for roles in self.opened_by.values() for role in roles
        }
        if opening:
            lines.append(
                "Accès retiré aux rôles d'arrivée : " + ", ".join(sorted(opening)[:4])
                + " (les vérifiés gardent l'accès)"
            )
        if self.manual_included:
            lines.append(f"Ajoutés par vous : {names(self.manual_included, 4)}")

        if self.review:
            lines.append(
                f"\n**✋ À confirmer : {len(self.review)}** — {names(self.review, 5)}\n"
                "-# Classés comme accueil/vérification d'après leur nom. "
                "Ajoutez-les s'ils doivent être verrouillés."
            )

        reasons = list(self.protected.values())
        staff = sum(1 for r in reasons if r in {"staff/logs/sécurité", "catégorie protégée"})
        portal = sum(1 for r in reasons if "portail" in r or "accueil" in r or "vérification" in r)
        private = sum(1 for r in reasons if r == "déjà privé")
        kept = len(self.protected) + len(self.untouched) - len(self.review)
        detail = " · ".join(
            f"{label} {count}" for label, count in (
                ("staff/logs", staff),
                ("accueil/vérification", max(portal - len(self.review), 0)),
                ("déjà privés", private),
            ) if count
        )
        lines.append(
            f"\n**🛡️ Salons protégés ou inchangés : {max(kept, 0)}**"
            + (f" — {detail}" if detail else "")
        )
        if self.onboarding:
            lines.append(
                f"📌 Onboarding Discord : {len(self.onboarding)} — {names(self.onboarding, 5)}\n"
                "-# Discord interdit de les masquer : retirez-les des salons par défaut "
                "(Paramètres du serveur → Onboarding) pour pouvoir les verrouiller."
            )
        if self.voice_already_locked:
            lines.append(f"Vocaux déjà restreints : {len(self.voice_already_locked)}")
        if self.role_restricted:
            lines.append(
                f"Réservés à un rôle facultatif : {len(self.role_restricted)} "
                "(jamais ouverts aux vérifiés)"
            )
        if self.manual_excluded:
            lines.append(f"Exclus par vous : {names(self.manual_excluded, 4)}")
        public_ids = {c.id for c in self.sensitive_public}
        opened_to_verified = [c for c in self.secure_sensitive if c.id not in public_ids]
        if self.sensitive_public:
            lines.append(
                f"⚠️ Salons sensibles à vérifier manuellement : {len(public_ids)} "
                "staff/logs visibles des nouveaux membres"
            )
        if opened_to_verified:
            lines.append(
                f"⚠️ Salons sensibles à vérifier manuellement : {len(opened_to_verified)} "
                "staff/logs ouverts au rôle Vérifié"
            )
        if self.sensitive_public or opened_to_verified:
            lines.append("-# Jamais modifiés ici : corrigez leurs permissions à la main.")
        if self.refused:
            lines.append(f"Choix refusés : {len(self.refused)} (staff, logs, portail ou déjà privé)")
        lines.append("-# Vérifiez la liste avant de confirmer. Staff, logs et vérification restent protégés.")
        text = "\n".join(lines)
        return text if len(text) <= 1700 else text[:1697] + "…"


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
    log_ids=(), onboarding_ids=(), verified_role=None, entry_roles=(),
    include_ids=(), exclude_ids=(),
) -> AccessPlan:
    plan = AccessPlan()
    everyone = guild.default_role
    conf_ids = {int(v) for v in configured_ids if v}
    special = {int(v) for v in special_ids if v}
    log_destinations = {int(v) for v in log_ids if v}
    onboarding = {int(v) for v in onboarding_ids if v}
    include = {int(v) for v in include_ids if v}
    exclude = {int(v) for v in exclude_ids if v}
    entry = [
        role for role in entry_roles
        if role is not None and role != everyone and role != verified_role
    ]
    plan.entry_roles = list(entry)
    protected_ids = conf_ids | special | log_destinations | onboarding | {int(verification_channel_id)}
    categories = list(getattr(guild, "categories", ()))
    for category in categories:
        category_tokens = tokens(getattr(category, "name", ""))
        if category.id in protected_ids or category_tokens & (SENSITIVE | ONBOARDING):
            plan.protected[category.id] = "catégorie protégée"

    def to_review(channel, reason: str) -> None:
        # Classé par son nom seulement : l'admin tranche dans la sélection.
        if channel.id in include:
            plan.manual_included.append(channel)
            plan.gate.append(channel)
            return
        plan.protected[channel.id] = reason
        plan.review.append(channel)

    for channel in list(guild.channels):
        if channel in categories:
            continue
        parent = getattr(channel, "category", None)
        own = tokens(getattr(channel, "name", ""))
        parent_words = tokens(getattr(parent, "name", "")) if parent else frozenset()
        current_public, can_connect = newcomer_access(channel, everyone, entry)
        # Un portail de vérification doit RESTER visible. Les logs persistés
        # et les catégories staff gardent leur classification après renommage.
        if channel.id in onboarding and channel.id != verification_channel_id and current_public:
            plan.protected[channel.id] = "Onboarding Discord"
            plan.onboarding.append(channel)
            if channel.id in include:
                plan.refused[channel.id] = "salon par défaut de l'Onboarding Discord"
            continue
        if channel.id == verification_channel_id or channel.id in special or channel.id in onboarding or (
            channel.id in conf_ids and channel.id not in log_destinations
        ):
            plan.protected[channel.id] = "portail/configuration enregistrée"
            if channel.id in include:
                plan.refused[channel.id] = "portail enregistré"
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
            if current_public:
                to_review(channel, "portail d'accueil/vérification")
            else:
                plan.protected[channel.id] = "portail d'accueil/vérification"
            continue
        sensitive = bool(
            channel.id in log_destinations
            or (own | parent_words) & SENSITIVE
            or (parent is not None and parent.id in plan.protected and not parent_words & ONBOARDING)
        )
        if sensitive:
            plan.protected[channel.id] = "staff/logs/sécurité"
            if channel.id in include:
                plan.refused[channel.id] = "salon staff, logs ou sécurité"
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
        if own & ONBOARDING:
            plan.protected[channel.id] = "accueil/vérification"
            continue
        if not current_public:
            plan.protected[channel.id] = "déjà privé"
            if channel.id in include:
                plan.refused[channel.id] = "déjà invisible aux nouveaux membres"
            verified_view = (
                verified_role is not None
                and channel.overwrites_for(verified_role).view_channel is True
            )
            if verified_view:
                plan.verified_only.append(channel)
            elif any(
                getattr(target, "id", None) != getattr(everyone, "id", None)
                and getattr(value, "view_channel", None) is True
                for target, value in (getattr(channel, "overwrites", {}) or {}).items()
            ):
                # Ouvert par un rôle facultatif (choix d'Onboarding, VIP…) :
                # y ajouter « Vérifié » l'ouvrirait à TOUS les vérifiés.
                plan.role_restricted.append(channel)
            if is_voice_channel(channel):
                plan.voice_already_locked.append(channel)
            continue
        # Un vocal peut être visible mais interdire déjà la connexion à
        # @everyone. Ne pas écraser une interdiction existante en donnant
        # arbitrairement Connect au rôle Vérifié.
        if is_voice_channel(channel) and not can_connect:
            plan.protected[channel.id] = "vocal déjà restreint"
            plan.voice_already_locked.append(channel)
            continue
        # Dans une catégorie de vérification (portail), un salon visible sans
        # nom de portail reste au jugement de l'admin : aide aux arrivants ?
        if parent_words & PORTALS:
            to_review(channel, "dans une catégorie de vérification")
            continue
        if channel.id in exclude:
            plan.protected[channel.id] = "exclu par l'administrateur"
            plan.manual_excluded.append(channel)
            continue
        # Règle principale : si un nouveau membre peut voir ce salon et
        # qu'aucune exception sensible/portail/privé ne s'applique, c'est un
        # espace membre, quel que soit son nom : annonces, giveaways,
        # discussion, forums, vidéos, salon vocal... Une catégorie nommée
        # « Bienvenue » ne protège plus ses enfants : seul le salon d'accueil
        # lui-même (nom ou configuration) reste ouvert.
        # L'admin doit voir l'aperçu et confirmer avant la moindre écriture.
        plan.gate.append(channel)
        opened = opening_roles(channel, everyone, entry)
        if opened:
            plan.opened_by[channel.id] = opened

    # Une exclusion manuelle vaut aussi pour un salon ajouté à la main.
    for channel in list(plan.manual_included):
        if channel.id in exclude:
            plan.manual_included.remove(channel)
            plan.gate.remove(channel)
            plan.protected[channel.id] = "exclu par l'administrateur"
            plan.manual_excluded.append(channel)
        else:
            opened = opening_roles(channel, everyone, entry)
            if opened:
                plan.opened_by[channel.id] = opened
    for channel_id in include:
        if channel_id not in plan.refused and all(ch.id != channel_id for ch in plan.gate):
            plan.refused.setdefault(channel_id, "non proposé au verrouillage")

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
            and newcomer_access(category, everyone, entry)[0]
        )
        if safe_whole_category:
            plan.category_gates.append(category)
            opened = opening_roles(category, everyone, entry)
            if opened:
                plan.opened_by[category.id] = opened
            continue
        # Catégorie mixte (ex. #annonces et #logs sous une même catégorie) :
        # ne JAMAIS toucher les permissions de la catégorie. Après un aperçu
        # signalant explicitement la désynchronisation, appliquer les deux
        # overwrites uniquement sur les salons membres publics sélectionnés.
        # Ainsi les salons staff/logs/portails restent inchangés.
        plan.mixed_synced.extend(synced_gates)
    return plan


def decision_rows(guild, plan: AccessPlan) -> list[str]:
    """Une ligne par salon pour le journal : type, décision, rôle qui ouvre.

    Lecture seule. Sert à comparer l'aperçu à la structure réelle d'un
    serveur sans rien y modifier.
    """
    gate_ids = {channel.id for channel in plan.gate}
    review_ids = {channel.id for channel in plan.review}
    category_ids = {category.id for category in plan.category_gates}
    rows = []
    for channel in getattr(guild, "channels", ()):
        channel_id = getattr(channel, "id", 0)
        flag = ""
        if channel_id in {c.id for c in plan.sensitive_public}:
            flag = " !VISIBLE_ARRIVANTS"
        elif channel_id in {c.id for c in plan.secure_sensitive}:
            flag = " !OUVERT_AU_ROLE_VERIFIE"
        if channel_id in gate_ids or channel_id in category_ids:
            decision = "VERROUILLER"
        elif channel_id in review_ids:
            decision = "A_CONFIRMER"
        else:
            decision = "INCHANGE:" + str(plan.protected.get(channel_id, "hors plan"))
        opened = ",".join(
            str(getattr(role, "name", "?")) for role in plan.opened_by.get(channel_id, ())
        )
        rows.append(
            f"{channel_id} {getattr(channel, 'type', '?')} "
            f"cat={getattr(getattr(channel, 'category', None), 'id', '-')} "
            f"#{getattr(channel, 'name', '?')} -> {decision}"
            + (f" via={opened}" if opened else "") + flag
        )
    return rows
