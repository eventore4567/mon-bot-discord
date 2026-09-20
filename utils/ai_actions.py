"""Routeur d'actions naturelles de SentriX.

Cette couche NE réimplémente aucune commande métier. Elle transforme une demande
naturelle en une action strictement autorisée, résout les paramètres ambigus et rend
une ligne de commande existante. L'exécution finale reste assurée par commands.Bot :
matrice d'accès, checks d'action, hiérarchie Discord, services métier, logs et
persistance restent donc exactement ceux des commandes classiques.

Le modèle IA est uniquement un classifieur/extracteur de paramètres. Il ne décide
jamais des permissions et ne peut pas choisir une action absente du registre.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import json
import re
import unicodedata
from typing import Any

import discord

from utils import ai_service


@dataclass(frozen=True, slots=True)
class ActionSpec:
    intent: str
    command: str | None
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    target_kind: str | None = None
    risk: str = "low"
    confirm: bool = False
    description: str = ""


@dataclass(slots=True)
class ParsedAction:
    intent: str
    slots: dict[str, Any]
    confidence: int = 100
    source: str = "local"

    @property
    def spec(self) -> ActionSpec | None:
        return ACTIONS.get(self.intent)


@dataclass(slots=True)
class MemberResolution:
    member: discord.Member | None = None
    ambiguous: tuple[discord.Member, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LogProposal:
    category: str
    label: str
    channel_id: int
    channel_name: str
    score: int
    evidence: str = ""


@dataclass(slots=True)
class ChannelResolution:
    channel: Any | None = None
    ambiguous: tuple[Any, ...] = ()
    error: str | None = None


ACTIONS: dict[str, ActionSpec] = {
    "moderation.ban": ActionSpec(
        "moderation.ban", "ban", ("target",), ("reason",), "member", "medium",
        description="bannir définitivement un membre",
    ),
    "moderation.tempban": ActionSpec(
        "moderation.tempban", "tempban", ("target", "duration"), ("reason",), "member", "medium",
        description="bannir temporairement un membre pendant une durée",
    ),
    "moderation.unban": ActionSpec(
        "moderation.unban", "unban", ("user_id",), ("reason",), None, "medium",
        description="débannir un utilisateur via son identifiant Discord",
    ),
    "moderation.kick": ActionSpec(
        "moderation.kick", "kick", ("target",), ("reason",), "member", "medium",
        description="expulser un membre",
    ),
    "moderation.warn": ActionSpec(
        "moderation.warn", "warn", ("target",), ("reason",), "member", "low",
        description="avertir un membre",
    ),
    "moderation.mute": ActionSpec(
        "moderation.mute", "mute", ("target", "duration"), ("reason",), "member", "low",
        description="mettre un membre en mute/timeout pendant une durée",
    ),
    "moderation.unmute": ActionSpec(
        "moderation.unmute", "unmute", ("target",), ("reason",), "member", "low",
        description="retirer le mute/timeout d'un membre",
    ),
    "moderation.purge": ActionSpec(
        "moderation.purge", "clear", ("count",), (), None, "high",
        description="supprimer les derniers messages du salon",
    ),
    "moderation.warnings": ActionSpec(
        "moderation.warnings", "warnings", ("target",), (), "member", "low",
        description="afficher les avertissements d'un membre",
    ),
    "moderation.history": ActionSpec(
        "moderation.history", "modhistory", ("target",), (), "member", "low",
        description="afficher l'historique complet des sanctions d'un membre",
    ),
    "navigation.help": ActionSpec(
        "navigation.help", "help", (), ("query",), None, "low",
        description="ouvrir le centre d'aide ou rechercher une commande",
    ),
    "navigation.setup": ActionSpec(
        "navigation.setup", "setup", (), ("section",), None, "low",
        description="ouvrir le centre de configuration SentriX, éventuellement sur une section précise",
    ),
    "navigation.dashboard": ActionSpec(
        "navigation.dashboard", None, (), (), None, "low",
        description="donner le lien du dashboard SentriX",
    ),
    "config.logs.auto": ActionSpec(
        "config.logs.auto", None, (), (), None, "medium", True,
        "analyser les salons et proposer un routage automatique des logs",
    ),
    "config.logs.route": ActionSpec(
        "config.logs.route", None, ("log_category", "channel"), (), None, "medium", True,
        "placer une catégorie précise de logs dans un salon précis",
    ),
    "desktop.open_app": ActionSpec(
        "desktop.open_app", None, ("app",), (), None, "medium", True,
        "demander l'ouverture d'une application locale via SentriX Desktop",
    ),
    "security.antispam": ActionSpec("security.antispam", "antispam", ("state",), (), None, "medium", description="activer ou désactiver l'anti-spam"),
    "security.antilink": ActionSpec("security.antilink", "antilink", ("state",), (), None, "medium", description="activer ou désactiver le blocage des liens"),
    "security.antiinvite": ActionSpec("security.antiinvite", "antiinvite", ("state",), (), None, "medium", description="activer ou désactiver le blocage des invitations"),
    "security.antiraid": ActionSpec("security.antiraid", "antiraid", ("state",), (), None, "medium", description="activer ou désactiver l'anti-raid"),
    "security.antinuke": ActionSpec("security.antinuke", "antinuke", ("state",), (), None, "high", description="activer ou désactiver l'anti-nuke"),
    "economy.balance": ActionSpec(
        "economy.balance", "balance", (), ("target",), "member", "low",
        description="afficher le solde d'un membre",
    ),
    "economy.shop": ActionSpec(
        "economy.shop", "shop", (), (), None, "low",
        description="ouvrir la boutique du serveur",
    ),
    "levels.leaderboard": ActionSpec(
        "levels.leaderboard", "leaderboard-levels", (), (), None, "low",
        description="afficher le classement des niveaux",
    ),
    "server.info": ActionSpec(
        "server.info", "serverinfo", (), (), None, "low",
        description="afficher les informations du serveur",
    ),
    "tickets.open": ActionSpec(
        "tickets.open", "ticket", (), (), None, "low",
        description="ouvrir/créer un ticket",
    ),
    "tickets.grant_access": ActionSpec(
        "tickets.grant_access", None, ("role",), (), None, "high", True,
        description="donner à un rôle l'accès aux tickets existants et futurs du serveur",
    ),
    # Actions Discord natives : elles ne passent pas par une commande +, mais restent
    # strictement bornées à ce registre et seront exécutées avec vérifications de
    # permissions + hiérarchie dans cogs.ai.
    "voice.join": ActionSpec(
        "voice.join", None, (), (), None, "low",
        description="rejoindre le salon vocal actuel de l'utilisateur",
    ),
    "voice.leave": ActionSpec(
        "voice.leave", None, (), (), None, "low",
        description="quitter le salon vocal actuel du bot",
    ),
    "channel.create_voice": ActionSpec(
        "channel.create_voice", None, ("name",), ("category",), None, "medium",
        description="créer un salon vocal",
    ),
    "channel.create_text": ActionSpec(
        "channel.create_text", None, ("name",), ("category",), None, "medium",
        description="créer un salon textuel",
    ),
    "channel.rename": ActionSpec(
        "channel.rename", None, ("channel", "name"), (), None, "medium",
        description="renommer un salon existant",
    ),
    "category.create": ActionSpec(
        "category.create", None, ("name",), (), None, "medium",
        description="créer une catégorie Discord",
    ),
    "category.restrict_role": ActionSpec(
        "category.restrict_role", None, ("category", "role"), (), None, "high", True,
        description="rendre une catégorie privée et l'autoriser uniquement à un rôle",
    ),
    "role.create": ActionSpec(
        "role.create", None, ("name",), (), None, "medium",
        description="créer un rôle",
    ),
    "role.color": ActionSpec(
        "role.color", None, ("role", "color"), (), None, "medium",
        description="modifier la couleur d'un rôle",
    ),
    "role.give": ActionSpec(
        "role.give", None, ("target", "role"), (), "member", "medium",
        description="donner un rôle à un membre",
    ),
    "role.remove": ActionSpec(
        "role.remove", None, ("target", "role"), (), "member", "medium",
        description="retirer un rôle à un membre",
    ),
    "message.send": ActionSpec(
        "message.send", None, ("channel", "text"), (), None, "medium",
        description="envoyer un message dans un salon textuel",
    ),
    "member.nickname": ActionSpec(
        "member.nickname", None, ("target", "nickname"), (), "member", "medium",
        description="modifier le pseudo serveur d'un membre",
    ),
    "member.move_voice": ActionSpec(
        "member.move_voice", None, ("target", "channel"), (), "member", "medium",
        description="déplacer un membre vers un salon vocal",
    ),
}

# Synonymes déterministes : le modèle reste le repli, pas le seul moyen de comprendre.
_INTENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("config.logs.auto", ("configure les logs", "configure mes logs", "configurer les logs", "setup des logs", "setup logs")),
    ("desktop.open_app", ("ouvre roblox", "lance roblox", "ouvre minecraft", "lance minecraft", "ouvre discord", "lance discord")),
    ("moderation.unban", ("unban", "deban", "déban", "debannis", "débannis", "debannir", "débannir")),
    ("moderation.tempban", ("tempban", "ban temporaire", "bannissement temporaire", "bannis temporairement")),
    ("moderation.unmute", ("unmute", "demute", "démute", "enleve le mute", "retire le mute", "enlève le mute")),
    ("moderation.mute", ("mute", "mut ", "mets en mute", "mettre en mute", "timeout")),
    ("moderation.warn", ("warn", "avertis", "avertir", "avertissement")),
    ("moderation.kick", ("kick", "expulse", "expulser")),
    ("moderation.ban", ("ban ", "bannis", "bannir", "vire ", "virer ")),
    ("moderation.purge", ("purge", "clear", "supprime les", "efface les")),
    ("moderation.history", ("sanctions de", "historique de sanctions", "dossier de sanctions")),
    ("moderation.warnings", ("avertissements de", "warnings de")),
    ("navigation.dashboard", ("dashboard", "dashbord", "dash board", "tableau de bord")),
    ("navigation.help", ("ouvre help", "affiche help", "montre help", "aide", "commandes")),
    ("navigation.setup", ("ouvre setup", "affiche setup", "montre setup", "configuration", "parametres", "paramètres")),
    ("economy.balance", ("balance", "solde", "argent de")),
    ("economy.shop", ("boutique", "shop")),
    ("levels.leaderboard", ("classement des niveaux", "leaderboard niveaux", "top niveaux")),
    ("server.info", ("infos du serveur", "information du serveur", "server info", "serverinfo")),
    ("tickets.open", ("cree un ticket", "crée un ticket", "ouvre un ticket", "ticket support")),
)

_NUMBER_WORDS = {
    "zero": 0, "zéro": 0, "un": 1, "une": 1, "deux": 2, "trois": 3,
    "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9,
    "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
    "quinze": 15, "seize": 16, "vingt": 20, "trente": 30,
}

_DURATION_UNITS = {
    "s": "s", "sec": "s", "seconde": "s", "secondes": "s",
    "m": "m", "min": "m", "minute": "m", "minutes": "m",
    "h": "h", "heure": "h", "heures": "h",
    "j": "j", "jour": "j", "jours": "j",
    "d": "j", "day": "j", "days": "j",
    "semaine": "j", "semaines": "j", "week": "j", "weeks": "j",
}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _number(value: str) -> int | None:
    raw = normalize_text(value)
    if raw.isdigit():
        return int(raw)
    return _NUMBER_WORDS.get(raw)


def normalize_duration(value: str | None) -> str | None:
    """Convertit les formes naturelles vers le format déjà compris par helpers.parse_duration."""
    if not value:
        return None
    raw = normalize_text(value).strip(" .,;:")
    if raw in {"une semaine", "1 semaine", "un week", "1 week"}:
        return "7j"
    compact = re.search(r"\b(\d{1,4})\s*([smhjd])\b", raw)
    if compact:
        return f"{int(compact.group(1))}{_DURATION_UNITS[compact.group(2)]}"
    match = re.search(
        r"\b(\d{1,4}|zero|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|"
        r"onze|douze|treize|quatorze|quinze|seize|vingt|trente)\s*"
        r"(secondes?|secs?|minutes?|mins?|heures?|jours?|semaines?|weeks?|days?)\b",
        raw,
    )
    if not match:
        return None
    amount = _number(match.group(1))
    unit = _DURATION_UNITS.get(normalize_text(match.group(2)).rstrip())
    if amount is None or unit is None:
        # formes plurielles non listées après normalisation
        u = normalize_text(match.group(2))
        if u.startswith("semaine") or u.startswith("week"):
            unit = "j"
        elif u.startswith("heure"):
            unit = "h"
        elif u.startswith("minute") or u.startswith("min"):
            unit = "m"
        elif u.startswith("seconde") or u.startswith("sec"):
            unit = "s"
        elif u.startswith("jour") or u.startswith("day"):
            unit = "j"
    if amount is None or unit is None:
        return None
    if normalize_text(match.group(2)).startswith(("semaine", "week")):
        amount *= 7
    return f"{amount}{unit}"


def _extract_reason(question: str) -> str | None:
    match = re.search(r"\b(?:pour|parce\s+qu['’]?(?:il|elle)?|raison\s*[:=-]?)\s+(.+)$", question, re.IGNORECASE)
    if not match:
        return None
    reason = match.group(1).strip(" .,:;-")
    return reason[:500] or None


def _extract_count(question: str) -> int | None:
    match = re.search(r"\b(\d{1,3})\s+(?:derniers?\s+)?messages?\b", normalize_text(question))
    if not match:
        return None
    return max(1, min(int(match.group(1)), 100))


def _extract_target(question: str) -> str | None:
    mention = re.search(r"<@!?(\d{15,22})>", question)
    if mention:
        return mention.group(0)
    # Formulations fréquentes où la cible se place après le verbe.
    patterns = (
        # Les formes composées passent AVANT le verbe générique : dans
        # « mets Tomioka en mute pendant 10h », le mot suivant « mute » est
        # « pendant », pas la cible.
        r"\bmets\s+@?([^\s,;]+)\s+en\s+(?:mute|timeout)",
        r"\b(?:enl[eè]ve|retire)\s+le\s+(?:mute|timeout)\s+(?:de|du|d['’])\s*@?([^\s,;]+)",
        r"\b(?:tempban|ban\s+temporaire|bannis\s+temporairement|bannir\s+temporairement)\s+@?([^\s,;]+)",
        r"\b(?:unmute|demute|démute)\s+@?([^\s,;]+)",
        r"\b(?:ban|bannis|bannir|warn|avertis|avertir|mute|mut|kick|expulse|vire)\s+@?([^\s,;]+)",
        r"\b(?:sanctions|avertissements|warnings)\s+(?:de|du|d['’])\s*@?([^\s,;]+)",
        r"\b(?:solde|balance|argent)\s+(?:de|du|d['’])\s*@?([^\s,;]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .,:;!?")
            if value and normalize_text(value) not in {"moi", "me", "mon"}:
                return value
    return None


def _toggle_state(normalized: str) -> str | None:
    if re.search(r"\b(desactive|desactiver|désactive|désactiver|coupe|eteins|éteins|off)\b", normalized):
        return "off"
    if re.search(r"\b(active|activer|allume|on)\b", normalized):
        return "on"
    return None


def _security_toggle_intent(normalized: str) -> tuple[str, str] | None:
    state = _toggle_state(normalized)
    if state is None:
        return None
    families = (
        ("security.antispam", ("anti spam", "antispam", "spam")),
        ("security.antilink", ("anti lien", "antilink", "liens", "links")),
        ("security.antiinvite", ("anti invite", "antiinvite", "invitations discord")),
        ("security.antiraid", ("anti raid", "antiraid", "raid")),
        ("security.antinuke", ("anti nuke", "antinuke", "nuke")),
    )
    for intent, tokens in families:
        if any(token in normalized for token in tokens):
            return intent, state
    return None


def _extract_log_route(question: str, normalized: str) -> ParsedAction | None:
    if "log" not in normalized and "journal" not in normalized:
        return None
    categories = (
        ("moderation", ("moderation", "mod", "sanction")),
        ("messages", ("messages", "message")),
        ("members", ("membres", "member", "arrivees", "departs", "join", "leave")),
        ("voice", ("vocal", "voice", "voc", "vc")),
        ("tickets", ("tickets", "ticket", "support")),
        ("channels", ("salons", "channels", "channel")),
        ("roles", ("roles", "rôles", "role")),
        ("automod", ("automod", "auto mod")),
        ("spam", ("spam", "anti spam", "antispam")),
        ("raid", ("raid", "anti raid", "antiraid")),
        ("server", ("serveur", "server", "guild")),
        ("resources", ("ressources", "resources", "invites", "emoji")),
        ("files", ("fichiers", "files", "uploads")),
        ("soundboard", ("soundboard", "sons")),
    )
    category = None
    for key, words in categories:
        if any(normalize_text(word) in normalized for word in words):
            category = key
            break
    if category is None:
        return None

    channel = None
    mention = re.search(r"<#(\d{15,22})>", question)
    if mention:
        channel = mention.group(0)
    else:
        named = re.search(r"(?:dans|sur|vers)\s+#([A-Za-z0-9_-]{1,100})", question, re.IGNORECASE)
        if named:
            channel = "#" + named.group(1)
    if channel is None:
        return None
    return ParsedAction(
        intent="config.logs.route",
        slots={"log_category": category, "channel": channel},
        confidence=99,
        source="local",
    )


def is_bare_action_candidate(text: str) -> bool:
    """Vrai uniquement pour une instruction autonome, pas pour une discussion ordinaire.

    Permet les formes demandées comme « ban Tomioka » sans transformer chaque phrase
    contenant le mot "ban" en commande. Le classifieur IA large reste réservé aux
    messages explicitement adressés à SentriX.
    """
    normalized = normalize_text(text).strip()
    if not normalized or len(normalized) > 500:
        return False
    gate = re.sub(r"[-_’']+", " ", normalized)
    gate = re.sub(r"\s+", " ", gate).strip()
    strong_starts = (
        "ban ", "bannis ", "bannir ", "vire ", "tempban ", "ban temporaire ",
        "warn ", "avertis ", "mute ", "mut ", "mets ", "unmute ", "demute ",
        "kick ", "expulse ", "purge ", "clear ", "supprime les ", "efface les ",
        "ouvre setup", "ouvre moi setup", "ouvre help", "ouvre moi help",
        "montre help", "affiche help",
        "donne moi le dashboard", "donne le dashboard", "dashboard",
        "active l anti", "active anti", "desactive l anti", "desactive anti",
        "configure les logs", "configure mes logs", "mets les logs",
        "rejoins le vocal", "rejoint le vocal", "rejoin le vocal", "regoin une voc", "reg une voc",
        "quitte le vocal", "cree une voc", "crée une voc", "cree un salon vocal", "crée un salon vocal",
        "cree un salon textuel", "crée un salon textuel", "cree un role", "crée un role",
        "cree une categorie", "crée une catégorie", "crée une categorie",
        "donne acces aux tickets", "donne l acces aux tickets", "ajoute acces aux tickets",
    )
    return any(gate.startswith(prefix) for prefix in strong_starts)


def local_parse(question: str) -> ParsedAction | None:
    normalized = normalize_text(question)
    if not normalized:
        return None

    # -------- actions Discord natives fréquentes --------
    # Les fautes usuelles sont volontairement tolérées ici : le modèle reste le repli.
    voice_words = ("vocal", "vocale", "voc", "voice", "vc")
    has_voice_word = any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in voice_words)
    if has_voice_word:
        if re.search(r"\b(?:quitte|quit|leave|deco|deconnecte|déconnecte|sors?)\b", normalized):
            return ParsedAction("voice.leave", {}, confidence=99, source="local")
        if re.search(r"\b(?:rejoint|rejoins|rejoin|regoin|reg|join|viens|connecte(?:[- ]?toi)?)\b", normalized):
            return ParsedAction("voice.join", {}, confidence=99, source="local")

    # « crée une voc » doit être comprise comme une action incomplète : SentriX
    # demandera simplement le nom au lieu de répondre qu'il ne peut pas agir.
    create_match = re.search(
        r"\b(?:cree|crée|creer|créer|ajoute|ajouter)\s+(?:moi\s+)?(?:un(?:e)?\s+)?"
        r"(?:(?:salon|channel)\s+)?(vocal|vocale|voc|voice|textuel|texte|text)\b(.*)$",
        question,
        re.IGNORECASE,
    )
    if create_match:
        kind = normalize_text(create_match.group(1))
        tail = create_match.group(2).strip(" .,:;!-")
        tail = re.sub(r"^(?:appele|appelé|nomme|nommé|qui s['’]appelle)\s+", "", tail, flags=re.IGNORECASE).strip()
        slots: dict[str, Any] = {}
        if tail:
            slots["name"] = tail[:100]
        return ParsedAction(
            "channel.create_voice" if kind in {"vocal", "vocale", "voc", "voice"} else "channel.create_text",
            slots,
            confidence=99,
            source="local",
        )

    category_create = re.search(
        r"\b(?:cree|crée|creer|créer|ajoute|ajouter)\s+(?:moi\s+)?(?:une\s+)?categorie\s+(.+)$",
        normalized,
    )
    if category_create:
        return ParsedAction("category.create", {"name": category_create.group(1).strip(" .,:;!-")[:100]}, 99, "local")

    role_color = re.search(
        r"\b(?:mets|met|change|modifie)\s+(?:le\s+)?role\s+(.+?)\s+(?:en|couleur)\s+(#[0-9a-fA-F]{6}|[A-Za-zÀ-ÿ]+)\b",
        question,
        re.IGNORECASE,
    )
    if role_color:
        return ParsedAction(
            "role.color",
            {"role": role_color.group(1).strip(" .,:;!-")[:100], "color": role_color.group(2)[:40]},
            99,
            "local",
        )

    role_create = re.search(
        r"\b(?:cree|crée|creer|créer|ajoute|ajouter)\s+(?:moi\s+)?(?:un\s+)?role\s+(.+)$",
        normalized,
    )
    if role_create:
        return ParsedAction("role.create", {"name": role_create.group(1).strip(" .,:;!-")[:100]}, 99, "local")

    role_change = re.search(
        r"\b(donne|ajoute|retire|enleve|enlève)\s+(?:le\s+)?role\s+(.+?)\s+(?:a|à|de)\s+@?([^\s,;]+)",
        question,
        re.IGNORECASE,
    )
    if role_change:
        verb = normalize_text(role_change.group(1))
        return ParsedAction(
            "role.remove" if verb in {"retire", "enleve"} else "role.give",
            {"role": role_change.group(2).strip(" .,:;!-")[:100], "target": role_change.group(3).strip(" .,:;!?")[:120]},
            99,
            "local",
        )

    rename_channel = re.search(
        r"\b(?:renomme|rename)\s+(<#\d{15,22}>|#[A-Za-z0-9_-]{1,100})\s+(?:en|vers)\s+(.+)$",
        question,
        re.IGNORECASE,
    )
    if rename_channel:
        return ParsedAction(
            "channel.rename",
            {"channel": rename_channel.group(1), "name": rename_channel.group(2).strip(" .,:;!-")[:100]},
            99,
            "local",
        )

    send_message = re.search(
        r"\b(?:envoie|envoye|send|ecris|écris)\s+(.+?)\s+(?:dans|sur)\s+(<#\d{15,22}>|#[A-Za-z0-9_-]{1,100})\s*$",
        question,
        re.IGNORECASE,
    )
    if send_message:
        return ParsedAction(
            "message.send",
            {"text": send_message.group(1).strip(), "channel": send_message.group(2)},
            99,
            "local",
        )

    nick = re.search(
        r"\b(?:change|mets|modifie)\s+(?:le\s+)?(?:pseudo|surnom)\s+(?:de|a|à)\s+@?([^\s,;]+)\s+(?:en|a|à)\s+(.+)$",
        question,
        re.IGNORECASE,
    )
    if nick:
        return ParsedAction(
            "member.nickname",
            {"target": nick.group(1).strip(" .,:;!?"), "nickname": nick.group(2).strip(" .,:;!-")[:32]},
            99,
            "local",
        )

    ticket_access = re.search(
        r"\b(?:donne|ajoute|accorde)\s+(?:l['’]?acc[eè]s|acc[eè]s)\s+(?:aux?|pour\s+les?)\s+tickets?\s+(?:au|a|à)\s+(?:r[oô]le\s+)?@?([^\s,;]+)",
        question,
        re.IGNORECASE,
    )
    if not ticket_access:
        ticket_access = re.search(
            r"\b(?:donne|ajoute|accorde)\s+(?:au\s+)?r[oô]le\s+(.+?)\s+(?:l['’]?acc[eè]s|acc[eè]s)\s+(?:aux?|pour\s+les?)\s+tickets?",
            question,
            re.IGNORECASE,
        )
    if ticket_access:
        return ParsedAction(
            "tickets.grant_access",
            {"role": ticket_access.group(1).strip(" .,:;!?")[:100]},
            99,
            "local",
        )

        log_route = _extract_log_route(question, normalized)
    if log_route is not None:
        return log_route

    toggle = _security_toggle_intent(normalized)
    if toggle is not None:
        intent, state = toggle
        return ParsedAction(intent=intent, slots={"state": state}, confidence=98, source="local")

    intent = None
    for candidate, words in _INTENT_PATTERNS:
        if any(normalize_text(word) in normalized for word in words):
            intent = candidate
            break
    if intent is None:
        return None

    slots: dict[str, Any] = {}
    if intent == "moderation.unban":
        uid_match = re.search(r"\b(\d{15,22})\b", question)
        if uid_match:
            slots["user_id"] = uid_match.group(1)
    if intent == "desktop.open_app":
        match = re.search(r"\b(?:ouvre|lance)\s+([A-Za-z0-9 ._+-]{2,80})", question, re.IGNORECASE)
        if match:
            slots["app"] = match.group(1).strip(" .,:;!?")
    target = _extract_target(question)
    if target:
        slots["target"] = target
    elif intent.startswith("moderation.") and re.search(
        r"(?:\b(?:le|la|lui)\b|-(?:le|la)\b)", normalized
    ):
        # Le runtime ne résoudra ce marqueur que vers une cible récente du MÊME
        # utilisateur et du MÊME serveur, avec un TTL court. Aucun membre n'est deviné.
        slots["target"] = "__recent__"
    duration = normalize_duration(question)
    if duration:
        slots["duration"] = duration
    reason = _extract_reason(question)
    if reason:
        slots["reason"] = reason
    count = _extract_count(question)
    if count is not None:
        slots["count"] = count

    if intent == "navigation.help":
        # "help ban" / "aide tickets" -> recherche interne, sans forcer un faux argument.
        match = re.search(r"\b(?:help|aide)\s+(.+)$", question, re.IGNORECASE)
        if match:
            slots["query"] = match.group(1).strip()[:80]

    if intent == "navigation.setup":
        sections = (
            ("tickets", ("ticket", "support")),
            ("logs", ("logs", "journal")),
            ("levels", ("niveau", "niveaux", "xp")),
            ("economy", ("economie", "économie", "economy", "boutique")),
            ("roles", ("role", "rôle", "roles", "rôles")),
            ("security", ("securite", "sécurité", "automod", "anti spam", "antispam")),
            ("notifications", ("notification", "notifications")),
            ("ai", (" ia", "intelligence artificielle")),
            ("moderation", ("moderation", "modération", "sanction")),
            ("welcome", ("bienvenue", "accueil", "welcome")),
        )
        for key, words in sections:
            if any(ai_actions_word in normalized for ai_actions_word in (normalize_text(w) for w in words)):
                slots["section"] = key
                break

    return ParsedAction(intent=intent, slots=slots, confidence=95, source="local")


def _json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^\s*```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def _validate_ai_payload(payload: dict[str, Any] | None) -> ParsedAction | None:
    if not payload:
        return None
    intent = str(payload.get("intent") or "").strip()
    if intent not in ACTIONS:
        return None
    try:
        confidence = int(payload.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    if confidence < 70:
        return None
    slots: dict[str, Any] = {}
    for key in (
        "target", "reason", "duration", "query", "app", "state", "section",
        "log_category", "channel", "user_id", "name", "category", "role",
        "text", "nickname", "color",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            slots[key] = value.strip()[:500]
    if "duration" in slots:
        normalized = normalize_duration(slots["duration"])
        if normalized:
            slots["duration"] = normalized
        else:
            slots.pop("duration", None)
    count = payload.get("count")
    if count is not None:
        try:
            slots["count"] = max(1, min(int(count), 100))
        except (TypeError, ValueError):
            pass
    return ParsedAction(intent=intent, slots=slots, confidence=min(100, confidence), source="ai")


async def classify_with_ai(
    question: str,
    *,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int | None,
) -> ParsedAction | None:
    """Classifie une demande explicite. Le résultat est ensuite validé localement."""
    catalog = "\n".join(
        f"- {spec.intent}: {spec.description}; required={','.join(spec.required) or 'none'}"
        for spec in ACTIONS.values()
    )
    instructions = (
        "Tu es le classifieur d'actions de SentriX. Tu n'exécutes rien. "
        "Retourne UNIQUEMENT un objet JSON valide, sans markdown. "
        "Choisis uniquement un intent de la liste. Si la demande n'est pas une action "
        "SentriX claire, retourne {\"intent\": null, \"confidence\": 0}. "
        "N'invente jamais un utilisateur, un ID, une durée, une raison ou un nombre. "
        "Préserve le texte de la cible tel que l'utilisateur l'a écrit. "
        "Champs autorisés: intent, target, user_id, duration, reason, count, query, app, state, section, log_category, channel, name, category, role, text, nickname, color, confidence.\n"
        "Actions autorisées:\n" + catalog
    )
    result = await ai_service.generate(
        question,
        model_key=ai_service.MODEL_LUNA,
        reasoning_effort="none",
        instructions=instructions,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        command="sentrix-action-router",
        web_search=False,
        max_output_tokens=220,
    )
    if not result.ok:
        return None
    return _validate_ai_payload(_json_object(result.text))


def looks_multi_action(question: str) -> bool:
    """Détecte une demande qui contient vraisemblablement plusieurs actions."""
    text = normalize_text(question)
    if not text or len(text) > 1800:
        return False
    separators = sum(text.count(token) for token in (" puis ", " ensuite ", ";", " et apres ", " et après "))
    action_words = re.findall(
        r"\b(?:cree|creer|ajoute|donne|retire|renomme|configure|mets|change|deplace|"
        r"envoie|ban|bannis|warn|mute|kick|active|desactive|rejoint|quitte|lance|joue)\b",
        text,
    )
    # Une simple phrase « ban X et raison Y » ne devient pas artificiellement un plan.
    return separators >= 1 or len(action_words) >= 2


async def parse_action_plan(
    question: str,
    *,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int | None,
) -> tuple[ParsedAction, ...]:
    """Transforme une instruction composée en 2..8 actions autorisées et ordonnées.

    Le modèle ne reçoit aucun pouvoir : chaque élément repasse par le même validateur
    fermé que parse_action(), puis l'exécution vérifie localement permissions, hiérarchie
    et existence réelle des ressources Discord.
    """
    if not looks_multi_action(question):
        return ()
    catalog = "\n".join(
        f"- {spec.intent}: {spec.description}; required={','.join(spec.required) or 'none'}; optional={','.join(spec.optional) or 'none'}"
        for spec in ACTIONS.values()
        if spec.intent != "desktop.open_app"
    )
    instructions = (
        "Tu es le planificateur d'actions de SentriX. Tu n'exécutes RIEN. "
        "Découpe uniquement une demande explicite en plusieurs actions Discord, dans l'ordre exact. "
        "Retourne UNIQUEMENT un JSON {\"actions\":[...]} sans markdown. "
        "Chaque action doit utiliser un intent EXACT de la liste et seulement les champs autorisés. "
        "Maximum 8 actions. N'invente jamais un membre, rôle, salon, catégorie, ID, nom, couleur, durée ou raison. "
        "Les noms créés dans une étape peuvent être réutilisés mot pour mot dans les étapes suivantes. "
        "Si la demande ne contient pas au moins deux actions claires, retourne {\"actions\":[]}. "
        "Champs autorisés par action: intent,target,user_id,duration,reason,count,query,state,section,"
        "log_category,channel,name,category,role,text,nickname,color,confidence.\n"
        "ACTIONS AUTORISÉES:\n" + catalog
    )
    result = await ai_service.generate(
        question,
        model_key=ai_service.MODEL_LUNA,
        reasoning_effort="none",
        instructions=instructions,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        command="sentrix-action-plan",
        web_search=False,
        max_output_tokens=900,
    )
    if not result.ok:
        return ()
    payload = _json_object(result.text)
    if not payload or not isinstance(payload.get("actions"), list):
        return ()
    actions: list[ParsedAction] = []
    for raw in payload["actions"][:8]:
        if not isinstance(raw, dict):
            return ()
        raw = dict(raw)
        raw.setdefault("confidence", 90)
        parsed = _validate_ai_payload(raw)
        if parsed is None:
            return ()
        parsed.source = "plan"
        if missing_slots(parsed):
            return ()
        actions.append(parsed)
    return tuple(actions) if len(actions) >= 2 else ()


def describe_action(action: ParsedAction) -> str:
    """Résumé utilisateur court pour la confirmation d'un plan."""
    label = action.spec.description if action.spec else action.intent
    details = []
    for key in ("name", "target", "role", "category", "channel", "log_category", "color", "duration", "count"):
        value = action.slots.get(key)
        if value not in (None, ""):
            details.append(f"{key}={value}")
    return label + (f" ({', '.join(details[:4])})" if details else "")


async def parse_action(
    question: str,
    *,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int | None,
) -> ParsedAction | None:
    parsed = local_parse(question)
    if parsed is not None:
        return parsed
    return await classify_with_ai(
        question, guild_id=guild_id, channel_id=channel_id, user_id=user_id
    )


def missing_slots(action: ParsedAction) -> tuple[str, ...]:
    spec = action.spec
    if spec is None:
        return ()
    return tuple(name for name in spec.required if action.slots.get(name) in (None, ""))


def missing_prompt(intent: str, slot: str, *, target: discord.Member | None = None) -> str:
    if slot == "target":
        return "Quel membre voulez-vous viser ?"
    if slot == "user_id":
        return "Quel est l’identifiant Discord de l’utilisateur à débannir ?"
    if slot == "duration":
        who = target.mention if target is not None else "ce membre"
        return f"Pendant combien de temps voulez-vous mute {who} ?"
    if slot == "count":
        return "Combien de messages voulez-vous supprimer ?"
    if slot == "channel":
        return "Dans quel salon voulez-vous envoyer ces logs ?"
    if slot == "log_category":
        return "Quelle catégorie de logs voulez-vous configurer ?"
    if slot == "name":
        if intent == "channel.create_voice":
            return "Quel nom voulez-vous donner au salon vocal ?"
        if intent == "channel.create_text":
            return "Quel nom voulez-vous donner au salon textuel ?"
        if intent == "role.create":
            return "Quel nom voulez-vous donner au rôle ?"
        if intent == "category.create":
            return "Quel nom voulez-vous donner à la catégorie ?"
    if slot == "category":
        return "Quelle catégorie voulez-vous utiliser ?"
    if slot == "role":
        return "Quel rôle voulez-vous utiliser ?"
    if slot == "text":
        return "Quel message voulez-vous envoyer ?"
    if slot == "nickname":
        return "Quel nouveau pseudo voulez-vous donner à ce membre ?"
    if slot == "color":
        return "Quelle couleur voulez-vous utiliser (ex. rouge ou #ff0000) ?"
    return f"Quelle valeur voulez-vous utiliser pour « {slot} » ?"


def merge_followup(action: ParsedAction, answer: str) -> ParsedAction:
    """Complète UNE action en attente avec une réponse courte."""
    slots = dict(action.slots)
    missing = missing_slots(action)
    if not missing:
        return ParsedAction(action.intent, slots, action.confidence, action.source)
    slot = missing[0]
    value = str(answer or "").strip()
    if slot == "duration":
        duration = normalize_duration(value)
        if duration:
            slots["duration"] = duration
    elif slot == "count":
        match = re.search(r"\d{1,3}", value)
        if match:
            slots["count"] = max(1, min(int(match.group(0)), 100))
    elif slot == "target" and value:
        slots["target"] = value[:120]
    elif slot == "app" and value:
        slots["app"] = value[:80]
    elif slot == "state":
        state = _toggle_state(normalize_text(value))
        if state:
            slots["state"] = state
    elif slot == "user_id":
        match = re.search(r"\b\d{15,22}\b", value)
        if match:
            slots["user_id"] = match.group(0)
    elif slot == "channel" and value:
        slots["channel"] = value[:120]
    elif slot == "log_category" and value:
        candidate = _log_category_alias(value)
        if candidate:
            slots["log_category"] = candidate
    elif slot in {"name", "category", "role", "text", "nickname", "color"} and value:
        limits = {"name": 100, "category": 100, "role": 100, "text": 1900, "nickname": 32, "color": 40}
        slots[slot] = value[: limits[slot]]
    return ParsedAction(action.intent, slots, action.confidence, "followup")


def _member_names(member: discord.Member) -> tuple[str, ...]:
    values = {
        str(getattr(member, "name", "") or ""),
        str(getattr(member, "display_name", "") or ""),
        str(getattr(member, "global_name", "") or ""),
    }
    return tuple(v for v in values if v)


def resolve_member(
    guild: discord.Guild,
    target_text: str | None,
    *,
    message: discord.Message | None = None,
    bot_user_id: int | None = None,
) -> MemberResolution:
    """Résout une cible sans jamais deviner quand plusieurs membres sont plausibles."""
    if message is not None:
        mentions = [
            member for member in getattr(message, "mentions", ())
            if isinstance(member, discord.Member) and int(member.id) != int(bot_user_id or 0)
        ]
        if len(mentions) == 1:
            return MemberResolution(member=mentions[0])
        if len(mentions) > 1:
            return MemberResolution(ambiguous=tuple(mentions[:5]))

    raw = str(target_text or "").strip()
    if not raw:
        return MemberResolution(error="missing")

    id_match = re.fullmatch(r"<@!?(\d{15,22})>", raw) or re.fullmatch(r"(\d{15,22})", raw)
    if id_match:
        member = guild.get_member(int(id_match.group(1)))
        if member is not None:
            return MemberResolution(member=member)
        return MemberResolution(error="not_found")

    wanted = normalize_text(raw.lstrip("@"))
    exact: list[discord.Member] = []
    for member in guild.members:
        if any(normalize_text(name) == wanted for name in _member_names(member)):
            exact.append(member)
    if len(exact) == 1:
        return MemberResolution(member=exact[0])
    if len(exact) > 1:
        return MemberResolution(ambiguous=tuple(exact[:5]))

    scored: list[tuple[float, discord.Member]] = []
    for member in guild.members:
        best = max(
            (difflib.SequenceMatcher(a=wanted, b=normalize_text(name)).ratio() for name in _member_names(member)),
            default=0.0,
        )
        if best >= 0.78:
            scored.append((best, member))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return MemberResolution(error="not_found")
    if len(scored) == 1 or (scored[0][0] >= 0.90 and scored[0][0] - scored[1][0] >= 0.12):
        return MemberResolution(member=scored[0][1])
    return MemberResolution(ambiguous=tuple(member for _, member in scored[:5]))


def build_command_line(
    action: ParsedAction,
    *,
    prefix: str,
    member: discord.Member | None = None,
) -> str | None:
    spec = action.spec
    if spec is None or not spec.command:
        return None
    command = f"{prefix}{spec.command}"
    slots = action.slots

    if action.intent in {"moderation.ban", "moderation.kick", "moderation.warn", "moderation.unmute"}:
        if member is None:
            return None
        command += f" {member.mention}"
        reason = str(slots.get("reason") or "").strip()
        if reason:
            command += f" {reason}"
        return command

    if action.intent in {"moderation.mute", "moderation.tempban"}:
        if member is None or not slots.get("duration"):
            return None
        command += f" {member.mention} {slots['duration']}"
        reason = str(slots.get("reason") or "").strip()
        if reason:
            command += f" {reason}"
        return command

    if action.intent == "moderation.unban":
        uid = str(slots.get("user_id") or "").strip()
        if not re.fullmatch(r"\d{15,22}", uid):
            return None
        command += f" {uid}"
        reason = str(slots.get("reason") or "").strip()
        if reason:
            command += f" {reason}"
        return command

    if action.intent == "moderation.purge":
        return f"{command} {int(slots['count'])}" if slots.get("count") else None

    if action.intent in {"moderation.warnings", "moderation.history", "economy.balance"}:
        if member is not None:
            command += f" {member.mention}"
        elif action.intent in {"moderation.warnings", "moderation.history"}:
            return None
        return command

    # +help est volontairement root-only dans le runtime actuel : la recherche
    # se fait depuis le menu interactif. Ne jamais lui ajouter un argument historique.
    if action.intent.startswith("security.") and slots.get("state"):
        command += f" {slots['state']}"
    return command


def _log_category_alias(value: str | None) -> str | None:
    normalized = normalize_text(value or "")
    if not normalized:
        return None
    aliases = {
        "moderation": ("moderation", "mod", "sanction"),
        "messages": ("messages", "message"),
        "members": ("membres", "members", "join", "leave", "arrivees", "departs"),
        "voice": ("vocal", "voice", "voc", "vc"),
        "tickets": ("tickets", "ticket", "support"),
        "channels": ("salons", "channels", "channel"),
        "roles": ("roles", "role", "rôles"),
        "automod": ("automod", "auto mod"),
        "spam": ("spam", "antispam", "anti spam"),
        "raid": ("raid", "antiraid", "anti raid"),
        "server": ("server", "serveur", "guild"),
        "resources": ("resources", "ressources", "invite", "emoji"),
        "files": ("files", "fichiers", "upload"),
        "soundboard": ("soundboard", "sons"),
    }
    for key, words in aliases.items():
        if normalized == key or any(normalize_text(word) in normalized for word in words):
            return key
    return None


def resolve_text_channel(guild: Any, target_text: str | None) -> ChannelResolution:
    raw = str(target_text or "").strip()
    if not raw:
        return ChannelResolution(error="missing")
    channels = list(getattr(guild, "text_channels", ()) or ())

    match = re.fullmatch(r"<#(\d{15,22})>", raw) or re.fullmatch(r"(\d{15,22})", raw)
    if match:
        cid = int(match.group(1))
        channel = next((ch for ch in channels if int(getattr(ch, "id", 0) or 0) == cid), None)
        return ChannelResolution(channel=channel, error=None if channel else "not_found")

    wanted = normalize_text(raw.lstrip("#"))
    exact = [ch for ch in channels if normalize_text(getattr(ch, "name", "")) == wanted]
    if len(exact) == 1:
        return ChannelResolution(channel=exact[0])
    if len(exact) > 1:
        return ChannelResolution(ambiguous=tuple(exact[:5]))

    ranked: list[tuple[float, Any]] = []
    for ch in channels:
        name = normalize_text(getattr(ch, "name", ""))
        if not name:
            continue
        score = difflib.SequenceMatcher(a=wanted, b=name).ratio()
        if score >= 0.82:
            ranked.append((score, ch))
    ranked.sort(key=lambda row: row[0], reverse=True)
    if not ranked:
        return ChannelResolution(error="not_found")
    if len(ranked) == 1 or (ranked[0][0] >= .92 and ranked[0][0] - ranked[1][0] >= .10):
        return ChannelResolution(channel=ranked[0][1])
    return ChannelResolution(ambiguous=tuple(ch for _, ch in ranked[:5]))


_LOG_MATCH_RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "moderation": ("Modération", ("moderation", "mod logs", "logs mod", "sanctions", "warn", "ban", "mute")),
    "messages": ("Messages", ("messages", "message logs", "logs messages", "edits", "deletes", "suppression")),
    "members": ("Membres / arrivées-départs", ("members", "membres", "join leave", "arrivees departs", "arrivee depart", "joins", "leaves")),
    "voice": ("Vocal", ("voice", "vocal", "voc logs", "logs voc", "voice logs", "vc logs")),
    "tickets": ("Tickets", ("tickets", "ticket logs", "logs tickets", "support logs")),
    "channels": ("Salons", ("channels", "salons", "channel logs", "logs salons")),
    "roles": ("Rôles", ("roles", "rôles", "role logs", "logs roles")),
    "automod": ("AutoMod", ("automod", "auto mod", "moderation auto")),
    "spam": ("Anti-Spam", ("spam logs", "antispam logs", "anti spam")),
    "raid": ("Anti-Raid", ("raid logs", "antiraid logs", "anti raid")),
    "server": ("Serveur", ("server logs", "serveur", "guild logs")),
    "resources": ("Ressources", ("resources", "ressources", "emoji logs", "invite logs")),
    "files": ("Fichiers", ("files", "fichiers", "upload logs")),
    "soundboard": ("Soundboard", ("soundboard", "sons")),
}


def log_category_label(category: str) -> str:
    return (_LOG_MATCH_RULES.get(str(category)) or (str(category).capitalize(), ()))[0]


def _log_match_text(value: object) -> str:
    # Discord emploie naturellement des tirets/underscores dans les noms de salons.
    # Pour le scoring uniquement, « ticket-logs », « ticket_logs » et « ticket logs »
    # doivent être équivalents.
    text = normalize_text(str(value or ""))
    return re.sub(r"[-_]+", " ", text).strip()


def _channel_text(channel: Any) -> tuple[str, str, str]:
    name = _log_match_text(getattr(channel, "name", ""))
    topic = _log_match_text(getattr(channel, "topic", ""))
    category = _log_match_text(getattr(getattr(channel, "category", None), "name", ""))
    return name, topic, category


def _log_channel_score(channel: Any, keywords: tuple[str, ...]) -> tuple[int, str]:
    name, topic, category = _channel_text(channel)
    if not name:
        return 0, ""
    score = 0
    evidence: list[str] = []
    if any(token in name for token in ("log", "logs", "journal")):
        score += 2
        evidence.append("nom de salon de logs")
    for keyword in keywords:
        key = _log_match_text(keyword)
        if not key:
            continue
        if name == key:
            score += 10
            evidence.append(f"nom exact « {keyword} »")
        elif key in name:
            score += 7
            evidence.append(f"nom contient « {keyword} »")
        if key in topic:
            score += 3
            evidence.append(f"sujet contient « {keyword} »")
        if key in category:
            score += 2
            evidence.append(f"catégorie contient « {keyword} »")
    return score, evidence[0] if evidence else ""


def propose_log_routes(guild: Any, *, max_categories: int = 14) -> tuple[LogProposal, ...]:
    """Propose des routes sans rien écrire. Une proposition faible ou ambiguë est ignorée."""
    channels = [
        ch for ch in getattr(guild, "text_channels", ())
        if getattr(ch, "id", None) and getattr(ch, "name", None)
    ]
    candidates: list[tuple[int, str, str, Any, str]] = []
    for key, (label, keywords) in _LOG_MATCH_RULES.items():
        ranked: list[tuple[int, Any, str]] = []
        for channel in channels:
            score, evidence = _log_channel_score(channel, keywords)
            if score >= 7:
                ranked.append((score, channel, evidence))
        ranked.sort(key=lambda row: row[0], reverse=True)
        if not ranked:
            continue
        # Deux salons quasi équivalents = pas de devinette. L'utilisateur pourra les
        # configurer manuellement au lieu de recevoir un mauvais routage automatique.
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 2:
            continue
        score, channel, evidence = ranked[0]
        candidates.append((score, key, label, channel, evidence))

    candidates.sort(key=lambda row: row[0], reverse=True)
    used_channels: set[int] = set()
    proposals: list[LogProposal] = []
    for score, key, label, channel, evidence in candidates:
        cid = int(channel.id)
        if cid in used_channels:
            continue
        used_channels.add(cid)
        proposals.append(LogProposal(key, label, cid, str(channel.name), score, evidence))
        if len(proposals) >= max_categories:
            break
    return tuple(proposals)


def public_catalog() -> tuple[ActionSpec, ...]:
    return tuple(ACTIONS.values())
