"""Ajout d'emojis par nom pour ``+addemoji`` / ``+addemogi``.

Quand aucun emoji, fichier ou URL n'est fourni, la commande cherche d'abord un emoji
que le bot connait deja sur Discord, puis le catalogue public Emoji.gg. Les anciennes
syntaxes restent entierement compatibles et la creation finale continue de passer par
le pipeline securise de ``cogs.utility`` (validation HTTPS, limites, conversion, etc.).
"""
from __future__ import annotations

import asyncio
import difflib
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
    """Compare les noms sans accents, espaces, tirets ni underscores."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]", "", text)


def _discord_name(value: str, *, fallback: str = "emoji") -> str:
    """Transforme un terme de recherche en nom accepte par Discord.

    Exemple : ``ban-1`` devient ``ban_1``. Discord n'autorise pas le tiret dans le
    nom final d'un emoji personnalise, mais l'utilisateur peut bien le taper dans la
    commande de recherche.
    """
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
        # Le legacy API renvoie souvent "4384_nom" : le numero ne fait pas partie
        # du nom que l'utilisateur connait.
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
                headers={"User-Agent": "SentriX-EmojiNameLookup/1.0", "Accept": "application/json"},
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
    if exact:
        return exact[0]
    return None


async def _resolve_by_name(bot: commands.Bot, query: str) -> tuple[str, str]:
    local = _local_emoji(bot, query)
    if local is not None:
        return str(local), local.name

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
    # Les emojis Unicode continuent d'etre geres par cogs.utility.
    return all(ord(ch) < 0x2300 for ch in value)


def install(bot: commands.Bot) -> bool:
    command = bot.get_command("addemoji")
    if command is None or getattr(command.callback, "_sentrix_name_lookup", False):
        return False

    original = command.callback

    async def wrapped(cog_self, ctx: commands.Context, nom: str, url: str = None):
        if not _plain_name_request(ctx, nom, url):
            return await original(cog_self, ctx, nom, url)

        query = nom.strip()
        # Si l'emoji est deja present dans CE serveur, evite de creer un doublon.
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
                "Essayez un nom un peu plus precis, ou joignez une image si c'est un emoji prive."
            ))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return await ctx.send(embed=embeds.error(
                "La recherche automatique d'emojis est momentanement indisponible. "
                "Reessayez dans quelques secondes."
            ))

        final_name = _discord_name(query, fallback=matched_title)
        return await original(cog_self, ctx, final_name, source)

    wrapped._sentrix_name_lookup = True
    wrapped.__name__ = getattr(original, "__name__", "addemoji")
    wrapped.__doc__ = getattr(original, "__doc__", None)
    command.callback = wrapped
    command.description = "Ajouter un emoji en donnant simplement son nom, ex. +addemogi ban-1."
    command.help = (
        "Donnez seulement le nom recherche : `+addemogi ban-1`. "
        "Le bot cherche automatiquement l'image. Les anciennes syntaxes avec emoji, fichier ou URL restent valides."
    )
    return True


class EmojiNameLookup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        install(self.bot)


async def setup(bot: commands.Bot) -> None:
    # Le cog sert aussi de marqueur visible dans +health/extensions.
    await bot.add_cog(EmojiNameLookup(bot))
    install(bot)
