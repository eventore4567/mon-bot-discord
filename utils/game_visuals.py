"""Habillage animé des mini-jeux SentriX.

GIFs Tenor directs et vérifiés : pas d'API, token, téléchargement ni upload au
runtime. Le navigateur Discord récupère les animations. Si un CDN est indisponible,
la manche et ses composants restent jouables : aucun enjeu métier n'en dépend.

Ne pas convertir les boutons en GIF : l'animation est une MediaGallery dans le
MÊME panneau Components V2 que la question, le score et les choix.
"""
from __future__ import annotations

import re
import unicodedata

import discord


# URLs de vrais fichiers GIF (et non des pages tenor.com/view/...).
# Certaines scènes sont tirées d'anime : les GIFs restent hébergés par Tenor.
GIFS: dict[str, str] = {
    "win": "https://media1.tenor.com/m/iFO-KQ5WR_kAAAAd/anime-victory.gif",
    "loss": "https://media1.tenor.com/m/96Hp6CanFZ0AAAAd/anime-cry.gif",
    "fight": "https://media1.tenor.com/m/QQrPX0TA3ZsAAAAd/battle-anime.gif",
    "think": "https://media1.tenor.com/m/9Lk0rzRc4C0AAAAd/anime-confused.gif",
    "coin": "https://media1.tenor.com/m/-Ty-f7Ld7skAAAAd/anime-coinflip.gif",
    "race": "https://media1.tenor.com/m/BF9yBwexIbMAAAAd/anime-run.gif",
    "arcade": "https://media1.tenor.com/m/ahGxtmKCTw8AAAAd/anime-gaming.gif",
    "slap": "https://media1.tenor.com/m/F11VMCuXthAAAAAd/anime-slap.gif",
}

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
    ("coin", ("pile ou face", "coinflip", "roulette", "roulette russe", "blackjack", "casino", "de", "dice", "slot", "machine a sous", "highlow")),
    ("race", ("course", "race", "vitesse", "reflex", "reaction", "fasttype", "rapidite")),
    ("think", ("quiz", "trivia", "enigme", "math", "memoire", "memory", "mot", "pendu", "guess", "scramble", "potion", "detective")),
    ("fight", ("duel", "combat", "dragon", "zombie", "arene", "archery", "tir", "bomb", "bombe", "lava", "lave", "rocket", "ghost", "fantome")),
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


__all__ = ["GIFS", "ICONS", "scene_for", "image_for", "decorate_embed", "result_icon"]
