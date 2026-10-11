"""Animations des jeux SentriX avec anti-cadres vides.

Les anciennes URLs Tenor aboutissaient parfois à une page HTML au lieu d'un GIF,
laissant un grand emplacement cassé dans Discord. Les nouvelles scènes sont des
fichiers GIF GIPHY observés avec MIME image/gif. Le bot vérifie leur signature
au premier usage et conserve le résultat en cache par scène.

Un média indisponible ne bloque JAMAIS le jeu : aucun MediaGallery n'est créé,
mais boutons, scores, mises, récompenses et résultats restent utilisables.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata

import aiohttp
import discord


# Liens d'images GIF (Content-Type: image/gif vérifié sur les liens source GIPHY).
# Utiliser les liens directs du CDN, PAS les pages giphy.com/gifs ou tenor.com/view.
# Les identifiants ci-dessous proviennent de pages officielles GIPHY.
GIFS: dict[str, str] = {
    "win": "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExc2RwMzRpdnlqaWdtNGNiYXJnaWFubW54eDA1cnNoOWFxbTVpeHFwMyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/f8Wil9jWfDhTbnw87P/giphy.gif",
    "loss": "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExcnE5dDE0Nm93eWVucXhoYTlua2xvdTVhN2ppcGptZ3V5YnpxZGlqdSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/U7v0GF9c8GcyA/giphy.gif",
    "fight": "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExNzVuMXB4dHdzbmxkdnQzdGFraHYwNmhlbm5nMTNmdTd2dHk2Nms2cCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/So4Yp61bm4pO1wYo1W/giphy.gif",
    "think": "https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExZjJ1YTdwbDlkMmswZG92aXVuejZtMTQ3MHUwcjBkc3JjdTN5MXlkYSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/5kLcdlFiZbv8l2hf5Y/giphy.gif",
    "coin": "https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExN296bHl5N3R6aW4yMjB0emFkcnRucHVmYmo5MHoyZ3R1c3I0dnMwcyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3oKIP65Q76D5KnUG6Q/giphy.gif",
    "race": "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExaTdhazc1NmN3dnJvY2szeXo1dTlvZmF3Y29naDg4Ym1qNTZ4MGQ3ZCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/xMqYlDtLEIO2nMoF3Z/giphy.gif",
    "arcade": "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExNTk1eDU2MXM5ZXB1ZmRrcW5wYmlwMWpvOWp4ajBvejE1bnY2bXhleiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/YtO5eHWu6hSGArNcxb/giphy.gif",
    "slap": "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExdWZxNW51ajZkNGhqcmdjMzU2NDZmNHhld2w0eWI1Nndka2M5djg5dSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/90cAvw5mBQHa1QNFG9/giphy.gif",
}

logger = logging.getLogger("bot.game-visuals")
# La validité dépend de l'accessibilité du CDN *depuis Railway*.
# Cache succès 1 h, échec 2 min : pas de requête à chaque clic sur les boutons.
_MEDIA_STATE: dict[str, tuple[float, bool]] = {}
_MEDIA_LOCK: asyncio.Lock | None = None
_VALID_SECONDS = 3600
_INVALID_SECONDS = 120


def _lock() -> asyncio.Lock:
    global _MEDIA_LOCK
    if _MEDIA_LOCK is None:
        _MEDIA_LOCK = asyncio.Lock()
    return _MEDIA_LOCK


async def _probe_gif(url: str) -> bool:
    """Vérifie le type et la signature, pas seulement un statut HTTP 200.

    Certaines URLs périmées sont HTTP 200 avec une page HTML : c'est exactement
    ce qui affichait un grand cadre d'image vide dans Discord.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=4, connect=2)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                url, headers={"Range": "bytes=0-15", "Accept": "image/gif"}
            ) as response:
                if response.status not in (200, 206):
                    return False
                content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if content_type != "image/gif":
                    return False
                signature = await response.content.read(6)
                return signature in (b"GIF87a", b"GIF89a")
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return False


async def verified_image_for(
    title: str, description: str | None = None, kind: str = "primary"
) -> str | None:
    """N'ajoute une galerie que si le CDN fournit réellement un GIF."""
    scene = scene_for(title, description, kind)
    url = GIFS.get(scene) if scene else None
    if not url:
        return None
    now = time.monotonic()
    cached = _MEDIA_STATE.get(url)
    if cached is not None and cached[0] > now:
        return url if cached[1] else None
    async with _lock():
        now = time.monotonic()
        cached = _MEDIA_STATE.get(url)
        if cached is not None and cached[0] > now:
            return url if cached[1] else None
        ok = await _probe_gif(url)
        _MEDIA_STATE[url] = (now + (_VALID_SECONDS if ok else _INVALID_SECONDS), ok)
        if not ok:
            logger.warning("Animation %s inaccessible ou non-GIF ; panneau sans image.", scene)
        return url if ok else None


async def decorate_embed_checked(
    embed: discord.Embed, *, title: str, description: str | None = None,
    kind: str = "primary",
) -> discord.Embed:
    """Pour les commandes de jeu : aucun cadre vide si un GIF ne charge pas."""
    url = await verified_image_for(title, description, kind)
    if url:
        embed.set_image(url=url)
    return embed


# Emojis de jeu, visibles même si l'utilisateur a désactivé l'animation Discord.
ICONS = {
    "win": "🏆 ✨",
    "loss": "💥 😢",
    "fight": "⚔️ 🔥",
    "think": "🧠 💡",
    "coin": "🪙 🎲",
    "race": "🏁 ⚡",
    "arcade": "🎮 ⭐",
    "slap": "👏 💥",
}
_NOT_A_GAME = (
    "historique", "statistique", "classement", "profil", "configuration",
    "parametre", "reglage", "tableau", "boutique", "inventaire", "parties jouees",
    "gamesetup", "game setup", "leaderboard", "settings", "stats",
)
_FAILURE = re.compile(r"\b(perdu|perdue|defaite|echec|explos|mort|elimin|rate|defeat|lost|lose|crash)\b")
_VICTORY = re.compile(r"\b(gagn|victoire|remport|reussi|encaisse|bravo|jackpot|victory|winner|win|succ[eè]s)")
_BAD_INPUT = re.compile(
    r"(invalide|impossible|permission|reessaye|reessayez|introuvable|"
    r"desactive|pas assez|cooldown|avant de rejouer|deja en cours|"
    r"aucune partie|doit etre|doivent etre|autorise|erreur)"
)
_FAMILIES = (
    ("slap", ("gifle", "slap")),
    ("coin", ("pile ou face", "coinflip", "roulette", "roulette russe", "blackjack", "casino", "lancer", "dice", "slot", "machine a sous", "highlow")),
    ("race", ("course", "race", "vitesse", "reflex", "reaction", "fasttype", "rapidite")),
    ("think", ("quiz", "trivia", "enigme", "math", "memoire", "memory", "mot", "pendu", "guess", "scramble", "potion", "detective")),
    ("fight", ("duel", "combat", "dragon", "zombie", "arene", "archery", "tir", "bomb", "bombe", "bombes", "lava", "lave", "rocket", "ghost", "fantome")),
)


def _normaliser(value: object) -> str:
    text = str(value or "").casefold()
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", text)


def scene_for(title: str, description: str | None = None, kind: str = "primary") -> str | None:
    """Choisit une scène pertinente sans ajouter d'images aux erreurs/config.

    Aucune fonction aléatoire : la scène d'une partie ne clignote pas quand un
    bouton édite son panneau. Une fin de partie remplace la scène de départ.
    """
    title_normal = _normaliser(title)
    description_normal = _normaliser(description)
    if any(phrase in title_normal for phrase in _NOT_A_GAME):
        return None
    if kind == "warning" or (kind == "danger" and _BAD_INPUT.search(description_normal)):
        return None
    if kind == "success" or _VICTORY.search(description_normal):
        return "win"
    if (kind == "danger" or _FAILURE.search(description_normal)) and (
        kind == "danger" or not _BAD_INPUT.search(description_normal)
    ):
        return "loss"
    if _BAD_INPUT.search(description_normal):
        return None
    for scene, tokens in _FAMILIES:
        if any(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", title_normal) for token in tokens):
            return scene
    return "arcade"


def image_for(title: str, description: str | None = None, kind: str = "primary") -> str | None:
    scene = scene_for(title, description, kind)
    return GIFS.get(scene) if scene else None


def decorate_embed(
    embed: discord.Embed, *, title: str, description: str | None = None,
    kind: str = "primary",
) -> discord.Embed:
    """Place un GIF large, rendu dans panels.depuis_embed / MediaGallery.

    On ne modifie ni la logique de jeu, ni la description (questions, résultats,
    récompenses, références), ni les callbacks des boutons.
    """
    url = image_for(title, description, kind)
    if url:
        embed.set_image(url=url)
    return embed


def result_icon(title: str, description: str | None = None, kind: str = "primary") -> str:
    return ICONS.get(scene_for(title, description, kind) or "", "")


__all__ = ["GIFS", "ICONS", "scene_for", "image_for", "verified_image_for", "decorate_embed", "decorate_embed_checked", "result_icon"]
