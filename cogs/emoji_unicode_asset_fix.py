"""Correctif final pour ``+addemoji <emoji unicode>``.

Le pipeline historique reencode toutes les images statiques avant le premier envoi a
Discord. Pour les glyphes Unicode (ex. 👑), cette etape peut produire un asset que l'API
refuse avec 50046 ``Invalid Asset`` alors que le PNG Twemoji original est parfaitement
valide.

Cette couche ne touche qu'aux requetes Unicode. Elle telecharge un vrai PNG Twemoji,
verifie ses octets, essaie d'abord l'asset original puis une seule variante PNG RGBA
reencodee si Discord refuse le premier fichier. Toutes les autres syntaxes continuent de
passer par le pipeline existant (emoji Discord/Nitro, URL, piece jointe, recherche par nom).
"""
from __future__ import annotations

import asyncio
import functools
import io
import logging
import re
import unicodedata

import aiohttp
import discord
from PIL import Image, UnidentifiedImageError
from discord.ext import commands

logger = logging.getLogger("bot.emoji-unicode-fix")

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_SOURCE_BYTES = 1024 * 1024
MAX_EMOJI_BYTES = 256 * 1024
EMOJI_SIZE = 128
CUSTOM_EMOJI_RE = re.compile(r"<(a?):([A-Za-z0-9_]{2,32}):([0-9]+)>")


def _is_emoji_codepoint(char: str) -> bool:
    value = ord(char)
    return (
        0x1F000 <= value <= 0x1FAFF
        or 0x2600 <= value <= 0x27BF
        or 0x2300 <= value <= 0x23FF
        or 0x1F1E6 <= value <= 0x1F1FF
    )


def _contains_unicode_emoji(value: str | None) -> bool:
    return bool(value) and any(_is_emoji_codepoint(char) for char in value)


def _discord_name(value: str, *, fallback: str = "emoji") -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if len(text) < 2:
        text = fallback
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_") or "emoji"
    if len(text) < 2:
        text = f"emoji_{text}"
    return text[:32]


def _twemoji_codepoints(value: str) -> str:
    # Twemoji n'inclut pas FE0F dans la plupart de ses noms de fichiers. On conserve
    # ZWJ, les tons de peau, les indicateurs de drapeaux et U+20E3 des keycaps.
    return "-".join(f"{ord(char):x}" for char in value if ord(char) != 0xFE0F)


def _unicode_request(nom: str, url: str | None) -> tuple[str, str] | None:
    """Retourne (sequence_unicode, nom_discord) uniquement pour la syntaxe Unicode."""
    raw_name = (nom or "").strip()
    raw_source = (url or "").strip()

    # Ne jamais voler la syntaxe d'un vrai emoji Discord/Nitro.
    if CUSTOM_EMOJI_RE.fullmatch(raw_source or raw_name):
        return None

    if raw_source and _contains_unicode_emoji(raw_source):
        first = next(ord(ch) for ch in raw_source if _is_emoji_codepoint(ch))
        return raw_source, _discord_name(raw_name, fallback=f"emoji_{first:x}")

    if not raw_source and _contains_unicode_emoji(raw_name):
        first = next(ord(ch) for ch in raw_name if _is_emoji_codepoint(ch))
        # Pour +addemoji 👑, le nom doit etre stable et legal sans reutiliser le glyphe.
        return raw_name, f"emoji_{first:x}"[:32]

    return None


def _asset_candidates(sequence: str) -> list[str]:
    codepoints = _twemoji_codepoints(sequence)
    # Une version figee en premier pour eviter qu'un tag ``latest`` change brutalement.
    # Le fork maintenu sert de secours et couvre les emojis plus recents.
    return [
        f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{codepoints}.png",
        f"https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{codepoints}.png",
    ]


async def _download_png(sequence: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=10, connect=4)
    headers = {
        "User-Agent": "SentriX-UnicodeEmoji/2.0",
        "Accept": "image/png,image/*;q=0.8",
    }
    last_status: int | None = None
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for candidate in _asset_candidates(sequence):
            try:
                async with session.get(candidate, allow_redirects=True) as response:
                    last_status = response.status
                    if response.status != 200:
                        continue
                    declared = int(response.headers.get("Content-Length", "0") or 0)
                    if declared > MAX_SOURCE_BYTES:
                        continue
                    data = await response.content.read(MAX_SOURCE_BYTES + 1)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                continue
            if not data or len(data) > MAX_SOURCE_BYTES:
                continue
            if not data.startswith(PNG_SIGNATURE):
                continue
            return data
    suffix = f" (HTTP {last_status})" if last_status is not None else ""
    raise ValueError(f"Impossible de recuperer le PNG de cet emoji{suffix}.")


def _safe_static_png(data: bytes) -> bytes:
    """Produit un PNG RGBA classique, mono-image et <= 256 Ko."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            source.load()
            if source.width <= 0 or source.height <= 0:
                raise ValueError("Dimensions invalides.")
            if source.width * source.height > 16_777_216:
                raise ValueError("Image trop grande.")
            frame = source.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Le PNG Unicode est illisible.") from exc

    frame.thumbnail((EMOJI_SIZE, EMOJI_SIZE), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (EMOJI_SIZE, EMOJI_SIZE), (0, 0, 0, 0))
    canvas.alpha_composite(frame, ((EMOJI_SIZE - frame.width) // 2, (EMOJI_SIZE - frame.height) // 2))

    output = io.BytesIO()
    # Pas de palette, pas d'APNG, pas de metadonnees exotiques : PNG RGBA standard.
    canvas.save(output, format="PNG", optimize=False, compress_level=6)
    encoded = output.getvalue()
    if not encoded.startswith(PNG_SIGNATURE) or len(encoded) > MAX_EMOJI_BYTES:
        raise ValueError("Le PNG final n'est pas compatible avec Discord.")
    return encoded


async def _send_embed(cog_self, ctx: commands.Context, *, title: str, description: str, kind: str):
    return await ctx.send(embed=await cog_self._embed(
        ctx.guild.id if ctx.guild else None,
        title=title,
        description=description,
        kind=kind,
    ))


async def _create_unicode_emoji(cog_self, ctx: commands.Context, sequence: str, emoji_name: str):
    if ctx.guild is None:
        return await _send_embed(
            cog_self, ctx,
            title="Commande indisponible",
            description="Cette commande doit etre utilisee sur un serveur.",
            kind="danger",
        )

    me = ctx.guild.me
    if me is None or not me.guild_permissions.manage_emojis_and_stickers:
        return await _send_embed(
            cog_self, ctx,
            title="Permission manquante",
            description="Le bot doit avoir la permission **Gerer les emojis et stickers**.",
            kind="danger",
        )

    existing = discord.utils.find(
        lambda item: item.name.casefold() == emoji_name.casefold(),
        ctx.guild.emojis,
    )
    if existing is not None:
        return await _send_embed(
            cog_self, ctx,
            title="Emoji deja present",
            description=f"{existing} existe deja sous le nom `:{existing.name}:`.",
            kind="warning",
        )

    if sum(1 for item in ctx.guild.emojis if not item.animated) >= ctx.guild.emoji_limit:
        return await _send_embed(
            cog_self, ctx,
            title="Limite atteinte",
            description="Le serveur n'a plus de place pour un emoji statique.",
            kind="danger",
        )

    try:
        original_png = await _download_png(sequence)
    except ValueError as exc:
        return await _send_embed(
            cog_self, ctx,
            title="Emoji introuvable",
            description=str(exc),
            kind="danger",
        )

    # Important : on essaie le PNG Twemoji officiel AVANT toute conversion. C'est le
    # chemin qui manquait au pipeline historique et qui evite le 50046 observe.
    attempts: list[bytes] = [original_png]
    try:
        repaired = await asyncio.to_thread(_safe_static_png, original_png)
        if repaired != original_png:
            attempts.append(repaired)
    except ValueError:
        pass

    last_error: discord.HTTPException | None = None
    for image in attempts:
        try:
            created = await ctx.guild.create_custom_emoji(
                name=emoji_name,
                image=image,
                reason=f"Emoji Unicode ajoute par {ctx.author} avec +addemoji",
            )
        except discord.Forbidden:
            return await _send_embed(
                cog_self, ctx,
                title="Creation refusee",
                description=(
                    "Discord refuse la creation. Verifiez la permission **Gerer les emojis et stickers** "
                    "et la position du role SentriX."
                ),
                kind="danger",
            )
        except discord.HTTPException as exc:
            last_error = exc
            if exc.code == 50046:
                continue
            return await _send_embed(
                cog_self, ctx,
                title="Creation impossible",
                description=f"Discord a refuse la creation (`{exc.code}`). Reessayez dans quelques secondes.",
                kind="danger",
            )
        else:
            return await _send_embed(
                cog_self, ctx,
                title="Emoji ajoute",
                description=(
                    f"{created} a ete ajoute sous le nom `:{created.name}:`.\n\n"
                    "Source : emoji Unicode converti en PNG compatible Discord."
                ),
                kind="success",
            )

    code = getattr(last_error, "code", 50046)
    return await _send_embed(
        cog_self, ctx,
        title="Image refusee par Discord",
        description=(
            f"Discord refuse encore cet asset (`{code}`) apres les deux formats verifies. "
            "Essayez le meme emoji avec un nom explicite, par exemple `+addemoji couronne 👑`."
        ),
        kind="danger",
    )


def install(bot: commands.Bot) -> bool:
    command = bot.get_command("addemoji")
    if command is None:
        logger.warning("Commande addemoji introuvable : correctif Unicode non installe.")
        return False
    if getattr(command.callback, "_sentrix_unicode_asset_fix_v2", False):
        return True

    original = command.callback
    original_params = command.params.copy()

    @functools.wraps(original)
    async def wrapped(cog_self, ctx: commands.Context, nom: str, url: str = None):
        request = _unicode_request(nom, url)
        if request is None:
            return await original(cog_self, ctx, nom, url)
        sequence, final_name = request
        return await _create_unicode_emoji(cog_self, ctx, sequence, final_name)

    wrapped._sentrix_unicode_asset_fix_v2 = True
    command.callback = wrapped
    command.params = original_params
    logger.info("Correctif +addemoji Unicode V2 installe.")
    return True


class EmojiUnicodeAssetFix(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        install(self.bot)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmojiUnicodeAssetFix(bot))
    install(bot)
