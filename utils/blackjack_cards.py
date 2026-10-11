"""Tables de blackjack SentriX : de vraies cartes, animées localement.

Pas de GIF externe : les images correspondent toujours à la main distribuée,
sans aléas de catalogue ni URL expirée. Le jeu fonctionne sans accès réseau.
"""
from __future__ import annotations

import io
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 900, 490
CARD_W, CARD_H = 92, 124
RED_SUITS = {"♥", "♦"}
PHASES = frozenset({"deal", "hit", "stand", "blackjack", "win", "loss", "draw", "bust", "timeout"})


@lru_cache(maxsize=8)
def _font(size: int, bold: bool = False):
    choices = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    )
    for name in choices:
        try:
            return ImageFont.truetype(name, size=size)
        except (OSError, ValueError):
            pass
    return ImageFont.load_default()


def _rounded(draw: ImageDraw.ImageDraw, xy, fill, *, radius=15, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _card(draw: ImageDraw.ImageDraw, x: int, y: int, code: str | None) -> None:
    box = (x, y, x + CARD_W, y + CARD_H)
    _rounded(draw, (x + 3, y + 5, x + CARD_W + 3, y + CARD_H + 5),
             (3, 30, 25), radius=11)
    if code is None:
        _rounded(draw, box, (28, 49, 96), radius=11, outline=(200, 220, 242), width=3)
        _rounded(draw, (x + 9, y + 9, x + CARD_W - 9, y + CARD_H - 9),
                 (38, 70, 135), radius=5, outline=(154, 188, 232), width=2)
        for delta in (0, 20, 40):
            draw.line((x + 18 + delta, y + 22, x + 18 + delta, y + CARD_H - 22),
                      fill=(90, 131, 188), width=2)
        draw.text((x + CARD_W // 2, y + CARD_H // 2), "S",
                  font=_font(44, True), fill=(239, 246, 255), anchor="mm")
        return

    rank, suit = code[:-1], code[-1]
    ink = (195, 49, 61) if suit in RED_SUITS else (28, 34, 49)
    _rounded(draw, box, (253, 252, 249), radius=11, outline=(218, 224, 224), width=2)
    draw.text((x + 9, y + 5), rank, font=_font(23, True), fill=ink)
    draw.text((x + 11, y + 32), suit, font=_font(21), fill=ink)
    draw.text((x + CARD_W // 2, y + CARD_H // 2 + 10), suit,
              font=_font(52), fill=ink, anchor="mm")
    draw.text((x + CARD_W - 9, y + CARD_H - 7), rank,
              font=_font(18, True), fill=ink, anchor="rd")


def _score(cards: list[tuple[str, int]]) -> int:
    total = sum(value for _, value in cards)
    aces = sum(code.startswith("A") for code, _ in cards)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _hand(draw: ImageDraw.ImageDraw, cards: list[tuple[str, int]], *, y: int,
          hidden: bool, progress: float, moving: bool = False) -> None:
    if not cards:
        return
    gap = min(101, max(44, (WIDTH - 130 - CARD_W) // max(1, len(cards) - 1)))
    origin = (WIDTH - ((len(cards) - 1) * gap + CARD_W)) // 2
    for index, (code, _value) in enumerate(cards):
        reveal = not hidden or index == 0
        shift = int((1 - progress) * 135) if moving and index == len(cards) - 1 else 0
        _card(draw, origin + gap * index + shift, y,
              code if reveal else None)


def _frame(player: list[tuple[str, int]], dealer: list[tuple[str, int]],
           *, hidden: bool, phase: str, progress: float, frame_index: int) -> Image.Image:
    picture = Image.new("RGB", (WIDTH, HEIGHT), (10, 62, 49))
    d = ImageDraw.Draw(picture)
    # Tapis de jeu : fond profond, bordure dorée, sans image publicitaire.
    _rounded(d, (12, 12, WIDTH - 13, HEIGHT - 13), (10, 67, 53),
             radius=25, outline=(132, 113, 66), width=4)
    d.arc((67, 72, WIDTH - 67, HEIGHT + 160), 186, 354, fill=(26, 104, 77), width=4)
    d.text((WIDTH // 2, 24), "SENTRIX  •  BLACKJACK",
           font=_font(25, True), fill=(240, 213, 140), anchor="mt")

    dealer_score = "?" if hidden else str(_score(dealer))
    player_score = str(_score(player))
    d.text((48, 88), "CROUPIER", font=_font(20, True), fill=(233, 243, 235))
    d.text((WIDTH - 47, 88), dealer_score, font=_font(24, True),
           fill=(241, 211, 132), anchor="ra")
    dealer_moving = phase == "stand" and not hidden
    _hand(d, dealer, y=117, hidden=hidden, progress=progress, moving=dealer_moving)
    d.line((60, 270, WIDTH - 60, 270), fill=(70, 127, 99), width=2)
    d.text((48, 284), "VOTRE MAIN", font=_font(20, True), fill=(233, 243, 235))
    d.text((WIDTH - 47, 284), player_score, font=_font(24, True),
           fill=(241, 211, 132), anchor="ra")
    _hand(d, player, y=315, hidden=False, progress=progress,
          moving=phase in {"hit", "deal"})
    labels = {
        "deal": "À VOUS DE JOUER", "hit": "NOUVELLE CARTE",
        "stand": "LE CROUPIER REVELE SON JEU", "blackjack": "BLACKJACK !",
        "win": "VICTOIRE !", "loss": "DEFAITE", "draw": "EGALITE",
        "bust": "VOUS DEPASSEZ 21", "timeout": "TEMPS ECOULE",
    }
    is_win = phase in {"blackjack", "win"}
    is_loss = phase in {"loss", "bust", "timeout"}
    badge = (29, 127, 83) if is_win else (146, 51, 56) if is_loss else (22, 86, 75)
    # La lumière bouge même sur les résultats sans carte distribuée.
    pulse = (frame_index % 4) * 6
    badge = tuple(min(255, channel + pulse) for channel in badge)
    _rounded(d, (260, 446, 640, 482), badge, radius=12)
    d.rectangle((264 + 26 * frame_index, 451, 282 + 26 * frame_index, 454),
                fill=(192, 212, 179))
    d.text((450, 464), labels.get(phase, "BLACKJACK"),
           font=_font(19, True), fill=(255, 255, 255), anchor="mm")
    if is_win:
        for n in range(10):
            x = 84 + (n * 83 + frame_index * 13) % 720
            y = 42 + (n * 41 + frame_index * 9) % 365
            d.ellipse((x, y, x + 7, y + 7), fill=(242, 209, 102))
    return picture


def render_table_gif(player: list[tuple[str, int]], dealer: list[tuple[str, int]],
                     *, hidden: bool = True, phase: str = "deal") -> bytes:
    """Produit un GIF animé authentique des cartes, compatible MediaGallery Discord.

    Aucun état de jeu n'est modifié. On génère des images séparées pour éviter
    qu'une main simultanée remplace celle d'un autre joueur dans un cache global.
    """
    if phase not in PHASES:
        raise ValueError(f"Animation blackjack inconnue : {phase}")
    if not player or not dealer:
        raise ValueError("La table doit contenir les deux mains.")
    frames = [
        _frame(player, dealer, hidden=hidden, phase=phase,
               progress=(i + 1) / 7, frame_index=i)
        for i in range(7)
    ]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:],
                   duration=[90] * (len(frames) - 1) + [900],
                   loop=0, optimize=True, disposal=2)
    return buffer.getvalue()
