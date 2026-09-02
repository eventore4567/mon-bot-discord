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

from utils import access_matrix, embeds, helpers, checks, design_system, sentrix_panels as panels, stats_service
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
    def _panneau_avatar(nom: str, membre, url: str) -> "panels.Panneau":
        """La photo EST le contenu : elle occupe toute la largeur, pas une vignette.

        L'URL est deja verifiee par l'appelant (lue, pesee, type d'image reconnu).
        On la passe telle quelle plutot qu'en attachment:// : une couche de style
        intermediaire ne peut pas la desolidariser du panneau.
        """
        return panels.Panneau(
            titre=f"Avatar de {nom}",
            sous_titre=membre.mention,
            kind="info",
            image=url,
            pied=f"Identifiant : {membre.id}",
        )

    @staticmethod
    def _cible_a_notifier(ctx, membre):
        """Qui doit reellement etre notifie par une fiche.

        Memes gardes que _envoi_cible : on ne ping que si une cible a ete demandee
        (consulter sa propre fiche ne s'auto-notifie pas, un bot n'est jamais ping).
        Un panneau Components V2 refuse un content : c'est panels.envoyer qui place
        la mention dans le texte et ouvre allowed_mentions nommement.
        """
        auteur = getattr(ctx, "author", None)
        if (
            membre is not None
            and getattr(auteur, "id", None) != getattr(membre, "id", None)
            and not getattr(membre, "bot", False)
        ):
            return membre
        return None

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
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'La commande `{commande}` est introuvable ou vous n’avez pas la permission de la consulter.\nUtilisez `{prefix}help` pour afficher uniquement les commandes disponibles pour vous.')))
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
            return await panels.envoyer(ctx, panels.depuis_embed(e))

        e = build_help_home(self.bot, ctx.guild, prefix, is_staff)
        try:
            view = HelpView(self.bot, prefix, is_staff)
            await ctx.send(embed=e, view=view)
        except Exception:
            # L'aide textuelle reste disponible même si Discord refuse ponctuellement
            # un composant du menu. Le détail technique reste visible dans Railway.
            logger.exception("Impossible d'afficher le menu interactif de +help")
            await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="ping", description="Afficher la latence du bot.")
    async def ping(self, ctx: commands.Context):
        """État de la connexion, pas seulement un nombre.

        « Pong ! 42 ms » ne dit pas si 42 ms est bon, ni si la base répond. Les
        deux comptent quand on tape +ping : on cherche à savoir si le bot va bien.
        """
        latence = helpers.latence_ms(self.bot)
        if latence <= 120:
            etat, intention = "Excellente", "success"
        elif latence <= 300:
            etat, intention = "Correcte", "success"
        elif latence <= 600:
            etat, intention = "Dégradée", "warning"
        else:
            etat, intention = "Mauvaise", "danger"

        connexion = [
            panels.Ligne("Latence", f"**{latence} ms**", indice=f"Qualité : {etat.lower()}"),
            panels.Ligne("Passerelle Discord", "connectée" if self.bot.is_ready() else "en reconnexion"),
        ]
        if ctx.guild is not None and ctx.guild.shard_id is not None:
            connexion.append(panels.Ligne("Fragment", f"#{ctx.guild.shard_id}"))

        # Ce que la latence recouvre : une bonne latence sur deux serveurs ne dit
        # pas la meme chose qu'une bonne latence sur deux cents.
        serveurs = list(getattr(self.bot, "guilds", ()) or ())
        membres = sum(int(getattr(g, "member_count", 0) or 0) for g in serveurs)
        portee = [
            panels.Ligne("Serveurs", f"{len(serveurs):,}".replace(",", " ")),
            panels.Ligne("Membres couverts", f"{membres:,}".replace(",", " ")),
            panels.Ligne("Fragments", str(int(getattr(self.bot, "shard_count", None) or 1))),
        ]

        base = "opérationnelle"
        try:
            await self.bot.db.fetchone("SELECT 1")
        except Exception:
            base = "**injoignable**"
            intention = "danger"

        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — État",
                sous_titre=f"Latence **{latence} ms** · connexion {etat.lower()}.",
                kind=intention,
                sections=[
                    panels.Section("Connexion", connexion),
                    panels.Section("Services", [panels.Ligne("Base de données", base)]),
                    panels.Section("Portée", portee),
                ],
                pied="SentriX • État",
            ),
        )

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
        except Exception:
            # Rafraichir n'est qu'un bonus : le cache suffit a afficher la fiche.
            # Une coupure reseau ne doit pas faire echouer la commande entiere.
            pass
        fresh_user = None
        try:
            fresh_user = await self.bot.fetch_user(membre.id)
        except Exception:
            # Rafraichir n'est qu'un bonus : le cache suffit a afficher la fiche.
            # Une coupure reseau ne doit pas faire echouer la commande entiere.
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
                    return await panels.envoyer(
                        ctx,
                        self._panneau_avatar(display_name, membre, str(asset.url)),
                        mentionner=self._cible_a_notifier(ctx, membre),
                    )
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
            return await panels.envoyer(
                ctx,
                self._panneau_avatar(display_name, membre, verified_url),
                mentionner=self._cible_a_notifier(ctx, membre),
            )

        # Ne jamais remplacer silencieusement la vraie photo par l'avatar orange.
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre=f"Avatar de {display_name}",
                sous_titre=f"{membre.mention} — image indisponible pour l'instant.",
                kind="warning",
                sections=[
                    panels.Section(
                        "CE QUI S'EST PASSÉ",
                        lignes=[
                            panels.Ligne("Cause", "Discord n'a pas transmis l'avatar personnalisé"),
                            panels.Ligne("À faire", "réessayer dans quelques secondes"),
                        ],
                    )
                ],
                pied="Aucune image de remplacement n'est affichée volontairement.",
            ),
            mentionner=self._cible_a_notifier(ctx, membre),
        )

    @commands.hybrid_group(
        name="info",
        description="Afficher toutes les informations du serveur ou d'un rôle.",
        invoke_without_command=True,
    )
    async def info(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Informations', description='Utilisez `+info serveur` pour le serveur ou `+info role @Rôle` pour un rôle.\nCes commandes existent aussi en slash : `/info serveur` et `/info role`.')))

    @info.command(name="serveur", description="Afficher la fiche complète du serveur.")
    async def info_serveur(self, ctx: commands.Context):
        """Fiche serveur composée : présentation, structure, sécurité, capacités.

        L'ancienne version alignait dix champs de même poids. Ici l'ordre suit ce
        qu'on cherche vraiment : qui tient le serveur, comment il est bâti, ce qui
        le protège, et ce qui approche des limites Discord.
        """
        guild = ctx.guild
        if guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(None, title='Serveur requis', kind='danger')))

        total = guild.member_count or len(guild.members)
        bots = sum(1 for m in guild.members if m.bot)
        humains = max(0, total - bots)
        cree = int(guild.created_at.timestamp())

        proprietaire = guild.owner
        identite = [
            panels.Ligne(
                "Propriétaire",
                proprietaire.mention if proprietaire else f"<@{guild.owner_id}>",
            ),
            panels.Ligne("Identifiant", f"`{guild.id}`"),
            panels.Ligne("Création", f"<t:{cree}:D> · <t:{cree}:R>"),
        ]
        moi = guild.me
        if moi is not None and moi.joined_at is not None:
            identite.append(
                panels.Ligne("Arrivée de SentriX", f"<t:{int(moi.joined_at.timestamp())}:R>")
            )

        # --- POPULATION et STRUCTURE : des nombres, donc en colonnes -----------
        population = [
            panels.Ligne("Membres", stats_service.format_number(total)),
            panels.Ligne("Humains", stats_service.format_number(humains)),
            panels.Ligne("Bots", stats_service.format_number(bots)),
            panels.Ligne("Rôles", str(len(guild.roles))),
        ]

        structure = [
            panels.Ligne("Catégories", str(len(guild.categories))),
            panels.Ligne("Textuels", str(len(guild.text_channels))),
            panels.Ligne("Vocaux", str(len(guild.voice_channels))),
        ]
        if getattr(guild, "forums", None):
            structure.append(panels.Ligne("Forums", str(len(guild.forums))))
        if guild.stage_channels:
            structure.append(panels.Ligne("Conférences", str(len(guild.stage_channels))))
        if guild.threads:
            structure.append(panels.Ligne("Fils actifs", str(len(guild.threads))))

        # --- SÉCURITÉ : les réglages qui décident qui peut écrire --------------
        niveau, explication = NIVEAUX_VERIFICATION.get(
            guild.verification_level.name, (guild.verification_level.name, "")
        )
        securite = [
            panels.Ligne("Vérification", f"**{niveau}**", indice=explication),
            panels.Ligne(
                "Filtre des médias",
                FILTRES_CONTENU.get(
                    guild.explicit_content_filter.name, guild.explicit_content_filter.name
                ),
            ),
        ]
        if guild.mfa_level:
            securite.append(
                panels.Ligne("Double authentification", "**Exigée du staff**")
            )
        if guild.afk_channel is not None:
            securite.append(
                panels.Ligne(
                    "Salon inactif",
                    guild.afk_channel.mention,
                    indice=f"Après {(guild.afk_timeout or 0) // 60} minutes sans activité.",
                )
            )

        # --- CAPACITÉS : savoir avant de heurter une limite --------------------
        capacites = [
            panels.Ligne("Émojis", f"{len(guild.emojis)} / {guild.emoji_limit}"),
            panels.Ligne("Autocollants", f"{len(guild.stickers)} / {guild.sticker_limit}"),
            panels.Ligne("Fichiers", f"{guild.filesize_limit // (1024 * 1024)} Mo par envoi"),
            panels.Ligne("Boosts", _marge_boosts(guild).replace("\n", " — ")),
        ]

        sections = [
            panels.Section("Identité", identite),
            panels.Section("Population", population, aligne=True),
            panels.Section("Structure", structure, aligne=True),
            panels.Section("Sécurité", securite),
            panels.Section("Capacités", capacites, aligne=True),
        ]

        roles = [role.mention for role in reversed(guild.roles) if role != guild.default_role]
        sections.append(
            panels.Section(
                f"Rôles ({len(roles)})",
                texte=self._limited_list(roles, empty="Aucun rôle en dehors de @everyone"),
            )
        )

        panneau = panels.Panneau(
            titre="SentriX — Informations serveur",
            sous_titre=f"**{guild.name}**",
            kind="brand",
            vignette=guild.icon.url if guild.icon else None,
            sections=sections,
            pied=f"SentriX • Serveur · demandé par {ctx.author.display_name}",
        )
        await panels.envoyer(ctx, panneau)


    @commands.hybrid_command(name="userinfo", description="Afficher les informations d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def userinfo(self, ctx: commands.Context, membre: discord.Member = None):
        """Fiche membre composée : bannière, identité, serveur, pouvoirs, activité.

        L'ancienne version tenait dans un embed à cinq champs. Les informations y
        étaient toutes présentes mais de même poids : rien ne distinguait
        « compte créé il y a trois jours » d'un nom d'utilisateur. Chaque famille
        a maintenant sa section, son filet, et son ordre de lecture.
        """
        membre = membre or ctx.author
        maintenant = discord.utils.utcnow()
        cree = int(membre.created_at.timestamp())
        arrive = int(membre.joined_at.timestamp()) if membre.joined_at else None
        anciennete = (maintenant - membre.created_at).days
        plus_haut = membre.top_role if membre.top_role != ctx.guild.default_role else None

        # --- résumé : qui, depuis quand, avec quel rôle ----------------------
        resume = f"{membre.mention} · `{membre.id}`"
        if arrive:
            resume += f"\nMembre du serveur depuis <t:{arrive}:R>"
        if plus_haut is not None:
            resume += f", rôle le plus élevé {plus_haut.mention}"

        sections: list[panels.Section] = []

        # --- IDENTITÉ ---------------------------------------------------------
        identite = [
            panels.Ligne("Utilisateur", f"**{membre.name}**"),
            panels.Ligne("Identifiant", f"`{membre.id}`"),
            panels.Ligne("Création du compte", f"<t:{cree}:D> · <t:{cree}:R>"),
        ]
        if anciennete < 7:
            identite.append(
                panels.Ligne(
                    "Compte récent",
                    f"**{anciennete} jour{'s' if anciennete > 1 else ''}**",
                    indice="Les comptes très récents sont un signal de raid fréquent.",
                )
            )
        if membre.bot:
            identite.append(panels.Ligne("Nature", "Ce compte est un **bot**"))
        sections.append(panels.Section("Identité", identite))

        # --- SERVEUR ----------------------------------------------------------
        serveur: list[panels.Ligne] = []
        if arrive:
            serveur.append(panels.Ligne("Arrivée", f"<t:{arrive}:D> · <t:{arrive}:R>"))
        serveur.append(panels.Ligne("Rôle principal", plus_haut.mention if plus_haut else "Aucun"))
        if membre.premium_since:
            serveur.append(
                panels.Ligne("Boost", f"Depuis <t:{int(membre.premium_since.timestamp())}:R>")
            )
        if ctx.guild.owner_id == membre.id:
            serveur.append(panels.Ligne("Statut", "**Propriétaire du serveur**"))
        timeout = getattr(membre, "timed_out_until", None)
        if timeout and timeout > maintenant:
            serveur.append(
                panels.Ligne(
                    "Exclusion temporaire",
                    f"Jusqu'à <t:{int(timeout.timestamp())}:R>",
                    indice="Ce membre ne peut ni écrire ni parler pendant ce délai.",
                )
            )
        sections.append(panels.Section("Sur ce serveur", serveur))

        # --- ACTIVITÉ SENTRIX : uniquement de vraies valeurs ------------------
        # Aligné en chasse fixe : ce sont des nombres, ils gagnent à être en colonnes,
        # et aucune mention ne s'y perd.
        try:
            stats = await stats_service.get_member_statistics(self.bot, ctx.guild, membre)
        except Exception:
            stats = None
        if stats:
            activite = [
                panels.Ligne("Niveau", str(stats.get("current_level", 0))),
                panels.Ligne("Messages", stats_service.format_number(stats.get("message_count", 0))),
                panels.Ligne("Argent", stats_service.format_number(stats.get("total_money", 0))),
            ]
            if stats.get("is_ranked"):
                activite.append(panels.Ligne("Classement", f"#{stats.get('rank', 0)}"))
            sections.append(panels.Section("Activité SentriX", activite, aligne=True))

        # --- POUVOIRS : ce que la personne peut faire, pas 40 permissions ------
        perms = membre.guild_permissions
        notables = (
            ("administrator", "Administrateur"),
            ("manage_guild", "Gérer le serveur"),
            ("manage_roles", "Gérer les rôles"),
            ("manage_channels", "Gérer les salons"),
            ("ban_members", "Bannir"),
            ("kick_members", "Expulser"),
            ("moderate_members", "Exclure temporairement"),
            ("manage_messages", "Gérer les messages"),
        )
        if perms.administrator:
            pouvoirs = panels.Section(
                "Pouvoirs",
                [
                    panels.Ligne(
                        "Administrateur",
                        "**Toutes les permissions**",
                        indice="Ce rôle contourne tous les réglages de salon.",
                    )
                ],
            )
        else:
            actifs = [libelle for attribut, libelle in notables if getattr(perms, attribut, False)]
            pouvoirs = panels.Section(
                "Pouvoirs",
                [panels.Ligne("Modération", " · ".join(actifs) if actifs else "Aucune")],
            )
        sections.append(pouvoirs)

        # --- RÔLES -------------------------------------------------------------
        roles = [r.mention for r in reversed(membre.roles) if r != ctx.guild.default_role]
        sections.append(
            panels.Section(
                f"Rôles ({len(roles)})",
                texte=self._limited_list(roles, empty="Aucun rôle en dehors de @everyone"),
            )
        )

        panneau = panels.Panneau(
            titre=f"SentriX — Informations membre",
            sous_titre=resume,
            kind="info",
            vignette=membre.display_avatar.url,
            sections=sections,
            pied=f"SentriX • Informations · demandé par {ctx.author.display_name}",
        )
        # On ne notifie que si une cible a été demandée : consulter sa propre fiche
        # ne doit pas s'auto-notifier, et un bot n'est jamais mentionné.
        cible = membre if (membre.id != ctx.author.id and not membre.bot) else None
        await panels.envoyer(ctx, panneau, mentionner=cible)

    @info.command(name="role", description="Afficher la fiche complète d'un rôle.")
    @app_commands.describe(role="Le rôle à inspecter")
    async def info_role(self, ctx: commands.Context, role: discord.Role):
        """Fiche rôle composée. La question qu'on se pose devant un rôle est
        « SentriX peut-il l'attribuer ? » — elle a donc sa propre section, avant
        la liste des permissions."""
        cree = int(role.created_at.timestamp())
        moi = ctx.guild.me

        # --- HIÉRARCHIE : la cause de la plupart des échecs d'attribution ------
        rang: list[panels.Ligne] = [
            panels.Ligne("Position", f"**{role.position}** sur {len(ctx.guild.roles)}")
        ]
        if role == ctx.guild.default_role:
            rang.append(panels.Ligne("Portée", "Rôle par défaut — tout le monde l'a"))
        elif moi is None:
            rang.append(panels.Ligne("Gestion", "Hiérarchie inconnue"))
        elif not moi.guild_permissions.manage_roles:
            rang.append(
                panels.Ligne(
                    "SentriX", "**Ne peut pas le gérer**",
                    indice="Permission « Gérer les rôles » manquante.",
                )
            )
        elif role >= moi.top_role:
            rang.append(
                panels.Ligne(
                    "SentriX", "**Ne peut pas le gérer**",
                    indice=f"Ce rôle est au-dessus de {moi.top_role.name}. Remontez le rôle SentriX.",
                )
            )
        elif role.managed:
            rang.append(
                panels.Ligne(
                    "Gestion", "Géré par une intégration",
                    indice="Personne ne peut l'attribuer manuellement.",
                )
            )
        else:
            rang.append(panels.Ligne("SentriX", "Peut l'attribuer et le retirer"))

        # --- PARTICULARITÉS ----------------------------------------------------
        nature: list[panels.Ligne] = [
            panels.Ligne("Membres", str(len(role.members))),
            panels.Ligne("Couleur", str(role.color) if role.color.value else "Aucune"),
            panels.Ligne("Création", f"<t:{cree}:D> · <t:{cree}:R>"),
        ]
        traits = []
        if role.hoist:
            traits.append("Affiché séparément")
        if role.mentionable:
            traits.append("Mentionnable")
        if role.is_premium_subscriber():
            traits.append("Rôle des boosteurs")
        if role.is_bot_managed():
            traits.append("Rôle d'un bot")
        nature.append(panels.Ligne("Particularités", " · ".join(traits) if traits else "Aucune"))

        sections = [
            panels.Section("Hiérarchie", rang),
            panels.Section("Caractéristiques", nature),
        ]

        # --- PERMISSIONS : les sensibles d'abord, séparées du reste ------------
        actives = [nom for nom, activee in role.permissions if activee]
        sensibles = [n for n in actives if n in access_matrix.PERMISSIONS_SENSIBLES]
        ordinaires = [n for n in actives if n not in access_matrix.PERMISSIONS_SENSIBLES]

        if role.permissions.administrator:
            sections.append(
                panels.Section(
                    "Pouvoirs sensibles",
                    [
                        panels.Ligne(
                            "Administrateur", "**Toutes les permissions**",
                            indice="Contourne chaque autre permission et tous les réglages de salon.",
                        )
                    ],
                )
            )
        elif sensibles:
            sections.append(
                panels.Section(
                    f"Pouvoirs sensibles ({len(sensibles)})",
                    texte=self._limited_list(
                        [access_matrix.permission_label(n) for n in sensibles], empty="Aucun"
                    ),
                )
            )

        sections.append(
            panels.Section(
                f"Autres permissions ({len(ordinaires)})",
                texte=self._limited_list(
                    [access_matrix.permission_label(n) for n in ordinaires], empty="Aucune"
                ),
            )
        )

        panneau = panels.Panneau(
            titre="SentriX — Informations rôle",
            sous_titre=f"{role.mention} · `{role.id}`",
            kind="brand",
            vignette=role.icon.url if role.icon else None,
            sections=sections,
            pied=f"SentriX • Rôles · demandé par {ctx.author.display_name}",
        )
        await panels.envoyer(ctx, panneau)


    @commands.hybrid_command(name="channelinfo", description="Afficher les informations d'un salon.", with_app_command=False)
    @app_commands.describe(salon="Le salon visé (optionnel)")
    async def channelinfo(self, ctx: commands.Context, salon: discord.abc.GuildChannel = None):
        """Fiche salon composée. Ce qu'on cherche devant un salon, dans l'ordre :
        ce que c'est, qui peut le voir, et ce que SentriX peut y faire."""
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

        resume = f"{salon.mention} · `{salon.id}`\n**{libelle}**"
        if getattr(salon, "category", None) is not None:
            resume += f" dans **{salon.category.name}**"

        sections: list[panels.Section] = []

        sujet = str(getattr(salon, "topic", "") or "").strip()
        if sujet:
            sections.append(panels.Section("Sujet", texte=sujet[:900]))

        # --- RÉGLAGES : ce qui change le comportement du salon -----------------
        reglages: list[panels.Ligne] = [
            panels.Ligne("Type", libelle),
            panels.Ligne("Position", str(getattr(salon, "position", 0))),
            panels.Ligne("Création", f"<t:{cree}:D> · <t:{cree}:R>"),
        ]
        lenteur = getattr(salon, "slowmode_delay", 0) or 0
        if lenteur:
            reglages.append(
                panels.Ligne("Mode lent", f"**{lenteur} s**",
                             indice="Délai imposé entre deux messages d'un même membre.")
            )
        if getattr(salon, "nsfw", False):
            reglages.append(panels.Ligne("Contenu", "Marqué **NSFW**"))
        if isinstance(salon, discord.VoiceChannel):
            reglages.append(panels.Ligne("Qualité", f"{salon.bitrate // 1000} kbps"))
            reglages.append(
                panels.Ligne("Places", str(salon.user_limit) if salon.user_limit else "Illimitées")
            )
            reglages.append(panels.Ligne("Connectés", str(len(salon.members))))
        if isinstance(salon, discord.TextChannel):
            reglages.append(panels.Ligne("Fils actifs", str(len(salon.threads))))
        sections.append(panels.Section("Réglages", reglages))

        # --- ACCÈS : qui voit ce salon ----------------------------------------
        acces: list[panels.Ligne] = []
        try:
            everyone = salon.overwrites_for(ctx.guild.default_role)
            if everyone.view_channel is False:
                acces.append(
                    panels.Ligne("Visibilité", "**Salon privé**",
                                 indice="Le rôle par défaut ne voit pas ce salon.")
                )
            else:
                acces.append(panels.Ligne("Visibilité", "Visible par tout le monde"))
            roles_autorises = [
                cible.mention for cible, perms in salon.overwrites.items()
                if isinstance(cible, discord.Role)
                and cible != ctx.guild.default_role
                and perms.view_channel is True
            ]
            if roles_autorises:
                acces.append(panels.Ligne("Accès explicite", ", ".join(roles_autorises[:5])))
            acces.append(panels.Ligne("Règles personnalisées", str(len(salon.overwrites))))
        except Exception:
            logger.exception("channelinfo : lecture des permissions impossible.")
            acces.append(panels.Ligne("Permissions", "Illisibles"))
        sections.append(panels.Section("Accès", acces))

        # --- CE QUE SENTRIX NE PEUT PAS : la section qui débloque vraiment -----
        moi = ctx.guild.me
        intention = "info"
        if moi is not None:
            perms = salon.permissions_for(moi)
            manques = [
                libelle_perm for attribut, libelle_perm in (
                    ("view_channel", "Voir le salon"),
                    ("send_messages", "Envoyer des messages"),
                    ("embed_links", "Intégrer des liens"),
                    ("attach_files", "Joindre des fichiers"),
                    ("manage_messages", "Gérer les messages"),
                ) if not getattr(perms, attribut, False)
            ]
            if manques:
                intention = "warning"
                sections.append(
                    panels.Section(
                        "SentriX ne peut pas",
                        [panels.Ligne("Permissions manquantes", " · ".join(manques),
                                      indice="Ouvrez les permissions du salon pour le rôle SentriX.")],
                    )
                )

        panneau = panels.Panneau(
            titre="SentriX — Informations salon",
            sous_titre=resume,
            kind=intention,
            sections=sections,
            pied=f"SentriX • Salons · demandé par {ctx.author.display_name}",
        )
        await panels.envoyer(ctx, panneau)

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
        await panels.envoyer(ctx, panels.depuis_embed(e))

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
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(None, title='Commande indisponible', description='Cette commande doit être utilisée sur un serveur.', kind='danger')))
        if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Permission manquante', description='Le bot doit avoir la permission **Gérer les emojis et stickers**.', kind='danger')))

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
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Nom invalide', description='Le nom doit contenir 2 à 32 caractères : lettres, chiffres ou tiret bas.\nExemple : +addemoji danse <a:emoji:identifiant>', kind='danger')))

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
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Image refusée', description=str(exc), kind='danger')))
        except asyncio.TimeoutError:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Téléchargement impossible', description="Le serveur de l'image met trop de temps à répondre.", kind='danger')))
        except discord.Forbidden:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Création refusée', description='Discord refuse la création. Vérifiez la permission et la position du rôle du bot.', kind='danger')))
        except (aiohttp.ClientError, discord.HTTPException) as exc:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Création impossible', description=f"Discord ou le serveur de l'image a refusé la demande : {exc}", kind='danger')))

        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Emoji ajouté', description=f"{emoji} a été créé sous le nom `:{emoji.name}:`.\nType : **{('animé' if emoji.animated else 'statique')}**.", kind='success')))

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
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(None, title='Commande indisponible', description='Cette commande doit être utilisée sur un serveur.', kind='danger')))
        if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Permission manquante', description='Le bot doit avoir la permission **Gérer les emojis et stickers**.', kind='danger')))

        value = emoji.strip()
        pasted = re.fullmatch(r"<a?:([A-Za-z0-9_]{2,32}):([0-9]+)>", value)
        target = None
        if pasted:
            target = ctx.guild.get_emoji(int(pasted.group(2)))
        else:
            name = value.strip(":").lower()
            target = discord.utils.find(lambda item: item.name.lower() == name, ctx.guild.emojis)

        if target is None:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Emoji introuvable', description='Collez un emoji de ce serveur ou indiquez exactement son nom.', kind='danger')))

        emoji_name = target.name
        try:
            await target.delete(reason=f"Emoji supprimé par {ctx.author} avec +deleteemoji")
        except discord.Forbidden:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Suppression refusée', description="Le bot n'a pas la permission de supprimer cet emoji.", kind='danger')))
        except discord.HTTPException as exc:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Suppression impossible', description=f'Discord a refusé la demande : {exc}', kind='danger')))

        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Emoji supprimé', description=f"L'emoji `:{emoji_name}:` a été supprimé du serveur.", kind='success')))

    @commands.hybrid_command(name="emoji-list", description="Lister les emojis du serveur.", with_app_command=False)
    async def emoji_list(self, ctx: commands.Context):
        """Les émojis du serveur, avec le quota restant."""
        emojis = list(ctx.guild.emojis)
        if not emojis:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Émojis",
                    sous_titre="Ce serveur n'a aucun émoji personnalisé.",
                    kind="info",
                    sections=[
                        panels.Section(
                            "En ajouter",
                            [panels.Ligne("`+addemoji <nom> <image>`", "Ajoute un émoji au serveur")],
                        )
                    ],
                    pied="SentriX • Émojis",
                ),
            )

        animes = [e for e in emojis if e.animated]
        fixes = [e for e in emojis if not e.animated]
        sections = [
            panels.Section("Émojis", texte=" ".join(str(e) for e in fixes)[:1400] or "Aucun")
        ]
        if animes:
            sections.append(
                panels.Section("Animés", texte=" ".join(str(e) for e in animes)[:1400])
            )
        # Le quota manquait : on decouvrait la limite en essayant d'en ajouter un.
        sections.append(
            panels.Section(
                "Quota",
                [
                    panels.Ligne("Utilisés", f"{len(emojis)} sur {ctx.guild.emoji_limit}"),
                    panels.Ligne("Restants", str(max(0, ctx.guild.emoji_limit - len(emojis)))),
                ],
                aligne=True,
            )
        )
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Émojis",
                sous_titre=f"**{len(emojis)}** émoji(s) sur ce serveur, dont **{len(animes)}** animé(s).",
                kind="info",
                sections=sections,
                pied="SentriX • Émojis",
            ),
        )

    @commands.hybrid_command(name="poll", description="Créer un sondage rapide (réactions 👍/👎).")
    @app_commands.describe(question="La question du sondage")
    async def poll(self, ctx: commands.Context, *, question: str):
        e = await self._embed(ctx.guild.id if ctx.guild else None, title="Sondage", description=question)
        e.set_footer(text=f"Créé par {ctx.author}")
        msg = await panels.envoyer(ctx, panels.depuis_embed(e))
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    @commands.hybrid_command(name="remind", description="Définir un rappel personnel.")
    @app_commands.describe(duree="Durée (ex: 10m, 2h, 1j)", texte="Le texte du rappel")
    async def remind(self, ctx: commands.Context, duree: str, *, texte: str):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Durée invalide', description='Exemple : `10m`, `2h`, `1j`.', kind='danger')))
        trigger_at = now() + seconds
        await self.bot.db.execute(
            "INSERT INTO reminders (user_id, channel_id, guild_id, text, trigger_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.author.id, ctx.channel.id, ctx.guild.id if ctx.guild else None, texte, trigger_at, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Rappel défini', description=f'⏰ Rappel défini dans {helpers.format_duration(seconds)}.', kind='success')))

    @commands.hybrid_command(name="reminder-list", description="Lister vos rappels en cours.", with_app_command=False)
    async def reminder_list(self, ctx: commands.Context):
        """Vos rappels, avec leur identifiant et comment les annuler."""
        rows = await self.bot.db.fetchall(
            "SELECT * FROM reminders WHERE user_id = ? ORDER BY trigger_at ASC", (ctx.author.id,)
        )
        if not rows:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Rappels",
                    sous_titre="Vous n'avez aucun rappel en attente.",
                    kind="info",
                    sections=[
                        panels.Section(
                            "En créer un",
                            [panels.Ligne("`+remind 2h Sortir les poubelles`",
                                          "SentriX vous écrira au bon moment")],
                        )
                    ],
                    pied="SentriX • Rappels",
                ),
            )

        prochains = [
            panels.Ligne(
                f"#{r['id']}",
                f"<t:{r['trigger_at']}:R> · {str(r['text'])[:60]}",
            )
            for r in rows[:12]
        ]
        sections = [panels.Section(f"Rappels en attente ({len(rows)})", prochains)]
        if len(rows) > 12:
            sections.append(
                panels.Section("Non affichés", [panels.Ligne("Autres rappels", str(len(rows) - 12))])
            )
        sections.append(
            panels.Section(
                "Gérer",
                [panels.Ligne("`+reminder-cancel <numéro>`", "Annule le rappel correspondant")],
            )
        )
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Rappels",
                sous_titre=f"**{len(rows)}** rappel(s) en attente, le prochain <t:{rows[0]['trigger_at']}:R>.",
                kind="info",
                sections=sections,
                pied="SentriX • Rappels",
            ),
        )

    @commands.hybrid_command(name="reminder-cancel", description="Annuler un rappel.", with_app_command=False)
    @app_commands.describe(id="L'identifiant du rappel (voir /reminder-list)")
    async def reminder_cancel(self, ctx: commands.Context, id: int):
        row = await self.bot.db.fetchone("SELECT * FROM reminders WHERE id = ? AND user_id = ?", (id, ctx.author.id))
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Rappel introuvable', kind='danger')))
        await self.bot.db.execute("DELETE FROM reminders WHERE id = ?", (id,))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Rappel annulé', kind='success')))

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
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="translate", description="Traduire un texte vers une autre langue.")
    @app_commands.describe(langue="Code langue cible (ex: en, es, de)", texte="Le texte à traduire")
    async def translate(self, ctx: commands.Context, langue: str, *, texte: str):
        try:
            from deep_translator import GoogleTranslator
            result = GoogleTranslator(source="auto", target=langue).translate(texte)
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title=f'Traduction ({langue})', description=result)))
        except Exception:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Traduction échouée', description='Vérifiez le code de langue.', kind='danger')))

    @commands.hybrid_command(name="weather", description="Afficher la météo d'une ville.")
    @app_commands.describe(ville="Le nom de la ville")
    async def weather(self, ctx: commands.Context, *, ville: str):
        import config
        if not config.WEATHER_API_KEY:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Météo indisponible', description="Aucune clé météo n'est configurée sur ce bot.", kind='danger')))
        import aiohttp
        url = f"https://api.openweathermap.org/data/2.5/weather?q={ville}&appid={config.WEATHER_API_KEY}&units=metric&lang=fr"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Ville introuvable', description=f'Ville `{ville}` introuvable.', kind='danger')))
                data = await resp.json()
        e = await self._embed(ctx.guild.id if ctx.guild else None, title=f"Météo à {data['name']}")
        e.add_field(name="Température", value=f"{data['main']['temp']}°C", inline=True)
        e.add_field(name="Ressenti", value=f"{data['main']['feels_like']}°C", inline=True)
        e.add_field(name="Condition", value=data["weather"][0]["description"], inline=True)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="suggest", description="Faire une suggestion pour le serveur.")
    @app_commands.describe(texte="Votre suggestion")
    async def suggest(self, ctx: commands.Context, *, texte: str):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        channel = ctx.guild.get_channel(conf["suggest_channel"]) if conf and conf["suggest_channel"] else ctx.channel
        e = await self._embed(ctx.guild.id, title="Nouvelle suggestion", description=texte)
        e.set_footer(text=f"Proposé par {ctx.author}")
        msg = await panels.envoyer(channel, panels.depuis_embed(e))
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await self.bot.db.execute(
            "INSERT INTO suggestions (guild_id, user_id, message_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, ctx.author.id, msg.id, texte, now()),
        )
        if channel != ctx.channel:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Suggestion envoyée', description=f'Suggestion envoyée dans {channel.mention} !', kind='success')))

    @commands.hybrid_command(name="report-bug", description="Signaler un bug du bot aux développeurs.", with_app_command=False)
    @app_commands.describe(texte="Description du bug")
    async def report_bug(self, ctx: commands.Context, *, texte: str):
        await self.bot.db.execute(
            "INSERT INTO bug_reports (guild_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id if ctx.guild else None, ctx.author.id, texte, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Signalement enregistré', description='🐛 Merci, votre signalement a été enregistré.', kind='success')))

    @commands.hybrid_command(name="afk", description="Se mettre en mode AFK (absent).")
    @app_commands.describe(raison="La raison de votre absence (optionnel)")
    async def afk(self, ctx: commands.Context, *, raison: str = "Absent"):
        self.afk_users[ctx.author.id] = raison
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Mode AFK activé', description=f'😴 {ctx.author.mention} est maintenant AFK : {raison}')))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        guild_id = message.guild.id if message.guild else None
        if message.author.id in self.afk_users:
            del self.afk_users[message.author.id]
            try:
                await panels.envoyer(message.channel, panels.depuis_embed(await self._embed(guild_id, title='De retour', description=f'👋 Bon retour {message.author.mention}, votre statut AFK a été retiré.')))
            except discord.HTTPException:
                pass
        for mention in message.mentions:
            if mention.id in self.afk_users:
                try:
                    await panels.envoyer(message.channel, panels.depuis_embed(await self._embed(guild_id, title='Membre AFK', description=f'💤 {mention.display_name} est AFK : {self.afk_users[mention.id]}')))
                except discord.HTTPException:
                    pass

    @commands.hybrid_command(name="roll", description="Lancer un dé (par défaut 1-100).")
    @app_commands.describe(max="Valeur maximale (optionnel, défaut 100)")
    async def roll(self, ctx: commands.Context, max: int = 100):
        import random
        result = random.randint(1, max)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Lancer de dé', description=f'🎲 Vous avez obtenu : **{result}** (sur {max})')))

    @commands.hybrid_command(name="choose", description="Faire choisir le bot parmi plusieurs options.")
    @app_commands.describe(options="Options séparées par des virgules")
    async def choose(self, ctx: commands.Context, *, options: str):
        import random
        choices = [c.strip() for c in options.split(",") if c.strip()]
        if len(choices) < 2:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Options manquantes', description='Donnez au moins deux options séparées par des virgules.', kind='danger')))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Choix du bot', description=f'🤔 Je choisis : **{random.choice(choices)}**')))

async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
