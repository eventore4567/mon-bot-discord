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
# Découpe par balisage Discord : « co||nnard » et « co**nnard** » s'affichent
# comme un seul mot pour le lecteur, mais la ponctuation devenant un espace
# plus bas, ils arrivaient en DEUX tokens que rien ne recollait — le recollage
# ne traite que les suites de caractères isolés (« c o n »). Mesuré le
# 2026-10-14 : 76 évasions sur ces deux familles seules. On retire donc les
# marqueurs avant la passe de ponctuation, ce qui reconstitue le mot vu.
_MARQUEURS_DISCORD_RE = re.compile(r"\|\||\*\*|__|~~|`")
_NO_SPACE_SCRIPT_RE = re.compile(r"[\u0e00-\u0e7f\u3040-\u30ff\u3400-\u9fff]")

# Termes pouvant être vulgaires, sexuels ou familiers sans constituer à eux seuls
# une insulte envers quelqu'un. L'anti-insulte ne doit pas supprimer un message
# simplement parce qu'il contient l'un de ces mots isolés. Les PHRASES/groupes du
# dataset restent analysés : par exemple un terme ambigu intégré à une attaque
# explicite peut toujours être détecté par le moteur contextuel.
_AMBIGUOUS_STANDALONE_TERMS = frozenset({
    "anal", "anus", "bdsm", "bite", "bobo", "boob", "butt", "caca", "cul",
    "fan", "guro", "meuf", "milf", "mama", "nsfw", "nude", "orgy", "pipi",
    "porn", "porno", "pot", "scat", "sex", "sexo", "sexy", "sm", "smut",
    "trio", "xx", "xxx", "yaoi", "zizi",
})

# Mots parfaitement ordinaires en français que le dataset multilingue contient
# comme insultes. Mesuré le 2026-10-14 sur 151 mots français courants : ces
# trois-là, et eux seuls, faisaient supprimer des phrases banales —
# « il a attrapé la balle au vol », « cette idée est folle mais géniale »,
# « je mets une pelle dans le coffre » — avec une confiance de 0,70, soit
# au-dessus du seuil de suppression de cogs/automod.
#
# Les retirer du dataset laisserait passer « tu es une folle ». Ils ne sont
# donc pas supprimés : ils exigent une cible explicite (tu, toi, vous…).
# « pele » mérite une mention : ce n'est pas « pelle » qui est dans le dataset,
# c'est « pele ». C'est donc le compactage des lettres étirées, ajouté le même
# jour pour fermer 38 évasions, qui rendait « pelle » détectable. Scan de
# vérification sur les 12 760 mots du dépôt : la compaction ne crée que deux
# détections nouvelles, « pelle »->« pele » et « conn »->« con » — la seconde
# étant une abréviation de code, et « con » une vraie insulte.
_TERMES_ORDINAIRES_SAUF_SI_CIBLE = frozenset({"balle", "folle", "pelle", "pele"})

# Les tokens de 1–2 caractères sont beaucoup trop ambigus dans un dataset
# multilingue pour justifier une suppression de message à eux seuls.
_MIN_STANDALONE_LENGTH = 3


@dataclass(frozen=True)
class ModerationMatch:
    kind: str
    confidence: float = 0.0
    targeted: bool = False
    reason: str = "contexte indéterminé"


_TARGET_MARKERS = frozenset({
    "tu", "toi", "ton", "ta", "tes", "vous", "votre", "vos",
    "you", "your", "youre", "u", "ur",
    "eres", "usted", "ustedes", "te", "tus",
})
# La normalisation casse l'apostrophe : « t'es » devient « t es ». Sans ces
# bigrammes, « t'es qu'une folle » n'était pas vu comme adressé alors que
# « tu es une folle » l'était — or c'est la forme la plus courante en tchat
# français. Un « t » isolé ne vient que d'une contraction de deuxième personne.
_MARQUEURS_CIBLE_CONTRACTES = ("t es", "t as", "t etais", "t avais", "t seras", "t etais")

_REPORTING_MARKERS = (
    "il m a dit", "elle m a dit", "on m a dit", "m a traite", "m a insult",
    "exemple", "citation", "je cite", "quote", "quoted", "he said", "she said",
    "they said", "called me", "lyrics", "paroles", "definition", "définition",
)


# Pour les mots ordinaires en français, un simple « ton » ne suffit pas :
# « la balle est dans ton camp » est une expression figée, pas une insulte. Il
# faut une attribution explicite — quelqu'un EST traité de ce mot.
_ATTRIBUTIONS = (
    "tu es", "t es", "tu n es", "vous etes", "t as", "tu as",
    "espece de", "bande de", "sale", "quelle", "quel", "t etais", "tu etais",
)


def _attribue_a_quelquun(normalized: str) -> bool:
    """Le mot est-il attribué à une personne, et pas seulement voisin d'un « ton » ?"""
    return any(f" {motif} " in f" {normalized} " for motif in _ATTRIBUTIONS)


def _context_confidence(normalized: str, kind: str) -> tuple[float, bool, str]:
    """Estime prudemment si le motif est une attaque, pas une citation ou un cours."""
    tokens = tuple(normalized.split())
    targeted = bool(set(tokens) & _TARGET_MARKERS) or any(
        marqueur in normalized for marqueur in _MARQUEURS_CIBLE_CONTRACTES
    )
    reporting = any(marker in normalized for marker in _REPORTING_MARKERS)
    base = {
        "phrase": 0.94,
        "groupe_de_mots": 0.93,
        "mot_ou_phrase_sans_espace": 0.88,
        "mot": 0.70,
    }.get(kind, 0.50)
    if targeted:
        base += 0.24 if kind == "mot" else 0.08
    if reporting:
        base -= 0.42
    confidence = max(0.0, min(0.99, base))
    reason = "attaque adressée" if targeted else "motif offensant sans cible certaine"
    if reporting:
        reason = "citation, signalement ou contexte pédagogique possible"
    return confidence, targeted, reason


def normalize_message(text: str) -> str:
    """Forme comparable d'un message : confusables, invisibles, ponctuation.

    La normalisation NFKC seule laissait passer presque tout : sur 200 termes du
    dataset, le cyrillique en attrapait 5, le leet 2, les petites capitales
    aucune. Le texte passe donc d'abord par utils.text_normalization, qui ramène
    « ᴄᴏɴ », « сon » (с cyrillique) et le gras mathématique à des lettres ASCII.
    """
    from utils.text_normalization import normaliser

    value = normaliser(text)
    value = _ZERO_WIDTH_RE.sub("", value)
    value = _URL_RE.sub(" ", value)
    value = _DISCORD_MARKUP_RE.sub(" ", value)
    value = _MARQUEURS_DISCORD_RE.sub("", value)
    value = "".join(char if (char.isalnum() or char.isspace()) else " " for char in value)
    return " ".join(value.split())


# Substitutions leet, appliquées comme variante SUPPLÉMENTAIRE d'un token — jamais
# en remplacement : « a1 » ne doit pas cesser d'être « a1 » sous prétexte qu'il
# pourrait se lire « ai ».
_LEET_TOKEN = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})


_REPETITIONS_RE = re.compile(r"(.)\1+")


def _compacter_repetitions(token: str) -> str:
    """« aaaanduu » -> « andu ». Une seule lettre par série identique."""
    return _REPETITIONS_RE.sub(r"\1", token)


def _tokens_candidats(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Tous les tokens à tester : les vrais, les recollés et les dé-leetés.

    Deux contournements triviaux, mesurés à 100 % de réussite avant ce correctif :
    « c o n » et « c.o.n ». La ponctuation ayant déjà été remplacée par des
    espaces, les deux arrivent ici comme une suite de tokens d'un seul caractère.
    On recolle donc ces suites — et SEULEMENT elles. Chercher le terme en
    sous-chaîne du message entier, la solution évidente, ferait correspondre
    « con » dans « connexion » : c'est précisément ce que la comparaison par
    token exact évitait, et il n'est pas question de le perdre.
    """
    candidats = list(tokens)

    suite: list[str] = []
    for token in (*tokens, ""):
        if len(token) == 1 and token.isalnum():
            suite.append(token)
            continue
        if len(suite) >= 3:
            candidats.append("".join(suite))
        suite = []

    # Lettres étirées : « coonnaard » se lit comme le terme nominal. On ajoute
    # la forme compactée en CANDIDAT, jamais en remplacement — « bonne » reste
    # « bonne » et ne devient pas « bone ». Mesuré le 2026-10-14 : 38 évasions
    # sur cette seule famille.
    for token in list(candidats):
        compacte = _compacter_repetitions(token)
        if compacte != token and len(compacte) >= 3:
            candidats.append(compacte)

    for token in list(candidats):
        deleete = token.translate(_LEET_TOKEN)
        if deleete != token:
            candidats.append(deleete)
    return tuple(candidats)


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
                    confidence, targeted, reason = _context_confidence(normalized, "phrase")
                    return ModerationMatch("phrase", confidence, targeted, reason)

        compact = normalized.replace(" ", "")
        for first_character in set(compact):
            for candidate in self._substrings_by_first.get(first_character, ()):
                if candidate in compact:
                    kind = "mot_ou_phrase_sans_espace"
                    confidence, targeted, reason = _context_confidence(normalized, kind)
                    return ModerationMatch(kind, confidence, targeted, reason)

        for max_gap, group_tokens, uses_no_space_script in self._groups:
            if uses_no_space_script:
                if self._ordered_substring_group(compact, group_tokens):
                    kind = "groupe_de_mots"
                    confidence, targeted, reason = _context_confidence(normalized, kind)
                    return ModerationMatch(kind, confidence, targeted, reason)
            elif self._ordered_token_group(tokens, group_tokens, max_gap):
                kind = "groupe_de_mots"
                confidence, targeted, reason = _context_confidence(normalized, kind)
                return ModerationMatch(kind, confidence, targeted, reason)

        for token in _tokens_candidats(tokens):
            if token not in self._terms:
                continue
            if len(token) < _MIN_STANDALONE_LENGTH:
                continue
            if token in _AMBIGUOUS_STANDALONE_TERMS:
                continue
            confidence, targeted, reason = _context_confidence(normalized, "mot")
            if token in _TERMES_ORDINAIRES_SAUF_SI_CIBLE and not _attribue_a_quelquun(normalized):
                continue
            return ModerationMatch("mot", confidence, targeted, reason)
        return None
