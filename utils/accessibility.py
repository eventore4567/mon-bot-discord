"""Règles pures d'accessibilité et de tolérance aux fautes pour SentriX.

Aucune dépendance Discord : ce module sert à la V2.3 et reste testable en CI.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata


INTENT_ALIASES = {
    "home": {
        "aide", "help", "menu", "commande", "commandes", "accueil", "demarrer",
        "commencer", "start", "tu peux faire quoi", "que peux tu faire",
    },
    "games": {"jeu", "jeux", "game", "games", "mini jeu", "mini jeux", "jouer"},
    "economy": {"economie", "eco", "argent", "money", "monnaie", "boutique", "shop"},
    "profile": {"profil", "profile", "niveau", "level", "xp", "reputation", "rep"},
    "ai": {"ia", "ai", "intelligence artificielle", "parler", "discussion", "assistant"},
    "ping": {"ping", "latence", "latency"},
}

PARAMETER_LABELS = {
    "membre": "membre",
    "member": "membre",
    "user": "utilisateur",
    "user_id": "identifiant utilisateur",
    "role": "rôle",
    "channel": "salon",
    "salon": "salon",
    "duree": "durée",
    "duration": "durée",
    "raison": "raison",
    "reason": "raison",
    "montant": "montant",
    "amount": "montant",
    "objet": "objet",
    "item": "objet",
    "nom": "nom",
    "name": "nom",
    "texte": "texte",
    "message": "message",
}


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("_", "-")
    text = re.sub(r"[^a-z0-9 -]+", " ", text)
    return " ".join(text.split()).strip()


def similarity(left: str, right: str) -> float:
    a, b = normalize_text(left), normalize_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def closest_commands(query: str, candidates, *, limit: int = 3, threshold: float = 0.56) -> list[str]:
    """Retourne les commandes les plus proches, sans correction automatique risquée."""
    q = normalize_text(query).lstrip("+-/")
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        name = str(candidate or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        score = similarity(q, name)
        normalized = normalize_text(name)
        if q and (normalized.startswith(q) or q.startswith(normalized)):
            score = max(score, 0.82)
        if score >= threshold:
            scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return [name for _score, name in scored[: max(1, int(limit))]]


def match_quick_intent(text: str, *, threshold: float = 0.72) -> str | None:
    """Tolère les petites fautes sur les demandes très courtes de navigation."""
    value = normalize_text(text)
    if not value or len(value) > 70:
        return None
    best: tuple[float, str] = (0.0, "")
    for intent, aliases in INTENT_ALIASES.items():
        for alias in aliases:
            score = similarity(value, alias)
            if score > best[0]:
                best = (score, intent)
    return best[1] if best[0] >= threshold else None


def human_parameter(name: str | None) -> str:
    key = normalize_text(name).replace("-", "_")
    return PARAMETER_LABELS.get(key, key.replace("_", " ") or "paramètre")


def clean_signature(signature: str | None) -> str:
    """Rend la signature Discord.py un peu plus lisible sans en changer le sens."""
    text = str(signature or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def usage_line(prefix: str, command_name: str, signature: str | None = None) -> str:
    prefix = str(prefix or "+")
    command_name = str(command_name or "").strip()
    signature = clean_signature(signature)
    return f"{prefix}{command_name}{(' ' + signature) if signature else ''}".strip()
