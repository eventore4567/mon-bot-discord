"""Génération et sélection des bannières de logs SentriX.

Les cinq bannières sont stockées dans ``assets/log_banners`` afin que le renderer
Components V2 puisse les joindre comme premier média du message. La génération est
mise en cache en mémoire et un fichier supprimé à chaud est recréé automatiquement.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BANNER_DIR = ROOT / "assets" / "log_banners"

WIDTH = 1024
HEIGHT = 110

COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "error": ((255, 65, 85), (125, 20, 45)),
    "success": ((45, 220, 110), (15, 105, 60)),
    "warning": ((255, 185, 55), (180, 80, 20)),
    "info": ((55, 145, 255), (45, 70, 200)),
    "special": ((165, 95, 255), (75, 40, 185)),
}

_READY = False


def _mix(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def ensure_banners(force: bool = False) -> None:
    """Génère les cinq bannières si elles n'existent pas déjà."""
    global _READY

    if _READY and not force:
        return

    BANNER_DIR.mkdir(parents=True, exist_ok=True)

    for kind, (left, right) in COLORS.items():
        path = BANNER_DIR / f"banner_{kind}.png"

        if path.exists() and not force:
            continue

        image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        pixels = image.load()

        for x in range(WIDTH):
            t = x / max(1, WIDTH - 1)
            r = _mix(left[0], right[0], t)
            g = _mix(left[1], right[1], t)
            b = _mix(left[2], right[2], t)

            for y in range(HEIGHT):
                center_light = 1 - abs((y / max(1, HEIGHT - 1)) * 2 - 1)
                brightness = 0.86 + center_light * 0.14
                pixels[x, y] = (
                    min(255, round(r * brightness)),
                    min(255, round(g * brightness)),
                    min(255, round(b * brightness)),
                    255,
                )

        # La bannière V2 reste entièrement opaque : aucun trou central artificiel.
        image.save(path, "PNG")

    _READY = True


# Ordre de priorité : les actions spécifiques sont évaluées avant les mots génériques.
# Ainsi « unban » est vert avant que « ban » puisse être détecté en rouge.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "success",
        (
            "unban", "déban", "deban", "unmute", "untimeout",
            "restaur", "réussi", "reussi", "succès", "succes",
            "activé", "active", "ajouté", "ajoute", "levé", "leve",
        ),
    ),
    (
        "special",
        (
            "arrivée", "arrivee", "rejoint", "bienvenue", "welcome",
            "boost", "special", "spécial", "anniversaire", "niveau",
        ),
    ),
    (
        "warning",
        (
            "warn", "avert", "mute", "timeout", "permission",
            "automod", "anti-spam", "antispam", "attention",
            "manquant", "échec", "echec", "refus",
        ),
    ),
    (
        "error",
        (
            "supprim", "delete", "ban", "kick", "expuls",
            "sanction", "erreur", "error", "départ", "depart",
            "quitté", "quitte", "blacklist", "purge",
        ),
    ),
)


def banner_kind(log_type: str, title: str = "", description: str = "") -> str:
    """Retourne ``error/success/warning/info/special`` pour un événement de log."""
    text = f"{log_type} {title} {description}".casefold()

    for kind, words in _RULES:
        if any(word in text for word in words):
            return kind

    return "info"


def get_banner(log_type: str, title: str = "", description: str = "") -> Path:
    """Retourne la bannière voulue et la recrée si elle a été supprimée à chaud."""
    ensure_banners()
    kind = banner_kind(log_type, title, description)
    path = BANNER_DIR / f"banner_{kind}.png"

    if not path.exists():
        ensure_banners(force=True)

    return path


__all__ = [
    "BANNER_DIR",
    "COLORS",
    "HEIGHT",
    "WIDTH",
    "banner_kind",
    "ensure_banners",
    "get_banner",
]
