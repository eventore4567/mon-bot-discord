"""Règles pures de SentriX V2.4 Intelligent UX.

Ce module ne dépend pas de Discord. Il transforme uniquement des formulations naturelles
très explicites en plans d'action vers des commandes EXISTANTES. Les actions sensibles
sont marquées comme telles afin que la couche Discord exige toujours une confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass
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


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.casefold().replace("’", "'")
    text = re.sub(r"[^a-z0-9@<>#'.,+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_reason(raw: str, *, action_words: tuple[str, ...], amount: str | None = None, duration: str | None = None) -> str:
    text = str(raw or "")
    text = _MENTION_RE.sub(" ", text)
    for word in sorted(action_words, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, count=1, flags=re.I)
    if amount:
        text = re.sub(re.escape(amount), " ", text, count=1, flags=re.I)
    if duration:
        text = re.sub(re.escape(duration), " ", text, count=1, flags=re.I)
    text = re.sub(r"\b(?:stp|svp|please|pls|lui|le|la|les|moi|pour|avec|car|parce que|raison)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" .,:;-_")
    return text[:400] or "Aucune raison fournie"


def parse_natural_action(value: str | None) -> NaturalAction | None:
    raw = str(value or "").strip()
    text = normalize_text(raw)
    if not text or len(text) > 500:
        return None

    # Actions de consultation : formulation volontairement explicite pour ne pas détourner
    # une vraie question qui doit continuer vers l'IA.
    safe_patterns: tuple[tuple[str, str, str], ...] = (
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:mon |ma )?(?:profil|profile)$", "profile", "Ouvrir ton profil"),
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:mon |mes )?(?:solde|balance)$", "balance", "Afficher ton solde"),
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:mon |mes )?(?:niveau|level|xp)$", "level", "Afficher ta progression"),
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:mon |mes )?(?:inventaire|inventory|objets)$", "inventory", "Ouvrir ton inventaire"),
        (r"^(?:ouvre|montre|affiche|voir|je veux voir) (?:la |le )?(?:boutique|shop)$", "shop", "Ouvrir la boutique"),
        (r"^(?:ouvre|cree|crée|faire|fais) (?:un |mon )?ticket$", "ticket", "Ouvrir les tickets"),
        (r"^(?:prends|prend|recupere|récupère|donne moi) (?:ma |la )?(?:recompense |récompense )?quotidienne$", "daily", "Récupérer la récompense quotidienne"),
        (r"^(?:prends|prend|recupere|récupère|donne moi) (?:ma |la )?(?:recompense |récompense )?hebdomadaire$", "weekly", "Récupérer la récompense hebdomadaire"),
        (r"^(?:fais moi travailler|je veux travailler|travaille|work)$", "work", "Travailler"),
    )
    for pattern, command, label in safe_patterns:
        if re.fullmatch(pattern, text, flags=re.I):
            return NaturalAction(command=command, label=label)

    # Paiement : on exige un verbe de transfert ET un montant. La couche Discord exigera
    # en plus une cible explicite (mention ou message auquel l'utilisateur répond).
    if re.search(r"\b(?:donne|donner|envoie|envoyer|paye|payer|transfere|transférer|transfert)\b", text):
        amount_match = _AMOUNT_RE.search(text)
        if amount_match:
            amount = amount_match.group(1).replace(" ", "")
            reason = _clean_reason(raw, action_words=("donne", "donner", "envoie", "envoyer", "paye", "payer", "transfere", "transférer", "transfert"), amount=amount)
            return NaturalAction(
                command="pay",
                label=f"Envoyer {amount}",
                sensitive=True,
                target_required=True,
                amount=amount,
                reason=reason,
            )

    # Vol économique : risque de perte de monnaie => confirmation obligatoire.
    if re.search(r"\b(?:vole|voler|rob)\b", text):
        return NaturalAction(command="rob", label="Tenter un vol", sensitive=True, target_required=True)

    moderation: tuple[tuple[tuple[str, ...], str, str, bool], ...] = (
        (("ban temporaire", "tempban"), "tempban", "Bannir temporairement", True),
        (("unmute", "demute", "démute", "demuter", "démuter"), "unmute", "Retirer le mute", False),
        (("mute", "timeout"), "mute", "Rendre muet", True),
        (("kick", "expulse", "expulser"), "kick", "Expulser", False),
        (("warn", "avertis", "avertir"), "warn", "Avertir", False),
        (("ban", "bannis", "bannir"), "ban", "Bannir", False),
    )
    for words, command, label, accepts_duration in moderation:
        if not any(re.search(rf"\b{re.escape(word)}\b", text) for word in words):
            continue
        duration_match = _DURATION_RE.search(raw) if accepts_duration else None
        duration = duration_match.group(1).strip() if duration_match else None
        if command == "mute" and duration is None:
            duration = "10m"
        if command == "tempban" and duration is None:
            # Une demande de ban temporaire sans durée n'est pas assez précise pour être
            # transformée en action : elle continue vers l'IA qui pourra demander la durée.
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
    """Retourne (valeur DB, libellé) via une heuristique déterministe et explicable."""
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
