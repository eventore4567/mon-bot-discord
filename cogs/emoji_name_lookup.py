"""Ajout d'emojis simple pour ``+addemoji`` / ``+addemogi``.

Modes pris en charge :
- emoji Discord/Nitro colle directement dans la commande ;
- nom simple, avec ou sans ``:`` autour, recherche automatiquement ;
- image jointe + nom, geree par le pipeline historique de ``cogs.utility``.

La copie d'un emoji Discord/Nitro contourne volontairement Pillow : l'asset existe deja
au bon format sur le CDN Discord, donc le redecoder ne sert a rien et peut echouer selon
les codecs installes sur l'hebergeur. Les GIF qui doivent quand meme etre recompresses
passent par un encodeur qui conserve les images completes et la transparence : cela evite
les petits fragments colores qui pouvaient remplacer certains emojis apres l'import.
"""
from __future__ import annotations

import asyncio
import difflib
import functools
import io
import re
import time
import unicodedata
from typing import Any

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, UnidentifiedImageError

from utils import embeds
from utils import sentrix_panels as panels

EMOJI_GG_API_URL = "https://emoji.gg/api"
CATALOG_TTL_SECONDS = 15 * 60
LOOKUP_TIMEOUT_SECONDS = 8
FUZZY_MIN_SCORE = 0.80
MAX_DIRECT_EMOJI_BYTES = 2 * 1024 * 1024
MAX_NORMALIZED_EMOJI_BYTES = 256 * 1024
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
                headers={"User-Agent": "SentriX-EmojiNameLookup/1.3", "Accept": "application/json"},
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


def _emoji_canvas(frame: Image.Image, size: int) -> Image.Image:
    """Place une frame complete au centre sans recadrer les deltas d'un GIF optimise."""
    rgba = frame.convert("RGBA")
    rgba.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        rgba,
        ((size - rgba.width) // 2, (size - rgba.height) // 2),
    )
    return canvas


def _gif_palette_frame(frame: Image.Image, colors: int) -> Image.Image:
    """Reserve un index GIF a la transparence au lieu de la transformer en noir."""
    alpha = frame.getchannel("A")
    indexed = frame.convert("RGB").quantize(
        colors=max(2, min(255, int(colors) - 1)),
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    transparent_mask = alpha.point(lambda value: 255 if value <= 24 else 0)
    indexed.paste(255, mask=transparent_mask)

    palette = list(indexed.getpalette() or [])
    if len(palette) < 768:
        palette.extend([0] * (768 - len(palette)))
    palette[765:768] = [0, 0, 0]
    indexed.putpalette(palette[:768])
    indexed.info["transparency"] = 255
    indexed.info["disposal"] = 2
    return indexed


def _encode_animated_emoji_safe(data: bytes) -> bytes:
    """Reencode une animation sans perdre transparence ni frames partielles.

    Pillow sait reconstruire l'etat visuel complet d'un GIF lorsque les frames sont
    parcourues avec ``seek`` dans l'ordre. On convertit cet etat complet en RGBA avant
    de redimensionner ; ainsi les GIF optimises en petits rectangles/deltas ne deviennent
    plus de minuscules morceaux colores une fois envoyes a Discord.
    """
    strategies = [
        (128, 256, 1),
        (112, 192, 1),
        (96, 128, 1),
        (80, 96, 2),
        (64, 64, 2),
        (56, 48, 3),
    ]
    last_size = 0

    for size, colors, frame_step in strategies:
        try:
            with Image.open(io.BytesIO(data)) as source:
                frame_count = int(getattr(source, "n_frames", 1) or 1)
                if frame_count <= 1:
                    raise ValueError("L'animation ne contient pas plusieurs images.")
                if frame_count > 400:
                    raise ValueError("L'animation contient trop d'images pour un emoji Discord.")
                if source.width * source.height > 16_777_216:
                    raise ValueError("L'animation source est trop grande pour etre traitee.")

                default_duration = max(20, int(source.info.get("duration", 100) or 100))
                loop = int(source.info.get("loop", 0) or 0)
                frames: list[Image.Image] = []
                durations: list[int] = []

                # seek() sequentiel laisse Pillow composer les rectangles delta du GIF
                # sur le canvas logique. Chaque frame sauvegardee ci-dessous est donc une
                # vraie image complete, meme si le fichier source n'en stocke qu'un morceau.
                for index in range(frame_count):
                    source.seek(index)
                    duration = max(
                        20,
                        min(1000, int(source.info.get("duration", default_duration) or default_duration)),
                    )
                    if index % frame_step == 0:
                        complete = source.convert("RGBA").copy()
                        frames.append(_gif_palette_frame(_emoji_canvas(complete, size), colors))
                        durations.append(duration)
                    elif durations:
                        durations[-1] = min(65_535, durations[-1] + duration)
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Impossible de decoder cette animation.") from exc

        if len(frames) <= 1:
            raise ValueError("L'animation ne contient pas assez d'images pour rester animee.")

        output = io.BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=loop,
            disposal=2,
            transparency=255,
            optimize=True,
        )
        encoded = output.getvalue()
        last_size = len(encoded)
        if last_size <= MAX_NORMALIZED_EMOJI_BYTES:
            return encoded

    raise ValueError(
        f"Le GIF reste trop lourd apres optimisation ({last_size // 1024} Ko). "
        "Utilisez une animation plus courte."
    )


def _install_animation_repair() -> bool:
    """Remplace uniquement le reencodeur GIF du pipeline +addemoji existant."""
    from . import utility as utility_module

    current = getattr(utility_module, "_encode_animated_emoji", None)
    if getattr(current, "_sentrix_fragment_safe", False):
        return False

    _encode_animated_emoji_safe._sentrix_fragment_safe = True
    utility_module._encode_animated_emoji = _encode_animated_emoji_safe
    return True


async def _copy_custom_emoji_direct(
    cog_self,
    ctx: commands.Context,
    markup: str,
    *,
    target_name: str | None = None,
):
    """Copie un emoji Discord/Nitro sans le faire passer par Pillow."""
    match = CUSTOM_EMOJI_RE.fullmatch((markup or "").strip())
    if match is None:
        return None

    if ctx.guild is None:
        return await panels.envoyer(ctx, panels.depuis_embed(await cog_self._embed(None, title='Commande indisponible', description='Cette commande doit etre utilisee sur un serveur.', kind='danger')))

    if not ctx.guild.me or not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
        return await panels.envoyer(ctx, panels.depuis_embed(await cog_self._embed(ctx.guild.id, title='Permission manquante', description='Le bot doit avoir la permission **Gerer les emojis et stickers**.', kind='danger')))

    animated = bool(match.group(1))
    source_name = match.group(2)
    emoji_name = _discord_name(target_name or source_name, fallback=source_name)
    emoji_id = match.group(3)

    existing = discord.utils.find(lambda item: item.name.casefold() == emoji_name.casefold(), ctx.guild.emojis)
    if existing is not None:
        return await panels.envoyer(ctx, panels.depuis_embed(await cog_self._embed(ctx.guild.id, title='Emoji deja present', description=f'{existing} existe deja sous le nom `:{existing.name}:`.', kind='warning')))

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
                        "User-Agent": "SentriX-NitroEmojiCopy/1.1",
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
        return await panels.envoyer(ctx, panels.depuis_embed(await cog_self._embed(ctx.guild.id, title='Emoji inaccessible', description=f"SentriX n'a pas pu recuperer cet emoji depuis Discord{detail}.", kind='danger')))

    try:
        created = await ctx.guild.create_custom_emoji(
            name=emoji_name,
            image=data,
            reason=f"Emoji Nitro copie par {ctx.author} avec +addemogi",
        )
    except discord.Forbidden:
        return await panels.envoyer(ctx, panels.depuis_embed(await cog_self._embed(ctx.guild.id, title='Creation refusee', description='Discord refuse la creation. Verifiez la permission **Gerer les emojis et stickers** et la position du role du bot.', kind='danger')))
    except discord.HTTPException as exc:
        return await panels.envoyer(ctx, panels.depuis_embed(await cog_self._embed(ctx.guild.id, title='Creation impossible', description=f'Discord a refuse cet emoji : {exc}', kind='danger')))

    return await panels.envoyer(ctx, panels.depuis_embed(await cog_self._embed(ctx.guild.id, title='Emoji ajoute', description=f"{created} a ete copie directement sous le nom `:{created.name}:`.\nType : **{('anime' if created.animated else 'statique')}**.", kind='success')))


def install(bot: commands.Bot) -> bool:
    # Le correctif d'encodage doit etre actif meme si le wrapper de nom a deja ete
    # installe par un autre passage du chargeur runtime.
    _install_animation_repair()

    command = bot.get_command("addemoji")
    if command is None or getattr(command.callback, "_sentrix_name_lookup", False):
        return False

    original = command.callback
    original_params = command.params.copy()

    @functools.wraps(original)
    async def wrapped(cog_self, ctx: commands.Context, nom: str, url: str = None):
        # Un emoji Discord/Nitro ne doit jamais etre reencode : on copie ses octets CDN
        # directement. Cela couvre maintenant les DEUX syntaxes :
        #   +addemogi <a:danse:id>
        #   +addemogi nouveau <a:danse:id>
        direct_markup = (url or nom or "").strip()
        if CUSTOM_EMOJI_RE.fullmatch(direct_markup) is not None:
            target_name = nom if url else None
            return await _copy_custom_emoji_direct(
                cog_self,
                ctx,
                direct_markup,
                target_name=target_name,
            )

        if not _plain_name_request(ctx, nom, url):
            # Unicode, image jointe ou ancienne syntaxe : pipeline historique.
            return await original(cog_self, ctx, nom, url)

        query = (nom or "").strip().strip(":").strip()
        if not query:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Indiquez un nom d'emoji, par exemple `+addemogi :tete:`, ou envoyez directement un emoji.")))

        if ctx.guild is not None:
            wanted = _search_key(query)
            existing = next((emoji for emoji in ctx.guild.emojis if _search_key(emoji.name) == wanted), None)
            if existing is not None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'{existing} existe deja sur ce serveur sous le nom `:{existing.name}:`.')))

        try:
            source, matched_title = await _resolve_by_name(bot, query)
        except LookupError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Aucun emoji assez proche de **{query}** n'a ete trouve. Vous pouvez aussi envoyer directement l'emoji Discord/Nitro ou joindre une image.")))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("La recherche automatique d'emojis est momentanement indisponible. Reessayez dans quelques secondes.")))

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
