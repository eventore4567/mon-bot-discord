"""Détection multilingue locale pour l'AutoMod SentriX.

Le fichier de données compact conserve les 2 663 termes, 1 200 phrases et 120 groupes
du dataset fourni. Il est chargé une seule fois au démarrage du cog : aucun appel réseau
et aucune requête SQLite ne sont effectués pour analyser un message.
"""

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("bot")

DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "sentrix_multilingual_moderation_dataset.json"
)
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DISCORD_MARKUP_RE = re.compile(r"<(?:@!?|@&|#)\d+>|<a?:[A-Za-z0-9_]+:\d+>")
_NO_SPACE_SCRIPT_RE = re.compile(r"[\u0e00-\u0e7f\u3040-\u30ff\u3400-\u9fff]")


@dataclass(frozen=True)
class ModerationMatch:
    kind: str


def normalize_message(text: str) -> str:
    """NFKC + casse Unicode + retrait des caractères invisibles et de la ponctuation."""
    value = unicodedata.normalize("NFKC", text or "").casefold()
    value = _ZERO_WIDTH_RE.sub("", value)
    value = _URL_RE.sub(" ", value)
    value = _DISCORD_MARKUP_RE.sub(" ", value)
    value = "".join(char if (char.isalnum() or char.isspace()) else " " for char in value)
    return " ".join(value.split())


def _uses_no_space_script(value: str) -> bool:
    return bool(_NO_SPACE_SCRIPT_RE.search(value))


class MultilingualModerationDataset:
    """Index en mémoire optimisé pour les messages Discord courts."""

    def __init__(self, path: Path | str = DATASET_PATH):
        self.path = Path(path)
        self.loaded = False
        self.version = 0
        self.languages: tuple[str, ...] = ()
        self.source_counts = {"terms": 0, "phrases": 0, "groups": 0}
        self._terms: set[str] = set()
        self._phrases_by_first: dict[str, set[tuple[str, ...]]] = {}
        self._substrings_by_first: dict[str, set[str]] = {}
        self._groups: list[tuple[int, tuple[str, ...], bool]] = []
        self._load()

    def _add_phrase(self, value: str):
        normalized = normalize_message(value)
        if not normalized:
            return
        if _uses_no_space_script(normalized):
            compact = normalized.replace(" ", "")
            self._substrings_by_first.setdefault(compact[0], set()).add(compact)
            return
        parts = tuple(normalized.split())
        if len(parts) == 1:
            self._terms.add(parts[0])
            return
        self._phrases_by_first.setdefault(parts[0], set()).add(parts)

    def _load(self):
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            terms = payload["terms"]
            term_modes = payload["term_modes"]
            phrases = payload["phrases"]
            groups = payload["groups"]
            if len(terms) != len(term_modes):
                raise ValueError("terms et term_modes ont des longueurs différentes")

            self.version = int(payload.get("version", 1))
            self.languages = tuple(payload.get("languages", ()))
            self.source_counts = {
                "terms": len(terms),
                "phrases": len(phrases),
                "groups": len(groups),
            }

            for term, mode in zip(terms, term_modes):
                if mode == "exact_phrase":
                    self._add_phrase(term)
                    continue
                normalized = normalize_message(term)
                if not normalized:
                    continue
                if _uses_no_space_script(normalized):
                    compact = normalized.replace(" ", "")
                    self._substrings_by_first.setdefault(compact[0], set()).add(compact)
                elif " " in normalized:
                    self._add_phrase(normalized)
                else:
                    self._terms.add(normalized)

            for phrase in phrases:
                self._add_phrase(phrase)

            for raw_gap, raw_tokens in groups:
                tokens = tuple(
                    part
                    for token in raw_tokens
                    for part in normalize_message(token).split()
                    if part
                )
                if tokens:
                    self._groups.append((
                        max(0, int(raw_gap)),
                        tokens,
                        any(_uses_no_space_script(token) for token in tokens),
                    ))

            self.loaded = True
            logger.info(
                "Dataset AutoMod chargé : %s termes, %s phrases, %s groupes, %s langues",
                self.source_counts["terms"],
                self.source_counts["phrases"],
                self.source_counts["groups"],
                len(self.languages),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            logger.exception("Impossible de charger le dataset multilingue AutoMod : %s", self.path)

    @staticmethod
    def _ordered_token_group(
        message_tokens: tuple[str, ...],
        group_tokens: tuple[str, ...],
        max_gap: int,
    ) -> bool:
        first = group_tokens[0]
        for start, token in enumerate(message_tokens):
            if token != first:
                continue
            cursor = start
            matched = True
            for wanted in group_tokens[1:]:
                stop = min(len(message_tokens), cursor + max_gap + 2)
                next_position = next(
                    (index for index in range(cursor + 1, stop) if message_tokens[index] == wanted),
                    None,
                )
                if next_position is None:
                    matched = False
                    break
                cursor = next_position
            if matched:
                return True
        return False

    @staticmethod
    def _ordered_substring_group(compact: str, group_tokens: tuple[str, ...]) -> bool:
        cursor = 0
        for token in group_tokens:
            wanted = token.replace(" ", "")
            position = compact.find(wanted, cursor)
            if position < 0:
                return False
            cursor = position + len(wanted)
        return True

    def match(self, text: str) -> ModerationMatch | None:
        if not self.loaded or not isinstance(text, str) or not text.strip():
            return None

        normalized = normalize_message(text)
        if not normalized:
            return None
        tokens = tuple(normalized.split())

        # Les motifs les plus précis passent avant le mot isolé. Cela permet aux logs
        # de distinguer réellement une phrase ou un groupe avec des mots intercalés.
        for index, token in enumerate(tokens):
            for phrase in self._phrases_by_first.get(token, ()):
                if tokens[index:index + len(phrase)] == phrase:
                    return ModerationMatch("phrase")

        compact = normalized.replace(" ", "")
        for first_character in set(compact):
            for candidate in self._substrings_by_first.get(first_character, ()):
                if candidate in compact:
                    return ModerationMatch("mot_ou_phrase_sans_espace")

        for max_gap, group_tokens, uses_no_space_script in self._groups:
            if uses_no_space_script:
                if self._ordered_substring_group(compact, group_tokens):
                    return ModerationMatch("groupe_de_mots")
            elif self._ordered_token_group(tokens, group_tokens, max_gap):
                return ModerationMatch("groupe_de_mots")

        if any(token in self._terms for token in tokens):
            return ModerationMatch("mot")
        return None
