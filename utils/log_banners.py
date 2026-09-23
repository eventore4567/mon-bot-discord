"""Génération des bannières SentriX — fond 100 % transparent.

Un seul dessin, partout : un trait lumineux part de chaque bord, s'arrête juste
avant le logo SentriX centré, et **rien d'autre**. Aucun fond n'est peint : les
pixels hors du trait, du logo et de leur léger halo ont un alpha de 0, donc le
panneau Discord se voit directement derrière — on ne devine pas un rectangle.

La couleur ne touche QUE le trait, le logo et leur halo. Elle vient du contexte
(``utils.log_categories.resolve`` pour les logs, la commande en cours pour les
panneaux), jamais devinée depuis un titre : « unban » contient « ban », un
débannissement sortait en rouge.

Le trait est plus intense près du logo et s'éteint doucement vers les bords.

Le logo est facultatif : s'il est absent, la bannière se génère sans lever.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image, ImageFilter

import config as _config

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
# Bandeau fin : juste la place du logo et de son halo. Un bandeau haut ajoutait
# du vide au-dessus et au-dessous du trait, visible même en transparent.
HEIGHT = 64

# Côté du logo centré : il reste petit, le trait occupe la largeur.
LOGO_BOX = 42
# Le trait part à MARGE du bord et s'arrête à ÉCART du logo.
MARGE = 14
ECART = 12

# Familles de bannières. La couleur ne s'applique qu'au trait, au logo et à leur
# halo — jamais à un fond. Une famille par état et par domaine ; une par commande
# ne serait plus reconnaissable.
def _rgb(valeur: int) -> tuple[int, int, int]:
    return ((valeur >> 16) & 0xFF, (valeur >> 8) & 0xFF, valeur & 0xFF)


# Couleurs des états : celles de config.py, la palette déjà utilisée par les embeds
# et le liseré des conteneurs. Une bannière rouge et un liseré rouge doivent être le
# MÊME rouge.
COLORS: dict[str, tuple[int, int, int]] = {
    # États
    "success": _rgb(_config.COLOR_SUCCESS),   # vert vif
    "error": _rgb(_config.COLOR_ERROR),       # rouge
    "warning": _rgb(_config.COLOR_WARNING),   # ambre
    "info": _rgb(_config.COLOR_INFO),         # bleu clair
    "special": _rgb(_config.COLOR_BRAND),     # violet de marque
    # Domaines
    "moderation": (255, 107, 107),  # rouge corail
    "security": (34, 211, 238),     # cyan électrique
    "tickets": (45, 212, 191),      # turquoise
    "economy": (245, 197, 66),      # jaune doré
    "levels": (163, 230, 53),       # vert citron
    "music": (255, 95, 200),        # rose magenta
    "games": (255, 138, 61),        # orange
    "ai": (168, 85, 247),           # violet
    "config": (192, 132, 252),      # violet clair
    "welcome": (52, 211, 153),      # vert turquoise
    "goodbye": (255, 106, 61),      # orange rouge
}

STYLES = tuple(COLORS)

# WebP : la bannière part en pièce jointe à CHAQUE message. En sans-perte, le
# dessin (un trait, un logo, beaucoup de transparence) pèse moins de 10 Ko et la
# couche alpha reste exacte — un WebP avec perte salit les bords du halo.
EXTENSION = "webp"
_QUALITE_WEBP = 88


def nom_fichier(style: str) -> str:
    """Nom du fichier de banniere pour une famille."""
    return f"banner_{style}.{EXTENSION}"
_READY = False


def _mix(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _glow_lines(accent: tuple[int, int, int]) -> Image.Image:
    """Les deux traits, sur un fond entièrement transparent.

    Un cœur net d'un pixel porte le dessin, un bloom flouté porte la lumière. Le
    trait est le plus intense près du logo et s'éteint avant le bord : coupé net,
    il redessinerait le rectangle de l'image.
    """
    milieu_y = HEIGHT // 2
    interieur = (WIDTH // 2 - LOGO_BOX // 2 - ECART, WIDTH // 2 + LOGO_BOX // 2 + ECART)
    exterieur = (MARGE, WIDTH - MARGE)

    coeur = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    pix_coeur, pix_halo = coeur.load(), halo.load()

    for x in range(WIDTH):
        if exterieur[0] <= x <= interieur[0]:
            t = (x - exterieur[0]) / max(1, interieur[0] - exterieur[0])
        elif interieur[1] <= x <= exterieur[1]:
            t = (exterieur[1] - x) / max(1, exterieur[1] - interieur[1])
        else:
            continue
        t = t * t * (3.0 - 2.0 * t)  # smoothstep : aucune coupure franche
        blanc = round(110 * t * t)   # le cœur vire au blanc là où il est le plus fort
        pix_coeur[x, milieu_y] = (
            min(255, accent[0] + blanc), min(255, accent[1] + blanc),
            min(255, accent[2] + blanc), round(255 * t),
        )
        pix_coeur[x, milieu_y - 1] = (*accent, round(110 * t))
        pix_coeur[x, milieu_y + 1] = (*accent, round(80 * t))
        for decalage in (-2, -1, 0, 1, 2):
            pix_halo[x, milieu_y + decalage] = (*accent, round(190 * t))

    halo = halo.filter(ImageFilter.GaussianBlur(3.5))
    return Image.alpha_composite(halo, coeur)


def _tinted_logo(logo: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    """Logo re-teinté à la couleur de la famille, ses reliefs conservés.

    Le logo du dépôt est bleu : tel quel, il jurait sur un trait rouge ou or. On
    garde sa luminance — donc son relief — et on la projette sur la couleur du
    trait, pour que les deux parlent de la même chose.
    """
    alpha = logo.getchannel("A")
    luminance = logo.convert("L")
    teinte = Image.new("RGBA", logo.size)
    source = luminance.load()
    cible = teinte.load()
    for y in range(logo.height):
        for x in range(logo.width):
            niveau = source[x, y] / 255.0
            ombre = 0.45 + niveau * 0.55
            cible[x, y] = (
                min(255, round(accent[0] * ombre + 255 * niveau * niveau * 0.55)),
                min(255, round(accent[1] * ombre + 255 * niveau * niveau * 0.55)),
                min(255, round(accent[2] * ombre + 255 * niveau * niveau * 0.55)),
                255,
            )
    teinte.putalpha(alpha)
    return teinte


def _composite_logo(image: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    """Logo centré, teinté, avec un halo LÉGER. Absence du fichier = image inchangée."""
    if not LOGO_PATH.exists():
        return image
    try:
        with Image.open(LOGO_PATH) as ouvert:
            logo = ouvert.convert("RGBA")
    except (OSError, ValueError):
        logger.warning("Logo illisible (%s) : bannière générée sans logo.", LOGO_PATH)
        return image

    echelle = min(LOGO_BOX / max(1, logo.width), LOGO_BOX / max(1, logo.height))
    taille = (max(1, round(logo.width * echelle)), max(1, round(logo.height * echelle)))
    if taille != logo.size:
        logo = logo.resize(taille, Image.Resampling.LANCZOS)
    logo = _tinted_logo(logo, accent)

    # Centrage exact : l'arrondi va au pixel près, sinon le logo est décalé d'un
    # pixel vers la gauche ou le haut et le trait ne le traverse plus au milieu.
    x = round((WIDTH - logo.width) / 2)
    y = round((HEIGHT - logo.height) / 2)
    masque = Image.new("L", (WIDTH, HEIGHT), 0)
    masque.paste(logo.getchannel("A"), (x, y))
    masque = masque.filter(ImageFilter.GaussianBlur(5))
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (*accent, 0))
    halo.putalpha(masque.point(lambda valeur: min(95, round(valeur * 0.42))))
    image = Image.alpha_composite(image, halo)
    image.alpha_composite(logo, (x, y))
    return image


def build_banner(style: str) -> Image.Image:
    """Bannière complète : fond transparent, deux traits, logo centré."""
    accent = COLORS.get(style, COLORS["info"])
    image = _glow_lines(accent)
    return _composite_logo(image, accent)


# Domaine SentriX -> famille de banniere. Le module vient de utils/access_matrix
# (la source unique qui sait deja a quel module appartient chaque commande) ; les
# racines ci-dessous couvrent ce qui n'est rattache a aucun module.
MODULE_FAMILIES: dict[str, str] = {
    "economy": "economy", "levels": "levels", "ai": "ai", "tickets": "tickets",
    "moderation": "moderation", "security": "security",
    "logs": "info", "welcome": "welcome", "goodbye": "goodbye",
    "roles": "config", "notifications": "config",
}
COG_FAMILIES: dict[str, str] = {
    "music": "music", "minigames": "games", "gameseconomy": "games",
    "economy": "economy", "levels": "levels", "stats": "levels", "ai": "ai",
    "tickets": "tickets", "moderation": "moderation", "automod": "security",
    "security": "security", "securitytools": "security", "verification": "security",
    "configuration": "config", "serverbuilder": "config", "notifications": "config",
    "guildarrival": "welcome", "welcome": "welcome",
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


def ensure_banners(force: bool = False) -> None:
    """Génère une bannière par famille. ``force=True`` régénère le cache disque.

    Les fichiers sont écrits une seule fois au démarrage puis relus depuis le
    disque à chaque envoi : aucune image n'est recalculée par commande.
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
            build_banner(style).save(path, "WEBP", lossless=True, method=6, exact=True)
        except Exception:
            logger.exception("Génération de la bannière %s impossible.", style)
    _purge_anciennes_bannieres()
    _READY = True


def _purge_anciennes_bannieres() -> None:
    """Supprime les bannières d'un ancien style resté sur le disque.

    Le dossier est un volume persistant en production : une famille retirée de
    COLORS (ou une bannière de l'ancien style à fond plein) y resterait sinon
    pour toujours et pourrait encore être servie.
    """
    attendus = {nom_fichier(style) for style in COLORS}
    attendus |= {f"banner_source_{style}.{EXTENSION}" for style in COLORS}
    for chemin in BANNER_DIR.glob("banner_*"):
        if chemin.name in attendus:
            continue
        try:
            chemin.unlink()
            logger.info("Ancienne bannière supprimée : %s", chemin.name)
        except OSError:
            logger.warning("Ancienne bannière impossible à supprimer : %s", chemin.name)


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
    "banner_kind", "build_banner", "ensure_banners", "get_banner", "LOGO_BOX",
    "family_for_command", "MODULE_FAMILIES", "COG_FAMILIES", "COMMAND_FAMILIES",
    "MARGE", "ECART",
]
