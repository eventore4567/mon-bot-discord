"""Ajout d'emojis simple pour ``+addemoji`` / ``+addemogi``.

Modes pris en charge :
- emoji Discord/Nitro colle directement dans la commande ;
- nom simple, avec ou sans ``:`` autour, recherche automatiquement ;
- image jointe + nom, geree par le pipeline historique de ``cogs.utility``.

La copie d'un emoji Discord/Nitro contourne volontairement Pillow : l'asset existe deja
au bon format sur le CDN Discord, donc le redecoder ne sert a rien et peut echouer selon
les codecs installes sur l'hebergeur.
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
import discord
from discord.ext import commands

from utils import embeds

EMOJI_GG_API_URL = "https://emoji.gg/api"
CATALOG_TTL_SECONDS = 15 * 60
LOOKUP_TIMEOUT_SECONDS = 8
FUZZY_MIN_SCORE = 0.80
MAX_DIRECT_EMOJI_BYTES = 2 * 1024 * 1024
CUSTOM_EMOJI_RE = re.compile(r"<(a?):([A-Za-z0-9_]{2,32}):([0-9]+)>")

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
                headers={"User-Agent": "SentriX-EmojiNameLookup/1.2", "Accept": "application/json"},
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
    # Les emojis Unicode restent geres par cogs.utility. Ici on ne prend que du texte
    # comme tete ou :tete:.
    return all(ord(ch) < 0x2300 for ch in value)


async def _copy_custom_emoji_direct(cog_self, ctx: commands.Context, markup: str):
    """Copie un emoji Discord/Nitro sans le faire passer par Pillow."""
    match = CUSTOM_EMOJI_RE.fullmatch((markup or "").strip())
    if match is None:
        return None

    if ctx.guild is None:
        return await ctx.send(embed=await cog_self._embed(
            None,
            title="Commande indisponible",
            description="Cette commande doit etre utilisee sur un serveur.",
            kind="danger",
        ))

    if not ctx.guild.me or not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
        return await ctx.send(embed=await cog_self._embed(
            ctx.guild.id,
            title="Permission manquante",
            description="Le bot doit avoir la permission **Gerer les emojis et stickers**.",
            kind="danger",
        ))

    animated = bool(match.group(1))
    emoji_name = _discord_name(match.group(2), fallback="emoji")
    emoji_id = match.group(3)

    existing = discord.utils.find(lambda item: item.name.casefold() == emoji_name.casefold(), ctx.guild.emojis)
    if existing is not None:
        return await ctx.send(embed=await cog_self._embed(
            ctx.guild.id,
            title="Emoji deja present",
            description=f"{existing} existe deja sous le nom `:{existing.name}:`.",
            kind="warning",
        ))

    extension = "gif" if animated else "png"
    candidates = [
        f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}?size=128&quality=lossless",
        f"https://media.discordapp.net/emojis/{emoji_id}.{extension}?size=128&quality=lossless",
        f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}",
    ]

    data = None
    last_status = None
    timeout = aiohttp.ClientTimeout(total=12)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for candidate in candidates:
                async with session.get(
                    candidate,
                    headers={
                        "User-Agent": "SentriX-NitroEmojiCopy/1.0",
                        "Accept": "image/png,image/gif,image/webp,image/*;q=0.8",
                    },
                ) as response:
                    last_status = response.status
                    if response.status != 200:
                        continue
                    payload = await response.content.read(MAX_DIRECT_EMOJI_BYTES + 1)
                    if not payload or len(payload) > MAX_DIRECT_EMOJI_BYTES:
                        continue
                    data = payload
                    break
    except (aiohttp.ClientError, asyncio.TimeoutError):
        data = None

    if data is None:
        detail = f" (HTTP {last_status})" if last_status else ""
        return await ctx.send(embed=await cog_self._embed(
            ctx.guild.id,
            title="Emoji inaccessible",
            description=f"SentriX n'a pas pu recuperer cet emoji depuis Discord{detail}.",
            kind="danger",
        ))

    try:
        created = await ctx.guild.create_custom_emoji(
            name=emoji_name,
            image=data,
            reason=f"Emoji Nitro copie par {ctx.author} avec +addemogi",
        )
    except discord.Forbidden:
        return await ctx.send(embed=await cog_self._embed(
            ctx.guild.id,
            title="Creation refusee",
            description="Discord refuse la creation. Verifiez la permission **Gerer les emojis et stickers** et la position du role du bot.",
            kind="danger",
        ))
    except discord.HTTPException as exc:
        return await ctx.send(embed=await cog_self._embed(
            ctx.guild.id,
            title="Creation impossible",
            description=f"Discord a refuse cet emoji : {exc}",
            kind="danger",
        ))

    return await ctx.send(embed=await cog_self._embed(
        ctx.guild.id,
        title="Emoji ajoute",
        description=(
            f"{created} a ete copie directement sous le nom `:{created.name}:`.\n"
            f"Type : **{'anime' if created.animated else 'statique'}**."
        ),
        kind="success",
    ))


def install(bot: commands.Bot) -> bool:
    command = bot.get_command("addemoji")
    if command is None or getattr(command.callback, "_sentrix_name_lookup", False):
        return False

    original = command.callback
    original_params = command.params.copy()

    @functools.wraps(original)
    async def wrapped(cog_self, ctx: commands.Context, nom: str, url: str = None):
        # Quand Nitro remplace :nom: par un vrai emoji, Discord envoie <a?:nom:id>.
        # On le copie directement depuis son CDN : aucun decodage Pillow.
        if not url:
            direct_match = CUSTOM_EMOJI_RE.fullmatch((nom or "").strip())
            if direct_match is not None:
                return await _copy_custom_emoji_direct(cog_self, ctx, nom)

        if not _plain_name_request(ctx, nom, url):
            # Unicode, image jointe ou ancienne syntaxe : pipeline historique.
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
    command.params = original_params
    command.usage = ":nom:"
    command.description = "Ajouter un emoji en l'envoyant directement, par son nom ou avec une image jointe."
    command.help = (
        "Exemples : `+addemogi :tete:` ou `+addemogi` suivi d'un emoji Discord/Nitro. "
        "Pour une image : joignez PNG/JPG/WebP/GIF et tapez `+addemogi nom`."
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
