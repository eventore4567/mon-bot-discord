"""Détection bornée des copies de messages pour le module SecurityHardening.

Évite l'accumulation illimitée d'empreintes lorsqu'un serveur reçoit des
milliers de messages tous différents. La fenêtre et le seuil existants sont
conservés ; les données ne survivent pas au redémarrage.
"""
from __future__ import annotations

import time
import unicodedata
from collections import OrderedDict


class DuplicateMessageWindow:
    def __init__(
        self,
        *,
        window_seconds: float = 12,
        threshold: int = 3,
        max_fingerprints: int = 4096,
    ) -> None:
        if window_seconds <= 0 or threshold < 2 or max_fingerprints < 1:
            raise ValueError("Paramètres anti-spam invalides")
        self.window_seconds = float(window_seconds)
        self.threshold = int(threshold)
        self.max_fingerprints = int(max_fingerprints)
        self._hits: OrderedDict[tuple[int, int, str], list[float]] = OrderedDict()

    @staticmethod
    def _fingerprint(content: str) -> str:
        value = unicodedata.normalize("NFKC", str(content or ""))
        value = "".join(c for c in value if unicodedata.category(c) != "Cf")
        return " ".join(value.casefold().split())[:300]

    def add(
        self, guild_id: int, user_id: int, content: str, *, now: float | None = None
    ) -> bool:
        """Retourne vrai dès trois copies dans une fenêtre de 12 secondes."""
        value = self._fingerprint(content)
        moment = time.monotonic() if now is None else float(now)
        cutoff = moment - self.window_seconds

        # Les clés sont ordonnées par dernière activité : éviction O(1)
        # amortie, même sous un flood de messages uniques.
        while self._hits:
            oldest = next(iter(self._hits))
            if self._hits[oldest][-1] >= cutoff:
                break
            self._hits.popitem(last=False)

        if len(value) < 3:
            return False

        key = (int(guild_id), int(user_id), value)
        past = self._hits.pop(key, [])
        hits = [stamp for stamp in past if stamp >= cutoff]
        hits.append(moment)
        if len(hits) >= self.threshold:
            return True

        self._hits[key] = hits
        while len(self._hits) > self.max_fingerprints:
            self._hits.popitem(last=False)
        return False

    def __len__(self) -> int:
        return len(self._hits)


__all__ = ["DuplicateMessageWindow"]
