"""Règles pures de SentriX Intelligent UX.

Ce module ne dépend pas de Discord. Il transforme uniquement des formulations naturelles
TRÈS explicites en plans d'action vers des commandes existantes. Une simple discussion
qui contient « ban », « mute », « payer », etc. ne doit jamais devenir une action.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import unicodedata


@dataclass(frozen=True)
class NaturalAction:
    command: str
    label: str
    sensitive: bool = False
    target_required: bool = False
    amount: str | None = None
    duration: str | None = None
    reason: str | None = None
    confidence: float = 1.0


_MENTION_RE = re.compile(r"<@!?\d+>")
_AMOUNT_RE = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?\s*[kmb]?|all|tout|max)(?!\w)", re.I)
_DURATION_RE = re.compile(
    r"(?<!\w)(\d+\s*(?:secondes?|secs?|sec|s|minutes?|mins?|min|m|heures?|h|jours?|j|d|semaines?|semaine|sem|w)(?:\s*\d+\s*(?:heures?|h|minutes?|mins?|min|m))?)(?!\w)",
    re.I,
)
_AMOUNT_MULTIPLIERS = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

# Les actions sensibles doivent commencer comme une vraie instruction. Cela évite que des
# questions telles que « c'est quoi un ban ? » ou « comment éviter de se faire voler ? »
# soient transformées en commande.
_REQUEST_PREFIX = r"(?:stp\s+|svp\s+|please\s+|pls\s+|peux[ -]?tu\s+|tu\s+peux\s+|je\s+veux\s+|merci\s+de\s+)?"


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.casefold().replace("’", "'")
    text = re.sub(r"[^a-z0-9@<>#'.,+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_amount(value: str | None) -> str | None:
    """Convertit 5k -> 5000, 1.5k -> 1500, 2m -> 2000000."""
    raw = str(value or "").strip().casefold().replace(" ", "")
    if raw in {"all", "tout", "max"}:
        return raw
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)([kmb]?)", raw, flags=re.I)
    if not match:
        return None
    try:
        number = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    amount = number * _AMOUNT_MULTIPLIERS[match.group(2).casefold()]
    if amount <= 0 or amount != amount.to_integral_value():
        return None
    return str(int(amount))


def _clean_reason(raw: str, *, action_words: tuple[str, ...], amount: str | None = None, duration: str | None = None) -> str:
    text = str(raw or "")
    text = _MENTION_RE.sub(" ", text)
    for word in sorted(action_words, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, count=1, flags=re.I)
    if amount:
        text = re.sub(re.escape(amount), " ", text, count=1, flags=re.I)
    if duration:
        text = re.sub(re.escape(duration), " ", text, count=1, flags=re.I)
    text = re.sub(
        r"\b(?:stp|svp|please|pls|peux|tu|je|veux|merci|lui|le|la|les|moi|pour|avec|car|parce que|raison|a|à|au|aux|de|du|des|vers|chez)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip(" .,:;-_")
    return text[:400] or "Aucune raison fournie"


def _explicit_action(text: str, alternatives: tuple[str, ...]) -> bool:
    words = "|".join(re.escape(item) for item in sorted(alternatives, key=len, reverse=True))
    return bool(re.match(rf"^{_REQUEST_PREFIX}(?:{words})\b", text, flags=re.I))


def parse_natural_action(value: str | None) -> NaturalAction | None:
    raw = str(value or "").strip()
    text = normalize_text(raw)
    if not text or len(text) > 500:
        return None

    safe_patterns: tuple[tuple[str, str, str], ...] = (
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:mon |ma )?(?:profil|profile)$", "profile", "Ouvrir ton profil"),
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:mon |mes )?(?:solde|balance)$", "balance", "Afficher ton solde"),
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:mon |mes )?(?:niveau|level|xp)$", "level", "Afficher ta progression"),
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:mon |mes )?(?:inventaire|inventory|objets)$", "inventory", "Ouvrir ton inventaire"),
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:la |le )?(?:boutique|shop)$", "shop", "Ouvrir la boutique"),
        (r"^(?:ouvre|cree|faire|fais) (?:un |mon )?ticket$", "ticket", "Ouvrir les tickets"),
        (r"^(?:prends|prend|recupere|donne moi) (?:ma |la )?(?:recompense )?quotidienne$", "daily", "Récupérer la récompense quotidienne"),
        (r"^(?:prends|prend|recupere|donne moi) (?:ma |la )?(?:recompense )?hebdomadaire$", "weekly", "Récupérer la récompense hebdomadaire"),
        (r"^(?:fais moi travailler|je veux travailler|travaille|work)$", "work", "Travailler"),
    )
    for pattern, command, label in safe_patterns:
        if re.fullmatch(pattern, text, flags=re.I):
            return NaturalAction(command=command, label=label)

    transfer_words = ("transfere", "transfert", "envoyer", "envoie", "donner", "donne", "payer", "paye")
    recipient_cue = bool(_MENTION_RE.search(raw) or re.search(r"\b(?:lui|a|au|pour)\b", text))
    if _explicit_action(text, transfer_words) and recipient_cue:
        amount_source = _MENTION_RE.sub(" ", raw)
        amount_match = _AMOUNT_RE.search(amount_source)
        if amount_match:
            displayed_amount = amount_match.group(1).replace(" ", "")
            amount = canonical_amount(displayed_amount)
            if amount is not None:
                reason = _clean_reason(raw, action_words=transfer_words, amount=displayed_amount)
                return NaturalAction(
                    command="pay",
                    label=f"Envoyer {displayed_amount}",
                    sensitive=True,
                    target_required=True,
                    amount=amount,
                    reason=reason,
                )

    if _explicit_action(text, ("vole", "voler", "rob")):
        return NaturalAction(command="rob", label="Tenter un vol", sensitive=True, target_required=True)

    moderation: tuple[tuple[tuple[str, ...], str, str, bool], ...] = (
        (("ban temporaire", "bannis temporairement", "bannir temporairement", "tempban"), "tempban", "Bannir temporairement", True),
        (("unmute", "demute", "demuter"), "unmute", "Retirer le mute", False),
        (("rends muet", "mettre en mute", "mute", "timeout"), "mute", "Rendre muet", True),
        (("kick", "expulse", "expulser"), "kick", "Expulser", False),
        (("warn", "avertis", "avertir"), "warn", "Avertir", False),
        (("ban", "bannis", "bannir"), "ban", "Bannir", False),
    )
    for words, command, label, accepts_duration in moderation:
        if not _explicit_action(text, words):
            continue
        duration_match = _DURATION_RE.search(raw) if accepts_duration else None
        duration = duration_match.group(1).strip() if duration_match else None
        if command == "mute" and duration is None:
            duration = "10m"
        if command == "tempban" and duration is None:
            return None
        reason = _clean_reason(raw, action_words=words, duration=duration)
        return NaturalAction(
            command=command,
            label=label,
            sensitive=True,
            target_required=True,
            duration=duration,
            reason=reason,
        )

    return None


def classify_ticket_priority(text: str | None) -> tuple[str, str]:
    value = normalize_text(text)
    urgent = ("compte vole", "compte hack", "hacke", "pirate", "menace", "dox", "arnaque", "scam", "paiement", "urgence", "urgent")
    high = ("harcelement", "harcele", "insulte", "ban injuste", "sanction", "bug bloquant", "perdu")
    if any(term in value for term in urgent):
        return "haute", "Haute"
    if any(term in value for term in high):
        return "elevee", "Élevée"
    return "normale", "Normale"


def summarize_ticket(category: str | None, answers: list[tuple[str, str]] | None, *, max_chars: int = 420) -> str:
    category_text = (category or "Support").strip()
    useful: list[str] = []
    for label, answer in answers or []:
        cleaned = re.sub(r"\s+", " ", str(answer or "")).strip()
        if cleaned:
            useful.append(f"{str(label or 'Réponse').strip()}: {cleaned}")
    body = " | ".join(useful) if useful else "Aucune réponse de formulaire."
    result = f"Type: {category_text} — {body}"
    return result[:max_chars]
