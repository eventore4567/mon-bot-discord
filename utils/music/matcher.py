"""Matching intelligent entre une piste cible (métadonnées Spotify/Deezer/recherche
texte) et des candidats de lecture (résultats YouTube/SoundCloud). Ne prend jamais le
premier résultat au hasard — voir utils/music/__init__.py pour l'architecture globale.

Compare titre normalisé, artiste et durée ; écarte nightcore/slowed/sped up/cover/
remix/karaoke SAUF si l'utilisateur les a explicitement demandés dans sa requête
d'origine ; donne un bonus aux versions officielles."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import Track

# Variantes qu'on écarte par défaut : quelqu'un qui demande "Blinding Lights" veut la
# vraie chanson, pas une version nightcore accélérée de 30% ou un karaoké instrumental.
VARIANT_MARKERS: dict[str, tuple[str, ...]] = {
    "nightcore": ("nightcore",),
    "slowed": ("slowed", "slow + reverb", "slowed + reverb", "slowed reverb"),
    "sped_up": ("sped up", "sped-up", "speed up", "fast version"),
    "cover": ("cover", "reprise"),
    "remix": ("remix", "rmx"),
    "karaoke": ("karaoke", "instrumental", "sans voix", "backing track"),
    "8d_audio": ("8d audio", "8d ", "bass boosted", "bass boost"),
}

OFFICIAL_MARKERS = (
    "official video", "official audio", "official music video", "official mv",
    "clip officiel", "audio officiel", "official lyric video",
)

_BRACKETED_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Minuscule, sans accents, sans ponctuation, espaces compactés. Utilisé
    uniquement pour la COMPARAISON — jamais affiché à l'utilisateur."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def _strip_brackets(text: str) -> str:
    """Retire "(Official Video)", "[Lyrics]", etc. avant comparaison de titre — ces
    mentions font partie du titre YouTube mais pas du titre "réel" de la chanson."""
    return _SPACE_RE.sub(" ", _BRACKETED_RE.sub(" ", text)).strip()


def detect_variants(text: str) -> set[str]:
    """Détecte quelles variantes (nightcore, slowed...) sont mentionnées dans un
    texte (titre de candidat OU requête utilisateur d'origine)."""
    normalized = normalize(text)
    found = set()
    for tag, markers in VARIANT_MARKERS.items():
        if any(normalize(marker) in normalized for marker in markers):
            found.add(tag)
    return found


def is_official(text: str) -> bool:
    normalized = normalize(text)
    return any(normalize(marker) in normalized for marker in OFFICIAL_MARKERS)


def _title_similarity(a: str, b: str) -> float:
    a, b = normalize(_strip_brackets(a)), normalize(_strip_brackets(b))
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _duration_score(target: int | None, candidate: int | None) -> float:
    """1.0 si les durées sont identiques ou inconnues (pas de pénalité quand on ne
    sait pas), dégradation progressive au-delà de 5s d'écart, 0 au-delà de 20s —
    assez large pour absorber les différences d'encodage/silence de fin, assez
    strict pour rejeter un extended mix ou une version tronquée."""
    if target is None or candidate is None:
        return 1.0
    diff = abs(target - candidate)
    if diff <= 3:
        return 1.0
    if diff >= 20:
        return 0.0
    return max(0.0, 1.0 - (diff - 3) / 17)


def _is_gross_duration_mismatch(target: int | None, candidate: int | None) -> bool:
    """Rejet catégorique (pas une simple pénalité de score) pour un écart qui ne
    peut pas s'expliquer par un montage différent — ex: cible 3 min, candidat 1h
    (compilation/extended mix/live intégral). Sans ce garde-fou, un bon score de
    titre/artiste pouvait suffire à faire passer un contenu manifestement différent
    malgré une durée à 0 sur ce critère (vérifié par test)."""
    if target is None or candidate is None or target <= 0:
        return False
    diff = abs(target - candidate)
    return diff > 60 and candidate > target * 2.5


def score_candidate(target: Track, candidate: Track, *, requested_variants: set[str]) -> float:
    """Score de 0 (aucune correspondance) à ~1.15 (correspondance officielle
    parfaite). requested_variants = variantes explicitement demandées par
    l'utilisateur dans sa requête d'origine (ex: {"remix"} si "remix" était dans la
    recherche) — ces variantes ne sont alors PAS pénalisées."""
    if _is_gross_duration_mismatch(target.duration, candidate.duration):
        return 0.0

    title_sim = _title_similarity(target.title, candidate.title)
    score = title_sim * 0.55

    if target.artist and candidate.artist:
        score += _title_similarity(target.artist, candidate.artist) * 0.25
    elif target.artist:
        # L'artiste cible est connu mais le candidat n'en a pas / le titre du
        # candidat le contient peut-être (cas YouTube fréquent : "Artiste - Titre").
        if normalize(target.artist) in normalize(candidate.title):
            score += 0.15
    else:
        score += 0.10  # pas d'artiste cible à comparer : neutre, pas de pénalité

    score += _duration_score(target.duration, candidate.duration) * 0.20

    candidate_variants = detect_variants(candidate.title)
    unwanted = candidate_variants - requested_variants
    if unwanted:
        score -= 0.35 * len(unwanted)
    missing_requested = requested_variants - candidate_variants
    if missing_requested:
        # L'utilisateur a demandé un remix, ce candidat n'en est pas un — pénalité
        # forte : sans elle, un candidat "officiel" (artiste exact + bonus officiel)
        # continuait à gagner malgré la demande explicite (vérifié par test).
        score -= 0.5 * len(missing_requested)

    # Le bonus "officiel" n'a de sens que si l'utilisateur n'a PAS explicitement
    # demandé une variante (nightcore/remix/cover/...) : une version "officielle"
    # n'est alors justement pas ce qu'il veut.
    if is_official(candidate.title) and not requested_variants:
        score += 0.10

    return max(0.0, score)


# En dessous de ce score, on préfère dire "aucune source trouvée" plutôt que de
# jouer un résultat qui n'a probablement rien à voir avec la demande.
MIN_ACCEPTABLE_SCORE = 0.45
# Les recherches +play en texte libre n'ont ni artiste structuré ni durée. Le score
# historique leur accordait donc 0.30 point "neutre", ce qui pouvait faire passer un
# titre sans rapport. On exige en plus une vraie proximité de titre dans ce cas.
FREE_TEXT_MIN_TITLE_SIMILARITY = 0.55


def pick_best(
    target: Track,
    candidates: list[Track],
    *,
    original_query: str = "",
) -> Track | None:
    """Retourne le meilleur candidat, ou None si aucun ne dépasse le seuil minimum.
    `original_query` sert à détecter si l'utilisateur a lui-même demandé une variante
    (ex: recherche "toto africa remix" -> le mot "remix" n'est alors plus pénalisé)."""
    if not candidates:
        return None
    requested_variants = detect_variants(original_query) | detect_variants(target.title)
    scored = [
        (score_candidate(target, candidate, requested_variants=requested_variants), candidate)
        for candidate in candidates
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = scored[0]
    if best_score < MIN_ACCEPTABLE_SCORE:
        return None
    if target.artist is None and target.duration is None:
        if _title_similarity(target.title, best.title) < FREE_TEXT_MIN_TITLE_SIMILARITY:
            return None
    best.match_score = best_score
    return best
