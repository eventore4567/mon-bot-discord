"""Génération des bannières SentriX (1024x110, neuf familles).

Style unique, aligné sur les bannières validées ``banner_source_*`` : fond nuit
quasi noir, **trait lumineux** qui part de chaque bord vers le centre, **logo
SentriX au centre** avec son halo, liseré d'accent à gauche et cadre arrondi
discret. La couleur (rouge, verte, jaune…) vient du ``log_type`` via
``utils.log_categories.resolve`` — jamais devinée depuis le titre : « unban »
contient « ban », un débannissement sortait en rouge.

Composition d'une bannière :
- fond nuit + halo d'accent centré derrière le logo ;
- deux traits lumineux (cœur net + bloom) s'éteignant vers les bords ;
- liseré vertical d'accent sur le bord gauche ;
- cadre arrondi et liseré supérieur très discrets ;
- logo ``assets/sentrix_logo.png`` centré, teinté à la couleur d'accent.

Le logo est facultatif : s'il est absent, la bannière se génère sans lever.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

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

# Le dégradé est calculé à cette largeur puis étiré en LANCZOS jusqu'à WIDTH. Un dégradé
# est lisse par construction : le rendu est identique à l'œil, pour 4x moins de pixels
# calculés en Python pur au démarrage.
_GRADIENT_WIDTH = 256

# Côté du logo centré. 70 px sur 110 : lisible sur mobile sans manger le trait.
LOGO_BOX = 70

# Familles de bannieres. Cinq etats (les quatre premiers plus « special »), puis
# quatre domaines. On s'arrete la volontairement : une famille par domaine reste
# reconnaissable, une par commande ne le serait plus, et chaque variante est une
# image de plus a garder coherente.
COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    # Etats : ce qui vient de se passer.
    "error": ((255, 82, 98), (168, 30, 58)),
    "success": ((62, 231, 134), (18, 132, 86)),
    "warning": ((255, 198, 74), (188, 104, 20)),
    "info": ((88, 168, 255), (44, 86, 214)),
    "special": ((168, 112, 255), (88, 44, 190)),
    # Domaines : de quoi parle la commande, quand l'etat ne dit rien d'utile.
    # Une teinte par domaine, assez ecartees pour se reconnaitre d'un coup d'oeil.
    "moderation": ((244, 104, 124), (132, 30, 58)),  # rouge sourd, distinct de l'erreur
    "security": ((132, 124, 250), (58, 44, 170)),    # indigo, la couleur des protections
    "economy": ((248, 202, 96), (168, 110, 24)),     # or
    "config": ((84, 222, 228), (26, 116, 150)),      # cyan, les reglages
    "levels": ((170, 228, 92), (86, 140, 28)),       # vert tilleul, la progression
    "music": ((255, 108, 188), (162, 34, 122)),      # rose, le lecteur audio
    "tickets": ((58, 214, 198), (18, 118, 122)),     # turquoise, le support
    "games": ((255, 150, 72), (176, 74, 16)),        # orange, les mini-jeux
    "ai": ((214, 124, 255), (120, 46, 190)),         # orchidee, l'assistant
}

# Fond nuit commun, TEINTE a la couleur de la famille : une bannière rouge doit se
# lire rouge d'un coup d'oeil, pas « gris noir ». Le nuit reste dominant pour que le
# texte du panneau posé dessous garde son contraste.
NIGHT = (20, 22, 48)
NIGHT_EDGE = (12, 13, 30)
# Part de la couleur profonde de la famille melangee au fond (0 = nuit neutre).
TINT = 0.34

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


def _mix(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _tinted_night(accent: tuple[int, int, int]) -> tuple[int, int, int]:
    """Nuit teintée qui garde la TEINTE de la famille.

    Mélanger simplement le bleu nuit avec un vert ou un or donnait un fond gris-bleu
    ou brunâtre : le canal bleu du fond restait dominant. On atténue donc le nuit sur
    les canaux que la couleur de la famille n'utilise pas.
    """
    fort = max(accent) or 1
    nuit = [NIGHT[i] * (0.45 + 0.55 * accent[i] / fort) for i in range(3)]
    return tuple(round(nuit[i] * (1.0 - TINT) + accent[i] * TINT) for i in range(3))


def _night_background(accent: tuple[int, int, int]) -> Image.Image:
    """Fond teinté à la famille + halo d'accent centré, calculé en basse résolution."""
    image = Image.new("RGB", (_GRADIENT_WIDTH, HEIGHT))
    pixels = image.load()
    teinte = _tinted_night(accent)
    cx, cy = _GRADIENT_WIDTH * 0.5, HEIGHT * 0.5
    rx, ry = _GRADIENT_WIDTH * 0.42, HEIGHT * 1.15
    last_x = max(1, _GRADIENT_WIDTH - 1)
    last_y = max(1, HEIGHT - 1)

    for y in range(HEIGHT):
        yn = y / last_y
        # Très léger éclaircissement vers le haut : le bandeau ne paraît pas plat.
        vertical = (1.0 - yn) * 0.35
        dy = (y - cy) / ry
        dy2 = dy * dy
        for x in range(_GRADIENT_WIDTH):
            xn = x / last_x
            # Les bords s'assombrissent : le trait lumineux s'y éteint proprement.
            edge = _clamp(abs(xn * 2.0 - 1.0) * 1.35 - 0.35)
            base = [
                _mix(teinte[i], NIGHT_EDGE[i], edge * edge * 0.85) + round(vertical * 6)
                for i in range(3)
            ]
            dx = (x - cx) / rx
            halo = _clamp(1.0 - math.sqrt(dx * dx + dy2)) ** 3
            pixels[x, y] = tuple(
                min(255, round(base[i] + accent[i] * halo * 0.16)) for i in range(3)
            )

    return image.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS).convert("RGBA")


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


def _add_frame(image: Image.Image, accent: tuple[int, int, int]) -> Image.Image:
    """Liseré d'accent à gauche + cadre arrondi et liseré supérieur très discrets."""
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(
        [(1, 1), (WIDTH - 2, HEIGHT - 2)], radius=12, outline=(*accent, 40), width=1
    )
    draw.rectangle([(0, 0), (WIDTH - 1, 0)], fill=(255, 255, 255, 34))
    # Bord gauche : la barre d'accent, comme sur les bannières validées.
    draw.rounded_rectangle([(0, 6), (3, HEIGHT - 7)], radius=2, fill=(*accent, 235))
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rectangle([(0, 6), (5, HEIGHT - 7)], fill=(*accent, 120))
    image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(4)))
    return Image.alpha_composite(image, overlay)


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
    halo_mask = halo_mask.filter(ImageFilter.GaussianBlur(13))
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (*accent, 0))
    halo.putalpha(halo_mask.point(lambda value: min(170, round(value * 0.70))))
    image = Image.alpha_composite(image, halo)
    image.alpha_composite(logo, (x, y))
    return image


def build_banner(style: str) -> Image.Image:
    accent, deep = COLORS.get(style, COLORS["info"])
    image = _night_background(deep)
    image = _add_glow_lines(image, accent)
    image = _add_frame(image, accent)
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
            build_banner(style).save(path, "WEBP", quality=_QUALITE_WEBP, method=6)
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
