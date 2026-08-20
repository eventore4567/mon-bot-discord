"""Ajout d'emojis par nom pour ``+addemoji`` / ``+addemogi``.

Quand aucun emoji ou fichier n'est fourni, la commande cherche d'abord un emoji
que le bot connait deja sur Discord, puis le catalogue public Emoji.gg. Un emoji
Discord colle depuis le selecteur (y compris avec Nitro) continue d'etre copie
directement par ``cogs.utility``. La signature originale de la commande est preservee
pour ne jamais exposer ``ctx`` comme argument utilisateur.
"""
from __future__ import annotations

import asyncio
import difflib
import functools
import re
import time
import unicodedata
from typing import Any

import aiohttp
from discord.ext import commands

from utils import embeds

EMOJI_GG_API_URL = "https://emoji.gg/api"
CATALOG_TTL_SECONDS = 15 * 60
LOOKUP_TIMEOUT_SECONDS = 8
FUZZY_MIN_SCORE = 0.80

_catalog_cache: list[dict[str, Any]] = []
_catalog_expires_at = 0.0
_catalog_lock = asyncio.Lock()


def _search_key(value: str) -> str:
    """Compare les noms sans accents, espaces, tirets, underscores ni deux-points."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def _discord_name(value: str, *, fallback: str = "emoji") -> str:
    """Transforme un terme de recherche en nom accepte par Discord."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if len(text) < 2:
        text = re.sub(r"[^A-Za-z0-9_]", "_", fallback)
        text = re.sub(r"_+", "_", text).strip("_") or "emoji"
    return text[:32]


def _catalog_names(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    title = str(item.get("title") or item.get("name") or "").strip()
    slug = str(item.get("slug") or "").strip()
    if title:
        values.append(title)
    if slug:
        values.append(slug)
        values.append(re.sub(r"^\d+[_-]?", "", slug))
    return [value for value in values if value]


async def _emoji_gg_catalog() -> list[dict[str, Any]]:
    global _catalog_cache, _catalog_expires_at
    now_mono = time.monotonic()
    if _catalog_cache and now_mono < _catalog_expires_at:
        return _catalog_cache

    async with _catalog_lock:
        now_mono = time.monotonic()
        if _catalog_cache and now_mono < _catalog_expires_at:
            return _catalog_cache

        timeout = aiohttp.ClientTimeout(total=LOOKUP_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                EMOJI_GG_API_URL,
                headers={"User-Agent": "SentriX-EmojiNameLookup/1.1", "Accept": "application/json"},
            ) as response:
                if response.status != 200:
                    raise ValueError(f"Le catalogue d'emojis est indisponible (HTTP {response.status}).")
                payload = await response.json(content_type=None)

        if not isinstance(payload, list):
            raise ValueError("Le catalogue d'emojis a renvoye une reponse invalide.")

        clean = [item for item in payload if isinstance(item, dict) and item.get("image")]
        if not clean:
            raise ValueError("Le catalogue d'emojis est momentanement vide.")
        _catalog_cache = clean
        _catalog_expires_at = time.monotonic() + CATALOG_TTL_SECONDS
        return _catalog_cache


def _best_catalog_match(items: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    wanted = _search_key(query)
    if len(wanted) < 2:
        return None

    exact: list[dict[str, Any]] = []
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for item in items:
        names = _catalog_names(item)
        keys = [_search_key(name) for name in names if _search_key(name)]
        if wanted in keys:
            exact.append(item)
            continue

        best = 0.0
        for key in keys:
            if not key:
                continue
            ratio = difflib.SequenceMatcher(None, wanted, key).ratio()
            if key.startswith(wanted) or wanted.startswith(key):
                ratio = max(ratio, 0.88)
            elif wanted in key or key in wanted:
                ratio = max(ratio, 0.84)
            best = max(best, ratio)
        if best >= FUZZY_MIN_SCORE:
            try:
                faves = int(item.get("faves") or 0)
            except (TypeError, ValueError):
                faves = 0
            scored.append((best, faves, item))

    if exact:
        def popularity(item: dict[str, Any]) -> int:
            try:
                return int(item.get("faves") or 0)
            except (TypeError, ValueError):
                return 0
        return max(exact, key=popularity)
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return scored[0][2]


def _local_emoji(bot: commands.Bot, query: str):
    wanted = _search_key(query)
    if not wanted:
        return None
    exact = [emoji for emoji in getattr(bot, "emojis", []) if _search_key(emoji.name) == wanted]
    return exact[0] if exact else None


async def _resolve_by_name(bot: commands.Bot, query: str) -> tuple[str, str]:
    local = _local_emoji(bot, query)
    if local is not None:
        # Le pipeline de cogs.utility attend une URL HTTPS. Utiliser l'Asset CDN
        # plutot que str(local), qui donnerait <:nom:id> et serait refuse par le
        # validateur d'URL.
        return str(local.url), local.name

    catalog = await _emoji_gg_catalog()
    match = _best_catalog_match(catalog, query)
    if match is None:
        raise LookupError(query)
    image = str(match.get("image") or "").strip()
    title = str(match.get("title") or match.get("name") or query).strip()
    if not image.startswith("https://"):
        raise ValueError("La source trouvee pour cet emoji n'est pas une URL HTTPS valide.")
    return image, title


def _plain_name_request(ctx: commands.Context, nom: str, source: str | None) -> bool:
    if source and source.strip():
        return False
    if getattr(getattr(ctx, "message", None), "attachments", None):
        return False
    value = (nom or "").strip()
    if not value or value.startswith("<") or value.startswith("http://") or value.startswith("https://"):
        return False
    # Les emojis Unicode et les emojis Discord rendus par Nitro sont geres directement
    # par cogs.utility. Ici on ne prend que du texte comme tete ou :tete:.
    return all(ord(ch) < 0x2300 for ch in value)


def install(bot: commands.Bot) -> bool:
    command = bot.get_command("addemoji")
    if command is None or getattr(command.callback, "_sentrix_name_lookup", False):
        return False

    original = command.callback
    # IMPORTANT : sauvegarder les vrais parametres avant de remplacer callback. Sans
    # cela certaines couches runtime de discord.py voient cog_self/ctx comme arguments
    # utilisateur et +addemogi <emoji> echoue avant meme d'entrer dans la commande.
    original_params = command.params.copy()

    @functools.wraps(original)
    async def wrapped(cog_self, ctx: commands.Context, nom: str, url: str = None):
        if not _plain_name_request(ctx, nom, url):
            # Emoji visuel Discord/Nitro, Unicode, image jointe ou ancienne syntaxe :
            # on laisse le pipeline natif de SentriX le traiter sans transformation.
            return await original(cog_self, ctx, nom, url)

        query = (nom or "").strip().strip(":").strip()
        if not query:
            return await ctx.send(embed=embeds.error(
                "Indiquez un nom d'emoji, par exemple `+addemogi :tete:`, ou envoyez directement un emoji."
            ))

        if ctx.guild is not None:
            wanted = _search_key(query)
            existing = next((emoji for emoji in ctx.guild.emojis if _search_key(emoji.name) == wanted), None)
            if existing is not None:
                return await ctx.send(embed=embeds.warning(
                    f"{existing} existe deja sur ce serveur sous le nom `:{existing.name}:`."
                ))

        try:
            source, matched_title = await _resolve_by_name(bot, query)
        except LookupError:
            return await ctx.send(embed=embeds.error(
                f"Aucun emoji assez proche de **{query}** n'a ete trouve. "
                "Vous pouvez aussi envoyer directement l'emoji Discord/Nitro ou joindre une image."
            ))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return await ctx.send(embed=embeds.error(
                "La recherche automatique d'emojis est momentanement indisponible. "
                "Reessayez dans quelques secondes."
            ))

        final_name = _discord_name(query, fallback=matched_title)
        return await original(cog_self, ctx, final_name, source)

    wrapped._sentrix_name_lookup = True
    command.callback = wrapped
    # Restaurer explicitement la signature de parsing d'origine. functools.wraps aide
    # l'introspection, mais command.params est la source de verite pour le parseur.
    command.params = original_params
    command.description = "Ajouter un emoji en l'envoyant directement ou en donnant son nom."
    command.help = (
        "Exemples : `+addemogi :tete:` ou `+addemogi` suivi d'un emoji Discord/Nitro. "
        "Une image jointe reste aussi acceptee avec un nom."
    )
    return True


class EmojiNameLookup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        install(self.bot)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmojiNameLookup(bot))
    install(bot)
