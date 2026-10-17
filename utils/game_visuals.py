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
import hashlib
import io
import logging
import re
import time
import unicodedata

import aiohttp
import discord


# Liens d'images GIF (Content-Type: image/gif vérifié sur les liens source GIPHY).
# Utiliser les liens directs du CDN, PAS les pages giphy.com/gifs ou tenor.com/view.
# Identifiants tirés de pages GIPHY existantes (Pokémon, Cyberpunk,
# iQiyi, Apple TV, animations de jeu). Pas de liens de tracking signés/expirables.
GIFS: dict[str, str] = {
    "win": "https://media.giphy.com/media/f8Wil9jWfDhTbnw87P/giphy.gif",
    "loss": "https://media.giphy.com/media/j8HIpI6nyLkNUwxP3w/giphy.gif",
    "fight": "https://media.giphy.com/media/NY3tXwOBUwQYq7lbXx/giphy.gif",
    "think": "https://media.giphy.com/media/5kLcdlFiZbv8l2hf5Y/giphy.gif",
    "coin": "https://media.giphy.com/media/WFvnujC1Tz6VoyPDka/giphy.gif",
    "race": "https://media.giphy.com/media/xMqYlDtLEIO2nMoF3Z/giphy.gif",
    "arcade": "https://media.giphy.com/media/7AvMktcyuw9TEpKDvF/giphy.gif",
    "slap": "https://media.giphy.com/media/90cAvw5mBQHa1QNFG9/giphy.gif",
    # Vraies scènes de combat : chaque action garde sa propre animation.
    # Les octets sont vérifiés par _fetch_gif_bytes avant tout envoi Discord.
    "boss-attack": "https://media.giphy.com/media/rMWtjgMUUwEnsKR9n2/giphy.gif",
    "boss-power": "https://media.giphy.com/media/j9oeNL144oaZQq2tJO/giphy.gif",
    "boss-guard": "https://media.giphy.com/media/WDRyxPW1BSpHIDH5Cg/giphy.gif",
    "boss-counter": "https://media.giphy.com/media/qJyZZ9B6Za6Yjsp69O/giphy.gif",
    "boss-counter-alt": "https://media.giphy.com/media/CLPSFbwMqpsvf5cRe8/giphy.gif",
    "doors": "https://media.giphy.com/media/rbpgvZ17l67oKfOODU/giphy.gif",
    "emojiorder": "https://media.giphy.com/media/LlIrosc9s0AsGEVXtU/giphy.gif",
}

logger = logging.getLogger("bot.game-visuals")
# La validité dépend de l'accessibilité du CDN *depuis Railway*.
# Cache succès 1 h, échec 2 min : pas de requête à chaque clic sur les boutons.
_MEDIA_STATE: dict[str, tuple[float, bool]] = {}
_MEDIA_BYTES: dict[str, bytes] = {}
MAX_GIF_BYTES = 4 * 1024 * 1024
_ATTACHMENT_PREFIX = "sentrix_game_"
_MEDIA_LOCK: asyncio.Lock | None = None
_VALID_SECONDS = 3600
_INVALID_SECONDS = 120


# Variantes par scène. Jayden, le 2026-10-17 : « quand on attaque ça monte un
# GIF d'attaque, pas le même à chaque fois ». Jusqu'ici une scène = une seule
# image, donc la même animation à chaque coup.
#
# Les variantes ne sont PAS de nouvelles URL inventées : ce sont celles déjà
# déclarées dans GIFS ci-dessus, dont les octets sont vérifiés par
# _fetch_gif_bytes avant tout envoi. Les scènes « boss-* » existaient sans
# jamais être choisies par scene_for ; elles servent enfin.
VARIANTES: dict[str, tuple[str, ...]] = {
    "fight": ("boss-attack", "boss-power", "boss-counter", "boss-counter-alt", "slap"),
    "win": ("boss-power", "arcade"),
    "loss": ("boss-guard", "slap"),
    "arcade": ("doors", "emojiorder"),
    "race": ("arcade",),
    "think": ("doors",),
}


def urls_de_scene(scene: str) -> tuple[str, ...]:
    """Toutes les images utilisables pour une scène, la canonique en tête."""
    canonique = GIFS.get(scene)
    if not canonique:
        return ()
    vues = {canonique}
    urls = [canonique]
    for autre in VARIANTES.get(scene, ()):
        url = GIFS.get(autre)
        if url and url not in vues:
            vues.add(url)
            urls.append(url)
    return tuple(urls)


def url_de_scene(scene: str, graine: object = None) -> str | None:
    """Image d'une scène, variée mais STABLE pour une même graine.

    Le choix doit rester déterministe : un panneau de jeu est réédité à chaque
    clic de bouton, et tirer au hasard ferait clignoter l'animation en plein
    tour. La graine est donc le numéro de tour (ou l'identifiant du message) —
    même tour, même image ; tour suivant, image suivante.
    """
    urls = urls_de_scene(scene)
    if not urls:
        return None
    if graine is None or len(urls) == 1:
        return urls[0]
    if isinstance(graine, int):
        index = graine
    else:
        # Stable d'un processus à l'autre, contrairement à hash() sur une str.
        index = int.from_bytes(hashlib.blake2b(str(graine).encode("utf-8"), digest_size=8).digest(), "big")
    return urls[index % len(urls)]


def _cle_variante(scene: str, url: str) -> str:
    """Identifiant stable d'une variante, utilisable comme nom de fichier."""
    urls = urls_de_scene(scene)
    if not urls or url == urls[0]:
        return scene
    try:
        return f"{scene}-v{urls.index(url) + 1}"
    except ValueError:
        return scene


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


async def _fetch_gif_bytes(url: str) -> bytes | None:
    """Charge le VRAI fichier binaire avec une taille bornée.

    Un simple GET Range ne suffit pas : Discord pourrait recevoir un GIF valide
    au premier octet mais incomplet ou refusé par le CDN sur la requête suivante.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=7, connect=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"Accept": "image/gif"}) as response:
                if response.status != 200:
                    return None
                mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if mime != "image/gif":
                    return None
                content_length = response.content_length
                if content_length is not None and content_length > MAX_GIF_BYTES:
                    return None
                chunks = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_GIF_BYTES:
                        return None
                raw = bytes(chunks)
                # GIF signé ET terminé, pour ne pas envoyer un média tronqué.
                if len(raw) < 14 or raw[:6] not in (b"GIF87a", b"GIF89a"):
                    return None
                if raw[-1:] != b";":
                    return None
                return raw
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return None


def attachment_file_for(image_url: str) -> discord.File | None:
    """Crée un fichier Discord NEUF depuis le cache, pour send ET edit."""
    prefix = "attachment://" + _ATTACHMENT_PREFIX
    if not str(image_url).startswith(prefix) or not str(image_url).endswith(".gif"):
        return None
    scene = str(image_url)[len(prefix):-4]
    data = _MEDIA_BYTES.get(scene)
    if not data:
        return None
    return discord.File(io.BytesIO(data), filename=_ATTACHMENT_PREFIX + scene + ".gif")


async def verified_image_for(
    title: str, description: str | None = None, kind: str = "primary",
    *, scene: str | None = None, graine: object = None,
) -> str | None:
    """Renvoie une référence à une pièce jointe locale, jamais un hotlink.

    Un CDN valide pour Railway peut rester inaccessible au proxy média Discord.
    La seule méthode fiable est l'upload des octets GIF dans le MÊME message
    Components V2. Sans octets locaux, aucune MediaGallery n'est ajoutée.
    """
    # Un combat multi-phases sélectionne EXPLICITEMENT son action.
    # Le moteur général garde sa résolution par titre pour les autres jeux.
    scene = scene if scene in GIFS else scene_for(title, description, kind)
    url = url_de_scene(scene, graine) if scene else None
    if not url:
        return None
    # La clé du cache suit l'IMAGE, pas la scène : deux variantes de « fight »
    # ont des octets différents et ne doivent pas se télescoper, ni dans
    # _MEDIA_BYTES ni dans le nom de la pièce jointe du message.
    scene = _cle_variante(scene, url)
    attachment = f"attachment://{_ATTACHMENT_PREFIX}{scene}.gif"
    cached = _MEDIA_STATE.get(url)
    if cached is not None and cached[0] > time.monotonic():
        return attachment if cached[1] and _MEDIA_BYTES.get(scene) else None
    async with _lock():
        cached = _MEDIA_STATE.get(url)
        if cached is not None and cached[0] > time.monotonic():
            return attachment if cached[1] and _MEDIA_BYTES.get(scene) else None
        data = await _fetch_gif_bytes(url)
        success = bool(data)
        if success:
            _MEDIA_BYTES[scene] = data
        else:
            _MEDIA_BYTES.pop(scene, None)
            logger.warning(
                "GIF %s non téléchargeable (%s) ; jeu servi sans image.",
                scene, url.split("/")[-2] if "/" in url else "source",
            )
        _MEDIA_STATE[url] = (
            time.monotonic() + (_VALID_SECONDS if success else _INVALID_SECONDS),
            success,
        )
        return attachment if success else None


async def preflight_assets() -> dict[str, bool]:
    """Vérifie les huit GIFs dès le chargement du module (en tâche de fond).

    Le diagnostic de disponibilité devient observable dans les logs Railway.
    Une panne du fournisseur ne fait pas échouer le démarrage du bot.
    """
    sample = {
        "win": ("Duel", "Victoire", "success"),
        "loss": ("Duel", "Vous avez perdu.", "danger"),
        "fight": ("Duel", "Début du combat", "primary"),
        "think": ("Quiz", "Choisissez une réponse", "primary"),
        "coin": ("Pile ou face", "Lancez la pièce", "primary"),
        "race": ("Course", "La course commence", "primary"),
        "arcade": ("Puissance 4", "C'est votre tour", "primary"),
        "slap": ("Slap", "Prêt à gifler", "primary"),
    }
    results = {}
    for scene, args in sample.items():
        try:
            results[scene] = bool(await verified_image_for(*args))
        except Exception:
            results[scene] = False
            logger.exception("Vérification GIF %s échouée.", scene)
    logger.info(
        "Animations des jeux : %d/%d GIFs disponibles, scenes=%s.",
        sum(results.values()), len(results),
        ",".join(scene for scene, ok in results.items() if ok) or "aucune",
    )
    return results


async def decorate_embed_checked(
    embed: discord.Embed, *, title: str, description: str | None = None,
    kind: str = "primary", scene: str | None = None, graine: object = None,
) -> discord.Embed:
    """Pour les commandes de jeu : aucun cadre vide si un GIF ne charge pas."""
    url = await verified_image_for(title, description, kind, scene=scene, graine=graine)
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
    ("doors", ("portes mysteres", "porte mystere", "doors")),
    ("emojiorder", ("chaine d'emojis", "emojiorder")),
    ("slap", ("gifle", "slap")),
    ("coin", ("pile ou face", "coinflip", "roulette", "roulette russe", "casino", "lancer", "dice", "slot", "machine a sous", "highlow")),
    ("race", ("course", "race", "vitesse", "reflex", "reaction", "fasttype", "rapidite")),
    ("think", ("quiz", "trivia", "question", "culture generale", "enigme", "math", "memoire", "memory", "mot", "pendu", "guess", "scramble", "potion", "detective")),
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
    # Le blackjack fabrique son propre GIF depuis les vraies cartes distribuées.
    if re.search(r"(?<!\w)blackjack(?!\w)", title_normal):
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


def image_for(
    title: str, description: str | None = None, kind: str = "primary",
    *, graine: object = None,
) -> str | None:
    scene = scene_for(title, description, kind)
    return url_de_scene(scene, graine) if scene else None


def decorate_embed(
    embed: discord.Embed, *, title: str, description: str | None = None,
    kind: str = "primary",
) -> discord.Embed:
    """Place un GIF large, rendu dans panels.depuis_embed / MediaGallery.

    On ne modifie ni la logique de jeu, ni la description (questions, résultats,
    récompenses, références), ni les callbacks des boutons.
    """
    # L'ancienne fonction synchrone ne doit jamais injecter une URL extérieure
    # non vérifiée. Elle exploite seulement les GIFs déjà téléchargés.
    scene = scene_for(title, description, kind)
    if scene in _MEDIA_BYTES:
        embed.set_image(url=f"attachment://{_ATTACHMENT_PREFIX}{scene}.gif")
    return embed


def result_icon(title: str, description: str | None = None, kind: str = "primary") -> str:
    return ICONS.get(scene_for(title, description, kind) or "", "")


__all__ = ["GIFS", "ICONS", "scene_for", "image_for", "verified_image_for", "attachment_file_for", "decorate_embed", "decorate_embed_checked", "preflight_assets", "result_icon"]
