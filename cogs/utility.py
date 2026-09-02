"""
Cog UTILITAIRES.
/help /ping /avatar /serverinfo /userinfo /roleinfo /channelinfo
/membercount /addemoji /deleteemoji /emoji-list /poll /remind /reminder-list /reminder-cancel
/say /embed-create /translate /weather /suggest /report-bug
/afk /roll /choose
"""

import asyncio
import io
import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import aiohttp
import discord
from PIL import Image, ImageSequence, UnidentifiedImageError
from discord import app_commands
from discord.ext import commands

from utils import access_matrix, embeds, helpers, checks, design_system
from database.db import now

logger = logging.getLogger("bot")

CUSTOM_EMOJI_RE = re.compile(r"<(a?):([A-Za-z0-9_]{2,32}):([0-9]+)>")
MAX_EMOJI_BYTES = 256 * 1024
MAX_EMOJI_SOURCE_BYTES = 8 * 1024 * 1024
EMOJI_DIMENSION = 128


def _contains_unicode_emoji(value: str) -> bool:
    return any(
        0x1F000 <= ord(char) <= 0x1FAFF
        or 0x2600 <= ord(char) <= 0x27BF
        or 0x2300 <= ord(char) <= 0x23FF
        for char in value
    )


def _twemoji_url(value: str) -> str:
    # Twemoji retire FE0F des noms de fichiers, mais conserve les jointures ZWJ,
    # les variantes de couleur de peau et les combinaisons de drapeaux.
    codepoints = "-".join(f"{ord(char):x}" for char in value if ord(char) != 0xFE0F)
    return (
        "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/"
        f"assets/72x72/{codepoints}.png"
    )


def _image_kind(data: bytes) -> str | None:
    """Détermine le type depuis les octets, sans faire confiance au serveur distant."""
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def _custom_emoji_urls(emoji_id: str, animated: bool) -> list[str]:
    extension = "gif" if animated else "png"
    base = f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}"
    # Les variantes sont essayées sans convertir un GIF en PNG : un emoji animé
    # reste donc animé même si un point CDN refuse une taille avec le code 415.
    return [
        base,
        f"{base}?size=128&quality=lossless",
        f"https://media.discordapp.net/emojis/{emoji_id}.{extension}?size=128&quality=lossless",
    ]


def _discord_avatar_url_variants(asset_url: str) -> list[str]:
    """Construit les variantes officielles d'un avatar Discord sans avatar par défaut."""
    parsed = urlparse(asset_url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "cdn.discordapp.com",
        "media.discordapp.net",
    }:
        return [asset_url]

    path_without_extension = re.sub(
        r"\.(?:gif|png|webp|jpe?g)$",
        "",
        parsed.path,
        flags=re.IGNORECASE,
    )
    filename = path_without_extension.rsplit("/", 1)[-1]
    original_match = re.search(r"\.([A-Za-z0-9]+)$", parsed.path)
    original_format = original_match.group(1).lower() if original_match else "webp"
    formats = [original_format]
    if filename.startswith("a_"):
        formats.extend(("gif", "webp", "png"))
    else:
        formats.extend(("webp", "png", "jpg"))

    variants: list[str] = []
    for hostname in (parsed.hostname, "cdn.discordapp.com", "media.discordapp.net"):
        for image_format in dict.fromkeys(formats):
            for size in (1024, 512, 256):
                candidate = (
                    f"https://{hostname}{path_without_extension}.{image_format}"
                    f"?size={size}&quality=lossless"
                )
                if candidate not in variants:
                    variants.append(candidate)
    return variants


async def _download_discord_avatar(
    asset_urls: list[str],
    *,
    byte_limit: int,
) -> tuple[bytes, str, str] | None:
    """Télécharge la vraie image via les deux CDN Discord et valide ses octets."""
    timeout = aiohttp.ClientTimeout(total=12, connect=5)
    headers = {
        "User-Agent": "SentriX-Avatar/3.0",
        "Accept": "image/avif,image/webp,image/apng,image/gif,image/*,*/*;q=0.8",
    }
    tried: set[str] = set()
    variants: list[str] = []
    for asset_url in asset_urls[:6]:
        for candidate in _discord_avatar_url_variants(asset_url):
            if candidate not in tried:
                tried.add(candidate)
                variants.append(candidate)

    if not variants:
        return None

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        semaphore = asyncio.Semaphore(8)

        async def fetch(candidate: str) -> tuple[bytes, str, str] | None:
            try:
                async with semaphore:
                    async with session.get(candidate, allow_redirects=True) as response:
                        if response.status != 200:
                            return None
                        declared_size = int(response.headers.get("Content-Length", "0") or 0)
                        if declared_size > byte_limit:
                            return None
                        data = await response.content.read(byte_limit + 1)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return None
            if len(data) > byte_limit:
                return None
            kind = _image_kind(data)
            return (data, kind, candidate) if kind is not None else None

        tasks = [asyncio.create_task(fetch(candidate)) for candidate in variants]
        try:
            for completed in asyncio.as_completed(tasks, timeout=5):
                result = await completed
                if result is not None:
                    return result
        except asyncio.TimeoutError:
            pass
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    return None


def _emoji_canvas(frame: Image.Image, size: int) -> Image.Image:
    rgba = frame.convert("RGBA")
    rgba.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    left = (size - rgba.width) // 2
    top = (size - rgba.height) // 2
    canvas.alpha_composite(rgba, (left, top))
    return canvas


def _encode_static_emoji(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > 16_777_216:
                raise ValueError("L'image source est trop grande pour être traitée.")
            canvas = _emoji_canvas(source, EMOJI_DIMENSION)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Impossible de décoder cette image.") from exc

    attempts: list[bytes] = []
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True, compress_level=9)
    attempts.append(output.getvalue())
    for colors in (256, 128, 64):
        output = io.BytesIO()
        indexed = canvas.quantize(
            colors=colors,
            method=Image.Quantize.FASTOCTREE,
            dither=Image.Dither.NONE,
        )
        indexed.save(output, format="PNG", optimize=True, compress_level=9)
        attempts.append(output.getvalue())
    for encoded in attempts:
        if len(encoded) <= MAX_EMOJI_BYTES:
            return encoded
    raise ValueError("L'image reste trop lourde après conversion en PNG 128 × 128.")


def _encode_animated_emoji(data: bytes) -> bytes:
    # Plusieurs niveaux sont essayés : l'animation est conservée, puis réduite
    # progressivement uniquement si elle dépasse encore la limite Discord.
    strategies = [
        (128, 256, 1),
        (112, 192, 1),
        (96, 128, 1),
        (80, 96, 2),
        (64, 64, 2),
    ]
    last_size = 0
    for size, colors, frame_step in strategies:
        try:
            with Image.open(io.BytesIO(data)) as source:
                frame_count = getattr(source, "n_frames", 1)
                if frame_count <= 1:
                    raise ValueError("Le GIF ne contient pas plusieurs images.")
                if frame_count > 400:
                    raise ValueError("Le GIF contient trop d'images pour un emoji Discord.")
                if source.width * source.height > 16_777_216:
                    raise ValueError("Le GIF source est trop grand pour être traité.")
                default_duration = max(20, int(source.info.get("duration", 100) or 100))
                loop = int(source.info.get("loop", 0) or 0)
                frames: list[Image.Image] = []
                durations: list[int] = []
                for index, frame in enumerate(ImageSequence.Iterator(source)):
                    if index % frame_step:
                        continue
                    canvas = _emoji_canvas(frame, size)
                    indexed = canvas.quantize(
                        colors=colors,
                        method=Image.Quantize.FASTOCTREE,
                        dither=Image.Dither.NONE,
                    )
                    frames.append(indexed)
                    duration = int(frame.info.get("duration", default_duration) or default_duration)
                    durations.append(max(20, min(1000, duration * frame_step)))
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Impossible de décoder ce GIF animé.") from exc

        if len(frames) <= 1:
            raise ValueError("Le GIF ne contient pas assez d'images pour rester animé.")
        output = io.BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=loop,
            disposal=2,
            optimize=True,
        )
        encoded = output.getvalue()
        last_size = len(encoded)
        if len(encoded) <= MAX_EMOJI_BYTES:
            return encoded
    raise ValueError(
        f"Le GIF reste trop lourd après optimisation ({last_size // 1024} Ko). "
        "Utilisez une animation plus courte."
    )


def _normalise_emoji_asset(data: bytes, animated: bool) -> bytes:
    return _encode_animated_emoji(data) if animated else _encode_static_emoji(data)


# Ordre volontaire : catégories utiles à tout le monde en premier, catégories staff/technique
# ensuite — pour que /help mette en avant ce qui sert le plus grand nombre.
CATEGORY_LABELS = {
    "Ai": "🤖 Intelligence Artificielle",
    "Economy": "💰 Économie",
    "Levels": "📈 Niveaux / Communauté",
    "Minigames": "🎮 Mini-jeux",
    "Music": "🎵 Musique",
    "Events": "🎉 Giveaways / Événements",
    "Invites": "📨 Invitations",
    "Utility": "🧰 Utilitaires",
    "Notifications": "📡 Notifications sociales / Accueil",
    "Moderation": "🛡️ Modération",
    "Automod": "🔒 Sécurité / AutoMod",
    "Security": "🔐 Sécurité avancée",
    "Tickets": "🎫 Tickets",
    "Verification": "● Vérification / Rôles",
    "Configuration": "⚙️ Configuration",
    "ServerBuilder": "🏗️ Création de serveur",
    "Stats": "📊 Statistiques / Développement",
    "Owner": "🔑 Propriétaire du bot",
    "EmbedBuilder": "📨 Créateur d'embeds",
    "Design": "Design et apparence",
}

# Catégories entièrement réservées au staff : un membre normal ne les voit JAMAIS
# dans /help, même si elles contiennent une commande techniquement publique.
MEMBER_HIDDEN_CATEGORIES = {"Moderation", "Automod", "Security", "Configuration", "ServerBuilder", "Verification", "Notifications", "Owner", "EmbedBuilder"}

# Décorateurs qui, sur une commande, signifient "réservé au staff". On les repère par
# le nom qualifié de la fonction de vérification plutôt que par une liste de commandes
# écrite à la main : ainsi le filtrage reste juste même quand des commandes sont
# ajoutées ou déplacées plus tard.
STAFF_CHECK_MARKERS = ("is_owner_or_admin", "has_permission", "has_permissions", "has_guild_permissions", "is_owner", "is_bot_owner")


def is_staff_command(cmd) -> bool:
    """Détecte les restrictions de la commande et de chacun de ses groupes parents."""
    current = cmd
    while current is not None:
        for check in getattr(current, "checks", []):
            qualname = getattr(check, "__qualname__", "") or ""
            if any(marker in qualname for marker in STAFF_CHECK_MARKERS):
                return True
        current = getattr(current, "parent", None)
    return False


def slash_command_names(bot: commands.Bot) -> set[str]:
    """Retourne aussi les sous-commandes slash (tree.get_commands ne donne que les racines)."""
    names: set[str] = set()

    def visit(command, parent: str = ""):
        qualified = f"{parent} {command.name}".strip()
        names.add(qualified)
        for child in getattr(command, "commands", []):
            visit(child, qualified)

    for command in bot.tree.get_commands():
        visit(command)
    return names


def visible_commands(cog, is_staff: bool):
    # walk_commands inclut aussi toutes les sous-commandes des groupes. Cela évite que
    # +help oublie d'anciennes commandes dès qu'elles sont rangées dans un groupe.
    walker = getattr(cog, "walk_commands", None)
    source = list(walker()) if walker else cog.get_commands()
    cmds = [c for c in source if not c.hidden]
    return cmds if is_staff else [c for c in cmds if not is_staff_command(c)]


def category_visible(cog_name: str, cog, is_staff: bool) -> bool:
    if not is_staff and cog_name in MEMBER_HIDDEN_CATEGORIES:
        return False
    return bool(visible_commands(cog, is_staff))


def split_category_label(label: str) -> tuple[str | None, str]:
    """Sépare l'emoji décoratif du nom seulement si le premier élément est réellement
    un symbole. Une catégorie textuelle comme "Design et apparence" reste intacte."""
    first, separator, rest = label.partition(" ")
    if separator and first and any(not char.isalnum() for char in first):
        return first, rest
    return None, label


CATEGORY_EMOJI = {name: split_category_label(label)[0] for name, label in CATEGORY_LABELS.items()}


def build_help_home(bot: commands.Bot, guild: discord.Guild | None, prefix: str, is_staff: bool) -> discord.Embed:
    """Construit l'embed d'accueil de /help. Partagé entre la première commande et le
    bouton "Accueil", pour que revenir en arrière affiche exactement la même chose."""
    rows = []  # (nom sans emoji, nombre de commandes, réservé au staff ?)
    visible_total = 0
    for cog_name, label in CATEGORY_LABELS.items():
        cog = bot.get_cog(cog_name)
        if not cog or not category_visible(cog_name, cog, is_staff):
            continue
        count = len(visible_commands(cog, is_staff))
        visible_total += count
        name = split_category_label(label)[1]
        rows.append((name, count, cog_name in MEMBER_HIDDEN_CATEGORIES))

    bot_name = bot.user.name if bot.user else "le bot"
    server_name = guild.name if guild else "ce serveur"

    e = embeds.brand(
        f"📖 Bienvenue dans l'aide de {bot_name}",
        f"Je suis l'assistant du serveur **{server_name}**. Je m'occupe de la modération, de la sécurité, "
        f"des tickets de support, de l'économie virtuelle, des niveaux, de la musique et de plein de "
        f"mini-jeux — pour que la communauté reste agréable et vivante.\n\n"
        f"Utilisez le menu déroulant tout en bas pour explorer une catégorie en détail, le bouton "
        f"**🔎 Rechercher** pour trouver une commande par mot-clé, ou tapez `{prefix}help <commande>` "
        f"pour l'aide détaillée d'une commande précise."
    )
    if bot.user:
        e.set_thumbnail(url=bot.user.display_avatar.url)

    if rows:
        name_width = max(len(n) for n, _, _ in rows) + 2
        lines = []
        for name, count, staff_only in rows:
            suffix = " (staff)" if staff_only else ""
            lines.append(f"{name.ljust(name_width)}{str(count).rjust(2)}{suffix}")
        e.add_field(name="📚 Catégories disponibles", value="```\n" + "\n".join(lines) + "\n```", inline=False)

    e.add_field(
        name="ℹ️ Bon à savoir",
        value=(
            f"**{visible_total} commande(s)** disponibles pour vous. Toutes fonctionnent avec le "
            f"préfixe `{prefix}` ; celles marquées `/ ou {prefix}` fonctionnent aussi en slash.\n"
            f"Astuce : `/sentrix <question>` répond à n'importe quelle question avec une jauge de confiance."
        ),
        inline=False,
    )
    return e


def format_command_line(cmd, prefix: str, slash_names: set) -> str:
    marker = f"/ ou {prefix}" if cmd.qualified_name in slash_names else prefix
    usage = ""
    if isinstance(cmd, commands.HybridCommand) and cmd.clean_params:
        parts = []
        for pname, param in cmd.clean_params.items():
            parts.append(f"[{pname}]" if param.required else f"({pname})")
        usage = " " + " ".join(parts)
    lock = "🔒 " if is_staff_command(cmd) else ""
    return f"{lock}**`{marker}{cmd.qualified_name}{usage}`**\n╰ {cmd.description or 'Pas de description.'}"


def search_commands(bot: commands.Bot, is_staff: bool, keyword: str):
    """Cherche un mot-clé dans le nom ET la description de toutes les commandes visibles,
    toutes catégories confondues. Retourne une liste de (label_catégorie, commande)."""
    keyword = keyword.lower().strip()
    results = []
    for cog_name, label in CATEGORY_LABELS.items():
        cog = bot.get_cog(cog_name)
        if not cog or not category_visible(cog_name, cog, is_staff):
            continue
        for cmd in visible_commands(cog, is_staff):
            haystack = f"{cmd.qualified_name} {cmd.description or ''}".lower()
            if keyword in haystack:
                results.append((label, cmd))
    return results


class SearchModal(discord.ui.Modal, title="🔎 Rechercher une commande"):
    mot_cle = discord.ui.TextInput(label="Mot-clé (nom ou description)", max_length=50)

    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool):
        super().__init__()
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff

    async def on_submit(self, interaction: discord.Interaction):
        slash_names = slash_command_names(self.bot)
        results = search_commands(self.bot, self.is_staff, self.mot_cle.value)

        if not results:
            e = embeds.brand("🔎 Recherche", f"Aucune commande trouvée pour `{self.mot_cle.value}`.")
            return await interaction.response.edit_message(embed=e, view=HelpView(self.bot, self.prefix, self.is_staff))

        lines = [f"*{label}*\n{format_command_line(cmd, self.prefix, slash_names)}" for label, cmd in results]
        chunks = [lines[i:i + 6] for i in range(0, len(lines), 6)] or [[]]
        pages = []
        for i, chunk in enumerate(chunks):
            e = embeds.brand(f"🔎 Résultats pour « {self.mot_cle.value} »", "\n\n".join(chunk))
            e.set_footer(text=f"Page {i + 1}/{len(chunks)} • {len(results)} commande(s) trouvée(s)")
            pages.append(e)

        home_embed = build_help_home(self.bot, interaction.guild, self.prefix, self.is_staff)
        view = CategoryHelpView(self.bot, self.prefix, self.is_staff, pages, interaction.user.id, home_embed)
        await interaction.response.edit_message(embed=pages[0], view=view)


class HelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool):
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        options = []
        for cog_name, label in CATEGORY_LABELS.items():
            cog = bot.get_cog(cog_name)
            if not cog or not category_visible(cog_name, cog, is_staff):
                continue
            # Aucun emoji dans les options : Discord rejette certains symboles Unicode
            # ordinaires (par exemple ●) lorsqu'ils sont envoyés comme emoji de composant.
            options.append(discord.SelectOption(
                label=split_category_label(label)[1],
                value=cog_name,
                description=f"{len(visible_commands(cog, is_staff))} commande(s)",
            ))
        # Discord autorise au maximum 25 options dans un menu.
        super().__init__(placeholder="Choisissez une catégorie...", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        cog = self.bot.get_cog(self.values[0])
        label = CATEGORY_LABELS.get(self.values[0], self.values[0])
        slash_names = slash_command_names(self.bot)

        lines = [format_command_line(cmd, self.prefix, slash_names) for cmd in visible_commands(cog, self.is_staff)]

        if not lines:
            e = embeds.brand(label, "Aucune commande visible dans cette catégorie pour vous.")
            return await interaction.response.edit_message(embed=e, view=self.view)

        chunks = [lines[i:i + 8] for i in range(0, len(lines), 8)] or [[]]
        pages = []
        for i, chunk in enumerate(chunks):
            e = embeds.brand(label, "\n\n".join(chunk))
            e.set_footer(text=f"Page {i + 1}/{len(chunks)} • {len(lines)} commande(s) au total • [param] = requis, (param) = optionnel")
            pages.append(e)

        home_embed = build_help_home(self.bot, interaction.guild, self.prefix, self.is_staff)
        view = CategoryHelpView(self.bot, self.prefix, self.is_staff, pages, interaction.user.id, home_embed)
        await interaction.response.edit_message(embed=pages[0], view=view)


class CategoryHelpView(discord.ui.View):
    """Vue affichée après avoir choisi une catégorie : menu déroulant toujours accessible
    pour changer de catégorie, pagination si besoin, et un bouton pour revenir à l'accueil."""

    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, pages: list[discord.Embed], author_id: int, home_embed: discord.Embed):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.pages = pages
        self.author_id = author_id
        self.home_embed = home_embed
        self.index = 0
        self.add_item(HelpSelect(bot, prefix, is_staff))
        self._update_buttons()

    def _update_buttons(self):
        self.previous_page.disabled = self.index == 0
        self.next_page.disabled = len(self.pages) <= 1 or self.index >= len(self.pages) - 1
        if len(self.pages) <= 1:
            self.previous_page.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne à l'origine de la commande peut naviguer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="🏠 Accueil", style=discord.ButtonStyle.primary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = HelpView(self.bot, self.prefix, self.is_staff)
        await interaction.response.edit_message(embed=self.home_embed, view=view)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="🔎 Rechercher", style=discord.ButtonStyle.secondary, row=2)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self.bot, self.prefix, self.is_staff))


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool):
        super().__init__(timeout=120)
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.add_item(HelpSelect(bot, prefix, is_staff))

    @discord.ui.button(label="🔎 Rechercher une commande", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self.bot, self.prefix, self.is_staff))



# Libelles francais des reglages de serveur. Discord les expose sous forme d'enums
# anglaises ; les afficher brutes ne renseigne personne.
NIVEAUX_VERIFICATION = {
    "none": ("Aucune", "N'importe qui peut écrire immédiatement."),
    "low": ("Faible", "E-mail vérifié exigé."),
    "medium": ("Moyenne", "Compte Discord de plus de 5 minutes."),
    "high": ("Élevée", "Membre du serveur depuis plus de 10 minutes."),
    "highest": ("Maximale", "Numéro de téléphone vérifié exigé."),
}
FILTRES_CONTENU = {
    "disabled": "Aucune analyse des médias",
    "no_role": "Médias analysés pour les membres sans rôle",
    "all_members": "Médias analysés pour tout le monde",
}
# Nombre de boosts requis par palier. Sert a dire ce qu'il manque, pas seulement
# ou on en est.
BOOSTS_PAR_PALIER = {0: 2, 1: 7, 2: 14}


def _detail_salons(guild) -> str:
    """Repartition reelle des salons. « 42 salons » ne dit pas s'il en manque un type."""
    compte = {
        "catégories": len(guild.categories),
        "textuels": len(guild.text_channels),
        "vocaux": len(guild.voice_channels),
        "forums": len(getattr(guild, "forums", []) or []),
        "conférences": len(guild.stage_channels),
    }
    lignes = [f"**{nombre}** {nom}" for nom, nombre in compte.items() if nombre]
    fils = len(guild.threads)
    if fils:
        lignes.append(f"**{fils}** fils actifs")
    return "\n".join(lignes) or "Aucun salon"


def _marge_boosts(guild) -> str:
    """Ou en est le serveur, et combien de boosts il manque pour le palier suivant."""
    palier = guild.premium_tier
    boosts = guild.premium_subscription_count or 0
    actuel = f"Palier {palier}" if palier else "Aucun palier"
    requis = BOOSTS_PAR_PALIER.get(palier)
    if requis is None:
        return f"{actuel} — palier maximal atteint\n**{boosts}** boosts actifs"
    manquants = max(0, requis - boosts)
    if manquants:
        return f"{actuel} · **{boosts}** boosts\nEncore **{manquants}** pour le palier {palier + 1}"
    return f"{actuel} · **{boosts}** boosts\nPalier {palier + 1} atteint sous peu"


class Utility(commands.Cog, name="Utility"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.afk_users: dict[int, str] = {}

    @staticmethod
    def _envoi_cible(ctx, membre, embed) -> dict:
        """Arguments d'envoi d'une fiche concernant une personne.

        Une mention placee dans un EMBED ne notifie JAMAIS : c'est une regle Discord.
        Pour que la personne soit reellement prevenue, la mention doit etre dans le
        content du message et allowed_mentions doit l'autoriser nommement.

        Deux gardes volontaires : on ne ping que si une cible a ete demandee (consulter
        sa propre fiche ne s'auto-notifie pas, et un bot n'est jamais ping), et jamais
        everyone ni les roles — consulter une fiche ne doit pas pouvoir alerter le
        serveur entier.
        """
        envoi = {"embed": embed}
        auteur = getattr(ctx, "author", None)
        if (
            membre is not None
            and getattr(auteur, "id", None) != getattr(membre, "id", None)
            and not getattr(membre, "bot", False)
        ):
            envoi["content"] = membre.mention
            envoi["allowed_mentions"] = discord.AllowedMentions(
                users=[membre], roles=False, everyone=False, replied_user=False
            )
        return envoi

    @staticmethod
    def _limited_list(values, *, empty: str, limit: int = 1000) -> str:
        """Assemble une liste sans dépasser la limite de 1 024 caractères d'un champ Discord."""
        values = [str(value) for value in values]
        if not values:
            return empty

        visible: list[str] = []
        for index, value in enumerate(values):
            hidden = len(values) - index
            suffix = f"\n… et {hidden} autre{'s' if hidden > 1 else ''}." if hidden else ""
            candidate = ", ".join([*visible, value])
            if len(candidate) + len(suffix) > limit:
                return (", ".join(visible) or value[: limit - len(suffix)]) + suffix
            visible.append(value)
        return ", ".join(visible)

    async def _embed(self, guild_id: int | None, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed utilitaire cohérent avec +designsetup (catégorie CATEGORY_STYLES["utility"]).
        `guild_id` peut être None (ex: commande utilisée en DM) — dans ce cas on retombe sur
        les réglages par défaut plutôt que d'échouer."""
        style = design_system.CATEGORY_STYLES["utility"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        design = await self.bot.db.get_design_settings(guild_id) if guild_id else dict(design_system.DEFAULT_DESIGN_SETTINGS)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )

    async def _user_is_staff(self, ctx: commands.Context) -> bool:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return False
        import config
        if ctx.author.id in config.OWNER_IDS:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        return await checks.is_mod_or_permission(ctx, "manage_guild")

    @commands.hybrid_command(name="help", description="Afficher la liste des commandes du bot.")
    @app_commands.describe(commande="Nom d'une commande précise (optionnel)")
    async def help_cmd(self, ctx: commands.Context, *, commande: str = None):
        prefix = self.bot.command_prefix
        if callable(prefix):
            conf = await self.bot.db.get_guild_config(ctx.guild.id) if ctx.guild else None
            prefix = conf["prefix"] if conf and conf["prefix"] else "+"

        is_staff = await self._user_is_staff(ctx)

        if commande:
            cmd = self.bot.get_command(commande)
            if not cmd or (is_staff_command(cmd) and not is_staff):
                return await ctx.send(embed=embeds.error(f"La commande `{commande}` est introuvable ou vous n’avez pas la permission de la consulter.\nUtilisez `{prefix}help` pour afficher uniquement les commandes disponibles pour vous."))
            slash_names = slash_command_names(self.bot)
            is_slash = cmd.qualified_name in slash_names
            marker = f"/{cmd.qualified_name}" if is_slash else f"{prefix}{cmd.qualified_name}"

            # Catégorie d'origine de la commande, pour donner du contexte.
            category_label = CATEGORY_LABELS.get(cmd.cog.qualified_name, cmd.cog.qualified_name) if cmd.cog else "—"

            e = embeds.brand(f"📘 {marker}", cmd.description or "Pas de description.")
            e.add_field(name="📂 Catégorie", value=category_label, inline=True)
            e.add_field(
                name="🔗 Accès",
                value="Slash `/` et préfixe" if is_slash else f"Préfixe `{prefix}` uniquement",
                inline=True,
            )
            e.add_field(name="🔒 Staff uniquement", value="Oui" if is_staff_command(cmd) else "Non", inline=True)

            if getattr(cmd, "aliases", None):
                e.add_field(name="🔁 Alias", value=", ".join(f"`{a}`" for a in cmd.aliases), inline=False)

            if isinstance(cmd, commands.HybridCommand) and cmd.clean_params:
                param_lines = []
                usage_parts = []
                for pname, param in cmd.clean_params.items():
                    required = param.required
                    type_name = getattr(param.annotation, "__name__", str(param.annotation)).replace("Optional", "texte")
                    tag = "requis" if required else "optionnel"
                    param_lines.append(f"• **{pname}** ({type_name}, {tag})")
                    usage_parts.append(f"<{pname}>" if required else f"[{pname}]")
                e.add_field(name="🧩 Paramètres", value="\n".join(param_lines), inline=False)
                e.add_field(name="✏️ Exemple d'usage", value=f"`{prefix}{cmd.qualified_name} {' '.join(usage_parts)}`", inline=False)
            else:
                e.add_field(name="✏️ Exemple d'usage", value=f"`{marker}`", inline=False)

            e.set_footer(text=f"Utilisez {prefix}help pour revenir à la liste complète.")
            return await ctx.send(embed=e)

        e = build_help_home(self.bot, ctx.guild, prefix, is_staff)
        try:
            view = HelpView(self.bot, prefix, is_staff)
            await ctx.send(embed=e, view=view)
        except Exception:
            # L'aide textuelle reste disponible même si Discord refuse ponctuellement
            # un composant du menu. Le détail technique reste visible dans Railway.
            logger.exception("Impossible d'afficher le menu interactif de +help")
            await ctx.send(embed=e)

    @commands.hybrid_command(name="ping", description="Afficher la latence du bot.")
    async def ping(self, ctx: commands.Context):
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Pong !", description=f"Latence : **{round(self.bot.latency * 1000)}ms**"))

    @commands.hybrid_command(name="avatar", description="Afficher l'avatar d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def avatar(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        # Rafraîchit les données : un Member gardé en cache peut encore contenir l'ancien
        # hash d'un avatar animé et produire une URL CDN « Invalid resource ».
        fresh_member = membre
        try:
            if ctx.guild is not None:
                fresh_member = await ctx.guild.fetch_member(membre.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        fresh_user = None
        try:
            fresh_user = await self.bot.fetch_user(membre.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        display_name = (
            getattr(fresh_member, "display_name", None)
            or getattr(membre, "display_name", None)
            or getattr(membre, "name", None)
            or str(membre)
        )
        e = await self._embed(
            ctx.guild.id if ctx.guild else None,
            title=f"Avatar de {display_name}",
            description=membre.mention,
        )

        # Chaque URL est d'abord lue et validée. L'URL validée est ensuite placée dans
        # l'embed : contrairement à attachment://, elle ne peut pas être désolidarisée
        # de l'image par une couche de style intermédiaire.
        message_member = getattr(getattr(ctx, "message", None), "author", None)
        if getattr(message_member, "id", None) != membre.id:
            message_member = None
        mentioned_member = next(
            (
                mention
                for mention in getattr(getattr(ctx, "message", None), "mentions", ())
                if getattr(mention, "id", None) == membre.id
            ),
            None,
        )
        candidates = [
            # MESSAGE_CREATE contient le profil affiché à côté du message et constitue
            # donc la source la plus fraîche lorsque le membre demande son propre avatar.
            getattr(message_member, "guild_avatar", None),
            getattr(message_member, "display_avatar", None),
            getattr(mentioned_member, "guild_avatar", None),
            getattr(mentioned_member, "display_avatar", None),
            getattr(fresh_member, "guild_avatar", None),
            getattr(fresh_user, "avatar", None),
            getattr(fresh_member, "avatar", None),
            getattr(fresh_member, "display_avatar", None),
            # La mention reçue dans le message peut être plus récente que le cache REST.
            getattr(membre, "guild_avatar", None),
            getattr(membre, "avatar", None),
            getattr(membre, "display_avatar", None),
        ]
        seen: set[str] = set()
        real_asset_urls: list[str] = []
        upload_limit = int(getattr(ctx.guild, "filesize_limit", 10 * 1024 * 1024) or 10 * 1024 * 1024)
        for original_asset in candidates:
            if original_asset is None:
                continue
            original_url = str(getattr(original_asset, "url", "") or "")
            if not original_url or original_url in seen:
                continue
            seen.add(original_url)
            # display_avatar peut être l'avatar Discord par défaut. On ne l'utilise
            # que si son URL correspond réellement à un avatar personnalisé.
            if "/embed/avatars/" in original_url:
                continue
            real_asset_urls.append(original_url)
            for size in (1024, 512, 256):
                try:
                    asset = original_asset
                    if asset.is_animated():
                        asset = asset.with_format("gif")
                    asset = asset.with_size(size)
                    data = await asset.read()
                    if not data or len(data) > upload_limit:
                        continue
                    if _image_kind(data) is None:
                        continue
                    e.set_image(url=str(asset.url))
                    return await ctx.send(**self._envoi_cible(ctx, membre, e))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
                    continue

        # Certains liens GIF expirés sont refusés par cdn.discordapp.com alors que
        # la même ressource fonctionne en WebP/PNG ou via media.discordapp.net.
        downloaded = await _download_discord_avatar(
            real_asset_urls,
            byte_limit=upload_limit,
        )
        if downloaded is not None:
            _data, _kind, verified_url = downloaded
            e.set_image(url=verified_url)
            return await ctx.send(**self._envoi_cible(ctx, membre, e))

        # Ne jamais remplacer silencieusement la vraie photo par l'avatar orange.
        e.description = (
            f"{membre.mention}\n"
            "Discord n'a pas transmis son avatar personnalisé. Réessaie dans quelques secondes."
        )
        await ctx.send(**self._envoi_cible(ctx, membre, e))

    @commands.hybrid_group(
        name="info",
        description="Afficher toutes les informations du serveur ou d'un rôle.",
        invoke_without_command=True,
    )
    async def info(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send(
                embed=await self._embed(
                    ctx.guild.id if ctx.guild else None,
                    title="Informations",
                    description=(
                        "Utilisez `+info serveur` pour le serveur ou "
                        "`+info role @Rôle` pour un rôle.\n"
                        "Ces commandes existent aussi en slash : `/info serveur` et `/info role`."
                    ),
                )
            )

    @info.command(name="serveur", description="Afficher la fiche complète du serveur.")
    async def info_serveur(self, ctx: commands.Context):
        guild = ctx.guild
        if guild is None:
            return await ctx.send(embed=await self._embed(None, title="Serveur requis", kind="danger"))

        total_members = guild.member_count or len(guild.members)
        bot_count = sum(1 for member in guild.members if member.bot)
        human_count = max(0, total_members - bot_count)
        thread_count = len(guild.threads)
        shard_text = f"Shard #{guild.shard_id}" if guild.shard_id is not None else "Shard inconnu"

        e = await self._embed(
            guild.id,
            title=f"{guild.name} ({guild.id})",
            description=(
                f"Informations et statistiques de **{guild.name}**\n"
                f"**{shard_text} • {len(guild.channels)} salons • {thread_count} fils "
                f"• {len(guild.roles)} rôles • {bot_count} bots**"
            ),
        )
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)

        owner = guild.owner
        owner_value = (
            f"{owner.mention}\n`{owner}`"
            if owner is not None
            else f"<@{guild.owner_id}>\n`ID : {guild.owner_id}`"
        )
        e.add_field(name="Propriétaire", value=owner_value, inline=True)
        e.add_field(
            name="Membres",
            value=f"**{total_members}** membres\n{human_count} humains • {bot_count} bots",
            inline=True,
        )

        e.add_field(name="Boosts", value=_marge_boosts(guild), inline=True)

        # Repartition des salons : « 42 salons » ne disait pas s'il manquait un type.
        e.add_field(name="Salons", value=_detail_salons(guild), inline=True)

        # Reglages de securite du serveur, invisibles autrement sans ouvrir les
        # parametres Discord — et ce sont eux qui decident qui peut ecrire.
        niveau, explication = NIVEAUX_VERIFICATION.get(
            guild.verification_level.name, (guild.verification_level.name, "")
        )
        moderation = [f"Vérification : **{niveau}** — {explication}"]
        moderation.append(
            "Filtre média : "
            + FILTRES_CONTENU.get(guild.explicit_content_filter.name, guild.explicit_content_filter.name)
        )
        if guild.mfa_level:
            moderation.append("Double authentification exigée du staff")
        if guild.afk_channel is not None:
            minutes = (guild.afk_timeout or 0) // 60
            moderation.append(f"Salon inactif : {guild.afk_channel.mention} après {minutes} min")
        e.add_field(name="Modération du serveur", value="\n".join(moderation), inline=False)

        # @everyone est exclu : tous les serveurs l'ont, il n'apprend rien, et son
        # role.name vaut litteralement "@everyone" — ce qui produisait un "@@everyone"
        # a l'affichage des qu'une couche prefixait la mention.
        roles = [
            role.mention for role in reversed(guild.roles)
            if role != guild.default_role
        ]
        e.add_field(
            name=f"Rôles [{len(roles)}]",
            value=self._limited_list(roles, empty="Aucun rôle en dehors de @everyone"),
            inline=False,
        )

        emojis = [str(emoji) for emoji in guild.emojis]
        e.add_field(
            name=f"Émojis [{len(emojis)}/{guild.emoji_limit}]",
            value=self._limited_list(emojis, empty="Aucun emoji personnalisé"),
            inline=False,
        )
        # Quotas : savoir qu'il reste de la place evite de decouvrir la limite au
        # moment d'ajouter un emoji.
        e.add_field(
            name="Capacités",
            value=(
                f"Émojis : **{len(guild.emojis)}/{guild.emoji_limit}**\n"
                f"Autocollants : **{len(guild.stickers)}/{guild.sticker_limit}**\n"
                f"Fichiers : **{guild.filesize_limit // (1024 * 1024)} Mo** par envoi"
            ),
            inline=True,
        )

        created_at = int(guild.created_at.timestamp())
        e.add_field(
            name="Création du serveur",
            value=f"<t:{created_at}:F>\n<t:{created_at}:R>",
            inline=True,
        )

        bot_member = guild.me
        if bot_member is not None and bot_member.joined_at is not None:
            joined_at = int(bot_member.joined_at.timestamp())
            joined_value = f"<t:{joined_at}:F>\n<t:{joined_at}:R>"
        else:
            joined_value = "Date inconnue"
        e.add_field(name=f"Arrivée de {self.bot.user.name}", value=joined_value, inline=True)

        await ctx.send(embed=e)

    @commands.hybrid_command(name="userinfo", description="Afficher les informations d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def userinfo(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        maintenant = discord.utils.utcnow()

        # --- phrase d'ouverture : qui, depuis quand, avec quel role ----------
        cree = int(membre.created_at.timestamp())
        arrive = int(membre.joined_at.timestamp()) if membre.joined_at else None
        anciennete = (maintenant - membre.created_at).days
        plus_haut = membre.top_role if membre.top_role.name != "@everyone" else None

        ouverture = f"{membre.mention} · `{membre.id}`"
        if arrive:
            ouverture += f"\nMembre du serveur depuis <t:{arrive}:R>"
        if plus_haut is not None:
            ouverture += f", rôle le plus élevé {plus_haut.mention}"
        ouverture += "."

        e = await self._embed(
            ctx.guild.id,
            title=membre.display_name,
            description=ouverture,
        )
        e.set_thumbnail(url=membre.display_avatar.url)
        if membre.colour.value:
            e.colour = membre.colour

        # --- compte ----------------------------------------------------------
        compte = [f"Nom d'utilisateur **{membre.name}**"]
        compte.append(f"Créé <t:{cree}:D> · <t:{cree}:R>")
        if anciennete < 7:
            compte.append(f"⚠️ Compte récent : **{anciennete} jour{'s' if anciennete > 1 else ''}**")
        if membre.bot:
            compte.append("Ce compte est un **bot**")
        e.add_field(name="Compte", value="\n".join(compte), inline=True)

        # --- presence sur le serveur ------------------------------------------
        serveur = []
        if arrive:
            serveur.append(f"Arrivé <t:{arrive}:D>")
        if membre.premium_since:
            serveur.append(f"Booste depuis <t:{int(membre.premium_since.timestamp())}:R>")
        if ctx.guild.owner_id == membre.id:
            serveur.append("**Propriétaire du serveur**")
        timeout = getattr(membre, "timed_out_until", None)
        if timeout and timeout > maintenant:
            serveur.append(f"🔇 En timeout jusqu'à <t:{int(timeout.timestamp())}:R>")
        e.add_field(name="Sur ce serveur", value="\n".join(serveur) or "Aucune information", inline=True)

        # --- pouvoirs reels, pas la liste des 40 permissions -------------------
        perms = membre.guild_permissions
        notables = [
            ("administrator", "Administrateur"),
            ("manage_guild", "Gérer le serveur"),
            ("manage_roles", "Gérer les rôles"),
            ("manage_channels", "Gérer les salons"),
            ("ban_members", "Bannir"),
            ("kick_members", "Expulser"),
            ("moderate_members", "Timeout"),
            ("manage_messages", "Gérer les messages"),
        ]
        pouvoirs = [libelle for attribut, libelle in notables if getattr(perms, attribut, False)]
        if perms.administrator:
            pouvoirs = ["**Administrateur** — toutes les permissions"]
        e.add_field(
            name="Pouvoirs",
            value=" · ".join(pouvoirs) if pouvoirs else "Aucune permission de modération",
            inline=False,
        )

        # --- roles -------------------------------------------------------------
        roles = [r.mention for r in reversed(membre.roles) if r.name != "@everyone"]
        e.add_field(
            name=f"Rôles ({len(roles)})",
            value=self._limited_list(roles, empty="Aucun rôle"),
            inline=False,
        )

        e.set_footer(text=f"Demandé par {ctx.author.display_name}")

        # Une mention placee dans un EMBED ne ping jamais : c'est une regle Discord.
        # Pour que la personne soit reellement notifiee, la mention doit etre dans le
        # content du message, et allowed_mentions doit l'autoriser explicitement.
        # On ne ping que si une cible a ete demandee : lancer +userinfo sur soi-meme
        # ne doit pas s'auto-notifier.
        await ctx.send(**self._envoi_cible(ctx, membre, e))

    @info.command(name="role", description="Afficher la fiche complète d'un rôle.")
    @app_commands.describe(role="Le rôle à inspecter")
    async def info_role(self, ctx: commands.Context, role: discord.Role):
        e = await self._embed(ctx.guild.id, title=f"{role.name} ({role.id})")
        if role.color.value:
            e.color = role.color
        if role.icon:
            e.set_thumbnail(url=role.icon.url)

        e.add_field(name="Mention", value=role.mention, inline=True)
        e.add_field(name="Couleur", value=str(role.color), inline=True)
        e.add_field(name="Membres", value=len(role.members), inline=True)

        # La position brute ne dit rien a personne. Ce qui compte, c'est si SentriX
        # peut attribuer ou retirer ce role — c'est la cause de la plupart des echecs
        # « je n'ai pas pu donner le rôle ».
        moi = ctx.guild.me
        rang = [f"Position **{role.position}** sur {len(ctx.guild.roles)}"]
        if role == ctx.guild.default_role:
            rang.append("Rôle par défaut : tout le monde l'a.")
        elif moi is None:
            rang.append("Hiérarchie inconnue.")
        elif not moi.guild_permissions.manage_roles:
            rang.append("SentriX ne peut pas le gérer : permission **Gérer les rôles** manquante.")
        elif role >= moi.top_role:
            rang.append(
                f"SentriX ne peut pas le gérer : il est au-dessus de {moi.top_role.mention}. "
                "Remontez le rôle de SentriX au-dessus."
            )
        elif role.managed:
            rang.append("Géré par Discord ou une intégration : personne ne peut l'attribuer.")
        else:
            rang.append("SentriX peut l'attribuer et le retirer.")
        e.add_field(name="Hiérarchie", value="\n".join(rang), inline=False)

        nature = []
        if role.hoist:
            nature.append("Affiché séparément dans la liste des membres")
        if role.mentionable:
            nature.append("Mentionnable par tout le monde")
        if role.is_premium_subscriber():
            nature.append("Rôle des boosteurs du serveur")
        if role.is_bot_managed():
            nature.append("Rôle d'intégration d'un bot")
        if role.is_integration():
            nature.append("Rôle géré par une intégration")
        e.add_field(
            name="Particularités",
            value="\n".join(f"• {ligne}" for ligne in nature) or "Rôle ordinaire, sans réglage particulier.",
            inline=False,
        )

        created_at = int(role.created_at.timestamp())
        e.add_field(
            name="Création du rôle",
            value=f"<t:{created_at}:F>\n<t:{created_at}:R>",
            inline=True,
        )

        # Les permissions s'affichaient en anglais avec des tirets bas
        # (« manage guild », « moderate members »). access_matrix les traduit.
        actives = [nom for nom, activee in role.permissions if activee]
        sensibles = [nom for nom in actives if nom in access_matrix.PERMISSIONS_SENSIBLES]
        ordinaires = [nom for nom in actives if nom not in access_matrix.PERMISSIONS_SENSIBLES]

        if role.permissions.administrator:
            e.add_field(
                name="Pouvoirs sensibles",
                value=(
                    "**Administrateur** — ce rôle contourne toutes les autres "
                    "permissions et tous les réglages de salon."
                ),
                inline=False,
            )
        elif sensibles:
            e.add_field(
                name=f"Pouvoirs sensibles [{len(sensibles)}]",
                value=self._limited_list(
                    [access_matrix.permission_label(nom) for nom in sensibles],
                    empty="Aucun",
                ),
                inline=False,
            )

        e.add_field(
            name=f"Autres permissions [{len(ordinaires)}]",
            value=self._limited_list(
                [access_matrix.permission_label(nom) for nom in ordinaires],
                empty="Aucune",
            ),
            inline=False,
        )
        await ctx.send(embed=e)

    @commands.hybrid_command(name="channelinfo", description="Afficher les informations d'un salon.", with_app_command=False)
    @app_commands.describe(salon="Le salon visé (optionnel)")
    async def channelinfo(self, ctx: commands.Context, salon: discord.abc.GuildChannel = None):
        salon = salon or ctx.channel
        cree = int(salon.created_at.timestamp())

        types_lisibles = {
            discord.ChannelType.text: "Salon textuel",
            discord.ChannelType.voice: "Salon vocal",
            discord.ChannelType.category: "Catégorie",
            discord.ChannelType.news: "Salon d'annonces",
            discord.ChannelType.stage_voice: "Conférence",
            discord.ChannelType.forum: "Forum",
        }
        libelle = types_lisibles.get(salon.type, str(salon.type).replace("_", " ").capitalize())

        ouverture = f"{salon.mention} · `{salon.id}`\n**{libelle}**"
        if getattr(salon, "category", None) is not None:
            ouverture += f" dans **{salon.category.name}**"
        ouverture += f", créé <t:{cree}:R>."

        e = await self._embed(ctx.guild.id, title=salon.name, description=ouverture)

        # --- sujet du salon, s'il en a un -----------------------------------
        sujet = str(getattr(salon, "topic", "") or "").strip()
        if sujet:
            e.add_field(name="Sujet", value=sujet[:1000], inline=False)

        # --- reglages, selon le type ----------------------------------------
        reglages: list[str] = []
        lenteur = getattr(salon, "slowmode_delay", 0) or 0
        if lenteur:
            reglages.append(f"Mode lent **{lenteur}s**")
        if getattr(salon, "nsfw", False):
            reglages.append("Marqué **NSFW**")
        if isinstance(salon, discord.VoiceChannel):
            reglages.append(f"Qualité **{salon.bitrate // 1000} kbps**")
            reglages.append(
                f"Limite **{salon.user_limit}**" if salon.user_limit else "Aucune limite de place"
            )
            reglages.append(f"**{len(salon.members)}** connecté(s)")
        if isinstance(salon, discord.TextChannel):
            fils = len(salon.threads)
            reglages.append(f"**{fils}** fil(s) actif(s)" if fils else "Aucun fil actif")
        reglages.append(f"Position **{getattr(salon, 'position', 0)}**")
        e.add_field(name="Réglages", value="\n".join(reglages), inline=True)

        # --- qui y a acces --------------------------------------------------
        acces: list[str] = []
        try:
            everyone = salon.overwrites_for(ctx.guild.default_role)
            if everyone.view_channel is False:
                acces.append("🔒 **Salon privé** — @everyone ne le voit pas")
            else:
                acces.append("🌐 Visible par **@everyone**")
            roles_autorises = [
                cible.mention for cible, perms in salon.overwrites.items()
                if isinstance(cible, discord.Role)
                and cible != ctx.guild.default_role
                and perms.view_channel is True
            ]
            if roles_autorises:
                acces.append("Accès explicite : " + ", ".join(roles_autorises[:5]))
            personnalisations = len(salon.overwrites)
            acces.append(f"**{personnalisations}** permission(s) personnalisée(s)")
        except Exception:
            logger.exception("channelinfo : lecture des permissions impossible.")
            acces.append("Permissions illisibles")
        e.add_field(name="Accès", value="\n".join(acces), inline=True)

        # --- ce que SentriX peut y faire -------------------------------------
        me = ctx.guild.me
        if me is not None:
            perms = salon.permissions_for(me)
            manques = [
                libelle for attribut, libelle in (
                    ("view_channel", "Voir le salon"),
                    ("send_messages", "Envoyer des messages"),
                    ("embed_links", "Intégrer des liens"),
                    ("attach_files", "Joindre des fichiers"),
                    ("manage_messages", "Gérer les messages"),
                ) if not getattr(perms, attribut, False)
            ]
            if manques:
                e.add_field(
                    name="⚠️ SentriX ne peut pas",
                    value=" · ".join(manques),
                    inline=False,
                )

        e.add_field(name="Création", value=f"<t:{cree}:F>", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="membercount", description="Afficher le nombre de membres du serveur.", with_app_command=False)
    async def membercount(self, ctx: commands.Context):
        guild = ctx.guild
        # Un seul passage sur guild.members (au lieu de deux) : sur un serveur de
        # plusieurs dizaines/centaines de milliers de membres, ça compte.
        humans = bots = 0
        for m in guild.members:
            if m.bot:
                bots += 1
            else:
                humans += 1
        e = await self._embed(guild.id, title="Membres du serveur")
        e.add_field(name="Total", value=guild.member_count, inline=True)
        e.add_field(name="Humains", value=humans, inline=True)
        e.add_field(name="Bots", value=bots, inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(
        name="addemoji",
        aliases=["add-emoji", "addemogi", "add-emogi"],
        description="Ajouter un emoji statique ou animé depuis un emoji, une image ou une URL.",
        with_app_command=False,
    )
    @app_commands.describe(
        nom="Nom du nouvel emoji, ou emoji à copier",
        url="Emoji à copier ou URL directe PNG/JPG/WebP/GIF",
    )
    @checks.has_permission("manage_emojis_and_stickers")
    async def addemoji(self, ctx: commands.Context, nom: str, url: str = None):
        if not ctx.guild:
            return await ctx.send(embed=await self._embed(None, title="Commande indisponible", description="Cette commande doit être utilisée sur un serveur.", kind="danger"))
        if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Permission manquante", description="Le bot doit avoir la permission **Gérer les emojis et stickers**.", kind="danger"))

        nom = nom.strip()
        source = (url or "").strip()
        source_urls: list[str] = []
        requires_animation = False

        # Deux syntaxes sont acceptées :
        #   +addemoji <a:danse:123>             -> conserve le nom danse
        #   +addemoji nouveau <a:danse:123>     -> utilise le nom nouveau
        # La seconde syntaxe ne fonctionnait pas auparavant car le deuxième argument
        # était obligatoirement interprété comme une URL HTTPS.
        pasted_emoji = CUSTOM_EMOJI_RE.fullmatch(source or nom)
        if pasted_emoji:
            animated = bool(pasted_emoji.group(1))
            requires_animation = animated
            if not source:
                nom = pasted_emoji.group(2)
            source_urls = _custom_emoji_urls(pasted_emoji.group(3), animated)
        else:
            unicode_source = source if source and _contains_unicode_emoji(source) else None
            if unicode_source is None and not source and _contains_unicode_emoji(nom):
                unicode_source = nom
                first_codepoint = next(
                    ord(char)
                    for char in nom
                    if (
                        0x1F000 <= ord(char) <= 0x1FAFF
                        or 0x2600 <= ord(char) <= 0x27BF
                        or 0x2300 <= ord(char) <= 0x23FF
                    )
                )
                nom = f"emoji_{first_codepoint:x}"
            if unicode_source:
                source_urls = [_twemoji_url(unicode_source)]
            elif source:
                source_urls = [source]
                requires_animation = urlparse(source).path.lower().endswith(".gif")

        if not re.fullmatch(r"[A-Za-z0-9_]{2,32}", nom):
            return await ctx.send(embed=await self._embed(
                ctx.guild.id,
                title="Nom invalide",
                description=(
                    "Le nom doit contenir 2 à 32 caractères : lettres, chiffres ou tiret bas.\n"
                    "Exemple : +addemoji danse <a:emoji:identifiant>"
                ),
                kind="danger",
            ))

        async def validate_public_https(candidate: str) -> str:
            parsed = urlparse(candidate)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Utilisez une URL HTTPS publique et directe.")
            loop = asyncio.get_running_loop()
            try:
                addresses = await loop.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise ValueError("Le domaine de cette URL est introuvable.") from exc
            for info in addresses:
                ip = ipaddress.ip_address(info[4][0])
                if not ip.is_global:
                    raise ValueError("Cette URL pointe vers une adresse privée ou non autorisée.")
            return candidate

        try:
            image_data = None
            attachment = ctx.message.attachments[0] if ctx.message.attachments else None

            if attachment is not None:
                content_type = (attachment.content_type or "").split(";", 1)[0].lower()
                extension = attachment.filename.rsplit(".", 1)[-1].lower() if "." in attachment.filename else ""
                if content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"} and extension not in {"png", "jpg", "jpeg", "gif", "webp"}:
                    raise ValueError("Le fichier joint doit être une image PNG, JPG, GIF ou WebP.")
                if attachment.size > MAX_EMOJI_SOURCE_BYTES:
                    raise ValueError("L'image source dépasse la limite de traitement de 8 Mo.")
                requires_animation = content_type == "image/gif" or extension == "gif"
                image_data = await attachment.read()
            elif source_urls:
                timeout = aiohttp.ClientTimeout(total=12)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    last_error = "Impossible de télécharger cette image."
                    for candidate in source_urls:
                        current_url = await validate_public_https(candidate)
                        for _ in range(5):
                            async with session.get(
                                current_url,
                                allow_redirects=False,
                                headers={
                                    "User-Agent": "SentriX-EmojiImporter/2.0",
                                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                },
                            ) as response:
                                if 300 <= response.status < 400 and response.headers.get("Location"):
                                    current_url = await validate_public_https(
                                        urljoin(current_url, response.headers["Location"])
                                    )
                                    continue
                                if response.status != 200:
                                    last_error = (
                                        f"Le serveur de l'image a répondu avec le code {response.status}."
                                    )
                                    break
                                declared_size = int(
                                    response.headers.get("Content-Length", "0") or 0
                                )
                                if declared_size > MAX_EMOJI_SOURCE_BYTES:
                                    last_error = (
                                        "L'image source dépasse la limite de traitement de 8 Mo."
                                    )
                                    break
                                downloaded = await response.content.read(
                                    MAX_EMOJI_SOURCE_BYTES + 1
                                )
                                if len(downloaded) > MAX_EMOJI_SOURCE_BYTES:
                                    last_error = (
                                        "L'image source dépasse la limite de traitement de 8 Mo."
                                    )
                                    break
                                if _image_kind(downloaded) is None:
                                    last_error = (
                                        "Le lien ne contient pas une vraie image PNG, JPG, GIF ou WebP."
                                    )
                                    break
                                if requires_animation and _image_kind(downloaded) != "gif":
                                    last_error = (
                                        "La source est indiquée comme animée, mais elle ne contient pas "
                                        "un vrai GIF. L'emoji n'a pas été converti en image fixe."
                                    )
                                    break
                                image_data = downloaded
                                break
                        if image_data is not None:
                            break
                    if image_data is None:
                        raise ValueError(last_error)
            else:
                raise ValueError(
                    "Ajoutez après le nom un emoji Discord, une URL, ou joignez une image.\n"
                    "Animé : +addemoji danse <a:emoji:identifiant>\n"
                    "Statique : +addemoji logo <:emoji:identifiant>"
                )

            image_type = _image_kind(image_data or b"")
            if image_type is None:
                raise ValueError("Le fichier n'est pas une vraie image PNG, JPG, GIF ou WebP.")
            if requires_animation and image_type != "gif":
                raise ValueError(
                    "Le fichier est annoncé comme animé, mais ce n'est pas un vrai GIF."
                )

            is_animated = image_type == "gif"
            asset_was_normalised = False
            if not is_animated or len(image_data) > MAX_EMOJI_BYTES:
                image_data = await asyncio.to_thread(
                    _normalise_emoji_asset,
                    image_data,
                    is_animated,
                )
                asset_was_normalised = True

            used_slots = sum(1 for item in ctx.guild.emojis if item.animated == is_animated)
            if used_slots >= ctx.guild.emoji_limit:
                slot_type = "animés" if is_animated else "statiques"
                raise ValueError(
                    f"Le serveur n'a plus de place pour les emojis {slot_type} "
                    f"({used_slots}/{ctx.guild.emoji_limit})."
                )

            try:
                emoji = await ctx.guild.create_custom_emoji(
                    name=nom,
                    image=image_data,
                    reason=f"Emoji ajouté par {ctx.author} avec +addemoji",
                )
            except discord.HTTPException as exc:
                if exc.code != 50046 or asset_was_normalised:
                    raise
                # Certains GIF Discord ont une signature correcte mais un encodage que
                # l'API refuse avec 50046. On le réencode puis on tente une seule fois.
                repaired = await asyncio.to_thread(
                    _normalise_emoji_asset,
                    image_data,
                    is_animated,
                )
                try:
                    emoji = await ctx.guild.create_custom_emoji(
                        name=nom,
                        image=repaired,
                        reason=f"Emoji réparé et ajouté par {ctx.author} avec +addemoji",
                    )
                except discord.HTTPException as retry_exc:
                    if retry_exc.code == 50046:
                        raise ValueError(
                            "Discord refuse encore cette image après sa conversion en "
                            "format emoji 128 × 128. Essayez un autre fichier."
                        ) from retry_exc
                    raise
        except ValueError as exc:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Image refusée", description=str(exc), kind="danger"))
        except asyncio.TimeoutError:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Téléchargement impossible", description="Le serveur de l'image met trop de temps à répondre.", kind="danger"))
        except discord.Forbidden:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Création refusée", description="Discord refuse la création. Vérifiez la permission et la position du rôle du bot.", kind="danger"))
        except (aiohttp.ClientError, discord.HTTPException) as exc:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Création impossible", description=f"Discord ou le serveur de l'image a refusé la demande : {exc}", kind="danger"))

        await ctx.send(embed=await self._embed(
            ctx.guild.id,
            title="Emoji ajouté",
            description=(
                f"{emoji} a été créé sous le nom `:{emoji.name}:`.\n"
                f"Type : **{'animé' if emoji.animated else 'statique'}**."
            ),
            kind="success",
        ))

    @commands.hybrid_command(
        name="deleteemoji",
        aliases=["delemoji", "removeemoji", "delete-emoji"],
        description="Supprimer un emoji personnalisé du serveur.",
        with_app_command=False,
    )
    @app_commands.describe(emoji="Nom de l'emoji ou emoji personnalisé à supprimer")
    @checks.has_permission("manage_emojis_and_stickers")
    async def deleteemoji(self, ctx: commands.Context, *, emoji: str):
        if not ctx.guild:
            return await ctx.send(embed=await self._embed(None, title="Commande indisponible", description="Cette commande doit être utilisée sur un serveur.", kind="danger"))
        if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Permission manquante", description="Le bot doit avoir la permission **Gérer les emojis et stickers**.", kind="danger"))

        value = emoji.strip()
        pasted = re.fullmatch(r"<a?:([A-Za-z0-9_]{2,32}):([0-9]+)>", value)
        target = None
        if pasted:
            target = ctx.guild.get_emoji(int(pasted.group(2)))
        else:
            name = value.strip(":").lower()
            target = discord.utils.find(lambda item: item.name.lower() == name, ctx.guild.emojis)

        if target is None:
            return await ctx.send(embed=await self._embed(
                ctx.guild.id,
                title="Emoji introuvable",
                description="Collez un emoji de ce serveur ou indiquez exactement son nom.",
                kind="danger",
            ))

        emoji_name = target.name
        try:
            await target.delete(reason=f"Emoji supprimé par {ctx.author} avec +deleteemoji")
        except discord.Forbidden:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Suppression refusée", description="Le bot n'a pas la permission de supprimer cet emoji.", kind="danger"))
        except discord.HTTPException as exc:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Suppression impossible", description=f"Discord a refusé la demande : {exc}", kind="danger"))

        await ctx.send(embed=await self._embed(
            ctx.guild.id,
            title="Emoji supprimé",
            description=f"L'emoji `:{emoji_name}:` a été supprimé du serveur.",
            kind="success",
        ))

    @commands.hybrid_command(name="emoji-list", description="Lister les emojis du serveur.", with_app_command=False)
    async def emoji_list(self, ctx: commands.Context):
        if not ctx.guild.emojis:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Aucun emoji", description="Ce serveur n'a aucun emoji personnalisé.", kind="warning"))
        text = " ".join(str(e) for e in ctx.guild.emojis)[:4000]
        await ctx.send(embed=await self._embed(ctx.guild.id, title=f"Emojis ({len(ctx.guild.emojis)})", description=text))

    @commands.hybrid_command(name="poll", description="Créer un sondage rapide (réactions 👍/👎).")
    @app_commands.describe(question="La question du sondage")
    async def poll(self, ctx: commands.Context, *, question: str):
        e = await self._embed(ctx.guild.id if ctx.guild else None, title="Sondage", description=question)
        e.set_footer(text=f"Créé par {ctx.author}")
        msg = await ctx.send(embed=e)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    @commands.hybrid_command(name="remind", description="Définir un rappel personnel.")
    @app_commands.describe(duree="Durée (ex: 10m, 2h, 1j)", texte="Le texte du rappel")
    async def remind(self, ctx: commands.Context, duree: str, *, texte: str):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Durée invalide", description="Exemple : `10m`, `2h`, `1j`.", kind="danger"))
        trigger_at = now() + seconds
        await self.bot.db.execute(
            "INSERT INTO reminders (user_id, channel_id, guild_id, text, trigger_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.author.id, ctx.channel.id, ctx.guild.id if ctx.guild else None, texte, trigger_at, now()),
        )
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Rappel défini", description=f"⏰ Rappel défini dans {helpers.format_duration(seconds)}.", kind="success"))

    @commands.hybrid_command(name="reminder-list", description="Lister vos rappels en cours.", with_app_command=False)
    async def reminder_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM reminders WHERE user_id = ? ORDER BY trigger_at ASC", (ctx.author.id,))
        if not rows:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Aucun rappel", description="Vous n'avez aucun rappel en cours."))
        lines = [f"`#{r['id']}` <t:{r['trigger_at']}:R> — {r['text'][:50]}" for r in rows[:15]]
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Vos rappels", description="\n".join(lines)))

    @commands.hybrid_command(name="reminder-cancel", description="Annuler un rappel.", with_app_command=False)
    @app_commands.describe(id="L'identifiant du rappel (voir /reminder-list)")
    async def reminder_cancel(self, ctx: commands.Context, id: int):
        row = await self.bot.db.fetchone("SELECT * FROM reminders WHERE id = ? AND user_id = ?", (id, ctx.author.id))
        if not row:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Rappel introuvable", kind="danger"))
        await self.bot.db.execute("DELETE FROM reminders WHERE id = ?", (id,))
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Rappel annulé", kind="success"))

    @commands.hybrid_command(name="say", description="Faire répéter un message par le bot.", with_app_command=False)
    @app_commands.describe(texte="Le texte à faire répéter")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx: commands.Context, *, texte: str):
        if ctx.interaction:
            await ctx.interaction.response.send_message("Message envoyé.", ephemeral=True)
        else:
            await ctx.message.delete()
        await ctx.channel.send(texte)

    @commands.hybrid_command(name="embed-create", description="Créer un embed personnalisé.", with_app_command=False)
    @app_commands.describe(titre="Titre de l'embed", description="Contenu de l'embed")
    @commands.has_permissions(manage_messages=True)
    async def embed_create(self, ctx: commands.Context, titre: str, *, description: str):
        e = await self._embed(ctx.guild.id if ctx.guild else None, title=titre, description=description)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="translate", description="Traduire un texte vers une autre langue.")
    @app_commands.describe(langue="Code langue cible (ex: en, es, de)", texte="Le texte à traduire")
    async def translate(self, ctx: commands.Context, langue: str, *, texte: str):
        try:
            from deep_translator import GoogleTranslator
            result = GoogleTranslator(source="auto", target=langue).translate(texte)
            await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title=f"Traduction ({langue})", description=result))
        except Exception:
            await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Traduction échouée", description="Vérifiez le code de langue.", kind="danger"))

    @commands.hybrid_command(name="weather", description="Afficher la météo d'une ville.")
    @app_commands.describe(ville="Le nom de la ville")
    async def weather(self, ctx: commands.Context, *, ville: str):
        import config
        if not config.WEATHER_API_KEY:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Météo indisponible", description="Aucune clé météo n'est configurée sur ce bot.", kind="danger"))
        import aiohttp
        url = f"https://api.openweathermap.org/data/2.5/weather?q={ville}&appid={config.WEATHER_API_KEY}&units=metric&lang=fr"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Ville introuvable", description=f"Ville `{ville}` introuvable.", kind="danger"))
                data = await resp.json()
        e = await self._embed(ctx.guild.id if ctx.guild else None, title=f"Météo à {data['name']}")
        e.add_field(name="Température", value=f"{data['main']['temp']}°C", inline=True)
        e.add_field(name="Ressenti", value=f"{data['main']['feels_like']}°C", inline=True)
        e.add_field(name="Condition", value=data["weather"][0]["description"], inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="suggest", description="Faire une suggestion pour le serveur.")
    @app_commands.describe(texte="Votre suggestion")
    async def suggest(self, ctx: commands.Context, *, texte: str):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        channel = ctx.guild.get_channel(conf["suggest_channel"]) if conf and conf["suggest_channel"] else ctx.channel
        e = await self._embed(ctx.guild.id, title="Nouvelle suggestion", description=texte)
        e.set_footer(text=f"Proposé par {ctx.author}")
        msg = await channel.send(embed=e)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await self.bot.db.execute(
            "INSERT INTO suggestions (guild_id, user_id, message_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, ctx.author.id, msg.id, texte, now()),
        )
        if channel != ctx.channel:
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Suggestion envoyée", description=f"Suggestion envoyée dans {channel.mention} !", kind="success"))

    @commands.hybrid_command(name="report-bug", description="Signaler un bug du bot aux développeurs.", with_app_command=False)
    @app_commands.describe(texte="Description du bug")
    async def report_bug(self, ctx: commands.Context, *, texte: str):
        await self.bot.db.execute(
            "INSERT INTO bug_reports (guild_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id if ctx.guild else None, ctx.author.id, texte, now()),
        )
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Signalement enregistré", description="🐛 Merci, votre signalement a été enregistré.", kind="success"))

    @commands.hybrid_command(name="afk", description="Se mettre en mode AFK (absent).")
    @app_commands.describe(raison="La raison de votre absence (optionnel)")
    async def afk(self, ctx: commands.Context, *, raison: str = "Absent"):
        self.afk_users[ctx.author.id] = raison
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Mode AFK activé", description=f"😴 {ctx.author.mention} est maintenant AFK : {raison}"))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        guild_id = message.guild.id if message.guild else None
        if message.author.id in self.afk_users:
            del self.afk_users[message.author.id]
            try:
                await message.channel.send(embed=await self._embed(guild_id, title="De retour", description=f"👋 Bon retour {message.author.mention}, votre statut AFK a été retiré."), delete_after=5)
            except discord.HTTPException:
                pass
        for mention in message.mentions:
            if mention.id in self.afk_users:
                try:
                    await message.channel.send(embed=await self._embed(guild_id, title="Membre AFK", description=f"💤 {mention.display_name} est AFK : {self.afk_users[mention.id]}"), delete_after=5)
                except discord.HTTPException:
                    pass

    @commands.hybrid_command(name="roll", description="Lancer un dé (par défaut 1-100).")
    @app_commands.describe(max="Valeur maximale (optionnel, défaut 100)")
    async def roll(self, ctx: commands.Context, max: int = 100):
        import random
        result = random.randint(1, max)
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Lancer de dé", description=f"🎲 Vous avez obtenu : **{result}** (sur {max})"))

    @commands.hybrid_command(name="choose", description="Faire choisir le bot parmi plusieurs options.")
    @app_commands.describe(options="Options séparées par des virgules")
    async def choose(self, ctx: commands.Context, *, options: str):
        import random
        choices = [c.strip() for c in options.split(",") if c.strip()]
        if len(choices) < 2:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Options manquantes", description="Donnez au moins deux options séparées par des virgules.", kind="danger"))
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Choix du bot", description=f"🤔 Je choisis : **{random.choice(choices)}**"))

async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
