"""Génération des bannières SentriX (1024x110, quatorze familles).

Le visuel est volontairement minimal : le canevas est **100 % transparent**.
Seuls deux éléments sont dessinés :
- un long trait lumineux coloré de chaque côté ;
- le logo SentriX, centré et teinté de la même couleur.

Aucun rectangle, fond bleu/noir, dégradé, cadre ou liseré n'est rendu. Discord
laisse donc apparaître directement le fond naturel du panneau sous la bannière.
La famille de couleur vient du registre des logs ou du domaine de la commande.
Le logo est facultatif : s'il est absent, les traits restent rendus.
"""
from __future__ import annotations

import logging

import config
from pathlib import Path

from PIL import Image, ImageFilter

logger = logging.getLogger("bot.log-banners")

ROOT = Path(__file__).resolve().parents[1]
BANNER_DIR = ROOT / "assets" / "log_banners"

# Logo de la bannière, par ordre de préférence. assets/sentrix_logo.png n'existe pas dans
# le dépôt : on retombe sur la marque déjà présente. Déposer sentrix_logo.png suffit à
# prendre la main sans toucher au code.
_LOGO_CANDIDATES = (
    ROOT / "assets" / "sentrix_logo.png",
    ROOT / "assets" / "sentrix" / "brand.png",
)


def _resolve_logo():
    for candidate in _LOGO_CANDIDATES:
        if candidate.exists():
            return candidate
    return _LOGO_CANDIDATES[0]


LOGO_PATH = _resolve_logo()
WIDTH = 1024
HEIGHT = 110

# Côté du logo centré. 70 px sur 110 : lisible sur mobile sans manger le trait.
LOGO_BOX = 70


def _rgb(value: int) -> tuple[int, int, int]:
    value = int(value)
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


# La première couleur de chaque paire est l'accent réellement rendu. La seconde
# reste présente uniquement pour compatibilité avec les quelques consommateurs
# historiques qui attendent encore la forme (accent, deep). Le fond n'utilise plus
# jamais cette seconde valeur.
COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    # États : même source que les accents des panneaux Discord.
    "error": (_rgb(config.COLOR_ERROR), (168, 30, 58)),
    "success": (_rgb(config.COLOR_SUCCESS), (18, 132, 86)),
    "warning": (_rgb(config.COLOR_WARNING), (188, 104, 20)),
    "info": (_rgb(config.COLOR_INFO), (44, 86, 214)),
    "special": (_rgb(config.COLOR_BRAND), (88, 44, 190)),
    # Domaines.
    "moderation": ((244, 104, 124), (132, 30, 58)),
    "security": ((132, 124, 250), (58, 44, 170)),
    "economy": ((248, 202, 96), (168, 110, 24)),
    "config": ((84, 222, 228), (26, 116, 150)),
    "levels": ((170, 228, 92), (86, 140, 28)),
    "music": ((255, 108, 188), (162, 34, 122)),
    "tickets": ((58, 214, 198), (18, 118, 122)),
    "games": ((255, 150, 72), (176, 74, 16)),
    "ai": ((214, 124, 255), (120, 46, 190)),
}

# Compatibilité d'import uniquement : la bannière n'a plus de fond.
NIGHT = (0, 0, 0)
NIGHT_EDGE = (0, 0, 0)
TINT = 0.0

STYLES = tuple(COLORS)

# WebP plutot que PNG : la banniere part en piece jointe a CHAQUE message, et le
# meme visuel pese 5 Ko au lieu de 45. Sur un degrade avec logo, la difference ne
# se voit pas ; sur la bande passante d'un gros serveur, si.
EXTENSION = "webp"
_QUALITE_WEBP = 88


def nom_fichier(style: str) -> str:
    """Nom du fichier de banniere pour une famille."""
    return f"banner_{style}.{EXTENSION}"
_READY = False


def _transparent_canvas() -> Image.Image:
    """Canevas sans aucun fond : alpha nul sur les 1024×110 pixels."""
    return Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))


def _add_glow_lines(image: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    """Deux traits lumineux partant des bords vers le centre.

    Un cœur net d'un pixel porte le dessin, un bloom flouté porte la lumière :
    la même image reste nette sur un écran de téléphone et lumineuse en grand.
    """
    y = HEIGHT // 2
    inner = (WIDTH // 2 - LOGO_BOX // 2 - 8, WIDTH // 2 + LOGO_BOX // 2 + 8)
    # Le trait court presque d'un bord a l'autre : il ne s'arrete qu'assez tot pour
    # s'eteindre proprement au lieu d'etre coupe net par le bord de l'image.
    outer = (26, WIDTH - 26)

    core = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    bloom = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    core_pixels, bloom_pixels = core.load(), bloom.load()

    for x in range(WIDTH):
        if outer[0] <= x <= inner[0]:
            # Segment gauche : éteint au bord, plein près du logo.
            t = (x - outer[0]) / max(1, inner[0] - outer[0])
        elif inner[1] <= x <= outer[1]:
            t = (outer[1] - x) / max(1, outer[1] - inner[1])
        else:
            continue
        t = t * t * (3.0 - 2.0 * t)  # smoothstep : pas de coupure franche
        blanc = round(120 * t * t)  # le cœur vire au blanc là où il est le plus fort
        core_pixels[x, y] = (
            min(255, accent[0] + blanc), min(255, accent[1] + blanc),
            min(255, accent[2] + blanc), round(255 * t),
        )
        core_pixels[x, y - 1] = (*accent, round(120 * t))
        core_pixels[x, y + 1] = (*accent, round(90 * t))
        for offset in (-3, -2, -1, 0, 1, 2, 3):
            bloom_pixels[x, y + offset] = (*accent, round(235 * t))

    bloom = bloom.filter(ImageFilter.GaussianBlur(6))
    image = Image.alpha_composite(image, bloom)
    return Image.alpha_composite(image, core)


def _tinted_logo(logo: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    """Logo re-teinté à la couleur d'accent, ses reliefs conservés.

    Le logo du dépôt est bleu : tel quel, il jurait sur une bannière rouge ou or.
    On garde sa luminance (donc son relief) et on la projette sur la couleur de
    la famille — trait et logo parlent alors de la même chose.
    """
    alpha = logo.getchannel("A")
    luminance = logo.convert("L")
    tinted = Image.new("RGBA", logo.size)
    source = luminance.load()
    target = tinted.load()
    for y in range(logo.height):
        for x in range(logo.width):
            level = source[x, y] / 255.0
            # Ombres légèrement teintées, hautes lumières proches du blanc.
            shade = 0.42 + level * 0.58
            target[x, y] = (
                min(255, round(accent[0] * shade + 255 * level * level * 0.55)),
                min(255, round(accent[1] * shade + 255 * level * level * 0.55)),
                min(255, round(accent[2] * shade + 255 * level * level * 0.55)),
                255,
            )
    tinted.putalpha(alpha)
    return tinted


def _composite_logo(image: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    """Logo centré, teinté, avec halo. Absence du fichier = bannière rendue telle quelle."""
    if not LOGO_PATH.exists():
        return image
    try:
        with Image.open(LOGO_PATH) as opened:
            logo = opened.convert("RGBA")
    except (OSError, ValueError):
        logger.warning("Logo illisible (%s) : bannière générée sans logo.", LOGO_PATH)
        return image

    scale = min(LOGO_BOX / max(1, logo.width), LOGO_BOX / max(1, logo.height))
    size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
    if size != logo.size:
        logo = logo.resize(size, Image.Resampling.LANCZOS)
    logo = _tinted_logo(logo, accent)

    x, y = (WIDTH - logo.width) // 2, (HEIGHT - logo.height) // 2
    halo_mask = Image.new("L", (WIDTH, HEIGHT), 0)
    halo_mask.paste(logo.getchannel("A"), (x, y))
    halo_mask = halo_mask.filter(ImageFilter.GaussianBlur(10))
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (*accent, 0))
    halo.putalpha(halo_mask.point(lambda value: min(110, round(value * 0.45))))
    image = Image.alpha_composite(image, halo)
    image.alpha_composite(logo, (x, y))
    return image


def build_banner(style: str) -> Image.Image:
    accent, _legacy_deep = COLORS.get(style, COLORS["info"])
    image = _transparent_canvas()
    image = _add_glow_lines(image, accent)
    return _composite_logo(image, accent)


def ensure_banners(force: bool = False) -> None:
    """Genere une banniere par famille. ``force=True`` regenere le cache disque.

    Les fichiers sont ecrits une seule fois au demarrage, puis relus depuis le
    disque a chaque envoi : aucune image n'est recalculee par commande.
    """
    global _READY
    if _READY and not force:
        return
    BANNER_DIR.mkdir(parents=True, exist_ok=True)
    for style in COLORS:
        path = BANNER_DIR / nom_fichier(style)
        if path.exists() and not force:
            continue
        try:
            build_banner(style).save(
                path, "WEBP", quality=_QUALITE_WEBP, method=6
            )
        except Exception:
            logger.exception("Génération de la bannière %s impossible.", style)
    _READY = True


# Domaine SentriX -> famille de banniere. Le module vient de utils/access_matrix
# (la source unique qui sait deja a quel module appartient chaque commande) ; les
# racines ci-dessous couvrent ce qui n'est rattache a aucun module.
MODULE_FAMILIES: dict[str, str] = {
    "economy": "economy", "levels": "levels", "ai": "ai", "tickets": "tickets",
    "moderation": "moderation", "security": "security",
    "logs": "config", "welcome": "config", "goodbye": "config",
    "roles": "config", "notifications": "config",
}
COG_FAMILIES: dict[str, str] = {
    "music": "music", "minigames": "games", "gameseconomy": "games",
    "economy": "economy", "levels": "levels", "stats": "levels", "ai": "ai",
    "tickets": "tickets", "moderation": "moderation", "automod": "security",
    "security": "security", "securitytools": "security", "verification": "security",
    "configuration": "config", "serverbuilder": "config", "notifications": "config",
    "events": "special", "design": "special", "embedbuilder": "config",
}
COMMAND_FAMILIES: dict[str, str] = {
    # Racines sans module : leur famille est declaree ici plutot que devinee.
    "play": "music", "music": "music", "nowplaying": "music", "queue": "music",
    "skip": "music", "stop": "music", "pause": "music", "resume": "music",
    "volume": "music", "seek": "music", "shuffle": "music", "join": "music", "leave": "music",
    "giveaway": "special", "concours": "special",
    "setup": "config", "help": "info", "ping": "info", "sentrix": "info",
}


def family_for_command(name: str = "", cog_name: str = "") -> str | None:
    """Famille de banniere qui va avec la commande, ou None si rien ne la designe.

    Sert a ce qu'une reponse neutre (ni reussite, ni refus) prenne la couleur de son
    domaine — +play en rose musique, +balance en or economie — au lieu du bleu
    d'information generique pour tout le bot.
    """
    key = str(name or "").strip().casefold().lstrip("+/")
    root = key.split(" ")[0]
    for candidate in (key, root):
        if candidate in COMMAND_FAMILIES:
            return COMMAND_FAMILIES[candidate]
    if root:
        try:
            from utils.access_matrix import module_for_command

            module = module_for_command(root)
        except Exception:
            module = None
        if module and module in MODULE_FAMILIES:
            return MODULE_FAMILIES[module]
    cog = str(cog_name or "").strip().casefold()
    return COG_FAMILIES.get(cog)


def banner_kind(log_type: str, title: str = "", description: str = "") -> str:
    """Le registre événementiel décide ; le texte n'est qu'un repli."""
    from utils.log_categories import resolve
    return resolve(log_type, title, description)[2]


def get_banner(log_type: str, title: str = "", description: str = "") -> Path:
    ensure_banners()
    path = BANNER_DIR / nom_fichier(banner_kind(log_type, title, description))
    if not path.exists():
        ensure_banners(force=True)
    return path


# Une seule régénération au démarrage. Une erreur Pillow ne doit jamais bloquer le boot :
# send_wide_log détecte l'absence de bannière et le trace (SXTRACE 6 BANNER_MISSING).
try:
    ensure_banners(force=True)
except Exception:  # pragma: no cover - dépend de l'environnement de rendu
    logger.exception("Régénération des bannières au démarrage impossible.")

__all__ = [
    "BANNER_DIR", "COLORS", "HEIGHT", "LOGO_PATH", "STYLES", "WIDTH",
    "banner_kind", "build_banner", "ensure_banners", "get_banner", "LOGO_BOX", "NIGHT",
    "family_for_command", "MODULE_FAMILIES", "COG_FAMILIES", "COMMAND_FAMILIES", "TINT",
]
